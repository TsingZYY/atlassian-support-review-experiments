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
    'minimal_model/verify.py', 'simulation/run_simulation.py',
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
    simulation = read('simulation/results.json')
    assert validation['primary']['alerts'] == 582
    assert validation['predictive_gate_pass'] is False
    assert abs(validation['month_permutation']['one_sided_p'] - 0.46553446553446554) < 1e-12
    assert model['decision_counts'] == {'DATA_CHECK':347,'REVIEW_CANDIDATE':43,'STANDARD_SUPPORT':8079}
    assert checks['frozen_source_cases_verified'] == 20 and len(checks['boundary_cases']) == 10
    for scenario, expected in [('positive',3),('unrelated',0),('reverse',-3)]:
        row = next(x for x in simulation['results'] if x['scenario'] == scenario and x['information_overhead_units'] == 0)
        assert abs(row['analytic_gain_pp'] - expected) < 1e-10
    assert simulation['real_customer_resolution_effect'] is None
    report = {'status':'PASS', 'executed_at':datetime.now(timezone.utc).isoformat(),
              'steps_completed':STEPS, 'key_snapshot_claims_verified':True,
              'business_efficacy':'UNVERIFIED', 'real_customer_trial':'CANDIDATE-UNRUN'}
    (ROOT / 'reproduction_check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('REPRODUCTION PASS: source, model and simulation checks passed; business efficacy remains unverified.')


if __name__ == '__main__':
    main()
