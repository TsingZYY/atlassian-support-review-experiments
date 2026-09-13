"""Independent Counter/log-odds reconstruction and complete evidence-index audit.

Does not import experiment.py. The auditor saw the protocol and implementation
interface before writing this checker; this is numerical replication, not blind
review. All independently derived quantities are built before result comparison.
"""
from collections import Counter, defaultdict
from pathlib import Path
from datetime import datetime, timezone
import csv
import hashlib
import json
import math
import os
import re
import subprocess
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"
UNKNOWN = "UNKNOWN_NO_CUSTOMER_VERBATIM_OR_SENTIMENT_LABEL"


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_json(name):
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def key(text):
    return text.strip().casefold()


def hashed(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def rating(ticket):
    raw = ticket["Customer Satisfaction Rating"]
    if raw.strip() == "":
        return None
    value = float(raw)
    assert value in [1, 2, 3, 4, 5]
    return int(value)


def state(value):
    return {None: "UNOBSERVED", 1: "LOW_REPORTED", 2: "LOW_REPORTED",
            3: "MIDDLE_REPORTED", 4: "HIGH_REPORTED", 5: "HIGH_REPORTED"}[value]


def route(value):
    return "FEEDBACK_NOT_OBSERVED" if value is None else "REVIEW_REPORTED_LOW_CSAT" if value in (1, 2) else "KEEP_OBSERVED_SCORE"


def near(observed, expected, tolerance=1e-11):
    assert math.isfinite(float(observed)) and math.isfinite(float(expected))
    assert abs(float(observed) - float(expected)) <= tolerance, (observed, expected)


def rank_auc(labels, probabilities):
    # Mann-Whitney statistic with average ranks for ties.
    ordered = sorted(zip(probabilities, labels))
    positives = sum(labels)
    negatives = len(labels) - positives
    if not positives or not negatives:
        return None
    rank_sum = 0.0
    start = 0
    while start < len(ordered):
        end = start + 1
        while end < len(ordered) and ordered[end][0] == ordered[start][0]:
            end += 1
        average_rank = (start + 1 + end) / 2
        rank_sum += average_rank * sum(label for _, label in ordered[start:end])
        start = end
    return (rank_sum - positives * (positives + 1) / 2) / (positives * negatives)


def measures(labels, probabilities):
    count = len(labels)
    clipped = [max(1e-12, min(1 - 1e-12, p)) for p in probabilities]
    return {
        "n": count,
        "low_csat_n": sum(labels),
        "brier": math.fsum((y-p)**2 for y, p in zip(labels, probabilities)) / count,
        "auc": rank_auc(labels, probabilities),
        "log_loss": -math.fsum(y*math.log(p)+(1-y)*math.log1p(-p) for y, p in zip(labels, clipped)) / count,
        "accuracy_at_05": sum((p >= .5) == bool(y) for y, p in zip(labels, probabilities)) / count,
        "predicted_low_at_05": sum(p >= .5 for p in probabilities),
    }


def main():
    p = read_json("protocol.json")
    customers = read_csv(DATA / "customers.csv")
    tickets = read_csv(DATA / "customer_support_tickets.csv")
    lookup = {key(c["Customer Email"]): c for c in customers}
    assert len(lookup) == len(customers)
    bad_ids = set()
    for ticket in tickets:
        customer = lookup[key(ticket["Customer Email"])]
        if any(key(ticket[f]) != key(customer[f]) for f in ("Customer Name", "Customer Age", "Customer Gender")):
            bad_ids.add(customer["Customer ID"])
    eligible = []
    for ticket in tickets:
        cid = lookup[key(ticket["Customer Email"])]["Customer ID"]
        if cid not in bad_ids and ticket["Ticket Status"] == "Closed" and rating(ticket) is not None and ticket[p["text_field"]]:
            eligible.append((cid, ticket))
    assert len(set(cid for cid, _ in eligible)) == len(eligible)
    eligible.sort(key=lambda row: hashed(p["split_salt"] + "|" + row[0]))
    train_size = int(p["training_fraction"] * len(eligible))
    train, test = eligible[:train_size], eligible[train_size:]
    assert set(cid for cid, _ in train).isdisjoint(cid for cid, _ in test)
    words = lambda ticket: re.findall(p["token_regex"], ticket[p["text_field"]].lower())
    document_frequency = Counter()
    for _, ticket in train:
        document_frequency.update(set(words(ticket)))
    vocabulary = sorted(word for word, frequency in document_frequency.items() if frequency >= p["minimum_training_document_frequency"])
    word_set = set(vocabulary)
    class_document_count = Counter()
    class_word_count = {0: Counter(), 1: Counter()}
    for _, ticket in train:
        label = int(rating(ticket) in p["low_csat_scores"])
        class_document_count[label] += 1
        class_word_count[label].update(w for w in words(ticket) if w in word_set)
    priors = [class_document_count[c] / len(train) for c in (0, 1)]
    alpha = p["smoothing_alpha"]
    log_probabilities = []
    for c in (0, 1):
        denominator = sum(class_word_count[c].values()) + alpha * len(vocabulary)
        log_probabilities.append([math.log((class_word_count[c][w] + alpha) / denominator) for w in vocabulary])
    log_ratios = {w: log_probabilities[1][i] - log_probabilities[0][i] for i, w in enumerate(vocabulary)}
    probabilities = []
    test_labels = []
    unknown_tokens = token_count = empty_known_documents = 0
    for _, ticket in test:
        tokens = words(ticket)
        token_count += len(tokens)
        unknown_tokens += sum(word not in word_set for word in tokens)
        known = Counter(word for word in tokens if word in word_set)
        empty_known_documents += int(not known)
        log_odds = math.log(priors[1] / priors[0]) + math.fsum(count * log_ratios[w] for w, count in known.items())
        if log_odds >= 0:
            probability = 1 / (1 + math.exp(-log_odds))
        else:
            odds = math.exp(log_odds)
            probability = odds / (1 + odds)
        probabilities.append(probability)
        test_labels.append(int(rating(ticket) in p["low_csat_scores"]))
    baseline = [priors[1]] * len(test)
    differences = [(q-y)**2 - (r-y)**2 for q, r, y in zip(baseline, probabilities, test_labels)]
    independent_metrics = {
        "baseline": measures(test_labels, baseline),
        "resolution_bag_of_words": measures(test_labels, probabilities),
        "brier_gain_baseline_minus_text": math.fsum(differences) / len(test),
    }
    # Replay specified customer bootstrap one repetition at a time. The RNG and
    # percentile convention match the protocol; this is a numerical replay,
    # not an independent uncertainty-estimation method.
    rng = np.random.default_rng(p["bootstrap_seed"])
    bootstrap = []
    for _ in range(p["bootstrap_repetitions"]):
        positions = rng.integers(0, len(test), size=len(test))
        bootstrap.append(math.fsum(differences[i] for i in positions) / len(test))
    interval = np.quantile(bootstrap, [.025, .975]).tolist()
    independent_metrics["paired_bootstrap_95"] = interval

    # Only now compare independently calculated numbers with published outputs.
    results = read_json("results.json")
    target = results["text_experiment"]
    for field, expected in {
        "training_n": len(train), "test_n": len(test),
        "identity_conflict_customers": len(bad_ids), "eligible_closed_n": len(eligible),
        "training_low_csat_n": class_document_count[1], "test_low_csat_n": sum(test_labels),
        "vocabulary_size": len(vocabulary), "test_unknown_token_count": unknown_tokens,
        "test_token_count": token_count, "test_documents_with_no_known_tokens": empty_known_documents,
    }.items():
        assert target[field] == expected, (field, target[field], expected)
    for model_name in ("baseline", "resolution_bag_of_words"):
        for metric, expected in independent_metrics[model_name].items():
            if metric != "auc":
                near(target[model_name][metric], expected)
    near(target["brier_gain_baseline_minus_text"], independent_metrics["brier_gain_baseline_minus_text"])
    for observed, expected in zip(target["paired_bootstrap_95"], interval):
        near(observed, expected)
    assert target["text_csat_increment_supported"] == (independent_metrics["brier_gain_baseline_minus_text"] > 0 and interval[0] > 0)
    assert target["customer_disjoint"] is True
    assert target["semantic_sentiment_accuracy"] is None
    assert target["valid_for_unclosed_tickets"] is False
    assert target["label_is_observed_csat_not_sentiment"] is True
    model = read_json("text_model.json")
    assert model["vocabulary"] == vocabulary
    assert model["training_document_frequency"] == {w: document_frequency[w] for w in vocabulary}
    near(model["alpha"], alpha)
    parameter_differences = []
    for observed, expected in zip(model["class_prior"], priors):
        near(observed, expected)
    for actual_row, expected_row in zip(model["word_log_probability"], log_probabilities):
        assert len(actual_row) == len(expected_row)
        for observed, expected in zip(actual_row, expected_row):
            parameter_differences.append(abs(observed - expected))
            near(observed, expected)
    split_rows = read_csv(HERE / "text_split.csv")
    expected_splits = [{"customer_id": cid, "ticket_id": ticket["Ticket ID"], "split": group}
                       for group, rows in (("train", train), ("test", test)) for cid, ticket in rows]
    assert split_rows == expected_splits
    predictions = read_csv(HERE / "text_test_predictions.csv")
    assert len(predictions) == len(test)
    probability_differences = []
    for i, (row, (cid, ticket)) in enumerate(zip(predictions, test)):
        assert row["ticket_id"] == ticket["Ticket ID"] and row["customer_id"] == cid
        assert int(row["observed_rating"]) == rating(ticket)
        assert int(row["low_csat"]) == test_labels[i]
        near(row["baseline_probability"], baseline[i])
        near(row["text_probability"], probabilities[i])
        near(row["paired_brier_gain"], differences[i])
        probability_differences.append(abs(float(row["text_probability"]) - probabilities[i]))
    saved_probabilities = [float(row["text_probability"]) for row in predictions]
    near(target["resolution_bag_of_words"]["auc"], rank_auc(test_labels, saved_probabilities))
    near(target["baseline"]["auc"], independent_metrics["baseline"]["auc"])
    # AUC is discontinuous at tied probabilities. Distinct float summation
    # orders can move mathematically tied scores by about 1e-16. Enumerate and
    # expose every affected positive/negative pair instead of hiding the issue
    # behind a widened global metric tolerance.
    auc_pairs = []
    for i, positive in enumerate(test_labels):
        if positive != 1:
            continue
        for j, negative in enumerate(test_labels):
            if negative != 0:
                continue
            saved_win = (saved_probabilities[i] > saved_probabilities[j]) + .5 * (saved_probabilities[i] == saved_probabilities[j])
            independent_win = (probabilities[i] > probabilities[j]) + .5 * (probabilities[i] == probabilities[j])
            if saved_win != independent_win:
                assert abs(saved_probabilities[i] - saved_probabilities[j]) <= 2 * max(probability_differences)
                auc_pairs.append({"positive_ticket_id": test[i][1]["Ticket ID"],
                                  "negative_ticket_id": test[j][1]["Ticket ID"],
                                  "saved_probabilities": [saved_probabilities[i], saved_probabilities[j]],
                                  "independent_probabilities": [probabilities[i], probabilities[j]],
                                  "saved_minus_independent_pair_credit": saved_win - independent_win})
    n_pairs = sum(test_labels) * (len(test_labels) - sum(test_labels))
    near(target["resolution_bag_of_words"]["auc"] - independent_metrics["resolution_bag_of_words"]["auc"],
         math.fsum(pair["saved_minus_independent_pair_credit"] for pair in auc_pairs) / n_pairs)

    index = read_csv(HERE / "all_ticket_evidence_index.csv")
    assert len(index) == len(tickets)
    assert len({row["ticket_id"] for row in index}) == len(tickets)
    state_counts = Counter()
    source_map = {}
    for line, (row, ticket) in enumerate(zip(index, tickets), 2):
        value = rating(ticket)
        evidence_state = state(value)
        state_counts[evidence_state] += 1
        source_map[ticket["Ticket ID"]] = (line, ticket)
        expected = {"ticket_id": ticket["Ticket ID"], "source_row": str(line),
                    "rating": "" if value is None else str(value), "csat_evidence_state": evidence_state,
                    "customer_sentiment": UNKNOWN, "review_route": route(value)}
        assert row == expected, (line, row, expected)
    assert results["evidence_state_counts"] == dict(state_counts)
    near(results["rating_coverage"], sum(rating(t) is not None for t in tickets) / len(tickets))
    assert results["all_tickets_customer_sentiment_unknown"] == len(tickets)
    for field in ("customer_sentiment_accuracy", "real_resolution_rate", "measured_profit_effect"):
        assert results[field] is None
    assert results["new_synthetic_observations"] == 0
    assert results["dataset_scope"] == "competition_csv_only"
    selected_ids = []
    for group in p["audit_groups"]:
        candidates = [ticket["Ticket ID"] for ticket in tickets if state(rating(ticket)) == group]
        selected_ids.extend(sorted(candidates, key=lambda tid: hashed(p["audit_salt"] + "|" + tid))[:p["audit_per_group"]])
    cards = read_json("evidence_cards_20.json")
    assert len(cards) == len(set(selected_ids)) == 20
    assert [card["ticket_id"] for card in cards] == selected_ids
    assert results["source_audit_cases"] == len(cards)
    review_input = read_csv(HERE / "text_review_input_20.csv")
    assert len(review_input) == len(cards)
    for card, review in zip(cards, review_input):
        line, ticket = source_map[card["ticket_id"]]
        value = rating(ticket)
        assert card["source"] == {"file": "data/customer_support_tickets.csv", "record_row": line}
        assert card["ticket_context"] == {field: ticket[field] for field in
               ("Product Purchased", "Ticket Type", "Ticket Subject", "Ticket Priority", "Ticket Channel", "Ticket Status")}
        assert card["csat"] == {"score": value, "evidence_state": state(value), "source_field": "Customer Satisfaction Rating"}
        assert card["customer_sentiment"] == UNKNOWN
        assert card["resolution_record"] == (ticket["Resolution"] or None)
        assert card["resolution_is_verified_customer_verbatim"] is False
        assert card["review_route"] == route(value)
        expected_step = "核对客户原始反馈及处理经过" if value in (1, 2) else "保留缺失；需直接反馈后再判断" if value is None else "保留评分及来源，不推断情绪或挽回效果"
        assert card["suggested_next_step"] == expected_step
        assert card["measured_recovery_outcome"] is None and card["measured_profit_effect"] is None
        assert review == {"ticket_id": ticket["Ticket ID"], "source_row": str(line),
                          "ticket_type": ticket["Ticket Type"], "subject": ticket["Ticket Subject"], "resolution": ticket["Resolution"]}

    resolutions = [t["Resolution"] for t in tickets if t["Resolution"]]
    word_counts = [len(re.findall("[A-Za-z]+", text)) for text in resolutions]
    profile = results["profile"]
    for field, expected in {
        "ticket_count": len(tickets), "ticket_fields": list(tickets[0]),
        "subject_counts": dict(Counter(t["Ticket Subject"] for t in tickets)),
        "resolution_nonempty": len(resolutions), "resolution_unique": len(set(resolutions)),
        "resolution_digit_normalized_unique": len({re.sub(r"\d+", "<NUMBER>", text) for text in resolutions}),
        "resolution_word_count_min": min(word_counts), "resolution_word_count_max": max(word_counts),
        "rating_counts": dict(Counter(str(rating(t)) for t in tickets)),
    }.items():
        assert profile[field] == expected, field
    near(profile["resolution_word_count_mean"], math.fsum(word_counts) / len(word_counts))
    assert profile["customer_verbatim_field_available"] is False
    assert profile["sentiment_annotation_field_available"] is False
    by_status = defaultdict(list)
    for ticket in tickets:
        by_status[ticket["Ticket Status"]].append(ticket)
    expected_coverage = [{"status": status, "tickets": len(rows),
                          "ratings": sum(rating(t) is not None for t in rows),
                          "resolutions": sum(bool(t["Resolution"]) for t in rows)}
                         for status, rows in sorted(by_status.items())]
    assert profile["status_coverage"] == expected_coverage
    lock = read_json("execution_lock.json")
    for field, directory in (("source_sha256", DATA), ("protocol_code_sha256", HERE)):
        actual = {name: sha(directory / name) for name in lock[field]}
        assert actual == lock[field] == results[field]

    # These are actual CLI executions, not direct calls into the main module.
    cli_checks = []
    for ticket_id, expected_state, expected_route, example_name in (
        ("5919", "LOW_REPORTED", "REVIEW_REPORTED_LOW_CSAT", "example_low_5919.json"),
        ("6863", "UNOBSERVED", "FEEDBACK_NOT_OBSERVED", "example_unknown_6863.json"),
    ):
        run = subprocess.run([sys.executable, str(HERE / "experiment.py"), "--ticket-id", ticket_id],
                             check=True, capture_output=True, text=True, encoding="utf-8",
                             env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        actual_card = json.loads(run.stdout)
        expected_card = next(card for card in cards if card["ticket_id"] == ticket_id)
        assert actual_card == expected_card
        assert actual_card["csat"]["evidence_state"] == expected_state
        assert actual_card["review_route"] == expected_route
        assert actual_card["customer_sentiment"] == UNKNOWN
        (HERE / example_name).write_text(json.dumps(actual_card, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        cli_checks.append({"ticket_id": ticket_id, "evidence_state": expected_state,
                           "review_route": expected_route, "matches_audited_card": True})
    review_annotations = read_json("text_review_annotations.json")
    annotations = review_annotations["annotations"]
    assert len(annotations) == len(review_input)
    assert [row["ticket_id"] for row in annotations] == [row["ticket_id"] for row in review_input]
    semantic_fields = ("identifiable_problem_detail", "concrete_resolution_action_or_outcome", "explicit_affect_expression")
    for annotation, source in zip(annotations, review_input):
        available = bool(source["resolution"].strip())
        assert annotation["text_available"] == available
        for field in semantic_fields:
            assert (annotation[field] in (True, False)) if available else (annotation[field] == "unclear")
    semantic_counts = {
        "cases": len(annotations), "text_available": sum(row["text_available"] for row in annotations),
        "text_missing": sum(not row["text_available"] for row in annotations),
        **{field + "_true_among_available": sum(row["text_available"] and row[field] is True for row in annotations) for field in semantic_fields},
        "not_assessable_missing_for_each_semantic_item": sum(not row["text_available"] for row in annotations),
    }
    assert review_annotations["counts"] == semantic_counts

    audit = {
        "status": "PASS", "executed_at": datetime.now(timezone.utc).isoformat(),
        "audit_method": "Independent standard-library Counter and scalar log-odds NB; rank-based AUC; complete per-row source reconstruction",
        "review_blinding": "Protocol and primary implementation were visible; primary code was not imported. Independent quantities computed before reading results.",
        "source_sha256": lock["source_sha256"], "protocol_code_sha256": lock["protocol_code_sha256"],
        "auditor_script_sha256": sha(Path(__file__)),
        "source_tickets": len(tickets), "identity_conflict_customers": len(bad_ids),
        "eligible_closed_n": len(eligible), "training_n": len(train), "test_n": len(test),
        "training_low_csat_n": class_document_count[1], "test_low_csat_n": sum(test_labels),
        "vocabulary_size": len(vocabulary), "test_unknown_token_count": unknown_tokens,
        "test_token_count": token_count, "test_documents_with_no_known_tokens": empty_known_documents,
        "model_log_parameter_max_abs_difference": max(parameter_differences),
        "test_probability_max_abs_difference": max(probability_differences),
        "auc_on_saved_probabilities_matches_primary": True,
        "auc_float_order_affected_pairs": auc_pairs,
        "auc_saved_minus_independent": target["resolution_bag_of_words"]["auc"] - independent_metrics["resolution_bag_of_words"]["auc"],
        "independent_metrics": independent_metrics,
        "bootstrap_scope": "5000 paired customer resamples replayed with protocol NumPy RNG and quantile definition, using independently reconstructed per-customer errors",
        "index_records_verified": len(index), "evidence_cards_verified": len(cards),
        "evidence_state_counts": dict(state_counts), "all_missing_ratings_preserved_unobserved": True,
        "all_customer_sentiment_states_unknown": True, "source_and_frozen_hashes_match": True,
        "cli_smoke_tests": cli_checks, "semantic_review_source_and_count_check": semantic_counts,
        "semantic_review_check_scope": "Verifies IDs, original text availability and arithmetic only; no semantic gold-standard or sentiment-accuracy claim",
        "limitations": ["Numerical and provenance validation does not establish semantic sentiment accuracy.",
                       "Bootstrap conditions on this fixed split and fitted model; it does not include model selection or retraining uncertainty.",
                       "No business intervention, recovery, actual resolution rate, or profit effect is tested.",
                       "The separate semantic sample review is outside this numeric audit."],
    }
    (HERE / "independent_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    brief = f"""# Independent numerical and evidence audit

**Result: PASS.** Rebuilt the classifier from the source CSVs with standard-library `Counter`, scalar log odds, and rank-based AUC. This verifier does not import the main experiment. The auditor saw its protocol and implementation interface: this is numerical replication, not a blinded review. The checker computes its own predictions and metrics before loading the primary result files.

- Identity-conflict customer exclusions: {len(bad_ids)}; eligible closed/rated/text cohort: {len(eligible)} unique customers. Exact fixed split: {len(train)} train / {len(test)} test, no customer overlap.
- Training vocabulary: {len(vocabulary)}. Rechecked all document frequencies, class priors, word log probabilities, split rows, and {len(predictions)} held-out probabilities. Maximum probability difference: {max(probability_differences):.3g}.
- Baseline Brier: {independent_metrics['baseline']['brier']:.12f}; text Brier: {independent_metrics['resolution_bag_of_words']['brier']:.12f}; baseline-minus-text gain: {independent_metrics['brier_gain_baseline_minus_text']:.12f}. Text AUC: {independent_metrics['resolution_bag_of_words']['auc']:.12f}.
- Rank-based AUC on the saved primary probabilities exactly reproduces the primary AUC. The scalar reconstruction changes AUC by {target['resolution_bag_of_words']['auc'] - independent_metrics['resolution_bag_of_words']['auc']:.12g}, entirely explained by {len(auc_pairs)} positive/negative pair(s) tied to floating precision. Every changed pair is listed in JSON; each score difference is bounded by the measured floating-point prediction difference. This is not a substantive result change.
- Replayed the specified {p['bootstrap_repetitions']} customer-level paired bootstrap draws from independently calculated errors. 95% interval: [{interval[0]:.12f}, {interval[1]:.12f}]. This checks the stated calculation; it is not an alternative uncertainty method or a new sample.
- All {len(index)} evidence-index records match source ticket IDs, rows, ratings, states, and routes. All missing ratings remain `UNOBSERVED`; every customer sentiment remains `UNKNOWN_NO_CUSTOMER_VERBATIM_OR_SENTIMENT_LABEL`.
- All {len(cards)} deterministic audit cards match their source rows, contexts, resolution strings, score states, routes, unknown sentiment, and unmeasured outcomes. The separate review-input CSV also matches.
- Source CSV/dictionary and frozen protocol/code SHA-256 hashes match the execution lock and results.
- Actual CLI smoke checks for tickets 5919 and 6863 return the full audited cards, respectively low reported CSAT and unobserved feedback, with sentiment unknown in both. Stable example JSONs are saved.
- The separate semantic-review IDs, source availability and counts match all 20 review-input rows: 15 available texts and 5 missing. This is a source/count check; semantic judgments are not validated as a sentiment gold standard.

The observed-CSAT states are {dict(state_counts)}. This is a provenance and software check, **not 100% sentiment accuracy**. No customer-verbatim field or sentiment annotation exists in the inspected schema. The semantic review of the short texts is a separate audit. No customer-recovery, resolution-rate, or profit result is validated by this checker.

Run from the repository root: `python sentiment_evidence_v1/independent_verify.py`. Complete numeric evidence is in `independent_audit.json`.
"""
    (HERE / "independent_audit.md").write_text(brief, encoding="utf-8", newline="\n")
    print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
