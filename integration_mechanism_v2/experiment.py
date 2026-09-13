"""Descriptive adjusted association; no intervention or upgrade outcomes."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
import csv
import hashlib
import json
import math
import numpy as np

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / 'data'


def read(path):
    with path.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_csv(name, rows):
    with (HERE / name).open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    old_protocol = HERE.parent / 'integration_plan_v1' / 'protocol.json'
    p = json.loads(old_protocol.read_text(encoding='utf-8'))
    customers, usage = read(DATA / 'customers.csv'), read(DATA / 'product_usage.csv')
    by_id = {r['Customer ID']: r for r in customers}
    assert len(customers) == len(by_id)
    by_customer, by_pair = defaultdict(list), defaultdict(set)
    seen = set()
    fields = ['Integrations Used', 'Sessions', 'Product Actions', 'Collaborators']
    for raw in usage:
        cid, product, month = raw['Customer ID'], raw['Product'], raw['Month']
        assert cid in by_id and product in p['products'] and month in p['months']
        key = (cid, product, month)
        assert key not in seen
        seen.add(key)
        nums = {f: float(raw[f]) for f in fields}
        assert all(math.isfinite(v) and v >= 0 and v.is_integer() for v in nums.values())
        by_customer[cid].append((product, nums))
        by_pair[cid, product].add(month)
    assert set(by_customer) == set(by_id)
    assert all(v == set(p['months']) for v in by_pair.values())
    ids = sorted(by_id)
    rows = []
    for cid in ids:
        c = by_id[cid]
        assert c['Plan Type'] in p['plans']
        row = {'cid': cid, 'plan': c['Plan Type']}
        for f in ['Company Size', 'Industry', 'Region']:
            assert c[f]
            row[f] = c[f]
        for f in fields:
            row[f] = math.fsum(r[f] for _, r in by_customer[cid]) / len(by_customer[cid])
        counts = Counter(product for product, _ in by_customer[cid])
        for product in p['products']:
            row['product:' + product] = counts[product] / len(by_customer[cid])
        rows.append(row)
    train_ids, test_ids = set(), set()
    for plan in p['plans']:
        group = sorted([r['cid'] for r in rows if r['plan'] == plan],
                       key=lambda cid: hashlib.sha256((p['holdout_hash_salt'] + '|' + cid).encode()).hexdigest())
        cut = int(len(group) * p['training_fraction'])
        train_ids.update(group[:cut])
        test_ids.update(group[cut:])
    assert not train_ids & test_ids and train_ids | test_ids == set(ids)
    train = np.array([cid in train_ids for cid in ids])
    test = ~train
    y = np.array([r['Integrations Used'] for r in rows])
    category_fields = ['Company Size', 'Industry', 'Region', 'plan']
    levels = {f: sorted({r[f] for r in rows if r['cid'] in train_ids}) for f in category_fields}
    unknown = {f: sum(r[f] not in levels[f] for r in rows if r['cid'] in test_ids) for f in category_fields}
    assert not any(unknown.values()), unknown

    def cats(names):
        return [np.array([float(r[f] == level) for r in rows]) for f in names for level in levels[f][1:]]

    bg = cats(category_fields[:3]) + [np.array([r['product:' + prod] for r in rows]) for prod in p['products'][1:]]
    plan = cats(['plan'])
    intensity = [np.log1p([r[f] for r in rows]) for f in fields[1:]]
    designs = {'P': plan, 'B': bg, 'B+P': bg + plan, 'B+U': bg + intensity, 'B+U+P': bg + intensity + plan}
    summaries, metrics = [], {}
    sst, test_sst = float(np.sum((y-y.mean())**2)), float(np.sum((y[test]-y[test].mean())**2))
    for name, cols in designs.items():
        x = np.column_stack([np.ones(len(rows))] + cols)
        coef, _, rank, _ = np.linalg.lstsq(x, y, rcond=None)
        train_coef, _, train_rank, _ = np.linalg.lstsq(x[train], y[train], rcond=None)
        assert rank == train_rank == x.shape[1], (name, rank, train_rank, x.shape)
        sse = float(np.sum((y-x @ coef)**2))
        test_sse = float(np.sum((y[test]-x[test] @ train_coef)**2))
        row = {'model': name, 'parameters': x.shape[1], 'full_n': len(y), 'full_r2': 1-sse/sst,
               'full_sse': sse, 'train_n': int(train.sum()), 'reused_test_n': int(test.sum()),
               'reused_test_r2': 1-test_sse/test_sst, 'reused_test_mse': test_sse/int(test.sum())}
        metrics[name] = row
        summaries.append(row)
    contrasts = []
    for small, large in [('B', 'B+P'), ('B+U', 'B+U+P')]:
        a, b = metrics[small], metrics[large]
        assert b['full_r2'] >= a['full_r2'] - 1e-12
        contrasts.append({'base': small, 'with_plan': large,
                          'full_delta_r2': b['full_r2']-a['full_r2'],
                          'full_residual_fraction_removed': 1-b['full_sse']/a['full_sse'],
                          'reused_test_delta_r2': b['reused_test_r2']-a['reused_test_r2'],
                          'reused_test_mse_fraction_removed': 1-b['reused_test_mse']/a['reused_test_mse']})
    strata, orders = [], []
    for size in sorted({r['Company Size'] for r in rows}):
        means = []
        for label in p['plans']:
            selected = [r['Integrations Used'] for r in rows if r['Company Size'] == size and r['plan'] == label]
            assert selected
            value = math.fsum(selected)/len(selected)
            means.append(value)
            strata.append({'company_size': size, 'plan': label, 'customer_n': len(selected), 'mean_integrations': value})
        orders.append({'company_size': size, 'all_four_plans_present': True,
                       'free_standard_premium_enterprise_means_increasing': all(a < b for a, b in zip(means, means[1:]))})
    inputs = [DATA/'customers.csv', DATA/'product_usage.csv', DATA/'README.md', old_protocol]
    result = {'executed_at': datetime.now(timezone.utc).isoformat(),
              'scope': 'exploratory_conditional_association_in_competition_synthetic_data',
              'source_sha256': {str(f.relative_to(HERE.parent)): sha(f) for f in inputs},
              'analysis_sha256': {f.name: sha(f) for f in [HERE/'protocol.md', HERE/'experiment.py']},
              'quality': {'customer_n': len(rows), 'usage_rows': len(usage), 'customer_product_pairs': len(by_pair),
                          'unknown_test_categories': unknown, 'all_pairs_complete': True,
                          'train_n': int(train.sum()), 'reused_test_n': int(test.sum()), 'split_previously_used': True},
              'models': summaries, 'adding_plan': contrasts, 'company_size_order_checks': orders,
              'new_observations': 0, 'causal_effect_identified': False,
              'configuration_help_executed': False, 'upgrade_or_profit_effect_measured': False,
              'limitations': ['Background and usage proxies need not form a valid causal adjustment set.',
                              'Usage and product choice may be mediators or selection variables.',
                              'Coarse measured variables and additive OLS cannot rule out all alternative explanations.',
                              'The same synthetic data and previously examined test split are reused.']}
    write_csv('model_comparison.csv', summaries)
    write_csv('company_size_plan.csv', strata)
    (HERE/'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'quality': result['quality'], 'models': summaries, 'adding_plan': contrasts,
                      'company_size_order_checks': orders}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
