# AI Campus Core Parser v12 Generic Strong-Requirement Replay

日期：2026-09-01

状态：已完成。复用 v11 的 20/20 成功模型输出，仅离线重放 v12
确定性规范化；没有模型调用，没有修改 v6 人工标签，也没有运行完整 154 条。

## 规则

- API 输出仍是初始语义判断，本地规范化负责稳定字段边界和标准术语。
- `必须`、`掌握`、`熟悉`、`具备`、`精通`、无弱化修饰的 `理解`
  所统领的已知技能，可以从 `skill_mentions` 提升为 `required_skills`。
- `了解`、`基础认知`、`有一定理解`、`优先`、`加分`、
  `包括但不限于` 不触发必备技能提升。
- `any_of` 选项、括号或“如/例如”后的示例、已折叠到上位类别的具体框架
  不触发提升。
- 原文兜底恢复只覆盖语义完整且不歧义的复合术语，不按 case ID、公司或
  岗位名称写死。
- 标准化 `LLM Agent`、`Agent Runtime`、`Agent评测`、`Bad Case 定位`、
  `Planning`、`Memory`、`Skill` 等 Agent 术语，并保护 `Task Planning`、
  `Memory Retrieval`、`Skill Selection`、`Skill Ops` 等更具体名称。

## 变化

20 条中只有 2 条主评测字段发生变化，其余 18 条不变：

- `campus-ai-073`：将“熟悉主流大模型的 API 调用和提示词工程”中的
  `Prompt Engineering` 从 mention 提升为必备；括号内 GPT、Gemini、Qwen
  等示例保持为 mention。
- `campus-ai-109`：合并 `LLM` + `Agent` 为 `LLM Agent`，恢复
  `Agent Runtime`、`Agent评测`，并将强要求统领的 Context Engineering、
  Tool Calling、Planning、Memory、RAG、Skill 提升为必备；加分项统一为
  `向量数据库`、`云原生开发`，恢复 `生产级Agent平台`。

`campus-ai-109` 的 `required_skills` 和 `preferred_skills` 均与 v6 人工标签
完全一致。

## 指标

| 字段 | v11 + v6 F1 | v12 + v6 F1 | 变化 |
| --- | ---: | ---: | ---: |
| 岗位类型 | 1.0000 | 1.0000 | 0.0000 |
| 地点 | 1.0000 | 1.0000 | 0.0000 |
| 必备技能 | 0.8728 | 0.9096 | +0.0368 |
| `required_skill_groups` | 0.8750 | 0.8750 | 0.0000 |
| 加分技能 | 0.9016 | 0.9224 | +0.0208 |
| Macro-F1 | 0.9299 | 0.9414 | +0.0115 |

v12 细分：必备技能 Precision `0.8798`、Recall `0.9415`；加分技能
Precision `0.9496`、Recall `0.8968`；`unsupported_claim_rate=0`。

## 版本与产物

- Core Parser：`jd-core-parser-v12`。
- Staged Parser：`jd-staged-parser-v12`。
- Prompt：仍为 `jd-core-parser-prompt-v7`。
- Manifest：`artifacts/evaluation/m11-ai-campus-manifest-core-v11-label-audit-v6-reviewed-20-2026-09-01.json`。
- Predictions：`artifacts/evaluation/m11-ai-campus-predictions-core-v12-generic-strong-replay-reviewed-20-2026-09-01.json`。
- Report：`artifacts/evaluation/m11-ai-campus-report-core-v12-label-audit-v6-reviewed-20-2026-09-01.json`。
