# 第二轮利润证据的独立来源审阅

本记录由独立代理审阅协议、冻结的 `case_packets_20.json`、三张原始 CSV 及 `data/README.md` 后形成。审阅过程中未读取主代理的审核注释、实验代码或结果文件，也未使用外部来源。以下状态是对现有来源能否支持一个说法的审查，不能当作真实客户需求、购买或利润标签。

## 状态口径

- `NOT_ESTABLISHED`：已有类别、主题或文本可以检查，但不足以支持该命题。
- `ABSENT_FIELD`：三张来源表缺少完成该项判断所需的一类记录。这里用于付费套餐能力及收入、成本、增量转化依据；不表示业务世界里这些事物不存在。
- `PRESENT`：原字段直接支持命题，并可精确引用。四项商业证据本次均未达到此状态。

`specific_need` 与 `explicit_purchase_intent` 在两种视图、全部 20 条均为 `NOT_ESTABLISHED`。`paid_capability_fit` 与 `profit_basis` 在两种视图、全部 20 条均为 `ABSENT_FIELD`。

具体需求未确立，是因为原表只有泛化类别、主题，以及空白或未表达具体任务的 Resolution；没有目标任务、具体操作、阻碍详情或可复述的客户原话。购买意愿未确立，是因为记录中没有明确的购买或升级表达；`Product inquiry`、`Product recommendation`、当前 `Free` 及使用量不能单独证明购买意愿。付费能力匹配缺少套餐功能和限制的来源表；利润依据缺少收入、成本及与对照相比的转化结果。B 视图确实多出背景字段和历史使用，但这些数值不能补出缺失的客户回答。

## 逐条审阅

表中状态顺序为：具体需求 / 明确购买意愿 / 付费能力匹配 / 利润依据。`N` = `NOT_ESTABLISHED`，`A` = `ABSENT_FIELD`。每行 A、B 两视图均逐条审阅；相同状态不代表客户行为相同。

| 案例（原工单 ID） | 精确来源摘录及理由 | ticket_only | enriched | 依协议路由 |
|---|---|---|---|---|
| PE2-01（4615） | `Product inquiry` / `Integration` 只表明咨询分类和集成主题，未写明与什么系统集成、失败步骤或目标。Resolution 为 `Begin blood hold get kind.`，不表达可确认的任务或购买。加入 1—5 月集成计数也不能确定具体集成需求。 | N/N/A/A | N/N/A/A | CLARIFY_REQUEST |
| PE2-02（5010） | `Product inquiry` / `Software bug` 是软件问题主题，Resolution 空白；缺少 bug 行为、复现过程与客户目标。公司规模 `1000+` 及协作人数不能证明客户愿意付费解决。 | N/N/A/A | N/N/A/A | CLARIFY_REQUEST |
| PE2-03（7951） | `Product inquiry` / `Display issue` 未说明显示对象或异常内容，Resolution 空白。较低活跃只说明记录的使用水平，不补充问题原因或升级意愿。 | N/N/A/A | N/N/A/A | CLARIFY_REQUEST |
| PE2-04（6686） | `Product inquiry` / `Device compatibility issue` 未说明设备、版本或限制。Resolution 为 `Pass animal Mr direction various century.`，不支持具体解决任务或购买。现有使用和公司背景不能对应任何有来源的付费能力。 | N/N/A/A | N/N/A/A | CLARIFY_REQUEST |
| PE2-05（928） | `Product inquiry` / `Account access` 没有账号、认证步骤或权限详情，Resolution 空白。Free 快照及月度计数不能补足访问任务与购买判断。 | N/N/A/A | N/N/A/A | CLARIFY_REQUEST |
| PE2-06（5703） | `Product inquiry` / `Data loss` 是需要澄清的问题标签，没有丢失对象、发生时间或恢复要求；Resolution 空白。使用下降不能确定丢失原因、付费需求或获益。 | N/N/A/A | N/N/A/A | CLARIFY_REQUEST |
| PE2-07（690） | `Product inquiry` / `Device compatibility issue` 缺少设备、版本与目标；Resolution 空白。行业、区域和使用次数均未提供客户对升级的表达。 | N/N/A/A | N/N/A/A | CLARIFY_REQUEST |
| PE2-08（8017） | `Cancellation request` / `Product recommendation` 同时出现，支持存在取消分类和推荐主题，但不能改写为主动购买。Resolution 空白，取消原因与对象未提供；历史活动仍存在也不否定取消标签。 | N/N/A/A | N/N/A/A | SUPPORT_FIRST |
| PE2-09（2602） | `Product inquiry` / `Integration` 缺少具体集成对象、步骤与目标；Resolution 空白。5 月 `Collaborators` 为 `19`，是协作计数证据，不是席位限制、付费能力匹配或购买意愿。 | N/N/A/A | N/N/A/A | CLARIFY_REQUEST |
| PE2-10（170） | `Product inquiry` / `Network problem` 未说明网络故障细节。Resolution 为 `Your determine such summer young.`，不表达具体任务或升级请求。补充使用背景未增加购买证据。 | N/N/A/A | N/N/A/A | CLARIFY_REQUEST |
| PE2-11（665） | `Product inquiry` / `Product setup` 未说明配置对象与期望行为。Resolution 为 `Before receive cut ago.`，不支持可执行的配置需求或购买。使用次数不能确定设置阻碍。 | N/N/A/A | N/N/A/A | CLARIFY_REQUEST |
| PE2-12（4179） | `Product inquiry` / `Product setup` 是设置主题；Resolution 为 `Congress treat stock effort.`，没有配置要求、错误信息或升级表达。公司规模和使用计数未提供缺失的需求。 | N/N/A/A | N/N/A/A | CLARIFY_REQUEST |
| PE2-13（884） | `Product inquiry` / `Product recommendation` 双标签直接支持先核对需求。Resolution 为 `Seek new whole teach yourself.`，不表达购买意愿或具体功能需求。`Free`、`1000+` 与协作计数不能把泛化推荐咨询变为付费意向。 | N/N/A/A | N/N/A/A | REQUIREMENT_REVIEW |
| PE2-14（844） | `Product inquiry` / `Cancellation request` 支持咨询分类中带取消主题，需要先核实取消请求。Resolution 空白，未给出取消原因，也没有新购买意愿。仍有活跃/集成记录不应覆盖取消标签。 | N/N/A/A | N/N/A/A | SUPPORT_FIRST |
| PE2-15（2125） | `Technical issue` / `Product recommendation` 可对应技术问题下的推荐主题；Resolution 为 `Produce free face majority.`，不能作为免费/付费选型需求原话。加入当前 `Free` 及使用背景未说明客户想购买什么。 | N/N/A/A | N/N/A/A | CLARIFY_REQUEST |
| PE2-16（8333） | `Product inquiry` / `Email delivery problem` 没有收发对象、错误或送达要求；Resolution 为 `Stand like quality firm.`，不支持明确任务与购买。月份使用变化不能解释送达问题。 | N/N/A/A | N/N/A/A | CLARIFY_REQUEST |
| PE2-17（503） | `Technical issue` / `Product recommendation` 未区分故障排查与选型需求，Resolution 空白。5 月 `Product Actions` 为 `125` 只支持行为量描述，不能证明升级需要或利润。 | N/N/A/A | N/N/A/A | CLARIFY_REQUEST |
| PE2-18（5580） | `Billing inquiry` / `Product recommendation` 含账务咨询与推荐主题，Resolution 空白；没有预算、报价接受或付款意向。当前 `Free` 和过往使用不能判定是购买咨询、账务疑问或标签不一致。 | N/N/A/A | N/N/A/A | CLARIFY_REQUEST |
| PE2-19（1739） | `Product inquiry` / `Loading issue` 未说明加载对象、时延和阻碍，Resolution 空白。使用和公司背景不能补出具体功能需求或愿付价格。 | N/N/A/A | N/N/A/A | CLARIFY_REQUEST |
| PE2-20（709） | `Product inquiry` / `Integration` 未说明具体集成、错误或期望；Resolution 空白。现有集成计数记录不等于新集成要求，亦没有付费能力来源。 | N/N/A/A | N/N/A/A | CLARIFY_REQUEST |

可直接确认的正面来源证据是：20 条均符合至少一个泛化咨询/推荐标签，20 条在客户表中的套餐均为 `Free`，20 条均能关联 5 个月使用背景；其中只有 PE2-13 同时有两个咨询/推荐标签。上述证据支持来源归档与提出澄清问题，不支持付费建议或利润增加。

## 原表独立复算

仅使用 CSV 标准库、JSON、SHA256 和协议参数独立复算，未调用主实验代码。

- 原始来源：8,320 客户、8,469 工单、42,210 使用行。
- 全部 8,469 工单邮箱均能唯一关联客户表；任一关联工单姓名、年龄、性别冲突的客户共 139 名，按协议整客排除后剩余 8,181 工单、8,181 客户。
- 当前 Free 的有效工单/客户均为 1,440；其中符合 `Product inquiry` 或 `Product recommendation` 的有 377 工单、377 客户。
- 以协议盐和 Ticket ID 算 SHA256，按每产品升序取 4 条，得到的 20 个 Ticket ID 及顺序与冻结包完全一致，且有 20 个唯一客户。
- 20 个工单源行及 20 个客户源行均一致；逐值比较了 240 个工单视图单元格、80 个客户背景单元格、100 个使用源行的 700 个单元格，全部匹配。
- 独立从使用全表按客户/产品取行，每个样本恰有 2023-01 至 2023-05 五条，与包内行完全相等；未发现重复或缺失月份。计数字段非负，Active Days 不超过当月自然日数。

| 产品 | 完整候选数 | SUPPORT_FIRST | REQUIREMENT_REVIEW | CLARIFY_REQUEST |
|---|---:|---:|---:|---:|
| Loom | 80 | 15 | 3 | 62 |
| Trello | 69 | 18 | 0 | 51 |
| Bitbucket | 58 | 7 | 3 | 48 |
| Confluence | 91 | 16 | 6 | 69 |
| Jira | 79 | 14 | 6 | 59 |
| 合计 | 377 | 70 | 18 | 289 |

冻结 20 条路由为 SUPPORT_FIRST 2、REQUIREMENT_REVIEW 1、CLARIFY_REQUEST 17。20 条中的类别计数：Product inquiry 16、Cancellation request 1、Technical issue 2、Billing inquiry 1；推荐主题共 5 条。这些是按公开规则计算的数量，不是路由准确率、付费概率或效果。

## 复核边界

未发现源行映射、固定样本选择或三路数量的错误。两种视图四项商业证据均无 PRESENT，因此没有观察到加入客户/使用背景后付费证据覆盖的提高。未知证据不代表客户无需求；本次也不测量真实客服决策、升级率、利润或用户体验改善。模型的可执行性仅指能按来源规则给出可追踪的澄清路径。

## 本次读取字节 SHA256

```text
data/customers.csv bb52312c947b0043df5b068ed96d0cd70e28ed7551ceff1ee16732cd817adc1a
data/customer_support_tickets.csv c1025a1ff1fd9b21cdd99e4b7387f353a8206e123f24cbdf00dc71445d512347
data/product_usage.csv e4cd675688ec7e10ba27f04488825737f131bcbe2239adb969e550b54ed07ebb
profit_evidence_v2/protocol.md 46d5f3859846dac435d2288ae21fe87d8232757d847f870f31f0fa8c2477f10b
profit_evidence_v2/protocol.json ee87c055df3bfa3b66c0f32cac294a46440bd8e0d4f2a161d2c422948b8b5a36
profit_evidence_v2/case_packets_20.json e58626962da6e91fd1e10f5eabcb5a0daf3bb5f27f1a8d6c966b62dd6dbcbadd
```
