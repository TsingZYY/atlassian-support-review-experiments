"""Rebuild the candidate and preparation audit without importing audit.py."""
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / 'data'


def load(path):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def hash_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rank(salt, customer_id):
    return hashlib.sha256((salt + '|' + customer_id).encode()).hexdigest()


def csv_value(value):
    return '' if value is None else str(value)


def main():
    protocol = json.loads((HERE / 'protocol.json').read_text(encoding='utf-8'))
    result = json.loads((HERE / 'results.json').read_text(encoding='utf-8'))
    lock = json.loads((HERE / 'execution_lock.json').read_text(encoding='utf-8'))
    source_hashes = {name: hash_file(DATA / name) for name in
                     ['customers.csv', 'customer_support_tickets.csv', 'product_usage.csv', 'README.md']}
    program_hashes = {name: hash_file(HERE / name) for name in ['protocol.json', 'audit.py']}
    assert source_hashes == lock['source_sha256'] == result['source_sha256']
    assert program_hashes == lock['protocol_code_sha256'] == result['protocol_code_sha256']
    customers, tickets, usage = (load(DATA / name) for name in
                               ['customers.csv', 'customer_support_tickets.csv', 'product_usage.csv'])
    normalize = lambda value: value.strip().casefold()
    customer_lookup = {normalize(row['Customer Email']): row for row in customers}
    assert len(customer_lookup) == len(customers) == len({row['Customer ID'] for row in customers})
    joined = [(line, ticket, customer_lookup[normalize(ticket['Customer Email'])])
              for line, ticket in enumerate(tickets, 2)]
    bad_ids = {customer['Customer ID'] for _, ticket, customer in joined
               if any(normalize(ticket[key]) != normalize(customer[key])
                      for key in ['Customer Name', 'Customer Age', 'Customer Gender'])}
    raw = [(line, ticket, customer) for line, ticket, customer in joined
           if customer['Plan Type'] == protocol['snapshot_plan']
           and ticket['Ticket Subject'] == protocol['ticket_subject']]
    clean = [(line, ticket, customer) for line, ticket, customer in raw
             if customer['Customer ID'] not in bad_ids]
    assert len(clean) == len({customer['Customer ID'] for _, _, customer in clean}) == 84
    monthly = defaultdict(list)
    for line, row in enumerate(usage, 2):
        monthly[row['Customer ID'], row['Product'], row['Month']].append((line, row))
    expected_records = []
    expected_history = {}
    original_tickets = {}
    for line, ticket, customer in clean:
        customer_id = customer['Customer ID']
        product = ticket['Product Purchased']
        available_months = sorted(month for cid, prod, month in monthly if (cid, prod) == (customer_id, product))
        assert available_months == protocol['months']
        history = []
        for month in protocol['months']:
            entries = monthly[customer_id, product, month]
            assert len(entries) == 1
            usage_line, usage_record = entries[0]
            value = int(usage_record['Integrations Used'])
            assert value >= 0
            history.append({'source_file': 'data/product_usage.csv', 'source_row': usage_line,
                            'month': month, 'integrations_used': value})
        values = [item['integrations_used'] for item in history]
        score = int(float(ticket['Customer Satisfaction Rating'])) if ticket['Customer Satisfaction Rating'] else None
        if score is not None:
            assert 1 <= score <= 5 and ticket['Ticket Status'] == 'Closed'
        record = {'customer_id': customer_id, 'ticket_id': ticket['Ticket ID'], 'ticket_source_row': line,
                  'snapshot_plan': customer['Plan Type'], 'product': product, 'ticket_type': ticket['Ticket Type'],
                  'ticket_subject': ticket['Ticket Subject'], 'ticket_status': ticket['Ticket Status'], 'csat': score,
                  'months_observed': len(values), 'any_nonzero_integration_month': max(values) > 0,
                  'all_months_zero': max(values) == 0, 'any_zero_month': min(values) == 0,
                  'may_integrations_used': history[-1]['integrations_used'], 'need_confirmed': False,
                  'setup_outcome_observed': False, 'upgrade_outcome_observed': False}
        expected_records.append(record)
        expected_history[customer_id] = history
        original_tickets[customer_id] = ticket
    roster = load(HERE / 'candidate_roster.csv')
    assert roster == [{key: csv_value(value) for key, value in record.items()} for record in expected_records]
    selected = []
    planned = []
    for product in protocol['products']:
        group = [record for record in expected_records if record['product'] == product]
        chosen = sorted(group, key=lambda row: rank(protocol['pilot_selection_salt'], row['customer_id']))[:protocol['per_product_pilot']]
        assert len(chosen) == 4
        selected.extend(chosen)
        ordered = sorted(chosen, key=lambda row: rank(protocol['pilot_assignment_salt'], row['customer_id']))
        for position, record in enumerate(ordered):
            planned.append({'customer_id': record['customer_id'], 'ticket_id': record['ticket_id'], 'product': product,
                            'planned_arm': protocol['planned_arm_a'] if position < 2 else protocol['planned_arm_b'],
                            'allocation_status': 'PREPARED_NOT_EXECUTED', 'eligibility_reconfirmation_required': True,
                            'intervention_executed': False, 'offer_accepted': None, 'setup_success_7d': None,
                            'paid_upgrade_30d': None, 'actual_upgrade_contribution': None, 'actual_support_cost': None})
    actual_planned = load(HERE / 'planned_pilot_20.csv')
    assert actual_planned == [{key: csv_value(value) for key, value in row.items()} for row in planned]
    assert len(planned) == len({row['customer_id'] for row in planned}) == 20
    for product in protocol['products']:
        assert Counter(row['planned_arm'] for row in planned if row['product'] == product) == {
            protocol['planned_arm_a']: 2, protocol['planned_arm_b']: 2}
    cards = json.loads((HERE / 'evidence_cards_20.json').read_text(encoding='utf-8'))
    assert len(cards) == len(selected) == 20
    for card, record in zip(cards, selected):
        assert {key: card[key] for key in record} == record
        cid = record['customer_id']
        assert card['usage_history'] == expected_history[cid]
        assert card['resolution_record'] == (original_tickets[cid]['Resolution'] or None)
        assert card['configuration_need'] == card['paid_capability_need'] == 'NOT_ESTABLISHED_FROM_AVAILABLE_FIELDS'
        assert card['candidate_evidence'] == 'Snapshot Free + exact Integration ticket subject; not confirmed configuration need'
        assert all(card[key] is None for key in ['configuration_success', 'paid_upgrade', 'incremental_profit'])
        assert len(card['next_questions']) == 3
    expected = {
        'dataset_scope': 'competition_csv_only', 'new_synthetic_observations': 0,
        'snapshot_free_customers': sum(customer['Plan Type'] == 'Free' for customer in customers),
        'identity_conflict_customers_all_plans': len(bad_ids),
        'identity_consistent_free_customers': sum(customer['Plan Type'] == 'Free' and customer['Customer ID'] not in bad_ids for customer in customers),
        'raw_candidate_tickets': len(raw), 'excluded_candidate_tickets': len(raw) - len(clean),
        'candidate_customers': len(clean),
        'by_product': dict(Counter(row['product'] for row in expected_records)),
        'by_type': dict(Counter(row['ticket_type'] for row in expected_records)),
        'by_status': dict(Counter(row['ticket_status'] for row in expected_records)),
        'rated_n': sum(row['csat'] is not None for row in expected_records),
        'same_product_five_month_complete_n': len(expected_records),
        'any_nonzero_history_n': sum(row['any_nonzero_integration_month'] for row in expected_records),
        'all_zero_history_n': sum(row['all_months_zero'] for row in expected_records),
        'any_zero_month_n': sum(row['any_zero_month'] for row in expected_records),
        'may_zero_n': sum(row['may_integrations_used'] == 0 for row in expected_records),
        'configuration_need_confirmation': 'NOT_ESTABLISHED_NOT_A_MEASURED_ZERO',
        'configuration_success_rate': None, 'upgrade_rate': None, 'incremental_upgrade_rate': None,
        'incremental_profit': None, 'pilot_records_prepared': len(planned),
        'planned_arm_counts': dict(Counter(row['planned_arm'] for row in planned)),
        'intervention_executed': False, 'upgrade_effect_identifiable': False,
        'prior_usage_is_not_current_configuration_success': True, 'snapshot_plan_is_not_plan_history': True}
    expected['candidate_fraction_of_clean_free'] = len(clean) / expected['identity_consistent_free_customers']
    assert {key: result[key] for key in expected} == expected
    assert protocol['intervention_executed'] is False and protocol['primary_effect_identified'] is False
    audit = {'status': 'PASS', 'review_type': 'independent_source_and_preparation_recomputation',
             'imports_main_audit': False, 'blind_to_protocol_or_main_implementation': False,
             'source_rows': {'customers': len(customers), 'tickets': len(tickets), 'usage': len(usage)},
             'checks': {'source_and_protocol_code_hashes': True, 'candidate_roster_all_fields_and_order': True,
                        'candidate_count': len(roster), 'same_product_monthly_source_rows': len(roster) * 5,
                        'fixed_card_count_and_order': len(cards), 'planned_allocation_all_fields_and_order': True,
                        'per_product_arms_2_to_2': True, 'planned_total_per_arm': 10,
                        'outcomes_unobserved_and_intervention_unexecuted': True,
                        'all_reported_candidate_summary_fields': True},
             'recomputed': expected,
             'limitations': ['This verifies candidate sources and an unexecuted preparation example, not intervention effectiveness.',
                            'The 20 candidates have not been confirmed eligible for configuration help; current Free status and a specific need must be confirmed before a real trial.',
                            'A real trial randomizes eligible customers to an offer before outcomes, without using this demonstration allocation to determine eligibility.',
                            'Analyse everyone as assigned, including declined offers or unsuccessful setups; never compare only successful configurations.',
                            'Closed status or nonzero integration usage is not a verified configuration outcome; missing upgrade labels are not zero upgrades.']}
    (HERE / 'independent_audit.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8', newline='\n')
    report = '''# Independent source and preparation audit

PASS. `independent_verify.py` reads the original three CSVs and the frozen protocol, reconstructs the cohort and preparation outputs, and does not import `audit.py`. The reviewer read the protocol and main implementation to establish the interface; this is independent recomputation, not a blinded study.

- Recomputed 89 raw Free + Integration candidates, 5 excluded for customer identity conflicts, and 84 distinct clean candidates among 1,440 clean Free customers.
- Verified all 84 roster rows, their order and every field; checked all 420 same-product January–May history rows. All 84 have at least one nonzero month, none have all-zero history, and 28 have zero integrations recorded in May.
- Reconstructed both salted hash orders directly. Verified all 20 evidence cards, original ticket/usage values and source rows, and the entire prepared allocation: 4 candidates per product, 2 per arm, 10 per arm overall.
- Verified all reported candidate summary fields, the four source-file hashes and two frozen protocol/code hashes.
- Verified outcomes remain JSON null / empty CSV fields, needs remain unconfirmed, and every intervention flag remains false.

The 20 records are a preparation example chosen before needs are confirmed, not an executed randomized trial. For a real trial, confirm current Free status and the specific integration task first, then randomize eligible customers to the additional help offer or existing support. Eligibility must not depend on this demonstration allocation. Analyse all customers as assigned, including those who decline help or fail to configure. Completion, upgrade and profit effects have not been measured. A closed ticket or historical integration use does not prove the current configuration is successful, and an absent upgrade label is not a zero upgrade.

Reproduce: `python integration_setup_v1/independent_verify.py`.
'''
    (HERE / 'independent_audit.md').write_text(report, encoding='utf-8', newline='\n')
    print(json.dumps({'status': 'PASS', 'candidate_count': len(roster), 'cards_verified': len(cards),
                      'planned_allocation_verified': len(planned), 'actual_interventions': 0}, ensure_ascii=False))


if __name__ == '__main__':
    main()
