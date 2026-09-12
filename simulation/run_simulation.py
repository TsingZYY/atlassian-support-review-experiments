"""A conditional, paired queue simulation. No real customer outcomes are generated."""
from pathlib import Path
import csv
import hashlib
import json
import math
import sys
from datetime import datetime, timezone
import numpy as np

ROOT = Path(__file__).resolve().parent
CASE = ROOT.parent
sys.path.insert(0, str(CASE / 'minimal_model'))
from model import run_dataset, MODEL_VERSION

SEED, REPEATS, BUDGET, SERVICE_COST = 20260918, 10000, 20, 2
SCENARIOS = [('positive',0.8,0.2),('unrelated',0.5,0.5),('reverse',0.2,0.8)]
OVERHEADS = [0,2,4,6,8]


def csv_rows(path):
    with path.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def expected_counts(priority, flags, capacity, assisted):
    """Closed form over random ordering inside ties, independent of sorting code."""
    remaining, hit, other = capacity, 0.0, 0.0
    for level in sorted(set(priority.tolist())):
        g = priority == level
        n, h = int(g.sum()), int(flags[g].sum())
        take = min(remaining, n)
        selected_hit = min(h,take) if assisted else take * h / n
        hit += selected_hit
        other += take - selected_hit
        remaining -= take
    return hit, other


def main():
    predictions = {str(p['ticket_id']):p for p in run_dataset(CASE/'data')}
    sample_key = csv_rows(CASE/'validation_v1/blind_review_key.csv')
    cohort = [predictions[r['Ticket ID']] for r in sample_key]
    assert len(cohort) == 20 and len({p['customer_id'] for p in cohort}) == 20
    assert all(p['decision'] != 'DATA_CHECK' for p in cohort)
    flags = np.array([p['decision']=='REVIEW_CANDIDATE' for p in cohort],dtype=bool)
    assert flags.sum() == 10
    priority_map = {'Critical':0,'High':1,'Medium':2,'Low':3}
    priority = np.array([priority_map[p['ticket_priority']] for p in cohort])
    composition = [{'priority':name,'rule_hit':int(flags[priority==v].sum()),
                    'rule_not_hit':int((~flags[priority==v]).sum())}
                   for name,v in priority_map.items() if (priority==v).any()]
    rng = np.random.default_rng(SEED)
    # World outcomes and shared tie order are generated independently.
    outcome_uniforms = rng.random((REPEATS, len(cohort)))
    tie_keys = rng.random((REPEATS,len(cohort)))
    prio = np.broadcast_to(priority,tie_keys.shape)
    hit_order = np.broadcast_to((~flags).astype(int),tie_keys.shape)
    baseline_order = np.lexsort((tie_keys,prio),axis=1)
    assisted_order = np.lexsort((tie_keys,hit_order,prio),axis=1)
    assert (np.take_along_axis(prio,baseline_order,axis=1) == np.sort(prio,axis=1)).all()
    assert (np.take_along_axis(prio,assisted_order,axis=1) == np.sort(prio,axis=1)).all()
    n = len(cohort)
    k_a = min(n,BUDGET//SERVICE_COST)
    base_select = baseline_order[:,:k_a]
    a_hit,a_other = expected_counts(priority,flags,k_a,False)
    rows = []
    all_capacity_checks = []
    for scenario,p_hit,p_other in SCENARIOS:
        probabilities = np.where(flags,p_hit,p_other)
        potential_result = outcome_uniforms < probabilities
        a_count = np.take_along_axis(potential_result,base_select,axis=1).sum(axis=1)
        a_exact = a_hit*p_hit + a_other*p_other
        full_a = np.take_along_axis(potential_result,baseline_order,axis=1).sum(axis=1)
        full_b = np.take_along_axis(potential_result,assisted_order,axis=1).sum(axis=1)
        assert np.array_equal(full_a,full_b)
        all_capacity_checks.append({'scenario':scenario,'paired_runs_identical':int((full_a==full_b).sum())})
        for overhead in OVERHEADS:
            k_b = min(n,max(0,(BUDGET-overhead)//SERVICE_COST))
            b_select = assisted_order[:,:k_b]
            b_count = np.take_along_axis(potential_result,b_select,axis=1).sum(axis=1)
            diff = b_count-a_count
            b_hit,b_other = expected_counts(priority,flags,k_b,True)
            b_exact = b_hit*p_hit+b_other*p_other
            se = float(diff.std(ddof=1)/math.sqrt(REPEATS))
            mean = float(diff.mean())
            assert abs(mean-(b_exact-a_exact)) <= max(6*se,0.02)
            rows.append({
                'scenario':scenario,'p_solvable_hit_assumed':p_hit,'p_solvable_other_assumed':p_other,
                'information_overhead_units':overhead,'baseline_cases_processed':k_a,'assisted_cases_processed':k_b,
                'baseline_expected_hit_processed':a_hit,'assisted_expected_hit_processed':b_hit,
                'baseline_analytic_resolved_count':a_exact,'assisted_analytic_resolved_count':b_exact,
                'analytic_gain_count':b_exact-a_exact,
                'baseline_analytic_rate_pct':a_exact/n*100,'assisted_analytic_rate_pct':b_exact/n*100,
                'analytic_gain_pp':(b_exact-a_exact)/n*100,
                'baseline_mc_resolved_count':float(a_count.mean()),'assisted_mc_resolved_count':float(b_count.mean()),
                'mc_gain_count':mean,'mc_gain_standard_error_count':se,
                'single_run_gain_count_p05':float(np.quantile(diff,.05)),
                'single_run_gain_count_p95':float(np.quantile(diff,.95)),
                'mc_probability_assisted_more':float((diff>0).mean()),
            })
    assert abs(next(r for r in rows if r['scenario']=='unrelated' and r['information_overhead_units']==0)['analytic_gain_count'])<1e-12
    result = {
        'study':'Conditional synthetic queue simulation v1','executed_at':datetime.now(timezone.utc).isoformat(),
        'model_version':MODEL_VERSION,'seed':SEED,'repeats':REPEATS,'cases_per_run':n,
        'budget_units':BUDGET,'service_cost_units':SERVICE_COST,'composition':composition,
        'source_hashes':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [
            ROOT/'protocol.md', CASE/'minimal_model/model.py', CASE/'validation_v1/blind_review_key.csv']},
        'results':rows,'all_cases_processed_placebo':all_capacity_checks,
        'interpretation':'Only conditional simulation results. Scenario probabilities and costs are uncalibrated assumptions.',
        'real_customer_resolution_effect':None,
        'limitations':['20 source cases are synthetic and enriched for the rule; not a population sample.',
                       'Simulated solvability is not observed or learned from real outcomes.',
                       'Random within-priority baseline is a declared comparator, not verified current support practice.',
                       'Repeated runs quantify simulation variability, not real-world external validity.'],
    }
    (ROOT/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    with (ROOT/'scenario_results.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    report = ['# 条件性模拟结果',
        '\n已执行模拟，但没有估计真实客服解决率。每轮固定20条合成案例，重复10000次用于降低计算误差。',
        '\n场景概率和时间成本全部为未校准假设；正向场景的收益不能反向证明这些假设成立。',
        '\n## 固定输入与比较',
        f'\n优先级构成：{composition}。两策略均先处理Critical。A同级随机；B同级命中优先。',
        '\n预算20单位，每例2单位。主表先取B额外信息开销为0；分母为全部20案例，指标是通过本次模拟处理解决的比例。',
        '\n| 假设情景 | 命中/未命中可解决概率 | A条件期望 | B条件期望 | 差值 |',
        '|---|---|---:|---:|---:|']
    labels={'positive':'正向关联','unrelated':'无关联','reverse':'反向关联'}
    for r in rows:
        if r['information_overhead_units']==0:
            report.append(f"| {labels[r['scenario']]} | {r['p_solvable_hit_assumed']:.0%}/{r['p_solvable_other_assumed']:.0%} | {r['baseline_analytic_rate_pct']:.1f}% | {r['assisted_analytic_rate_pct']:.1f}% | {r['analytic_gain_pp']:+.1f}个百分点 |")
    report += ['\n主表给出可由处理构成直接核算的解析期望；每个情景的模拟均值均通过与解析期望的核对。',
        '\n## 信息开销敏感性',
        '\n| 开销单位 | B可处理数量 | 正向情景 B-A | 无关联情景 B-A | 反向情景 B-A |',
        '|---:|---:|---:|---:|---:|']
    for overhead in OVERHEADS:
        rr=[next(r for r in rows if r['scenario']==s and r['information_overhead_units']==overhead) for s,_,_ in SCENARIOS]
        report.append(f"| {overhead} | {rr[0]['assisted_cases_processed']} | " + ' | '.join(f"{r['analytic_gain_pp']:+.1f}个百分点" for r in rr) + ' |')
    report += ['\n## 核对与解释',
        '\n- 处理容量足够覆盖全部20案例且没有信息开销时，两策略每次得到完全相同的解决结果；排序没有凭空增加修复能力。',
        '- 无关联、无开销时，解析期望增益恰为零。',
        '- Critical共有12例，预算只能处理其中10例；两策略只在这个同级集合中竞争，High没有进入本轮处理名额。',
        '- 正向场景中，A平均处理5个命中、5个未命中；B处理6个命中、4个未命中，因此期望仅增加0.6例，而不是把所有名单客户都修好。',
        '- 在正向场景，信息开销达到6单位时增益归零；达到8单位时反转。单位为模拟设定，不能换算成已测得的分钟节省。',
        '- 模拟可检验“规则相关性×有限容量×信息成本”这一作用机制。是否有正向相关性，当前数据仍未证明。',
        '\n完整每轮差值分布范围、蒙特卡洛标准误、参数与哈希见 results.json；结果矩阵见 scenario_results.csv。',
        '\n## 可用于比赛的结论',
        '\n在明确有利关联、容量受限且信息开销低的模拟环境下，同优先级内按名单排序可产生小幅收益；无关联时没有期望收益，反向关联或过高开销会造成损失。模型的现实有效性仍取决于这些条件是否成立。不能表述为已证实真实解决率提高或高有效性。']
    (ROOT/'README.md').write_text('\n'.join(report)+'\n',encoding='utf-8')
    print(json.dumps({'composition':composition,'zero_overhead_results':[r for r in rows if r['information_overhead_units']==0],
                      'checks':'Analytic means, priority preservation and all-case placebo passed.'},ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
