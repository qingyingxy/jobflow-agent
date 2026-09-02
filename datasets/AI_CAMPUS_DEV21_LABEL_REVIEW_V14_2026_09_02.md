# AI Campus 剩余 51 条 dev21 标签复核 v14

日期：2026-09-02

状态：21 条 dev 已按 `ai-campus-annotation-guide-v1` 完成人工复核并冻结。
本轮只读取固定 dev 样本的原始 JD 和草稿标签，未读取或生成任何 Parser prediction，
未查看 30 条 sealed holdout 的正文或标签。

## 复核范围

- 固定划分：`datasets/ai_campus_remaining_51_split_v1_2026_09_02.json`
- 标注规范：`datasets/AI_CAMPUS_ANNOTATION_GUIDE_V1.md`
- 样本数：21
- 公司数：11
- 招聘类型：19 条校招、2 条实习
- 字段：`job_type`、`locations`、`required_skills`、
  `required_skill_groups`、`preferred_skills`、`skill_mentions`

## 关键决策

| 样本 | 决策 |
| --- | --- |
| `001` | “至少一种智能体框架”建开放组；“生成式算法或者强化学习”建封闭组。 |
| `008` | 原文未披露招聘类型；两个研究方向是嵌套条件，只按上位方向建组。 |
| `011` | 深度学习框架为必备上位能力，PyTorch/PaddlePaddle 只作示例 mentions。 |
| `023/032` | “技术领域之一或多个”统一建立 Agent 技术方向开放组。 |
| `024` | 第 3-5 条均为“了解”，Agent 评测、RAG 和具体机制不计必备。 |
| `027` | Agent 框架使用或自主架构设计建立上位组，具体框架只作示例。 |
| `029` | Python/Golang 普通斜杠枚举按 `all_of`；至少一种框架才建组。 |
| `037` | 原文未披露地点；大模型应用技术为了解，语言为至少一门开放组。 |
| `078` | 一个或多个模型/机器人学习方向建立封闭组。 |
| `080` | 编程语言和推理引擎分别建组；PyTorch、ViT/DiT、并行方法按示例处理。 |
| `097` | 系统基础“或”与至少一种语言分别建组；可观测工具全部属于优先。 |
| `102` | 学习方法建立组；PPO 等基本思想和仿真平台经验属于优先。 |
| `116` | 未列出面向对象语言选项，不构造伪单选组；ROS 条款属于优先。 |
| `121` | Kubernetes 原理为必备，调度机制和项目经验为优先。 |
| `126` | Agent/RAG/多智能体均在加分项，不作为硬门槛。 |
| `128` | CAE 工具与 Python/MATLAB 均为优先，具体工具名为示例。 |
| `142` | LLM/Agent/RAG 为了解；Web 漏洞为直接必备，其余为优先或加分。 |
| `147` | LLM/Prompt/Agent 为了解；Python、低代码和项目经历为加分。 |
| `160` | 对话系统或 Agent 应用经验建组；VLM/视频理解为弱了解。 |

## 严格字段处理

- `campus-ai-008` 的招聘类型仅来自采集元数据，严格评测不包含 `job_type`。
- `campus-ai-037` 的工作地点未出现在 JD 原文，严格评测不包含 `locations`。
- 其余岗位类型和地点均有原文依据。

## 冻结规则

`v14` 标签冻结后不得根据 dev prediction 静默修改。发现争议时创建新标签版本，
保留 v14 标签、prediction 和 report。30 条 sealed holdout 在 Parser、Prompt、别名词表
和阈值冻结前不得生成或查看 prediction。

## 产物

- 标签：`datasets/ai_campus_label_overrides_v14_remaining51_dev21_reviewed.json`
- 冻结清单：`datasets/ai_campus_dev21_label_freeze_v1_2026_09_02.json`
- 严格 Manifest：
  `artifacts/evaluation/m11-ai-campus-manifest-core-v20-label-v14-remaining51-dev21-strict-2026-09-02.json`
- 严格 Review：
  `artifacts/evaluation/m11-ai-campus-review-core-v20-label-v14-remaining51-dev21-strict-2026-09-02.json`
