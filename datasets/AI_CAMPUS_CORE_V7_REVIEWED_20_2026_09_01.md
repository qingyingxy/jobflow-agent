# AI Campus Core Parser v7 Reviewed-20 Evaluation

日期：2026-09-01

## 范围

- 样本：`ai_campus_label_overrides_v5_skill_schema_reviewed.json` 中人工复核的 20 条。
- 字段：`job_type`、`locations`、`required_skills`、`required_skill_groups`、`preferred_skills`。
- Parser：`jd-core-parser-v7`。
- Prompt：`jd-core-parser-prompt-v5`。
- 模型：`deepseek-v4-flash`。

## 调用结果

首轮完成 18/20；`campus-ai-087` 和 `campus-ai-105` 发生模型超时。第一次定向重试时
服务端对两条均返回 HTTP 402。模型额度恢复后再次从 checkpoint 只重试这两条，最终
20/20 全部成功，未重复调用其余 18 条。

## 指标

| 字段 | v7 F1（20 条） | v4 同标签口径 F1（20 条） |
| --- | ---: | ---: |
| 岗位类型 | 1.000 | 1.000 |
| 地点 | 1.000 | 1.000 |
| 必备技能 | 0.644 | 0.435 |
| `required_skill_groups` | 0.694 | 0.361 |
| 加分技能 | 0.655 | 0.680 |
| Macro-F1 | 0.799 | 0.695 |

v4 对照使用当前标签重新计算，因此包含 077/152 的普通仿真平台枚举修订。两个版本
均覆盖相同的 20 条人工复核样本。

## 主要误差

- `preferred_skills` Precision 为 0.576。当前确定性恢复会把加分段中的大量具体动作、
  设备和实验活动都提升为技能，`campus-ai-106` 最明显。
- `required_skills` Exact Match 为 1/20。主要问题是上位类别、具体能力和同义表达的粒度
  仍不统一，077、100、103、152、159 的差异较大。
- `required_skill_groups` Exact Match 为 13/20。普通枚举与 `any_of` 已明显改善，但
  部分复杂方向列表仍会被拆分、漏项或错误开放。

## 结论

v7 已验证了本轮 `any_of` 优化能从 5 条扩展到完整的 20 条人工复核集，且相同口径下
Macro-F1 相比 v4 从 0.695 提升至 0.799。但暂不应直接运行完整 154 条；下一步应先
收紧加分项恢复范围，并统一剩余技能粒度，再复跑这 20 条确认没有回归。

## 产物

- Manifest：`artifacts/evaluation/m11-ai-campus-manifest-core-v7-reviewed-20-2026-09-01.json`
- Predictions：`artifacts/evaluation/m11-ai-campus-predictions-core-v7-reviewed-20-2026-09-01.json`
- 完整 20 条报告：`artifacts/evaluation/m11-ai-campus-report-core-v7-reviewed-20-2026-09-01.json`
- 成功样本报告：`artifacts/evaluation/m11-ai-campus-report-core-v7-reviewed-20-successful-only-2026-09-01.json`
- v4 同标签口径报告：`artifacts/evaluation/m11-ai-campus-report-core-v4-rebased-v7-reviewed-20-2026-09-01.json`
