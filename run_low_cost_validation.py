# %% Setup
from pathlib import Path
import hashlib
import json
import time
from datetime import datetime, timezone
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'validation_v1'
OUT.mkdir(exist_ok=True)
start = time.perf_counter()
SEED = 20260912
MONTHS = ['2023-01','2023-02','2023-03','2023-04','2023-05']
t = pd.read_csv(ROOT/'data/customer_support_tickets.csv')
c = pd.read_csv(ROOT/'data/customers.csv')
u = pd.read_csv(ROOT/'data/product_usage.csv')
assert t['Ticket ID'].is_unique and c['Customer ID'].is_unique
assert not u.duplicated(['Customer ID','Product','Month']).any()
for df in [t,c]:
    df['email_key'] = df['Customer Email'].str.strip().str.lower()
assert c['email_key'].is_unique
tc = t.merge(c, on='email_key', how='left', suffixes=('_ticket','_customer'),validate='many_to_one')
assert len(tc)==len(t) and tc['Customer ID'].notna().all()

# %% Population and quality exclusions
conflict = np.zeros(len(tc),dtype=bool)
for col in ['Customer Name','Customer Age','Customer Gender']:
    conflict |= (tc[col+'_ticket'].astype(str).str.strip().str.lower()!=tc[col+'_customer'].astype(str).str.strip().str.lower()).to_numpy()
conflict_ids=set(tc.loc[conflict,'Customer ID'])
u['days_in_month']=pd.to_datetime(u['Month']).dt.days_in_month
invalid = u['Active Days'].isna() | u['Active Days'].lt(0) | u['Active Days'].gt(u['days_in_month'])
invalid_ids=set(u.loc[invalid,'Customer ID'])
u['activity']=u['Active Days']/u['days_in_month']
wide=u.pivot(index=['Customer ID','Product'],columns='Month',values='activity').reindex(columns=MONTHS)
complete=wide.notna().all(axis=1)
eligible_ids = ~wide.index.get_level_values('Customer ID').isin(conflict_ids|invalid_ids)
panel=wide.loc[complete & eligible_ids].copy()
# The strict identity exclusion leaves one ticket and one product per customer.
assert panel.index.get_level_values('Customer ID').is_unique
X=panel.to_numpy()
R={'study':'Offline exploratory validation v1','seed':SEED,'executed_at':datetime.now(timezone.utc).isoformat(),
   'source':'https://drive.google.com/drive/folders/1NirfOKfM54cYeYXS3gn3azWznX1jaFiP',
   'limitations':['Synthetic dataset.','Retrospective exploratory forward-month evaluation; May was previously available, not a sealed holdout.','May low activity is not churn.','No June-or-later usage or intervention outcome exists.'],
   'source_hashes':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'data').glob('*.csv')},
   'protocol_sha256':hashlib.sha256((ROOT/'validation_protocol.md').read_bytes()).hexdigest(),
   'population':{'source_customers':len(c),'source_customer_products':len(wide),'identity_conflict_customers':len(conflict_ids),'invalid_activity_customers':len(invalid_ids),'exclusion_overlap':len(conflict_ids&invalid_ids),'excluded_union_customers':len(conflict_ids|invalid_ids),'incomplete_customer_products':int((~complete).sum()),'analysis_customers':len(panel),'analysis_customer_products':len(panel)}}
print('Population:',R['population'])

# %% Fixed rule and retrospective evaluation
def flags(x, relative=0.30):
    baseline=x[:,:3].mean(axis=1)
    april=(x[:,3]<=baseline*(1-relative)) & ((baseline-x[:,3])>=0.10)
    may=(x[:,4]<=baseline*(1-relative)) & ((baseline-x[:,4])>=0.10)
    return baseline,april,may

def metrics(a,y):
    n=len(a); na=int(a.sum()); nn=n-na
    hit=int((a&y).sum()); other=int((~a&y).sum()); total=hit+other
    p=hit/na if na else None; q=other/nn if nn else None; base=total/n
    return {'n':n,'alerts':na,'alert_outcomes':hit,'nonalerts':nn,'nonalert_outcomes':other,'population_outcomes':total,
            'alert_rate':na/n,'precision':p,'nonalert_outcome_rate':q,'population_outcome_rate':base,
            'risk_difference':p-q if p is not None and q is not None else None,
            'lift_vs_population':p/base if p is not None and base else None,
            'risk_ratio_vs_nonalert':p/q if p is not None and q else None,
            'expected_hits_same_capacity_random':na*base}

B,A,Y=flags(X)
primary=metrics(A,Y)
rng=np.random.default_rng(SEED)
cells=np.array([int((A&Y).sum()),int((A&~Y).sum()),int((~A&Y).sum()),int((~A&~Y).sum())])
boot=rng.multinomial(len(X),cells/len(X),size=2000)
boot_p=boot[:,0]/boot[:,:2].sum(axis=1)
boot_q=boot[:,2]/boot[:,2:].sum(axis=1)
boot_base=(boot[:,0]+boot[:,2])/len(X)
for key,values in [('precision',boot_p),('risk_difference',boot_p-boot_q),('lift_vs_population',boot_p/boot_base)]:
    primary[key+'_ci95']=[float(x) for x in np.quantile(values,[.025,.975])]
R['primary']=primary
print('Primary:',json.dumps(primary,indent=2))

# %% Negative control retaining individual activity distribution and shared baseline
null=[]
for i in range(1000):
    order=rng.random(X.shape).argsort(axis=1)
    shuffled=np.take_along_axis(X,order,axis=1)
    _,a,y=flags(shuffled)
    m=metrics(a,y)
    null.append([m['lift_vs_population'],m['risk_difference'],m['precision'],m['alerts']])
null=np.array(null)
R['month_permutation']={'replicates':1000,'null_lift_mean':float(null[:,0].mean()),'null_lift_ci95':np.quantile(null[:,0],[.025,.975]).tolist(),
    'observed_lift':primary['lift_vs_population'],'one_sided_p':float((1+np.sum(null[:,0]>=primary['lift_vs_population']))/1001),
    'note':'Permutes already calendar-normalized rates within individuals. Approximate null: preserves shared-baseline effects and individual variation, assumes month exchangeability.'}
print('Month-order negative control:',json.dumps(R['month_permutation'],indent=2))
R['evidence_gate']={'min_50_alerts':primary['alerts']>=50,'lift_at_least_1_5':primary['lift_vs_population']>=1.5,
   'risk_difference_ci_lower_positive':primary['risk_difference_ci95'][0]>0,'better_than_month_null':R['month_permutation']['one_sided_p']<.05}
R['predictive_gate_pass']=all(R['evidence_gate'].values())

# %% Frozen sensitivity checks, not threshold selection
R['threshold_sensitivity']=[dict(relative_threshold=r,**metrics(*flags(X,r)[1:])) for r in [.20,.30,.40]]
raw=wide.loc[complete].to_numpy()
R['quality_sensitivity']=[{'population':'strict exclusions',**metrics(A,Y)},
    {'population':'all complete raw records, invalid values retained and flagged',**metrics(*flags(raw)[1:])},
    {'population':'all complete records, activity explicitly clipped to [0,1]',**metrics(*flags(np.clip(raw,0,1))[1:])}]
R['cohort_history']=[{'month':month,'cohort':name,'mean_activity_pct':float(X[mask,j].mean()*100),'customers':int(mask.sum())}
    for name,mask in [('April alert',A),('No April alert',~A)] for j,month in enumerate(MONTHS)]
R['alert_rebound']={'april_mean_activity_pct':float(X[A,3].mean()*100),'may_mean_activity_pct':float(X[A,4].mean()*100),
    'april_mean_active_days':float((X[A,3]*30).mean()),'may_mean_active_days':float((X[A,4]*31).mean())}

# %% June snapshot feasibility, never used as historical model features
snapshot=panel.reset_index()[['Customer ID','Product']].merge(
    tc.loc[tc['Customer ID'].isin(panel.index.get_level_values('Customer ID')),['Customer ID','Product Purchased','Ticket ID','Ticket Status','Ticket Priority','Ticket Subject','Ticket Type','Plan Type']],
    left_on=['Customer ID','Product'],right_on=['Customer ID','Product Purchased'],how='left',validate='one_to_one')
assert len(snapshot)==len(panel)
snapshot['april_alert']=A
snapshot['may_low_activity']=Y
snapshot['sustained_low_activity']=A&Y
snapshot['support_eligible']=snapshot['Ticket Status'].ne('Closed') & snapshot['Ticket Priority'].isin(['High','Critical'])
snapshot['review_candidate']=snapshot['support_eligible'] & snapshot['sustained_low_activity']
for j,month in enumerate(MONTHS):
    snapshot[month+'_active_pct']=X[:,j]*100
snapshot['baseline_active_pct']=B*100
snapshot['may_drop_pp']=(B-X[:,4])*100
R['snapshot']={'population':len(snapshot),'unclosed':int(snapshot['Ticket Status'].ne('Closed').sum()),
   'unclosed_high_or_critical':int(snapshot['support_eligible'].sum()),'sustained_low_activity':int((A&Y).sum()),
   'review_candidates':int(snapshot['review_candidate'].sum()),'newly_low_in_may_support_eligible':int((snapshot['support_eligible'] & Y).sum()),
   'note':'Descriptive June snapshot candidate list; no validated need or intervention benefit.'}
group_ids=snapshot.groupby(['Product','Plan Type'],sort=True).indices
sustained=snapshot['sustained_low_activity'].to_numpy()
support=snapshot['support_eligible'].to_numpy()
queue_null=[]
for i in range(1000):
    perm=sustained.copy()
    for idx in group_ids.values(): perm[idx]=rng.permutation(sustained[idx])
    queue_null.append(int((perm&support).sum()))
R['snapshot']['product_plan_permutation_expected_candidates']=float(np.mean(queue_null))
R['snapshot']['product_plan_permutation_ci95']=np.quantile(queue_null,[.025,.975]).tolist()
R['snapshot']['product_plan_permutation_p']=float((1+np.sum(np.array(queue_null)>=R['snapshot']['review_candidates']))/1001)
print('June snapshot:',json.dumps(R['snapshot'],indent=2))

# %% Pseudonymized review examples, not completed human validation
candidate=snapshot[snapshot['review_candidate']].copy()
candidate['priority_sort']=candidate['Ticket Priority'].map({'Critical':0,'High':1})
candidate=candidate.sort_values(['priority_sort','may_drop_pp','Customer ID'],ascending=[True,False,True])
candidate['selection_reason']='Unclosed High/Critical ticket; April and May both at least 30% and 10 percentage points below Jan-Mar activity baseline.'
candidate['proposed_action_unvalidated']=candidate['Ticket Type'].map({
    'Technical issue':'Human technical triage and confirm the reported issue.',
    'Billing inquiry':'Human billing support review.',
    'Cancellation request':'Human review of cancellation request and customer intent.',
    'Refund request':'Human refund-process review.',
    'Product inquiry':'Human product guidance and needs check.'})
export_cols=['Customer ID','Ticket ID','Product','Plan Type','Ticket Status','Ticket Priority','Ticket Type','Ticket Subject','baseline_active_pct']+[m+'_active_pct' for m in MONTHS]+['selection_reason','proposed_action_unvalidated']
candidate[export_cols].to_csv(OUT/'review_candidates.csv',index=False)
candidate[export_cols].head(10).to_csv(OUT/'review_examples_10.csv',index=False)
pd.DataFrame(R['cohort_history']).to_csv(OUT/'cohort_history.csv',index=False)
pd.DataFrame(R['threshold_sensitivity']).to_csv(OUT/'threshold_sensitivity.csv',index=False)
R['case_examples']=candidate[export_cols].head(10).round(3).to_dict('records')
R['resource_use']={'paid_api_calls':0,'customer_contacts':0,'wall_seconds':round(time.perf_counter()-start,3),'software':'Python stdlib, numpy, pandas'}
def clean(obj):
    if isinstance(obj,dict): return {str(k):clean(v) for k,v in obj.items()}
    if isinstance(obj,(list,tuple)): return [clean(v) for v in obj]
    if isinstance(obj,np.generic): return obj.item()
    return obj
R=clean(R)
(OUT/'validation_results.json').write_text(json.dumps(R,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
print('Predictive evidence gate:',R['predictive_gate_pass'],R['evidence_gate'])
print('Resources:',R['resource_use'])
