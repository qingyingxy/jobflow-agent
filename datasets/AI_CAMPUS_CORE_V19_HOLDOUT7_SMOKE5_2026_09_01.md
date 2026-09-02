# Core Parser v19 Holdout-7 Smoke（2026-09-01）

## 目的

在新的未见样本上验证以下通用修复：

- `any_of` 固定数组协议能否继续避免结构失败；
- 归一化后不足两个唯一选项的伪技能组是否消失；
- Prompt 对必备、优先、弱提及和示例的边界是否改善。

## 公平性约束

- 严格源集包含 154 条样本。
- 排除历史人工复核覆盖和 holdout-v1 至 holdout-v6 中出现的 98 条样本，
  剩余未见候选池为 56 条。
- 使用固定种子 `holdout-v7-smoke5` 按 SHA-256 排名抽取 5 条，每家公司
  最多 1 条：`campus-ai-093`、`104`、`140`、`137`、`040`。
- 模型调用前仅依据原始 JD 和既定标注规则完成人工复核，并冻结 v13 override；
  manifest 的 `review_required_count=0`。
- 预测生成后未修改冻结标签。

## 运行配置

- 模型：`deepseek-v4-flash`
- Parser：`jd-core-parser-v19`
- Prompt：`jd-core-parser-prompt-v12`
- Schema：`core-job-fields-v5`
- 并发：1
- 单条外层超时：240 秒
- 样本数：5

## 调用结果

- 成功：5/5（100%）
- `structured_output_invalid`：0
- 超时：0
- Warning：0
- 总生成耗时：667.942 秒

连续两批新的未见 smoke 共 8 条均未出现结构失败。该结果支持保留固定数组协议，
但样本量仍不足以证明结构错误率已经永久归零。

## 严格指标

| 字段 | Precision | Recall | F1 | Exact Match |
|---|---:|---:|---:|---:|
| `job_type` | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| `locations` | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| `required_skills` | 0.7632 | 0.5686 | 0.6517 | 0.0000 |
| `required_skill_groups` | 0.0000 | 0.0000 | 0.0000 | 0.6000 |
| `preferred_skills` | 0.6129 | 0.5938 | 0.6032 | 0.0000 |

Macro-F1：`0.6510`。

## 修复目标检查

- **结构协议通过小样本验证**：5 条均成功，未出现非数组 `any_of`。
- **单选项伪组未复现**：输出的两个技能组分别有 7 个和 2 个归一化后唯一
  选项，没有出现归一化后仅剩一个选项的组。
- **技能组语义仍不稳定**：`campus-ai-040` 将嵌套的前端/客户端/服务端
  选择关系错误展开为跨层级选项；`campus-ai-104` 将近义的 VLA/具身大模型
  误建为必备备选组，因此技能组 F1 为 0。
- **优先范围仍需收紧**：`campus-ai-140` 将弱了解的 LLM/VLM 错误纳入
  preferred，说明“末尾优先支配整句”在复杂并列句上可能作用过宽。
- **召回仍是主要问题**：`campus-ai-137` 漏掉 PID、MPC、阻抗控制、力控制和
  轨迹规划等受强要求支配的并列方法；多个样本也漏掉工程化能力。

## 逐条诊断

- `campus-ai-040`：岗位类型、地点和大部分基础技能正确；正确识别全栈/多端为
  优先，但嵌套 any-of 跨层级展开，并漏掉工程化实践、系统开发和性能优化。
- `campus-ai-093`：分布式训练与系统基础召回较好；将括号示例 DDP/FSDP
  提升为必备，将 DeepSpeed 等示例框架直接提升为优先，粒度与标签不一致。
- `campus-ai-104`：具身后训练主链路和大部分加分项正确；VLA/具身大模型被误建
  为近义备选组，且未稳定保留驻场调试和项目交付的上位能力。
- `campus-ai-137`：正确识别控制理论、运动学/动力学、语言、Linux 和四个优先项；
  受同一强条款约束的具体控制方法被路由到 mentions，造成必备召回不足。
- `campus-ai-140`：岗位类型、地点和数据分析正确；Prompt Engineering 与 Agent
  产品设计正确进入 preferred，但弱了解的 LLM/VLM 被优先信号过度覆盖。

## 结论

v19 已将当前主要风险从结构协议失败转移到可诊断的语义分类问题。下一步不应再改
`any_of` 数组 schema，也不应立即跑完整 154 条；应先用本轮暴露的通用句法类型完善
最小条款切分和嵌套备选关系，再通过本地契约测试验证，之后另抽少量未见样本复测。

## 产物

- 选择清单：`datasets/ai_campus_holdout_5_v7_selection_2026_09_01.json`
- 冻结标签：`datasets/ai_campus_label_overrides_v13_holdout7_smoke5_frozen.json`
- Manifest：
  `artifacts/evaluation/m11-ai-campus-manifest-core-v19-holdout7-smoke5-frozen-v13-2026-09-01.json`
- Predictions：
  `artifacts/evaluation/m11-ai-campus-predictions-core-v19-holdout7-smoke5-new-api-v13-2026-09-01.json`
- Report：
  `artifacts/evaluation/m11-ai-campus-report-core-v19-holdout7-smoke5-new-api-v13-2026-09-01.json`
