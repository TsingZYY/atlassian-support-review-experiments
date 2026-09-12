"""Read-only outcome-availability check; no intervention-effect estimate."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import pandas as pd

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'resolution_validation'
OUT.mkdir(exist_ok=True)
paths = {
    'tickets': ROOT / 'data/customer_support_tickets.csv',
    'usage': ROOT / 'data/product_usage.csv',
    'candidates': ROOT / 'validation_v1/review_candidates.csv',
    'review_key': ROOT / 'validation_v1/blind_review_key.csv',
}
t = pd.read_csv(paths['tickets'])
u = pd.read_csv(paths['usage'])
cohorts = {
    'candidate_list': pd.read_csv(paths['candidates'])['Ticket ID'],
    'prepared_review_sample': pd.read_csv(paths['review_key'])['Ticket ID'],
}
assert t['Ticket ID'].is_unique
result = {
    'executed_at': datetime.now(timezone.utc).isoformat(),
    'scope': 'Supplied synthetic competition data only; missing outcomes are unknown, not failed resolutions.',
    'source': 'https://drive.google.com/drive/folders/1NirfOKfM54cYeYXS3gn3azWznX1jaFiP',
    'source_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths.values()},
    'ticket_columns': list(t.columns),
    'usage_months': sorted(u['Month'].unique().tolist()),
    'cohorts': {},
    'intervention_assignment_field_available': False,
    'intervention_action_log_available': False,
    'post_intervention_outcome_available': False,
    'measured_resolution_improvement': None,
    'measured_time_saving': None,
    'human_trial_status': 'CANDIDATE-UNRUN',
}
for label, ids in cohorts.items():
    q = t[t['Ticket ID'].isin(ids)]
    assert len(q) == len(ids) and ids.is_unique
    result['cohorts'][label] = {
        'tickets': len(q),
        'nonmissing_fields': {c: int(q[c].notna().sum()) for c in [
            'Resolution', 'Time to Resolution', 'Customer Satisfaction Rating']},
        'status_counts': q['Ticket Status'].value_counts().to_dict(),
    }
(OUT / 'evidence_check.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
# Empty means unobserved. This template contains no synthetic successes or assignments.
fields = ['case_id', 'matched_pair_id', 'rule_hit_before_assignment',
          'usual_queue_rank_before_assignment', 'assigned_queue',
          'chosen_for_extra_review', 'assignment_time', 'review_started_at',
          'review_ended_at', 'total_staff_minutes', 'specific_action',
          'source_evidence_for_action', 'different_action_due_to_usage_information',
          'why_action_changed', 'customer_confirmed_resolved_within_7d',
          'resolved_at', 'resolution_evidence', 'followup_state_resolved_unresolved_unknown',
          'reopened_within_7d', 'outside_arm_help_or_crossover', 'notes']
template = OUT / 'trial_log_blank.csv'
if not template.exists():
    pd.DataFrame([{'case_id': f'PILOT-{i:02d}'} for i in range(1,21)], columns=fields).to_csv(template, index=False, encoding='utf-8-sig')
print(json.dumps({k: result[k] for k in ['cohorts','measured_resolution_improvement','human_trial_status']}, ensure_ascii=False, indent=2))
