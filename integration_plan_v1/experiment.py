"""Competition-only integration/plan association; no causal or profit labels."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
import calendar
import csv
import hashlib
import json
import math
import numpy as np

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / 'data'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name, value):
    (HERE/name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8', newline='\n')


def read(name):
    with (DATA/name).open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def csv_out(name, rows):
    with (HERE/name).open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


def eta_squared(values, labels):
    values = np.asarray(values, dtype=float)
    if values.ndim == 1:
        values = values[:, None]
    mean = values.mean(axis=0)
    total = ((values-mean)**2).sum(axis=0)
    between = sum(np.sum(labels == group) * (values[labels == group].mean(axis=0)-mean)**2
                  for group in np.unique(labels))
    assert np.all(total > 0)
    return between / total


def stratified_bootstrap(values, labels, count, seed):
    rng = np.random.default_rng(seed)
    groups = [np.flatnonzero(labels == g) for g in np.unique(labels)]
    result = []
    for _ in range(count):
        sample = np.concatenate([rng.choice(g, size=len(g), replace=True) for g in groups])
        result.append(eta_squared(values[sample], labels[sample]))
    return np.asarray(result)


def build_cohort(p):
    customers, usage = read('customers.csv'), read('product_usage.csv')
    by_id = {r['Customer ID']: r for r in customers}
    assert len(by_id) == len(customers)
    assert all(r['Plan Type'] in p['plans'] for r in customers)
    assert len({(r['Customer ID'], r['Product'], r['Month']) for r in usage}) == len(usage)
    by_customer, by_pair = defaultdict(list), defaultdict(list)
    invalid_active_ids = set()
    numeric = ['Integrations Used', 'Sessions', 'Product Actions', 'Collaborators', 'Active Days']
    for row_number, r in enumerate(usage, 2):
        assert r['Customer ID'] in by_id and r['Month'] in p['months'] and r['Product'] in p['products']
        for f in numeric:
            v = float(r[f])
            assert math.isfinite(v) and v >= 0 and v.is_integer()
        days = calendar.monthrange(*map(int, r['Month'].split('-')))[1]
        r = dict(r, source_row=row_number, **{f:float(r[f]) for f in numeric})
        r['Active Day Rate'] = r['Active Days']/days
        if r['Active Days'] > days:
            invalid_active_ids.add(r['Customer ID'])
        by_customer[r['Customer ID']].append(r)
        by_pair[r['Customer ID'], r['Product']].append(r)
    assert set(by_customer) == set(by_id)
    assert all(len(group) == 5 and sorted(r['Month'] for r in group) == p['months'] for group in by_pair.values())
    cohort = []
    for row_number, c in enumerate(customers, 2):
        group = by_customer[c['Customer ID']]
        cohort.append({'customer_id':c['Customer ID'], 'plan':c['Plan Type'], 'customer_source_row':row_number,
                       'usage_source_rows':'|'.join(str(r['source_row']) for r in group),
                       'product_n':len({r['Product'] for r in group}), 'usage_record_n':len(group),
                       **{f:float(np.mean([r[f] for r in group])) for f in p['metrics']},
                       'zero_record_n':sum(r['Integrations Used'] == 0 for r in group),
                       'all_records_zero':all(r['Integrations Used'] == 0 for r in group),
                       'common_metric_eligible':c['Customer ID'] not in invalid_active_ids})
    quality = {'source_customers':len(customers), 'source_usage_rows':len(usage), 'customer_product_pairs':len(by_pair),
               'unmatched_usage_ids':0, 'customers_without_usage':0, 'duplicate_customer_product_months':0,
               'incomplete_five_month_pairs':0, 'invalid_numeric_counts':0,
               'active_days_exceed_calendar_rows':sum(r['Active Day Rate'] > 1 for rows in by_customer.values() for r in rows),
               'active_days_exceed_calendar_customers':len(invalid_active_ids),
               'customer_product_counts':dict(Counter(r['product_n'] for r in cohort)),
               'primary_customer_n':len(cohort), 'common_metrics_customer_n':sum(r['common_metric_eligible'] for r in cohort)}
    return cohort, by_customer, by_pair, by_id, quality


def main():
    p = json.loads((HERE/'protocol.json').read_text(encoding='utf-8'))
    fingerprints = {'source_sha256':{n:sha(DATA/n) for n in ('customers.csv','product_usage.csv','README.md')},
                    'protocol_code_sha256':{n:sha(HERE/n) for n in ('protocol.json','protocol.md','experiment.py')}}
    if (HERE/'execution_lock.json').exists():
        old = json.loads((HERE/'execution_lock.json').read_text(encoding='utf-8'))
        assert all(old[k] == v for k,v in fingerprints.items())
    else:
        write('execution_lock.json',dict(fingerprints, frozen_at=datetime.now(timezone.utc).isoformat()))
    cohort, by_customer, by_pair, by_id, quality = build_cohort(p)
    labels = np.array([p['plans'].index(r['plan']) for r in cohort])
    y = np.array([r['Integrations Used'] for r in cohort])
    main_r2 = float(eta_squared(y, labels)[0])
    primary_boot = stratified_bootstrap(y, labels, p['bootstrap_repetitions'], p['seed'])[:,0]
    rng = np.random.default_rng(p['seed']+1)
    extreme = sum(float(eta_squared(y, rng.permutation(labels))[0]) >= main_r2-1e-12
                  for _ in range(p['permutation_repetitions']))
    primary = {'customer_n':len(cohort), 'eta_squared_ols_r2':main_r2,
               'bootstrap_95':np.quantile(primary_boot, [.025,.975]).tolist(),
               'permutation_extreme_count':extreme, 'permutation_p':(extreme+1)/(p['permutation_repetitions']+1),
               'repetitions':p['permutation_repetitions'], 'direction':'categorical_plan_predicts_mean_integration_count'}
    common = [r for r in cohort if r['common_metric_eligible']]
    common_labels = np.array([p['plans'].index(r['plan']) for r in common])
    values = np.array([[r[f] for f in p['metrics']] for r in common])
    point = eta_squared(values, common_labels)
    boots = stratified_bootstrap(values, common_labels, p['bootstrap_repetitions'], p['seed']+2)
    comparisons = [{'metric':f, 'customer_n':len(common), 'eta_squared_ols_r2':float(point[j]),
                    'bootstrap_95_lower':float(np.quantile(boots[:,j],.025)),
                    'bootstrap_95_upper':float(np.quantile(boots[:,j],.975))} for j,f in enumerate(p['metrics'])]
    ranking = {'comparisons':comparisons, 'integration_is_largest':bool(point[0] > max(point[1:])),
               'integration_minus_largest_other':float(point[0]-max(point[1:])),
               'gap_bootstrap_95':np.quantile(boots[:,0]-boots[:,1:].max(axis=1),[.025,.975]).tolist(),
               'scope':'five_prespecified_usage_metrics_univariate_association_not_causal_importance'}
    summaries = []
    for plan in p['plans']:
        selected = [r for r in cohort if r['plan'] == plan]
        raw_group = [r for c in selected for r in by_customer[c['customer_id']]]
        summaries.append({'plan':plan, 'customer_n':len(selected),
                          'mean_customer_integrations':float(np.mean([r['Integrations Used'] for r in selected])),
                          'median_customer_integrations':float(np.median([r['Integrations Used'] for r in selected])),
                          'any_zero_record_customers':sum(r['zero_record_n'] > 0 for r in selected),
                          'all_records_zero_customers':sum(r['all_records_zero'] for r in selected),
                          'product_month_records':len(raw_group),
                          'zero_product_month_records':sum(r['Integrations Used'] == 0 for r in raw_group)})
    products = []
    for product in p['products']:
        groups = [(cid,g) for (cid,prod),g in by_pair.items() if prod == product]
        z = np.array([np.mean([r['Integrations Used'] for r in g]) for _,g in groups])
        lab = np.array([p['plans'].index(by_id[cid]['Plan Type']) for cid,_ in groups])
        products.append({'product':product, 'customer_n':len(groups), 'eta_squared_ols_r2':float(eta_squared(z,lab)[0])})
    raw = [r for rows in by_customer.values() for r in rows]
    row_r2 = float(eta_squared([r['Integrations Used'] for r in raw],
                              np.array([p['plans'].index(by_id[r['Customer ID']]['Plan Type']) for r in raw]))[0])
    months = []
    for month in p['months']:
        rows = [r for r in raw if r['Month'] == month]
        z = [r['Integrations Used'] for r in rows]
        lab = np.array([p['plans'].index(by_id[r['Customer ID']]['Plan Type']) for r in rows])
        months.append({'month':month, 'product_customer_rows':len(rows), 'eta_squared_ols_r2':float(eta_squared(z,lab)[0])})
    train, test, split = [], [], []
    for plan in p['plans']:
        group = sorted([r for r in cohort if r['plan'] == plan],
                       key=lambda r:hashlib.sha256((p['holdout_hash_salt']+'|'+r['customer_id']).encode()).hexdigest())
        cutoff = int(len(group)*p['training_fraction'])
        train.extend(group[:cutoff]); test.extend(group[cutoff:])
        split.append({'plan':plan,'train_n':cutoff,'test_n':len(group)-cutoff})
    assert not ({r['customer_id'] for r in train} & {r['customer_id'] for r in test})
    means = {plan:float(np.mean([r['Integrations Used'] for r in train if r['plan']==plan])) for plan in p['plans']}
    baseline = float(np.mean([r['Integrations Used'] for r in train]))
    actual = np.array([r['Integrations Used'] for r in test])
    predicted = np.array([means[r['plan']] for r in test])
    mse = float(np.mean((actual-predicted)**2))
    baseline_mse = float(np.mean((actual-baseline)**2))
    holdout = {'train_n':len(train), 'test_n':len(test), 'by_plan':split, 'trained_plan_means':means,
               'training_global_mean':baseline, 'test_r2':float(1-np.sum((actual-predicted)**2)/np.sum((actual-actual.mean())**2)),
               'test_mse':mse, 'training_global_mean_baseline_test_mse':baseline_mse,
               'mse_reduction_vs_training_global_mean':1-mse/baseline_mse,
               'no_customer_overlap':True, 'not_a_forecast_or_upgrade_model':True}
    audit = []
    for plan in p['plans']:
        group = sorted([r for r in cohort if r['plan']==plan],
                       key=lambda r:hashlib.sha256((p['audit_hash_salt']+'|'+r['customer_id']).encode()).hexdigest())[:p['audit_per_plan']]
        audit.extend(group)
    assert len(audit) == len({r['customer_id'] for r in audit}) == 20
    result = {'executed_at':datetime.now(timezone.utc).isoformat(), 'dataset_scope':'competition_csv_only',
              'new_synthetic_observations':0, **fingerprints, 'quality':quality, 'primary':primary,
              'common_cohort_metric_ranking':ranking, 'plan_summary':summaries,
              'raw_product_month_descriptive_r2':row_r2, 'monthly_descriptive_r2':months,
              'product_sensitivity':products, 'customer_holdout':holdout,
              'zero_usage':{'zero_product_month_records':sum(r['Integrations Used']==0 for r in raw),
                            'product_month_denominator':len(raw), 'any_zero_record_customers':sum(r['zero_record_n']>0 for r in cohort),
                            'all_records_zero_customers':sum(r['all_records_zero'] for r in cohort), 'customer_denominator':len(cohort)},
              'audit_source_customers':20, 'nonuse_reasons_observed':False, 'monthly_plan_history_available':False,
              'causal_upgrade_effect':'UNVERIFIED', 'measured_profit_effect':None}
    csv_out('plan_summary.csv',summaries)
    csv_out('usage_metric_comparison.csv',comparisons)
    csv_out('product_sensitivity.csv',products)
    csv_out('audit_cases_20.csv',audit)
    write('results.json',result)
    print(json.dumps({k:result[k] for k in ('quality','primary','common_cohort_metric_ranking','plan_summary',
                      'raw_product_month_descriptive_r2','product_sensitivity','customer_holdout','zero_usage')},ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
