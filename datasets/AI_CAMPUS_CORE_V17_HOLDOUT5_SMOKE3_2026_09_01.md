# Core Parser v17 Holdout-5 Smoke（2026-09-01）

## 目的

验证缩减后的 `core-job-fields-v4` / `jd-core-parser-prompt-v10` /
`jd-core-parser-v17` 是否能减少长输出导致的超时，并检查新的条款协议在未见样本上的
`required`、`preferred` 与 `any_of` 分类。

## 公平性约束

- 从 154 条 strict manifest 中排除历史人工复核覆盖和 holdout-v1 至 holdout-v4
  选择清单里出现的 92 条样本，剩余候选池为 62 条。
- 使用固定种子 `holdout-v5-smoke3` 按 SHA-256 排名抽取 3 条，每家公司最多
  1 条：`campus-ai-134`、`campus-ai-054`、`campus-ai-113`。
- 模型调用前只依据原始 JD 和既定规则完成人工标签复核并冻结 v11 override；
  manifest 的 `review_required_count=0`。
- 预测生成后不修改冻结标签；发现的标签契约问题仅记录，不回改本轮指标。

## 运行配置

- 模型：`deepseek-v4-flash`
- Parser：`jd-core-parser-v17`
- Prompt：`jd-core-parser-prompt-v10`
- Schema：`core-job-fields-v4`
- 并发：1
- 单条外层超时：240 秒
- 样本数：3

## 调用结果

- 成功：`campus-ai-113`、`campus-ai-134`
- 失败：`campus-ai-054`，`structured_output_invalid`
- 超时：0
- 成功率：2/3（66.67%）
- 总生成耗时：530.002 秒

`campus-ai-054` 的两次输出都把 `skill_clauses[0].any_of` 和
`skill_clauses[3].any_of` 生成为非数组值，因此未通过 Pydantic 校验。该失败属于
结构协议稳定性问题，不是字段证据裁剪导致的失败。

## 严格指标

全 3 条（失败预测按空字段计入）：

| 字段 | Precision | Recall | F1 |
|---|---:|---:|---:|
| `job_type` | 1.0000 | 0.6667 | 0.8000 |
| `locations` | 1.0000 | 0.6000 | 0.7500 |
| `required_skills` | 0.7857 | 0.4231 | 0.5500 |
| `required_skill_groups` | 1.0000 | 0.6667 | 0.8000 |
| `preferred_skills` | 1.0000 | 0.6667 | 0.8000 |

Macro-F1：`0.7400`。

仅统计成功的 2 条：

| 字段 | Precision | Recall | F1 |
|---|---:|---:|---:|
| `job_type` | 1.0000 | 1.0000 | 1.0000 |
| `locations` | 1.0000 | 1.0000 | 1.0000 |
| `required_skills` | 0.7857 | 0.7857 | 0.7857 |
| `required_skill_groups` | 1.0000 | 1.0000 | 1.0000 |
| `preferred_skills` | 1.0000 | 0.6667 | 0.8000 |

成功样本 Macro-F1：`0.9171`。

## 逐条诊断

- `campus-ai-113`：三个必备备选组的选项和开放性全部正确，地点正确。必备技能中
  `实验评测/模型评测` 存在本体粒度差异；模型未把真实机器人落地、大规模训练和
  高质量开源项目召回为优先技能。冻结标签同时把 `LLM` 放入必备技能和项目方向组，
  与当前编译器“组选项不重复进入扁平必备技能”的契约存在冲突，本轮不回改。
- `campus-ai-134`：地点、仿真工具开放组及 6 个优先项全部正确。必备技能主要差异为
  `机器人常见传动机构/机器人传动机构` 的命名粒度，并额外抽取了
  `将仿真结论转化为设计建议`。4 个平铺提及项因不是原文连续片段而被证据校验删除，
  不影响本轮五个计分字段。
- `campus-ai-054`：输出结构失败，无法进行字段级诊断。

## 结论

本轮只能说明缩减协议在 3 条样本中没有发生超时，不能证明延迟已经稳定改善；不同
样本和极小样本量也不能与 v16 smoke 直接作性能比较。成功样本显示 `any_of` 语义
明显可用，但下一步应先消除 `any_of` 的 nullable/数组结构不稳定，再运行新的小规模
smoke，不应直接扩展到完整 154 条。

## 产物

- 选择清单：`datasets/ai_campus_holdout_3_v5_selection_2026_09_01.json`
- 冻结标签：`datasets/ai_campus_label_overrides_v11_holdout5_smoke3_frozen.json`
- Manifest：
  `artifacts/evaluation/m11-ai-campus-manifest-core-v17-holdout5-smoke3-frozen-v11-2026-09-01.json`
- Predictions：
  `artifacts/evaluation/m11-ai-campus-predictions-core-v17-holdout5-smoke3-new-api-v11-2026-09-01.json`
- Report：
  `artifacts/evaluation/m11-ai-campus-report-core-v17-holdout5-smoke3-new-api-v11-2026-09-01.json`
- Successful-only report：
  `artifacts/evaluation/m11-ai-campus-report-core-v17-holdout5-smoke3-successful-only-v11-2026-09-01.json`
