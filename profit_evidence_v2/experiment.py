"""Traceable 20-case evidence audit, not a purchase or profit experiment."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
import argparse
import calendar
import csv
import hashlib
import json
import math

ROOT = Path(__file__).resolve().parent
DATA = ROOT.parent / 'data'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name, value):
    (ROOT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False),
                             encoding='utf-8', newline='\n')


def read(name):
    with (DATA / name).open(encoding='utf-8-sig', newline='') as handle:
        return list(csv.DictReader(handle))


def normalize(value):
    return value.strip().casefold()


def main(prepare_only=False):
    p = json.loads((ROOT / 'protocol.json').read_text(encoding='utf-8'))
    fingerprints = {'source_sha256': {n: sha(DATA/n) for n in
                    ('customers.csv', 'customer_support_tickets.csv', 'product_usage.csv', 'README.md')},
                    'protocol_code_sha256': {n: sha(ROOT/n) for n in ('protocol.json', 'protocol.md', 'experiment.py')}}
    lock_path = ROOT / 'execution_lock.json'
    if lock_path.exists():
        saved = json.loads(lock_path.read_text(encoding='utf-8'))
        assert all(saved[k] == v for k, v in fingerprints.items())
    else:
        write(lock_path.name, dict(fingerprints, frozen_at=datetime.now(timezone.utc).isoformat()))

    customers, tickets, usage = [read(n) for n in ('customers.csv', 'customer_support_tickets.csv', 'product_usage.csv')]
    emails, used = defaultdict(list), defaultdict(list)
    for line, row in enumerate(customers, 2):
        emails[normalize(row['Customer Email'])].append((line, row))
    for line, row in enumerate(usage, 2):
        used[row['Customer ID'], row['Product'], row['Month']].append((line, row))
    conflicts, matches = set(), {}
    for line, row in enumerate(tickets, 2):
        candidates = emails[normalize(row['Customer Email'])]
        if len(candidates) != 1:
            continue
        customer_line, customer = candidates[0]
        matches[row['Ticket ID']] = (customer_line, customer)
        if any(normalize(row[f]) != normalize(customer[f]) for f in ('Customer Name', 'Customer Age', 'Customer Gender')):
            conflicts.add(customer['Customer ID'])
    free = [r for r in customers if r['Plan Type'] == p['plan'] and r['Customer ID'] not in conflicts]
    eligible, all_signals, free_signals = [], Counter(), Counter()
    for line, row in enumerate(tickets, 2):
        kind, subject = row['Ticket Type'] == p['ticket_type_signal'], row['Ticket Subject'] == p['ticket_subject_signal']
        key = 'both' if kind and subject else 'type_only' if kind else 'subject_only' if subject else 'neither'
        all_signals[key] += 1
        match = matches.get(row['Ticket ID'])
        if match is None:
            continue
        customer_line, customer = match
        if customer['Customer ID'] in conflicts or customer['Plan Type'] != p['plan']:
            continue
        free_signals[key] += 1
        if kind or subject:
            eligible.append((line, row, customer_line, customer))
    selected = []
    for product_name in p['products']:
        group = [r for r in eligible if r[1]['Product Purchased'] == product_name]
        group.sort(key=lambda r: hashlib.sha256((p['hash_salt']+'|'+r[1]['Ticket ID']).encode()).hexdigest())
        assert len(group) >= p['per_product']
        selected.extend(group[:p['per_product']])
    assert len(selected) == len({r[3]['Customer ID'] for r in selected}) == 20
    selection = [{'ticket_id':r[1]['Ticket ID'], 'customer_id':r[3]['Customer ID'], 'product':r[1]['Product Purchased']} for r in selected]
    if (ROOT / 'selection_freeze.json').exists():
        assert json.loads((ROOT/'selection_freeze.json').read_text(encoding='utf-8'))['selected'] == selection
    else:
        write('selection_freeze.json', {'frozen_at':datetime.now(timezone.utc).isoformat(), 'selected':selection})

    packets = []
    ticket_fields = [f for f in tickets[0] if f not in ('Customer Name', 'Customer Email', 'Customer Age', 'Customer Gender')]
    for i, (ticket_line, ticket, customer_line, customer) in enumerate(selected, 1):
        history, flags = [], []
        for month in p['months']:
            matches_usage = used[customer['Customer ID'], ticket['Product Purchased'], month]
            if len(matches_usage) != 1:
                flags.append('missing_or_duplicate_usage:' + month)
                continue
            line, values = matches_usage[0]
            record = {'source_row':line, **{k:v for k,v in values.items() if k != 'Customer ID'}}
            for field in ('Active Days', 'Sessions', 'Product Actions', 'Collaborators', 'Integrations Used'):
                try:
                    value = float(values[field])
                    assert math.isfinite(value) and value >= 0 and value.is_integer()
                    if field == 'Active Days':
                        assert value <= calendar.monthrange(*map(int, month.split('-')))[1]
                except (ValueError, AssertionError, TypeError):
                    flags.append('invalid:' + month + ':' + field)
            history.append(record)
        packets.append({'case_id':f'PE2-{i:02}', 'customer_id':customer['Customer ID'],
                        'ticket_source_row':ticket_line, 'customer_source_row':customer_line,
                        'ticket_view':{f:ticket[f] for f in ticket_fields},
                        'added_customer_context':{f:customer[f] for f in ('Plan Type','Company Size','Industry','Region')},
                        'added_usage_context':history, 'usage_quality_flags':flags})
    write('case_packets_20.json', packets)
    overview = {'source_counts':{'customers':len(customers),'tickets':len(tickets),'usage':len(usage)},
                'all_ticket_signal_counts':dict(all_signals), 'identity_consistent_free_customers':len(free),
                'free_ticket_signal_counts':dict(free_signals), 'eligible_candidate_tickets':len(eligible),
                'eligible_candidate_customers':len({r[3]['Customer ID'] for r in eligible}),
                'eligible_by_product':dict(Counter(r[1]['Product Purchased'] for r in eligible))}
    write('source_overview.json', overview)
    if prepare_only:
        print(json.dumps(overview, ensure_ascii=False, indent=2))
        print('PREPARED: 20 source packets; evidence review pending.')
        return

    audit = json.loads((ROOT / 'audit_annotations.json').read_text(encoding='utf-8'))
    assert audit['case_packets_sha256'] == sha(ROOT / 'case_packets_20.json')
    assert audit['review_type'] == 'source_evidence_review_not_customer_outcomes'
    annotations = {r['case_id']:r for r in audit['cases']}
    assert set(annotations) == {r['case_id'] for r in packets}
    coverage = {view:{d:Counter() for d in p['review_dimensions']} for view in ('ticket_only','enriched')}
    outputs, routes = [], Counter()
    for packet in packets:
        note = annotations[packet['case_id']]
        raw = packet['ticket_view']
        for view in coverage:
            for dimension in p['review_dimensions']:
                item = note[view][dimension]
                assert item['status'] in p['allowed_review_statuses'] and item['reason']
                if item['status'] == 'PRESENT':
                    assert item['quotes'], 'Positive source judgment requires exact quotations.'
                    for quote in item['quotes']:
                        assert quote['field'] in raw and quote['text'] and quote['text'] in raw[quote['field']]
                coverage[view][dimension][item['status']] += 1
        refund_or_cancel = any(raw[f] in ('Refund request','Cancellation request') for f in ('Ticket Type','Ticket Subject'))
        both = raw['Ticket Type'] == p['ticket_type_signal'] and raw['Ticket Subject'] == p['ticket_subject_signal']
        route = 'SUPPORT_FIRST' if refund_or_cancel else 'REQUIREMENT_REVIEW' if both else 'CLARIFY_REQUEST'
        prompts = {'SUPPORT_FIRST':'记录包含退款或取消类别；先核实这项请求是否仍待处理。',
                   'REQUIREMENT_REVIEW':'需要完成的具体任务是什么，当前阻碍是什么，是否希望评估付费选项？',
                   'CLARIFY_REQUEST':'本次主要是产品选型咨询，还是现有使用或账务问题？'}
        routes[route] += 1
        outputs.append({'case_id':packet['case_id'],'customer_id':packet['customer_id'],
                        'ticket_id':raw['Ticket ID'],'product':raw['Product Purchased'],
                        'route':route,'source_basis':{'Ticket Type':raw['Ticket Type'],'Ticket Subject':raw['Ticket Subject']},
                        'current_plan':packet['added_customer_context']['Plan Type'],
                        'usage_context':packet['added_usage_context'],'usage_quality_flags':packet['usage_quality_flags'],
                        'evidence_review':note['enriched'],'next_question':prompts[route],
                        'question_status':'PROPOSED_NOT_SENT','customer_answer':None,
                        'paid_recommendation':None,'incremental_profit':None})
    write('model_outputs_20.json', outputs)
    result = {'executed_at':datetime.now(timezone.utc).isoformat(),'dataset_scope':'competition_csv_only',
              'new_synthetic_observations':0,'case_count':len(packets),'source_overview':overview,
              'source_sha256':fingerprints['source_sha256'],'case_packets_sha256':sha(ROOT/'case_packets_20.json'),
              'audit_annotations_sha256':sha(ROOT/'audit_annotations.json'),
              'coverage':coverage,'route_counts':dict(routes),
              'observed_current_plan_context_n':sum(bool(r['added_customer_context']['Plan Type']) for r in packets),
              'observed_five_month_context_n':sum(len(r['added_usage_context']) == 5 for r in packets),
              'usage_context_with_quality_flags_n':sum(bool(r['usage_quality_flags']) for r in packets),
              'evidence_sufficient_for_paid_recommendation_n':sum(
                  all(annotations[r['case_id']]['enriched'][d]['status'] == 'PRESENT'
                      for d in ('specific_need','paid_capability_fit')) for r in packets),
              'generated_paid_recommendations_n':sum(r['paid_recommendation'] is not None for r in outputs),
              'business_efficacy':'UNVERIFIED',
              'profit_uplift':None,'statistical_significance_test':'NOT_APPLICABLE_TO_EVIDENCE_COVERAGE_AUDIT'}
    write('results.json', result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare-only', action='store_true')
    main(parser.parse_args().prepare_only)
