"""A 20-source-record opportunity-screening replay; no observed profit labels."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
from itertools import combinations, product
from pathlib import Path
import csv
import hashlib
import json
import math

ROOT = Path(__file__).resolve().parent
DATA = ROOT.parent / 'data'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(name, value):
    (ROOT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2,
                                      allow_nan=False), encoding='utf-8', newline='\n')


def read(name):
    with (DATA / name).open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def write_csv(name, rows):
    with (ROOT / name).open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


def norm(value):
    return value.strip().casefold()


def nonnegative_integer(value):
    number = float(value)
    assert math.isfinite(number) and number >= 0 and number.is_integer()
    return int(number)


def main():
    protocol = json.loads((ROOT / 'protocol.json').read_text(encoding='utf-8'))
    fingerprints = {
        'source_sha256': {name: sha(DATA / name) for name in
                          ('customers.csv', 'customer_support_tickets.csv', 'product_usage.csv', 'README.md')},
        'protocol_code_sha256': {name: sha(ROOT / name) for name in
                                 ('protocol.json', 'protocol.md', 'experiment.py')},
    }
    if (ROOT / 'execution_lock.json').exists():
        lock = json.loads((ROOT / 'execution_lock.json').read_text(encoding='utf-8'))
        assert all(lock[key] == value for key, value in fingerprints.items())
    else:
        write_json('execution_lock.json', dict(fingerprints, frozen_at=datetime.now(timezone.utc).isoformat()))

    customers, tickets, usage = [read(name) for name in
                                 ('customers.csv', 'customer_support_tickets.csv', 'product_usage.csv')]
    assert len({row['Customer ID'] for row in customers}) == len(customers)
    by_email, by_usage, products_by_customer = defaultdict(list), defaultdict(list), defaultdict(set)
    for row in customers:
        by_email[norm(row['Customer Email'])].append(row)
    conflicts = set()
    for ticket in tickets:
        match = by_email[norm(ticket['Customer Email'])]
        if len(match) != 1:
            continue
        if any(norm(match[0][field]) != norm(ticket[field]) for field in
               ('Customer Name', 'Customer Age', 'Customer Gender')):
            conflicts.add(match[0]['Customer ID'])
    for line, row in enumerate(usage, 2):
        by_usage[row['Customer ID'], row['Product'], row['Month']].append((line, row))
        products_by_customer[row['Customer ID']].add(row['Product'])

    def hash_key(cid):
        return hashlib.sha256((protocol['hash_salt'] + '|' + cid).encode()).hexdigest()

    cohort, exclusions = [], Counter()
    for source_line, customer in enumerate(customers, 2):
        if customer['Plan Type'] != protocol['plan']:
            continue
        cid = customer['Customer ID']
        if cid in conflicts:
            exclusions['identity_conflict'] += 1
            continue
        if len(products_by_customer[cid]) != 1:
            exclusions['non_unique_or_missing_product'] += 1
            continue
        product_name = next(iter(products_by_customer[cid]))
        if product_name not in protocol['products']:
            exclusions['outside_product_scope'] += 1
            continue
        values, lines = [], []
        try:
            for month in protocol['feature_months']:
                matches = by_usage[cid, product_name, month]
                assert len(matches) == 1
                line, row = matches[0]
                values.append(nonnegative_integer(row[protocol['feature']]))
                lines.append(line)
        except (AssertionError, ValueError, TypeError):
            exclusions['invalid_feature_history'] += 1
            continue
        cohort.append({'customer_id': cid, 'product': product_name, 'plan': customer['Plan Type'],
                       'customer_source_row': source_line,
                       'jan_collaborators': values[0], 'feb_collaborators': values[1],
                       'mar_collaborators': values[2], 'apr_collaborators': values[3],
                       'jan_apr_mean_collaborators': sum(values) / len(values),
                       'history_source_rows': '|'.join(map(str, lines))})

    selected = []
    for product_name in protocol['products']:
        members = [row for row in cohort if row['product'] == product_name]
        ranking = sorted(members, key=lambda row: (-row['jan_apr_mean_collaborators'], hash_key(row['customer_id'])))
        top = ranking[:protocol['priority_per_product']]
        comparison = sorted(ranking[protocol['priority_per_product']:],
                            key=lambda row: hash_key(row['customer_id']))[:protocol['comparison_per_product']]
        assert len(top) == 2 and len(comparison) == 2
        selected.extend(dict(row, group=group) for group, rows in
                        [('priority', top), ('comparison', comparison)] for row in rows)
    assert len(selected) == len({row['customer_id'] for row in selected}) == 20
    selection_path = ROOT / 'selection_freeze.json'
    if selection_path.exists():
        assert json.loads(selection_path.read_text(encoding='utf-8'))['selected_without_may'] == selected
    else:
        write_json(selection_path.name, {'frozen_at': datetime.now(timezone.utc).isoformat(),
                                         'selected_without_may': selected})

    # Outcomes are joined only after writing the immutable selection snapshot.
    def outcome(record):
        matches = by_usage[record['customer_id'], record['product'], protocol['outcome_month']]
        try:
            assert len(matches) == 1
            line, row = matches[0]
            return nonnegative_integer(row[protocol['outcome']]), line
        except (AssertionError, ValueError, TypeError):
            return None, None

    for row in selected:
        row['may_collaborators'], row['may_source_row'] = outcome(row)
    write_csv('cases_20.csv', selected)
    observed = all(row['may_collaborators'] is not None for row in selected)
    primary = {'complete': observed, 'interpretation': 'retrospective_association_only'}
    by_product = []
    if observed:
        group_mean = {group: sum(row['may_collaborators'] for row in selected if row['group'] == group) / 10
                      for group in ('priority', 'comparison')}
        difference = group_mean['priority'] - group_mean['comparison']
        allocations = []
        for product_name in protocol['products']:
            rows = [row for row in selected if row['product'] == product_name]
            y = [row['may_collaborators'] for row in rows]
            allocations.append([2 * sum(y[i] for i in choice) - sum(y) for choice in combinations(range(4), 2)])
            means = {group: sum(row['may_collaborators'] for row in rows if row['group'] == group) / 2
                     for group in ('priority', 'comparison')}
            members = [row for row in cohort if row['product'] == product_name]
            remaining = [row for row in members if row['customer_id'] not in
                         {r['customer_id'] for r in rows if r['group'] == 'priority'}]
            pool_values = [outcome(row)[0] for row in remaining]
            valid_values = [value for value in pool_values if value is not None]
            by_product.append({'product': product_name, 'eligible_free_customers': len(members),
                               'priority_may_mean': means['priority'], 'comparison_may_mean': means['comparison'],
                               'difference': means['priority'] - means['comparison'],
                               'remaining_pool_n': len(remaining), 'remaining_pool_valid_may_n': len(valid_values),
                               'remaining_pool_may_mean': sum(valid_values) / len(valid_values) if valid_values else None})
        permuted_differences = [sum(terms) / 10 for terms in product(*allocations)]
        assert len(permuted_differences) == 7776
        p = sum(value >= difference - 1e-12 for value in permuted_differences) / len(permuted_differences)
        primary.update(priority_n=10, comparison_n=10, group_means=group_mean, difference=difference,
                       one_sided_exact_permutation_p=p, permutations=7776,
                       exploratory_proxy_support=bool(difference > 0 and p < 0.05),
                       selected_may_sum={group: sum(row['may_collaborators'] for row in selected
                                                   if row['group'] == group) for group in group_mean})
        write_csv('product_summary.csv', by_product)
    results = {
        'executed_at': datetime.now(timezone.utc).isoformat(), 'dataset_scope': 'competition_csv_only',
        'new_synthetic_observations': 0, 'source_sha256': fingerprints['source_sha256'],
        'selection_sha256': sha(selection_path),
        'source_counts': {'customers': len(customers), 'tickets': len(tickets), 'usage': len(usage)},
        'plan_counts': dict(Counter(row['Plan Type'] for row in customers)),
        'free_source_customers': sum(row['Plan Type'] == 'Free' for row in customers),
        'free_eligible_customers': len(cohort), 'free_exclusions': dict(exclusions),
        'selected_source_records': len(selected), 'primary': primary, 'by_product': by_product,
        'business_outcomes': {'upgrade_observed': False, 'willingness_to_pay_observed': False,
                              'profit_observed': False, 'incremental_profit': None,
                              'status': 'NOT_IDENTIFIABLE_FROM_COMPETITION_DATA'},
        'economic_model': {'formula': 'N * (delta_conversion * net_contribution - contact_cost - other_expected_loss) - fixed_cost',
                           'observed_parameter_values': None,
                           'breakeven_if_N_and_net_contribution_positive':
                           'delta_conversion > (contact_cost + other_expected_loss + fixed_cost / N) / net_contribution'},
        'limitations': ['Static Free plan timing is unknown.', 'Prior tasks have inspected this dataset; not a pristine holdout.',
                       'Collaborators are not observed paid seats, upgrade intentions or profit.',
                       'Hash comparison sampling is not randomized treatment assignment.',
                       'Synthetic support-customer sample; sampling frame and generator unknown.'],
    }
    write_json('results.json', results)
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
