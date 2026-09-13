"""Retrospective response-to-resolution interval / observed CSAT association."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
import csv
import hashlib
import itertools
import json
import math
import numpy as np
from cost_model import calculate

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA = ROOT / 'data'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name, value):
    (HERE / name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8',newline='\n')


def read_csv(name):
    with (DATA / name).open(encoding='utf-8-sig',newline='') as f:
        return list(csv.DictReader(f))


def csv_out(name, rows):
    with (HERE / name).open('w',encoding='utf-8',newline='') as f:
        writer = csv.DictWriter(f,fieldnames=list(rows[0]),lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


def rating(row):
    value = row['Customer Satisfaction Rating']
    if not value:
        return None
    x = float(value)
    assert math.isfinite(x) and x.is_integer() and 1 <= x <= 5
    return int(x)


def interval(row, fmt):
    a,b = row['First Response Time'],row['Time to Resolution']
    if not a or not b:
        return 'MISSING_PAIR',None
    try:
        start,end = datetime.strptime(a,fmt),datetime.strptime(b,fmt)
    except ValueError:
        return 'UNPARSEABLE_PAIR',None
    hours = (end-start).total_seconds()/3600
    if hours < 0:
        return 'REVERSED_PAIR',None
    return ('ZERO_INTERVAL' if hours == 0 else 'POSITIVE_INTERVAL'),hours


def average_ranks(values):
    _,inverse,counts = np.unique(values,return_inverse=True,return_counts=True)
    return (np.cumsum(counts)-(counts-1)/2)[inverse].astype(float)


def correlation(a,b):
    a,b = np.asarray(a,dtype=float),np.asarray(b,dtype=float)
    a,b = a-a.mean(),b-b.mean()
    scale = float(np.sqrt(a@a * (b@b)))
    return float(a@b/scale) if scale else None


def spearman(a,b):
    return correlation(average_ranks(a),average_ranks(b))


def primary_test(hours, scores, p):
    x,y = average_ranks(hours),average_ranks(scores)
    observed = correlation(x,y)
    rng = np.random.default_rng(p['seed'])
    extreme = 0
    for _ in range(p['repetitions']):
        value = correlation(x,rng.permutation(y))
        extreme += abs(value) >= abs(observed)-1e-12
    rng = np.random.default_rng(p['bootstrap_seed'])
    boot = []
    for _ in range(p['repetitions']):
        indices = rng.integers(0,len(hours),len(hours))
        value = spearman(hours[indices],scores[indices])
        assert value is not None
        boot.append(value)
    probability = (extreme+1)/(p['repetitions']+1)
    return {'n':len(hours),'spearman_rho':observed,'bootstrap_95':np.quantile(boot,[.025,.975]).tolist(),
            'two_sided_permutation_p':probability,'permutation_extreme_count':int(extreme),
            'repetitions':p['repetitions'],
            'shorter_interval_higher_csat_supported':bool(observed < 0 and probability < .05)}


def group_summary(label, hours, scores):
    return {'group':label,'n':len(scores),'interval_hours_mean':float(hours.mean()),
            'interval_hours_median':float(np.median(hours)),'rating_sum':int(scores.sum()),
            'mean_csat':float(scores.mean()),'low_csat_n':int(np.sum(scores<=2)),
            'low_csat_fraction':float(np.mean(scores<=2)),
            'high_csat_n':int(np.sum(scores>=4)),'high_csat_fraction':float(np.mean(scores>=4))}


def fast_slow(cohort, p):
    hours = np.array([r['interval_hours'] for r in cohort])
    scores = np.array([r['rating'] for r in cohort])
    threshold = float(np.median(hours))
    is_fast = hours <= threshold
    a,b = scores[is_fast],scores[~is_fast]
    rng = np.random.default_rng(p['seed']+2)
    boot = a[rng.integers(0,len(a),(p['repetitions'],len(a)))].mean(axis=1)-b[rng.integers(0,len(b),(p['repetitions'],len(b)))].mean(axis=1)
    summary = [group_summary('fast',hours[is_fast],a),group_summary('slow',hours[~is_fast],b)]
    buckets = defaultdict(list)
    for r in cohort:
        r['speed_group'] = 'fast' if r['interval_hours'] <= threshold else 'slow'
        buckets[tuple(r[f] for f in p['adjustment_fields'])].append(r)
    included,excluded = [],[]
    for key,group in sorted(buckets.items()):
        x = np.array([r['rating'] for r in group if r['speed_group']=='fast'])
        y = np.array([r['rating'] for r in group if r['speed_group']=='slow'])
        if len(x) and len(y):
            included.append((key,x,y))
        else:
            excluded.append({'stratum':list(key),'n':len(group)})
    total = sum(len(x)+len(y) for _,x,y in included)
    adjusted,details = 0.0,[]
    adjusted_boot = np.zeros(p['repetitions'])
    rng = np.random.default_rng(p['seed']+3)
    for key,x,y in included:
        weight = (len(x)+len(y))/total
        delta = float(x.mean()-y.mean())
        adjusted += weight*delta
        adjusted_boot += weight*(x[rng.integers(0,len(x),(p['repetitions'],len(x)))].mean(axis=1)-y[rng.integers(0,len(y),(p['repetitions'],len(y)))].mean(axis=1))
        details.append({'product':key[0],'priority':key[1],'fast_n':len(x),'slow_n':len(y),
                        'pooled_weight':weight,'fast_minus_slow_csat':delta})
    return {'threshold_hours':threshold,'fast_rule':'hours <= threshold','groups':summary,
            'fast_minus_slow_mean_csat':float(a.mean()-b.mean()),
            'bootstrap_95':np.quantile(boot,[.025,.975]).tolist(),
            'adjusted':{'fields':p['adjustment_fields'],'common_support_n':total,
                        'excluded_strata':excluded,'fast_minus_slow_mean_csat':float(adjusted),
                        'bootstrap_95':np.quantile(adjusted_boot,[.025,.975]).tolist(),'strata':details},
            'scope':'Prespecified descriptive sensitivity; no subgroup significance selection or causal interpretation'}


def main():
    p = json.loads((HERE/'protocol.json').read_text(encoding='utf-8'))
    hashes = {'source_sha256':{name:sha(DATA/name) for name in ('customer_support_tickets.csv','customers.csv','README.md')},
              'audit_roster_sha256':sha(ROOT/p['audit_roster']),
              'protocol_code_sha256':{name:sha(HERE/name) for name in ('protocol.json','protocol.md','experiment.py','cost_model.py')}}
    lock_path = HERE/'execution_lock.json'
    if lock_path.exists():
        lock = json.loads(lock_path.read_text(encoding='utf-8'))
        assert all(lock[k]==v for k,v in hashes.items())
    else:
        write('execution_lock.json',{**hashes,'frozen_at':datetime.now(timezone.utc).isoformat()})
    tickets,customers = read_csv('customer_support_tickets.csv'),read_csv('customers.csv')
    norm = lambda text:text.strip().casefold()
    by_email = {norm(c['Customer Email']):c for c in customers}
    assert len(by_email)==len(customers)
    conflicts = set()
    for t in tickets:
        c = by_email[norm(t['Customer Email'])]
        if any(norm(t[f]) != norm(c[f]) for f in ('Customer Name','Customer Age','Customer Gender')):
            conflicts.add(c['Customer ID'])
    cohort,all_records = [],[]
    for row,t in enumerate(tickets,2):
        c = by_email[norm(t['Customer Email'])]
        state,hours = interval(t,p['timestamp_format'])
        value = rating(t)
        eligible = t['Ticket Status']=='Closed' and value is not None and hours is not None and c['Customer ID'] not in conflicts
        record = {'ticket_id':t['Ticket ID'],'source_row':row,'customer_id':c['Customer ID'],
                  'time_state':state,'interval_hours':hours,'rating':value,
                  'identity_conflict':c['Customer ID'] in conflicts,'primary_eligible':eligible,
                  **{f:t[f] for f in ('Ticket Status','Product Purchased','Ticket Type','Ticket Priority','Ticket Channel',
                                      'First Response Time','Time to Resolution')}}
        all_records.append(record)
        if eligible:
            cohort.append(record.copy())
    assert len(cohort)==len({r['customer_id'] for r in cohort})
    assert len(tickets)==len({r['Ticket ID'] for r in tickets})
    hours,scores = np.array([r['interval_hours'] for r in cohort]),np.array([r['rating'] for r in cohort])
    primary = primary_test(hours,scores,p)
    secondary = fast_slow(cohort,p)
    roster = json.loads((ROOT/p['audit_roster']).read_text(encoding='utf-8'))
    by_id = {r['ticket_id']:r for r in all_records}
    audit = [by_id[c['ticket_id']] for c in roster]
    assert len(audit)==len({r['ticket_id'] for r in audit})==20
    for c,r in zip(roster,audit):
        assert c['source']['record_row']==r['source_row'] and c['csat']['score']==r['rating']
    quality = []
    for state in ('MISSING_PAIR','UNPARSEABLE_PAIR','REVERSED_PAIR','ZERO_INTERVAL','POSITIVE_INTERVAL'):
        group = [r for r in all_records if r['time_state']==state]
        ratings = [r['rating'] for r in group if r['rating'] is not None]
        quality.append({'time_state':state,'n':len(group),'rating_n':len(ratings),
                        'mean_csat':sum(ratings)/len(ratings) if ratings else None,
                        **{f'rating_{i}_n':ratings.count(i) for i in range(1,6)}})
    csv_out('time_quality.csv',quality)
    csv_out('primary_cohort.csv',cohort)
    csv_out('audit_cases_20.csv',audit)
    csv_out('fast_slow_summary.csv',secondary['groups'])
    csv_out('adjusted_strata.csv',secondary['adjusted']['strata'])
    keys = list(p['cost_grid'])
    grid = [calculate(**dict(zip(keys,values)),minutes_saved=p['illustrative_minutes_saved'])
            for values in itertools.product(*(p['cost_grid'][k] for k in keys))]
    csv_out('cost_break_even_grid.csv',grid)
    base = calculate(**p['cost_base'])
    examples = []
    for label,overrides in [('base',{}),('half_realizable',{'realizable_fraction':.5}),
                            ('no_realizable_saving',{'realizable_fraction':0}),('twenty_ticket_volume',{'volume':20})]:
        examples.append({'scenario':label,**calculate(**{**p['cost_base'],**overrides},minutes_saved=p['illustrative_minutes_saved'])})
    csv_out('cost_examples.csv',examples)
    cost_result = {'parameter_status':'EXPLICIT_UNCALIBRATED_ASSUMPTIONS','unit':p['cost_unit'],
                   'base_no_observed_time_saving':base,'examples':examples,'grid_rows':len(grid),
                   'measured_labour_minutes_saved':None,'measured_profit_effect':None,
                   'retention_and_conversion_contribution':0,
                   'ticket_interval_used_as_labour_saving':False}
    write('cost_results.json',cost_result)
    clean_closed = [r for r in all_records if r['Ticket Status']=='Closed' and not r['identity_conflict']]
    result = {'executed_at':datetime.now(timezone.utc).isoformat(),**hashes,
              'dataset_scope':'competition_csv_only','new_synthetic_observations':0,
              'profile':{'tickets':len(tickets),'rated_closed_n':sum(r['Ticket Status']=='Closed' and r['rating'] is not None for r in all_records),
                         'identity_conflict_customers':len(conflicts),'clean_closed_rated_n':len(clean_closed),
                         'all_time_state_counts':dict(Counter(r['time_state'] for r in all_records)),
                         'clean_closed_time_state_counts':dict(Counter(r['time_state'] for r in clean_closed)),
                         'time_quality':quality,'primary_n':len(cohort)},
              'interval_name':'first_response_to_recorded_resolution_calendar_interval_hours',
              'full_resolution_duration_available':False,'labour_time_available':False,
              'primary':primary,'fast_slow':secondary,
              'excluding_zero_sensitivity':{'n':int(np.sum(hours>0)),'spearman_rho':spearman(hours[hours>0],scores[hours>0])},
              'audit_cases':len(audit),'audit_time_state_counts':dict(Counter(r['time_state'] for r in audit)),
              'audit_primary_eligible_n':sum(r['primary_eligible'] for r in audit),
              'human_review_efficiency_measured':False,'causal_csat_improvement':None,'measured_profit_effect':None}
    write('results.json',result)
    print(json.dumps({'profile':result['profile'],'primary':primary,'fast_slow':{k:v for k,v in secondary.items() if k!='adjusted'},
                      'adjusted':{k:v for k,v in secondary['adjusted'].items() if k!='strata'},'audit_time_states':result['audit_time_state_counts'],
                      'cost_base':base},ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
