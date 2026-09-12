"""User-authorized, uncalibrated profit scenarios on a fixed competition roster."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
import csv
import hashlib
import json
import math

import numpy as np

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
DATA = REPO / 'data'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name, value):
    (ROOT/name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False),
                           encoding='utf-8', newline='\n')


def read_csv(name):
    with (DATA/name).open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def csv_out(name, rows):
    with (ROOT/name).open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


def original_cohort(v1):
    customers, tickets, usage = [read_csv(n) for n in ('customers.csv','customer_support_tickets.csv','product_usage.csv')]
    emails, by_usage, products = defaultdict(list), defaultdict(list), defaultdict(set)
    norm = lambda x: x.strip().casefold()
    for c in customers:
        emails[norm(c['Customer Email'])].append(c)
    conflicts = set()
    for t in tickets:
        match = emails[norm(t['Customer Email'])]
        if len(match) == 1 and any(norm(t[f]) != norm(match[0][f]) for f in ('Customer Name','Customer Age','Customer Gender')):
            conflicts.add(match[0]['Customer ID'])
    for u in usage:
        by_usage[u['Customer ID'],u['Product'],u['Month']].append(u)
        products[u['Customer ID']].add(u['Product'])
    cohort = []
    for c in customers:
        cid = c['Customer ID']
        if c['Plan Type'] != 'Free' or cid in conflicts or len(products[cid]) != 1:
            continue
        product = next(iter(products[cid]))
        if product not in v1['products']:
            continue
        try:
            values = []
            for month in v1['feature_months']:
                match = by_usage[cid,product,month]
                assert len(match) == 1
                value = float(match[0]['Collaborators'])
                assert math.isfinite(value) and value >= 0 and value.is_integer()
                values.append(value)
        except (AssertionError, ValueError, TypeError):
            continue
        cohort.append({'customer_id':cid, 'product':product, 'historical_mean':sum(values)/4})
    return cohort


def prepare_roster(protocol):
    v1 = json.loads((REPO/'profit_opportunity_v1/protocol.json').read_text(encoding='utf-8'))
    original = json.loads((REPO/protocol['selection_file']).read_text(encoding='utf-8'))['selected_without_may']
    cohort = original_cohort(v1)
    assert len(cohort) == 1440
    calculated, population_by_product = [], {}
    for product in v1['products']:
        group = [r for r in cohort if r['product'] == product]
        scores = np.array([r['historical_mean'] for r in group])
        for r in group:
            midrank = (np.sum(scores < r['historical_mean']) + .5*np.sum(scores == r['historical_mean'])) / len(scores)
            r['z'] = float(2*midrank-1)
        assert abs(sum(r['z'] for r in group)) < 1e-9
        hash_key = lambda r: hashlib.sha256((v1['hash_salt']+'|'+r['customer_id']).encode()).hexdigest()
        ranking = sorted(group, key=lambda r:(-r['historical_mean'], hash_key(r)))
        top = ranking[:2]
        ordinary = sorted(ranking[2:],key=hash_key)[:2]
        calculated.extend(dict(r,group=group_name) for group_name, rs in
                          [('priority',top),('comparison',ordinary)] for r in rs)
        population_by_product[product] = len(group)
    assert len(calculated) == len({r['customer_id'] for r in calculated}) == 20
    for a,b in zip(calculated,original):
        assert (a['customer_id'],a['product'],a['group'],a['historical_mean']) == (
            b['customer_id'],b['product'],b['group'],b['jan_apr_mean_collaborators'])
    csv_out('fixed_roster_20.csv',calculated)
    return calculated,population_by_product


def poisson_binomial(probabilities):
    pmf = np.array([1.0])
    for q in probabilities:
        pmf = np.convolve(pmf, [1-q,q])
    assert abs(float(pmf.sum())-1) < 1e-12
    return pmf


def distribution(values, weights):
    order = np.argsort(values)
    x, w = np.asarray(values)[order],np.asarray(weights)[order]
    cdf = np.cumsum(w)
    quantile = lambda q: float(x[min(int(np.searchsorted(cdf,q)),len(x)-1)])
    return {'profit_probability':float(w[x > 1e-9].sum()),
            'breakeven_probability':float(w[np.abs(x) <= 1e-9].sum()),
            'loss_probability':float(w[x < -1e-9].sum()),
            'central_95_model_interval':[quantile(.025),quantile(.975)]}


def monte_carlo_check(samples, expected, exact_probability):
    mean = float(samples.mean())
    se = float(samples.std(ddof=1)/math.sqrt(len(samples)))
    assert abs(mean-expected) <= max(5*se,1e-9)
    observed = float(np.mean(samples > 1e-9))
    p_se = math.sqrt(exact_probability*(1-exact_probability)/len(samples))
    assert abs(observed-exact_probability) <= max(5*p_se,1/len(samples))
    return {'mean':mean,'mean_mc_standard_error':se,'profit_probability':observed,
            'analytic_mean_check_passed':True,'exact_probability_check_passed':True}


def main():
    p = json.loads((ROOT/'protocol.json').read_text(encoding='utf-8'))
    inputs = ['data/customers.csv','data/customer_support_tickets.csv','data/product_usage.csv','data/README.md',
              p['selection_file'],'profit_opportunity_v1/protocol.json']
    hashes = {'input_sha256':{n:sha(REPO/n) for n in inputs},
              'protocol_code_sha256':{n:sha(ROOT/n) for n in ('protocol.json','protocol.md','experiment.py')}}
    lock = ROOT/'execution_lock.json'
    if lock.exists():
        saved = json.loads(lock.read_text(encoding='utf-8'))
        assert all(saved[k] == v for k,v in hashes.items())
    else:
        write(lock.name,dict(hashes,frozen_at=datetime.now(timezone.utc).isoformat()))
    roster,populations = prepare_roster(p)
    z = np.array([r['z'] for r in roster])
    masks = {g:np.array([r['group'] == g for r in roster]) for g in ('priority','comparison')}
    assert all(m.sum() == 10 for m in masks.values())
    G,c,F = (p[k] for k in ('net_contribution_per_incremental_conversion','contact_cost_per_customer',
                            'priority_extra_screening_cost_per_batch'))
    assert p['shared_fixed_campaign_cost'] == p['ordinary_extra_screening_cost_per_batch'] == 0
    rng = np.random.default_rng(p['seed'])
    uniform = rng.random((p['repetitions'],len(roster)))
    scenarios,probability_rows,grid,summary = [],[],[],[]
    for scenario in p['scenarios']:
        p1 = p['contact_conversion_intercept'] + scenario['slope']*z
        p0 = p1-scenario['constant_incremental_probability'] if 'constant_incremental_probability' in scenario else np.full(len(z),p['natural_conversion'])
        uplift = p1-p0
        assert np.all((p0 >= 0) & (p0 <= p1) & (p1 <= 1))
        increments = (uniform < p1).astype(int) - (uniform < p0).astype(int)
        group_results,pmfs,sample_profits = {},{},{}
        for group,mask in masks.items():
            q = uplift[mask]
            cost = 10*c+(F if group == 'priority' else 0)
            expected = G*float(q.sum())-cost
            pmf = poisson_binomial(q)
            values = np.arange(11)*G-cost
            pmfs[group] = pmf
            sample_profits[group] = increments[:,mask].sum(axis=1)*G-cost
            exact = distribution(values,pmf)
            group_results[group] = {'n':10,'mean_z':float(z[mask].mean()),
                'mean_contact_conversion':float(p1[mask].mean()),'mean_natural_conversion':float(p0[mask].mean()),
                'mean_incremental_conversion':float(q.mean()),'expected_incremental_conversions':float(q.sum()),
                'expected_incremental_profit':expected,'exact':exact,
                'monte_carlo':monte_carlo_check(sample_profits[group],expected,exact['profit_probability']),
                'incremental_count_pmf':pmf.tolist(),
                'contact_cost_breakeven_per_customer':float(G*q.mean()-(F/10 if group == 'priority' else 0)),
                'contribution_breakeven':float(cost/q.sum()) if q.sum() > 1e-12 else None}
        expected_difference = group_results['priority']['expected_incremental_profit']-group_results['comparison']['expected_incremental_profit']
        differences = (np.arange(11)[:,None]-np.arange(11)[None,:])*G-F
        joint_pmf = pmfs['priority'][:,None]*pmfs['comparison'][None,:]
        diff_exact = distribution(differences.flatten(),joint_pmf.flatten())
        diff_samples = sample_profits['priority']-sample_profits['comparison']
        advantage_before_screen = G*float(uplift[masks['priority']].sum()-uplift[masks['comparison']].sum())
        outcome = {'id':scenario['id'],'label':scenario['label'],'groups':group_results,
                   'expected_priority_minus_comparison':expected_difference,'difference_exact':diff_exact,
                   'difference_monte_carlo':monte_carlo_check(diff_samples,expected_difference,diff_exact['profit_probability']),
                   'screening_cost_breakeven_vs_ordinary':advantage_before_screen}
        scenarios.append(outcome)
        summary.append({'scenario':scenario['id'],'priority_contact_conversion':group_results['priority']['mean_contact_conversion'],
                        'ordinary_contact_conversion':group_results['comparison']['mean_contact_conversion'],
                        'priority_expected_profit':group_results['priority']['expected_incremental_profit'],
                        'ordinary_expected_profit':group_results['comparison']['expected_incremental_profit'],
                        'priority_advantage':expected_difference,
                        'priority_profit_probability':group_results['priority']['exact']['profit_probability'],
                        'ordinary_profit_probability':group_results['comparison']['exact']['profit_probability'],
                        'priority_beats_ordinary_probability':diff_exact['profit_probability'],
                        'max_extra_screening_cost_vs_ordinary':advantage_before_screen})
        for i,r in enumerate(roster):
            probability_rows.append({'scenario':scenario['id'],**r,'assumed_natural_probability':float(p0[i]),
                                     'assumed_contact_probability':float(p1[i]),'assumed_incremental_probability':float(uplift[i])})
        for contribution in p['sensitivity']['net_contributions']:
            for contact_cost in p['sensitivity']['contact_costs']:
                for screening_cost in p['sensitivity']['extra_screening_costs']:
                    profits = {g:contribution*float(uplift[m].sum())-10*contact_cost-(screening_cost if g == 'priority' else 0)
                               for g,m in masks.items()}
                    grid.append({'scenario':scenario['id'],'contribution':contribution,'contact_cost':contact_cost,
                                 'screening_cost':screening_cost,'priority_profit':profits['priority'],
                                 'ordinary_profit':profits['comparison'],'priority_advantage':profits['priority']-profits['comparison']})
    s = {r['id']:r for r in scenarios}
    assert abs(s['unrelated']['expected_priority_minus_comparison']+F) < 1e-9
    assert abs(s['natural_conversion_trap']['expected_priority_minus_comparison']+F) < 1e-9
    assert all(r['priority_profit'] <= 0 for r in [
        {'priority_profit':0*10*q-c*10-F} for q in (0,.15,.30)])
    z_sum_gap = float(z[masks['priority']].sum()-z[masks['comparison']].sum())
    results = {'executed_at':datetime.now(timezone.utc).isoformat(),
               'evidence_type':'USER_AUTHORIZED_CONDITIONAL_SIMULATION_NOT_EMPIRICAL_PROFIT',
               'observed_customer_source_records':20,'new_real_customer_outcomes':0,'repetitions':p['repetitions'],
               'input_sha256':hashes['input_sha256'],'original_cohort_by_product':populations,
               'original_roster_and_rule_verified':True,'parameters':p,'scenarios':scenarios,
               'positive_slope_breakeven_vs_ordinary':float(F/(G*z_sum_gap)),
               'all_analytic_monte_carlo_checks_passed':True,'scenario_grid_rows':len(grid),
               'empirical_profit_effect':'UNVERIFIED',
               'limitations':['Conversion probabilities and money values are uncalibrated assumptions.',
                              'Profit distributions assume monotone potential outcomes and independent customers.',
                              'Repeated draws do not increase the number of observed customers.',
                              'Ordinary roster is the prior fixed product-matched hash sample excluding top-ranked customers.']}
    csv_out('scenario_summary.csv',summary)
    csv_out('assumed_case_probabilities.csv',probability_rows)
    csv_out('cost_sensitivity.csv',grid)
    write('results.json',results)
    print(json.dumps({'scenarios':summary,'positive_slope_breakeven':results['positive_slope_breakeven_vs_ordinary'],
                      'checks':'PASS'},ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
