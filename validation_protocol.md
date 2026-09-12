# Low-cost validation v1

Question: does a recent usage decline contain enough temporal signal to justify developing a customer-support review queue?

Scope: local offline analysis only. No paid model calls, external writes, customer contact, or revenue/causal claims. The source is a supplied synthetic competition dataset.

This is retrospective exploratory validation: all five months were available and described in earlier work. May is a forward evaluation month relative to April, not a pristine sealed holdout. No model fitting or threshold optimization.

## Primary population and definitions (fixed before validation results)

- Unit: customer-product, one row per customer-product; cluster bootstrap by customer if needed.
- Exclude a customer if any ticket name, age, or gender disagrees with the customer dimension; report exclusions.
- Exclude a customer if any monthly Active Days is negative, missing, or greater than days in that calendar month; report exclusions.
- Require all five monthly records, January-May 2023, and unique source keys.
- Activity = Active Days / calendar days. No silent correction of invalid values.
- Baseline = mean monthly activity in January-March.
- April alert = April activity <= 70% of baseline AND baseline minus April activity >= 0.10. This is both a 30% relative decline and a 10 percentage-point absolute decline.
- May outcome = May meets the same low-activity definition against January-March. This is an activity proxy, not churn or customer harm.
- Main comparisons: alert vs non-alert May outcome rates and alert precision divided by the population outcome rate (same-capacity random expectation).
- Report alert count, outcomes, rate difference, lift, 95% percentile bootstrap intervals (2,000 resamples), and full uncertainty.
- Negative control: independently permute the five activity months within each customer-product 1,000 times, recomputing baseline/alert/outcome. This retains individual levels, variation and shared-baseline effects, but removes calendar order. The exchangeability assumption is approximate; calendar effects are not controlled completely.
- Frozen initial evidence gate: >=50 alerts; lift >=1.5; risk-difference 95% lower bound >0; lift greater than the month-permutation null with one-sided p<0.05. All conditions required. Failure stops promotion of a predictive claim; do not tune to pass.

## Snapshot feasibility

- Use all currently supplied ticket statuses only for a descriptive June support snapshot.
- Eligible = non-Closed status AND High/Critical priority.
- Review candidate = eligible AND April alert AND May low activity. No claim that June support caused the earlier decline.
- Export up to 10 deterministic anonymized case examples with source Ticket ID and Customer ID, product, plan, priority/status/topic, activity sequence, selection reasons, and a proposed support action marked unvalidated.
- Candidate size is not evidence of need, successful intervention, or economic value. No June+ usage labels exist.

## Fixed sensitivity and failure handling

- Repeat with relative thresholds 20%, 30%, 40%; retain absolute threshold 0.10. Report all, never select a new winner.
- Repeat primary definition retaining all complete raw rows (invalid days flagged), and with explicitly clipped activity values (sensitivity only).
- Show history January-May for alerts and non-alerts; check whether alerts rebound in May.
- Compare snapshot queue count to within product-plan random reassignment of the sustained-decline indicator; descriptive independence check only.
- If predictive gate fails, retain at most a manual workflow demonstration and recommend a small human review before further investment. Do not claim an intervention pilot or human validation has been run.

Random seed: 20260912. No significance fishing or expanding hypotheses after a failed gate in this round.
