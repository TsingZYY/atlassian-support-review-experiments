"""Independent, low-cost temporal signal audit; no June features are predictors.

Predeclared checks: clean IDs only; one lexicographically selected product per
customer to keep resampling units independent; April alert = relative fall >=30%
and absolute fall >=0.10 vs Jan-Mar mean daily activity fraction. May outcome
uses the same thresholds, with a baseline-free May low-use sensitivity outcome.
Within-product baseline-decile randomization checks whether April alert adds
information beyond baseline propensity and the actual May marginal distribution.
All results are retrospective proxy checks, never causal business-benefit tests.
"""
from pathlib import Path
import json
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
RNG = np.random.default_rng(9122026)
N_PERM = 1999
N_BOOT = 1000


def norm(s):
    return s.astype(str).str.strip().str.casefold()


def contrast(a, y):
    p1, p0 = float(y[a].mean()), float(y[~a].mean())
    return dict(alert_n=int(a.sum()), comparison_n=int((~a).sum()),
                event_rate_alert=p1, event_rate_comparison=p0,
                risk_difference=p1-p0, risk_ratio=p1/p0 if p0 else None)


def conditional_check(frame, outcome):
    """Alert-population standardized RD on cells containing both groups."""
    a = frame['alert'].to_numpy(bool)
    y = frame[outcome].to_numpy(float)
    codes, _ = pd.factorize(frame['stratum'], sort=True)
    groups = [np.flatnonzero(codes == v) for v in np.unique(codes)]
    valid = [ix for ix in groups if a[ix].any() and (~a[ix]).any()]
    valid_idx = np.concatenate(valid)
    alert_total = sum(int(a[ix].sum()) for ix in valid)
    def statistic(av, yv, cv):
        total = 0.0
        denom = 0
        for v in np.unique(cv):
            ix = np.flatnonzero(cv == v)
            ai = av[ix]
            if ai.any() and (~ai).any():
                n1 = int(ai.sum())
                total += n1 * (yv[ix][ai].mean() - yv[ix][~ai].mean())
                denom += n1
        return total / denom if denom else np.nan
    observed = statistic(a, y, codes)
    # Fast permutation uses fixed group weights, preserving baseline/product and
    # May outcomes. One panel per ID makes observations independently shuffled.
    null = np.empty(N_PERM)
    for k in range(N_PERM):
        total = 0.0
        for ix in valid:
            yi = RNG.permutation(y[ix])
            ai = a[ix]
            total += ai.sum() * (yi[ai].mean() - yi[~ai].mean())
        null[k] = total / alert_total
    boot = np.empty(N_BOOT)
    for k in range(N_BOOT):
        ix = RNG.integers(0, len(frame), len(frame))
        boot[k] = statistic(a[ix], y[ix], codes[ix])
    return dict(**contrast(a, y), adjusted_risk_difference=float(observed),
                adjusted_bootstrap_95_ci=np.quantile(boot, [.025,.975]).tolist(),
                one_sided_permutation_p=float((1+(null>=observed).sum())/(N_PERM+1)),
                null_95_interval=np.quantile(null,[.025,.975]).tolist(),
                matched_strata=len(valid), observations_in_matched_strata=len(valid_idx),
                alerts_in_matched_strata=alert_total)


def main():
    c = pd.read_csv(ROOT/'data/customers.csv')
    t = pd.read_csv(ROOT/'data/customer_support_tickets.csv')
    u = pd.read_csv(ROOT/'data/product_usage.csv')
    j = t.merge(c, on='Customer Email', how='left', suffixes=('_ticket','_customer'), validate='many_to_one')
    mismatch = np.zeros(len(j),dtype=bool)
    mismatch_counts = {}
    for field in ['Customer Name','Customer Age','Customer Gender']:
        m = norm(j[field+'_ticket']) != norm(j[field+'_customer'])
        mismatch |= m.to_numpy()
        mismatch_counts[field] = int(m.sum())
    identity_bad_ids = set(j.loc[mismatch,'Customer ID'])
    u['days_in_month'] = pd.to_datetime(u['Month']).dt.daysinmonth
    invalid = ((u['Active Days'] < 0) | (u['Active Days'] > u['days_in_month']))
    invalid_ids = set(u.loc[invalid,'Customer ID'])
    excluded_ids = identity_bad_ids | invalid_ids
    clean = u.loc[~u['Customer ID'].isin(excluded_ids)].copy()
    clean['fraction'] = clean['Active Days'] / clean['days_in_month']
    panels = clean.pivot(index=['Customer ID','Product'],columns='Month',values='fraction').reset_index()
    months = ['2023-01','2023-02','2023-03','2023-04','2023-05']
    assert panels[months].notna().all().all()
    # Deterministic independent sample, fixed before inspecting outcomes.
    sample = panels.sort_values(['Customer ID','Product']).drop_duplicates('Customer ID').copy()
    sample['baseline'] = sample[months[:3]].mean(axis=1)
    sample['alert'] = ((sample['2023-04'] <= .70*sample['baseline']) &
                       (sample['2023-04'] <= sample['baseline']-.10))
    sample['may_persistent_low'] = ((sample['2023-05'] <= .70*sample['baseline']) &
                                    (sample['2023-05'] <= sample['baseline']-.10))
    # Sensitivity outcome does not reuse a person's Jan-Mar baseline.
    cutoff = sample.groupby('Product')['2023-05'].transform(lambda x: x.quantile(.2))
    sample['may_product_bottom_quintile'] = sample['2023-05'] <= cutoff
    # Rank-based qcut can split ties. Use actual baseline values and allow fewer
    # bins when duplicate quantile boundaries occur.
    bins = sample.groupby('Product')['baseline'].transform(lambda x: pd.qcut(x,10,labels=False,duplicates='drop'))
    sample['stratum'] = sample['Product'].astype(str) + ':' + bins.astype(str)
    results = dict(
        method='Independent product x baseline-decile conditional randomization; one product per customer',
        seed=9122026, permutations=N_PERM, bootstrap_replicates=N_BOOT,
        caveats=['Retrospective active-use proxies only; no ticket features or future business outcomes used.',
                 'Baseline deciles only coarsely condition on baseline; observational association is not causal.',
                 'Month permutation alone assumes calendar months are exchangeable and can be sensitive to common trends.',
                 'Bottom-quintile ties may yield more than 20 percent classified as low use.'],
        counts=dict(customer_ids=c['Customer ID'].nunique(), usage_pairs=u[['Customer ID','Product']].drop_duplicates().shape[0],
                    identity_conflict_ids=len(identity_bad_ids), identity_conflict_ticket_rows=int(mismatch.sum()),
                    conflict_rows_by_field=mismatch_counts, invalid_active_day_rows=int(invalid.sum()),
                    invalid_active_day_ids=len(invalid_ids), excluded_union_ids=len(excluded_ids),
                    clean_pairs=len(panels), one_product_sample_ids=len(sample)),
        monthly_raw_active_day_means=u.groupby('Month')['Active Days'].mean().to_dict(),
        monthly_clean_activity_fractions=clean.groupby('Month')['fraction'].mean().to_dict(),
        raw_month_correlation=sample[months].corr().round(5).to_dict(),
        primary=conditional_check(sample,'may_persistent_low'),
        baseline_free_sensitivity=conditional_check(sample,'may_product_bottom_quintile'),
        per_product={name: contrast(g['alert'].to_numpy(bool),g['may_persistent_low'].to_numpy(float)) for name,g in sample.groupby('Product')},
    )
    out=ROOT/'validation_independent.json'
    out.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(results,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
