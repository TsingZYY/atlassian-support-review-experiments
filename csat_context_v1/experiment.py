"""Dataset-only, customer-disjoint, 20-case held-out low-CSAT experiment."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
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


def write(name, obj):
    (ROOT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')


def read(name):
    with (DATA/name).open(encoding='utf-8-sig',newline='') as f:
        return list(csv.DictReader(f))


def norm(value):
    return str(value or '').strip().casefold()


def assemble(protocol):
    customers, tickets, usage = [read(n) for n in ('customers.csv','customer_support_tickets.csv','product_usage.csv')]
    customer_index, usage_index = defaultdict(list), defaultdict(list)
    for row in customers:
        customer_index[norm(row['Customer Email'])].append(row)
    for row in usage:
        usage_index[(row['Customer ID'],row['Product'],row['Month'])].append(row)
    conflicts = set()
    for ticket in tickets:
        match = customer_index[norm(ticket['Customer Email'])]
        if len(match) == 1 and any(norm(ticket[f]) != norm(match[0][f]) for f in ('Customer Name','Customer Age','Customer Gender')):
            conflicts.add(match[0]['Customer ID'])
    stages, rejected, qualified = [], Counter(), []
    closed = [t for t in tickets if t['Ticket Status'] == 'Closed']
    def record_stage(name, rows):
        stages.append({'stage':name,'tickets':len(rows),'unique_emails':len({norm(t['Customer Email']) for t in rows})})
    record_stage('all_tickets',tickets)
    record_stage('closed',closed)
    scored = []
    for ticket in closed:
        try:
            score = float(ticket['Customer Satisfaction Rating'])
            assert math.isfinite(score) and score.is_integer() and 1 <= score <= 5
        except (ValueError, AssertionError, TypeError):
            rejected['invalid_or_missing_rating'] += 1
            continue
        scored.append(ticket)
    record_stage('valid_closed_rating',scored)
    identity_ok = []
    for ticket in scored:
        match = customer_index[norm(ticket['Customer Email'])]
        if len(match) != 1:
            rejected['nonunique_or_missing_customer'] += 1
            continue
        if match[0]['Customer ID'] in conflicts:
            rejected['customer_has_identity_field_conflict'] += 1
            continue
        identity_ok.append(ticket)
    record_stage('identity_consistent',identity_ok)
    usable_tickets = []
    for ticket in identity_ok:
        customer = customer_index[norm(ticket['Customer Email'])][0]
        cid, product = customer['Customer ID'], ticket['Product Purchased']
        monthly, failure = [], None
        for month in protocol['months']:
            candidates = usage_index[(cid,product,month)]
            if len(candidates) != 1:
                failure = 'usage_month_not_unique_or_missing'
                break
            try:
                values = [float(candidates[0][f]) for f in protocol['usage_columns']]
                days = calendar.monthrange(*map(int,month.split('-')))[1]
                assert all(math.isfinite(v) and v >= 0 for v in values)
                assert values[0].is_integer() and values[0] <= days
            except (ValueError, KeyError, AssertionError):
                failure = 'invalid_usage_value'
                break
            monthly.append([values[0]/days]+[math.log1p(v) for v in values[1:]])
        if failure:
            rejected[failure] += 1
            continue
        matrix = np.array(monthly)
        numeric = np.concatenate([matrix.mean(axis=0),matrix[-1]-matrix[0]]).tolist()
        qualified.append({'customer_id':cid,'ticket_id':ticket['Ticket ID'],
            'categories':{f:ticket[f] for f in protocol['ticket_categories']} | {f:customer[f] for f in protocol['profile_categories']},
            'usage_features':numeric})
        usable_tickets.append(ticket)
    record_stage('valid_jan_apr_same_product_usage',usable_tickets)
    selected = {}
    for row in sorted(qualified,key=lambda r:int(r['ticket_id'])):
        selected.setdefault(row['customer_id'],row)
    records = list(selected.values())
    records.sort(key=lambda r:hashlib.sha256((protocol['split_salt']+'|'+r['customer_id']).encode()).hexdigest())
    return records, {'stages':stages,'first_rejection_counts':dict(rejected),
                     'identity_conflict_customers_all_tickets':len(conflicts),
                     'eligible_tickets':len(qualified),'one_ticket_per_customer':len(records),
                     'additional_eligible_tickets_removed':len(qualified)-len(records)}


def read_labels(records):
    wanted = {r['ticket_id'] for r in records}
    labels = {t['Ticket ID']:float(t['Customer Satisfaction Rating']) for t in read('customer_support_tickets.csv') if t['Ticket ID'] in wanted}
    return np.array([int(labels[r['ticket_id']] <= 2) for r in records],dtype=float), labels


def fit_encoder(records, protocol, full):
    fields = protocol['ticket_categories'] + (protocol['profile_categories'] if full else [])
    levels = {f:sorted({r['categories'][f] for r in records}) for f in fields}
    numeric = np.array([r['usage_features'] for r in records])
    std = numeric.std(axis=0)
    std[std < 1e-12] = 1
    return {'fields':fields,'levels':levels,'full_context':full,'means':numeric.mean(axis=0).tolist(),
            'stds':std.tolist(),'numeric_clip':protocol['numeric_clip_training_std']}


def encode(records, encoder):
    blocks, names = [np.ones((len(records),1))], ['intercept']
    for field in encoder['fields']:
        levels = encoder['levels'][field]
        blocks.append(np.array([[float(r['categories'][field] == level) for level in levels] for r in records]))
        names += [field+'='+level for level in levels]
    if encoder['full_context']:
        matrix = (np.array([r['usage_features'] for r in records])-np.array(encoder['means']))/np.array(encoder['stds'])
        blocks.append(np.clip(matrix,-encoder['numeric_clip'],encoder['numeric_clip']))
        names += ['usage_mean_'+f for f in ('activity_rate','log_sessions','log_actions','log_collaborators','log_integrations')]
        names += ['usage_apr_minus_jan_'+f for f in ('activity_rate','log_sessions','log_actions','log_collaborators','log_integrations')]
    return np.concatenate(blocks,axis=1), names


def sigmoid(z):
    return 1/(1+np.exp(-np.clip(z,-40,40)))


def train(x, y, regularization, protocol):
    weights = np.zeros(x.shape[1])
    prevalence = np.clip(y.mean(),1e-6,1-1e-6)
    weights[0] = math.log(prevalence/(1-prevalence))
    penalty = np.ones(x.shape[1])*regularization
    penalty[0] = 0
    def loss(w):
        z = x@w
        return float(np.mean(np.logaddexp(0,z)-y*z)+0.5*np.sum(penalty*w*w))
    for iteration in range(protocol['max_newton_iterations']):
        p = sigmoid(x@weights)
        gradient = x.T@(p-y)/len(y)+penalty*weights
        if float(np.max(np.abs(gradient))) <= protocol['gradient_tolerance']:
            break
        hessian = (x.T*(p*(1-p)))@x/len(y)+np.diag(penalty)+np.eye(x.shape[1])*1e-10
        step = np.linalg.solve(hessian,gradient)
        scale, current = 1.0, loss(weights)
        while scale > 1e-10 and loss(weights-scale*step) > current-1e-4*scale*float(gradient@step):
            scale *= 0.5
        weights -= scale*step
    max_gradient = float(np.max(np.abs(x.T@(sigmoid(x@weights)-y)/len(y)+penalty*weights)))
    assert max_gradient < 1e-6, f'Optimizer did not converge: {max_gradient}'
    return weights, {'iterations':iteration+1,'max_abs_gradient':max_gradient,'objective':loss(weights)}


def auc(y, p):
    positive, negative = p[y == 1], p[y == 0]
    if not len(positive) or not len(negative):
        return None
    comparisons = positive[:,None]-negative[None,:]
    return float(np.mean((comparisons > 0)+0.5*(comparisons == 0)))


def metrics(y, p, records):
    p = np.clip(p,1e-12,1-1e-12)
    order = sorted(range(len(y)),key=lambda i:(-p[i],int(records[i]['ticket_id'])))
    return {'n':len(y),'low_rating_n':int(y.sum()),'brier':float(np.mean((p-y)**2)),
            'auc':auc(y,p),'log_loss':float(-np.mean(y*np.log(p)+(1-y)*np.log(1-p))),
            'accuracy_at_0_5':float(np.mean((p >= .5) == y)),
            'top_5_observed_low_rating_n':int(sum(y[i] for i in order[:5]))}


def main():
    protocol = json.loads((ROOT/'protocol.json').read_text(encoding='utf-8'))
    source_hashes = {n:sha(DATA/n) for n in ('customers.csv','customer_support_tickets.csv','product_usage.csv')}
    frozen_hashes = {n:sha(ROOT/n) for n in ('protocol.json','protocol.md','experiment.py')}
    lock = ROOT/'execution_lock.json'
    if lock.exists():
        previous = json.loads(lock.read_text(encoding='utf-8'))
        assert previous['source_sha256'] == source_hashes and previous['protocol_code_sha256'] == frozen_hashes, 'Frozen source/protocol/code changed; use a new documented version.'
    else:
        write(lock.name,{'frozen_at':datetime.now(timezone.utc).isoformat(),'source_sha256':source_hashes,'protocol_code_sha256':frozen_hashes})
    records, eligibility = assemble(protocol)
    test = records[:protocol['test_customers']]
    remainder = records[protocol['test_customers']:]
    ndev = math.floor(len(remainder)*protocol['development_fraction_of_remainder'])
    dev, training = remainder[:ndev], remainder[ndev:]
    groups = {'training':training,'development':dev,'test':test}
    ids = [{r['customer_id'] for r in rs} for rs in groups.values()]
    assert len(test) == 20 and all(not ids[i]&ids[j] for i in range(3) for j in range(i))
    write('split_manifest.json',{'selection_uses_rating_class':False,
        'groups':{g:[{'customer_id':r['customer_id'],'ticket_id':r['ticket_id']} for r in rs] for g,rs in groups.items()},
        'eligibility':eligibility})
    ytrain,_ = read_labels(training)
    ydev,_ = read_labels(dev)
    models, development = {}, {}
    for label, full in [('ticket_only',False),('full_context',True)]:
        encoder = fit_encoder(training,protocol,full)
        xtrain, names = encode(training,encoder)
        xdev,_ = encode(dev,encoder)
        attempts = []
        for regularization in protocol['l2_grid']:
            weights, diagnostics = train(xtrain,ytrain,regularization,protocol)
            stats = metrics(ydev,sigmoid(xdev@weights),dev)
            attempts.append((stats['brier'],-regularization,weights,diagnostics,stats))
        chosen = min(attempts,key=lambda item:(item[0],item[1]))
        models[label] = {'encoder':encoder,'feature_names':names,'weights':chosen[2].tolist(),
                         'l2':-chosen[1],'optimizer':chosen[3]}
        development[label] = [{'l2':-a[1],**a[4]} for a in attempts]
    write('model_freeze.json',{'frozen_at':datetime.now(timezone.utc).isoformat(),'test_scoring_started':False,
        'split_manifest_sha256':sha(ROOT/'split_manifest.json'),'training_prevalence':float(ytrain.mean()),
        'training_n':len(training),'development_n':len(dev),'models':models,'development_grid':development})
    # Test outcome scoring starts only after encoder, regularization and weights are saved.
    ytest, raw_scores = read_labels(test)
    probabilities = {'training_prevalence':np.full(len(test),ytrain.mean())}
    for label, model in models.items():
        xtest,_ = encode(test,model['encoder'])
        probabilities[label] = sigmoid(xtest@np.array(model['weights']))
    stats = {label:metrics(ytest,p,test) for label,p in probabilities.items()}
    paired = (probabilities['ticket_only']-ytest)**2-(probabilities['full_context']-ytest)**2
    rng = np.random.default_rng(protocol['bootstrap_seed'])
    bootstrap = paired[rng.integers(0,len(test),size=(protocol['bootstrap_replicates'],len(test)))].mean(axis=1)
    interval = np.quantile(bootstrap,[.025,.975]).tolist()
    gate_parts = {'both_classes_present':0 < int(ytest.sum()) < len(test),
        'brier_gain_at_least_0_02':float(paired.mean()) >= protocol['min_absolute_brier_gain'],
        'paired_bootstrap_lower_bound_above_zero':interval[0] > 0,
        'beats_training_prevalence':stats['full_context']['brier'] < stats['training_prevalence']['brier']}
    case_rows = []
    for i, record in enumerate(test):
        case_rows.append({'case_id':f'CSAT-{i+1:02}','ticket_id':record['ticket_id'],'customer_id':record['customer_id'],
            'observed_rating':raw_scores[record['ticket_id']],'low_rating':int(ytest[i]),
            **{name+'_probability':float(p[i]) for name,p in probabilities.items()},
            'paired_brier_gain':float(paired[i])})
    with (ROOT/'test_cases_20.csv').open('w',encoding='utf-8',newline='') as f:
        writer = csv.DictWriter(f,fieldnames=list(case_rows[0]))
        writer.writeheader()
        writer.writerows(case_rows)
    unseen = {name:{f:sum(r['categories'][f] not in model['encoder']['levels'][f] for r in test)
                    for f in model['encoder']['fields']} for name,model in models.items()}
    result = {'executed_at':datetime.now(timezone.utc).isoformat(),'dataset_scope':'competition_csv_only',
        'outcome_source':'unmodified CSV Customer Satisfaction Rating', 'new_synthetic_cases':0,
        'source_sha256':source_hashes,'protocol_code_sha256':frozen_hashes,
        'model_freeze_sha256':sha(ROOT/'model_freeze.json'), 'eligibility':eligibility,
        'split_n':{name:len(rs) for name,rs in groups.items()},'test_metrics':stats,
        'selected_l2':{name:m['l2'] for name,m in models.items()},'unseen_test_category_counts':unseen,
        'brier_gain_ticket_minus_full':float(paired.mean()),'paired_bootstrap_95_interval':interval,
        'gate_parts':gate_parts,'exploratory_gate_pass':all(gate_parts.values()),
        'decision':'EXPLORATORY_SUPPORT_ONLY' if all(gate_parts.values()) else 'NOT_SUPPORTED_BY_THIS_TEST',
        'business_resolution_effect':'UNOBSERVED','temporal_prediction':'NOT_ESTABLISHED',
        'limits':['20 held-out customers only; source dataset previously explored.',
                  'Complete, identity-consistent, closed and rated customers only.',
                  'Retrospective discrimination; feature availability before rating is unverified.',
                  'Bootstrap resamples original rows; it does not add observations.']}
    assert source_hashes == {n:sha(DATA/n) for n in source_hashes}
    write('results.json',result)
    print(json.dumps({k:result[k] for k in ('split_n','test_metrics','selected_l2','brier_gain_ticket_minus_full',
        'paired_bootstrap_95_interval','gate_parts','exploratory_gate_pass','decision')},ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
