"""Finite ticket associations and an integration-to-ticket bridge audit."""
from collections import Counter, defaultdict
from pathlib import Path
from datetime import datetime, timezone
import csv
import hashlib
import json
import math
import numpy as np

HERE = Path(__file__).resolve().parent
DATA = HERE.parent/'data'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name, value):
    (HERE/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8',newline='\n')


def read(name):
    with (DATA/name).open(encoding='utf-8-sig',newline='') as stream:
        return list(csv.DictReader(stream))


def csv_out(name, rows):
    with (HERE/name).open('w',encoding='utf-8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]),lineterminator='\n')
        writer.writeheader(); writer.writerows(rows)


def norm(x):
    return x.strip().casefold()


def assemble(p):
    customers,tickets,usage=[read(n) for n in ('customers.csv','customer_support_tickets.csv','product_usage.csv')]
    by_email={norm(c['Customer Email']):(i,c) for i,c in enumerate(customers,2)}
    assert len(by_email)==len(customers)==len({c['Customer ID'] for c in customers})
    conflicts=set(); unmatched=[]
    for t in tickets:
        match=by_email.get(norm(t['Customer Email']))
        if match is None:
            unmatched.append(t['Ticket ID']); continue
        c=match[1]
        if any(norm(c[f])!=norm(t[f]) for f in ('Customer Name','Customer Age','Customer Gender')):
            conflicts.add(c['Customer ID'])
    grouped=defaultdict(list)
    for i,u in enumerate(usage,2):
        grouped[u['Customer ID'],u['Product'],u['Month']].append((i,u))
    cohort=[]; excluded=Counter()
    for ti,t in enumerate(tickets,2):
        match=by_email.get(norm(t['Customer Email']))
        if match is None:
            excluded['unmatched_ticket']+=1; continue
        ci,c=match
        if c['Customer ID'] in conflicts:
            excluded['identity_conflict_ticket']+=1; continue
        values=[]; lines=[]
        try:
            for month in p['months']:
                pairs=grouped[c['Customer ID'],t['Product Purchased'],month]
                assert len(pairs)==1
                ui,u=pairs[0]; v=float(u['Integrations Used'])
                assert math.isfinite(v) and v>=0 and v.is_integer()
                values.append(int(v)); lines.append(ui)
        except (AssertionError,ValueError,TypeError):
            excluded['invalid_integration_history']+=1; continue
        rating=None
        if t['Ticket Status']=='Closed':
            v=float(t['Customer Satisfaction Rating'])
            assert v.is_integer() and 1<=v<=5
            rating=int(v)
        cohort.append({'customer_id':c['Customer ID'],'ticket_id':t['Ticket ID'],
                       'customer_source_row':ci,'ticket_source_row':ti,'usage_source_rows':'|'.join(map(str,lines)),
                       **{f:t[f] for f in ('Product Purchased','Ticket Type','Ticket Subject','Ticket Priority','Ticket Channel','Ticket Status')},
                       'Plan Type':c['Plan Type'],'integration_month_values':values,'mean_integrations':sum(values)/5,
                       'rating':rating,'low_csat':int(rating<=2) if rating is not None else None,
                       'cancellation_request':int(t['Ticket Type']=='Cancellation request'),
                       'technical_issue':int(t['Ticket Type']=='Technical issue'),'not_closed':int(t['Ticket Status']!='Closed')})
    assert len(cohort)==len({r['customer_id'] for r in cohort})==len({r['ticket_id'] for r in cohort})
    peers=defaultdict(list)
    for r in cohort:
        peers[r['Product Purchased'],r['Plan Type']].append(r)
    peer_summary=[]
    for (product,plan),group in sorted(peers.items()):
        median=float(np.median([r['mean_integrations'] for r in group]))
        for r in group:
            r['peer_median_integrations']=median
            r['low_integration']=int(r['mean_integrations']<median)
        peer_summary.append({'product':product,'plan':plan,'n':len(group),'median_integrations':median,
                             'low_n':sum(r['low_integration'] for r in group),
                             'ties_n':sum(r['mean_integrations']==median for r in group)})
    quality={'source_customers':len(customers),'source_tickets':len(tickets),'source_usage_rows':len(usage),
             'identity_conflict_customers':len(conflicts),'exclusions':dict(excluded),'eligible_unique_customers':len(cohort),
             'valid_rated_closed':sum(r['rating'] is not None for r in cohort),
             'all_source_customers_have_tickets':set(by_email)=={norm(t['Customer Email']) for t in tickets},
             'complete_same_product_integration_history':len(cohort),'peer_strata_n':len(peers)}
    return cohort,quality,peer_summary


def screen(rows, field, outcome, count, seed):
    eligible=[r for r in rows if r[outcome] is not None]
    categories=sorted({r[field] for r in eligible})
    labels=np.array([categories.index(r[field]) for r in eligible])
    y=np.array([r[outcome] for r in eligible],dtype=float)
    sizes=np.bincount(labels,minlength=len(categories)); prevalence=y.mean()
    assert 0<prevalence<1
    def statistic(z):
        events=np.bincount(labels,weights=z,minlength=len(categories))
        return float(np.sum((events-sizes*prevalence)**2/(sizes*prevalence*(1-prevalence))))
    observed=statistic(y); rng=np.random.default_rng(seed)
    extreme=sum(statistic(rng.permutation(y))>=observed-1e-12 for _ in range(count))
    events=np.bincount(labels,weights=y,minlength=len(categories)).astype(int)
    table=[{'category':c,'n':int(sizes[j]),'events':int(events[j]),'rate':float(events[j]/sizes[j])} for j,c in enumerate(categories)]
    return {'id':field.lower().replace(' ','_')+'__'+outcome,'kind':'categorical_screen','feature':field,'outcome':outcome,
            'n':len(y),'events':int(y.sum()),'pearson_chi_square':observed,'degrees_of_freedom':len(categories)-1,
            'cramers_v':math.sqrt(observed/len(y)), 'minimum_expected_cell':float(min(sizes.min()*prevalence,sizes.min()*(1-prevalence))),
            'permutation_extreme_count':extreme,'raw_p':(extreme+1)/(count+1),'table':table}


def bridge(rows, outcome, p, seed):
    eligible=[r for r in rows if r[outcome] is not None]
    buckets=defaultdict(list)
    for r in eligible:
        buckets[r['Product Purchased'],r['Plan Type']].append(r)
    included=[]; excluded=[]
    for key,group in sorted(buckets.items()):
        a=np.array([r[outcome] for r in group if r['low_integration']],dtype=float)
        b=np.array([r[outcome] for r in group if not r['low_integration']],dtype=float)
        if len(a) and len(b): included.append((key,a,b))
        else: excluded.append({'stratum':list(key),'n':len(group)})
    total=sum(len(a)+len(b) for _,a,b in included); assert total>0
    rng=np.random.default_rng(seed); boot=np.zeros(p['bootstrap_repetitions']); perm=np.zeros(p['permutations'])
    standard_low=0.; standard_other=0.; details=[]
    for key,a,b in included:
        weight=(len(a)+len(b))/total
        standard_low+=weight*a.mean(); standard_other+=weight*b.mean()
        boot+=weight*(rng.binomial(len(a),a.mean(),len(boot))/len(a)-rng.binomial(len(b),b.mean(),len(boot))/len(b))
        # Binary-label permutation: number of events assigned to low group is hypergeometric.
        events=int(a.sum()+b.sum()); assigned=rng.hypergeometric(events,len(a)+len(b)-events,len(a),len(perm))
        perm+=weight*(assigned/len(a)-(events-assigned)/len(b))
        details.append({'product':key[0],'plan':key[1],'low_n':len(a),'other_n':len(b),
                        'low_events':int(a.sum()),'other_events':int(b.sum()),'pooled_weight':weight})
    observed=float(standard_low-standard_other)
    extreme=int(np.sum(np.abs(perm)>=abs(observed)-1e-12))
    groups=[]
    for low in (1,0):
        group=[r for r in eligible if r['low_integration']==low]
        groups.append({'low_integration':low,'n':len(group),'events':sum(r[outcome] for r in group),
                       'unadjusted_rate':sum(r[outcome] for r in group)/len(group)})
    return {'id':'relative_low_integration__'+outcome,'kind':'stratified_integration_bridge','feature':'relative_low_integration',
            'outcome':outcome,'n':total,'original_eligible_n':len(eligible),'events':sum(r[outcome] for r in eligible),
            'standardized_low_rate':float(standard_low),'standardized_comparison_rate':float(standard_other),
            'standardized_risk_difference':observed,'bootstrap_95':np.quantile(boot,[.025,.975]).tolist(),
            'permutation_extreme_count':extreme,'raw_p':(extreme+1)/(p['permutations']+1),
            'unadjusted_groups':groups,'excluded_strata':excluded,'strata':details}


def main():
    p=json.loads((HERE/'protocol.json').read_text(encoding='utf-8'))
    hashes={'source_sha256':{n:sha(DATA/n) for n in ('customers.csv','customer_support_tickets.csv','product_usage.csv','README.md')},
            'protocol_code_sha256':{n:sha(HERE/n) for n in ('protocol.json','protocol.md','experiment.py')}}
    if (HERE/'execution_lock.json').exists():
        old=json.loads((HERE/'execution_lock.json').read_text(encoding='utf-8'))
        assert all(old[k]==v for k,v in hashes.items())
    else: write('execution_lock.json',dict(hashes,frozen_at=datetime.now(timezone.utc).isoformat()))
    rows,quality,peer_summary=assemble(p)
    tests=[screen(rows,f,y,p['permutations'],p['seed']+i) for i,(f,y) in enumerate(p['category_screens'])]
    tests += [bridge(rows,y,p,p['seed']+100+i) for i,y in enumerate(p['bridge_outcomes'])]
    assert len(tests)==p['family_size']==12
    previous=0.
    for i,result in enumerate(sorted(tests,key=lambda x:x['raw_p'])):
        result['holm_p']=min(1.,max(previous,(len(tests)-i)*result['raw_p']))
        previous=result['holm_p']; result['supported_after_holm']=bool(result['holm_p']<.05)
    audit=[]
    for product in p['products']:
        for low in (1,0):
            candidates=[r for r in rows if r['Product Purchased']==product and r['low_integration']==low]
            chosen=sorted(candidates,key=lambda r:sha_text(p['audit_salt']+'|'+r['customer_id']))[:p['audit_per_product_per_group']]
            audit.extend({k:('|'.join(map(str,v)) if isinstance(v,list) else v) for k,v in r.items()} for r in chosen)
    assert len(audit)==len({r['customer_id'] for r in audit})==20
    summary=[{k:r.get(k) for k in ('id','kind','feature','outcome','n','events','cramers_v',
                                  'standardized_risk_difference','raw_p','holm_p','supported_after_holm')} for r in tests]
    result={'executed_at':datetime.now(timezone.utc).isoformat(),'dataset_scope':'competition_csv_only','new_synthetic_observations':0,
            **hashes,'quality':quality,'peer_summary':peer_summary,'tests':tests,'test_family_size':len(tests),
            'raw_p_below_05_n':sum(t['raw_p']<.05 for t in tests),'holm_supported_n':sum(t['supported_after_holm'] for t in tests),
            'bridge_supported_n':sum(t['supported_after_holm'] for t in tests if t['kind']=='stratified_integration_bridge'),
            'audit_cases_n':len(audit),'all_possible_ticket_associations_exhausted':False,
            'only_plan_integration_significant_globally':'NOT_ESTABLISHED',
            'competition_ticket_requirement':'UNVERIFIED_ORIGINAL_BRIEF_UNAVAILABLE',
            'measured_profit_effect':None,'causal_integration_effect':'UNVERIFIED'}
    csv_out('test_summary.csv',summary); csv_out('peer_summary.csv',peer_summary); csv_out('audit_cases_20.csv',audit)
    write('results.json',result)
    print(json.dumps({'quality':quality,'tests':summary,'holm_supported_n':result['holm_supported_n']},ensure_ascii=False,indent=2))
    print(json.dumps([r for r in tests if r['kind']=='stratified_integration_bridge'],ensure_ascii=False,indent=2))


def sha_text(value):
    return hashlib.sha256(value.encode()).hexdigest()


if __name__=='__main__':
    main()
