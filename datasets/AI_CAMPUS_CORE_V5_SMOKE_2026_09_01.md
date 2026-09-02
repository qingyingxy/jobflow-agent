# AI Campus Core Parser v5 Smoke Test

日期：2026-09-01

## 标签状态

- 范围：技能差异最大的 20 条岗位。
- 标签版本：`ai-campus-label-overrides-v5-skill-schema-reviewed-2026-09-01`。
- 人工确认：A1-A8 全部采用建议方案。
- 证据可达性：20 条中没有无法在原文定位的技能标签。
- `review_required_count`：0。

## 20 条基线

Core Parser v4、prompt v2 在 20 条 reviewed 标签上的主指标如下。主指标不包含
`skill_mentions`，因为该字段用于追溯原文技术提及，当前标签并非穷举式标注。

| 字段 | Precision | Recall | F1 |
| --- | ---: | ---: | ---: |
| `job_type` | 1.000 | 1.000 | 1.000 |
| `locations` | 1.000 | 1.000 | 1.000 |
| `required_skills` | 0.573 | 0.357 | 0.440 |
| `required_skill_groups` | 0.340 | 0.571 | 0.427 |
| `preferred_skills` | 0.707 | 0.656 | 0.680 |

主指标 Macro-F1：`0.709`。20/20 最终调用成功，字段级证据过滤产生 26 条
`unsupported_field_value` warning，unsupported claim rate 为 0。

技能组按 `any_of + allow_other` 计分，忽略仅用于展示的 `name`。例如“VLA 架构”
和“端到端 VLA 架构”若选项及开放性相同，应视为同一个技能组。

## v5 目标复测

Core Parser v5、prompt v3 只复测 `campus-ai-103`、`campus-ai-105`、
`campus-ai-152`，未重跑 20 条或 154 条。

| 字段 | v4 F1 | v5 F1 |
| --- | ---: | ---: |
| `job_type` | 1.000 | 1.000 |
| `locations` | 1.000 | 1.000 |
| `required_skills` | 0.333 | 0.439 |
| `required_skill_groups` | 0.609 | 0.500 |
| `preferred_skills` | 0.588 | 0.780 |
| Macro-F1 | 0.709 | 0.744 |

v5 必备技能 Precision 从 `0.310` 提升到 `0.727`，加分项召回从 `0.417`
提升到 `0.733`。三条均调用成功，unsupported claim rate 为 0。

## 结论

v5 已明显减少“加分项误标成必备技能”，但 `any_of` 召回有所下降，普通枚举与
备选关系仍需要进一步约束。当前适合继续做 3-5 条针对性回归，不建议直接运行完整
154 条模型评测。
