"""Independent source/statistical audit; does not import experiment.py.

The first computation was performed before reading the primary implementation
or its results. An independent RNG seed is intentional for Monte Carlo checks.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SEED = 2026091317


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def score(row):
    try:
        value = float(row["Customer Satisfaction Rating"])
    except ValueError:
        return None
    return int(value) if value.is_integer() and 1 <= value <= 5 else None


def one_stratum(left, right, rng, repetitions):
    """Independent multinomial bootstrap and random-permutation implementation."""
    left = np.asarray(left, dtype=np.int8)
    right = np.asarray(right, dtype=np.int8)
    lv, lc = np.unique(left, return_counts=True)
    rv, rc = np.unique(right, return_counts=True)
    boot = (rng.multinomial(len(left), lc / len(left), size=repetitions) @ lv / len(left)
            - rng.multinomial(len(right), rc / len(right), size=repetitions) @ rv / len(right))
    pooled = np.concatenate([left, right])
    # Each row receives an independent permutation; preserve observed group sizes.
    permuted = rng.permuted(np.broadcast_to(pooled, (repetitions, len(pooled))), axis=1)
    perm = permuted[:, :len(left)].mean(axis=1) - permuted[:, len(left):].mean(axis=1)
    return float(left.mean() - right.mean()), boot, perm


def summarize(observed, bootstrap, permutation):
    extreme = int(np.count_nonzero(np.abs(permutation) >= abs(observed) - 1e-12))
    return {
        "difference": float(observed),
        "bootstrap_95_interval": np.quantile(bootstrap, [0.025, 0.975]).tolist(),
        "permutation_extreme_count": extreme,
        "permutation_p": (extreme + 1) / (len(permutation) + 1),
    }


def independently_compute():
    protocol = json.loads((HERE / "protocol.json").read_text(encoding="utf-8"))
    rows = read_csv(ROOT / "data" / "customer_support_tickets.csv")
    assert len({row["Ticket ID"] for row in rows}) == len(rows)
    technical = [row for row in rows if row["Ticket Type"] == "Technical issue"]
    rated = [row for row in technical if row["Ticket Status"] == "Closed" and score(row) is not None]
    primary = [row for row in rated if row["Ticket Channel"] in ("Email", "Social media")]
    assert len({row["Customer Email"].strip().lower() for row in primary}) == len(primary)
    grouped = {channel: [row for row in rated if row["Ticket Channel"] == channel]
               for channel in protocol["channels"]}
    rng = np.random.default_rng(SEED)
    repetitions = protocol["repetitions"]
    main = summarize(*one_stratum([score(r) for r in grouped["Email"]],
                                  [score(r) for r in grouped["Social media"]], rng, repetitions))
    strata = defaultdict(lambda: {"Email": [], "Social media": []})
    for row in primary:
        key = (row["Product Purchased"], row["Ticket Priority"])
        strata[key][row["Ticket Channel"]].append(score(row))
    supported = {key: cells for key, cells in strata.items() if cells["Email"] and cells["Social media"]}
    total_supported = sum(len(c["Email"]) + len(c["Social media"]) for c in supported.values())
    adjusted_diff = 0.0
    adjusted_boot = np.zeros(repetitions)
    adjusted_perm = np.zeros(repetitions)
    for key, cells in sorted(supported.items()):
        weight = (len(cells["Email"]) + len(cells["Social media"])) / total_supported
        difference, bootstrap, permutation = one_stratum(cells["Email"], cells["Social media"], rng, repetitions)
        adjusted_diff += weight * difference
        adjusted_boot += weight * bootstrap
        adjusted_perm += weight * permutation
    adjusted = summarize(adjusted_diff, adjusted_boot, adjusted_perm)
    adjusted.update({"strata": len(supported), "common_support": total_supported,
                     "excluded_strata": [list(k) for k in strata if k not in supported]})
    payment = [row for row in rows if row["Ticket Subject"] == "Payment issue"]
    payment_quality = {}
    for channel in protocol["channels"]:
        selected = [row for row in payment if row["Ticket Channel"] == channel]
        counts = Counter(total=len(selected), closed=sum(row["Ticket Status"] == "Closed" for row in selected))
        for row in selected:
            first, resolved = row["First Response Time"], row["Time to Resolution"]
            if not first or not resolved:
                counts["missing"] += 1
                continue
            counts["complete"] += 1
            try:
                first = datetime.strptime(first, "%d-%m-%Y %H:%M")
                resolved = datetime.strptime(resolved, "%d-%m-%Y %H:%M")
            except ValueError:
                counts["unparseable"] += 1
                continue
            counts["reversed" if resolved < first else "same" if resolved == first else "ordered"] += 1
        payment_quality[channel] = {key: counts[key] for key in
                                    ("total", "closed", "missing", "complete", "unparseable", "reversed", "same", "ordered")}
    audit_arms = [grouped["Email"], grouped["Social media"],
                  [r for r in payment if r["Ticket Status"] == "Closed" and r["Ticket Channel"] == "Chat"],
                  [r for r in payment if r["Ticket Status"] == "Closed" and r["Ticket Channel"] != "Chat"]]
    chosen_ids = []
    for arm in audit_arms:
        sorted_rows = sorted(arm, key=lambda r: hashlib.sha256(
            (protocol["audit_salt"] + "|" + r["Ticket ID"]).encode()).hexdigest())
        selection = [row["Ticket ID"] for row in sorted_rows if row["Ticket ID"] not in chosen_ids][:5]
        assert len(selection) == 5
        chosen_ids.extend(selection)
    assert len(chosen_ids) == len(set(chosen_ids)) == 20
    return {
        "independent_seed": SEED, "repetitions": repetitions,
        "source_ticket_count": len(rows), "technical_total": len(technical), "technical_rated": len(rated),
        "primary_unique_customer_count": len(primary),
        "channels": {channel: {"n": len(items), "sum": sum(score(r) for r in items),
                                "mean": float(np.mean([score(r) for r in items])),
                                "rating_counts": {str(value): sum(score(r) == value for r in items) for value in range(1, 6)}}
                     for channel, items in grouped.items()},
        "primary": main, "adjusted": adjusted, "payment_quality": payment_quality,
        "audit_ticket_ids_in_order": chosen_ids,
        "causal_effect_identified": False,
        "speed_identified": False,
    }


def verify_primary_outputs(independent):
    """Read the main outputs only after the independent computation above."""
    primary = json.loads((HERE / "results.json").read_text(encoding="utf-8"))
    lock = json.loads((HERE / "execution_lock.json").read_text(encoding="utf-8"))
    for name, expected in lock["source_sha256"].items():
        assert hashlib.sha256((ROOT / "data" / name).read_bytes()).hexdigest() == expected
        assert primary["source_sha256"][name] == expected
    for name, expected in lock["protocol_code_sha256"].items():
        assert hashlib.sha256((HERE / name).read_bytes()).hexdigest() == expected
    assert independent["source_ticket_count"] == primary["source_tickets"] == 8469
    assert independent["technical_total"] == primary["technical_total"] == 1747
    assert independent["technical_rated"] == primary["technical_rated_closed"] == 580
    assert independent["primary_unique_customer_count"] == 287
    for exported in primary["technical_channel_summary"]:
        mine = independent["channels"][exported["channel"]]
        assert mine["n"] == exported["rated_closed_n"]
        assert mine["sum"] == exported["rating_sum"]
        assert math.isclose(mine["mean"], exported["mean_rating"], abs_tol=1e-12)
        for value, count in mine["rating_counts"].items():
            assert count == exported[f"rating_{value}_n"]
        assert mine["rating_counts"]["4"] + mine["rating_counts"]["5"] == exported["high_rating_n"]
    monte_carlo_checks = []
    comparisons = [(independent["primary"], primary["primary"], "mean_difference", "two_sided_permutation_p"),
                   (independent["adjusted"], primary["adjusted_sensitivity"],
                    "standardized_mean_difference", "within_stratum_two_sided_permutation_p")]
    for mine, exported, difference_key, probability_key in comparisons:
        assert math.isclose(mine["difference"], exported[difference_key], abs_tol=1e-12)
        observed_p, reference_p = mine["permutation_p"], exported[probability_key]
        standard_error = math.sqrt((observed_p * (1 - observed_p) + reference_p * (1 - reference_p))
                                   / independent["repetitions"])
        z_difference = abs(observed_p - reference_p) / standard_error
        assert z_difference < 4.5, (probability_key, z_difference)
        ci_gap = max(abs(a - b) for a, b in zip(mine["bootstrap_95_interval"], exported["bootstrap_95"]))
        assert ci_gap < 0.04, (probability_key, ci_gap)
        assert observed_p > 0.05 and reference_p > 0.05
        assert mine["bootstrap_95_interval"][0] < 0 < mine["bootstrap_95_interval"][1]
        assert exported["bootstrap_95"][0] < 0 < exported["bootstrap_95"][1]
        monte_carlo_checks.append({"comparison": probability_key, "p_difference_in_combined_mc_se": z_difference,
                                   "max_ci_endpoint_gap": ci_gap})
    assert independent["adjusted"]["strata"] == len(primary["adjusted_sensitivity"]["strata"]) == 20
    assert independent["adjusted"]["common_support"] == primary["adjusted_sensitivity"]["common_support_n"] == 287
    assert independent["adjusted"]["excluded_strata"] == primary["adjusted_sensitivity"]["excluded_strata"] == []
    mapping = {"total": "payment_tickets", "closed": "closed_n", "missing": "missing_timestamp_pair",
               "unparseable": "unparseable_pair", "reversed": "resolution_before_first_response",
               "same": "same_time", "ordered": "ordered_pair"}
    for exported in primary["payment_time_quality_by_channel"]:
        mine = independent["payment_quality"][exported["channel"]]
        for key, output_key in mapping.items():
            assert mine[key] == exported[output_key]
        assert mine["complete"] == mine["closed"]
    assert sum(v["total"] for v in independent["payment_quality"].values()) == primary["payment_total"] == 526
    assert sum(v["closed"] for v in independent["payment_quality"].values()) == primary["payment_closed"] == 156
    assert sum(v["reversed"] for v in independent["payment_quality"].values()) == 82
    raw = read_csv(ROOT / "data" / "customer_support_tickets.csv")
    source = {row["Ticket ID"]: (record, row) for record, row in enumerate(raw, start=2)}
    cases = read_csv(HERE / "audit_cases_20.csv")
    assert [row["Ticket ID"] for row in cases] == independent["audit_ticket_ids_in_order"]
    assert Counter(row["audit_arm"] for row in cases) == {
        "technical_email": 5, "technical_social": 5, "payment_chat": 5, "payment_other": 5}
    for case in cases:
        record, original = source[case["Ticket ID"]]
        assert int(case["source_row"]) == record
        for field in case:
            if field in original:
                assert case[field] == original[field], (case["Ticket ID"], field)
        first = datetime.strptime(original["First Response Time"], "%d-%m-%Y %H:%M")
        resolved = datetime.strptime(original["Time to Resolution"], "%d-%m-%Y %H:%M")
        state = "resolution_before_first_response" if resolved < first else "same_time" if resolved == first else "ordered_pair"
        assert case["timestamp_state"] == state
    for filename, key in [("technical_channel_summary.csv", "technical_channel_summary"),
                          ("payment_time_quality.csv", "payment_time_quality_by_channel")]:
        assert read_csv(HERE / filename) == [{k: str(v) for k, v in row.items()} for row in primary[key]]
    dictionary = (ROOT / "data" / "README.md").read_text(encoding="utf-8")
    assert "Channel through which the ticket was submitted" in dictionary
    assert "Timestamp of the first response" in dictionary
    assert "Timestamp associated with ticket resolution" in dictionary
    assert not any("creat" in key.casefold() for key in raw[0])
    assert primary["payment_chat_faster_conclusion"] == "NOT_IDENTIFIABLE_FROM_AVAILABLE_TIMESTAMPS"
    assert primary["ticket_created_timestamp_available"] is False
    assert primary["total_resolution_duration_available"] is False
    assert primary["primary"]["email_higher_supported"] is False
    assert primary["causal_channel_effect"] == "UNVERIFIED"
    assert primary["measured_profit_effect"] is None
    return {"status": "PASS", "monte_carlo_checks": monte_carlo_checks,
            "source_and_protocol_hashes": "PASS", "all_20_source_rows_and_fields": "PASS",
            "summary_csv_consistency": "PASS", "dictionary_semantics": "PASS",
            "mc_p_tolerance": "4.5 combined Monte Carlo standard errors",
            "bootstrap_endpoint_tolerance_points": 0.04,
            "channel_means_submission_channel": True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--compute-only", action="store_true")
    args = parser.parse_args()
    result = independently_compute()
    if not args.compute_only:
        result["verification"] = verify_primary_outputs(result)
    (HERE / "independent_audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result if args.compute_only else result["verification"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
