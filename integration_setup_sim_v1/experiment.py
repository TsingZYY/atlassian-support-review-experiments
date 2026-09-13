"""Conditional simulation; never writes observed outcomes to the original pilot."""
from collections import defaultdict, Counter
from pathlib import Path
from datetime import datetime, timezone
import csv
import hashlib
import itertools
import json
import math
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name,obj):
    (HERE/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8',newline='\n')


def table(name,rows):
    with (HERE/name).open('w',encoding='utf-8',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]),lineterminator='\n')
        writer.writeheader(); writer.writerows(rows)


def expected(p,s,n):
    a,q0,qh=p['acceptance_probability'],p['baseline_setup_probability'],s['assisted_setup_probability']
    qs=q0+a*(qh-q0)
    pb=q0*s['upgrade_given_setup']+(1-q0)*s['upgrade_given_no_setup']
    pa=qs*s['upgrade_given_setup']+(1-qs)*s['upgrade_given_no_setup']
    cost=p['offer_cost_per_assigned_help_customer']+a*p['assistance_cost_per_acceptor']
    total=n*cost+p['incremental_fixed_cost_per_help_batch']
    return {'control_setup_probability':q0,'help_setup_probability':qs,
            'control_upgrade_probability':pb,'help_upgrade_probability':pa,
            'setup_rate_difference':qs-q0,'upgrade_rate_difference':pa-pb,
            'expected_extra_cost':total,
            'expected_incremental_profit':n*(pa-pb)*p['upgrade_net_contribution']-total,
            'break_even_upgrade_rate_difference':total/(n*p['upgrade_net_contribution'])}


def customer_distribution(p,s,help_arm):
    result=defaultdict(float)
    acceptance=p['acceptance_probability'] if help_arm else 0.0
    for accepted in (0,1):
        ap=acceptance if accepted else 1-acceptance
        q=s['assisted_setup_probability'] if accepted else p['baseline_setup_probability']
        for setup in (0,1):
            sp=q if setup else 1-q
            pu=s['upgrade_given_setup'] if setup else s['upgrade_given_no_setup']
            for upgrade in (0,1):
                up=pu if upgrade else 1-pu
                cost=(p['offer_cost_per_assigned_help_customer']+accepted*p['assistance_cost_per_acceptor']) if help_arm else 0
                contribution=upgrade*p['upgrade_net_contribution']-cost
                if ap*sp*up:
                    result[int(contribution)]+=ap*sp*up
    assert abs(sum(result.values())-1)<1e-12
    return dict(result)


def convolve(a,b):
    out=defaultdict(float)
    for x,px in a.items():
        for y,py in b.items(): out[x+y]+=px*py
    return dict(out)


def exact_distribution(p,s,n):
    help_pmf,control_pmf={0:1.0},{0:1.0}
    h,b=customer_distribution(p,s,True),customer_distribution(p,s,False)
    for _ in range(n):
        help_pmf=convolve(help_pmf,h); control_pmf=convolve(control_pmf,b)
    delta=defaultdict(float)
    for x,px in help_pmf.items():
        for y,py in control_pmf.items():
            delta[x-y-p['incremental_fixed_cost_per_help_batch']]+=px*py
    mass=sum(delta.values()); assert abs(mass-1)<1e-10
    delta={x:px/mass for x,px in sorted(delta.items())}
    mean=sum(x*px for x,px in delta.items())
    variance=sum((x-mean)**2*px for x,px in delta.items())
    def quantile(q):
        cumulative=0.0
        for x,px in delta.items():
            cumulative+=px
            if cumulative>=q: return x
        return max(delta)
    return delta,{'expected_incremental_profit':mean,'variance':variance,
                  'probability_strictly_positive_profit':sum(px for x,px in delta.items() if x>0),
                  'central_95_batch_profit_range':[quantile(.025),quantile(.975)]}


def main():
    p=json.loads((HERE/'protocol.json').read_text(encoding='utf-8'))
    hashes={'source_sha256':{name:sha(ROOT/name) for name in (p['roster'],p['evidence_cards'])},
            'protocol_code_sha256':{name:sha(HERE/name) for name in ('protocol.json','protocol.md','experiment.py')}}
    if (HERE/'execution_lock.json').exists():
        lock=json.loads((HERE/'execution_lock.json').read_text(encoding='utf-8'))
        assert all(lock[k]==v for k,v in hashes.items())
    else: write('execution_lock.json',{**hashes,'frozen_at':datetime.now(timezone.utc).isoformat()})
    with (ROOT/p['roster']).open(encoding='utf-8-sig',newline='') as f: roster=list(csv.DictReader(f))
    assert len(roster)==len({r['customer_id'] for r in roster})==20
    treatment=np.array([r['planned_arm']=='OFFER_INTEGRATION_SETUP_HELP' for r in roster])
    n=int(treatment.sum()); assert n==len(roster)-n==10
    assert all(r['intervention_executed']=='False' and r['paid_upgrade_30d']=='' for r in roster)
    assert Counter(r['product'] for r in roster)=={'Loom':4,'Trello':4,'Bitbucket':4,'Confluence':4,'Jira':4}
    rng=np.random.default_rng(p['seed']); shape=(p['repetitions'],len(roster))
    u_accept=rng.random(shape); u_setup=rng.random(shape); u_upgrade=rng.random(shape)
    accepted=(u_accept<p['acceptance_probability']) & treatment[None,:]
    costs=treatment[None,:]*p['offer_cost_per_assigned_help_customer']+accepted*p['assistance_cost_per_acceptor']
    records,summaries,results,pmfs,grid=[],[],[],[],[]
    for s in p['scenarios']:
        q=np.where(accepted,s['assisted_setup_probability'],p['baseline_setup_probability'])
        setup=u_setup<q
        upgrade=u_upgrade<np.where(setup,s['upgrade_given_setup'],s['upgrade_given_no_setup'])
        contribution=upgrade*p['upgrade_net_contribution']-costs
        profits=contribution[:,treatment].sum(axis=1)-contribution[:,~treatment].sum(axis=1)-p['incremental_fixed_cost_per_help_batch']
        theory=expected(p,s,n)
        pmf,exact=exact_distribution(p,s,n)
        assert abs(theory['expected_incremental_profit']-exact['expected_incremental_profit'])<1e-9
        mean_se=math.sqrt(exact['variance']/p['repetitions'])
        probability=exact['probability_strictly_positive_profit']
        probability_se=math.sqrt(probability*(1-probability)/p['repetitions'])
        mc_mean=float(profits.mean()); mc_probability=float(np.mean(profits>0))
        assert abs(mc_mean-theory['expected_incremental_profit'])<=p['numerical_tolerance_standard_errors']*mean_se
        assert abs(mc_probability-probability)<=p['numerical_tolerance_standard_errors']*probability_se
        mc={'repetitions':p['repetitions'],'mean_incremental_profit':mc_mean,'mean_profit_simulation_se':mean_se,
            'probability_strictly_positive_profit':mc_probability,'probability_simulation_se':probability_se,
            'mean_help_setup_rate':float(setup[:,treatment].mean()),'mean_control_setup_rate':float(setup[:,~treatment].mean()),
            'mean_help_upgrade_rate':float(upgrade[:,treatment].mean()),'mean_control_upgrade_rate':float(upgrade[:,~treatment].mean())}
        first={'repetition':0,'help_accepted_n':int(accepted[0].sum()),
               'help_setup_n':int(setup[0,treatment].sum()),'control_setup_n':int(setup[0,~treatment].sum()),
               'help_upgrade_n':int(upgrade[0,treatment].sum()),'control_upgrade_n':int(upgrade[0,~treatment].sum()),
               'incremental_profit':int(profits[0]),'outcome_kind':'SIMULATED_NOT_OBSERVED'}
        results.append({'scenario':s['id'],'label':s['label'],'assumptions':s,'analytic':theory,'exact':exact,'monte_carlo':mc,'fixed_first_replay':first})
        summaries.append({'scenario':s['id'],'label':s['label'],**theory,
                          'exact_probability_profit_positive':probability,
                          'batch_profit_p025':exact['central_95_batch_profit_range'][0],
                          'batch_profit_p975':exact['central_95_batch_profit_range'][1],
                          'monte_carlo_mean_profit':mc_mean,'first_replay_profit':first['incremental_profit'],
                          'all_business_outcomes_are_simulated':True})
        for j,r in enumerate(roster):
            records.append({'scenario':s['id'],'repetition':0,'customer_id':r['customer_id'],'ticket_id':r['ticket_id'],
                            'product':r['product'],'assigned_arm':r['planned_arm'],
                            'outcome_kind':'SIMULATED_NOT_OBSERVED','eligibility_assumed_not_verified':True,
                            'sim_help_offered':bool(treatment[j]),'sim_help_accepted':bool(accepted[0,j]) if treatment[j] else None,
                            'sim_setup_success_7d':bool(setup[0,j]),'sim_paid_upgrade_30d':bool(upgrade[0,j]),
                            'sim_variable_help_cost':int(costs[0,j]),'sim_upgrade_contribution':int(upgrade[0,j]*p['upgrade_net_contribution']),
                            'sim_net_contribution_before_batch_fixed_cost':int(contribution[0,j]),'real_intervention_executed':False})
        pmfs.extend({'scenario':s['id'],'batch_incremental_profit':x,'probability':px} for x,px in pmf.items())
        keys=list(p['cost_grid'])
        for values in itertools.product(*(p['cost_grid'][k] for k in keys)):
            settings=dict(zip(keys,values)); outcome=expected({**p,**settings},s,n)
            grid.append({'scenario':s['id'],**settings,**outcome,'all_amounts_are_hypothetical':True})
    table('fixed_first_replay_20.csv',records)
    table('scenario_summary.csv',summaries)
    table('exact_profit_distributions.csv',pmfs)
    table('cost_sensitivity.csv',grid)
    final={'executed_at':datetime.now(timezone.utc).isoformat(),**hashes,
           'execution_kind':'EXPLICITLY_AUTHORIZED_CONDITIONAL_SIMULATION',
           'official_roster_records':20,'assigned_help_n':n,'assigned_control_n':n,
           'simulated_first_replay_rows':len(records),'repetitions_per_scenario':p['repetitions'],
           'unique_empirical_customers_added':0,'real_interventions_executed':0,
           'actual_setup_success_rate':None,'actual_upgrade_rate_difference':None,'actual_incremental_profit':None,
           'original_pilot_outcomes_modified':False,'cost_grid_rows':len(grid),'scenarios':results,
           'checks':'PASS','simulation_is_not_real_world_effect_validation':True}
    write('results.json',final)
    print(json.dumps({'checks':'PASS','scenarios':summaries,'single_replay':[r['fixed_first_replay'] for r in results]},ensure_ascii=False,indent=2))


if __name__=='__main__': main()
