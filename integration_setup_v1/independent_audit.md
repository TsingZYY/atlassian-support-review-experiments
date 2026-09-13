# Independent source and preparation audit

PASS. `independent_verify.py` reads the original three CSVs and the frozen protocol, reconstructs the cohort and preparation outputs, and does not import `audit.py`. The reviewer read the protocol and main implementation to establish the interface; this is independent recomputation, not a blinded study.

- Recomputed 89 raw Free + Integration candidates, 5 excluded for customer identity conflicts, and 84 distinct clean candidates among 1,440 clean Free customers.
- Verified all 84 roster rows, their order and every field; checked all 420 same-product January–May history rows. All 84 have at least one nonzero month, none have all-zero history, and 28 have zero integrations recorded in May.
- Reconstructed both salted hash orders directly. Verified all 20 evidence cards, original ticket/usage values and source rows, and the entire prepared allocation: 4 candidates per product, 2 per arm, 10 per arm overall.
- Verified all reported candidate summary fields, the four source-file hashes and two frozen protocol/code hashes.
- Verified outcomes remain JSON null / empty CSV fields, needs remain unconfirmed, and every intervention flag remains false.

The 20 records are a preparation example chosen before needs are confirmed, not an executed randomized trial. For a real trial, confirm current Free status and the specific integration task first, then randomize eligible customers to the additional help offer or existing support. Eligibility must not depend on this demonstration allocation. Analyse all customers as assigned, including those who decline help or fail to configure. Completion, upgrade and profit effects have not been measured. A closed ticket or historical integration use does not prove the current configuration is successful, and an absent upgrade label is not a zero upgrade.

Reproduce: `python integration_setup_v1/independent_verify.py`.
