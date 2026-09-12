"""A small, explainable support-review decision model. Python standard library only.

Run: python model.py --data-dir ../data --output-dir outputs
One case: python model.py --data-dir ../data --ticket-id 6545
No training labels, risk probabilities, automatic support actions, or external calls.
"""
import argparse
import calendar
import csv
from collections import defaultdict
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path

MODEL_VERSION = 'review-rules-1.0'
RULE = {'relative_decline': 0.30, 'absolute_decline': 0.10, 'baseline_months': 3,
        'consecutive_low_months': 2, 'epsilon': 1e-12}
MEANINGS = {
    'DATA_CHECK': '先核对数据，暂不输出使用变化判断。',
    'REVIEW_CANDIDATE': '补充复核候选；不是流失预测、自动升级或已验证的处理收益。',
    'STANDARD_SUPPORT': '未命中本复核规则；沿用原有支持流程，不代表客户健康。',
}


def normalize(value):
    return str(value or '').strip().casefold()


def month_window(end):
    dt = datetime.strptime(end, '%Y-%m')
    n = dt.year * 12 + dt.month - 1
    return [f'{m // 12:04d}-{m % 12 + 1:02d}' for m in range(n - 4, n + 1)]


def evaluate(ticket, usage, end_month='2023-05', quality_flags=()):
    """Evaluate one ticket with its five monthly records; do not infer outcomes."""
    flags = list(quality_flags)
    result = {'model_version': MODEL_VERSION, 'ticket_id': ticket.get('Ticket ID'),
              'customer_id': ticket.get('Customer ID'),
              'product': ticket.get('Product Purchased'),
              'ticket_status': ticket.get('Ticket Status'),
              'ticket_priority': ticket.get('Ticket Priority'),
              'ticket_subject': ticket.get('Ticket Subject'),
              'decision': None, 'meaning': None, 'data_quality_flags': [],
              'evidence': None, 'next_step_unvalidated': None,
              'missing_information': ['完整工单正文和对话', '问题发生时间', '处置后的结果'],
              'resolution_outcome': 'UNOBSERVED'}
    for f in ['Ticket ID','Customer ID','Product Purchased','Ticket Status','Ticket Priority']:
        if ticket.get(f) is None or str(ticket[f]).strip() == '':
            flags.append(f'missing_field:{f}')
    if ticket.get('Ticket Status') not in ['Open','Closed','Pending Customer Response']:
        flags.append('unknown_ticket_status')
    if ticket.get('Ticket Priority') not in ['Low','Medium','High','Critical']:
        flags.append('unknown_ticket_priority')
    window = month_window(end_month)
    grouped = defaultdict(list)
    for row in usage:
        if row.get('Customer ID') != ticket.get('Customer ID') or row.get('Product') != ticket.get('Product Purchased'):
            flags.append('usage_key_mismatch')
            continue
        grouped[row.get('Month')].append(row)
    rates, active_days = [], []
    for month in window:
        rows = grouped.get(month, [])
        if len(rows) != 1:
            flags.append(f'usage_month_count:{month}:{len(rows)}')
            continue
        days_in_month = calendar.monthrange(*map(int, month.split('-')))[1]
        try:
            active = float(rows[0]['Active Days'])
            if not math.isfinite(active) or not active.is_integer() or not 0 <= active <= days_in_month:
                raise ValueError()
        except (ValueError, TypeError, KeyError):
            flags.append(f'invalid_active_days:{month}')
            continue
        active_days.append(int(active))
        rates.append(active / days_in_month)
    if flags:
        result.update(decision='DATA_CHECK', data_quality_flags=sorted(set(flags)),
                      next_step_unvalidated='核对来源记录、客户关联和月份数据后再评估；原有支持流程继续。')
    else:
        baseline = sum(rates[:3]) / 3
        cutoff = baseline * (1 - RULE['relative_decline'])
        low = [r <= cutoff + RULE['epsilon'] and baseline - r >= RULE['absolute_decline'] - RULE['epsilon']
               for r in rates[3:]]
        support = ticket['Ticket Status'] != 'Closed' and ticket['Ticket Priority'] in ['High','Critical']
        decision = 'REVIEW_CANDIDATE' if support and all(low) else 'STANDARD_SUPPORT'
        result.update(decision=decision, evidence={
            'months': window, 'active_days': active_days,
            'monthly_activity_pct': [round(x * 100, 6) for x in rates],
            'baseline_activity_pct': round(baseline * 100, 6),
            'relative_cutoff_pct': round(cutoff * 100, 6),
            'absolute_decline_pp': [round((baseline - x) * 100, 6) for x in rates[3:]],
            'two_month_flags': low, 'support_eligible': support,
            'rule': RULE,
        })
        if decision == 'REVIEW_CANDIDATE':
            result['next_step_unvalidated'] = ('先核对已有追问与客户回复；' if ticket['Ticket Status'] == 'Pending Customer Response'
                else '先核实问题原话和已经尝试的动作；') + '必要时询问使用减少是否与该问题有关，再按问题证据处理。'
        else:
            result['next_step_unvalidated'] = '沿用当前工单流程；不因未触发该规则降低优先级或关闭工单。'
    result['meaning'] = MEANINGS[result['decision']]
    return result


def read_csv(path):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def run_dataset(data_dir, end_month='2023-05'):
    customers = read_csv(data_dir / 'customers.csv')
    tickets = read_csv(data_dir / 'customer_support_tickets.csv')
    usage = read_csv(data_dir / 'product_usage.csv')
    by_email, by_usage = defaultdict(list), defaultdict(list)
    for c in customers:
        by_email[normalize(c.get('Customer Email'))].append(c)
    invalid_customers, identity_conflicts = set(), set()
    for row in usage:
        by_usage[(row.get('Customer ID'), row.get('Product'))].append(row)
        try:
            dt = datetime.strptime(row['Month'], '%Y-%m')
            active = float(row['Active Days'])
            if not math.isfinite(active) or not active.is_integer() or not 0 <= active <= calendar.monthrange(dt.year, dt.month)[1]:
                raise ValueError()
        except (ValueError, KeyError, TypeError):
            invalid_customers.add(row.get('Customer ID'))
    for t in tickets:
        match = by_email.get(normalize(t.get('Customer Email')), [])
        if len(match) == 1 and any(normalize(t.get(f)) != normalize(match[0].get(f))
                                   for f in ['Customer Name','Customer Age','Customer Gender']):
            identity_conflicts.add(match[0]['Customer ID'])
    outputs = []
    for t in tickets:
        match = by_email.get(normalize(t.get('Customer Email')), [])
        flags = []
        if len(match) != 1:
            flags.append(f'customer_email_match_count:{len(match)}')
            customer_id = None
        else:
            customer_id = match[0]['Customer ID']
        if customer_id in invalid_customers:
            flags.append('customer_has_invalid_usage')
        if customer_id in identity_conflicts:
            flags.append('customer_identity_conflict')
        record = dict(t, **{'Customer ID': customer_id})
        outputs.append(evaluate(record, by_usage.get((customer_id, t.get('Product Purchased')), []), end_month, flags))
    return outputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=Path(__file__).resolve().parents[1] / 'data')
    parser.add_argument('--output-dir', type=Path, default=Path(__file__).resolve().parent / 'outputs')
    parser.add_argument('--as-of', default='2023-05', help='Last usage month; ticket statuses are a separate snapshot.')
    parser.add_argument('--ticket-id', help='Print one ticket assessment without exporting a batch.')
    args = parser.parse_args()
    predictions = run_dataset(args.data_dir, args.as_of)
    if args.ticket_id:
        selected = [p for p in predictions if str(p['ticket_id']) == args.ticket_id]
        if len(selected) != 1:
            parser.error('Ticket ID must match exactly one record.')
        print(json.dumps(selected[0], ensure_ascii=False, indent=2))
        return
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / 'predictions.json').write_text(json.dumps(predictions, ensure_ascii=False, indent=2), encoding='utf-8')
    counts = {k: sum(p['decision'] == k for p in predictions) for k in MEANINGS}
    summary = {'model_version': MODEL_VERSION, 'unit': 'ticket', 'usage_end_month': args.as_of,
               'ticket_count': len(predictions), 'decision_counts': counts,
               'source_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in args.data_dir.glob('*.csv')},
               'claim': 'Descriptive review decisions, not predictions of churn or resolution outcomes.'}
    (args.output_dir / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
