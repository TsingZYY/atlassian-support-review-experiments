"""Check frozen source cases and independently specified boundary cases."""
import csv
import json
from pathlib import Path
from model import evaluate, run_dataset

ROOT = Path(__file__).resolve().parent
CASE = ROOT.parent


def fixture(days=(31,0,0,7,7), status='Open', priority='High'):
    ticket = {'Ticket ID':'TEST','Customer ID':'TEST-CUSTOMER','Product Purchased':'Jira',
              'Ticket Status':status,'Ticket Priority':priority,'Ticket Subject':'Fixture only'}
    usage = [{'Customer ID':'TEST-CUSTOMER','Product':'Jira','Month':f'2023-{i:02d}','Active Days':str(d)}
             for i,d in enumerate(days,1)]
    return ticket, usage


def main():
    predictions = run_dataset(CASE / 'data')
    ids = [p['ticket_id'] for p in predictions]
    assert len(ids) == len(set(ids))
    by_id = {str(p['ticket_id']): p for p in predictions}
    # The source-alignment audit is independent of this model's implementation.
    cards = json.loads((CASE / 'competition_evidence/evidence_cards_20.json').read_text(encoding='utf-8'))
    for c in cards:
        p = by_id[str(c['source_ticket_id'])]
        expected = 'REVIEW_CANDIDATE' if c['review_rule_triggered'] else 'STANDARD_SUPPORT'
        assert p['decision'] == expected and p['customer_id'] == c['source_customer_id']
        assert all(abs(a-b) <= .005001 for a,b in zip(p['evidence']['monthly_activity_pct'], c['monthly_activity_pct']))
    with (CASE / 'validation_v1/review_candidates.csv').open(encoding='utf-8-sig', newline='') as f:
        expected_ids = {r['Ticket ID'] for r in csv.DictReader(f)}
    actual_ids = {p['ticket_id'] for p in predictions if p['decision'] == 'REVIEW_CANDIDATE'}
    assert actual_ids == expected_ids
    checked = []
    def check(name, ticket, usage, expected, flags=()):
        actual = evaluate(ticket, usage, quality_flags=flags)['decision']
        assert actual == expected, (name, actual, expected)
        checked.append({'case':name,'expected':expected,'actual':actual})
    # Baseline = 1/3; April = 7/30. Both thresholds equal exactly in rational arithmetic.
    t,u = fixture(); check('both_thresholds_inclusive',t,u,'REVIEW_CANDIDATE')
    t,u = fixture((0,0,0,0,0)); check('zero_baseline',t,u,'STANDARD_SUPPORT')
    t,u = fixture(status='Closed'); check('closed_ticket',t,u,'STANDARD_SUPPORT')
    t,u = fixture(priority='Low'); check('low_priority',t,u,'STANDARD_SUPPORT')
    t,u = fixture((31,0,0,7,31)); check('only_one_low_month',t,u,'STANDARD_SUPPORT')
    t,u = fixture(); check('missing_month',t,u[:-1],'DATA_CHECK')
    t,u = fixture(); check('duplicate_month',t,u+[u[-1]],'DATA_CHECK')
    t,u = fixture((31,29,0,7,7)); check('invalid_february_days',t,u,'DATA_CHECK')
    t,u = fixture(); check('identity_conflict',t,u,'DATA_CHECK',('customer_identity_conflict',))
    t,u = fixture(); u[0]['Customer ID']='OTHER'; check('usage_key_mismatch',t,u,'DATA_CHECK')
    report = {'frozen_source_cases_verified':len(cards),'full_candidate_set_matches':len(actual_ids),
              'boundary_cases':checked,
              'claim':'Implementation and source integrity only; not predictive accuracy or business efficacy.',
              'real_resolution_improvement':'UNOBSERVED'}
    (ROOT / 'outputs').mkdir(exist_ok=True)
    (ROOT / 'outputs/verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    example = by_id['6545']
    (ROOT / 'outputs/example_ticket_6545.json').write_text(json.dumps(example,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
