# AI Campus Core Parser v8 定向 Smoke Test

日期：2026-09-01

## 范围

- 样本：`campus-ai-092`、`100`、`103`、`105`、`106`。
- 标签：v5.1 人工复核标签；统一 `3D视觉`、`Agent`、`Tool Calling` 等名称。
- Parser：`jd-core-parser-v8`。
- Prompt：`jd-core-parser-prompt-v6`。
- 模型：`deepseek-v4-flash`。
- 只运行 Core Parser，没有运行完整 20 条或 154 条评测。

## 结果

旧 v7 基线使用同一份 v5.1 标签重新计算，避免把标签命名变化算作 Parser 提升。

| 指标 | v7 基线 | v8 | 变化 |
| --- | ---: | ---: | ---: |
| Macro-F1 | 0.7401 | 0.8600 | +0.1199 |
| required_skills F1 | 0.6087 | 0.6984 | +0.0897 |
| required_skill_groups F1 | 0.5882 | 0.8571 | +0.2689 |
| preferred_skills F1 | 0.5036 | 0.7447 | +0.2411 |
| preferred_skills Precision | 0.4167 | 0.8974 | +0.4808 |

`job_type` 和 `locations` F1 均为 1.0000。5 条最终全部成功；103 首次达到
180 秒上限，随后只重试该条并成功。最终评测没有 prediction failure，
`unsupported_claim_rate` 为 0。

## 结论

本轮已经显著缓解 `preferred_skills` 过度扩张，并修复“研究或工程经验”中的
“或”误建 `any_of`、低强度要求误标为必备、复合技能重复抽取等问题。

目前主要瓶颈从 Precision 转为 Recall：092 的复现/贡献类加分能力，100 和 103
的部分直接必备工程能力，以及 106 的部分加分技术名仍有漏抽。下一步应继续用
3 至 5 条定向样本优化召回，稳定后再重跑完整 20 条人工复核集；暂不运行 154 条。

## 产物

- Manifest：`artifacts/evaluation/m11-ai-campus-manifest-core-v8-targeted-5-2026-09-01.json`
- Predictions：`artifacts/evaluation/m11-ai-campus-predictions-core-v8-targeted-5-2026-09-01.json`
- Report：`artifacts/evaluation/m11-ai-campus-report-core-v8-targeted-5-2026-09-01.json`
