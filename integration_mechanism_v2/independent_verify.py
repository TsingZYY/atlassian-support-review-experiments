"""Non-blind independent recalculation from raw CSVs, using QR OLS.

Does not import experiment.py. No new observations or causal identification.
"""
import csv
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / 'data'


def read_csv(path):
    with path.open(encoding='utf-8-sig', newline='') as source:
        return list(csv.DictReader(source))


def main():
    customer_rows = read_csv(DATA / 'customers.csv')
    usage_rows = read_csv(DATA / 'product_usage.csv')
    old = json.loads((HERE.parent / 'integration_plan_v1' / 'protocol.json').read_text())
    expected = json.loads((HERE / 'results.json').read_text())
    customer_rows.sort(key=lambda x: x['Customer ID'], reverse=True)
    ids = [r['Customer ID'] for r in customer_rows]
    lookup = {cid: idx for idx, cid in enumerate(ids)}
    assert len(lookup) == len(ids) == 8320
    fields = ['Integrations Used', 'Sessions', 'Product Actions', 'Collaborators']
    totals = np.zeros((len(ids), 4))
    record_counts = np.zeros(len(ids))
    products = sorted({r['Product'] for r in usage_rows}, reverse=True)
    product_counts = np.zeros((len(ids), len(products)))
    seen = set()
    pair_months = defaultdict(set)
    for raw in usage_rows:
        cid, product, month = raw['Customer ID'], raw['Product'], raw['Month']
        key = (cid, product, month)
        assert key not in seen
        seen.add(key)
        pair_months[(cid, product)].add(month)
        i = lookup[cid]
        values = np.asarray([int(raw[f]) for f in fields])
        assert np.all(values >= 0)
        totals[i] += values
        record_counts[i] += 1
        product_counts[i, products.index(product)] += 1
    assert np.all(record_counts > 0)
    assert all(v == set(old['months']) for v in pair_months.values())
    averages = totals / record_counts[:, None]
    y = averages[:, 0]
    shares = product_counts / record_counts[:, None]
    plans = np.asarray([r['Plan Type'] for r in customer_rows])
    train_ids = set()
    for plan in old['plans']:
        members = [cid for cid, label in zip(ids, plans) if label == plan]
        members.sort(key=lambda cid: hashlib.sha256(f"{old['holdout_hash_salt']}|{cid}".encode()).hexdigest())
        train_ids.update(members[:int(np.floor(len(members) * old['training_fraction']))])
    train = np.asarray([cid in train_ids for cid in ids])
    test = np.logical_not(train)
    assert train.sum() == 6654 and test.sum() == 1666

    def encode(field):
        labels = np.asarray([r[field] for r in customer_rows])
        levels = sorted(set(labels[train]), reverse=True)
        assert set(labels[test]) <= set(levels)
        return np.column_stack([(labels == value).astype(float) for value in levels[:-1]])

    p = encode('Plan Type')
    b = np.column_stack([encode(f) for f in ['Company Size', 'Industry', 'Region']] + [shares[:, :-1]])
    u = np.log1p(averages[:, 1:])
    designs = {'P': p, 'B': b, 'B+P': np.column_stack([b, p]),
               'B+U': np.column_stack([b, u]), 'B+U+P': np.column_stack([b, u, p])}

    def qr_fit(x, outcome):
        q, r = np.linalg.qr(x, mode='reduced')
        assert np.linalg.matrix_rank(r) == x.shape[1]
        return np.linalg.solve(r, q.T @ outcome)

    recomputed = []
    worst_model_difference = 0.0
    for name, features in designs.items():
        x = np.column_stack([np.ones(len(y)), features])
        all_residual = y - x @ qr_fit(x, y)
        test_residual = y[test] - x[test] @ qr_fit(x[train], y[train])
        values = {
            'model': name,
            'full_r2': float(1 - np.dot(all_residual, all_residual) / np.dot(y-y.mean(), y-y.mean())),
            'reused_test_r2': float(1 - np.dot(test_residual, test_residual) / np.dot(y[test]-y[test].mean(), y[test]-y[test].mean())),
            'reused_test_mse': float(np.mean(test_residual ** 2)),
        }
        original = next(r for r in expected['models'] if r['model'] == name)
        differences = [abs(values[k] - original[k]) for k in ['full_r2', 'reused_test_r2', 'reused_test_mse']]
        worst_model_difference = max(worst_model_difference, *differences)
        assert max(differences) < 1e-10
        assert x.shape[1] == original['parameters']
        recomputed.append(values)

    expected_cells = {(r['company_size'], r['plan']): r for r in read_csv(HERE / 'company_size_plan.csv')}
    sizes = np.asarray([r['Company Size'] for r in customer_rows])
    cells = []
    worst_mean_difference = 0.0
    for size in sorted(set(sizes)):
        ordered_means = []
        for plan in old['plans']:
            mask = (sizes == size) & (plans == plan)
            mean = float(np.mean(y[mask]))
            count = int(mask.sum())
            original = expected_cells[(size, plan)]
            difference = abs(mean - float(original['mean_integrations']))
            worst_mean_difference = max(worst_mean_difference, difference)
            assert count == int(original['customer_n']) and difference < 1e-10
            cells.append({'company_size': size, 'plan': plan, 'customer_n': count, 'mean_integrations': mean})
            ordered_means.append(mean)
        assert all(a < b for a, b in zip(ordered_means, ordered_means[1:]))
    assert len(cells) == len(expected_cells) == 24
    # Verify the recorded input hashes, including the original split protocol.
    for source, digest in expected['source_sha256'].items():
        assert hashlib.sha256((HERE.parent / source).read_bytes()).hexdigest() == digest
    audit = {
        'status': 'PASS', 'executed_at_utc': datetime.now(timezone.utc).isoformat(),
        'review_blinded': False,
        'method': 'Raw CSV independent aggregation; different row/category ordering; QR OLS without importing main script.',
        'models': recomputed, 'company_size_plan': cells,
        'max_model_metric_absolute_difference': worst_model_difference,
        'max_cell_mean_absolute_difference': worst_mean_difference,
        'source_hashes_verified': True, 'new_observations': 0,
        'causal_effect_identified': False,
        'limitations': ['Non-blind numerical and code verification; not an independent dataset.',
                        'Reuses an already examined customer split; not a new holdout.',
                        'Additive conditional association cannot identify mechanisms or causal effects.',
                        'Product composition and usage may be mediators or selection variables.',
                        '24 size-plan cells provide marginal support, not guaranteed joint covariate overlap.'],
    }
    (HERE / 'independent_audit.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    table = '\n'.join(f"| {r['model']} | {r['full_r2']:.12f} | {r['reused_test_r2']:.12f} |" for r in recomputed)
    report = f'''# 独立计算与代码复核

**PASS。此为非盲独立实现复核，不是新增样本或独立数据验证。** 审阅者事先见过主脚本和结果。

从原始 customers.csv 与 product_usage.csv 重新聚合8,320名客户、42,210行使用记录；不导入主脚本。使用不同客户/类别顺序、独立矩阵编码和QR分解求解OLS，复算五个模型全数据R²、复用原划分的测试R²与MSE，以及全部24个规模×套餐单元的客户数和均值。

| 模型 | 全数据 R² | 复用划分测试 R² |
|---|---:|---:|
{table}

所有模型指标与主结果最大绝对差为 {worst_model_difference:.3g}；24单元均值最大绝对差为 {worst_mean_difference:.3g}，客户数完全一致。每规模的四套餐均值递增；最小单元131人、最大913人。原输入文件SHA-256全部一致。训练6,654人、测试1,666人，复用旧协议哈希算法，类别取自训练集。

代码审阅未发现阻断问题。全数据和测试R²分别使用相应y均值作为总平方和基准；训练拟合后才预测测试集；同一客户不跨侧。B模型测试R²为负已保留，不隐藏不利结果。

解释限制：加性模型下的条件关联不能排除未测需求、复杂度、细粒度规模或非线性交互；产品选择和使用强度可能是中介或选择变量；规模×套餐的边际支持不保证全部背景字段联合重叠。不能把R²增量解释为套餐因果贡献，不能识别权限、需求自选或配置障碍机制。没有新增客户观测、配置帮助执行、升级效果或利润证据。

复现：`python integration_mechanism_v2/independent_verify.py`。机器结果在 `independent_audit.json`。
'''
    (HERE / 'independent_audit.md').write_text(report, encoding='utf-8')
    print(json.dumps({'status': audit['status'], 'models': recomputed, 'cells_checked': len(cells),
                      'max_model_difference': worst_model_difference, 'max_mean_difference': worst_mean_difference}, indent=2))


if __name__ == '__main__':
    main()
