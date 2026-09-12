# Atlassian 支持复核：实验与结论

本仓库保存比赛中的数据检查、最小规则模型与离线验证。**当前假设、样本和观测标签只采用比赛提供的三张合成CSV**，详见[数据范围](EXPERIMENT_SCOPE.md)。未进行降价或折扣实验。

**当前结论：计算流程可运行、可追溯；新增客户画像和使用信息没有通过本轮低满意度识别的预设门槛。现有证据也不足以宣称动态预警或真实解决率提升。**

## 当前主实验：客户信息能否改善低满意度识别

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
python minimal_model/model.py --ticket-id 6545
```

`reproduce.py` 顺序重跑比赛数据检查、独立时序核查、原始来源案例核对、最小模型实现检查和低满意度识别实验，验证关键结论。通过后生成 `reproduction_check.json`；计算通过不代表假设成立。计算期间会更新结果时间戳和运行耗时，固定输入、版本与随机种子下的关键结果应一致。只运行本轮可用 `python csat_context_v1/experiment.py`。

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
