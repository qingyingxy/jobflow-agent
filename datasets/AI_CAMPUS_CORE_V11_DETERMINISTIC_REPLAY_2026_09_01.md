# AI Campus Core Parser v11 Deterministic Replay

日期：2026-09-01

状态：已完成。复用 v10 的 20/20 成功模型输出，仅离线重放 v11
确定性规范化与原文校验；本轮没有模型调用，也没有修改人工标签。

## 范围

- 样本：v5.1 人工复核的 20 条 JD。
- 字段：`job_type`、`locations`、`required_skills`、
  `required_skill_groups`、`preferred_skills`。
- Parser：`jd-core-parser-v11`。
- Prompt：仍为 `jd-core-parser-prompt-v7`。
- 模型底稿：`deepseek-v4-flash` 的 v10 Reviewed-20 输出。
- 只允许由岗位原文直接证明的别名、复合词、强要求和备选组规则。

## 结果

20 条中只有以下 4 条字段发生变化，其余 16 条完全不变：

- `campus-ai-077`：统一 `MDP`、机器人运动学/动力学、数值计算；
  将科学计算库展开为 `Eigen`/`NumPy`，恢复明确加分经验。
- `campus-ai-105`：恢复机器人算法四选一组、机器人部署、问题定位及
  明确加分技能。
- `campus-ai-153`：统一 `LLM Agent`、`TAMP`，恢复 `Agent Workflow`、
  `具身Agent` 和两个原文明示的备选组。
- `campus-ai-159`：统一低延迟推理、分布式架构，恢复强化学习强要求、
  系统编程及 Agent 系统经历三选一组。

`campus-ai-109` 没有变化。其剩余差异涉及是否把 Context Engineering、
Planning、Memory、RAG、Skill 等能力提升为必备技能，仍保留给人工判断。

| 字段 | v10 F1 | v11 重放 F1 | 变化 |
| --- | ---: | ---: | ---: |
| 岗位类型 | 1.0000 | 1.0000 | 0.0000 |
| 地点 | 1.0000 | 1.0000 | 0.0000 |
| 必备技能 | 0.7205 | 0.8218 | +0.1013 |
| `required_skill_groups` | 0.7083 | 0.8750 | +0.1667 |
| 加分技能 | 0.8739 | 0.8971 | +0.0232 |
| Macro-F1 | 0.8606 | 0.9188 | +0.0582 |

v11 重放细分结果：

| 字段 | Precision | Recall | F1 | Exact Match |
| --- | ---: | ---: | ---: | ---: |
| 必备技能 | 0.7771 | 0.8718 | 0.8218 | 7/20 |
| `required_skill_groups` | 0.9130 | 0.8400 | 0.8750 | 17/20 |
| 加分技能 | 0.9237 | 0.8720 | 0.8971 | 11/20 |

## 验证

- 定向及 Parser 相关测试：51 passed。
- Ruff：通过。
- 预测成功率：100%。
- `unsupported_claim_rate`：0。
- 原文重新校验后保留 2 条删除型 warning，不影响主评测字段。

## 产物

- Manifest：`artifacts/evaluation/m11-ai-campus-manifest-core-v11-deterministic-reviewed-20-2026-09-01.json`
- Predictions：`artifacts/evaluation/m11-ai-campus-predictions-core-v11-deterministic-replay-reviewed-20-2026-09-01.json`
- Report：`artifacts/evaluation/m11-ai-campus-report-core-v11-deterministic-reviewed-20-2026-09-01.json`
- v10 基线：`artifacts/evaluation/m11-ai-campus-report-core-v10-reviewed-20-2026-09-01.json`
