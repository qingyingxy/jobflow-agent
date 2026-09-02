# AI Campus Core Parser v12 未见 Holdout-30 评测

日期：2026-09-01

状态：已完成 30 条未见样本的人工标签冻结、新 API 调用和误差分析。当前结果
未达到全量评测门槛，暂不运行完整 154 条。

## 评测隔离

- 从 154 条严格集排除所有曾进入 smoke、targeted、recall 或 Reviewed manifest
  的 30 条历史样本，候选池剩 124 条。
- 使用固定种子 `holdout-v1` 抽取 30 条，覆盖 22 家公司，每家公司最多 2 条。
- 在任何模型预测生成前，仅依据岗位原文完成人工标签并冻结 v7 override。
- 标签冻结后，使用 `deepseek-v4-flash`、`jd-core-parser-prompt-v7` 和
  `jd-core-parser-v12` 发起全新 API 调用，没有复用历史预测。
- 首轮 `campus-ai-091` 在 180 秒超时；随后仅重试该条并成功。最终 30/30
  预测成功，失败数为 0。

## 严格指标

| 字段 | Precision | Recall | F1 | Exact Match |
| --- | ---: | ---: | ---: | ---: |
| `job_type` | 1.0000 | 0.9667 | 0.9831 | 0.9667 |
| `locations` | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| `required_skills` | 0.6211 | 0.5917 | 0.6061 | 0.1000 |
| `required_skill_groups` | 0.4118 | 0.2692 | 0.3256 | 0.5333 |
| `preferred_skills` | 0.6304 | 0.4496 | 0.5249 | 0.2000 |
| **Macro-F1** |  |  | **0.6879** |  |

`unsupported_claim_rate=0`，但本轮是 Core-only Parser 评测，没有运行证据匹配，
因此该值只表示没有 matcher claim，不应作为证据正确率结论。

## 主要误差

### 1. 技能名称没有统一到同一评测本体

多处语义正确但严格字符串不相等，例如：

- `JavaScript` / `JS`、`Go` / `Golang`；
- `Tool Calling` / `工具/函数调用`；
- `Diffusion` / `扩散模型`、`Imitation Learning` / `模仿学习`；
- `LLM` / `大语言模型相关技术`；
- `数据标注` / `标注`、`自动标注` / `自动化标注`；
- `World Model` / `世界模型 + 策略`、`目标检测` / `检测`。

`required_skill_groups` 当前按整组严格匹配，一个选项的同义词差异会使整组同时
产生一个 FP 和一个 FN，因此该字段对本体不一致尤其敏感。

### 2. `any_of` 识别仍有系统性漏召回

以下明确选择关系未稳定建组：

- `006`：C++/Python 至少一种、任意机器学习推理训练框架；
- `058`、`064`、`084`：至少一种主流编程语言；
- `064`：一种或多种深度学习框架；
- `079`：CV/NLP/多模态模型项目方向；
- `125`：React/Node.js/Go 中一种或多种；
- `127`：NX/SolidWorks/Creo 中一种或多种。

`124` 虽识别出三个组，但仿真工具被错误命名为编程语言，`MATLAB/Simulink`
没有拆分，研究方向的 `allow_other` 也与原文不一致。

### 3. 优先项召回不足

`010`、`055`、`066`、`069`、`094`、`124`、`155` 等样本存在整段或部分
preferred 丢失。`070` 已正确保持 required 为空，说明“全部条件均为优先”
的边界可以处理，但具体加分技能仍只召回一部分。

### 4. 原文支持校验过度依赖连续字符串

最终共有 44 个 `unsupported_field_value` warning，涉及 16 条样本。其中既有
应删除的模型扩写，也有语义明确但因省略共享后缀、缩写或规范化而被误删的值，
例如：

- 原文“半监督、自监督、主动学习、弱监督”无法支持规范化后的
  `半监督学习`、`自监督学习`、`弱监督学习`；
- 原文 `OOM 降级`、`GPU 编程与优化`、`模型压缩` 等被模型合理归一后，
  仍可能因连续子串不完全一致而被删除；
- `算法实现`、`失效原因定位`、`双臂操作` 等有直接语义依据，但当前校验器
  无法定位对应片段。

### 5. 两个确定性数据/词表问题

- `campus-ai-006` 的 internship 标签来自外部元数据，当前 Core Parser 输入只有
  `raw_content` 和 `source_url`，正文没有招聘类型，因此该标签对 Parser 不可观测。
- `campus-ai-127` 的机械“轻量化设计”仍被解析为 `模型量化`，属于跨领域词表
  误命中，需要通用的模型语境约束。

## 决策

当前不运行完整 154 条。原因不是 API 失败，而是技能本体、组选项规范化、
选择关系识别和原文支持校验仍会系统性扭曲指标；直接全量运行只会增加调用成本，
不会提供可信的新结论。

建议后续顺序：

1. 建立统一技能 alias/上位类别表，并让 gold 与 prediction 使用同一纯词法规范化；
2. 修复通用 `any_of` 模式和 `轻量化设计 -> 模型量化` 的跨领域误判；
3. 让证据校验支持共享后缀枚举和可证明的规范化别名，同时继续拒绝模型扩写；
4. 改善“者优先/加分项”的技能召回；
5. 将本批 30 条转为诊断集，从剩余 94 条从未使用样本中再抽一批新的冻结
   holdout。只有新 holdout 达到 Macro-F1 >= 0.90、required F1 >= 0.85，
   且没有系统性规则回归后，再运行完整 154 条。

## 产物

- 抽样清单：`datasets/ai_campus_holdout_30_selection_2026_09_01.json`
- 冻结标签：`datasets/ai_campus_label_overrides_v7_holdout_30_reviewed.json`
- 冻结 manifest：
  `artifacts/evaluation/m11-ai-campus-manifest-core-v12-holdout-30-frozen-v7-2026-09-01.json`
- 新 API predictions：
  `artifacts/evaluation/m11-ai-campus-predictions-core-v12-holdout-30-new-api-v7-2026-09-01.json`
- 评测报告：
  `artifacts/evaluation/m11-ai-campus-report-core-v12-holdout-30-new-api-v7-2026-09-01.json`
