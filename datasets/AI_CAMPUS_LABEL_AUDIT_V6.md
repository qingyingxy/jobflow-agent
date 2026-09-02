# AI Campus v6 争议标签复核

日期：2026-09-01

状态：已完成 20 条 Reviewed 集合的剩余差异复核。本轮只修改标签并离线重算，
没有调用模型，也没有运行完整 154 条。

## 字段口径

- `required_skills`：候选人必须同时满足的直接技术要求，每项都独立计分。
- `required_skill_groups`：备选硬门槛，`any_of` 中满足任意一项即可。
- `preferred_skills`：原文明示“优先、加分”的技术能力，不作为硬门槛。
- `skill_mentions`：正文提到但不是独立硬门槛的方向、示例和子概念。

标签复核只依据岗位原文。prediction 命中了某个词，不构成修改标签的理由。

## 修订结果

| 样本 | 修订 | 依据 |
| --- | --- | --- |
| `campus-ai-089` | 删除直接必备“模型训练” | “大规模模型训练或分布式训练”已经由 `any_of` 组完整表达，重复上位标签会双重计分。 |
| `campus-ai-092` | 加分技能补 `log2world` | 加分项明确写有 `log2world、sim-to-real` 实战经验。 |
| `campus-ai-103` | 必备补代码组织、代码调试、问题定位、系统集成 | 四项均位于职位要求的明确能力条款；计算机视觉、NLP、LLM、机器人仍只作相关方向提及。 |
| `campus-ai-108` | 必备补完整开发、源码二开、部署和代码治理能力 | 职位要求第 4-7 条使用“具备、熟悉、能够”直接约束这些能力。 |
| `campus-ai-109` | `LLM + Agent` 合并为 `LLM Agent`；`Agent Evaluation` 统一为 `Agent评测`；补 `Bad Case 定位` | 与 `campus-ai-153` 使用同一复合词口径，并保留原文“熟悉”的硬要求。 |
| `campus-ai-152` | 必备补动作空间设计、训练目标、推理机制、连续动作空间训练经验 | 原文要求理解 VLA 架构机制并具备连续动作空间训练经验。 |

`campus-ai-061/073/077/087/088/100/106` 复核后维持 v5 标签，剩余差异属于
Parser 分组、同义词或必备/加分分类问题。

## 指标影响

使用同一份 v11 prediction 离线重算：

| 字段 | v5.1 标签 F1 | v6 标签 F1 | 变化 |
| --- | ---: | ---: | ---: |
| 岗位类型 | 1.0000 | 1.0000 | 0.0000 |
| 地点 | 1.0000 | 1.0000 | 0.0000 |
| 必备技能 | 0.8218 | 0.8728 | +0.0511 |
| `required_skill_groups` | 0.8750 | 0.8750 | 0.0000 |
| 加分技能 | 0.8971 | 0.9016 | +0.0045 |
| Macro-F1 | 0.9188 | 0.9299 | +0.0111 |

`campus-ai-109` 单条 Macro-F1 从 `0.8353` 降至 `0.8090`。这是预期结果：
规范标签后，当前 Parser 对 `LLM Agent`、`Agent Runtime`、`Agent评测`、
Context Engineering、Planning、Memory、RAG、Skill 等强要求的漏抽更清晰。

## 当前结论

- v6 的 20 条 manifest 已无待复核标记，`review_required=0`。
- 当前 Macro-F1 为 `0.9299`，但不能据此宣称 Parser 已解决全部问题。
- 下一轮应优先针对 `109` 的必备技能召回，以及 `061/088/089` 的复杂技能组；
  继续使用 3-5 条定向测试，不直接运行完整 154 条。

## 产物

- 标签增量：`datasets/ai_campus_label_overrides_v6_disputed_audit.json`
- Manifest：`artifacts/evaluation/m11-ai-campus-manifest-core-v11-label-audit-v6-reviewed-20-2026-09-01.json`
- Review：`artifacts/evaluation/m11-ai-campus-review-core-v11-label-audit-v6-reviewed-20-2026-09-01.json`
- Report：`artifacts/evaluation/m11-ai-campus-report-core-v11-label-audit-v6-reviewed-20-2026-09-01.json`
- Predictions：沿用 `artifacts/evaluation/m11-ai-campus-predictions-core-v11-deterministic-replay-reviewed-20-2026-09-01.json`
