"""Verify the existing 20 synthetic cases against raw data and emit evidence cards.

This checks source fidelity and deterministic calculations, not business efficacy.
"""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import pandas as pd

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'competition_evidence'
OUT.mkdir(exist_ok=True)
paths = {name: ROOT / 'data' / f'{name}.csv' for name in
         ['customers', 'customer_support_tickets', 'product_usage']}
c, t, u = [pd.read_csv(paths[n]) for n in paths]
sample = pd.read_csv(ROOT / 'validation_v1/blind_review_20.csv')
key = pd.read_csv(ROOT / 'validation_v1/blind_review_key.csv')
cases = sample.merge(key, on='Case ID', validate='one_to_one')
assert len(cases) == 20 and cases['Ticket ID'].is_unique and cases['Customer ID'].is_unique
months = [f'2023-{i:02d}' for i in range(1, 6)]
topic_gaps = {
    'Network problem': '失败操作、报错、发生时间和网络环境',
    'Loading issue': '卡住的页面或操作、持续时长、报错和运行环境',
    'Account access': '登录或权限的失败阶段、报错以及身份与权限核验',
    'Device compatibility issue': '设备型号、系统版本和具体不兼容表现',
    'Refund request': '实际退款诉求、收费凭证和适用政策',
    'Product compatibility': '对接产品、版本、预期和实际行为',
    'Email delivery problem': '邮件类型、触发时间和投递或退信证据',
    'Integration': '集成对象、实际诉求、配置和失败步骤',
    'Product recommendation': '用户目标、现用流程和实际选型或收费诉求',
    'Display issue': '显示异常位置、预期效果、截图和运行环境',
    'Payment issue': '具体支付诉求、交易状态、时间和错误信息',
}
records = []
for _, r in cases.iterrows():
    cr = c[c['Customer ID'] == r['Customer ID']]
    tr = t[t['Ticket ID'] == r['Ticket ID']]
    ur = u[(u['Customer ID'] == r['Customer ID']) & (u['Product'] == r['Product'])]
    assert len(cr) == len(tr) == 1 and len(ur) == 5
    cr, tr = cr.iloc[0], tr.iloc[0]
    assert cr['Customer Email'].strip().casefold() == tr['Customer Email'].strip().casefold()
    assert all(str(cr[f]).strip().casefold() == str(tr[f]).strip().casefold()
               for f in ['Customer Name', 'Customer Age', 'Customer Gender'])
    assert tr['Product Purchased'] == r['Product'] and cr['Plan Type'] == r['Plan Type']
    assert all(tr[f] == r[f] for f in ['Ticket Status','Ticket Priority','Ticket Type','Ticket Subject'])
    ur = ur.set_index('Month').loc[months]
    days = pd.DatetimeIndex(months).days_in_month.to_numpy()
    active = ur['Active Days'].to_numpy()
    assert ((active >= 0) & (active <= days)).all()
    rates = active / days
    assert all(abs(r[f'{m}_active_pct'] - round(float(v * 100), 2)) < 1e-8
               for m, v in zip(months, rates))
    baseline = float(rates[:3].mean())
    low = [float(v) <= baseline * .7 and baseline - float(v) >= .1 for v in rates[3:]]
    support = tr['Ticket Status'] != 'Closed' and tr['Ticket Priority'] in ['High','Critical']
    candidate = bool(support and all(low))
    assert candidate == (r['hidden_group'] == 'candidate')
    missing = [f for f in ['Resolution','Time to Resolution','Customer Satisfaction Rating'] if pd.isna(tr[f])]
    assert len(missing) == 3
    gap = topic_gaps.get(r['Ticket Subject'], '原始诉求、症状、环境和已经尝试的动作')
    step = ('先查已有追问和客户回复，避免重复询问；' if r['Ticket Status'] == 'Pending Customer Response'
            else '先核实原始问题和已经尝试的动作；') + f'需要补足：{gap}。'
    records.append({
        'case_id': r['Case ID'], 'pair_id': int(r['pair_id']),
        'source_ticket_id': int(r['Ticket ID']), 'source_customer_id': r['Customer ID'],
        'product': r['Product'], 'plan': r['Plan Type'],
        'status': r['Ticket Status'], 'priority': r['Ticket Priority'],
        'ticket_type': r['Ticket Type'], 'subject': r['Ticket Subject'],
        'baseline_activity_pct': round(baseline * 100, 4),
        'monthly_activity_pct': [round(float(v * 100), 2) for v in rates],
        'april_low_activity': bool(low[0]), 'may_low_activity': bool(low[1]),
        'review_rule_triggered': candidate,
        'role': 'rule_candidate' if candidate else 'matched_nontrigger_control',
        'source_and_rule_check': 'PASS',
        'missing_information': gap + '；完整工单正文、对话、问题发生时间和后续处理结果未提供。',
        'proposed_next_step_unvalidated': step,
        'usage_followup_unvalidated': ('在核对原始问题后，必要时询问使用减少是否与该问题有关。'
                                      if candidate else '未触发该规则不代表没有支持需要；沿用现有工单流程。'),
        'business_result': 'UNOBSERVED',
    })

matched_fields = ['Product','Plan Type','Ticket Priority','Ticket Status']
for _, group in cases.groupby('pair_id'):
    assert len(group) == 2
    assert all(group[f].nunique() == 1 for f in matched_fields)
    assert set(group['hidden_group']) == {'candidate','priority_only_control'}

result = {
    'executed_at': datetime.now(timezone.utc).isoformat(),
    'source': 'Supplied competition synthetic CSV files',
    'source_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths.values()},
    'cases_checked': len(records), 'source_and_rule_checks_passed': len(records),
    'matching_pairs_checked': int(cases.pair_id.nunique()),
    'rule_candidates': sum(r['review_rule_triggered'] for r in records),
    'matched_controls': sum(not r['review_rule_triggered'] for r in records),
    'observed_real_resolution_results': 0,
    'human_review_executed': False,
    'scope': 'Integrity of these 20 cases only. Proposed next steps are not validated support actions; no resolution uplift estimated.',
}
(OUT / 'case_checks.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
(OUT / 'evidence_cards_20.json').write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
md = ['# 20 条比赛案例证据卡',
      '\n全部来自竞赛合成数据。原始字段、跨表对应、月度占比和固定规则已复算；以下澄清项为待验证建议，未执行客服处理。未触发规则不代表没有风险。',
      '\n每对按产品、套餐、优先级、状态匹配，仅供展示和完整性检查，不能当作随机干预试验。']
for r in records:
    md += [f"\n## {r['case_id']} · {r['product']} · {r['subject']}",
           f"- 追溯：Ticket ID {r['source_ticket_id']}；Customer ID {r['source_customer_id']}；匹配对 {r['pair_id']}。",
           f"- 工单事实：{r['status']}；{r['priority']}；{r['ticket_type']}；{r['plan']}。",
           f"- 使用事实：1—5 月活跃天数占比 {r['monthly_activity_pct']}%；1—3 月均值 {r['baseline_activity_pct']:.2f}%。",
           f"- 规则复算：4 月低使用={r['april_low_activity']}；5 月低使用={r['may_low_activity']}；复核候选={r['review_rule_triggered']}。",
           f"- 缺少的信息：{r['missing_information']}",
           f"- 待验证下一步：{r['proposed_next_step_unvalidated']}",
           f"- 使用信息处理方式：{r['usage_followup_unvalidated']}",
           '- 结论边界：数据对应与规则复算 PASS；解决效果 UNOBSERVED。']
(OUT / 'evidence_cards_20.md').write_text('\n'.join(md) + '\n', encoding='utf-8')
print(json.dumps(result, ensure_ascii=False, indent=2))
