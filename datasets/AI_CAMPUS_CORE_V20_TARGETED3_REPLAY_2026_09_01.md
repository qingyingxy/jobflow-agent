# Core Parser v20 Targeted-3 Replay（2026-09-01）

## 定位

使用 holdout-7 中已经看过的 `campus-ai-040`、`137`、`140`，在相同冻结 v13
标签上比较 v19 与统一 clause schema 的 v20。该结果只用于开发诊断，不是新的
holdout，也不能替代未见样本指标。

## 运行配置

- 模型：`deepseek-v4-flash`
- Parser：`jd-core-parser-v20`
- Prompt：`jd-core-parser-prompt-v13`
- Schema：`core-job-fields-v6`
- 并发：1
- 单条外层超时：240 秒
- 样本数：3

## 调用结果

- 成功：3/3
- `structured_output_invalid`：0
- 超时：0
- Warning：0
- 总生成耗时：329.859 秒

DSV4 接受了统一的 `source_text + strength + relation + skills` clause schema。

## 同口径比较

| 字段 | v19 F1 | v20 F1 | 变化 |
|---|---:|---:|---:|
| `job_type` | 1.0000 | 1.0000 | 0.0000 |
| `locations` | 1.0000 | 1.0000 | 0.0000 |
| `required_skills` | 0.6190 | 0.6939 | +0.0749 |
| `required_skill_groups` | 0.0000 | 0.6667 | +0.6667 |
| `preferred_skills` | 0.6923 | 0.6667 | -0.0256 |
| **Macro-F1** | **0.6623** | **0.8054** | **+0.1431** |

## 行为变化

- `campus-ai-137`：PID、MPC、阻抗控制、力控和轨迹规划由 mentions 正确进入
  required，解决了本次最明确的强条款并列召回问题。
- `campus-ai-140`：LLM/VLM 由 preferred 回到 mentions；Prompt Engineering、
  AI 产品设计和 Agent 保持 preferred，优先作用域得到改善。
- `campus-ai-040`：前端、客户端、服务端被正确建为同层级 any-of，上一次混入
  Flutter、Go 等下层示例的问题消失。

## 剩余问题

- 严格归一化仍未覆盖 `力控/力控制`、`AI 工具/AI工具使用` 等近义词，造成并非
  语义错误的 FP/FN。
- v20 将“系统开发或性能优化经验”按字面建立 any-of；冻结标签却把两项同时列为
  required。按既定“A 或 B 建组”规则，标签本身存在需要后续裁决的不一致。本轮
  保持冻结标签不变。
- `产品实习`、开源贡献、机器人项目等优先经历仍有漏召回。

## 结论

统一 clause schema 已通过真实 DSV4 的定向开发验证，并改善了三个目标句式中的
核心两个语义错误。由于这 3 条已参与 Prompt 设计，`0.8054` 只能作为开发集结果；
下一步应先固定近义词和 any-of 标注规则，再从剩余未见池抽少量样本复测。

## 产物

- Manifest：
  `artifacts/evaluation/m11-ai-campus-manifest-core-v20-targeted3-replay-frozen-v13-2026-09-01.json`
- Predictions：
  `artifacts/evaluation/m11-ai-campus-predictions-core-v20-targeted3-replay-new-api-v13-2026-09-01.json`
- Report：
  `artifacts/evaluation/m11-ai-campus-report-core-v20-targeted3-replay-new-api-v13-2026-09-01.json`
