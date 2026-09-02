# AI Campus Core Parser v15 Holdout-3 Smoke-5

日期：2026-09-01

状态：已完成第三批未见候选池的 5 条 smoke 评测。结果未达到扩展到 20 条或
完整 154 条的门槛，本批转为诊断集。

## 评测隔离

- 严格源集包含 154 条样本。
- 排除历史 smoke、targeted、recall、Reviewed 的 30 条，以及 holdout-v1、
  holdout-v2 各 30 条诊断样本，剩余未见候选池为 64 条。
- 使用固定种子 `holdout-v3-smoke-5` 按 SHA-256 排名抽取 5 条，每家公司最多
  1 条，覆盖沐瞳科技、自变量机器人、它石智航、普源精电和字节跳动。
- 在模型调用前，仅依据原始 JD 和既定规则完成人工标签复核并冻结 v9 override；
  冻结 manifest 的 `review_required_count=0`。
- 标签冻结后，使用 `deepseek-v4-flash`、`jd-core-parser-prompt-v8` 和
  `jd-core-parser-v15` 发起 5 次全新 Core Parser API 调用。
- 5/5 预测成功，无超时；总生成耗时约 234 秒。预测后未修改冻结标签。

## 严格指标

| 字段 | Precision | Recall | F1 | Exact Match | TP / FP / FN |
| --- | ---: | ---: | ---: | ---: | ---: |
| `job_type` | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 5 / 0 / 0 |
| `locations` | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 6 / 0 / 0 |
| `required_skills` | 0.9200 | 0.7419 | 0.8214 | 0.2000 | 23 / 2 / 8 |
| `required_skill_groups` | 0.7500 | 1.0000 | 0.8571 | 0.8000 | 3 / 1 / 0 |
| `preferred_skills` | 0.6538 | 0.5000 | 0.5667 | 0.0000 | 17 / 9 / 17 |
| **Macro-F1** |  |  | **0.8490** |  |  |

门槛结果：

- Macro-F1 `0.8490 < 0.90`，未通过。
- Required-skills F1 `0.8214 < 0.85`，未通过。
- `required_skill_groups` 的三条真实组全部召回，但存在一条弱要求误建组。
- `preferred_skills` 召回率仍只有 `0.5000`，不满足扩样条件。

## 逐条诊断

- `campus-ai-025`：语言三选一完全正确；漏掉必备的 Agent 框架、Agent 项目，
  并漏掉开源贡献优先项。
- `campus-ai-072`：语言组和 Prompt Engineering/RAG 组均正确；漏掉数学建模、
  AI 原生工作流，AI 应用原型开发存在粒度差异。
- `campus-ai-086`：长加分段召回了 LangChain、AutoGen、MCP、RAG、Prompt
  Engineering、自动化工作流和观测分析类能力，但仍漏掉多智能体系统、
  人机协作、智能研发工具等；同时存在 gRPC/gRPC API、上下文工程、Token 空格和
  可观测性后缀等本体差异。
- `campus-ai-107`：正确保持 required 为空，没有把职责段的预训练、量化、蒸馏
  提升为必备；漏掉任职要求中的开源贡献优先项。
- `campus-ai-136`：必备基础技能基本正确，但将 `C/C++` 拆出额外的 C，并把
  “了解 ROS/ROS2”错误恢复为必备组；优先项目经历还存在上位技术与项目经历的
  粒度差异。

## 决策

本批不扩展到 20 条，也不运行完整 154 条。后续只做通用修复：

1. 所有技能组创建和恢复入口统一执行强弱要求检查，阻止“了解 ROS/ROS2”建必备组。
2. 审计可证明的同义本体，如 gRPC/gRPC API、Context Engineering/上下文工程、
   Token 空格和可观测性后缀；不使用模糊字符串匹配。
3. 改善长加分段和开源贡献条款的完整召回，同时保持职责段技术不提升为必备。
4. 修复后从剩余 59 条未见样本重新抽取新 smoke；本批 5 条只用于诊断，不能再
   作为最终 holdout。

## 产物

- 抽样清单：`datasets/ai_campus_holdout_5_v3_selection_2026_09_01.json`
- 冻结标签：`datasets/ai_campus_label_overrides_v9_holdout3_smoke5_frozen.json`
- 冻结 manifest：
  `artifacts/evaluation/m11-ai-campus-manifest-core-v15-holdout3-smoke5-frozen-v9-2026-09-01.json`
- 新 API predictions：
  `artifacts/evaluation/m11-ai-campus-predictions-core-v15-holdout3-smoke5-new-api-v9-2026-09-01.json`
- 机器可读报告：
  `artifacts/evaluation/m11-ai-campus-report-core-v15-holdout3-smoke5-new-api-v9-2026-09-01.json`
