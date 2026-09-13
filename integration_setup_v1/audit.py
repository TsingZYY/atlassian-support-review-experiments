"""Identify source-backed candidates and prepare an unexecuted help-offer pilot."""
from pathlib import Path
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import json

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA = ROOT / 'data'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def write(name, obj):
    (HERE/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8',newline='\n')


def read(name):
    with (DATA/name).open(encoding='utf-8-sig',newline='') as f:
        return list(csv.DictReader(f))


def table(name, rows):
    with (HERE/name).open('w',encoding='utf-8',newline='') as f:
        writer = csv.DictWriter(f,fieldnames=list(rows[0]),lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


def main():
    p = json.loads((HERE/'protocol.json').read_text(encoding='utf-8'))
    hashes = {'source_sha256':{n:sha(DATA/n) for n in ('customers.csv','customer_support_tickets.csv','product_usage.csv','README.md')},
              'protocol_code_sha256':{n:sha(HERE/n) for n in ('protocol.json','audit.py')}}
    if (HERE/'execution_lock.json').exists():
        old = json.loads((HERE/'execution_lock.json').read_text(encoding='utf-8'))
        assert all(old[k]==v for k,v in hashes.items())
    else:
        write('execution_lock.json',{**hashes,'frozen_at':datetime.now(timezone.utc).isoformat()})
    customers,tickets,usage = read('customers.csv'),read('customer_support_tickets.csv'),read('product_usage.csv')
    norm = lambda text:text.strip().casefold()
    by_email = {norm(c['Customer Email']):c for c in customers}
    assert len(by_email)==len(customers)
    bad = set()
    for t in tickets:
        c = by_email[norm(t['Customer Email'])]
        if any(norm(t[f])!=norm(c[f]) for f in ('Customer Name','Customer Age','Customer Gender')):
            bad.add(c['Customer ID'])
    free = [c for c in customers if c['Plan Type']==p['snapshot_plan']]
    clean_free = [c for c in free if c['Customer ID'] not in bad]
    raw = [(row,t) for row,t in enumerate(tickets,2)
           if by_email[norm(t['Customer Email'])]['Plan Type']==p['snapshot_plan'] and t['Ticket Subject']==p['ticket_subject']]
    clean = [(row,t) for row,t in raw if by_email[norm(t['Customer Email'])]['Customer ID'] not in bad]
    assert len(clean)==len({by_email[norm(t['Customer Email'])]['Customer ID'] for _,t in clean})
    usage_map = defaultdict(dict)
    for row,u in enumerate(usage,2):
        key = (u['Customer ID'],u['Product'])
        assert u['Month'] not in usage_map[key]
        usage_map[key][u['Month']] = (row,u)
    records = []
    cards = {}
    for row,t in clean:
        c = by_email[norm(t['Customer Email'])]
        history = usage_map[(c['Customer ID'],t['Product Purchased'])]
        assert sorted(history)==p['months']
        values = [int(history[m][1]['Integrations Used']) for m in p['months']]
        assert all(v>=0 for v in values)
        record = {'customer_id':c['Customer ID'],'ticket_id':t['Ticket ID'],'ticket_source_row':row,
                  'snapshot_plan':c['Plan Type'],'product':t['Product Purchased'],'ticket_type':t['Ticket Type'],
                  'ticket_subject':t['Ticket Subject'],'ticket_status':t['Ticket Status'],
                  'csat':int(float(t['Customer Satisfaction Rating'])) if t['Customer Satisfaction Rating'] else None,
                  'months_observed':len(values),'any_nonzero_integration_month':any(v>0 for v in values),
                  'all_months_zero':all(v==0 for v in values),'any_zero_month':any(v==0 for v in values),
                  'may_integrations_used':values[-1],
                  'need_confirmed':False,'setup_outcome_observed':False,'upgrade_outcome_observed':False}
        records.append(record)
        cards[c['Customer ID']] = {**record,
            'candidate_evidence':'Snapshot Free + exact Integration ticket subject; not confirmed configuration need',
            'usage_history':[{'source_file':'data/product_usage.csv','source_row':history[m][0],
                              'month':m,'integrations_used':values[i]} for i,m in enumerate(p['months'])],
            'resolution_record':t['Resolution'] or None,
            'configuration_need':'NOT_ESTABLISHED_FROM_AVAILABLE_FIELDS',
            'paid_capability_need':'NOT_ESTABLISHED_FROM_AVAILABLE_FIELDS',
            'configuration_success':None,'paid_upgrade':None,'incremental_profit':None,
            'next_questions':['具体要连接哪个产品或系统？','目前卡在哪个配置步骤，是否有错误信息？',
                              '配置成功后要完成什么工作，是否存在需要另行核实的付费功能需求？']}
    selected,allocation = [],[]
    for product in p['products']:
        candidates = [r for r in records if r['product']==product]
        chosen = sorted(candidates,key=lambda r:digest(p['pilot_selection_salt']+'|'+r['customer_id']))[:p['per_product_pilot']]
        assert len(chosen)==4
        planned = sorted(chosen,key=lambda r:digest(p['pilot_assignment_salt']+'|'+r['customer_id']))
        for i,r in enumerate(planned):
            arm = p['planned_arm_a'] if i<2 else p['planned_arm_b']
            allocation.append({'customer_id':r['customer_id'],'ticket_id':r['ticket_id'],'product':product,
                               'planned_arm':arm,'allocation_status':'PREPARED_NOT_EXECUTED',
                               'eligibility_reconfirmation_required':True,'intervention_executed':False,
                               'offer_accepted':None,'setup_success_7d':None,'paid_upgrade_30d':None,
                               'actual_upgrade_contribution':None,'actual_support_cost':None})
        selected.extend(cards[r['customer_id']] for r in chosen)
    table('candidate_roster.csv',records)
    table('planned_pilot_20.csv',allocation)
    write('evidence_cards_20.json',selected)
    result = {'executed_at':datetime.now(timezone.utc).isoformat(),**hashes,'dataset_scope':'competition_csv_only',
              'new_synthetic_observations':0,'snapshot_free_customers':len(free),'identity_conflict_customers_all_plans':len(bad),
              'identity_consistent_free_customers':len(clean_free),'raw_candidate_tickets':len(raw),
              'excluded_candidate_tickets':len(raw)-len(clean),'candidate_customers':len(records),
              'candidate_fraction_of_clean_free':len(records)/len(clean_free),
              'by_product':dict(Counter(r['product'] for r in records)),
              'by_type':dict(Counter(r['ticket_type'] for r in records)),
              'by_status':dict(Counter(r['ticket_status'] for r in records)),
              'rated_n':sum(r['csat'] is not None for r in records),
              'same_product_five_month_complete_n':len(records),
              'any_nonzero_history_n':sum(r['any_nonzero_integration_month'] for r in records),
              'all_zero_history_n':sum(r['all_months_zero'] for r in records),
              'any_zero_month_n':sum(r['any_zero_month'] for r in records),
              'may_zero_n':sum(r['may_integrations_used']==0 for r in records),
              'configuration_need_confirmation':'NOT_ESTABLISHED_NOT_A_MEASURED_ZERO',
              'configuration_success_rate':None,'upgrade_rate':None,'incremental_upgrade_rate':None,'incremental_profit':None,
              'pilot_records_prepared':len(allocation),'planned_arm_counts':dict(Counter(r['planned_arm'] for r in allocation)),
              'intervention_executed':False,'upgrade_effect_identifiable':False,
              'prior_usage_is_not_current_configuration_success':True,'snapshot_plan_is_not_plan_history':True}
    write('results.json',result)
    print(json.dumps({k:v for k,v in result.items() if not k.endswith('sha256')},ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
