from pathlib import Path
import json
import pandas as pd

ROOT = Path(__file__).resolve().parent
t = pd.read_csv(ROOT / 'data/customer_support_tickets.csv')
c = pd.read_csv(ROOT / 'data/customers.csv')
u = pd.read_csv(ROOT / 'data/product_usage.csv')

def dist(s):
    return {str(k): int(v) for k, v in s.value_counts(dropna=False).items()}

def dates(s, fmt):
    p = pd.to_datetime(s, format=fmt, errors='coerce')
    return p, {'nonmissing': int(s.notna().sum()), 'parse_failed_nonmissing': int((s.notna() & p.isna()).sum()), 'min': str(p.min()), 'max': str(p.max()), 'distinct': int(p.nunique())}

r = {'rows': {'tickets': len(t), 'customers': len(c), 'usage': len(u)}}
r['keys'] = {
    'ticket_id_distinct': t['Ticket ID'].nunique(),
    'ticket_email_distinct': t['Customer Email'].nunique(),
    'customer_id_distinct': c['Customer ID'].nunique(),
    'customer_email_distinct': c['Customer Email'].nunique(),
    'customer_id_missing': c['Customer ID'].isna().sum(),
    'customer_email_missing': c['Customer Email'].isna().sum(),
    'customer_email_duplicated_rows': c['Customer Email'].duplicated(keep=False).sum(),
    'usage_customer_distinct': u['Customer ID'].nunique(),
    'ticket_email_frequency': dist(t['Customer Email'].value_counts()),
}
t['_email_norm'] = t['Customer Email'].str.strip().str.lower()
c['_email_norm'] = c['Customer Email'].str.strip().str.lower()
r['email_link'] = {
    'raw_matched_ticket_rows': t['Customer Email'].isin(c['Customer Email']).sum(),
    'raw_unmatched_customer_rows': (~c['Customer Email'].isin(t['Customer Email'])).sum(),
    'normalized_matched_ticket_rows': t['_email_norm'].isin(c['_email_norm']).sum(),
    'normalized_customer_email_duplicated_rows': c['_email_norm'].duplicated(keep=False).sum(),
}
j = t.merge(c, on='Customer Email', how='left', suffixes=('_ticket', '_customer'), validate='many_to_one')
r['email_link']['joined_rows'] = len(j)
r['demographic_consistency'] = {}
for field in ['Customer Name', 'Customer Age', 'Customer Gender']:
    mismatch = j[field + '_ticket'].ne(j[field + '_customer'])
    r['demographic_consistency'][field] = {
        'mismatch_ticket_rows': mismatch.sum(),
        'mismatch_distinct_emails': j.loc[mismatch, 'Customer Email'].nunique(),
        'multiple_ticket_values_per_email': (t.groupby('Customer Email')[field].nunique() > 1).sum(),
    }
any_mismatch = pd.concat([j[field + '_ticket'].ne(j[field + '_customer']) for field in ['Customer Name', 'Customer Age', 'Customer Gender']], axis=1).any(axis=1)
r['demographic_consistency']['any_field'] = {'mismatch_ticket_rows': any_mismatch.sum(), 'mismatch_distinct_emails': j.loc[any_mismatch, 'Customer Email'].nunique()}

usage_key = ['Customer ID', 'Product', 'Month']
r['usage_grain'] = {
    'key_duplicate_rows': u.duplicated(usage_key, keep=False).sum(),
    'key_missing_rows': u[usage_key].isna().any(axis=1).sum(),
    'unmatched_customer_rows': (~u['Customer ID'].isin(c['Customer ID'])).sum(),
    'customer_without_usage': (~c['Customer ID'].isin(u['Customer ID'])).sum(),
    'customer_product_pairs': len(u[['Customer ID','Product']].drop_duplicates()),
    'products_per_customer_distribution': dist(u.groupby('Customer ID')['Product'].nunique()),
    'months_per_customer_product_distribution': dist(u.groupby(['Customer ID','Product'])['Month'].nunique()),
    'month_counts': dist(u['Month']),
    'products_usage': dist(u['Product']),
    'products_tickets': dist(t['Product Purchased']),
}

purchase, ps = dates(t['Date of Purchase'], '%d-%m-%Y')
response, rs = dates(t['First Response Time'], '%d-%m-%Y %H:%M')
resolution, res = dates(t['Time to Resolution'], '%d-%m-%Y %H:%M')
created, cs = dates(c['Account Created Date'], '%Y-%m-%d')
month, ms = dates(u['Month'], '%Y-%m')
r['dates'] = {'purchase': ps, 'response': rs, 'resolution': res, 'account_created': cs, 'usage_month': ms}
both = response.notna() & resolution.notna()
r['date_anomalies'] = {
    'both_response_resolution': both.sum(),
    'resolution_before_response': (both & (resolution < response)).sum(),
    'resolution_equal_response': (both & (resolution == response)).sum(),
    'response_before_purchase': (response.notna() & (response < purchase)).sum(),
    'resolution_before_purchase': (resolution.notna() & (resolution < purchase)).sum(),
}
jpurchase = pd.to_datetime(j['Date of Purchase'], format='%d-%m-%Y', errors='coerce')
jcreated = pd.to_datetime(j['Account Created Date'], format='%Y-%m-%d', errors='coerce')
r['date_anomalies']['purchase_before_account_created'] = (jpurchase < jcreated).sum()
uc = u.merge(c[['Customer ID','Account Created Date']], on='Customer ID', validate='many_to_one')
ucmonth = pd.to_datetime(uc['Month'], format='%Y-%m').dt.to_period('M')
uccreated = pd.to_datetime(uc['Account Created Date'], format='%Y-%m-%d').dt.to_period('M')
r['date_anomalies']['usage_month_before_account_creation_month'] = (ucmonth < uccreated).sum()
r['date_anomalies']['active_days_exceed_days_in_month'] = (u['Active Days'] > month.dt.days_in_month).sum()
active_invalid = u['Active Days'] > month.dt.days_in_month
r['date_anomalies']['active_days_invalid_distinct_customers'] = u.loc[active_invalid, 'Customer ID'].nunique()
r['date_anomalies']['active_days_invalid_breakdown'] = u.loc[active_invalid].groupby(['Month','Active Days']).size().reset_index(name='rows').to_dict(orient='records')
r['date_anomalies']['negative_usage_metric_rows'] = (u[['Active Days','Sessions','Product Actions','Collaborators','Integrations Used']] < 0).any(axis=1).sum()

jpair = j[['Customer ID', 'Product Purchased']].drop_duplicates().rename(columns={'Product Purchased': 'Product'})
upair = u[['Customer ID','Product']].drop_duplicates()
paircheck = jpair.merge(upair, on=['Customer ID','Product'], how='outer', indicator=True)
r['ticket_usage_link'] = {
    'ticket_customer_product_pairs': len(jpair),
    'customer_product_pairs_both': (paircheck['_merge'] == 'both').sum(),
    'ticket_pairs_without_usage': (paircheck['_merge'] == 'left_only').sum(),
    'usage_pairs_without_ticket': (paircheck['_merge'] == 'right_only').sum(),
    'tickets_with_any_customer_usage': j['Customer ID'].isin(u['Customer ID']).sum(),
    'tickets_with_same_product_usage': len(j.merge(upair, left_on=['Customer ID','Product Purchased'], right_on=['Customer ID','Product'], how='inner', validate='many_to_one')),
}
r['csat'] = {'nonmissing': t['Customer Satisfaction Rating'].notna().sum(), 'rating_counts': dist(t['Customer Satisfaction Rating']), 'status_vs_rating_present': pd.crosstab(t['Ticket Status'], t['Customer Satisfaction Rating'].notna()).to_dict()}

def encode(x):
    if hasattr(x, 'item'):
        return x.item()
    return str(x)

out = json.dumps(r, ensure_ascii=False, indent=2, default=encode)
(ROOT / 'independent_check.json').write_text(out, encoding='utf-8')
print(out)
