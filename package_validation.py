from pathlib import Path
import contextlib
import io
import json
import os
import re
import html
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'validation_v1'
source=(ROOT/'run_low_cost_validation.py').read_text(encoding='utf-8')
source=source.replace('ROOT = Path(__file__).resolve().parent',"ROOT = Path.cwd()\nif ROOT.name == 'validation_v1': ROOT = ROOT.parent\nif not (ROOT/'data').exists(): ROOT = ROOT/'atlassian_case'")
parts=re.split(r'^# %% (.+)$',source,flags=re.M)
ns={'__name__':'__main__'}
cells=[]
preview=[]
previous=Path.cwd()
os.chdir(ROOT)
for i in range(1,len(parts),2):
    title,code=parts[i],parts[i+1]
    log=io.StringIO()
    with contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):
        exec(compile(code,'<validation notebook cell>','exec'),ns)
    cell_id=f'section-{i}'
    cells.append({'cell_type':'markdown','id':cell_id,'metadata':{},'source':[f'### {title}\n']})
    cells.append({'cell_type':'code','id':cell_id+'-code','metadata':{},'execution_count':(i+1)//2,'source':code.strip().splitlines(keepends=True),'outputs':[] if not log.getvalue() else [{'output_type':'stream','name':'stdout','text':log.getvalue().splitlines(keepends=True)}]})
    preview.append(f'<h3>{html.escape(title)}</h3><details><summary>Code</summary><pre>{html.escape(code)}</pre></details><pre>{html.escape(log.getvalue())}</pre>')
os.chdir(previous)
R=ns['R']; primary=R['primary']; snap=R['snapshot']
ind=json.loads((ROOT/'validation_independent.json').read_text(encoding='utf-8'))
assert primary['alerts']==ind['primary']['alert_n']
assert primary['precision']==ind['primary']['event_rate_alert']
assert primary['nonalert_outcome_rate']==ind['primary']['event_rate_comparison']

# A prepared human review is a separate, explicitly unrun next check.
snapshot=ns['snapshot'].copy()
rng=np.random.default_rng(20260913)
chosen=snapshot[snapshot.review_candidate].sample(n=min(10,int(snapshot.review_candidate.sum())),random_state=20260913)
controls=snapshot[snapshot.support_eligible & ~snapshot.review_candidate].copy()
paired=[]
for _,row in chosen.iterrows():
    mask=(controls.Product==row.Product)&(controls['Plan Type']==row['Plan Type'])&(controls['Ticket Priority']==row['Ticket Priority'])&(controls['Ticket Status']==row['Ticket Status'])
    pool=controls[mask]
    assert len(pool)>0, 'No exact product/plan/priority/status control; do not relax silently.'
    ctrl=pool.iloc[int(rng.integers(len(pool)))].copy()
    controls=controls.drop(ctrl.name)
    pair_id=len(paired)//2+1
    for x,group in [(row,'candidate'),(ctrl,'priority_only_control')]:
        item=x.to_dict();item['hidden_group']=group;item['pair_id']=pair_id;paired.append(item)
review=pd.DataFrame(paired).sample(frac=1,random_state=20260914).reset_index(drop=True)
review['Case ID']=[f'REVIEW-{i+1:02}' for i in range(len(review))]
review[['Case ID','hidden_group','pair_id','Customer ID','Ticket ID']].to_csv(OUT/'blind_review_key.csv',index=False)
review_cols=['Case ID','Product','Plan Type','Ticket Status','Ticket Priority','Ticket Type','Ticket Subject']+[m+'_active_pct' for m in ns['MONTHS']]
review=review[review_cols].copy()
for col in ['Need extra human review? yes/no/insufficient','Proposed useful action','Evidence supporting action','Review time minutes','Reviewer']:
    review[col]=''
review.round(2).to_csv(OUT/'blind_review_20.csv',index=False)

summary=f'''# 低成本验证结果

结论：可以生成客户支持人工复核队列；当前未通过“动态恶化预警”的预设证据门槛。暂不把它包装成已经验证的流失预测或挽回收入方案。

## 已执行

使用三份完整合成 CSV；排除身份字段冲突139人、活跃天数越界59人，留下8,122人。规则在运行前保存在 ../validation_protocol.md。1—3月活跃天数/日历天数均值为基线，4月相对下降至少30%且绝对下降至少10个百分点时告警；5月按同一定义评估。6月工单状态未用于预测4—5月。

| 检查 | 结果 |
|---|---:|
| 4月告警 | 582人 |
| 告警组5月仍低使用 | 136/582 = 23.37% |
| 未告警组5月低使用 | 566/7,540 = 7.51% |
| 全体5月低使用 | 702/8,122 = 8.64% |
| 相对同人数随机筛选的命中倍数 | 2.70 |
| 打乱个人月份顺序后的平均倍数 | 2.69 |
| 月序负对照单侧p值 | 0.466 |
| 当前队列 | 43人 |

真实月序的2.70倍处于月份重排结果的95%区间2.31—3.07倍内。月序对照没有通过预设p<0.05门槛。它保留个人使用水平、波动与共同基线造成的关联，提醒我们不能把普通富集直接解释成时间恶化信号。月份可交换性只是近似假设，尤其日历天数标准化会带来2月效应。

独立补充核查仍发现：产品×基线十分位内，告警与5月低使用相关（调整差13.76个百分点，95%区间10.24—17.30，置换p=0.0005）。这说明4月观测有相关信息，不能据此宣布“毫无预测信息”；但它也没有验证顺序特有信号或业务干预收益。两种对照回答不同问题。

## 稳健性与操作性

保留全部原始记录得到2.699倍；显式截断越界活跃率得到2.688倍；严格排除得到2.704倍。结论不由这些异常行主导。

20%、30%、40%相对阈值均已完整报告；各自改变了告警和结果定义，不可通过挑最高倍数选择赢家。没有调参补救失败的主门槛。

在2,673名未关闭且High/Critical工单客户中，43人同时满足4、5月持续低使用规则。按产品×套餐重排持续低使用标记，预期约45人，95%范围34—55，观察43人未显示额外集中（p=0.671）。名单证明流程能运行，不能证明真实需求或收益。

## 产物

- review_candidates.csv：43条去除姓名和邮箱的候选，保留合成数据ID以追溯；不是完全匿名数据。
- review_examples_10.csv：确定性排序的10条机械核查样例，不代表随机人审。
- low_cost_validation.ipynb：逐单元运行、保存输出的完整代码，依赖numpy/pandas。
- validation_results.json：完整指标、固定敏感性、源文件哈希、规则哈希。
- blind_review_20.csv：10名随机候选和10名产品/套餐/优先级/状态完全匹配的对照，混排并隐藏组别，所有评价列留空。
- blind_review_key.csv：分析用分组答案，不给首轮评审者。

## 尚未执行：小样本人工可用性检查（CANDIDATE-UNRUN）

建议请一位有客户支持经验的人，盲审20条记录，每条预算不超过2分钟，先不查看分组答案。标注是否值得额外复核、可采取的具体行动、证据是否足够及耗时。由于是合成数据，且缺少客户原话，允许并鼓励标注“信息不足”。这是工作流可用性检查，不能验证真实客户需求。

预算是40分钟人工；未联系人、未获得人审结果。只有评审能提出有依据的动作且候选优于匹配对照，才考虑继续获取真实脱敏样例与后续结果。20条样例不能证明留存提升或经济收益。

核心统计脚本单次运行约{R['resource_use']['wall_seconds']:.1f}秒；未调用外部付费API，未发送客户消息。Codex本身的使用不计入这个API调用数。

数据来源：https://drive.google.com/drive/folders/1NirfOKfM54cYeYXS3gn3azWznX1jaFiP
'''
(OUT/'validation_summary.md').write_text(summary,encoding='utf-8')
intro='''# Low-cost customer-support validation\n\n## Findings\nThe predefined dynamic-signal gate did not pass. Observed lift is 2.70 versus 2.69 under within-person month-order randomization (p=0.466). A 43-record support review queue is operationally constructible, but no intervention effect has been measured.\n\n## Context and methods\nThe dataset is synthetic. This is exploratory forward-month retrospective analysis, not a pristine holdout. Read ../validation_protocol.md for frozen thresholds, exclusions and all pass conditions. Activity uses calendar-normalized active days. All historical prediction features come from January-April; June support statuses only define the current snapshot.\n\n## Reproduction\nRun cells in order from this directory or its parent. Requires Python, numpy, pandas; no paid APIs. Original CSVs remain under ../data. Notebook cells have been executed in sequence through the Python interpreter; no Jupyter kernel package is bundled here.\n\n'''
cells.insert(0,{'cell_type':'markdown','id':'intro','metadata':{},'source':intro.splitlines(keepends=True)})
table=pd.DataFrame(R['cohort_history']).pivot(index='month',columns='cohort',values='mean_activity_pct').round(2)
table_cell={'cell_type':'code','id':'history-table','metadata':{},'execution_count':len(parts)//2+1,'source':["print(pd.DataFrame(R['cohort_history']).pivot(index='month',columns='cohort',values='mean_activity_pct').round(2).to_string())"],'outputs':[{'output_type':'stream','name':'stdout','text':[table.to_string()+'\n']}]}
cells.append({'cell_type':'markdown','id':'history-title','metadata':{},'source':['## Monthly activity history (%)\n','April defines the groups; the April separation is mechanical. May compares the later observation.\n']})
cells.append(table_cell)
cells.append({'cell_type':'markdown','id':'takeaways','metadata':{},'source':['## Takeaways\n','The alert can enrich the explicitly defined low-activity proxy. It has not shown a special chronological deterioration effect beyond the permutation control. Human workflow validation is pending. The grouped history table is included for portability; interactive figures accompany the chat answer.\n']})
nb={'nbformat':4,'nbformat_minor':5,'metadata':{'kernelspec':{'display_name':'Python 3','language':'python','name':'python3'},'language_info':{'name':'python'}},'cells':cells}
assert all(c.get('cell_type') in ['code','markdown'] for c in cells)
assert len({c['id'] for c in cells})==len(cells)
assert all(o['output_type']!='error' for c in cells for o in c.get('outputs',[]))
(OUT/'low_cost_validation.ipynb').write_text(json.dumps(nb,ensure_ascii=False,indent=2),encoding='utf-8')
preview_html='<!doctype html><meta charset="utf-8"><title>Validation notebook</title><style>body{max-width:960px;margin:32px auto;font:16px system-ui;line-height:1.5;padding:16px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px}table{border-collapse:collapse}td,th{padding:6px 10px;border-bottom:1px solid #ddd}</style><h1>Low-cost validation</h1><p>Dynamic deterioration signal not established: observed lift 2.70, month-order null mean 2.69, p=0.466. Human validation pending.</p>'+''.join(preview)+table.to_html()
(OUT/'notebook_preview.html').write_text(preview_html,encoding='utf-8')

# Inline source-backed figures use the shared renderer.
folder=R['source']
base_source={'label':'Atlassian竞赛合成数据：离线小成本验证','files':[{'label':p} for p in ['customer_support_tickets.csv','customers.csv','product_usage.csv']], 'links':[{'label':'原始数据文件夹','url':folder}], 'caveats':['合成数据；本轮为回顾性探索，5月不是封存确认集。','低使用指标不是流失或真实客户需求。','排除身份冲突与越界活跃天数涉及的198名客户。','没有执行客户干预或人工评审。']}
comparison=[{'method':'真实月份顺序','lift':primary['lift_vs_population']},{'method':'打乱月份顺序（均值）','lift':R['month_permutation']['null_lift_mean']}]
chart={'schemaVersion':1,'id':'validation-lift','title':'低使用命中倍数：真实月序与随机月序','description':'倍数相对同人数随机筛选；随机月序为1,000次重排的均值。','chart':{'type':'bar','x':'method','y':'lift','yLabel':'命中倍数','showXAxisLabel':False,'showValues':True},'rows':comparison,'source':base_source,'height':260}
(OUT/'lift_chart.json').write_text(json.dumps(chart,ensure_ascii=False,indent=2),encoding='utf-8')
history=[dict(x,cohort={'April alert':'4月告警组','No April alert':'未告警组'}[x['cohort']]) for x in R['cohort_history']]
hist_chart={'schemaVersion':1,'id':'validation-history','title':'两组客户的月均活跃天数占比','description':'按4月是否触发固定规则分组；4月差异由分组定义产生。','chart':{'type':'line','x':'month','y':'mean_activity_pct','series':'cohort','yLabel':'活跃天数 / 日历天数（%）','showXAxisLabel':False},'rows':history,'source':base_source,'height':290}
(OUT/'history_chart.json').write_text(json.dumps(hist_chart,ensure_ascii=False,indent=2),encoding='utf-8')
src_lift=dict(base_source,caveats=base_source['caveats']+['月序置换保留个体水平和共享基线效应，但月份可交换性只是近似假设。'],executedAt=R['executed_at'])
receipt={'schemaVersion':1,'items':[{'id':'lift-validation','title':'动态恶化信号未通过预设对照','queries':[{'id':'main-null','source':src_lift,'rows':comparison,'columns':['method','lift'],'summary':'真实月序2.704倍，重排均值2.686倍，重排95%区间2.312—3.073倍，单侧p=0.466。命中倍数是告警组5月低使用率除以全体5月低使用率。','preview':{'kind':'aggregate','note':'8,122名清洗后客户，1,000次个人内月序重排。'},'reportingPeriod':'2023年1—3月基线，4月告警，5月评价'}]}]}
(OUT/'lift_sources.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
hist_receipt={'schemaVersion':1,'items':[{'id':'cohort-history','title':'4月告警组5月平均使用回升','queries':[{'id':'history','source':base_source,'rows':history,'columns':['month','cohort','mean_activity_pct','customers'],'reportingPeriod':'2023年1—5月','preview':{'kind':'aggregate','note':'客户等权均值，April alert组582名；No April alert组7,540名。'}}]}]}
(OUT/'history_sources.json').write_text(json.dumps(hist_receipt,ensure_ascii=False,indent=2),encoding='utf-8')
extra={'schemaVersion':1,'items':[{'id':'snapshot','title':'当前人工复核队列与已完成范围','queries':[{'id':'snapshot-count','source':base_source,'rows':[{'measure':'清洗后客户','count':8122},{'measure':'未关闭且High/Critical','count':2673},{'measure':'同时4月5月低使用的复核候选','count':43}],'columns':['measure','count'],'summary':'43条候选的复核名单已生成。20条候选/对照盲审表已准备，评价列全部留空，人工评审尚未执行。','preview':{'kind':'aggregate','note':'6月支持快照，月度使用截至5月。'}}]},{'id':'independent-check','title':'独立核验及解释边界','queries':[{'id':'conditional-check','source':base_source,'summary':'独立计算重现582名告警，23.37%与7.51%的结果率。产品与基线十分位内置换仍有条件关联，p=0.0005；该关联与月份顺序价值是不同问题，不能推断干预收益。'}]}]}
(OUT/'extra_sources.json').write_text(json.dumps(extra,ensure_ascii=False,indent=2),encoding='utf-8')
print('Notebook cells executed and saved; source hashes retained; independent primary metrics match.')
print('20 blinded review rows prepared, 10 candidate/10 exact-matched controls. All review fields blank.')
print('Summary:',OUT/'validation_summary.md')
