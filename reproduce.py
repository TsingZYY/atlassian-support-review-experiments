"""Reproduce the current experiment snapshot and check its principal claims."""
from pathlib import Path
from datetime import datetime, timezone
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
STEPS = [
    'inspect_case.py', 'independent_check.py', 'validation_independent.py',
    'package_validation.py', 'check_resolution_evidence.py',
    'verify_competition_cases.py', 'minimal_model/model.py',
    'minimal_model/verify.py', 'csat_context_v1/experiment.py',
    'product_churn_v1/experiment.py',
    'profit_opportunity_v1/experiment.py',
    'profit_evidence_v2/experiment.py',
]


def main():
    for step in STEPS:
        print(f'Running {step}', flush=True)
        subprocess.run([sys.executable, str(ROOT / step)], cwd=ROOT, check=True)
    def read(path):
        return json.loads((ROOT / path).read_text(encoding='utf-8'))
    validation = read('validation_v1/validation_results.json')
    model = read('minimal_model/outputs/summary.json')
    checks = read('minimal_model/outputs/verification.json')
    csat = read('csat_context_v1/results.json')
    products = read('product_churn_v1/results.json')
    profit = read('profit_opportunity_v1/results.json')
    evidence = read('profit_evidence_v2/results.json')
    assert validation['primary']['alerts'] == 582
    assert validation['predictive_gate_pass'] is False
    assert abs(validation['month_permutation']['one_sided_p'] - 0.46553446553446554) < 1e-12
    assert model['decision_counts'] == {'DATA_CHECK':347,'REVIEW_CANDIDATE':43,'STANDARD_SUPPORT':8079}
    assert checks['frozen_source_cases_verified'] == 20 and len(checks['boundary_cases']) == 10
    assert csat['dataset_scope'] == 'competition_csv_only' and csat['new_synthetic_cases'] == 0
    assert csat['split_n'] == {'training':2100,'development':524,'test':20}
    assert csat['exploratory_gate_pass'] is False
    assert abs(csat['brier_gain_ticket_minus_full'] - (-0.0016263333242940588)) < 1e-10
    assert products['dataset_scope'] == 'competition_csv_only' and products['new_synthetic_cases'] == 0
    assert products['quality']['primary_customer_product_pairs'] == 8181
    assert products['quality']['usage_eligible_pairs'] == 8122
    assert products['indicators']['cancellation_request']['events'] == 1634
    assert abs(products['indicators']['cancellation_request']['overall_p'] - 0.3940726943079439) < 1e-10
    assert products['indicators']['usage_stopped_pattern']['overall_p'] is None
    assert products['real_churn_observed'] is False and products['source_audit_cases_verified'] == 20
    assert profit['dataset_scope'] == 'competition_csv_only' and profit['new_synthetic_observations'] == 0
    assert profit['free_eligible_customers'] == 1440 and profit['selected_source_records'] == 20
    assert profit['primary']['complete'] is True
    assert profit['primary']['selected_may_sum'] == {'priority':121,'comparison':109}
    assert abs(profit['primary']['one_sided_exact_permutation_p'] - 0.2856224279835391) < 1e-12
    assert profit['primary']['exploratory_proxy_support'] is False
    assert profit['business_outcomes']['incremental_profit'] is None
    assert evidence['dataset_scope'] == 'competition_csv_only' and evidence['new_synthetic_observations'] == 0
    assert evidence['source_overview']['eligible_candidate_customers'] == 377 and evidence['case_count'] == 20
    assert evidence['observed_five_month_context_n'] == 20
    assert evidence['coverage']['ticket_only']['specific_need'] == {'NOT_ESTABLISHED':20}
    assert evidence['coverage']['enriched']['specific_need'] == {'NOT_ESTABLISHED':20}
    assert evidence['evidence_sufficient_for_paid_recommendation_n'] == 0 and evidence['profit_uplift'] is None
    assert evidence['route_counts'] == {'CLARIFY_REQUEST':17,'SUPPORT_FIRST':2,'REQUIREMENT_REVIEW':1}
    report = {'status':'PASS', 'executed_at':datetime.now(timezone.utc).isoformat(),
              'steps_completed':STEPS, 'key_snapshot_claims_verified':True,
              'main_experiment_scope':'competition_csv_only', 'csat_hypothesis_supported':False,
              'product_churn_ranking_established':False,
              'profit_screening_proxy_supported':False, 'profit_uplift_established':False,
              'paid_reason_evidence_established':False, 'profit_evidence_cases_verified':20,
              'business_efficacy':'UNVERIFIED', 'real_customer_trial':'CANDIDATE-UNRUN'}
    (ROOT / 'reproduction_check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('REPRODUCTION PASS: competition-data calculations verified; profit uplift remains unverified.')


if __name__ == '__main__':
    main()
