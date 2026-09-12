from pathlib import Path
import json
import hashlib
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
t = pd.read_csv(DATA / 'customer_support_tickets.csv')
c = pd.read_csv(DATA / 'customers.csv')
u = pd.read_csv(DATA / 'product_usage.csv')

result = {'source_folder': 'https://drive.google.com/drive/folders/1NirfOKfM54cYeYXS3gn3azWznX1jaFiP',
          'scope': 'Full three CSV files, synthetic competition dataset; exploratory checks, not causal estimates.'}
result['files'] = {p.name: {'sha256': hashlib.sha256(p.read_bytes()).hexdigest(), 'bytes': p.stat().st_size} for p in DATA.glob('*.csv')}
result['shape'] = {name: {'rows': len(df), 'columns': len(df.columns)} for name,df in [('tickets',t),('customers',c),('usage',u)]}
result['nulls'] = {name: df.isna().sum().to_dict() for name,df in [('tickets',t),('customers',c),('usage',u)]}
result['rating_by_status'] = t.groupby('Ticket Status')['Customer Satisfaction Rating'].agg(['size','count','mean']).reset_index().to_dict('records')
result['rating_distribution'] = t['Customer Satisfaction Rating'].value_counts(dropna=False).to_dict()

for df in (t,c):
    df['email_key'] = df['Customer Email'].str.strip().str.lower()
if c['email_key'].is_unique:
    tc = t.merge(c[['email_key','Customer ID','Industry','Region','Company Size','Plan Type']],on='email_key',how='left',validate='many_to_one')
    result['ticket_customer_join'] = {'matched': int(tc['Customer ID'].notna().sum()), 'unmatched': int(tc['Customer ID'].isna().sum()), 'rows_after':len(tc)}
else:
    raise RuntimeError('Ambiguous customer email; no implicit many-to-many join allowed.')

rated = tc[tc['Customer Satisfaction Rating'].notna()].copy()
rated['low_rating'] = rated['Customer Satisfaction Rating'].le(2)
result['low_rating_definition'] = 'Exploratory operational definition: ratings 1 or 2 among rated tickets only.'
result['rating_segments'] = {}
for col in ['Product Purchased','Ticket Type','Ticket Subject','Ticket Channel','Ticket Priority','Industry','Region','Company Size','Plan Type']:
    summary = rated.groupby(col).agg(n=('low_rating','size'),low_n=('low_rating','sum'),low_rate=('low_rating','mean'),mean_rating=('Customer Satisfaction Rating','mean')).reset_index()
    table = pd.crosstab(rated[col],rated['Customer Satisfaction Rating'])
    observed = table.to_numpy()
    expected = np.outer(observed.sum(axis=1),observed.sum(axis=0))/observed.sum()
    chi2 = ((observed-expected)**2/expected).sum()
    v = np.sqrt(chi2/(observed.sum()*min(observed.shape[0]-1,observed.shape[1]-1)))
    result['rating_segments'][col] = {'rows':summary.to_dict('records'), 'exploratory_cramers_v':v, 'note':'Unadjusted descriptive association; no significance or causal claim.'}

u['month_dt'] = pd.to_datetime(u['Month'],format='%Y-%m')
result['usage_months'] = u.groupby('Month').agg(rows=('Customer ID','size'),customers=('Customer ID','nunique'),mean_active_days=('Active Days','mean'),mean_sessions=('Sessions','mean'),mean_actions=('Product Actions','mean')).reset_index().to_dict('records')
result['usage_customer_coverage'] = {'unique_customers':u['Customer ID'].nunique(),'unique_customer_products':len(u[['Customer ID','Product']].drop_duplicates()),'months_per_customer_product_distribution':u.groupby(['Customer ID','Product'])['Month'].nunique().value_counts().to_dict()}
uc = u.merge(c[['Customer ID','Plan Type','Company Size']],on='Customer ID',how='left',validate='many_to_one')
result['usage_segments'] = {col:uc.groupby(col).agg(rows=('Customer ID','size'),customers=('Customer ID','nunique'),mean_active_days=('Active Days','mean'),mean_actions=('Product Actions','mean')).reset_index().to_dict('records') for col in ['Product','Plan Type','Company Size']}

# Fixed calendar halves are used for descriptive change only; they are not a support-event intervention window.
months = sorted(u['Month'].unique())
half = len(months)//2
u['period'] = u['Month'].isin(months[half:]).map({False:'earlier',True:'later'})
means = u.groupby(['Customer ID','Product','period'])['Active Days'].mean().unstack()
means['fraction_change'] = means['later']/means['earlier']-1
result['usage_change'] = {'earlier_months':months[:half], 'later_months':months[half:], 'customer_products':len(means), 'median_fraction_change':means['fraction_change'].median(), 'decline_30pct_n':int(means['fraction_change'].le(-0.3).sum()),'note':'30% is an illustrative threshold; no churn outcome is available.'}
result['support_product_match'] = {'ticket_rows_with_usage_for_same_customer_product':int(tc.merge(u[['Customer ID','Product']].drop_duplicates().assign(has_same_product=True),left_on=['Customer ID','Product Purchased'],right_on=['Customer ID','Product'],how='left',validate='many_to_one')['has_same_product'].fillna(False).sum())}

result['text_checks'] = {'columns':list(t.columns[:-1]),'resolution_nonnull':int(t['Resolution'].notna().sum()),'resolution_unique':int(t['Resolution'].nunique()),'resolution_examples':t['Resolution'].dropna().head(3).tolist(),'note':'Resolution is a recorded resolution field, not a customer-authored message. Examples require semantic review before NLP.'}
for col in ['Date of Purchase','First Response Time','Time to Resolution']:
    dt = pd.to_datetime(t[col],dayfirst=True,errors='coerce')
    result.setdefault('ticket_dates',{})[col] = {'min':str(dt.min()),'max':str(dt.max()),'valid':int(dt.notna().sum()),'unique_dates':dt.dt.date.nunique()}
first = pd.to_datetime(t['First Response Time'],dayfirst=True,errors='coerce')
end = pd.to_datetime(t['Time to Resolution'],dayfirst=True,errors='coerce')
delta = (end-first).dt.total_seconds()/3600
result['time_order'] = {'both_available':int(delta.notna().sum()),'negative':int(delta.lt(0).sum()),'zero':int(delta.eq(0).sum()),'positive':int(delta.gt(0).sum()),'note':'Difference is not full resolution duration because ticket creation timestamp is absent.'}

def default(x):
    return x.item() if hasattr(x,'item') else str(x)
(ROOT/'inspection_results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=default),encoding='utf-8')
print(json.dumps({k:v for k,v in result.items() if k not in ['files','nulls','rating_segments','usage_segments','text_checks']},ensure_ascii=False,indent=2,default=default))
print('RATING_ASSOCIATIONS', {k:round(v['exploratory_cramers_v'],4) for k,v in result['rating_segments'].items()})
print('USAGE_SEGMENTS',json.dumps(result['usage_segments'],ensure_ascii=False,default=default))
