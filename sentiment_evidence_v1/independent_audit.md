# Independent numerical and evidence audit

**Result: PASS.** Rebuilt the classifier from the source CSVs with standard-library `Counter`, scalar log odds, and rank-based AUC. This verifier does not import the main experiment. The auditor saw its protocol and implementation interface: this is numerical replication, not a blinded review. The checker computes its own predictions and metrics before loading the primary result files.

- Identity-conflict customer exclusions: 139; eligible closed/rated/text cohort: 2663 unique customers. Exact fixed split: 2130 train / 533 test, no customer overlap.
- Training vocabulary: 971. Rechecked all document frequencies, class priors, word log probabilities, split rows, and 533 held-out probabilities. Maximum probability difference: 3.89e-15.
- Baseline Brier: 0.236501204197; text Brier: 0.297404224576; baseline-minus-text gain: -0.060903020379. Text AUC: 0.484556588593.
- Rank-based AUC on the saved primary probabilities exactly reproduces the primary AUC. The scalar reconstruction changes AUC by 7.44978842598e-06, entirely explained by 1 positive/negative pair(s) tied to floating precision. Every changed pair is listed in JSON; each score difference is bounded by the measured floating-point prediction difference. This is not a substantive result change.
- Replayed the specified 5000 customer-level paired bootstrap draws from independently calculated errors. 95% interval: [-0.080753191565, -0.040957030680]. This checks the stated calculation; it is not an alternative uncertainty method or a new sample.
- All 8469 evidence-index records match source ticket IDs, rows, ratings, states, and routes. All missing ratings remain `UNOBSERVED`; every customer sentiment remains `UNKNOWN_NO_CUSTOMER_VERBATIM_OR_SENTIMENT_LABEL`.
- All 20 deterministic audit cards match their source rows, contexts, resolution strings, score states, routes, unknown sentiment, and unmeasured outcomes. The separate review-input CSV also matches.
- Source CSV/dictionary and frozen protocol/code SHA-256 hashes match the execution lock and results.
- Actual CLI smoke checks for tickets 5919 and 6863 return the full audited cards, respectively low reported CSAT and unobserved feedback, with sentiment unknown in both. Stable example JSONs are saved.
- The separate semantic-review IDs, source availability and counts match all 20 review-input rows: 15 available texts and 5 missing. This is a source/count check; semantic judgments are not validated as a sentiment gold standard.

The observed-CSAT states are {'UNOBSERVED': 5700, 'MIDDLE_REPORTED': 580, 'LOW_REPORTED': 1102, 'HIGH_REPORTED': 1087}. This is a provenance and software check, **not 100% sentiment accuracy**. No customer-verbatim field or sentiment annotation exists in the inspected schema. The semantic review of the short texts is a separate audit. No customer-recovery, resolution-rate, or profit result is validated by this checker.

Run from the repository root: `python sentiment_evidence_v1/independent_verify.py`. Complete numeric evidence is in `independent_audit.json`.
