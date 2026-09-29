# Atlassian 利润机会研究：实验与结论

## 项目档案：时间线、笔记、代码与反思

[项目总览](https://github.com/TsingZYY/project-experience/blob/main/projects/atlassian-analytics/README.md) · [时间线](https://github.com/TsingZYY/project-experience/blob/main/projects/atlassian-analytics/TIMELINE.md) · [开发／研究笔记](https://github.com/TsingZYY/project-experience/blob/main/projects/atlassian-analytics/NOTES.md) · [实际代码与入口](https://github.com/TsingZYY/project-experience/blob/main/projects/atlassian-analytics/CODE.md) · [最终反思](https://github.com/TsingZYY/project-experience/blob/main/projects/atlassian-analytics/REFLECTION.md)

以上档案于2026-09-30依据跨对话记录及现存文件整理，保留原始结果的适用范围；此次整理没有重新运行实验。


本仓库保存比赛中的数据检查、最小规则模型与离线验证。**当前研究怎样增加利润；实证样本和观测标签只采用比赛提供的三张合成CSV，另按用户明确要求开展转化机制与集成配置协助的条件模拟**，详见[数据范围](EXPERIMENT_SCOPE.md)。未进行降价或折扣实验。

**利润实证结论：已完成两轮20条验证。高协作筛选未显示清晰优势；加入客户和使用背景，也未在第二轮20条中补齐具体付费理由。模型现在输出可追溯证据和待确认问题，实际付费与利润提升仍未知。最新20人集成配置协助模拟试点、机制与候选核对，以及此前时间、满意度、成本保本线等研究见下文。**

## 补充机制排查：公司规模与使用量能解释套餐差异吗

新增 `integration_mechanism_v2/`，同一8,320客户上比较固定OLS模型。公司规模、行业、地区和产品构成的拟合R²为0.40%；加入会话、操作、协作量后18.41%；再加入套餐为88.00%。复用原1,666人测试集对应17.70%与87.26%，不是新的留出确认。六个公司规模层内，四套餐的平均集成数均依次增加。

这说明已记录背景在该模型中无法完全替代套餐，仍不能识别权限限制、需求自选或合成数据生成规则，更不验证配置帮助促进升级。新增真实观测和干预均为0。[研究说明](integration_mechanism_v2/README.md) · [结果](integration_mechanism_v2/results.json) · [复算代码](integration_mechanism_v2/experiment.py)。

## 已执行：20人集成配置协助模拟试点

经用户明确选择模拟试点，沿用原20人10:10分组，完成四种机制各100,000次条件模拟。全部概率与成本是假设：配置成功促进升级时，协助/对照升级率24.2%/17%，每批期望净贡献差+14；配置改善但升级无变化−130；免费需求满足后升级减少−226；配置无改善−130。基准需要6.5个百分点额外升级才能保本。

固定首批无效情景也偶然出现+270，而它的期望为−130，说明不能挑一批成功来验证机制。原客户结果仍为空、真实干预为0；模拟只是执行流程与条件边界，不代表实际升级或利润改善。

[模拟执行报告](integration_setup_sim_v1/README.md) → [固定20人首批记录](integration_setup_sim_v1/fixed_first_replay_20.csv) → [四种情景](integration_setup_sim_v1/scenario_summary.csv) → [完整结果](integration_setup_sim_v1/results.json) → [独立复核](integration_setup_sim_v1/independent_audit.md)。

## 机制假设：配置集成帮助能促进免费客户升级吗

新假设可拆为“帮助完成具体配置→获得价值→产生付费需求”。只用比赛数据，Free快照且Integration主题的89候选中排除5人身份冲突，剩84人；这84人同产品五个月记录完整且均至少一次非零集成使用，因此不能全称首次配置客户，也不能把主题当确认需求。

已准备每产品4人、共20人的证据卡和10:10配置协助/现行支持预分配示例。配置、升级和利润结果全部保持未知；真实试验须先确认需求与资格再随机分组，按提供帮助的分组比较，不能只比较配置成功者。报告包含7日任务完成、30日升级及净贡献的待执行测量方案。

[机制与验证方案](integration_setup_v1/README.md) → [84人候选](integration_setup_v1/candidate_roster.csv) → [20条证据卡](integration_setup_v1/evidence_cards_20.json) → [未执行的预分配](integration_setup_v1/planned_pilot_20.csv) → [结果范围](integration_setup_v1/results.json)。

## 响应后间隔、满意度与成本保本线

按用户最新要求，改用解决时间与评分研究。2,769张Closed时间对中1,365张逆序；剔除时间逆序与跨表身份冲突后，1,357名客户的响应后间隔与CSAT相关仅0.0030，95%区间[−0.0484, 0.0573]，p=0.9108。中位数分组的较快/较慢均分为3.018/3.052，未支持更快更满意；产品×优先级调整后结论不变。

固定20条来源审核为8条有序、7条逆序、5条缺失，无人评计时。新增可运行成本计算器与144格条件网格：在明示成本假设下，1,000票规模、全部时间可兑现时每票保本需节省1.2劳动分钟；仅一半可兑现需2.4分钟。响应后日历间隔不能当人工劳动时间，实际节省与利润未知。

[完整报告](resolution_csat_v1/README.md) → [固定方法](resolution_csat_v1/protocol.md) → [机器结果](resolution_csat_v1/results.json) → [20条时间审核](resolution_csat_v1/audit_cases_20.csv) → [成本计算器](resolution_csat_v1/cost_model.py) → [独立复核](resolution_csat_v1/independent_audit.md)。

## 客户体验与情绪证据

工单没有客户正文/对话/情感标注字段；Resolution是解决记录，不能直接当客户语言。固定词袋模型尝试预测Closed工单低评分，在533名留出客户上Brier=0.29740，差于常数基线0.23650，AUC=0.4846；未显示低评分识别增量，更不构成情绪识别验证。

已实现评分证据原型：1,102张1—2分进入待复核；580张3分、1,087张4—5分保留原评分；5,700张无评分保持未观测。所有票的语言情绪与业务效果保持未知。20条来源卡和全表输出可复现，评分映射正确不是情感模型准确率。建议保留客户体验方向，以可追溯证据复核为当前范围，保护利润的效果仍待验证。

[完整报告](sentiment_evidence_v1/README.md) → [固定方法](sentiment_evidence_v1/protocol.md) → [机器结果](sentiment_evidence_v1/results.json) → [20条证据卡](sentiment_evidence_v1/evidence_cards_20.json) → [独立复核](sentiment_evidence_v1/independent_audit.md)。

## 集成方向能否与工单结果结合

保守关联保留8,181客户各一票，同产品五个月集成记录全部完整。固定12项工单类别及集成相关比较，统一Holm校正后0项获得清晰支持。在同产品×套餐内，低集成组的低评分率差+1.75个百分点、技术类型+1.00、未关闭−0.10；均不清晰。取消请求反而低2.16个百分点，原始p=0.0154、12项校正p=0.185，保留为待复查线索。

这支持“本轮工单关联证据有限”，不能证明工单无价值。针对“全数据唯一显著是套餐—集成”的补充核验找到四个反例：套餐与会话、活跃比例、操作、协作的R²为10.15%—18.79%，按16项保守校正p均约0.0032。集成是已比较使用指标中关联最强，其他关系也可以显著；这些非工单关联仍不证明工单改善或利润收益。“比赛硬性要求工单”尚未找到可核对的原赛题/评分表，保持未核实。

[完整报告](ticket_bridge_v1/README.md) → [固定方法](ticket_bridge_v1/protocol.md) → [12项结果](ticket_bridge_v1/test_summary.csv) → [独立复核](ticket_bridge_v1/independent_audit.md)。

## 集成观点核验：集成使用与套餐的关联最强吗

这一假设得到明确的样本关联支持。用套餐类别解释集成使用量，原始产品月行的描述R²为59.14%；按8,320名客户分别取五个月跨产品均值后为87.93%，95%区间87.56%—88.31%。另1,666名留出客户的R²为87.26%；各产品结果一致。

共同合格的8,261名客户中，集成R²=87.94%，其他四项使用指标为10.15%—18.79%，因此集成是这五项中与套餐单变量关联最强的指标。这个R²方向是“套餐类别解释集成数量”，不能当作增加集成带来的升级效果。

3,979条产品月记录为零，但全部五个月、全部产品都为零的只有4名客户。数据没有不用原因、套餐变更或功能额度，尚不能解释为什么少用，或证明提高集成采用会增加利润。

[完整报告](integration_plan_v1/README.md) → [固定方法](integration_plan_v1/protocol.md) → [机器结果](integration_plan_v1/results.json) → [独立复核](integration_plan_v1/independent_audit.md)。

## 渠道观点核验：技术邮件更好、支付Chat更快吗

使用原比赛工单数据，技术问题的主比较为Email对Social media。已关闭且有评分的样本分别为135与152条，均分3.000与2.763；差异+0.237分，95%重抽样区间[−0.087, +0.554]，双侧置换p=0.161。产品×优先级调整后仍未提供清晰支持。渠道字段表示提交渠道，评分只覆盖已关闭工单，不能解释为切换处理渠道的因果收益。

支付主题共526条，其中156条已关闭且时间对完整，但82条（52.56%）解决时间早于首次响应；也没有工单创建时间。因而无法验证Chat解决更快，不删除异常后制造速度结论。

本轮完成了假设、字段可测性、全量比较、20条来源核对和研究决定：**暂不将“技术→邮件、支付→Chat”作为已验证的路由策略，利润效果仍未知。**

[完整报告](channel_hypotheses_v1/README.md) → [固定方法](channel_hypotheses_v1/protocol.md) → [机器结果](channel_hypotheses_v1/results.json) → [独立复核](channel_hypotheses_v1/independent_audit.md)。

## 条件模拟：什么情况下筛选名单赚钱

沿用首轮相同20人，筛选与普通名单各10人。转化概率及金额明确为未校准假设：新增转化净贡献100利润单位，每人跟进成本10，筛选额外成本20，前三种世界的自然转化5%。

| 假设世界 | 筛选名单期望增量利润 | 普通名单期望增量利润 | 筛选优势 |
|---|---:|---:|---:|
| 用得多更易转化 | +178.90 | +38.63 | +140.27 |
| 使用与转化无关 | +30.00 | +50.00 | −20.00 |
| 用得多更难转化 | −118.90 | +61.37 | −180.27 |

各情景100,000次重复均与解析计算及精确分布核对。正向关系下，高成本也会造成亏损；额外反例保持购买率不变但提高自然购买率，利润变为−90与−70。**高购买率不等于能被跟进改变的高转化增量。**

[模拟协议、盈亏阈值及反例](profit_scenarios_v1/README.md) → [完整情景结果](profit_scenarios_v1/scenario_summary.csv) → [成本敏感性](profit_scenarios_v1/cost_sensitivity.csv)。这些是条件结论，不是实测利润。

## 第二轮核验：客户背景能否支持具体付费建议

身份一致的Free客户中，377人带有Product inquiry或Product recommendation泛化标签，仅18人两个字段同时符合。标签组合不能当作购买意愿。每产品固定4条，共20条，逐条比较仅工单与加入客户/五个月使用背景后的证据覆盖。

20/20补充了套餐与使用背景，但两种视图均未确认明确购买意愿，缺少具体需求与付费套餐能力匹配依据；利润参数仍缺失。未知不等于没有需求，20条审核不提供转化率或真实效果。

可执行小模型输出17条先澄清、2条先核实退款/取消、1条继续确认具体需求。它提供来源和待确认问题，没有客户干预或已验证的销售效果。

[第二轮假设、结果与研究决定](profit_evidence_v2/README.md) → [20条原始记录包](profit_evidence_v2/case_packets_20.json) → [逐条证据审核](profit_evidence_v2/audit_annotations.json) → [小模型输出](profit_evidence_v2/model_outputs_20.json)。

## 利润首轮：从Free客户中寻找付费需求线索

原表1,472名Free客户，经既有身份一致性检查保留1,440人。每产品按1—4月平均协作人数选2人，共10人；另从各产品剩余Free客户中固定哈希抽取2人，共10人。冻结名单后核对5月原始协作人数，不增加模拟客户或成功概率。

| 方法 | 人数 | 5月每客户平均协作人数 |
|---|---:|---:|
| 历史高协作优先组 | 10 | 12.1 |
| 同产品哈希抽样比较组 | 10 | 10.9 |

差异+1.2；产品内7,776种完整标签置换的单侧p=0.286，未提供清晰支持。协作人数不是付费席位或购买意愿，此结果不能解释为付费或利润提升。保留利润方向，不将该筛选规则当作已经验证的销售策略。

[利润机会研究与结果](profit_opportunity_v1/README.md) → [固定协议](profit_opportunity_v1/protocol.md) → [20条原始记录](profit_opportunity_v1/cases_20.csv) → [机器结果](profit_opportunity_v1/results.json)。报告提供含未知参数的增量利润和盈亏平衡公式，缺失金额和转化率不以假设数值填充。

## 背景实验：五个产品谁更容易流失

原表没有取消成功、未续费或订阅终止标签。本轮主指标是记录为Cancellation request的客户占比，不能当作实际流失率。

| 产品 | 取消请求人数／分母 | 占比 |
|---|---:|---:|
| Loom | 340 / 1,586 | 21.44% |
| Trello | 324 / 1,575 | 20.57% |
| Bitbucket | 297 / 1,535 | 19.35% |
| Confluence | 335 / 1,767 | 18.96% |
| Jira | 338 / 1,718 | 19.67% |

五组整体p=0.394；最高/最低差距2.48个百分点，该对在全部10对比较的Holm校正后p=0.739；套餐调整未改变判断。Loom的5月低使用占比20.08%、Jira6.71%，但相对个人历史的持续下降占比接近（1.89%与1.88%）。绝对低使用不能直接解释成更容易流失。

[完整假设、结果与研究决定](product_churn_v1/README.md) → [协议](product_churn_v1/protocol.md) → [机器可读结果](product_churn_v1/results.json) → [每产品4条的原始来源核对](product_churn_v1/audit_cases_20.csv)。20条用于来源审计，产品差异使用完整可用分母；取消请求与使用指标采用各自合格队列。

## 之前的实验：客户信息能否改善低满意度识别

标签直接来自比赛CSV的Customer Satisfaction Rating，1—2分为低评分。经关联与使用记录质量检查保留2,644个客户；按不看评分的固定客户哈希分为训练2,100、开发524、测试20。无新造情景、客户回答或解决概率。

| 方法 | 20条测试的Brier误差（越低越好） |
|---|---:|
| 训练集低分比例常数 | 0.21819 |
| 仅工单字段 | 0.21680 |
| 工单＋客户画像＋1—4月使用 | 0.21843 |

加入信息的误差改善为−0.00163，配对重抽样95%区间[−0.01280, 0.01023]；没有通过预设门槛。20条中6条低评分，结果仅为小样本回顾性识别，不能外推全部工单或解释成解决率。

[假设与结果说明](csat_context_v1/README.md) → [冻结协议](csat_context_v1/protocol.md) → [可运行实验](csat_context_v1/experiment.py) → [20条原始案例预测](csat_context_v1/test_cases_20.csv) → [完整结果](csat_context_v1/results.json)。

## 之前基于比赛数据的实验

| 实验 | 已核实结果 | 可支持的结论 |
|---|---|---|
| 数据完整性与来源核查 | 8,320 名客户、8,469 张工单、42,210 条使用记录；排除身份冲突139人、活跃天数越界59人后，时序分析保留8,122人 | 数据口径及质量缺口明确 |
| 4月下降规则与5月低使用 | 582人触发；触发组23.37%，未触发组7.51%；相对全体8.64%的命中倍数为2.70 | 有定义内的低使用关联，不等于流失或干预收益 |
| 月序负对照 | 月份打乱后的平均倍数2.69；p=0.466 | 未通过预设动态恶化证据门槛；不能单独宣传2.70倍 |
| 最小规则模型 | 347张数据待核对、43张复核候选、8,079张沿用现有支持；20条来源案例及10个边界检查通过 | 实现符合规则，不是预测准确率或解决率 |
| 真实客服试点 | **CANDIDATE-UNRUN** | 只有实施方案，没有客户干预或实测效果 |

历史[条件性模拟](simulation/README.md)含人为可解决概率，已从当前主证据和默认复现中排除。自建问答情景的追问方向也已撤回；不再用外部规则补造比赛测试数据。旧的实现边界检查只证明代码符合定义，不计入效果样本。

## 最小模型

输入一张工单与对应产品连续五个月的使用记录，输出三类结论：

```text
数据关联与质量检查
  ├─ 数据问题 → DATA_CHECK
  └─ 数据可用 → 未关闭且High/Critical，且最近两月均显著低使用？
                 ├─ 是 → REVIEW_CANDIDATE + 计算依据 + 缺失信息
                 └─ 否 → STANDARD_SUPPORT
```

低使用定义：相对前三个月平均活跃率下降至少30%，并且绝对下降至少10个百分点。月活跃率使用当月日历天数标准化。规则版本固定，无模型训练、外部API或自动客服动作。“未触发”不代表健康，“候选”不代表已证明值得提级。工单是较后的快照，不作为4月的历史预测特征。

## 复现

建议 Python 3.12；锁定的 numpy/pandas 版本见 requirements.txt。最小模型本身仅用标准库。

```bash
python -m pip install -r requirements.txt
python reproduce.py
python reproduce.py --include-scenarios
python minimal_model/model.py --ticket-id 6545
```

`reproduce.py` 默认重跑比赛数据实证和证据审核汇总；加 `--include-scenarios` 再执行本轮授权的利润情景模拟。通过后生成 `reproduction_check.json`，实证与条件模拟分别记录；计算通过不代表假设成立。计算期间会更新结果时间戳和运行耗时，固定输入、版本与随机种子下的关键结果应一致。只运行最新模拟可用 `python profit_scenarios_v1/experiment.py`。证据核验脚本汇总已保存的来源审核，不冒充重新完成语义审核。

## 阅读顺序与证据

- [验证方案](validation_protocol.md) → [时序验证结论](validation_v1/validation_summary.md) → [已保存输出的Notebook](validation_v1/low_cost_validation.ipynb)
- [模型说明](minimal_model/README.md) → [单例输出](minimal_model/outputs/example_ticket_6545.json) → [实现检查](minimal_model/outputs/verification.json)
- [20条证据卡](competition_evidence/evidence_cards_20.md) → [原始记录核对结果](competition_evidence/case_checks.json)
- 历史归档：[模拟协议](simulation/protocol.md) → [全部情景结论](simulation/README.md)，不纳入当前仅比赛数据的有效性证据。
- [20条AI可操作性审计](actionability_audit.md)：未发现使用轨迹提供确定修复依据；不是客服人审。
- [赛后真实试点附录](resolution_validation/minimum_effect_trial.md)：未执行，不是完成比赛方案的前提。

额外的AI客服建议A/B方案只准备过输入，未执行，不计为实验结果。逐票大体积输出、缓存和桌面图表预览不随代码提交，可由脚本重新生成。

## 数据来源与适用范围

原始三张CSV和[字段说明](data/README.md)来自提供的 [Atlassian 竞赛数据文件夹](https://drive.google.com/drive/folders/1NirfOKfM54cYeYXS3gn3azWznX1jaFiP)，说明明确标注为合成数据。原始数据保留用于复现，哈希记录在结果文件中；本仓库不对源数据另行授予许可。

所有客户都有支持工单，无法比较“有工单”与“无工单”客户。满意度只覆盖已关闭工单；时间字段存在异常，不能直接当处理时长。缺少真实问题正文、实际干预和后续结果，不能报告真实解决率。进一步实施应预先固定业务指标、对照策略和成本约束，保留失败和未知结果。
