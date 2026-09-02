# AI Campus Core Parser v10 召回定向测试

日期：2026-09-01

## 范围

- 样本：`campus-ai-092`、`100`、`103`、`105`、`106`。
- 标签：v5.1 人工复核标签。
- Parser：`jd-core-parser-v10`。
- Prompt：`jd-core-parser-prompt-v7`，本轮未修改。
- 模型：`deepseek-v4-flash`。
- 只运行 Core Parser，没有运行 20 条或 154 条评测。

## 正式结果

| 指标 | v9 | v10 | 变化 |
| --- | ---: | ---: | ---: |
| Macro-F1 | 0.8988 | 0.9560 | +0.0572 |
| required_skills Precision | 0.6327 | 0.7447 | +0.1120 |
| required_skills Recall | 0.8378 | 0.9459 | +0.1081 |
| required_skills F1 | 0.7209 | 0.8333 | +0.1124 |
| required_skill_groups Recall | 0.7500 | 1.0000 | +0.2500 |
| required_skill_groups F1 | 0.8571 | 1.0000 | +0.1429 |
| preferred_skills Precision | 0.9423 | 0.9298 | -0.0125 |
| preferred_skills Recall | 0.8909 | 0.9636 | +0.0727 |
| preferred_skills F1 | 0.9159 | 0.9464 | +0.0305 |

`job_type` 和 `locations` F1 均保持 1.0000。5 条最终全部成功，
`unsupported_claim_rate` 为 0。`campus-ai-106` 首次达到 240 秒上限，随后只重试
该条并成功；最终报告不包含 prediction failure。

## 修复内容

- 恢复强制语气明确但被模型漏掉的编程语言、软件工程、编程能力、模型评测和实验结果分析。
- 将 `重建-生成-评测` 链路折叠为 `模型评测`，并将 baseline、control group、变量控制、指标对比降为 mention。
- 将 `conda/docker` 和“触觉感知或接触操作”恢复为明确的 `any_of` 组。
- 规范 `真机部署` 为 `机器人部署`。
- 只在模型已识别至少一个加分技能时，窄范围恢复 Agent 项目/评测/上线、世界模型复现、World Model 和 VLA；不扫描恢复所有加分段枚举。

## 离线隔离验证

在正式模型运行前，将 v10 确定性规范化重放到相同 5 条 v9 输出上，Macro-F1
为 0.9769，三类技能字段 Recall 均为 1.0000。正式结果略低，说明剩余差异包含
模型生成波动，而不是本轮规则未生效。

正式运行的新差异包括 092 的 `模型训练`、100 的 `编程基础` 漏抽，以及 100
的 `前后端开发/后端开发`、103 的 `计算机视觉` 字段边界变化。当前不继续针对
单次随机输出增加规则。下一步应先扩大到 20 条人工复核集，观察这些差异是否
重复出现，再决定优化 Parser 或调整标签粒度。

## 产物

- Manifest：`artifacts/evaluation/m11-ai-campus-manifest-core-v9-recall-5-2026-09-01.json`
- Predictions：`artifacts/evaluation/m11-ai-campus-predictions-core-v10-recall-5-2026-09-01.json`
- Report：`artifacts/evaluation/m11-ai-campus-report-core-v10-recall-5-2026-09-01.json`
