"""Competition-only product comparison of observed churn-related proxies."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
import calendar
import csv
import hashlib
import json
import math

import numpy as np

ROOT = Path(__file__).resolve().parent
DATA = ROOT.parent/'data'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name, value):
    (ROOT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8',newline='\n')


def read(name):
    with (DATA/name).open(encoding='utf-8-sig',newline='') as stream:
        return list(csv.DictReader(stream))


def write_csv(name, rows):
    with (ROOT/name).open('w',encoding='utf-8',newline='') as stream:
        writer = csv.DictWriter(stream,fieldnames=list(rows[0]),lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


def normalize(value):
    return str(value or '').strip().casefold()


def assemble(protocol):
    customers, tickets, usage = [read(name) for name in ('customers.csv','customer_support_tickets.csv','product_usage.csv')]
    by_email, by_usage = defaultdict(list), defaultdict(list)
    for customer in customers:
        by_email[normalize(customer['Customer Email'])].append(customer)
    for row_number, row in enumerate(usage,2):
        by_usage[(row['Customer ID'],row['Product'],row['Month'])].append((row_number,row))
    conflicts, bad_match_tickets = set(), []
    raw_pairs = {}
    for ticket in tickets:
        candidates = by_email[normalize(ticket['Customer Email'])]
        if len(candidates) != 1:
            bad_match_tickets.append(ticket['Ticket ID'])
            continue
        customer = candidates[0]
        cid = customer['Customer ID']
        if any(normalize(ticket[f]) != normalize(customer[f]) for f in ('Customer Name','Customer Age','Customer Gender')):
            conflicts.add(cid)
        key = (cid,ticket['Product Purchased'])
        pair = raw_pairs.setdefault(key,{'customer_id':cid,'product':key[1], 'plan':customer['Plan Type'],
                                       'ticket_ids':[],'cancel_ticket_ids':[]})
        pair['ticket_ids'].append(ticket['Ticket ID'])
        if ticket[protocol['primary_label']['field']] == protocol['primary_label']['value']:
            pair['cancel_ticket_ids'].append(ticket['Ticket ID'])
    records, quality_counts = [], Counter()
    for key, pair in sorted(raw_pairs.items()):
        if pair['customer_id'] in conflicts:
            continue
        pair = dict(pair)
        pair['cancellation_request'] = int(bool(pair['cancel_ticket_ids']))
        daily, activity, source_rows, flags = [], [], [], []
        for month in protocol['months']:
            matches = by_usage[(key[0],key[1],month)]
            if len(matches) != 1:
                flags.append('month_missing_or_duplicate:'+month)
                continue
            row_number, row = matches[0]
            try:
                value = float(row['Active Days'])
                denominator = calendar.monthrange(*map(int,month.split('-')))[1]
                assert math.isfinite(value) and value.is_integer() and 0 <= value <= denominator
            except (ValueError, AssertionError, TypeError):
                flags.append('invalid_active_days:'+month)
                continue
            daily.append(int(value))
            activity.append(value/denominator)
            source_rows.append(row_number)
        pair.update(usage_eligible=not flags, usage_flags=flags,
                    active_days=daily if not flags else None, usage_source_row_numbers=source_rows)
        if flags:
            quality_counts['invalid_or_incomplete_usage_customer_products'] += 1
            pair.update(baseline_rate=None,may_rate=None,may_low_usage=None,persistent_decline=None,usage_stopped_pattern=None)
        else:
            baseline = sum(activity[:3])/3
            persistent = all(value <= (1-protocol['persistent_relative_decline'])*baseline+1e-12
                             and baseline-value >= protocol['persistent_absolute_decline']-1e-12
                             for value in activity[3:])
            pair.update(baseline_rate=baseline,may_rate=activity[4],
                        may_low_usage=int(activity[4] < protocol['may_low_activity_threshold']),
                        persistent_decline=int(persistent),
                        usage_stopped_pattern=int(any(value > 0 for value in daily[:3]) and daily[3:] == [0,0]))
        records.append(pair)
    customer_multiplicity = Counter(r['customer_id'] for r in records)
    assert max(customer_multiplicity.values()) == 1, 'Use customer-cluster inference for a multi-product cohort.'
    raw_by_product = Counter(pair['product'] for pair in raw_pairs.values())
    primary_by_product = Counter(r['product'] for r in records)
    usage_by_product = Counter(r['product'] for r in records if r['usage_eligible'])
    quality = {'source_ticket_rows':len(tickets),'source_customers':len(customers),
               'source_usage_rows':len(usage),'unmatched_or_ambiguous_ticket_n':len(bad_match_tickets),
               'identity_conflict_customers':len(conflicts),'raw_matched_customer_product_pairs':len(raw_pairs),
               'primary_customer_product_pairs':len(records),'primary_distinct_customers':len(customer_multiplicity),
               'primary_multi_product_customers':sum(v > 1 for v in customer_multiplicity.values()),
               'usage_eligible_pairs':sum(r['usage_eligible'] for r in records),
               'usage_rejections':dict(quality_counts),
               'by_product':[{'product':p,'raw_matched_pairs':raw_by_product[p],
                              'primary_pairs':primary_by_product[p],
                              'identity_excluded_pairs':raw_by_product[p]-primary_by_product[p],
                              'usage_eligible_pairs':usage_by_product[p],
                              'usage_excluded_from_primary':primary_by_product[p]-usage_by_product[p]}
                             for p in protocol['products']]}
    return records, quality


def wilson(x,n):
    z = 1.959963984540054
    rate, denominator = x/n, 1+z*z/n
    center = (rate+z*z/(2*n))/denominator
    half = z*math.sqrt(rate*(1-rate)/n+z*z/(4*n*n))/denominator
    return [center-half,center+half]


def describe(records, indicator, products):
    rows = []
    for product in products:
        members = [r for r in records if r['product'] == product]
        n, x = len(members), sum(r[indicator] for r in members)
        rows.append({'product':product,'n':n,'events':x,'rate':x/n,'wilson_95':wilson(x,n)})
    total, events = sum(r['n'] for r in rows), sum(r['events'] for r in rows)
    pooled = events/total
    statistic = sum((r['events']-r['n']*pooled)**2/(r['n']*pooled*(1-pooled)) for r in rows) if 0 < pooled < 1 else 0.0
    # Chi-square survival with 4 degrees of freedom has this exact closed form.
    assert len(products) == 5
    p = math.exp(-statistic/2)*(1+statistic/2) if 0 < pooled < 1 else None
    return {'indicator':indicator,'n':total,'events':events,'pooled_rate':pooled,'products':rows,
            'pearson_chi_square':statistic,'degrees_of_freedom':4,'overall_p':p,
            'constant_outcome':events in (0,total),
            'test_status':'COMPUTED' if 0 < pooled < 1 else 'NOT_ESTIMABLE_CONSTANT_OUTCOME'}


def pairwise_holm(summary):
    rows = []
    for left,right in combinations(summary['products'],2):
        pooled = (left['events']+right['events'])/(left['n']+right['n'])
        se = math.sqrt(pooled*(1-pooled)*(1/left['n']+1/right['n']))
        delta = left['rate']-right['rate']
        z = delta/se if se else 0.0
        rows.append({'product_a':left['product'],'product_b':right['product'],'difference_pp':delta*100,
                     'z':z,'raw_p':math.erfc(abs(z)/math.sqrt(2))})
    previous = 0.0
    for rank, row in enumerate(sorted(rows,key=lambda r:r['raw_p'])):
        previous = min(1.0,max(previous,(len(rows)-rank)*row['raw_p']))
        row['holm_p'] = previous
    return rows


def standardize(records, indicator, protocol, seed_offset):
    products, plans = protocol['products'], sorted({r['plan'] for r in records})
    pi, si = {p:i for i,p in enumerate(products)}, {p:i for i,p in enumerate(plans)}
    product_codes = np.array([pi[r['product']] for r in records])
    stratum_codes = np.array([si[r['plan']] for r in records])
    y = np.array([r[indicator] for r in records],dtype=float)
    cells = stratum_codes*len(products)+product_codes
    counts = np.bincount(cells,minlength=len(plans)*len(products)).reshape(len(plans),len(products))
    if np.any(counts == 0):
        return {'available':False,'reason':'Some product-plan cells have no support','plans':plans,'cell_counts':counts.tolist()}
    weights = np.bincount(stratum_codes,minlength=len(plans))/len(records)
    def adjusted(labels):
        totals = np.bincount(cells,weights=labels,minlength=counts.size).reshape(counts.shape)
        return weights@(totals/counts)
    rates = adjusted(y)
    observed_range = float(np.ptp(rates))
    strata = [np.flatnonzero(stratum_codes == i) for i in range(len(plans))]
    rng = np.random.default_rng(protocol['permutation_seed']+seed_offset)
    ranges = []
    for _ in range(protocol['stratified_permutations']):
        permuted = y.copy()
        for indices in strata:
            permuted[indices] = rng.permutation(y[indices])
        ranges.append(float(np.ptp(adjusted(permuted))))
    p = (1+sum(value >= observed_range-1e-12 for value in ranges))/(1+len(ranges))
    return {'available':True,'plans':plans,'pooled_plan_weights':weights.tolist(),'product_order':products,
            'cell_counts':counts.tolist(),'minimum_cell_count':int(counts.min()),
            'standardized_rates':{p:float(rates[i]) for i,p in enumerate(products)},
            'max_minus_min_pp':observed_range*100,'stratified_range_permutation_p':p,
            'permutation_repetitions':len(ranges),'scope':'Descriptive adjustment; not causal or representative of a real customer population.'}


def audit_cases(records, protocol):
    audited = []
    tickets = {r['Ticket ID']:r for r in read('customer_support_tickets.csv')}
    usage = {(r['Customer ID'],r['Product'],r['Month']):r for r in read('product_usage.csv')}
    for product in protocol['products']:
        members = [r for r in records if r['product'] == product]
        members.sort(key=lambda r:hashlib.sha256((protocol['audit_salt']+'|'+r['customer_id']+'|'+product).encode()).hexdigest())
        for record in members[:protocol['audit_cases_per_product']]:
            original = [tickets[tid] for tid in record['ticket_ids']]
            flag = int(any(t['Ticket Type'] == 'Cancellation request' for t in original))
            assert flag == record['cancellation_request']
            assert all(t['Product Purchased'] == product for t in original)
            days = [usage[(record['customer_id'],product,month)]['Active Days'] for month in protocol['months']]
            if record['usage_eligible']:
                assert [int(float(d)) for d in days] == record['active_days']
            audited.append({'case_id':f'PROD-{len(audited)+1:02}','customer_id':record['customer_id'],'product':product,
                            'ticket_ids':'|'.join(record['ticket_ids']),'original_ticket_types':'|'.join(t['Ticket Type'] for t in original),
                            'cancellation_request':flag,'usage_eligible':record['usage_eligible'],
                            'jan_active_days':days[0],'feb_active_days':days[1],'mar_active_days':days[2],
                            'apr_active_days':days[3],'may_active_days':days[4],
                            'may_low_usage':record['may_low_usage'],'persistent_decline':record['persistent_decline'],
                            'usage_stopped_pattern':record['usage_stopped_pattern']})
    assert len(audited) == 20
    return audited


def main():
    protocol = json.loads((ROOT/'protocol.json').read_text(encoding='utf-8'))
    source_hashes = {n:sha(DATA/n) for n in ('customers.csv','customer_support_tickets.csv','product_usage.csv')}
    protocol_hashes = {n:sha(ROOT/n) for n in ('protocol.json','protocol.md','experiment.py')}
    lock = ROOT/'execution_lock.json'
    if lock.exists():
        previous = json.loads(lock.read_text(encoding='utf-8'))
        assert previous['source_sha256'] == source_hashes and previous['protocol_code_sha256'] == protocol_hashes
    else:
        write(lock.name,{'frozen_at':datetime.now(timezone.utc).isoformat(),
                         'source_sha256':source_hashes,'protocol_code_sha256':protocol_hashes})
    records, quality = assemble(protocol)
    usage_records = [r for r in records if r['usage_eligible']]
    definitions = [('cancellation_request',records),('may_low_usage',usage_records),
                   ('persistent_decline',usage_records),('usage_stopped_pattern',usage_records)]
    summaries = {label:describe(cohort,label,protocol['products']) for label,cohort in definitions}
    adjusted = {label:standardize(cohort,label,protocol,i) for i,(label,cohort) in enumerate(definitions[:3])}
    pairwise = pairwise_holm(summaries['cancellation_request'])
    sensitivity = describe(usage_records,'cancellation_request',protocol['products'])
    common_plan = standardize(usage_records,'cancellation_request',protocol,4)
    table = []
    for product in protocol['products']:
        record = {'product':product}
        for label, summary in summaries.items():
            row = next(r for r in summary['products'] if r['product'] == product)
            record.update({label+'_n':row['n'],label+'_events':row['events'],label+'_pct':row['rate']*100})
        members = [r for r in usage_records if r['product'] == product]
        record['jan_mar_mean_activity_pct'] = float(np.mean([r['baseline_rate'] for r in members])*100)
        record['may_mean_activity_pct'] = float(np.mean([r['may_rate'] for r in members])*100)
        record['plan_adjusted_cancellation_pct'] = adjusted['cancellation_request']['standardized_rates'][product]*100
        table.append(record)
    audited = audit_cases(records,protocol)
    write_csv('audit_cases_20.csv',audited)
    write_csv('product_summary.csv',table)
    write_csv('cancellation_pairwise_holm.csv',pairwise)
    primary = summaries['cancellation_request']
    ranked = sorted(primary['products'],key=lambda r:r['rate'],reverse=True)
    candidate_contrast = next(r for r in pairwise if {r['product_a'],r['product_b']} == {ranked[0]['product'],ranked[-1]['product']})
    result = {'executed_at':datetime.now(timezone.utc).isoformat(),'dataset_scope':'competition_csv_only',
        'source_sha256':source_hashes,'protocol_code_sha256':protocol_hashes,
        'new_synthetic_cases':0,'real_churn_observed':False,'real_churn_ranking':'NOT_IDENTIFIABLE_FROM_THIS_DATASET',
        'quality':quality,'indicators':summaries,'plan_standardization':adjusted,
        'cancellation_pairwise_holm':pairwise,'cancellation_common_usage_cohort':sensitivity,
        'cancellation_common_usage_plan_adjusted':common_plan,
        'product_table':table,'source_audit_cases_verified':len(audited),
        'primary_observed_highest':ranked[0]['product'],'primary_observed_lowest':ranked[-1]['product'],
        'primary_highest_minus_lowest_pp':(ranked[0]['rate']-ranked[-1]['rate'])*100,
        'primary_extreme_contrast_holm_p':candidate_contrast['holm_p'],
        'primary_any_holm_difference':any(r['holm_p'] < protocol['primary_familywise_alpha'] for r in pairwise),
        'primary_proxy_conclusion':'EVIDENCE_OF_PRODUCT_DIFFERENCE_IN_THIS_SYNTHETIC_COHORT' if primary['overall_p'] < .05 else 'NO_CLEAR_PRODUCT_DIFFERENCE_IN_CANCELLATION_REQUESTS',
        'limitations':['Cancellation requests are not completed churn and lack a common event window.',
                      'All source customers have support tickets; population sampling and synthesis mechanism are unspecified.',
                      'Low activity thresholds can reflect normal product usage frequency.',
                      'Statistical intervals and p-values do not account for synthetic-data generation bias.',
                      'Plan adjustment is descriptive; no causal product effect is identified.',
                      'The 20 source-audit cases are not an independent efficacy sample.']}
    assert source_hashes == {n:sha(DATA/n) for n in source_hashes}
    write('results.json',result)
    print(json.dumps({'quality':quality,'product_table':table,
                      'primary_overall_p':primary['overall_p'],
                      'primary_extreme_contrast_holm_p':result['primary_extreme_contrast_holm_p'],
                      'primary_plan_standardization':adjusted['cancellation_request'],
                      'secondary_overall_p':{label:s['overall_p'] for label,s in summaries.items() if label != 'cancellation_request'},
                      'primary_proxy_conclusion':result['primary_proxy_conclusion'],
                      'real_churn_ranking':result['real_churn_ranking']},ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
