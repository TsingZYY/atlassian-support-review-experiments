"""Post-primary wording check: strongest relationship is not necessarily unique."""
from collections import defaultdict
from pathlib import Path
from datetime import datetime, timezone
import calendar
import csv
import hashlib
import json
import numpy as np

HERE=Path(__file__).resolve().parent
DATA=HERE.parent/'data'
METRICS=['Active Day Rate','Sessions','Product Actions','Collaborators']
SEED=2026091314
REPETITIONS=5000


def read(path):
    with path.open(encoding='utf-8-sig',newline='') as stream:
        return list(csv.DictReader(stream))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name,obj):
    (HERE/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8',newline='\n')


def main():
    fingerprints={'source_sha256':{n:sha(DATA/n) for n in ('customers.csv','product_usage.csv','README.md')},
                  'supplement_sha256':{n:sha(HERE/n) for n in ('uniqueness_protocol.md','uniqueness_check.py')}}
    if (HERE/'uniqueness_lock.json').exists():
        old=json.loads((HERE/'uniqueness_lock.json').read_text(encoding='utf-8'))
        assert all(old[k]==v for k,v in fingerprints.items())
    else: write('uniqueness_lock.json',dict(fingerprints,frozen_at=datetime.now(timezone.utc).isoformat()))
    customers=read(DATA/'customers.csv'); usage=read(DATA/'product_usage.csv')
    by_id={c['Customer ID']:c for c in customers}; groups=defaultdict(list); bad=set()
    assert len(by_id)==len(customers)
    seen=set()
    for u in usage:
        assert u['Customer ID'] in by_id
        key=(u['Customer ID'],u['Product'],u['Month'])
        assert key not in seen; seen.add(key)
        days=calendar.monthrange(*map(int,u['Month'].split('-')))[1]
        if float(u['Active Days'])>days: bad.add(u['Customer ID'])
        groups[u['Customer ID']].append([float(u['Active Days'])/days]+[float(u[f]) for f in METRICS[1:]])
    ids=[c['Customer ID'] for c in customers if c['Customer ID'] not in bad]
    assert len(ids)==8261 and len(bad)==59
    x=np.array([np.mean(groups[cid],axis=0) for cid in ids])
    plans=sorted({c['Plan Type'] for c in customers})
    labels=np.array([plans.index(by_id[cid]['Plan Type']) for cid in ids])
    total=((x-x.mean(axis=0))**2).sum(axis=0)
    sizes=np.bincount(labels,minlength=len(plans)); grand=x.mean(axis=0)
    def r2(codes):
        group_means=np.array([x[codes==g].mean(axis=0) for g in range(len(plans))])
        return (sizes[:,None]*(group_means-grand)**2).sum(axis=0)/total
    observed=r2(labels); extreme=np.zeros(4,dtype=int); rng=np.random.default_rng(SEED)
    for _ in range(REPETITIONS):
        extreme += r2(rng.permutation(labels))>=observed-1e-12
    tests=[{'metric':metric,'n':len(ids),'r2':float(observed[j]),'extreme_count':int(extreme[j]),
            'raw_p':float((extreme[j]+1)/(REPETITIONS+1)),
            'bonferroni_16_p':float(min(1,16*(extreme[j]+1)/(REPETITIONS+1)))} for j,metric in enumerate(METRICS)]
    previous=0.
    for i,t in enumerate(sorted(tests,key=lambda t:t['raw_p'])):
        t['holm_4_p']=min(1,max(previous,(4-i)*t['raw_p'])); previous=t['holm_4_p']
    # Verify point estimates against the previously independently audited experiment.
    prior=json.loads((HERE.parent/'integration_plan_v1/results.json').read_text(encoding='utf-8'))
    for t in tests:
        old=next(v for v in prior['common_cohort_metric_ranking']['comparisons'] if v['metric']==t['metric'])
        assert abs(t['r2']-old['eta_squared_ols_r2'])<1e-10
    result={'executed_at':datetime.now(timezone.utc).isoformat(),'scope':'post_primary_supplement_non_ticket_associations',
            'dataset_scope':'competition_csv_only','new_synthetic_observations':0,**fingerprints,
            'seed':SEED,'permutations':REPETITIONS,'tests':tests,'family_size':4,'conservative_current_total_family':16,
            'counterexamples_to_only_integration_significant':sum(t['bonferroni_16_p']<.05 for t in tests),
            'original_12_ticket_tests_unchanged':True,'historical_all_searches_controlled':False,
            'ticket_effect_evidence':False,'profit_effect':None}
    write('uniqueness_results.json',result)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
