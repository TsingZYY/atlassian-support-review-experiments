"""Independent source/arithmetic audit; never creates human timing observations.

Does not import experiment.py. Ranks are rebuilt by sorting indexed observations
and assigning tie-block midranks; covariance uses math.fsum. Same seeded random
draw streams reproduce the specified experiment, not an independent experiment.
"""
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
import csv
import hashlib
import importlib.util
import itertools
import json
import math
import statistics
import subprocess
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def read_csv(path):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def same(actual, expected, path='value'):
    if isinstance(expected, dict):
        assert set(actual) == set(expected), (path, set(actual) ^ set(expected))
        for key in expected:
            same(actual[key], expected[key], path + '.' + key)
    elif isinstance(expected, list):
        assert len(actual) == len(expected), (path, len(actual), len(expected))
        for i, (a, e) in enumerate(zip(actual, expected)):
            same(a, e, f'{path}[{i}]')
    elif isinstance(expected, float):
        assert isinstance(actual, (int, float)) and math.isclose(actual, expected, rel_tol=1e-11, abs_tol=1e-12), (path, actual, expected)
    else:
        assert actual == expected, (path, actual, expected)


def compare_csv(name, expected):
    saved = read_csv(HERE / name)
    assert len(saved) == len(expected), name
    for row_index, (actual, reference) in enumerate(zip(saved, expected)):
        assert set(actual) == set(reference), (name, row_index)
        for key, value in reference.items():
            label = f'{name}[{row_index}].{key}'
            if value is None:
                assert actual[key] == '', (label, actual[key])
            elif isinstance(value, bool):
                assert actual[key] == str(value), (label, actual[key])
            elif isinstance(value, float):
                same(float(actual[key]), value, label)
            else:
                assert actual[key] == str(value), (label, actual[key], value)


def midranks(values):
    ordered = sorted(enumerate(values), key=lambda pair: pair[1])
    output = [0.0] * len(ordered)
    start = 0
    while start < len(ordered):
        end = start + 1
        while end < len(ordered) and ordered[end][1] == ordered[start][1]:
            end += 1
        rank = ((start + 1) + end) / 2
        for position in range(start, end):
            output[ordered[position][0]] = rank
        start = end
    return output


def pearson(x, y):
    mx, my = statistics.fmean(x), statistics.fmean(y)
    dx, dy = [v - mx for v in x], [v - my for v in y]
    denominator = math.sqrt(math.fsum(v * v for v in dx) * math.fsum(v * v for v in dy))
    return math.fsum(a * b for a, b in zip(dx, dy)) / denominator


def spearman(x, y):
    return pearson(midranks(x), midranks(y))


def interval_95(values):
    ordered = sorted(values)
    def percentile(p):
        location = p * (len(ordered) - 1)
        low = math.floor(location)
        high = math.ceil(location)
        return ordered[low] + (ordered[high] - ordered[low]) * (location - low)
    return [percentile(.025), percentile(.975)]


def resampled_means(values, repetitions, rng):
    # Draw order matches the protocol execution, while sums are explicit.
    values = np.asarray(values, dtype=float)
    indices = rng.integers(0, len(values), (repetitions, len(values)))
    return np.sum(values[indices], axis=1) / len(values)


def independent_cost(volume, fixed_cost, variable_cost_per_ticket, hourly_cost,
                     realizable_fraction, minutes_saved=None):
    total_cost = fixed_cost + volume * variable_cost_per_ticket
    benefit_per_minute = volume * hourly_cost * realizable_fraction / 60
    if benefit_per_minute:
        threshold, state = total_cost / benefit_per_minute, 'FINITE'
    elif total_cost:
        threshold, state = None, 'NO_FINITE_BREAK_EVEN'
    else:
        threshold, state = 0.0, 'ZERO_COST_ZERO_MONETIZED_BENEFIT'
    return {
        'volume': volume, 'fixed_cost': fixed_cost,
        'variable_cost_per_ticket': variable_cost_per_ticket,
        'hourly_cost': hourly_cost, 'realizable_fraction': realizable_fraction,
        'total_extra_cost': total_cost,
        'break_even_minutes_per_ticket': threshold, 'break_even_state': state,
        'assumed_labour_minutes_saved': minutes_saved,
        'conditional_net_profit': None if minutes_saved is None else minutes_saved * benefit_per_minute - total_cost,
        'retention_conversion_contribution': 0, 'actual_profit_measured': False,
        'elapsed_ticket_interval_used_as_labour_saving': False,
    }


def main():
    protocol = read_json(HERE / 'protocol.json')
    saved = read_json(HERE / 'results.json')
    lock = read_json(HERE / 'execution_lock.json')
    assert protocol['timestamp_format'] == '%d-%m-%Y %H:%M'
    assert protocol['permutation_alternative'] == 'two_sided'
    assert protocol['repetitions'] == 5000
    assert protocol['retention_and_conversion_contribution'] == 0
    assert protocol['adjustment_fields'] == ['Product Purchased', 'Ticket Priority']
    verified_hashes = {
        'source_sha256': {name: digest(ROOT / 'data' / name) for name in ('customer_support_tickets.csv', 'customers.csv', 'README.md')},
        'audit_roster_sha256': digest(ROOT / protocol['audit_roster']),
        'protocol_code_sha256': {name: digest(HERE / name) for name in ('protocol.json', 'protocol.md', 'experiment.py', 'cost_model.py')},
    }
    for key, value in verified_hashes.items():
        same(lock[key], value, 'lock.' + key)
        same(saved[key], value, 'results.' + key)

    customers = read_csv(ROOT / 'data/customers.csv')
    tickets = read_csv(ROOT / 'data/customer_support_tickets.csv')
    normal = lambda value: value.strip().casefold()
    customer_map = {normal(c['Customer Email']): c for c in customers}
    assert len(customer_map) == len(customers) == 8320
    assert len(tickets) == len({t['Ticket ID'] for t in tickets}) == 8469
    conflicts = set()
    for ticket in tickets:
        customer = customer_map[normal(ticket['Customer Email'])]
        if any(normal(ticket[field]) != normal(customer[field]) for field in ['Customer Name', 'Customer Age', 'Customer Gender']):
            conflicts.add(customer['Customer ID'])

    records, cohort = [], []
    for source_row, ticket in enumerate(tickets, 2):
        customer_id = customer_map[normal(ticket['Customer Email'])]['Customer ID']
        a, b = ticket['First Response Time'], ticket['Time to Resolution']
        hours = None
        if not a or not b:
            state = 'MISSING_PAIR'
        else:
            try:
                start = datetime.strptime(a, '%d-%m-%Y %H:%M')
                end = datetime.strptime(b, '%d-%m-%Y %H:%M')
            except ValueError:
                state = 'UNPARSEABLE_PAIR'
            else:
                elapsed_minutes = (end - start).total_seconds() / 60
                state = 'REVERSED_PAIR' if elapsed_minutes < 0 else 'ZERO_INTERVAL' if elapsed_minutes == 0 else 'POSITIVE_INTERVAL'
                if elapsed_minutes >= 0:
                    hours = elapsed_minutes / 60
        value = ticket['Customer Satisfaction Rating']
        rating = None if value == '' else int(value)
        assert rating is None or 1 <= rating <= 5
        conflict = customer_id in conflicts
        eligible = ticket['Ticket Status'] == 'Closed' and rating is not None and hours is not None and not conflict
        record = {
            'ticket_id': ticket['Ticket ID'], 'source_row': source_row,
            'customer_id': customer_id, 'time_state': state,
            'interval_hours': hours, 'rating': rating, 'identity_conflict': conflict,
            'primary_eligible': eligible,
            **{field: ticket[field] for field in ('Ticket Status', 'Product Purchased', 'Ticket Type', 'Ticket Priority', 'Ticket Channel', 'First Response Time', 'Time to Resolution')},
        }
        records.append(record)
        if eligible:
            cohort.append(record.copy())
    assert len(conflicts) == 139
    assert len(cohort) == len({r['customer_id'] for r in cohort}) == 1357
    assert Counter(r['time_state'] for r in records) == {'MISSING_PAIR': 5700, 'REVERSED_PAIR': 1365, 'ZERO_INTERVAL': 2, 'POSITIVE_INTERVAL': 1402}
    clean_closed = [r for r in records if r['Ticket Status'] == 'Closed' and not r['identity_conflict']]
    quality = []
    for state in ['MISSING_PAIR', 'UNPARSEABLE_PAIR', 'REVERSED_PAIR', 'ZERO_INTERVAL', 'POSITIVE_INTERVAL']:
        group = [r for r in records if r['time_state'] == state]
        scores = [r['rating'] for r in group if r['rating'] is not None]
        quality.append({'time_state': state, 'n': len(group), 'rating_n': len(scores),
                        'mean_csat': statistics.fmean(scores) if scores else None,
                        **{f'rating_{i}_n': scores.count(i) for i in range(1, 6)}})
    profile = {
        'tickets': len(tickets), 'rated_closed_n': sum(r['Ticket Status'] == 'Closed' and r['rating'] is not None for r in records),
        'identity_conflict_customers': len(conflicts), 'clean_closed_rated_n': len(clean_closed),
        'all_time_state_counts': dict(Counter(r['time_state'] for r in records)),
        'clean_closed_time_state_counts': dict(Counter(r['time_state'] for r in clean_closed)),
        'time_quality': quality, 'primary_n': len(cohort),
    }
    same(saved['profile'], profile, 'profile')
    compare_csv('time_quality.csv', quality)
    print('SOURCE_AND_TIME_QUALITY_PASS', flush=True)

    hours = [r['interval_hours'] for r in cohort]
    scores = [r['rating'] for r in cohort]
    ranked_hours, ranked_scores = midranks(hours), midranks(scores)
    rho = pearson(ranked_hours, ranked_scores)
    rng = np.random.default_rng(protocol['seed'])
    extreme = 0
    for _ in range(protocol['repetitions']):
        value = pearson(ranked_hours, rng.permutation(ranked_scores).tolist())
        extreme += abs(value) >= abs(rho) - 1e-12
    probability = (extreme + 1) / (protocol['repetitions'] + 1)
    rng = np.random.default_rng(protocol['bootstrap_seed'])
    bootstrap = []
    for _ in range(protocol['repetitions']):
        indices = rng.integers(0, len(cohort), len(cohort)).tolist()
        bootstrap.append(spearman([hours[i] for i in indices], [scores[i] for i in indices]))
    primary = {'n': len(cohort), 'spearman_rho': rho, 'bootstrap_95': interval_95(bootstrap),
               'two_sided_permutation_p': probability, 'permutation_extreme_count': extreme,
               'repetitions': protocol['repetitions'], 'shorter_interval_higher_csat_supported': rho < 0 and probability < .05}
    same(saved['primary'], primary, 'primary')
    positive = [r for r in cohort if r['interval_hours'] > 0]
    zero_sensitivity = {'n': len(positive), 'spearman_rho': spearman([r['interval_hours'] for r in positive], [r['rating'] for r in positive])}
    same(saved['excluding_zero_sensitivity'], zero_sensitivity, 'excluding_zero')
    print('PRIMARY_RESAMPLING_PASS', flush=True)

    threshold = statistics.median(hours)
    for r in cohort:
        r['speed_group'] = 'fast' if r['interval_hours'] <= threshold else 'slow'
    group_values, group_summaries = {}, []
    for label in ['fast', 'slow']:
        subset = [r for r in cohort if r['speed_group'] == label]
        a = [r['interval_hours'] for r in subset]
        b = [r['rating'] for r in subset]
        group_values[label] = b
        group_summaries.append({'group': label, 'n': len(subset),
                               'interval_hours_mean': statistics.fmean(a), 'interval_hours_median': statistics.median(a),
                               'rating_sum': sum(b), 'mean_csat': statistics.fmean(b),
                               'low_csat_n': sum(x <= 2 for x in b), 'low_csat_fraction': sum(x <= 2 for x in b) / len(b),
                               'high_csat_n': sum(x >= 4 for x in b), 'high_csat_fraction': sum(x >= 4 for x in b) / len(b)})
    fast, slow = group_values['fast'], group_values['slow']
    rng = np.random.default_rng(protocol['seed'] + 2)
    group_bootstrap = resampled_means(fast, protocol['repetitions'], rng) - resampled_means(slow, protocol['repetitions'], rng)
    strata = defaultdict(lambda: {'fast': [], 'slow': []})
    for r in cohort:
        strata[(r['Product Purchased'], r['Ticket Priority'])][r['speed_group']].append(r['rating'])
    shared_n = sum(len(v['fast']) + len(v['slow']) for v in strata.values() if v['fast'] and v['slow'])
    excluded = [{'stratum': list(k), 'n': len(v['fast']) + len(v['slow'])} for k, v in sorted(strata.items()) if not v['fast'] or not v['slow']]
    details, weighted_terms = [], []
    stratified_bootstrap = np.zeros(protocol['repetitions'])
    rng = np.random.default_rng(protocol['seed'] + 3)
    for key, v in sorted(strata.items()):
        a, b = v['fast'], v['slow']
        if not a or not b:
            continue
        weight = (len(a) + len(b)) / shared_n
        delta = statistics.fmean(a) - statistics.fmean(b)
        weighted_terms.append(weight * delta)
        stratified_bootstrap += weight * (resampled_means(a, protocol['repetitions'], rng) - resampled_means(b, protocol['repetitions'], rng))
        details.append({'product': key[0], 'priority': key[1], 'fast_n': len(a), 'slow_n': len(b),
                        'pooled_weight': weight, 'fast_minus_slow_csat': delta})
    adjusted = {'fields': protocol['adjustment_fields'], 'common_support_n': shared_n,
                'excluded_strata': excluded, 'fast_minus_slow_mean_csat': math.fsum(weighted_terms),
                'bootstrap_95': interval_95(stratified_bootstrap), 'strata': details}
    expected_secondary = {'threshold_hours': threshold, 'fast_rule': 'hours <= threshold',
                          'groups': group_summaries, 'fast_minus_slow_mean_csat': statistics.fmean(fast) - statistics.fmean(slow),
                          'bootstrap_95': interval_95(group_bootstrap), 'adjusted': adjusted,
                          'scope': 'Prespecified descriptive sensitivity; no subgroup significance selection or causal interpretation'}
    same(saved['fast_slow'], expected_secondary, 'fast_slow')
    compare_csv('primary_cohort.csv', cohort)
    compare_csv('fast_slow_summary.csv', group_summaries)
    compare_csv('adjusted_strata.csv', details)
    roster = read_json(ROOT / protocol['audit_roster'])
    by_ticket = {r['ticket_id']: r for r in records}
    audit_rows = [by_ticket[item['ticket_id']] for item in roster]
    assert len(audit_rows) == len({r['ticket_id'] for r in audit_rows}) == 20
    for item, row in zip(roster, audit_rows):
        assert item['source']['record_row'] == row['source_row']
        assert item['csat']['score'] == row['rating']
    audit_counts = dict(Counter(r['time_state'] for r in audit_rows))
    assert audit_counts == {'POSITIVE_INTERVAL': 8, 'REVERSED_PAIR': 7, 'MISSING_PAIR': 5}
    same(saved['audit_time_state_counts'], audit_counts, 'audit_counts')
    assert saved['audit_primary_eligible_n'] == sum(r['primary_eligible'] for r in audit_rows) == 8
    assert saved['audit_cases'] == 20
    compare_csv('audit_cases_20.csv', audit_rows)
    print('SECONDARY_AND_20_SOURCE_CASES_PASS', flush=True)

    grid_keys = list(protocol['cost_grid'])
    grid = [independent_cost(**dict(zip(grid_keys, values)), minutes_saved=protocol['illustrative_minutes_saved'])
            for values in itertools.product(*(protocol['cost_grid'][k] for k in grid_keys))]
    assert len(grid) == 144
    compare_csv('cost_break_even_grid.csv', grid)
    base = protocol['cost_base']
    baseline = independent_cost(**base)
    examples = []
    for scenario, overrides in [('base', {}), ('half_realizable', {'realizable_fraction': .5}),
                                 ('no_realizable_saving', {'realizable_fraction': 0}), ('twenty_ticket_volume', {'volume': 20})]:
        examples.append({'scenario': scenario, **independent_cost(**{**base, **overrides}, minutes_saved=protocol['illustrative_minutes_saved'])})
    compare_csv('cost_examples.csv', examples)
    costs = read_json(HERE / 'cost_results.json')
    same(costs['base_no_observed_time_saving'], baseline, 'cost_base')
    same(costs['examples'], examples, 'cost_examples')
    assert costs['grid_rows'] == 144
    assert costs['parameter_status'] == 'EXPLICIT_UNCALIBRATED_ASSUMPTIONS'
    assert costs['unit'] == protocol['cost_unit']
    assert costs['measured_labour_minutes_saved'] is None
    assert costs['measured_profit_effect'] is None
    assert costs['retention_and_conversion_contribution'] == 0
    assert costs['ticket_interval_used_as_labour_saving'] is False

    # Only cost_model is imported for API checks; expected values above are independent.
    spec = importlib.util.spec_from_file_location('audited_cost_model', HERE / 'cost_model.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    api_cases = [({}, None), ({}, 2), ({'volume': 20}, 2), ({'realizable_fraction': 0}, 2),
                 ({'realizable_fraction': .5}, 2), ({'hourly_cost': 0}, 2),
                 ({'fixed_cost': 0, 'variable_cost_per_ticket': 0, 'realizable_fraction': 0}, 2),
                 ({'fixed_cost': 0, 'variable_cost_per_ticket': 0}, 0), ({}, -2)]
    for overrides, minutes in api_cases:
        params = {**base, **overrides, 'minutes_saved': minutes}
        same(module.calculate(**params), independent_cost(**params), 'cost_api')
    invalid = [{'volume': 0}, {'volume': -1}, {'volume': 1.5}, {'volume': float('inf')},
               {'fixed_cost': -1}, {'variable_cost_per_ticket': -1}, {'hourly_cost': -1},
               {'realizable_fraction': -0.1}, {'realizable_fraction': 1.1},
               {'fixed_cost': float('nan')}, {'minutes_saved': float('nan')}, {'minutes_saved': float('inf')}]
    for overrides in invalid:
        try:
            module.calculate(**{**base, **overrides})
        except ValueError:
            pass
        else:
            raise AssertionError(('invalid_cost_input_accepted', overrides))
    cli_cases = [([], baseline),
                 (['--realizable-fraction', '0', '--minutes-saved', '2'], independent_cost(**{**base, 'realizable_fraction': 0}, minutes_saved=2)),
                 (['--volume', '20', '--minutes-saved', '2'], independent_cost(**{**base, 'volume': 20}, minutes_saved=2)),
                 (['--minutes-saved', '-2'], independent_cost(**base, minutes_saved=-2))]
    for options, expected in cli_cases:
        completed = subprocess.run([sys.executable, str(HERE / 'cost_model.py'), *options], check=True, capture_output=True, text=True)
        same(json.loads(completed.stdout), expected, 'cost_cli')
    rejected_cli = subprocess.run([sys.executable, str(HERE / 'cost_model.py'), '--volume', '0'], capture_output=True, text=True)
    assert rejected_cli.returncode != 0 and 'positive integer' in rejected_cli.stderr
    assert saved['dataset_scope'] == 'competition_csv_only' and saved['new_synthetic_observations'] == 0
    assert saved['full_resolution_duration_available'] is False
    assert saved['labour_time_available'] is False
    assert saved['human_review_efficiency_measured'] is False
    assert saved['causal_csat_improvement'] is None
    assert saved['measured_profit_effect'] is None

    report = {
        'status': 'PASS_WITH_STATED_SCOPE',
        'audit_kind': 'independent_source_and_arithmetic_reimplementation_not_blinded',
        'experiment_module_imported': False,
        'source_and_protocol_hashes_verified': verified_hashes,
        'auditor_script_sha256': digest(Path(__file__)),
        'source_ticket_rows_checked': len(tickets),
        'primary_cohort_rows_checked': len(cohort),
        'independently_recomputed_primary': primary,
        'resampling_note': 'Independent rank/correlation/percentile implementation; same NumPy seeded random draws as protocol; not an independent sample or experiment.',
        'fast_slow_group_n': {r['group']: r['n'] for r in group_summaries},
        'fast_slow_delta': expected_secondary['fast_minus_slow_mean_csat'],
        'fast_slow_bootstrap_95': expected_secondary['bootstrap_95'],
        'adjusted_strata_checked': len(details),
        'adjusted_delta': adjusted['fast_minus_slow_mean_csat'],
        'adjusted_bootstrap_95': adjusted['bootstrap_95'],
        'audit_cases_checked': len(audit_rows), 'audit_time_state_counts': audit_counts,
        'cost_grid_rows_checked': len(grid), 'cost_examples_checked': len(examples),
        'cost_api_valid_cases': len(api_cases), 'cost_api_invalid_cases': len(invalid),
        'cost_cli_success_cases': len(cli_cases), 'cost_cli_rejection_cases': 1,
        'observed_human_time_or_profit_created': False,
        'limitations': [
            'Code and primary output were visible to the auditor; this is not a blinded review.',
            'Hash equality verifies current inputs/code match execution_lock, not that no analyst had previously seen the data.',
            'Only ordered, rated Closed tickets with consistent customer identity enter the association; selection and confounding remain.',
            'Calendar interval is not labour effort, complete resolution duration, or an intervention effect.',
            'Twenty cases audit source records only; no human timed review or customer problem-solving trial was performed.',
            'All cost parameters and two-minute savings are explicit uncalibrated assumptions; actual efficiency and profit are unknown.',
        ],
    }
    (HERE / 'independent_audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8', newline='\n')
    markdown = f'''# 独立复核：解决时间与满意度

结论：在下述范围内通过。独立脚本从比赛原始 CSV 重建队列，不导入 experiment.py；主源码及结果已向审核者可见，因此不是盲审。没有进行真人计时复核，也没有制造模拟客户结果。

- 核验全部 {len(tickets):,} 张工单的时间状态、评分与身份关联；重建 {len(cohort):,} 位一人一票的主队列，逐行核对保存的主队列 CSV。
- 用排序后的并列中秩及 fsum 协方差公式复算 Spearman；按固定随机种子重跑 5,000 次双侧置换和 5,000 次成对 bootstrap，使用独立线性插值分位数。
- Spearman = {rho:.12f}，置换极端次数 {extreme}/5000，p = {probability:.12f}；95% 区间 {primary['bootstrap_95']}。结果不支持较短间隔对应更高满意度。
- 快慢组 {len(fast)}/{len(slow)} 人，快减慢均分差 {expected_secondary['fast_minus_slow_mean_csat']:.12f}；复核其 bootstrap 及全部 {len(details)} 个 Product × Priority 分层的加权差和 bootstrap。
- 保留原 20 条票号及顺序，逐字段核对时间、评分、来源行号和资格：8 条正间隔、7 条逆序、5 条缺失；无换样。
- 独立核算 144 格成本表及 4 个固定示例，并检查成本 API 的 {len(api_cases)} 个有效边界、{len(invalid)} 个无效输入、CLI 的 {len(cli_cases)} 次成功及 1 次拒绝。
- 基准条件阈值 1.2 分钟；兑现比例 0.5 时 2.4 分钟；兑现比例 0 且成本为正时无有限阈值；计划 20 票时 11 分钟。假设每票节省 2 分钟时条件净额依次为 400、-100、-600、-90。这些不是实测利润。
- 核对执行锁中的输入、协议和主代码哈希。哈希一致仅说明当前文件与锁定版本一致，不证明分析者此前从未见过数据。

复现：`python resolution_csat_v1/independent_verify.py`

限制：固定种子复算验证执行正确性，不是新的独立样本。约半数配对时间逆序、未关闭票缺评分，以及难度等混杂限制业务外推。观察间隔不等于人工劳动时间，不能填入节省分钟。20 条用于来源审核，不是人工效率实验；实测效率、因果满意度提升与利润均保持未知。
'''
    (HERE / 'independent_audit.md').write_text(markdown, encoding='utf-8', newline='\n')
    print(json.dumps({'status': report['status'], 'primary_n': len(cohort), 'rho': rho, 'p': probability, 'cost_grid_rows': len(grid), 'human_observations_created': False}, ensure_ascii=False))


if __name__ == '__main__':
    main()
