"""Competition-data channel comparisons and timestamp feasibility audit."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
import csv
import hashlib
import json
import math
import numpy as np

ROOT = Path(__file__).resolve().parent
DATA = ROOT.parent/'data'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name, obj):
    (ROOT/name).write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8', newline='\n')


def csv_out(name, rows):
    with (ROOT/name).open('w',encoding='utf-8',newline='') as stream:
        writer = csv.DictWriter(stream,fieldnames=list(rows[0]),lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


def rating(row, protocol):
    if row['Ticket Status'] != protocol['rated_status']:
        return None
    try:
        v = float(row['Customer Satisfaction Rating'])
        if math.isfinite(v) and v.is_integer() and 1 <= v <= 5:
            return int(v)
    except (ValueError, TypeError):
        pass
    return None


def time_state(row):
    if not row['First Response Time'] or not row['Time to Resolution']:
        return 'missing_timestamp_pair'
    try:
        first = datetime.strptime(row['First Response Time'],'%d-%m-%Y %H:%M')
        resolved = datetime.strptime(row['Time to Resolution'],'%d-%m-%Y %H:%M')
    except ValueError:
        return 'unparseable_pair'
    return 'resolution_before_first_response' if resolved < first else 'same_time' if resolved == first else 'ordered_pair'


def primary_compare(a, b, repetitions, seed):
    rng = np.random.default_rng(seed)
    a,b = np.asarray(a,dtype=float),np.asarray(b,dtype=float)
    delta = float(a.mean()-b.mean())
    boot = a[rng.integers(0,len(a),(repetitions,len(a)))].mean(axis=1)-b[rng.integers(0,len(b),(repetitions,len(b)))].mean(axis=1)
    pooled = np.concatenate((a,b))
    extreme = 0
    for _ in range(repetitions):
        perm = rng.permutation(pooled)
        statistic = float(perm[:len(a)].mean()-perm[len(a):].mean())
        extreme += abs(statistic) >= abs(delta)-1e-12
    return {'email_n':len(a),'social_n':len(b),'email_mean':float(a.mean()),'social_mean':float(b.mean()),
            'mean_difference':delta,'bootstrap_95':np.quantile(boot,[.025,.975]).tolist(),
            'two_sided_permutation_p':(extreme+1)/(repetitions+1),'permutation_extreme_count':int(extreme),
            'repetitions':repetitions,'email_higher_supported':bool(delta > 0 and (extreme+1)/(repetitions+1) < .05)}


def adjusted_compare(rows, p):
    buckets = defaultdict(list)
    for row in rows:
        buckets[tuple(row[f] for f in p['adjustment_fields'])].append(row)
    included,excluded = [],[]
    for key, group in sorted(buckets.items()):
        a = np.array([rating(r,p) for r in group if r['Ticket Channel'] == 'Email'],dtype=float)
        b = np.array([rating(r,p) for r in group if r['Ticket Channel'] == 'Social media'],dtype=float)
        if len(a) and len(b):
            included.append((key,a,b))
        else:
            excluded.append({'stratum':list(key),'n':len(group)})
    total = sum(len(a)+len(b) for _,a,b in included)
    if not total:
        return {'available':False,'excluded_strata':excluded}
    rng = np.random.default_rng(p['seed']+1)
    boot,permuted = np.zeros(p['repetitions']),np.zeros(p['repetitions'])
    observed,details = 0.0,[]
    for key,a,b in included:
        weight = (len(a)+len(b))/total
        delta = float(a.mean()-b.mean())
        observed += weight*delta
        details.append({'product':key[0],'priority':key[1],'email_n':len(a),'social_n':len(b),
                        'pooled_weight':weight,'difference':delta})
        boot += weight*(a[rng.integers(0,len(a),(p['repetitions'],len(a)))].mean(axis=1)-b[rng.integers(0,len(b),(p['repetitions'],len(b)))].mean(axis=1))
        pooled = np.concatenate((a,b))
        for i in range(p['repetitions']):
            values = rng.permutation(pooled)
            permuted[i] += weight*(values[:len(a)].mean()-values[len(a):].mean())
    probability = (1+int(np.sum(np.abs(permuted) >= abs(observed)-1e-12)))/(p['repetitions']+1)
    return {'available':True,'common_support_n':total,'original_n':len(rows),'excluded_strata':excluded,
            'standardized_mean_difference':observed,'bootstrap_95':np.quantile(boot,[.025,.975]).tolist(),
            'within_stratum_two_sided_permutation_p':probability,'strata':details,
            'scope':'Product-priority standardized association, not a causal channel effect.'}


def main():
    p = json.loads((ROOT/'protocol.json').read_text(encoding='utf-8'))
    hashes = {'source_sha256':{n:sha(DATA/n) for n in ('customer_support_tickets.csv','README.md')},
              'protocol_code_sha256':{n:sha(ROOT/n) for n in ('protocol.json','protocol.md','experiment.py')}}
    if (ROOT/'execution_lock.json').exists():
        old = json.loads((ROOT/'execution_lock.json').read_text(encoding='utf-8'))
        assert all(old[k] == v for k,v in hashes.items())
    else:
        write('execution_lock.json',dict(hashes,frozen_at=datetime.now(timezone.utc).isoformat()))
    with (DATA/'customer_support_tickets.csv').open(encoding='utf-8-sig',newline='') as stream:
        tickets = list(csv.DictReader(stream))
    assert len(tickets) == len({r['Ticket ID'] for r in tickets})
    technical = [r for r in tickets if r[p['technical_filter']['field']] == p['technical_filter']['value']]
    payment = [r for r in tickets if r[p['payment_filter']['field']] == p['payment_filter']['value']]
    rated = [r for r in technical if rating(r,p) is not None]
    primary = [r for r in rated if r['Ticket Channel'] in p['primary_channels']]
    assert len(primary) == len({r['Customer Email'].strip().casefold() for r in primary})
    summary = []
    for channel in p['channels']:
        all_rows = [r for r in technical if r['Ticket Channel'] == channel]
        scores = [rating(r,p) for r in all_rows if rating(r,p) is not None]
        counts = Counter(scores)
        summary.append({'channel':channel,'total_technical_tickets':len(all_rows),'rated_closed_n':len(scores),
                        'rating_sum':sum(scores),'mean_rating':sum(scores)/len(scores),'high_rating_n':sum(v >= 4 for v in scores),
                        'high_rating_share':sum(v >= 4 for v in scores)/len(scores),
                        **{f'rating_{i}_n':counts[i] for i in range(1,6)}})
    a = [rating(r,p) for r in primary if r['Ticket Channel'] == 'Email']
    b = [rating(r,p) for r in primary if r['Ticket Channel'] == 'Social media']
    comparison = primary_compare(a,b,p['repetitions'],p['seed'])
    adjustment = adjusted_compare(primary,p)
    quality = []
    for channel in p['channels']:
        group = [r for r in payment if r['Ticket Channel'] == channel]
        states = Counter(time_state(r) for r in group)
        quality.append({'channel':channel,'payment_tickets':len(group),'closed_n':sum(r['Ticket Status'] == 'Closed' for r in group),
                        **{key:states[key] for key in ('missing_timestamp_pair','unparseable_pair','resolution_before_first_response','same_time','ordered_pair')}})
    closed = [r for r in tickets if r['Ticket Status'] == 'Closed']
    payment_closed = [r for r in payment if r['Ticket Status'] == 'Closed']
    audit_arms = [('technical_email',[r for r in rated if r['Ticket Channel']=='Email']),
                  ('technical_social',[r for r in rated if r['Ticket Channel']=='Social media']),
                  ('payment_chat',[r for r in payment_closed if r['Ticket Channel']=='Chat']),
                  ('payment_other',[r for r in payment_closed if r['Ticket Channel']!='Chat'])]
    source_line = {r['Ticket ID']:i for i,r in enumerate(tickets,2)}
    audited,seen = [],set()
    for arm,group in audit_arms:
        choices = sorted((r for r in group if r['Ticket ID'] not in seen),
                         key=lambda r:hashlib.sha256((p['audit_salt']+'|'+r['Ticket ID']).encode()).hexdigest())[:p['audit_per_arm']]
        assert len(choices) == 5
        for r in choices:
            seen.add(r['Ticket ID'])
            audited.append({'audit_arm':arm,'source_row':source_line[r['Ticket ID']],
                            **{f:r[f] for f in ('Ticket ID','Ticket Type','Ticket Subject','Ticket Channel','Ticket Status',
                                                'Customer Satisfaction Rating','First Response Time','Time to Resolution')},
                            'timestamp_state':time_state(r)})
    assert len(audited) == len(seen) == 20
    csv_out('technical_channel_summary.csv',summary)
    csv_out('payment_time_quality.csv',quality)
    csv_out('audit_cases_20.csv',audited)
    results = {'executed_at':datetime.now(timezone.utc).isoformat(),'dataset_scope':'competition_csv_only',
               'new_synthetic_observations':0,'source_sha256':hashes['source_sha256'],'source_tickets':len(tickets),
               'technical_total':len(technical),'technical_rated_closed':len(rated),
               'technical_closed_invalid_or_missing_rating':sum(r['Ticket Status']=='Closed' and rating(r,p) is None for r in technical),
               'technical_channel_summary':summary,'primary':comparison,'adjusted_sensitivity':adjustment,
               'payment_total':len(payment),'payment_closed':len(payment_closed),
               'payment_timestamp_states':dict(Counter(time_state(r) for r in payment_closed)),
               'payment_time_quality_by_channel':quality,
               'all_closed_timestamp_states':dict(Counter(time_state(r) for r in closed)),
               'payment_type_distribution':dict(Counter(r['Ticket Type'] for r in payment)),
               'ticket_created_timestamp_available':False,'total_resolution_duration_available':False,
               'payment_chat_faster_conclusion':'NOT_IDENTIFIABLE_FROM_AVAILABLE_TIMESTAMPS',
               'source_audit_case_n':len(audited),'causal_channel_effect':'UNVERIFIED','measured_profit_effect':None}
    write('results.json',results)
    print(json.dumps({k:results[k] for k in ('technical_total','technical_rated_closed','technical_channel_summary','primary',
                      'payment_total','payment_closed','payment_time_quality_by_channel','payment_chat_faster_conclusion')},ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in adjustment.items() if k != 'strata'},ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
