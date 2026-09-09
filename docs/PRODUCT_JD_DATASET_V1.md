# Product JD 100 条评测集 v1

日期：2026-09-06

## 目的

这套数据只评估精简版 `ProductJDParser`。它不再沿用旧实验中的语义本体、
复杂 clause 层级或模糊总分，而是检查少量、可以直接从 JD 原文核对的结果。

## 固定划分

总计 100 条真实官方岗位：

- `development-70`：日常标注、调试和错误分析。
- `sealed-test-30`：最终验收，禁止用于提示词修改和日常调参。

`development-70` 由原有 50 条开发集和 20 条扩展样本组成。扩展样本仅从官方、
允许 Parser 评测且不属于原开发集或密封集的岗位中选择；每轮优先选择当前开发集
中数量最少的公司，同数量时使用固定 SHA-256 排序。因此选择结果可重复生成，
且不会被人工偏好改变。

公开清单为
[`datasets/product_jd_eval_split_v1_2026_09_06.json`](../datasets/product_jd_eval_split_v1_2026_09_06.json)。
完整 JD 正文保存在 Git 忽略的本地 `artifacts/evaluation/`，公开文件只记录来源元数据、
正文长度和 SHA-256。

样本选择没有变化，公开划分清单仍为
[`datasets/product_jd_eval_split_v2_2026_09_06.json`](../datasets/product_jd_eval_split_v2_2026_09_06.json)。
当前本地开发标签为
`artifacts/evaluation/product-jd-development70-v3-human-reviewed-2026-09-07.json`；它以 v2
为输入，应用了完整的 `any_of` 争议人工裁定。v2 和 v3 都只处理
`development-70`；`sealed-test-30` 的样本 ID、元数据、路径和 SHA-256 与 v1 完全
相同，未读取正文、未生成标签、未运行模型。

## 当前标注状态

- 原开发集 50 条：从既有 Unified 标签保守迁移，状态为
  `reviewed_unified_gold_migration_verified`。
- 新增 20 条：完成 Product Schema 的 agent 首轮标注，状态为
  `agent_reviewed_product_native_v1`。
- development-70 标签 v2：已用确定性规则对齐 Product 契约，修正专业字段的硬性边界
  和逐字证据问题；`human_reviewed=false`，不能表述为独立人工复核或正式冻结金标。
- development-70 标签 v3：77 个 `any_of` 争议候选已经逐条人工裁定；这是关系争议范围
  的完整人工复核，不表示 facts、普通 `all_of`、职责等所有字段都已重新逐条人工标注。
- 密封 30 条：只固定原文，不包含 Product 标签，状态为 `sealed_unannotated`。

迁移时只保留有连续原文证据的内容。旧标签中的规范化语义项如果不能逐字出现在
`source_text` 中，会退化为整句 `all_of`，不会猜测拆分结果。迁移结果不是新的人工
金标，只有逐条复核并另行冻结后才能用于报告正式成绩。

## 精简标注规则

每条非空输出必须能在 `raw_content` 中找到连续原文：

1. `facts` 只标岗位类型、地点、毕业年份、学历、专业和截止日期六类事实。
2. `requirements` 只标明确的申请条件；职责不能标成条件。
3. 只有“优先、加分、preferred、plus”等明确措辞使用 `preferred`，其他明确条件
   使用 `required`。
4. 只有原文明示“或、任选、任一、任意、至少一种/一门/一类、or、one of、
   at least one”并能可靠拆出至少两个原文项时使用 `any_of`；否则保留完整原句并
   使用 `all_of`。
5. `items` 必须逐字出现在对应的 `source_text` 中，不做同义词归一化。
6. `responsibilities` 只保存连续职责原文，不生成摘要。
7. 不确定时留空，不通过推断提高召回率。

## 评价指标

评测器版本为 `product-jd-evaluator-v2`。日常先看报告中的 `primary_metrics`：

- Schema 合法率。
- 原文证据合法率。
- 解析成功率。
- facts 的 value Macro-F1，以及硬专业字段的存在性 F1。
- requirement 和 responsibility 的原文字符覆盖 F1。
- `any_of` 的边界容忍、选项精确组 F1。

详细诊断仍分别保留 facts 的精确值、字段存在性和原文字符覆盖，以及 `any_of` 的
严格整组精确、边界容忍整组精确、item 覆盖和原文字符覆盖。严格整组精确会把标点或
公共前缀边界差异也算错，因此只作为诊断项，不单独代表产品准确率。普通 `all_of`
不比较任意拆词粒度。

不使用单一的“综合准确率”，也不把旧语义标签与逐字原文项做模糊匹配。
部分 smoke 运行的内容质量只以已预测样本为分母，同时单独报告相对完整 70 条的完成率；
不得把未运行样本作为模型漏抽计入 smoke 的 Precision、Recall 或 F1。

当前 165 条来源 JD 均未提供明确投递截止日期，因此开发集的 `deadline` 正例数为
`0`。该字段继续保留在产品 Schema 中，但本版本不得为它报告 Precision、Recall 或
F1，也不能把“全部预测为空”写成 100% 准确；报告中必须显示 `N/A (no positive
examples)`。其余字段照常计算。

## development-70 单阶段参考基线

`product-jd-parser-v2 + product-jd-prompt-v7` 曾在标签 v2 的完整开发集上运行，
使用 `product-jd-evaluator-v2` 评估。70 条全部一次解析成功，没有触发修复重试。
该结果是两阶段 Parser 实现前的参考基线，只用于开发诊断，不是密封盲测成绩，
也不能替代独立人工复核。

| 主指标 | 结果 |
| --- | ---: |
| Schema 合法率 | 100.00% |
| 原文证据合法率 | 100.00% |
| 解析成功率 | 100.00% |
| Facts 精确值 Macro-F1 | 0.8952 |
| 硬专业存在性 F1 | 0.9254 |
| Requirement 原文字符覆盖 F1 | 0.8985 |
| `any_of` 边界容忍整组 F1 | 0.4031 |
| Responsibility 原文字符覆盖 F1 | 0.9495 |

硬专业问题主要是旧标签与产品定义不一致，而不是单纯 Parser 漏抽。标签 v2 只把明确
硬性专业限制放入 `major_requirements`；“专业优先”保留为 preferred requirement，
“专业不限”不再算硬专业。修订后硬专业的精确值、存在性和原文覆盖 F1 分别为
`0.9024 / 0.9254 / 0.8779`。

`any_of` 仍是当前主要未决项。严格整组、边界容忍整组、item 覆盖和原文覆盖 F1 分别为
`0.1550 / 0.4031 / 0.4574 / 0.4304`。开发金标有 43 组，清洗后预测有 86 组，说明
模型仍会把普通枚举或并列条件过度解释成“任选其一”。争议清单另外列出 18 个金标侧
不一致、56 个预测侧额外关系和 61 个由 sanitizer 降级的原始关系。这些是复核候选，
不是已经裁定的 Parser 错误或标签错误，不会自动覆盖金标。

旧 Parser 的确定性清洗只删除没有原文支持的事实，或把无法证明的 `any_of` 降级为
`all_of`。它不能新增模型未输出的事实。

本地完整产物：

- `artifacts/evaluation/product-jd-development70-baseline-predictions-v5.json`
- `artifacts/evaluation/product-jd-development70-baseline-report-v5.json`
- `artifacts/evaluation/product-jd-any-of-review-candidates-v2.json`

## 两阶段 Parser v3

当前代码已改为 `product-jd-parser-v3 + product-jd-two-stage-v3`：

1. `product-jd-extraction-v3` 只提取 facts、独立条件连续原文、required/preferred 和职责。
2. `product-jd-relation-v3` 一次接收该 JD 的全部条件，由模型 API 判断
   `all_of / any_of / uncertain`、逐字 items 和理由。
3. 本地代码不再根据“或、任选”等关键词决定关系，只校验索引完整性、Schema、
   `source_text/items` 的逐字证据，以及 `any_of` 至少包含两个选项。
4. `uncertain` 在本地匹配中固定进入“待确认”，不会被自动当成全部满足或任选满足。

正常含条件的 JD 使用两次模型调用；没有条件时跳过第二阶段。每个阶段只有结构或证据
校验失败时才允许重试一次，因此单份 JD 正常为 2 次、最坏为 4 次。

2026-09-06 使用 `deepseek-v4-flash` 对 development-70 的固定前 10 条做了 v3 smoke，
共调用 20 次，10 条全部通过 Schema 与逐字证据校验。主要结果为：Facts value F1
`0.8695`、Requirement 字符覆盖 F1 `0.7853`、`any_of` 边界容忍整组 F1 `0.7273`、
Responsibility 字符覆盖 F1 `0.9232`。8 个金标 `any_of` 均完成边界对齐；模型另输出
6 组语义上可能成立但与当前金标不一致的备选关系，应作为标签口径复核项，不能用本地
规则强制覆盖。

扩跑 development-70 时，API 余额在完成 41 条后耗尽；其余 29 条均为 HTTP 402，不能
把当前完整报告中的总体分数解释为模型质量。成功结果和失败诊断已保存在 v3 checkpoint。
额度恢复后使用 `--resume --retry-failures` 只重跑失败项。完成关系标签裁定和版本冻结前，
继续不读取、不标注、不运行 `sealed-test-30`。

## Terra medium 与两阶段 Parser v4

2026-09-07 将模型切换为 `gpt-5.6-terra`，思考深度使用 API 标准值
`reasoning_effort=medium`。该兼容 API 的简单 strict `json_schema` 请求可用，但当前
Product Pydantic Schema 会因网关要求把所有 properties 都列入 `required` 而返回
HTTP 400。因此实际配置使用 `response_format=json_object`，结构、索引完整性和逐字
证据仍由现有 Pydantic 校验与一次受限重试保证，不增加本地语义判断规则。

`product-jd-two-stage-v4` 只修改第一阶段提取口径：忽略没有具体技术或经历对象的泛化
软素质；同一编号、同强度、同一能力主题的过程链默认保持一条，不再按每个动词或逗号
拆成微条件。第二阶段仍使用 `product-jd-relation-v3`，由模型结合完整 JD 判断
`all_of / any_of / uncertain`。

固定前 10 条 smoke 中，v4 将 requirement 数量从 v3 的 102 条降到 61 条，接近金标
59 条；Requirement 字符覆盖 F1 从 `0.8167` 提升到 `0.8657`，`any_of` 边界容忍
整组 F1 从 `0.5833` 提升到 `0.6957`。8 个金标 `any_of` 均被识别，另有 7 组模型
认为语义成立、但与迁移标签关系不一致的候选。

随后只在 `development-70` 完成全量运行。70 条全部通过 Schema、逐字证据和解析校验；
共进行 141 次模型调用，其中 1 次为校验重试。结果如下：

| 主指标 | 结果 |
| --- | ---: |
| Schema 合法率 | 100.00% |
| 原文证据合法率 | 100.00% |
| 解析成功率 | 100.00% |
| Facts 精确值 Macro-F1 | 0.8462 |
| 硬专业存在性 F1 | 0.9706 |
| Requirement 原文字符覆盖 F1 | 0.9119 |
| `any_of` 边界容忍整组 F1 | 0.4324 |
| Responsibility 原文字符覆盖 F1 | 0.9346 |

全量 requirement 数量为金标 496 条、预测 506 条，说明 v4 已基本解决第一阶段的过度
拆分。`any_of` 仍是唯一需要人工裁定的边界：开发标签有 43 组，模型预测 105 组；
边界对齐后命中 32 组，Precision/Recall/F1 为 `0.3048 / 0.7442 / 0.4324`。
11 个金标侧不一致中有 7 个已经被模型判为 `any_of`，只是 `C/C++` 是否拆开、共享
修饰语是否进入 item 等边界不同；预测侧额外的 66 组中也包含“任一方向均可”、
“论文或竞赛”等语义上合理的可替代关系。

当前 development 标签来自旧标签迁移且 `human_reviewed=false`，因此不能把全部额外关系
直接认定为模型错误，也不应增加本地关键词规则强制降级。下一步应逐条裁定完整争议清单，
冻结新的 development 关系标签后再判断是否需要更新关系提示词。在此之前继续禁止读取、
标注或运行 `sealed-test-30`。

本次产物：

- `artifacts/evaluation/product-jd-development70-terra-medium-json-object-v4-predictions-v1.json`
- `artifacts/evaluation/product-jd-development70-terra-medium-json-object-v4-report-v1.json`
- `artifacts/evaluation/product-jd-any-of-review-candidates-terra-medium-v4-development70-v1.json`

## `any_of` 人工复核标签 v3

2026-09-07 完成了上述全量争议清单的 77 条人工裁定：69 条采用 API 结果，3 条保留旧
标签，5 条使用人工自定义边界；最终包含 73 条 `any_of` 和 4 条 `all_of` 裁定。
确定性应用脚本会验证候选与裁定一一对应、拒绝同一金标被多次覆盖，并对全部 70 条结果
重新执行 Product Schema 与逐字证据校验。应用结果为 73 个 requirement 替换和 4 个
新增，其中 73 个结果相对 v2 实际发生变化；整个过程只读取 v2 development、争议候选
和人工裁定文件。

v3 标签共有 502 条 requirement，其中 105 条为 `any_of`。复用原有 Terra medium v4
预测重新计算指标，没有再次调用 API：

| 主指标 | v2 标签 | v3 人工复核标签 |
| --- | ---: | ---: |
| Schema 合法率 | 100.00% | 100.00% |
| 原文证据合法率 | 100.00% | 100.00% |
| 解析成功率 | 100.00% | 100.00% |
| Facts 精确值 Macro-F1 | 0.8462 | 0.8462 |
| 硬专业存在性 F1 | 0.9706 | 0.9706 |
| Requirement 原文字符覆盖 F1 | 0.9119 | 0.9170 |
| `any_of` 边界容忍整组 F1 | 0.4324 | 0.9524 |
| Responsibility 原文字符覆盖 F1 | 0.9346 | 0.9346 |

`any_of` 的严格整组 F1 为 `0.8286`，边界容忍整组 F1 为 `0.9524`，item 覆盖 F1
为 `0.9661`，原文覆盖 F1 为 `0.9716`。标签和预测现在都包含 105 组 `any_of`；边界
容忍整组只剩 5 个未命中。另有 3 个模型把动作方式误判为 `any_of` 的额外关系。二者
合计对应人工裁定中 8 个真正的模型关系/边界错误，下一轮关系提示词只需围绕这些残差
调整，不需要增加本地关键词语义规则。

本次产物：

- `artifacts/evaluation/product-jd-development70-v3-human-reviewed-2026-09-07.json`
- `artifacts/evaluation/product-jd-development70-terra-medium-json-object-v4-report-v2-human-reviewed.json`
- `artifacts/evaluation/product-jd-any-of-post-review-residuals-terra-medium-v4-v1.json`

## 关系提示词 v6 残差复测

人工复核后确认的模型残差共有 7 个岗位、8 条关系/边界问题。当前代码更新为
`product-jd-two-stage-v6`：第一阶段 `product-jd-extraction-v5` 增强“局部备选项与独立
共同条件”的拆分；第二阶段 `product-jd-relation-v5` 要求优先选择可直接匹配的技术、
对象、方向或资格分支，禁止把思考/实践、复现/参与、分析/解释等动作方式拆成
`any_of`，并明确多层“或”和局部备选关系的作用范围。仍然只由 API 做语义判断，
本地代码没有新增关键词语义规则。

只对这 7 个 development 样本做了 Terra medium 定向复测，共 14 次模型调用，全部通过
Schema 和逐字证据校验。同一子集上的结果如下：

| 指标 | v4 | v6 |
| --- | ---: | ---: |
| `any_of` 边界容忍整组 F1 | 0.6875 | 0.9375 |
| `any_of` item 覆盖 F1 | 0.7810 | 0.9369 |
| `any_of` 原文覆盖 F1 | 0.8231 | 0.9373 |
| Requirement 原文字符覆盖 F1 | 0.9191 | 0.9094 |

v6 在 16 个金标 `any_of` 中边界对齐 15 个，同时输出 16 个预测组。本次运行仍有 2 个
残差：一条复合资格条件被第一阶段漏抽，一条 CAE 经历范围被第二阶段过度解释为
`any_of`。由于这是 7 条定向开发复测，且 Requirement 覆盖略有下降，不能据此宣称
完整 development-70 已全面提升；在全量重跑前保留 v4 全量报告作为当前完整基线。
本轮仍未读取、标注或运行 `sealed-test-30`。

定向复测产物：

- `artifacts/evaluation/product-jd-residual7-terra-medium-json-object-v6-predictions-v1.json`
- `artifacts/evaluation/product-jd-residual7-terra-medium-json-object-v6-report-v1.json`
- `artifacts/evaluation/product-jd-residual7-terra-medium-json-object-v6-any-of-residuals-v1.json`

### v6 development-70 全量结果

2026-09-07 随后使用相同的 Terra medium 配置运行完整 development-70。70 条全部解析
成功，共调用模型 141 次；只有 `campus-ai-160` 发生 1 次校验重试，重试后通过。

| 主指标 | v4 | v6 |
| --- | ---: | ---: |
| Facts 精确值 Macro-F1 | 0.8462 | 0.8595 |
| 硬专业存在性 F1 | 0.9706 | 0.9706 |
| Requirement 原文字符覆盖 F1 | 0.9170 | 0.9162 |
| `any_of` 边界容忍整组 F1 | 0.9524 | 0.7465 |
| Responsibility 原文字符覆盖 F1 | 0.9346 | 0.9467 |

v6 把最初定向处理的 8 个关系错误减少到 2 个，但在其他开发样本上产生了新的关系
分歧。预测 `any_of` 从 105 组增至 112 组，边界对齐命中从 100 组降至 81 组；残差
分析列出 24 个金标侧不一致和 14 个预测侧额外关系。因此 v6 不能按当前结果冻结，也
不能用于密封集验收。当前完整稳定参考仍是 v4 在人工复核 v3 标签上的报告；后续应先
决定回退 v4，或重新设计更短、更稳定的关系提示词，再进行新的 development 验证。

全量 v6 产物：

- `artifacts/evaluation/product-jd-development70-terra-medium-json-object-v6-predictions-v1.json`
- `artifacts/evaluation/product-jd-development70-terra-medium-json-object-v6-report-v1.json`
- `artifacts/evaluation/product-jd-development70-terra-medium-json-object-v6-any-of-residuals-v1.json`

## relation-only 受控实验与指标拆分

2026-09-07 固定 v4 的 `raw_extraction`，只重放第二阶段关系判断，从而排除第一阶段提取
变化。原 `product-jd-relation-v5` 在 70 条上全部成功，共 70 次调用、0 次重试；facts、
Requirement 原文覆盖和 Responsibility 指标与 v4 完全相同，但 `any_of` 边界容忍整组
F1 为 `0.8182`。这证明完整 v6 从 `0.9524` 降到 `0.7465` 的主要原因是关系提示词，
提取变化又进一步放大了下降。

随后进行了四个只改关系提示词的消融版本。`relation-v6` 采用强保守默认，
`relation-v7` 强调整条条件反事实，`relation-v8` 恢复 v5 主体并增加复合条件约束，
`relation-v9` 仅保留动作方式排除与边缘部署模型作用域说明。四版均未超过 v5，因此
运行默认已恢复为 `product-jd-two-stage-v6` / `product-jd-relation-v5`，不再继续用
development-70 堆叠提示词规则。

评估器升级为 `product-jd-evaluator-v3`，将两个问题分开报告：

- `aligned_relation_groups`：只判断某条条件是否正确识别为 `any_of`，容忍 source_text
  边界差异，不要求 items 完全一致。
- `aligned_exact_item_groups`：在关系正确的基础上继续要求 items 集合精确一致，衡量边界
  和粒度。

| 固定 v4 提取的关系版本 | 预测 `any_of` | 关系识别 F1 | 关系 + items 精确 F1 |
| --- | ---: | ---: | ---: |
| v4 原始预测 | 105 | 0.9714 | 0.9524 |
| relation-v5 | 115 | 0.9364 | 0.8182 |
| relation-v6 | 62 | 0.7305 | 0.4671 |
| relation-v7 | 91 | 0.8878 | 0.5510 |
| relation-v8 | 86 | 0.8901 | 0.6073 |
| relation-v9 | 94 | 0.9347 | 0.7437 |

拆开后可见：relation-v5 的关系识别 F1 已有 `0.9364`，明显高于 items 精确 F1
`0.8182`。当前剩余问题不应再被笼统描述为“API 不会判断 any_of”；更准确的说法是，
API 对关系本身已经较准，但对 `创业/创业经历`、复合名称是否拆分、长分支保留范围等
items 粒度仍不稳定。后续产品决策应以关系识别指标为主，以 items 精确指标作为诊断，
避免为了追逐单一边界写法而让整体语义判断退化。本轮仍未读取、标注或运行
`sealed-test-30`。

受控实验产物：

- `artifacts/evaluation/product-jd-development70-v4-extraction-relation-v5-replay-predictions-v1.json`
- `artifacts/evaluation/product-jd-development70-v4-extraction-relation-v5-replay-report-v1.json`
- `artifacts/evaluation/product-jd-development70-v4-extraction-relation-v5-replay-any-of-residuals-v1.json`
- `artifacts/evaluation/product-jd-development70-v4-extraction-relation-v6-replay-*`
- `artifacts/evaluation/product-jd-development70-v4-extraction-relation-v7-replay-*`
- `artifacts/evaluation/product-jd-development70-v4-extraction-relation-v8-replay-*`
- `artifacts/evaluation/product-jd-development70-v4-extraction-relation-v9-replay-*`
- `artifacts/evaluation/product-jd-development70-*-evaluator-v3-report-v1.json`

## 复现

```powershell
.\.venv\Scripts\python.exe scripts\build_product_jd_eval_dataset_v1.py
.\.venv\Scripts\python.exe scripts\revise_product_jd_development_v2.py
.\.venv\Scripts\python.exe scripts\apply_product_jd_any_of_human_review.py
.\.venv\Scripts\python.exe scripts\apply_product_jd_sealed30_relation_review.py
.\.venv\Scripts\python.exe scripts\apply_product_jd_sealed30_item_review.py
.\.venv\Scripts\pytest.exe tests\test_product_jd_eval_dataset.py -q
.\.venv\Scripts\python.exe scripts\analyze_product_jd_relation_disagreements.py
# 使用已有预测重算 v3 标签指标，不调用 API：
.\.venv\Scripts\python.exe scripts\run_product_jd_baseline.py --dataset artifacts\evaluation\product-jd-development70-v3-human-reviewed-2026-09-07.json --predictions artifacts\evaluation\product-jd-development70-terra-medium-json-object-v4-predictions-v1.json --report artifacts\evaluation\product-jd-development70-terra-medium-json-object-v4-report-v2-human-reviewed.json --evaluate-only
# 使用已有 sealed-30 预测重算关系复核标签指标，不调用 API：
.\.venv\Scripts\python.exe scripts\run_product_jd_baseline.py --dataset artifacts\evaluation\product-jd-sealed30-relation-reviewed-v1-2026-09-08.json --predictions artifacts\evaluation\product-jd-sealed30-terra-medium-v1-predictions.json --report artifacts\evaluation\product-jd-sealed30-terra-medium-relation-reviewed-v1-report.json --evaluate-only
# 使用相同预测重算关系 + items 完整裁定后的指标，不调用 API：
.\.venv\Scripts\python.exe scripts\run_product_jd_baseline.py --dataset artifacts\evaluation\product-jd-sealed30-relation-items-reviewed-v2-2026-09-08.json --predictions artifacts\evaluation\product-jd-sealed30-terra-medium-v1-predictions.json --report artifacts\evaluation\product-jd-sealed30-terra-medium-relation-items-reviewed-v2-report.json --evaluate-only
# 可重复传入 --case-id，只运行指定的 development 样本。
# 以下命令会调用真实模型，只运行 development-70 的前 10 条：
.\.venv\Scripts\python.exe scripts\run_product_jd_baseline.py --max-new-cases 10 --max-model-calls 30 --concurrency 2
# API 中断后只重跑 checkpoint 中的失败项：
.\.venv\Scripts\python.exe scripts\run_product_jd_baseline.py --resume --retry-failures --max-model-calls 180 --concurrency 2
```

## sealed-test-30 首次预评测（2026-09-08）

在用户确认开始测试后读取此前未打开的 30 条密封原文。先由 Codex 在不读取 Product JD
预测的前提下建立盲标草案并通过 Schema 与逐字证据校验，再冻结标签、解析器、评测器、
模型配置和预注册阈值的 SHA-256，最后一次性运行当前产品候选版本。标签草案的 SHA-256
为 `c602badc9a29194186def0a6f0dd2980873dbff9dee9c7c5cf27ef01b70f4ea6`，预测文件在
该哈希冻结时尚不存在。

运行配置为 `gpt-5.6-terra`、reasoning effort `medium`、`json_object`，解析版本为
`product-jd-parser-v3 / product-jd-two-stage-v6 / product-jd-extraction-v5 /
product-jd-relation-v5`。30 条全部成功，共 60 次模型调用，没有校验重试。

| 预注册指标 | sealed-test-30 预评测 | 阈值 | 结果 |
| --- | ---: | ---: | --- |
| 解析成功率 | 100.00% | 95% | 通过 |
| Schema 合法率 | 100.00% | 95% | 通过 |
| 逐字证据合法率 | 100.00% | 95% | 通过 |
| Facts 精确值 Macro-F1 | 0.8867 | 0.80 | 通过 |
| 硬专业存在性 F1 | 1.0000 | 0.90 | 通过 |
| Requirement 原文字符覆盖 F1 | 0.9613 | 0.85 | 通过 |
| `any_of` 关系识别 F1 | 0.9074 | 0.85 | 通过 |
| `any_of` 关系 + items 精确 F1 | 0.7037 | 0.70 | 通过 |
| Responsibility 原文字符覆盖 F1 | 0.9576 | 0.85 | 通过 |

54 个金标 `any_of` 与 54 个预测组中，关系识别为 49 TP、5 FP、5 FN；关系正确后，
items 精确组为 38 TP、16 FP、16 FN。全部预注册阈值通过，但当前标签状态仍是
`codex_blind_draft_requires_human_review`，因此这些数字只能称为预评测，不能直接写成
“人工复核密封集成绩”。人工裁定必须保留修改日志，且不得再根据结果修改提示词或重跑
密封集；完成裁定后只能使用已保存预测重新计算一次最终报告。

本次产物：

- `datasets/product_jd_sealed30_preliminary_preregistration_v1_2026_09_08.json`
- `datasets/product_jd_sealed30_preliminary_evaluation_receipt_v1_2026_09_08.json`
- `artifacts/evaluation/product-jd-sealed30-codex-blind-draft-v1-2026-09-08.json`
- `artifacts/evaluation/product-jd-sealed30-terra-medium-v1-predictions.json`
- `artifacts/evaluation/product-jd-sealed30-terra-medium-v1-report.json`
- `artifacts/evaluation/product-jd-sealed30-any-of-review-candidates-v1-2026-09-08.json`
- `docs/PRODUCT_JD_SEALED30_REVIEW_CHECKLIST_V1.md`

## sealed-test-30 关系争议人工裁定（2026-09-08）

项目负责人逐条裁定上述预评测揭示的 10 条关系语义分歧：6 条采用 API 关系判断，
4 条保留盲标草案。裁定通过独立决策文件和确定性应用脚本执行；原始盲标、预测文件和
初步报告均未修改。应用过程只读取盲标和裁决文件，共替换 7 条 requirement、插入 9 条，
没有再次调用模型。

复用相同的 30 条 Terra medium 预测重新评估后：

| 指标 | 盲标草案 | 关系人工裁定后 | 阈值 | 结果 |
| --- | ---: | ---: | ---: | --- |
| 解析成功率 | 100.00% | 100.00% | 95% | 通过 |
| Schema 合法率 | 100.00% | 100.00% | 95% | 通过 |
| 逐字证据合法率 | 100.00% | 100.00% | 95% | 通过 |
| Facts 精确值 Macro-F1 | 0.8867 | 0.8867 | 0.80 | 通过 |
| 硬专业存在性 F1 | 1.0000 | 1.0000 | 0.90 | 通过 |
| Requirement 原文字符覆盖 F1 | 0.9613 | 0.9617 | 0.85 | 通过 |
| `any_of` 关系识别 F1 | 0.9074 | 0.9636 | 0.85 | 通过 |
| `any_of` 关系 + items 精确 F1 | 0.7037 | 0.7636 | 0.70 | 通过 |
| Responsibility 原文字符覆盖 F1 | 0.9576 | 0.9576 | 0.85 | 通过 |

关系识别共有 56 个裁定后金标组和 54 个预测组，得到 53 TP、1 FP、3 FN，Precision、
Recall、F1 分别为 `0.9815 / 0.9464 / 0.9636`。这 10 条关系语义已经完成项目负责人
复核，因此 `0.9636` 可以明确写成“30 条密封集、关系分歧人工裁定后的关系识别 F1”。
但标签的 facts、普通 `all_of`、职责没有全部重新逐条人工标注，且另有 11 组关系一致、
仅 items 写法不同的边界尚待复核，所以不得把整个数据集描述为“完整独立人工金标”；
`0.7636` 的关系 + items 精确 F1 仍是暂定值。

本轮新增产物：

- `datasets/product_jd_sealed30_relation_adjudication_round1_decisions_v1_2026_09_08.json`
- `datasets/product_jd_sealed30_relation_review_evaluation_receipt_v1_2026_09_08.json`
- `scripts/apply_product_jd_sealed30_relation_review.py`
- `artifacts/evaluation/product-jd-sealed30-relation-reviewed-v1-2026-09-08.json`
- `artifacts/evaluation/product-jd-sealed30-terra-medium-relation-reviewed-v1-report.json`

## sealed-test-30 items 边界人工裁定（2026-09-08）

项目负责人继续裁定 11 组关系正确但 items 边界不一致的结果：10 组采用 API items，
1 组保留盲标草案。应用脚本严格保持每条 requirement 的 `source_text`、`level`、
`relation` 和 `relation_reason` 不变，仅更新明确裁定的 `items`；10 组实际改变，1 组保持。
复用相同预测重算，全程没有模型调用。

| 指标 | 关系裁定后 | 关系 + items 裁定后 | 结果 |
| --- | ---: | ---: | --- |
| `any_of` 关系识别 F1 | 0.9636 | 0.9636 | 不变 |
| `any_of` 关系 + items 精确 F1 | 0.7636 | 0.9455 | 提升 0.1818 |
| `any_of` item 覆盖 F1 | 0.8500 | 0.9560 | 提升 0.1060 |

关系识别为 53 TP、1 FP、3 FN；关系和 items 同时精确为 52 TP、2 FP、4 FN。
剩余的一组 items 差异来自负责人明确选择保留第 11 条草案，因此属于模型边界错误，
不能继续修改标签以追求满分。关系与 items 两项指标的人工争议裁定至此完成。

本次产物：

- `datasets/product_jd_sealed30_item_boundary_adjudication_round2_decisions_v1_2026_09_08.json`
- `datasets/product_jd_sealed30_relation_items_review_evaluation_receipt_v2_2026_09_08.json`
- `scripts/apply_product_jd_sealed30_item_review.py`
- `artifacts/evaluation/product-jd-sealed30-relation-items-reviewed-v2-2026-09-08.json`
- `artifacts/evaluation/product-jd-sealed30-terra-medium-relation-items-reviewed-v2-report.json`
