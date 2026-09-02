# AI Campus Core Parser v10 Reviewed-20 Evaluation

日期：2026-09-01

状态：已完成，20/20 预测成功。

## 范围

- 样本：v5.1 人工复核的 20 条 JD。
- 字段：`job_type`、`locations`、`required_skills`、`required_skill_groups`、`preferred_skills`。
- Parser：`jd-core-parser-v10`。
- Prompt：`jd-core-parser-prompt-v7`。
- 模型：`deepseek-v4-flash`。
- 新 manifest 已与当前人工覆盖逐条校验，20 条技能标签差异数为 0。

## 调用结果

首轮成功 16/20；`campus-ai-156`、`158`、`159`、`165` 因模型账户额度不足
返回 HTTP 402。额度恢复后从 checkpoint 只重试这 4 条，最终 20/20 全部成功，
没有重复调用其余 16 条。最终 prediction failure 为 0，`unsupported_claim_rate` 为 0。

## 指标

v7 基线使用同一份最新 v5.1 标签重新计算，保证比较口径一致。

| 字段 | v7 F1 | v10 F1 | 变化 |
| --- | ---: | ---: | ---: |
| 岗位类型 | 1.0000 | 1.0000 | 0.0000 |
| 地点 | 1.0000 | 1.0000 | 0.0000 |
| 必备技能 | 0.6395 | 0.7205 | +0.0810 |
| `required_skill_groups` | 0.6939 | 0.7083 | +0.0145 |
| 加分技能 | 0.6552 | 0.8739 | +0.2188 |
| Macro-F1 | 0.7977 | 0.8606 | +0.0629 |

v10 细分结果：

| 字段 | Precision | Recall | F1 | Exact Match |
| --- | ---: | ---: | ---: | ---: |
| 必备技能 | 0.6988 | 0.7436 | 0.7205 | 4/20 |
| `required_skill_groups` | 0.7391 | 0.6800 | 0.7083 | 14/20 |
| 加分技能 | 0.9204 | 0.8320 | 0.8739 | 9/20 |

相比 v7，必备技能 Recall 从 0.6026 提高到 0.7436；加分技能 Precision 从
0.5758 提高到 0.9204，说明加分项过度恢复已明显收敛。技能组 Precision 从
0.7083 提高到 0.7391，但 Recall 仍为 0.6800，是下一轮的主要瓶颈。

## 剩余误差

- `campus-ai-077`：`MDP/MDP建模`、`运动学/机器人运动学`、`数值计算/数值计算方法`等同义粒度不一致。
- `campus-ai-109`：Agent Runtime、Planning、Memory、Skill 等英文能力漏抽，云原生和向量数据库标签粒度不一致。
- `campus-ai-159`：MARL、Meta-RL、Self-play 等强化学习能力漏抽，Agentic RL 技能组边界仍不准确。
- `campus-ai-103/105/152/153`：仍有必备与加分字段边界、上位能力与具体能力重复、复杂 `any_of` 组命名差异。

不应直接针对单条输出继续堆叠规则。下一步应优先统一同义标签映射，并选择
`077`、`109`、`159` 加 2 条复杂技能组样本做新一轮定向优化。

## 产物

- Manifest：`artifacts/evaluation/m11-ai-campus-manifest-core-v10-reviewed-20-2026-09-01.json`
- Review：`artifacts/evaluation/m11-ai-campus-review-core-v10-reviewed-20-2026-09-01.json`
- Predictions / checkpoint：`artifacts/evaluation/m11-ai-campus-predictions-core-v10-reviewed-20-2026-09-01.json`
- 最终报告：`artifacts/evaluation/m11-ai-campus-report-core-v10-reviewed-20-2026-09-01.json`
- v7 最新标签重算报告：`artifacts/evaluation/m11-ai-campus-report-core-v7-rebased-v10-reviewed-20-2026-09-01.json`
