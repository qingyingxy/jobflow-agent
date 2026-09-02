# AI Campus Core Parser v16 Holdout-4 Smoke-5

日期：2026-09-01

状态：已完成第四批未见候选池的 5 条 API smoke。新条款协议被真实模型接受，
但 2/5 样本超时，成功样本指标也未达到扩样门槛，本批转为诊断集。

## 评测隔离

- 严格源集包含 154 条样本。
- 排除历史使用的 30 条、holdout-v1 和 holdout-v2 各 30 条、holdout-v3
  的 5 条，剩余未见候选池为 59 条。
- 使用固定种子 `holdout-v4-smoke-5` 按 SHA-256 排名抽取 5 条，每家公司
  最多 1 条，覆盖百度、字节跳动、蔚来、影石创新和它石智航。
- 在模型调用前，仅依据原始 JD 和既定规则完成人工标签复核并冻结 v10
  override；冻结 manifest 的 `review_required_count=0`。
- 标签冻结后，使用 `deepseek-v4-flash`、`jd-core-parser-prompt-v9`、
  `jd-core-parser-v16` 和 `core-job-fields-v3` 发起 5 次全新 Core Parser 调用。

## 调用结果

- 成功：`campus-ai-018`、`campus-ai-057`、`campus-ai-068`。
- 超时：`campus-ai-065`、`campus-ai-101`，均达到单条 240 秒上限。
- 总生成耗时约 926 秒；成功率为 60%。未重试超时条目。

## 严格指标

全 5 条（失败预测按空字段计入）：

| 字段 | Precision | Recall | F1 | Exact Match | TP / FP / FN |
| --- | ---: | ---: | ---: | ---: | ---: |
| `job_type` | 1.0000 | 0.6000 | 0.7500 | 0.6000 | 3 / 0 / 2 |
| `locations` | 1.0000 | 0.3333 | 0.5000 | 0.4000 | 2 / 0 / 4 |
| `required_skills` | 0.7692 | 0.2273 | 0.3509 | 0.2000 | 10 / 3 / 34 |
| `required_skill_groups` | 0.0000 | 0.0000 | 0.0000 | 0.6000 | 0 / 1 / 2 |
| `preferred_skills` | 0.7143 | 0.3571 | 0.4762 | 0.4000 | 5 / 2 / 9 |
| **Macro-F1** |  |  | **0.4154** |  |  |

只看 3 条成功预测：

| 字段 | Precision | Recall | F1 | Exact Match | TP / FP / FN |
| --- | ---: | ---: | ---: | ---: | ---: |
| `job_type` | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 3 / 0 / 0 |
| `locations` | 1.0000 | 0.6667 | 0.8000 | 0.6667 | 2 / 0 / 1 |
| `required_skills` | 0.7692 | 0.6667 | 0.7143 | 0.3333 | 10 / 3 / 5 |
| `required_skill_groups` | 0.0000 | 0.0000 | 0.0000 | 0.6667 | 0 / 1 / 1 |
| `preferred_skills` | 0.7143 | 0.8333 | 0.7692 | 0.3333 | 5 / 2 / 1 |
| **Macro-F1** |  |  | **0.6567** |  |  |

## 逐条诊断

- `campus-ai-018`：四项必备技能完全正确，三个优先研究方向全部召回；额外把
  学术论文发表当成优先技能。地点的“上海市/上海”由指标正常归一。
- `campus-ai-057`：正确排除了兴趣条款中的 Agent 和 AI 基础设施，但漏掉工作
  地点北京、编程能力以及软件工程括号内的系统设计、API 开发和代码质量控制；
  数据结构与基础算法也与冻结标签的复合粒度不一致。
- `campus-ai-068`：正确识别系统基础的开放 `any_of` 关系和三个优先方向；差异
  集中在 `C/C++`、`CPU体系结构/CPU架构`、`加固/软件加固` 等共享本体。
- `campus-ai-065`、`campus-ai-101`：模型调用超时，没有可用于字段诊断的输出。

## 决策

本批不扩展到更多样本，也不运行完整 154 条。保留条款级分类方向，但下一版必须：

1. 缩减模型输出体积，避免为职责和所有示例生成完整条款对象。
2. 从显式“工作地点”字段确定性提取地点，模型只处理歧义地点。
3. 在共享本体统一 `C/C++`、CPU 架构和软件加固等可证明别名。
4. 明确排除论文、竞赛和兴趣，并区分“如/例如”的示例与“包括”的必备子项。
5. 完成本地回归后再抽新的未见 smoke；本批 5 条不能再作为最终 holdout。

## 产物

- 抽样清单：`datasets/ai_campus_holdout_5_v4_selection_2026_09_01.json`
- 冻结标签：`datasets/ai_campus_label_overrides_v10_holdout4_smoke5_frozen.json`
- 冻结 manifest：
  `artifacts/evaluation/m11-ai-campus-manifest-core-v16-holdout4-smoke5-frozen-v10-2026-09-01.json`
- API predictions：
  `artifacts/evaluation/m11-ai-campus-predictions-core-v16-holdout4-smoke5-new-api-v10-2026-09-01.json`
- 全 5 条报告：
  `artifacts/evaluation/m11-ai-campus-report-core-v16-holdout4-smoke5-new-api-v10-2026-09-01.json`
- 成功样本报告：
  `artifacts/evaluation/m11-ai-campus-report-core-v16-holdout4-smoke5-successful-only-v10-2026-09-01.json`
