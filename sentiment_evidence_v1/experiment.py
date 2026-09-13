"""Observed experience evidence and a bounded retrospective text/CSAT check."""
from collections import Counter, defaultdict
from pathlib import Path
from datetime import datetime, timezone
import argparse
import csv
import hashlib
import json
import math
import re
import numpy as np

HERE=Path(__file__).resolve().parent
DATA=HERE.parent/'data'


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def digest(text): return hashlib.sha256(text.encode()).hexdigest()
def norm(text): return text.strip().casefold()


def read(name):
    with (DATA/name).open(encoding='utf-8-sig',newline='') as stream: return list(csv.DictReader(stream))


def write(name,obj):
    (HERE/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8',newline='\n')


def csv_out(name,rows):
    with (HERE/name).open('w',encoding='utf-8',newline='') as stream:
        out=csv.DictWriter(stream,fieldnames=list(rows[0]),lineterminator='\n'); out.writeheader(); out.writerows(rows)


def score(ticket):
    if not ticket['Customer Satisfaction Rating']: return None
    value=float(ticket['Customer Satisfaction Rating'])
    assert math.isfinite(value) and value.is_integer() and 1<=value<=5
    return int(value)


def state(value):
    return 'UNOBSERVED' if value is None else 'LOW_REPORTED' if value<=2 else 'MIDDLE_REPORTED' if value==3 else 'HIGH_REPORTED'


def card(ticket,source_row):
    value=score(ticket); group=state(value)
    return {'ticket_id':ticket['Ticket ID'],'source':{'file':'data/customer_support_tickets.csv','record_row':source_row},
            'ticket_context':{f:ticket[f] for f in ('Product Purchased','Ticket Type','Ticket Subject','Ticket Priority','Ticket Channel','Ticket Status')},
            'csat':{'score':value,'evidence_state':group,'source_field':'Customer Satisfaction Rating'},
            'customer_sentiment':'UNKNOWN_NO_CUSTOMER_VERBATIM_OR_SENTIMENT_LABEL',
            'resolution_record':ticket['Resolution'] or None,'resolution_is_verified_customer_verbatim':False,
            'review_route':'REVIEW_REPORTED_LOW_CSAT' if group=='LOW_REPORTED' else 'FEEDBACK_NOT_OBSERVED' if group=='UNOBSERVED' else 'KEEP_OBSERVED_SCORE',
            'suggested_next_step':'核对客户原始反馈及处理经过' if group=='LOW_REPORTED' else '保留缺失；需直接反馈后再判断' if group=='UNOBSERVED' else '保留评分及来源，不推断情绪或挽回效果',
            'measured_recovery_outcome':None,'measured_profit_effect':None}


def auc(y,p):
    pos=p[y==1]; neg=p[y==0]
    return float(np.mean((pos[:,None]>neg).astype(float)+.5*(pos[:,None]==neg))) if len(pos) and len(neg) else None


def metrics(y,p):
    clipped=np.clip(p,1e-12,1-1e-12)
    return {'n':len(y),'low_csat_n':int(y.sum()),'brier':float(np.mean((p-y)**2)), 'auc':auc(y,p),
            'log_loss':float(-np.mean(y*np.log(clipped)+(1-y)*np.log(1-clipped))),
            'accuracy_at_05':float(np.mean((p>=.5)==y)),'predicted_low_at_05':int(np.sum(p>=.5))}


def text_experiment(tickets,customers,p):
    by_email={norm(c['Customer Email']):c for c in customers}; assert len(by_email)==len(customers)
    conflicts=set()
    for t in tickets:
        c=by_email[norm(t['Customer Email'])]
        if any(norm(t[f])!=norm(c[f]) for f in ('Customer Name','Customer Age','Customer Gender')): conflicts.add(c['Customer ID'])
    rated=[t for t in tickets if t['Ticket Status']=='Closed' and score(t) is not None and t[p['text_field']]]
    cohort=[dict(ticket=t,cid=by_email[norm(t['Customer Email'])]['Customer ID']) for t in rated
            if by_email[norm(t['Customer Email'])]['Customer ID'] not in conflicts]
    assert len(cohort)==len({r['cid'] for r in cohort})
    cohort.sort(key=lambda r:digest(p['split_salt']+'|'+r['cid']))
    cut=int(len(cohort)*p['training_fraction']); train=cohort[:cut]; test=cohort[cut:]
    tokenize=lambda r:re.findall(p['token_regex'],r['ticket'][p['text_field']].lower())
    df=Counter(w for r in train for w in set(tokenize(r)))
    vocab=sorted(w for w,n in df.items() if n>=p['minimum_training_document_frequency']); vi={w:i for i,w in enumerate(vocab)}
    assert vocab
    def encode(rows):
        x=np.zeros((len(rows),len(vocab)),dtype=float); unseen=0; total=0
        for i,r in enumerate(rows):
            for w in tokenize(r):
                total+=1
                if w in vi: x[i,vi[w]]+=1
                else: unseen+=1
        return x,unseen,total
    x,_,_=encode(train); z,unknown,total_tokens=encode(test)
    y=np.array([int(score(r['ticket'])<=2) for r in train]); yt=np.array([int(score(r['ticket'])<=2) for r in test])
    counts=np.array([x[y==c].sum(axis=0) for c in (0,1)])+p['smoothing_alpha']
    log_word=np.log(counts/counts.sum(axis=1,keepdims=True)); prior=np.array([np.mean(y==c) for c in (0,1)])
    assert np.all(prior>0)
    log_scores=z@log_word.T+np.log(prior)
    prob=1/(1+np.exp(np.clip(log_scores[:,0]-log_scores[:,1],-700,700)))
    baseline=np.full(len(yt),y.mean()); difference=(baseline-yt)**2-(prob-yt)**2
    rng=np.random.default_rng(p['bootstrap_seed'])
    boot=difference[rng.integers(0,len(yt),(p['bootstrap_repetitions'],len(yt)))].mean(axis=1)
    ci=np.quantile(boot,[.025,.975]).tolist()
    result={'training_n':len(train),'test_n':len(test),'identity_conflict_customers':len(conflicts),
            'eligible_closed_n':len(cohort),'training_low_csat_n':int(y.sum()),'test_low_csat_n':int(yt.sum()),
            'vocabulary_size':len(vocab),'test_unknown_token_count':unknown,'test_token_count':total_tokens,
            'test_documents_with_no_known_tokens':int(np.sum(z.sum(axis=1)==0)),
            'baseline':metrics(yt,baseline),'resolution_bag_of_words':metrics(yt,prob),
            'brier_gain_baseline_minus_text':float(difference.mean()),'paired_bootstrap_95':ci,
            'text_csat_increment_supported':bool(difference.mean()>0 and ci[0]>0),
            'customer_disjoint':True,'semantic_sentiment_accuracy':None,
            'valid_for_unclosed_tickets':False,'label_is_observed_csat_not_sentiment':True}
    predictions=[{'ticket_id':r['ticket']['Ticket ID'],'customer_id':r['cid'],'observed_rating':score(r['ticket']),
                  'low_csat':int(yt[i]),'baseline_probability':float(baseline[i]),'text_probability':float(prob[i]),
                  'paired_brier_gain':float(difference[i])} for i,r in enumerate(test)]
    csv_out('text_test_predictions.csv',predictions)
    csv_out('text_split.csv',[{'customer_id':r['cid'],'ticket_id':r['ticket']['Ticket ID'],'split':part}
                            for part,group in [('train',train),('test',test)] for r in group])
    write('text_model.json',{'vocabulary':vocab,'training_document_frequency':{w:df[w] for w in vocab},
                            'class_prior':prior.tolist(),'word_log_probability':log_word.tolist(),'alpha':p['smoothing_alpha']})
    return result


def main(ticket_id=None):
    p=json.loads((HERE/'protocol.json').read_text(encoding='utf-8')); tickets=read('customer_support_tickets.csv')
    if ticket_id is not None:
        selected=[(i,t) for i,t in enumerate(tickets,2) if t['Ticket ID']==str(ticket_id)]
        assert len(selected)==1,'Ticket ID not found or not unique'
        i,t=selected[0]; print(json.dumps(card(t,i),ensure_ascii=False,indent=2)); return
    hashes={'source_sha256':{n:sha(DATA/n) for n in ('customers.csv','customer_support_tickets.csv','README.md')},
            'protocol_code_sha256':{n:sha(HERE/n) for n in ('protocol.json','protocol.md','experiment.py')}}
    if (HERE/'execution_lock.json').exists():
        old=json.loads((HERE/'execution_lock.json').read_text(encoding='utf-8')); assert all(old[k]==v for k,v in hashes.items())
    else: write('execution_lock.json',dict(hashes,frozen_at=datetime.now(timezone.utc).isoformat()))
    resolutions=[t['Resolution'] for t in tickets if t['Resolution']]
    lengths=[len(re.findall('[A-Za-z]+',s)) for s in resolutions]
    profile={'ticket_count':len(tickets),'ticket_fields':list(tickets[0]),'subject_counts':dict(Counter(t['Ticket Subject'] for t in tickets)),
             'resolution_nonempty':len(resolutions),'resolution_unique':len(set(resolutions)),
             'resolution_digit_normalized_unique':len({re.sub(r'\d+','<NUMBER>',s) for s in resolutions}),
             'resolution_word_count_min':min(lengths),'resolution_word_count_max':max(lengths),'resolution_word_count_mean':float(np.mean(lengths)),
             'customer_verbatim_field_available':False,'sentiment_annotation_field_available':False,
             'rating_counts':dict(Counter(str(score(t)) for t in tickets)),
             'status_coverage':[{'status':s,'tickets':len(group),'ratings':sum(score(t) is not None for t in group),
                                 'resolutions':sum(bool(t['Resolution']) for t in group)} for s in sorted({t['Ticket Status'] for t in tickets})
                                for group in [[t for t in tickets if t['Ticket Status']==s]] ]}
    all_cards=[card(t,i) for i,t in enumerate(tickets,2)]
    states=Counter(c['csat']['evidence_state'] for c in all_cards)
    audit=[]
    for group in p['audit_groups']:
        choices=sorted([c for c in all_cards if c['csat']['evidence_state']==group],key=lambda c:digest(p['audit_salt']+'|'+c['ticket_id']))[:p['audit_per_group']]
        assert len(choices)==5; audit.extend(choices)
    write('evidence_cards_20.json',audit)
    csv_out('text_review_input_20.csv',[{'ticket_id':c['ticket_id'],'source_row':c['source']['record_row'],
              'ticket_type':c['ticket_context']['Ticket Type'],'subject':c['ticket_context']['Ticket Subject'],
              'resolution':c['resolution_record'] or ''} for c in audit])
    csv_out('all_ticket_evidence_index.csv',[{'ticket_id':c['ticket_id'],'source_row':c['source']['record_row'],
             'rating':c['csat']['score'],'csat_evidence_state':c['csat']['evidence_state'],'customer_sentiment':c['customer_sentiment'],
             'review_route':c['review_route']} for c in all_cards])
    text_result=text_experiment(tickets,read('customers.csv'),p)
    result={'executed_at':datetime.now(timezone.utc).isoformat(),'dataset_scope':'competition_csv_only','new_synthetic_observations':0,
            **hashes,'profile':profile,'evidence_state_counts':dict(states),
            'rating_coverage':sum(score(t) is not None for t in tickets)/len(tickets),
            'text_experiment':text_result,'source_audit_cases':len(audit),
            'all_tickets_customer_sentiment_unknown':len(all_cards),
            'customer_sentiment_accuracy':None,'real_resolution_rate':None,'measured_profit_effect':None,
            'prototype_scope':'observed_csat_evidence_and_review_workflow_not_sentiment_classifier'}
    write('results.json',result)
    print(json.dumps({'evidence_state_counts':result['evidence_state_counts'],'text_experiment':text_result},ensure_ascii=False,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--ticket-id')
    main(parser.parse_args().ticket_id)
