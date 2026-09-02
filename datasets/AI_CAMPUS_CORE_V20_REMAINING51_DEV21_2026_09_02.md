# Core Parser v20 Remaining-51 Dev-21 评测（2026-09-02）

## 定位

使用固定划分中的 21 条 dev，在 `ai-campus-annotation-guide-v1` 和 v14 人工标签
冻结后首次生成 prediction。标签冻结发生在模型调用之前，本轮未根据 prediction 修改标签，
也未运行或查看 30 条 sealed holdout prediction。

该结果是当前 Parser 的新 dev 指标，不是最终 holdout 指标。

## 运行配置

- 模型：`deepseek-v4-flash`
- Parser：`jd-core-parser-v20`
- Prompt：`jd-core-parser-prompt-v13`
- Schema：`core-job-fields-v6`
- 并发：2
- 单条外层超时：240 秒
- 样本数：21
- 总生成耗时：1,238,012.64 ms（约 20 分 38 秒）

## 调用可靠性

- 成功：21/21
- 失败：0
- 超时：0
- Warning：0
- `structured_output_invalid`：0
- 缺失或额外 prediction：0

统一 clause schema 在这 21 条新 dev 上没有出现运行或结构失败。

## 旧字段指标

| 字段 | Precision | Recall | F1 | 单条完全匹配率 |
| --- | ---: | ---: | ---: | ---: |
| `job_type` | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| `locations` | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| `required_skills` | 0.6952 | 0.6134 | 0.6518 | 0.1429 |
| `required_skill_groups` | 0.8000 | 0.7500 | 0.7742 | 0.8571 |
| `preferred_skills` | 0.7000 | 0.5753 | 0.6316 | 0.3333 |
| **Macro-F1** |  |  | **0.8115** |  |

`0.8115` 与旧 Reviewed-20 的 `0.9299` 不是同一批样本或 Parser 版本；本结果更适合
描述 v20 在新 dev 上的当前效果。

## 拆分指标

### 技能检出

忽略 required/preferred/mention 强度，只判断技术概念是否出现：

| Precision | Recall | F1 | 单条完全匹配率 | TP / FP / FN |
| ---: | ---: | ---: | ---: | ---: |
| 0.6740 | 0.7048 | **0.6890** | 0.0000 | 339 / 164 / 142 |

### 技能强度

`any_of` 组选项不参与强度分类：

| 强度 | Precision | Recall | F1 | 单条完全匹配率 |
| --- | ---: | ---: | ---: | ---: |
| required | 0.6952 | 0.6239 | 0.6577 | 0.1429 |
| preferred | 0.7000 | 0.6000 | 0.6462 | 0.3810 |
| mention | 0.5278 | 0.6230 | 0.5714 | 0.0000 |
| **Macro-F1** |  |  | **0.6251** |  |

### `any_of` 关系

- 标准标签含组：13 条
- 组完全匹配：10 条
- 条件完全匹配率：**0.7692**
- 标准标签不含组：8 条
- 误建组：0 条
- 误建组率：**0.0000**

三条未完全匹配分别是：

- `campus-ai-001`：漏建“至少一种 Agent 框架”的开放组，是真实关系漏召回。
- `campus-ai-008`：模型正确识别两个研究方向的选择关系，但输出 `LLM/穿戴模型方向`，
  标签使用 `LLM方向经验/穿戴模型方向经验`，属于粒度差异。
- `campus-ai-097`：两组关系均正确，仅 `网络/计算机网络` 未归一，属于安全别名差异。

## 困难样本

以下为诊断用的单条技能字段 Macro-F1，空组双方均为空时按 1.0 处理；它不是正式汇总指标：

| 样本 | 技能字段 Macro-F1 | 主要问题 |
| --- | ---: | --- |
| `campus-ai-037` | 0.3333 | 漏编程基础、AI 项目和开源实践；语言组正确。 |
| `campus-ai-015` | 0.4359 | 数据分析、效果分析、训练/数据问题诊断和工业研发经历漏召回。 |
| `campus-ai-097` | 0.5000 | 工程能力漏召回；系统组只有网络别名差异。 |
| `campus-ai-008` | 0.5079 | 研究方向组粒度不同，电生理项目与算法创新部分漏召回。 |
| `campus-ai-128` | 0.5397 | 输出具体 CAE 工具，标签使用上位 CAE 能力；力学能力也存在粒度差异。 |
| `campus-ai-078` | 0.5439 | 论文复现、工程实现和机器人项目漏召回；方向组关系正确。 |
| `campus-ai-147` | 0.5556 | 需求分析、逻辑拆解、文档撰写、产品实习和 AI 项目漏召回。 |

## 主要误差类型

1. **上位类别与具体示例不统一**：例如深度学习框架与 PyTorch/PaddlePaddle、
   CAE 工具与 Ansys/Abaqus、跨平台开发与 KMP/RN。
2. **复合能力命名不统一**：例如编程能力/编程技能、模型微调/微调方法、
   机器人感知/感知、在线离线混部/在离线混部。
3. **项目和工程经历召回偏低**：`Agent项目`、`AI项目`、机器人项目、开源实践、
   工业级研发经历是 preferred 的主要 FN。
4. **直接工程能力漏抽**：工程能力、软件质量、代码审查、数据与训练问题诊断等
   明确能力条款仍容易被忽略。
5. **职责 mentions 噪声较多**：模型会抽取更细的职责动作，导致 mention precision
   只有 0.5278；但 recall 也只有 0.6230，说明不能只靠减少输出解决。

## 结论

- v20 的结构稳定性已经通过 21 条新 dev 验证。
- 岗位类型和地点解析稳定，均为 1.0000。
- `any_of` 关系层表现明显好于技能命名层；13 条正例中只有 1 条明确关系漏召回。
- 当前核心瓶颈是技能粒度、别名和项目经历召回，不是 JSON 结构或地点/岗位类型。
- 下一轮应先处理可泛化的安全别名和上位/示例策略，再在 dev 上做小规模定向重放；
  不应修改 v14 冻结标签，也不应提前运行 sealed holdout。

## 产物

- Manifest：
  `artifacts/evaluation/m11-ai-campus-manifest-core-v20-label-v14-remaining51-dev21-strict-2026-09-02.json`
- Predictions：
  `artifacts/evaluation/m11-ai-campus-predictions-core-v20-remaining51-dev21-new-api-v14-2026-09-02.json`
- Checkpoint：
  `artifacts/evaluation/m11-ai-campus-predictions-core-v20-remaining51-dev21-new-api-v14-2026-09-02.checkpoint.json`
- Report：
  `artifacts/evaluation/m11-ai-campus-report-core-v20-remaining51-dev21-new-api-v14-2026-09-02.json`
