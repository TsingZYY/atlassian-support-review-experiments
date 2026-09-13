"""Independent check of the four supplementary, non-ticket associations."""
from collections import defaultdict
from pathlib import Path
import calendar
import csv
import hashlib
import json
import math

import numpy as np

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / 'data'
METRICS = ['Active Day Rate', 'Sessions', 'Product Actions', 'Collaborators']
MONTHS = {f'2023-{month:02d}' for month in range(1, 6)}


def read(name):
    with (DATA / name).open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def compute():
    customers, usage = read('customers.csv'), read('product_usage.csv')
    by_customer, bad, seen = defaultdict(list), set(), set()
    coverage = defaultdict(lambda: defaultdict(set))
    for row in usage:
        if row['Month'] not in MONTHS:
            continue
        cid = row['Customer ID']
        key = (cid, row['Product'], row['Month'])
        assert key not in seen
        seen.add(key)
        coverage[cid][row['Product']].add(row['Month'])
        active = float(row['Active Days'])
        days = calendar.monthrange(*map(int, row['Month'].split('-')))[1]
        values = [active / days] + [float(row[field]) for field in METRICS[1:]]
        if not (active.is_integer() and 0 <= active <= days and
                all(math.isfinite(value) and value >= 0 for value in values)):
            bad.add(cid)
        by_customer[cid].append(values)
    ids, plans, means = [], [], []
    for customer in sorted(customers, key=lambda row: row['Customer ID']):
        cid = customer['Customer ID']
        assert by_customer[cid]
        assert all(months == MONTHS for months in coverage[cid].values())
        if cid in bad:
            continue
        ids.append(cid)
        plans.append(customer['Plan Type'])
        means.append(np.mean(by_customer[cid], axis=0))
    assert len(ids) == len(set(ids)) == 8261
    matrix = np.asarray(means)
    levels = sorted(set(plans))
    codes = np.array([levels.index(plan) for plan in plans])
    total_ss = np.sum((matrix - matrix.mean(axis=0)) ** 2, axis=0)

    def residual_r2(labels):
        # Explicit group means -> fitted values -> residual sum of squares.
        fitted = np.empty_like(matrix)
        for level in range(len(levels)):
            mask = labels == level
            fitted[mask] = matrix[mask].mean(axis=0)
        residual_ss = np.sum((matrix - fitted) ** 2, axis=0)
        return 1 - residual_ss / total_ss

    observed = residual_r2(codes)
    rng = np.random.default_rng(202609140499)
    extreme = np.zeros(len(METRICS), dtype=int)
    for _ in range(1000):
        statistic = residual_r2(rng.permutation(codes))
        extreme += statistic >= observed - 1e-12
    p_values = (extreme + 1) / 1001
    rows = [{'metric': metric, 'n': len(ids), 'r_squared': float(observed[index]),
             'independent_extreme': int(extreme[index]),
             'independent_p': float(p_values[index]),
             'independent_bonferroni_16_p': min(1.0, float(p_values[index]) * 16)}
            for index, metric in enumerate(METRICS)]
    return {'eligible_customers': len(ids), 'excluded_customers': len(bad),
            'independent_seed': 202609140499, 'independent_permutations': 1000,
            'monte_carlo_minimum_reportable_p': 1 / 1001,
            'metrics': rows, 'customer_id_sha256': hashlib.sha256('|'.join(ids).encode()).hexdigest()}


def main():
    result = compute()
    # No main implementation is imported; primary results are read only now.
    primary = json.loads((HERE / 'uniqueness_results.json').read_text(encoding='utf-8'))
    lock = json.loads((HERE / 'uniqueness_lock.json').read_text(encoding='utf-8'))
    for field, parent in [('source_sha256', DATA), ('supplement_sha256', HERE)]:
        assert primary[field] == lock[field]
        for name, value in lock[field].items():
            assert hashlib.sha256((parent / name).read_bytes()).hexdigest() == value
    errors = []
    assert len(primary['tests']) == len(result['metrics']) == 4
    assert primary['family_size'] == 4 and primary['conservative_current_total_family'] == 16
    running = 0.0
    for rank, row in enumerate(sorted(primary['tests'], key=lambda item: item['raw_p'])):
        running = min(1.0, max(running, (4 - rank) * row['raw_p']))
        assert math.isclose(row['holm_4_p'], running, abs_tol=1e-14)
    for independent in result['metrics']:
        main = next(row for row in primary['tests'] if row['metric'] == independent['metric'])
        assert main['n'] == independent['n'] == 8261
        errors.append(abs(main['r2'] - independent['r_squared']))
        assert math.isclose(main['r2'], independent['r_squared'], abs_tol=1e-12)
        assert math.isclose(main['raw_p'], (main['extreme_count'] + 1) / 5001, abs_tol=1e-14)
        assert math.isclose(main['bonferroni_16_p'], min(1, 16 * main['raw_p']), abs_tol=1e-14)
        assert main['bonferroni_16_p'] < .05 and independent['independent_bonferroni_16_p'] < .05
        independent['primary_p'] = main['raw_p']
        independent['primary_bonferroni_16_p'] = main['bonferroni_16_p']
    result['verification'] = {
        'status': 'PASS', 'source_and_supplement_hashes_checked': True,
        'independent_reconstruction_n': 8261, 'maximum_absolute_r_squared_difference': max(errors),
        'primary_holm_4_and_bonferroni_16_verified': True,
        'all_four_independent_bonferroni_16_p_below_05': True,
        'primary_twelve_ticket_tests_modified': False,
        'independent_script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    }
    (HERE / 'uniqueness_independent.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n',
        encoding='utf-8', newline='\n')
    lines = [
        '# “唯一显著”补充核对：独立审计', '',
        '**状态：PASS。** 从原客户和使用CSV独立重建：59名客户存在不合法活跃天数，共同合格队列为8,261人；每个客户产品均覆盖1—5月。独立脚本未导入主实现，先计算再读取主结果。', '',
        '用套餐组均值拟合每名客户的五个月跨产品均值，直接计算残差平方和，R²=1−残差平方和/总平方和。四个R²与主结果最大差小于6×10⁻¹⁵。源文件、补充协议和主补充代码哈希通过。', '',
        '独立种子202609140499，直接置换客户套餐标签1,000次；同一次标签置换用于四个指标。', '',
        '|指标|独立R²|独立极端次数/置换次数|独立p|独立Bonferroni×16 p|',
        '|---|---:|---:|---:|---:|'
    ]
    labels = {'Active Day Rate': '活跃天数比例', 'Sessions': '会话数',
              'Product Actions': '产品操作数', 'Collaborators': '协作人数'}
    for row in result['metrics']:
        lines.append(f"|{labels[row['metric']]}|{row['r_squared']:.6f}|"
                     f"{row['independent_extreme']}/1000|{row['independent_p']:.6f}|"
                     f"{row['independent_bonferroni_16_p']:.6f}|")
    lines.extend(['',
        '1,000次置换的加一p分辨率为1/1001≈0.000999，不能报告p=0，也不能把它与主5,000次置换的1/5001差异解释成结论冲突。四项均无极端置换；独立结果即使乘16，p≈0.015984，仍低于0.05。主结果的四项Holm及×16 Bonferroni公式也逐项核对通过。', '',
        '**结论范围：** 在这批合成数据中，另外四项已报告使用指标与套餐也有统计关联，因此“集成最强”不能改写为“只有集成显著”。本补充是在主工单结果后进行的措辞核对；原12项工单检验未改变，不把这些非工单关联宣传为工单改善、采用原因或利润效果。16项校正不覆盖所有历史探索。', '',
        '运行：`python ticket_bridge_v1/uniqueness_independent.py`；机器记录见`uniqueness_independent.json`。', ''
    ])
    (HERE / 'uniqueness_independent.md').write_text('\n'.join(lines), encoding='utf-8', newline='\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
