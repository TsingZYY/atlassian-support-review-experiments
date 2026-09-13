"""Independent raw-CSV reconstruction; does not import the primary experiment.

Point estimates and direct-label permutations are calculated before primary
outputs are opened. The primary bootstrap is intentionally not rerun here.
"""
from collections import Counter, defaultdict
from pathlib import Path
import csv
import hashlib
import json
import math
import statistics

import numpy as np

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / 'data'


def read_csv(path):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def norm(value):
    return value.strip().casefold()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def calculate():
    protocol = json.loads((HERE / 'protocol.json').read_text(encoding='utf-8'))
    customers = read_csv(DATA / 'customers.csv')
    tickets = read_csv(DATA / 'customer_support_tickets.csv')
    usage = read_csv(DATA / 'product_usage.csv')
    by_email, by_usage = defaultdict(list), defaultdict(list)
    for line, customer in enumerate(customers, 2):
        by_email[norm(customer['Customer Email'])].append((line, customer))
    for line, row in enumerate(usage, 2):
        by_usage[row['Customer ID'], row['Product'], row['Month']].append((line, row))
    candidates, conflicted, unmatched = [], set(), 0
    all_ticket_customers = set()
    for ticket_line, ticket in enumerate(tickets, 2):
        matches = by_email[norm(ticket['Customer Email'])]
        if len(matches) != 1:
            unmatched += 1
            continue
        customer_line, customer = matches[0]
        cid = customer['Customer ID']
        all_ticket_customers.add(cid)
        if any(norm(customer[field]) != norm(ticket[field])
               for field in ('Customer Name', 'Customer Age', 'Customer Gender')):
            conflicted.add(cid)
        candidates.append((customer_line, customer, ticket_line, ticket))
    records, invalid_usage = [], []
    for customer_line, customer, ticket_line, ticket in candidates:
        if customer['Customer ID'] in conflicted:
            continue
        values, lines = [], []
        for month in protocol['months']:
            found = by_usage[customer['Customer ID'], ticket['Product Purchased'], month]
            if len(found) != 1:
                invalid_usage.append((ticket['Ticket ID'], month, 'missing_or_duplicate'))
                break
            source_line, row = found[0]
            value = float(row['Integrations Used'])
            if not math.isfinite(value) or value < 0 or not value.is_integer():
                invalid_usage.append((ticket['Ticket ID'], month, 'invalid_integer'))
                break
            values.append(int(value))
            lines.append(source_line)
        if len(values) != len(protocol['months']):
            continue
        rating = ticket['Customer Satisfaction Rating'].strip()
        valid_rating = bool(rating) and float(rating).is_integer() and 1 <= float(rating) <= 5
        low_csat = int(float(rating) <= 2) if ticket['Ticket Status'] == 'Closed' and valid_rating else None
        records.append({**ticket, 'customer_id': customer['Customer ID'],
                        'Plan Type': customer['Plan Type'],
                        'customer_source_row': customer_line,
                        'ticket_source_row': ticket_line,
                        'usage_source_rows': lines,
                        'integration_month_values': values,
                        'mean_integrations': statistics.mean(values),
                        'rating': int(float(rating)) if valid_rating else None,
                        'low_csat': low_csat,
                        'cancellation_request': int(ticket['Ticket Type'] == 'Cancellation request'),
                        'technical_issue': int(ticket['Ticket Type'] == 'Technical issue'),
                        'not_closed': int(ticket['Ticket Status'] != 'Closed')})
    assert len(records) == len({row['customer_id'] for row in records}) == 8181
    peers = defaultdict(list)
    for row in records:
        peers[row['Product Purchased'], row['Plan Type']].append(row)
    peer_summary = []
    for (product, plan), rows in sorted(peers.items()):
        median = statistics.median(row['mean_integrations'] for row in rows)
        for row in rows:
            row['peer_median_integrations'] = median
            row['low_integration'] = int(row['mean_integrations'] < median)
        peer_summary.append({'product': product, 'plan': plan, 'n': len(rows),
                             'median_integrations': median,
                             'low_n': sum(row['low_integration'] for row in rows),
                             'ties_n': sum(row['mean_integrations'] == median for row in rows)})
    screens = []
    for feature, outcome in protocol['category_screens']:
        groups = defaultdict(list)
        for row in records:
            if row[outcome] is not None:
                groups[row[feature]].append(row[outcome])
        table = [{'category': name, 'n': len(values), 'events': sum(values)}
                 for name, values in sorted(groups.items())]
        n = sum(row['n'] for row in table)
        events = sum(row['events'] for row in table)
        pooled = events / n
        chi_square = sum((row['events'] - row['n'] * pooled) ** 2 /
                         (row['n'] * pooled * (1 - pooled)) for row in table)
        screens.append({'feature': feature, 'outcome': outcome, 'n': n, 'events': events,
                        'chi_square': chi_square, 'cramers_v': math.sqrt(chi_square / n),
                        'table': table})
    bridges = []
    repetitions = 5000
    for outcome_index, outcome in enumerate(protocol['bridge_outcomes']):
        rng = np.random.default_rng(202609140401 + outcome_index)
        strata = []
        for (product, plan), rows in sorted(peers.items()):
            eligible = [row for row in rows if row[outcome] is not None]
            low = [row[outcome] for row in eligible if row['low_integration']]
            other = [row[outcome] for row in eligible if not row['low_integration']]
            assert low and other, 'Missing common support must be handled explicitly.'
            strata.append({'product': product, 'plan': plan, 'n': len(eligible),
                           'low_n': len(low), 'low_events': sum(low),
                           'comparison_n': len(other), 'comparison_events': sum(other),
                           'risk_difference': statistics.mean(low) - statistics.mean(other)})
        n = sum(row['n'] for row in strata)
        effect = sum(row['n'] / n * row['risk_difference'] for row in strata)
        randomized_effects = np.zeros(repetitions)
        for stratum in strata:
            low_n, other_n = stratum['low_n'], stratum['comparison_n']
            successes = stratum['low_events'] + stratum['comparison_events']
            labels = np.concatenate((np.ones(successes, dtype=np.uint8),
                                     np.zeros(stratum['n'] - successes, dtype=np.uint8)))
            # Actually shuffle every customer's binary label within each stratum.
            randomized_low_events = np.array([
                rng.permutation(labels)[:low_n].sum() for _ in range(repetitions)
            ], dtype=float)
            randomized_effects += stratum['n'] / n * (
                randomized_low_events / low_n - (successes - randomized_low_events) / other_n)
        extreme = int(np.count_nonzero(np.abs(randomized_effects) >= abs(effect) - 1e-12))
        low_n = sum(row['low_n'] for row in strata)
        low_events = sum(row['low_events'] for row in strata)
        other_n = sum(row['comparison_n'] for row in strata)
        other_events = sum(row['comparison_events'] for row in strata)
        bridges.append({'outcome': outcome, 'n': n, 'events': low_events + other_events,
                        'standardized_low_rate': sum(row['n'] / n * row['low_events'] / row['low_n']
                                                     for row in strata),
                        'standardized_comparison_rate': sum(row['n'] / n * row['comparison_events'] /
                                                            row['comparison_n'] for row in strata),
                        'standardized_risk_difference': effect,
                        'low_n': low_n, 'low_events': low_events,
                        'comparison_n': other_n, 'comparison_events': other_events,
                        'permutation_seed': 202609140401 + outcome_index,
                        'permutations': repetitions, 'permutation_extreme': extreme,
                        'independent_permutation_p': (extreme + 1) / (repetitions + 1),
                        'strata': strata})
    audit_records = []
    for product in protocol['products']:
        for group in (1, 0):
            selected = [row for row in records if row['Product Purchased'] == product
                        and row['low_integration'] == group]
            selected.sort(key=lambda row: hashlib.sha256(
                (protocol['audit_salt'] + '|' + row['customer_id']).encode()).hexdigest())
            audit_records.extend(selected[:protocol['audit_per_product_per_group']])
    summary = {'source_counts': {'customers': len(customers), 'tickets': len(tickets), 'usage': len(usage)},
               'unique_customer_emails': len(by_email),
               'all_customers_with_tickets': len(all_ticket_customers),
               'unmatched_tickets': unmatched, 'identity_conflict_customers': len(conflicted),
               'identity_conflict_tickets': sum(customer['Customer ID'] in conflicted
                                              for _, customer, _, _ in candidates),
               'eligible_customers': len(records), 'eligible_tickets': len(records),
               'invalid_or_incomplete_integration_records': invalid_usage,
               'rated_closed_n': sum(row['low_csat'] is not None for row in records),
               'low_integration_n': sum(row['low_integration'] for row in records),
               'peer_summary': peer_summary, 'category_screens': screens, 'bridges': bridges,
               'independent_audit_customer_ids': sorted(row['customer_id'] for row in audit_records),
               'bootstrap_independently_recomputed': False}
    return summary, audit_records


def check_primary(summary, audit_records):
    primary = json.loads((HERE / 'results.json').read_text(encoding='utf-8'))
    lock = json.loads((HERE / 'execution_lock.json').read_text(encoding='utf-8'))
    numerical_errors = []

    def close(actual, expected):
        numerical_errors.append(abs(actual - expected))
        assert math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-12), (actual, expected)

    for field, parent in [('source_sha256', DATA), ('protocol_code_sha256', HERE)]:
        assert primary[field] == lock[field]
        for name, expected in lock[field].items():
            assert digest(parent / name) == expected, f'Hash mismatch: {name}'
    quality = primary['quality']
    assert quality['eligible_unique_customers'] == summary['eligible_customers'] == 8181
    assert quality['valid_rated_closed'] == summary['rated_closed_n'] == 2663
    assert quality['identity_conflict_customers'] == summary['identity_conflict_customers'] == 139
    assert quality['exclusions'] == {'identity_conflict_ticket': summary['identity_conflict_tickets']}
    assert summary['identity_conflict_tickets'] == 288
    assert quality['complete_same_product_integration_history'] == 8181
    assert quality['all_source_customers_have_tickets'] and summary['all_customers_with_tickets'] == 8320
    assert primary['peer_summary'] == summary['peer_summary']
    assert summary['invalid_or_incomplete_integration_records'] == []
    main_tests = primary['tests']
    assert len(main_tests) == primary['test_family_size'] == 12
    for computed in summary['category_screens']:
        main = next(row for row in main_tests if row['feature'] == computed['feature']
                    and row['outcome'] == computed['outcome'])
        for key in ('n', 'events'):
            assert main[key] == computed[key]
        close(main['pearson_chi_square'], computed['chi_square'])
        close(main['cramers_v'], computed['cramers_v'])
        assert [{key: row[key] for key in ('category', 'n', 'events')} for row in main['table']] == computed['table']
        for row in main['table']:
            close(row['rate'], row['events'] / row['n'])
    bridge_main_by_outcome = {row['outcome']: row for row in main_tests
                              if row['kind'] == 'stratified_integration_bridge'}
    for computed in summary['bridges']:
        main = bridge_main_by_outcome[computed['outcome']]
        assert main['excluded_strata'] == []
        for key in ('n', 'events'):
            assert main[key] == computed[key]
        for key in ('standardized_risk_difference', 'standardized_low_rate', 'standardized_comparison_rate'):
            close(main[key], computed[key])
        for main_row, row in zip(main['strata'], computed['strata'], strict=True):
            assert (main_row['product'], main_row['plan']) == (row['product'], row['plan'])
            for main_key, key in [('low_n', 'low_n'), ('low_events', 'low_events'),
                                  ('other_n', 'comparison_n'), ('other_events', 'comparison_events')]:
                assert main_row[main_key] == row[key]
            close(main_row['pooled_weight'], row['n'] / computed['n'])
        for main_row in main['unadjusted_groups']:
            prefix = 'low' if main_row['low_integration'] else 'comparison'
            assert main_row['n'] == computed[prefix + '_n']
            assert main_row['events'] == computed[prefix + '_events']
            close(main_row['unadjusted_rate'], computed[prefix + '_events'] / computed[prefix + '_n'])
        a, b = computed['independent_permutation_p'], main['raw_p']
        combined_mc_se = math.sqrt(a * (1 - a) / 5000 + b * (1 - b) / 5000)
        z = abs(a - b) / combined_mc_se
        # The two randomizations use distinct seeds and different samplers.
        assert z < 4, f'Permutation disagreement requires investigation: {computed["outcome"]}'
        computed.update(primary_permutation_p=b, monte_carlo_difference=a-b,
                        combined_monte_carlo_se=combined_mc_se,
                        absolute_mc_z=z, agreement_within_four_mc_se=True)
    ordered = sorted(main_tests, key=lambda row: row['raw_p'])
    corrected, running = {}, 0.0
    for rank, row in enumerate(ordered):
        close(row['raw_p'], (row['permutation_extreme_count'] + 1) / 5001)
        running = min(1.0, max(running, (12 - rank) * row['raw_p']))
        corrected[row['id']] = running
        close(row['holm_p'], running)
        assert row['supported_after_holm'] == (running < 0.05)
    assert primary['holm_supported_n'] == sum(p < .05 for p in corrected.values()) == 0
    # Replace only the four bridge p values to check decision stability; this
    # is not a fully independent rerun of the eight categorical permutations.
    replacement = [dict(row) for row in main_tests]
    for row in replacement:
        if row['kind'] == 'stratified_integration_bridge':
            row['raw_p'] = next(item['independent_permutation_p'] for item in summary['bridges']
                                if item['outcome'] == row['outcome'])
    replacement_holm, running = {}, 0.0
    for rank, row in enumerate(sorted(replacement, key=lambda row: row['raw_p'])):
        running = min(1.0, max(running, (12 - rank) * row['raw_p']))
        replacement_holm[row['id']] = running
    assert sum(p < .05 for p in replacement_holm.values()) == 0
    published_audit = read_csv(HERE / 'audit_cases_20.csv')
    assert len(published_audit) == len(audit_records) == 20
    assert [row['customer_id'] for row in published_audit] == [row['customer_id'] for row in audit_records]
    verified_fields = 0
    for main_row, row in zip(published_audit, audit_records, strict=True):
        for field, actual in main_row.items():
            source_key = 'Ticket ID' if field == 'ticket_id' else field
            expected = row[source_key]
            if field in ('usage_source_rows', 'integration_month_values'):
                assert [int(value) for value in actual.split('|')] == expected
            elif expected is None:
                assert actual == ''
            elif isinstance(expected, (int, float)):
                close(float(actual), expected)
            else:
                assert actual == expected
            verified_fields += 1
    return {'status': 'PASS', 'primary_output_hashes_checked': True,
            'source_and_frozen_protocol_code_hashes_checked': True,
            'all_20_peer_strata_checked': True, 'categorical_point_estimates_checked': 8,
            'bridge_point_estimates_and_all_stratum_counts_checked': 4,
            'independent_direct_label_permutations_per_bridge': 5000,
            'categorical_permutations_independently_recomputed': False,
            'bootstrap_independently_recomputed': False,
            'holm_recalculated_from_all_12_primary_p_values': corrected,
            'holm_with_four_independent_bridge_p_values': replacement_holm,
            'supported_after_holm_n': 0,
            'source_audit_cases_checked': 20, 'source_audit_fields_checked': verified_fields,
            'maximum_absolute_numerical_difference': max(numerical_errors),
            'audit_script_sha256': digest(Path(__file__))}


def main():
    summary, audit_records = calculate()
    # Primary outputs are deliberately read only after independent calculations.
    summary['verification'] = check_primary(summary, audit_records)
    (HERE / 'independent_audit.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + '\n',
        encoding='utf-8', newline='\n')
    lines = [
        '# 工单与集成桥接：独立复核', '',
        '**状态：PASS。** 独立脚本直接重建原三张CSV，没有导入主实验代码；先计算独立结果，再读取主输出核对。', '',
        '- 8,320客户、8,469票、42,210使用月记录；139客户身份冲突涉及288票；保留8,181客户各一票。',
        '- 同产品1—5月集成记录全部完整且有效；2,663人已关闭且有效评分。20个产品×套餐中位数与低集成分组全部一致。',
        '- 独立复算8项列联表的全部分子、分母、Pearson卡方和Cramér V；4项桥接的80个分层计数、权重、标准化两组率及率差全部一致。',
        '- 四个原始数据/字典文件以及冻结协议、主代码的SHA-256均与锁定记录一致。20条哈希抽样记录及全部420字段通过逐项核对。', '',
        '四项桥接另使用独立随机种子，实际在每层洗牌客户二元结局，每项5,000次；与主脚本超几何抽样比较如下。', '',
        '|结局|标准化率差（低集成减比较组）|主置换p|独立置换p|两次p差距/合并MC标准误|',
        '|---|---:|---:|---:|---:|'
    ]
    labels = {'low_csat': '低满意度', 'cancellation_request': '取消请求',
              'technical_issue': '技术问题类型', 'not_closed': '快照未关闭'}
    for row in summary['bridges']:
        lines.append(f"|{labels[row['outcome']]}|{row['standardized_risk_difference'] * 100:+.4f}个百分点|"
                     f"{row['primary_permutation_p']:.6f}|{row['independent_permutation_p']:.6f}|{row['absolute_mc_z']:.3f}|")
    lines.extend(['',
        '差距均在4个合并蒙特卡洛标准误以内，且保留全部12项统一Holm后的0项通过结论。原12项p的Holm计算逐项核实；将其中4项桥接p替换为独立置换结果后，仍0项通过。', '',
        '**保留反例：** 取消请求差异为负，低集成组反而更低；其原始p约0.015，但12项Holm后约0.185，不能宣传低集成增加取消风险，也不能宣布取消风险确实降低。', '',
        '**独立复核边界：** 未独立重跑八项类别置换或bootstrap区间。八项类别统计量及全部计数已独立复算，主置换p的极端次数加一公式和所有Holm值已核查；区间仍为主实现生成的逐项95%区间，不是同时覆盖区间。', '',
        '此结论只适用于比赛合成数据的截面关联。未关闭不等于失败，取消请求不等于实际流失，所有客户已有工单，无法估计产生工单的风险。未显著不证明无关系，有限12项不能证明全数据只有套餐与集成显著。', '',
        '运行：`python ticket_bridge_v1/independent_verify.py`。机器记录见`independent_audit.json`。', ''
    ])
    (HERE / 'independent_audit.md').write_text('\n'.join(lines), encoding='utf-8', newline='\n')
    print(json.dumps({'status': summary['verification']['status'],
                      'independent_calculation_complete': True,
                      'eligible_customers': summary['eligible_customers'],
                      'bridge_points': [{key: row[key] for key in
                                        ('outcome', 'standardized_risk_difference', 'independent_permutation_p')}
                                       for row in summary['bridges']]}, indent=2))


if __name__ == '__main__':
    main()
