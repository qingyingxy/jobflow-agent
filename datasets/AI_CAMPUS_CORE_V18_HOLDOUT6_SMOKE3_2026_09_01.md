# Core Parser v18 Holdout-6 Smoke（2026-09-01）

## 目的

验证将 `any_of` 从 nullable 联合类型改为单一数组后，未见样本中的
`structured_output_invalid` 是否消失，并补充观察字段质量与调用耗时。

## 公平性约束

- 从 154 条 strict manifest 中排除历史人工复核覆盖和 holdout-v1 至 holdout-v5
  选择清单里出现的 95 条样本，剩余候选池为 59 条。
- 使用固定种子 `holdout-v6-smoke3` 按 SHA-256 排名抽取 3 条，每家公司最多
  1 条：`campus-ai-013`、`campus-ai-135`、`campus-ai-030`。
- 模型调用前只依据原始 JD 和既定规则完成人工标签复核并冻结 v12 override；
  manifest 的 `review_required_count=0`。
- 预测生成后不修改冻结标签。

## 运行配置

- 模型：`deepseek-v4-flash`
- Parser：`jd-core-parser-v18`
- Prompt：`jd-core-parser-prompt-v11`
- Schema：`core-job-fields-v5`
- 并发：1
- 单条外层超时：240 秒
- 样本数：3

## 调用结果

- 成功：3/3（100%）
- `structured_output_invalid`：0
- 超时：0
- Warning：0
- 总生成耗时：303.792 秒

与 holdout-5 的 `1/3` 结构失败相比，本轮未复现 `any_of` 非数组问题。由于两轮
样本不同且样本量都很小，这只能作为协议修复通过小样本验证的证据，不能证明错误率
已永久归零。

## 严格指标

| 字段 | Precision | Recall | F1 | Exact Match |
|---|---:|---:|---:|---:|
| `job_type` | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| `locations` | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| `required_skills` | 0.8621 | 0.6944 | 0.7692 | 0.0000 |
| `required_skill_groups` | 0.5000 | 1.0000 | 0.6667 | 0.6667 |
| `preferred_skills` | 0.3333 | 0.2500 | 0.2857 | 0.3333 |

Macro-F1：`0.7443`。

## 逐条诊断

- `campus-ai-013`：岗位类型、地点、6 个核心必备技能和深度学习框架开放组均正确，
  仅漏掉 `工程实践`。
- `campus-ai-030`：编程语言组正确，主要必备能力具有较高语义覆盖，但出现两个错误
  技能组。其一在归一化前有多个值、归一化后塌缩为单个 `Agent`；其二把
  `实践经验/深入理解` 误当成技能备选关系。优先项还把部分示例产品直接列为技能，
  与冻结标签的上位能力粒度不一致。
- `campus-ai-135`：正确识别 `C++`、代码调试、示波器和逻辑分析仪，但把
  `嵌入式软件/操作系统/计算机组成` 放入提及，且未将“了解 MCU、RTOS、Linux
  驱动、通信协议或实时控制系统者优先”整体判为优先技能，说明强度判断应让句末
  `优先` 高于句首 `了解`。

## 结论

`any_of` 单一数组协议通过本轮 3 条未见样本验证：结构失败和超时均为 0，可以继续
保留。下一步不需要再改数组 schema，应在本地编译阶段删除归一化后不足两个选项的
技能组，并在 Prompt 中明确“了解……者优先”属于 preferred，而不是弱提及；完成
后再跑小规模 smoke，不直接跑完整 154 条。

## 产物

- 选择清单：`datasets/ai_campus_holdout_3_v6_selection_2026_09_01.json`
- 冻结标签：`datasets/ai_campus_label_overrides_v12_holdout6_smoke3_frozen.json`
- Manifest：
  `artifacts/evaluation/m11-ai-campus-manifest-core-v18-holdout6-smoke3-frozen-v12-2026-09-01.json`
- Predictions：
  `artifacts/evaluation/m11-ai-campus-predictions-core-v18-holdout6-smoke3-new-api-v12-2026-09-01.json`
- Report：
  `artifacts/evaluation/m11-ai-campus-report-core-v18-holdout6-smoke3-new-api-v12-2026-09-01.json`
