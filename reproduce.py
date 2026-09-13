"""Reproduce the current experiment snapshot and check its principal claims."""
from pathlib import Path
from datetime import datetime, timezone
import json
import argparse
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
    'channel_hypotheses_v1/experiment.py',
    'channel_hypotheses_v1/independent_verify.py',
    'integration_plan_v1/experiment.py',
    'integration_plan_v1/independent_verify.py',
]


def main(include_scenarios=False):
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
    channels = read('channel_hypotheses_v1/results.json')
    integrations = read('integration_plan_v1/results.json')
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
    assert channels['dataset_scope'] == 'competition_csv_only' and channels['new_synthetic_observations'] == 0
    assert channels['technical_total'] == 1747 and channels['technical_rated_closed'] == 580
    assert channels['primary']['email_n'] == 135 and channels['primary']['social_n'] == 152
    assert abs(channels['primary']['mean_difference'] - 0.23684210526315796) < 1e-12
    assert channels['primary']['email_higher_supported'] is False
    assert channels['primary']['bootstrap_95'][0] < 0 < channels['primary']['bootstrap_95'][1]
    assert channels['adjusted_sensitivity']['common_support_n'] == 287
    assert channels['payment_closed'] == 156 and channels['payment_timestamp_states']['resolution_before_first_response'] == 82
    assert channels['payment_chat_faster_conclusion'] == 'NOT_IDENTIFIABLE_FROM_AVAILABLE_TIMESTAMPS'
    assert channels['source_audit_case_n'] == 20 and channels['measured_profit_effect'] is None
    assert integrations['dataset_scope'] == 'competition_csv_only' and integrations['new_synthetic_observations'] == 0
    assert integrations['quality']['primary_customer_n'] == 8320
    assert integrations['quality']['common_metrics_customer_n'] == 8261
    assert abs(integrations['primary']['eta_squared_ols_r2'] - 0.8793435370848043) < 1e-10
    assert integrations['common_cohort_metric_ranking']['integration_is_largest'] is True
    assert abs(integrations['customer_holdout']['test_r2'] - 0.8726475449858313) < 1e-10
    assert integrations['customer_holdout']['no_customer_overlap'] is True
    assert integrations['zero_usage']['all_records_zero_customers'] == 4
    assert integrations['audit_source_customers'] == 20 and integrations['measured_profit_effect'] is None
    report = {'status':'PASS', 'executed_at':datetime.now(timezone.utc).isoformat(),
              'steps_completed':STEPS, 'key_snapshot_claims_verified':True,
              'main_experiment_scope':'competition_csv_only', 'csat_hypothesis_supported':False,
              'product_churn_ranking_established':False,
              'profit_screening_proxy_supported':False, 'profit_uplift_established':False,
              'paid_reason_evidence_established':False, 'profit_evidence_cases_verified':20,
              'technical_email_rating_advantage_established':False,
              'payment_channel_speed_identifiable':False,
              'integration_plan_association_supported':True,
              'integration_nonuse_reasons_observed':False,
              'business_efficacy':'UNVERIFIED', 'real_customer_trial':'CANDIDATE-UNRUN'}
    if include_scenarios:
        subprocess.run([sys.executable, str(ROOT/'profit_scenarios_v1/experiment.py')], cwd=ROOT, check=True)
        simulation = read('profit_scenarios_v1/results.json')
        assert simulation['evidence_type'] == 'USER_AUTHORIZED_CONDITIONAL_SIMULATION_NOT_EMPIRICAL_PROFIT'
        assert simulation['observed_customer_source_records'] == 20 and simulation['new_real_customer_outcomes'] == 0
        assert simulation['repetitions'] == 100000 and simulation['all_analytic_monte_carlo_checks_passed']
        assert simulation['scenario_grid_rows'] == 300
        worlds = {s['id']:s for s in simulation['scenarios']}
        assert abs(worlds['positive']['expected_priority_minus_comparison']-140.26650963221823) < 1e-9
        assert abs(worlds['unrelated']['expected_priority_minus_comparison']+20) < 1e-9
        assert abs(worlds['negative']['expected_priority_minus_comparison']+180.26650963221826) < 1e-9
        assert abs(worlds['natural_conversion_trap']['groups']['priority']['expected_incremental_profit']+90) < 1e-9
        report['conditional_simulation'] = {'status':'PASS','script':'profit_scenarios_v1/experiment.py',
                                            'repetitions_per_scenario':100000,'actual_profit_verified':False}
    (ROOT / 'reproduction_check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('REPRODUCTION PASS: competition-data calculations verified; profit uplift remains unverified.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--include-scenarios', action='store_true')
    main(parser.parse_args().include_scenarios)
