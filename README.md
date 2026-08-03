# JobFlow Agent

面向国内校招与实习场景的岗位发现、分析与申请管理 Agent。

> 当前状态：MVP 规划阶段
> 项目名称：暂定，正式发布前需检查重名情况。

## 1. 项目简介

JobFlow Agent 根据用户的求职意向，从限定范围内的公开招聘来源发现岗位，也支持用户直接导入岗位链接或 JD 文本。系统自动解析中文 JD，检查校招资格，将岗位要求与用户真实经历进行匹配，并在用户确认后创建可追踪的申请记录。

项目核心原则：

```text
Agent 负责读取、分析和提出建议
用户负责材料修改和申请决策
确定性代码负责状态与数据一致性
```

本项目不追求自动海投，而是重点解决：

- 岗位信息格式不统一；
- 校招资格容易遗漏；
- 岗位匹配结论缺少事实依据；
- 简历修改容易产生虚构内容；
- 多个申请的状态和下一步行动难以管理。

## 2. 项目要证明什么

本项目主要展示四项能力：

1. Agent 能处理非结构化岗位页面，并在受控工具范围内提出读取和回退策略。
2. 岗位匹配和材料修改基于用户真实经历证据。
3. Agent 提出的材料修改需要经过用户确认。
4. 申请过程由状态机和事件日志管理，而不是一次对话结束。

本项目不以“支持多少家公司”为主要成功标准，而以是否完成以下闭环为标准：

```text
根据求职意向发现或导入真实岗位
→ 用户选择感兴趣的岗位
→ 正确解析要求
→ 完成资格检查
→ 引用真实经历解释匹配情况
→ 用户确认准备申请并创建申请记录
→ 用户审批材料修改建议
→ 跟踪申请状态
```

## 3. 项目边界

### 第一版实现

- 用户画像、求职意向和筛选条件；
- 从 1 个真实公开招聘来源发现岗位，第 2 个来源作为可选扩展；
- 岗位链接和岗位文本直接导入；
- 岗位来源和页面读取工具选择；
- 中文 JD 结构化解析；
- 校招和实习资格检查；
- 基于简历证据的岗位匹配；
- 简历修改建议及逐条确认；
- 申请状态机；
- 申请事件时间线；
- 基础岗位发现、筛选和去重；
- 可复现的评测脚本。

### 第一版不实现

- 自动登录 BOSS、微信等平台；
- 绕过验证码或反爬限制；
- 自动提交简历；
- 自动发送招聘消息；
- 邮件和短信持续监听；
- Temporal 持久工作流；
- 多 Agent 协作；
- Computer Use 自动填写表单；
- 完整简历排版系统；
- 自动面试系统；
- 复杂知识图谱；
- 大规模招聘信息聚合平台。

第一版的岗位发现范围限定为已配置的公司官方招聘入口和通用公开招聘页面，不承诺搜索整个互联网。用户已经找到岗位时，可以通过岗位链接或粘贴 JD 直接进入分析流程。

如果后续需要跨月自动等待、外部事件唤醒和复杂故障恢复，再评估迁移到 Temporal。

## 4. 核心用户流程

```text
用户填写个人信息和求职偏好
→ Agent 从限定范围的招聘来源发现岗位
→ 系统标准化、去重并完成基础筛选
→ 展示候选岗位和推荐原因
→ 用户选择感兴趣的岗位
→ 系统判断来源和页面类型
→ 在允许范围内路由到 ATS、HTTP 或浏览器工具
→ 获取并解析完整 JD
→ 检查届别、地点、学历等硬性资格
→ 将岗位要求与真实经历证据匹配
→ 展示匹配项、风险项和缺失项
→ 用户决定是否准备申请
→ 创建 PREPARING 状态的申请记录
→ Agent 生成材料修改建议
→ 用户逐条接受、修改或拒绝
→ 保存用户最终文本和审批结果
→ 用户在看板中更新申请状态
```

## 5. 核心模块

项目控制在六个主要模块。

### 5.1 Job Discovery & Ingestion Router

负责根据用户求职意向发现候选岗位，并读取用户选中的岗位信息。该模块是一个顶层边界，内部由意图解析、来源注册、来源适配、岗位标准化、去重和详情读取组成。

输入：

```text
用户画像和求职意向
目标公司或招聘来源
岗位链接
岗位文本
公司招聘页
```

岗位发现流程：

```text
自然语言求职目标
→ Search Intent Parser
→ Source Registry
→ Source Adapter 获取岗位列表
→ Job Normalizer
→ 确定性筛选和去重
→ 输出候选岗位
```

岗位详情读取回退顺序：

```text
已知 ATS 结构化接口
→ 普通 HTTP 页面读取
→ 页面结构化数据解析
→ 请求用户粘贴文本
```

Playwright 浏览器读取作为动态页面的可选扩展，不属于核心 MVP 的完成条件。

岗位发现阶段还需要完成：

- 将用户的自然语言求职目标转换为结构化筛选条件；
- 从已配置来源提取岗位列表；
- 标准化岗位字段；
- 按确定性条件进行筛选和去重；
- 为候选岗位生成可解释的粗粒度推荐原因。

发现阶段只提取公司、岗位名称、地点、招聘类型、发布时间等基础字段，不对所有候选岗位执行完整的资格检查和 Evidence Matcher。用户打开岗位详情后，才运行完整分析流水线。

候选岗位统一为轻量结构：

```json
{
  "source_id": "source_example",
  "source_job_id": "123",
  "company": "示例公司",
  "title": "AI 应用开发工程师",
  "location": ["上海"],
  "job_type": "campus",
  "published_at": null,
  "detail_url": "https://example.com/job/123",
  "last_seen_at": "2026-08-03T10:00:00+08:00"
}
```

优先使用 `source_id + source_job_id` 去重；来源缺少稳定岗位 ID 时，再使用规范化 URL 和岗位内容指纹作为回退。

用户选中岗位后，详情读取输出统一的原始岗位文档：

```json
{
  "source_url": "https://example.com/job/123",
  "source_type": "generic_html",
  "raw_content": "...",
  "retrieved_at": "2026-08-03T10:00:00+08:00",
  "trace_id": "trace_xxx"
}
```

系统需要记录：

- 选择了什么工具；
- 为什么选择该工具；
- 是否发生失败和回退；
- 最终提取结果是否完整；
- 是否需要用户补充信息。

如果实现 Playwright，它只用于动态渲染或普通请求无法读取的页面。

### 5.2 JD Parser

负责将中文 JD 转换成结构化数据。

核心字段：

```text
公司
岗位名称
校招 / 社招 / 实习
面向届别
招聘批次
工作地点
学历要求
专业要求
必备技能
加分技能
实习时长
每周到岗天数
最早到岗时间
截止日期
申请地址
```

结构化输出必须经过数据模型校验。缺失字段使用 `null`，不能让模型猜测。

### 5.3 Eligibility Checker

负责检查硬性条件，不与技能匹配分数混在一起。

示例输出：

```json
{
  "eligible": null,
  "checks": [
    {
      "field": "graduation_year",
      "result": "pass",
      "reason": "岗位面向 2027 届，用户为 2027 届"
    },
    {
      "field": "internship_duration",
      "result": "unknown",
      "reason": "岗位要求连续实习 6 个月，用户尚未确认"
    }
  ]
}
```

检查结果分为：

```text
pass
fail
unknown
```

存在 `unknown` 时，应向用户请求确认，不能直接判定符合。

### 5.4 Evidence Matcher

负责将 JD 要求与用户真实经历关联。

用户经历拆分为证据条目：

```json
{
  "evidence_id": "ev_project_001",
  "type": "project",
  "title": "Memory-RAG",
  "claim": "实现关键词检索与向量检索融合，并加入重排模块",
  "skills": ["RAG", "BM25", "Vector Search", "Reranker"],
  "source": "resume"
}
```

匹配流程：

```text
提取 JD 要求
→ 召回候选证据
→ 判断 supported / partial / unsupported
→ 保存引用证据
→ 生成可解释结论
```

示例：

```json
{
  "requirement": "具备 RAG 系统开发经验",
  "support_level": "supported",
  "evidence_ids": ["ev_project_001"],
  "explanation": "用户在 Memory-RAG 项目中实现了混合检索和重排"
}
```

系统必须满足：

1. `supported / partial` 至少保存一个当前用户的有效 `evidence_id`，`unsupported` 的 `evidence_ids` 必须为空。
2. 不允许生成证据中不存在的项目或技能。
3. 不允许擅自生成证据中不存在的数字。
4. `unsupported` 的要求不能被描述为用户已经掌握。
5. 用户可以查看每条结论的原始证据。
6. 无效 ID、跨用户引用或虚构事实统一安全降级为 `unsupported`，清空非法解释，并在 `AgentRun` 中记录校验失败。

用户编辑证据后，引用旧证据的完整分析不能继续作为最新结果展示。删除采用硬删除，同时删除引用该证据的 RequirementMatch、JobAnalysis、ResumeSuggestion 和 `final_text`；DomainEvent 只保留不含材料正文的审计元数据。

### 5.5 Candidate and Application State Machine

候选岗位和正式申请使用两套状态，避免将“发现岗位”误认为“已经申请”。

候选岗位状态：

```python
CANDIDATE_TRANSITIONS = {
    "DISCOVERED": {"SAVED", "IGNORED", "CONVERTED"},
    "SAVED": {"IGNORED", "CONVERTED"},
    "IGNORED": {"SAVED"},
    "CONVERTED": set()
}
```

申请状态：

```python
APPLICATION_TRANSITIONS = {
    "PREPARING": {"SUBMITTED", "WITHDRAWN"},
    "SUBMITTED": {"ASSESSMENT", "INTERVIEW", "REJECTED", "WITHDRAWN"},
    "ASSESSMENT": {"INTERVIEW", "REJECTED", "WITHDRAWN"},
    "INTERVIEW": {"INTERVIEW", "OFFER", "REJECTED", "WITHDRAWN"},
    "OFFER": set(),
    "REJECTED": set(),
    "WITHDRAWN": set()
}
```

用户点击“准备申请”时，领域服务在同一事务中完成：

```text
CandidateJob → CONVERTED
创建 Application → PREPARING
记录 ApplicationCreated 事件
```

状态转换只能由领域服务执行。大模型可以提出状态建议，但不能直接修改数据库。

真实来源发现会创建 `DISCOVERED` CandidateJob；用户手动粘贴或导入的 `JobPosting` 也可以通过 `POST /api/candidates` 幂等创建 `SAVED` CandidateJob，因此申请闭环不依赖岗位发现功能先完成。

### 5.6 Event and Trace Log

业务事件和 Agent 执行轨迹分开保存。业务事件用于用户可见的时间线，Agent Trace 用于调试、评测和复现。

业务事件：

```text
创建申请
生成分析
接受材料修改
拒绝材料修改
确认已投递
进入笔试
进入面试
收到 Offer
申请被拒绝
用户主动结束申请
```

Agent Trace：

```text
调用了什么工具
工具输入摘要
工具是否成功
是否发生回退
模型输出是否通过校验
最终使用了哪些证据
```

业务事件表建议字段：

```text
id
entity_type
entity_id
event_type
source
payload JSON
created_at
```

核心 MVP 只使用 `AgentRun`，保存 `user_id`、运行类型、目标实体、状态、模型、提示词版本、输入哈希、结构化输出、校验结果、起止时间、耗时和错误。运行状态使用 `succeeded / failed`，输出校验结果单独使用 `passed / failed`，因此模型调用成功但输出被安全降级时仍能准确记录。运行类型至少支持 `jd_parse`、`evidence_match` 和 `resume_suggestion`。实现多步网页工具调用后，再按需要增加独立的工具调用记录。

## 6. 人工确认机制

第一版最重要的人工确认场景是创建申请、采用简历修改建议和推进申请状态。

交互流程：

```text
用户点击“准备申请”并创建 PREPARING 申请
→ 用户选择要修改的文本类型并提供原文
→ Agent 生成修改建议
→ 展示原始文本
→ 展示建议文本
→ 展示引用证据
→ 用户接受、编辑或拒绝
→ 保存用户最终决定
```

用户没有接受之前，建议内容不能成为最终文本。

核心 MVP 不创建完整 Resume 或 ResumeVersion。建议请求使用 `SuggestionTargetInput` 显式提供 `original_text`、`target_type` 和可选 `target_label`；`ResumeSuggestion` 关联当前用户、Application 和 JobAnalysis，保存目标、原文、建议文本、引用证据、审批状态及最终文本。

创建申请本身必须来自用户明确操作。Agent 可以建议用户准备申请，但不能自行将候选岗位转换为申请记录。

状态变更使用确认弹窗：

```text
是否确认已经完成官网投递？
是否将申请状态更新为“面试”？
是否将该申请标记为“已拒绝”？
```

## 7. 页面设计

第一版只实现三个主要页面。

### 7.1 岗位发现页

展示：

- 当前求职意向和筛选条件；
- 岗位来源和最近更新时间；
- 岗位基本信息；
- 来源链接；
- 推荐原因；
- 地点、届别、岗位类型等基础筛选结果；
- 信息缺失或来源异常等初步风险；
- 收藏、忽略和查看详情操作。

用户也可以从本页面直接输入岗位链接或粘贴 JD，跳过岗位发现，进入岗位分析流程。

### 7.2 岗位分析与申请准备页

展示：

- 结构化 JD；
- 硬性资格检查；
- 每条要求对应的经历证据；
- `supported / partial / unsupported` 判断；
- 匹配分数和风险项；
- 简历修改建议；
- 建议目标类型和用户提供的原文；
- 修改前后 Diff；
- 接受、编辑和拒绝操作；
- 创建申请记录并保存材料建议的最终文本和审批状态。

### 7.3 申请看板

按状态展示：

```text
准备申请
已投递
笔试或测评
面试
Offer
拒绝或结束
```

每个申请展示：

- 当前状态；
- 下一步待办；
- 最近更新时间；
- 已采用的材料建议；
- 事件时间线；
- 官方岗位链接。

审批中心不单独创建页面，确认操作直接放在岗位分析页和申请看板中。

## 8. 系统架构

```mermaid
flowchart LR
    UI["Next.js Web"] --> API["FastAPI"]
    API --> DISCOVERY["Discovery Service"]
    API --> ANALYSIS["Analysis Pipeline"]
    API --> APPLICATION["Application Service"]

    DISCOVERY --> SOURCES["Source Registry / Adapters"]
    SOURCES --> HTTP["HTTP / HTML"]
    SOURCES -. Optional .-> BROWSER["Playwright Fallback"]
    SOURCES --> MANUAL["Manual Import"]

    ANALYSIS --> PARSER["JD Parser"]
    ANALYSIS --> ELIGIBILITY["Eligibility Checker"]
    ANALYSIS --> MATCHER["Evidence Matcher"]

    APPLICATION --> STATE["Candidate / Application State Machine"]
    APPLICATION --> APPROVAL["Approval Gate"]
    APPLICATION --> EVENTS["Business Events"]
    ANALYSIS --> TRACE["Agent Trace"]

    DISCOVERY --> DB["SQLite（核心 MVP） / PostgreSQL（发布前验证与可选升级）"]
    ANALYSIS --> DB
    APPLICATION --> DB
```

## 9. Agent 与普通代码的边界

### Agent 负责

- 理解用户求职意向并生成检索条件；
- 判断岗位页面类型和语义相关性；
- 在系统允许的工具范围内提出读取或回退建议；
- 解析非结构化 JD；
- 判断岗位要求与经历之间的语义关系；
- 解释匹配结论；
- 生成材料修改建议。

### 确定性代码负责

- 数据模型校验；
- 招聘来源注册和 Adapter 路由；
- URL、工具、超时和重试策略；
- 硬性资格规则；
- 匹配分数计算；
- 状态转换；
- 用户权限；
- 数据保存；
- 岗位去重；
- 岗位筛选和排序；
- 事件记录；
- 定时任务；
- 修改建议是否被用户接受。

## 10. 匹配评分

第一版采用可解释的简单评分，不训练独立模型。

该评分只在用户打开岗位详情并完成完整分析后计算。岗位发现页仅展示基于岗位方向、地点和招聘类型的粗粒度推荐原因。

建议权重：

```text
硬性资格：门控条件
必备技能覆盖率：60%
加分技能覆盖率：20%
地点和岗位偏好：20%
```

`supported / partial / unsupported` 分别按 `1 / 0.5 / 0` 计入覆盖率。硬性资格出现 `fail` 时标记为不推荐；出现 `unknown` 时保留分数但要求用户确认。

评分使用以下确定性边界：

- 要求先按规范化后的 `category + name` 去重；
- 只有 JD 明确不存在某类要求时，该分组才标记为 `not_applicable`；
- `not_applicable` 分组的权重按原比例重分配给其他适用分组；
- JD 字段缺失属于信息不足，不能当作 `not_applicable`；
- 所有软评分分组都不可用时，分数返回 `null`，并展示补充信息提示。

最终结果必须同时展示分数和证据，不能只显示一个百分比。

## 11. 岗位发现与同步范围

核心 MVP：

- 支持用户填写求职意向和筛选条件；
- 支持从 1 个真实公开招聘来源发现岗位；
- 支持岗位链接和文本直接导入；
- 实现手动文本和通用 HTML 两种读取方式；
- 支持基础字段标准化、筛选和内容指纹去重。

扩展目标：

- 覆盖 5～10 个招聘来源；
- 收集并解析 100～300 条真实岗位；
- 支持简单定时同步和岗位变化检测；
- 增加 Embedding 召回和 Playwright 动态页面回退。
- 增加第 2 个招聘来源。

推荐连接器：

```text
MokaAdapter
GenericHtmlAdapter
BrowserFallbackAdapter
ManualTextAdapter
```

这里的招聘来源优先指已配置的公司官方招聘入口，不要求为每家公司单独编写完整爬虫。除非通用连接器无法适配，否则不实现公司级专用爬虫。扩展目标不作为核心 MVP 的完成条件。

## 12. 数据模型

主要实体：

```text
UserProfile
EvidenceItem
JobSource
JobPosting
JobParseResult
CandidateJob
JobAnalysis
RequirementMatch
ResumeSuggestion
Application
DomainEvent
AgentRun
DiscoveryRun
```

核心 MVP 使用 SQLite-first，求职偏好作为 `UserProfile.search_preferences JSON` 保存；切换 PostgreSQL 后可以再升级为 JSONB。M05 使用 `SearchPreferences` Schema 明确地点、岗位类型、到岗日期、每周天数和实习时长的类型、范围与 `null` 语义，不能在资格函数中直接猜测任意 JSON。岗位原文、内容指纹和读取时间直接保存在 `JobPosting`；审批状态和用户最终文本直接保存在 `ResumeSuggestion`。

关键关系：

```text
UserProfile
├── EvidenceItem
├── search_preferences JSON
├── DiscoveryRun
└── CandidateJob
    ├── JobPosting
    │   └── JobParseResult
    └── JobAnalysis
        └── RequirementMatch

CandidateJob
└── Application
    ├── ResumeSuggestion
    └── DomainEvent
```

`CandidateJob` 保留为轻量关联实体，用于隔离外部岗位事实和用户侧的收藏、忽略、转换状态，但不为它单独建设复杂 Repository 层。

`JobParseResult` 是岗位级、与用户无关的解析缓存，只允许按 `content_hash + schema_version + parser_version + prompt_version + model` 复用。`JobAnalysis` 是用户级结果，必须包含 `user_id`、`analysis_version` 和可选 `invalidated_at`，并在每次分析时使用当前画像和当前证据重新计算资格、匹配与分数，不能跨用户复用。

`DiscoveryRun` 保存一次用户手动发现的来源、状态、发现/新增/重复数量、失败摘要和起止时间。`DomainEvent` 通过 `entity_type + entity_id` 关联候选岗位或申请；`AgentRun` 从 M04 首次接入模型时开始保存必要执行轨迹，切换 PostgreSQL 后可升级为 JSONB，不参与业务状态计算，也不在普通日志中保存完整敏感输入。

以下实体延后到确有需求时再增加：

```text
SearchPreference 独立表
JobSnapshot
ResumeVersion
ApprovalDecision 独立表
ToolCallTrace 独立表
```

## 13. 评测方案

第一版重点评测三项能力。

### 13.1 JD 核心字段解析

指标：

```text
字段级 Precision
字段级 Recall
Macro-F1
```

### 13.2 硬性资格判断

指标：

```text
pass / fail / unknown 分类准确率
误判符合率
```

### 13.3 证据引用正确率

指标：

```text
Evidence Precision
Evidence Coverage
Unsupported Claim Rate
```

核心 MVP 准备 30～50 条人工标注样本，后续扩展到 50～100 条。数据集需要有版本、标注说明和固定格式，并区分开发样本与最终评测样本；正常、字段缺失、`unknown`、无证据、读取失败和非法模型输出均需预先规定最小样本分布。

最终运行前冻结 Evaluation Manifest、指标口径和发布阈值，不能查看最终结果后再修改通过标准。原始模型输出和 Validator 后用户可见输出分别报告；用户可见 Unsupported Claim Rate 的发布要求为 0。评测结果同时记录模型、提示词、数据集版本、随机参数、运行时间和失败数，不在简历中使用未经实际运行的指标。

## 14. 技术栈

### 后端

- Python 3.12
- uv：Python 项目、依赖和锁文件管理
- FastAPI
- Pydantic
- SQLAlchemy
- Alembic
- SQLite（本地 MVP）
- PostgreSQL 16 + pgvector（Docker Compose，可选升级路径）

### 前端

- Next.js
- TypeScript
- 简单组件库

### Agent 和网页读取

- 支持结构化输出的大模型接口
- HTTP Client
- HTML Parser
- Playwright，可选的动态页面兜底
- Embedding，可选

### 任务与测试

- 平台定时任务或独立同步命令，作为扩展能力
- Pytest
- Playwright Test，仅在实现浏览器兜底后启用
- 结构化日志

核心 MVP 不强制使用 LangGraph、Temporal、Redis 或独立向量数据库。如果工具选择和人工中断流程后续变复杂，再评估引入 LangGraph；如果需要跨月等待、外部事件唤醒和复杂故障恢复，再评估 Temporal。

Python 环境统一使用 `uv` 管理，提交 `pyproject.toml` 和 `uv.lock`，不维护单独的 `requirements.txt`。所有 Python 命令通过 `uv run` 执行。

本地后端开发：

```text
uv sync
uv run uvicorn src.main:app --reload
uv run pytest
uv run ruff check src tests migrations
uv run alembic upgrade head
```

本地前端开发：

```powershell
Set-Location frontend
Copy-Item .env.example .env.local
npm install
npm run dev
```

前端默认运行在 `http://localhost:3000`，后端默认运行在 `http://localhost:8000`。首页的“检查后端连接”按钮会调用 `/health`，用于确认两部分已经连通。生产构建和 TypeScript 检查：

```powershell
npm run typecheck
npm run build
```

完成后可以返回项目根目录：

```powershell
Set-Location ..
```

### SQLite-first 本地开发

默认配置使用 SQLite，适合先完成用户画像、岗位分析、资格判断、证据匹配和申请状态机，不需要安装数据库服务。数据库文件会自动创建在 `./data/jobflow.db`，并被 Git 忽略。

```powershell
Copy-Item .env.example .env
uv sync
uv run alembic upgrade head
uv run uvicorn src.main:app --reload
```

后续如果模型中使用 PostgreSQL 专有能力（例如 JSONB 或 pgvector），再为对应迁移增加 PostgreSQL 方言分支；业务服务和 SQLAlchemy Session 接口保持不变。

### PostgreSQL 发布前验证与可选升级

SQLite 是 M01～M11 的核心开发和验收数据库，因此没有 Docker Desktop 不影响核心进度。准备部署、需要验证 PostgreSQL 迁移，或开始使用 JSONB/向量检索时，再启用 PostgreSQL。该检查属于发布前验证，不计入 M01～M11 核心进度。

基础设施采用与 Memory-RAG 相同的轻量方案：使用 `pgvector/pgvector:pg16` 镜像、持久化卷和健康检查。当前 Compose 文件只负责数据库，API 和前端仍按本地开发方式启动。

不需要单独安装 PostgreSQL，但需要安装并运行 Docker Desktop：

```powershell
Copy-Item .env.example .env
docker compose up -d postgres
docker compose ps
$env:DATABASE_URL = 'postgresql+psycopg://jobflow:jobflow@localhost:5432/jobflow?connect_timeout=3'
uv run alembic upgrade head
```

API 在宿主机运行时通过 `localhost:5432` 连接数据库；以后如果 API 也放进 Compose，需要把连接地址中的主机名改为 `postgres`。数据库数据保存在 `jobflow_postgres_data` 卷中，执行 `docker compose down` 不会删除该卷。

停止数据库：

```powershell
docker compose stop postgres
```

如果暂时没有 Docker Desktop，可以继续完成 SQLite 迁移、测试和全部核心功能。发布前应在全新 PostgreSQL 数据库上执行迁移，并复核 JSON、时区、唯一约束、事务和核心 API；验证结果记录镜像版本、迁移版本、日期及已知差异。

### M02 用户画像与经历证据 API

当前 M02 使用 SQLite 保存用户画像和经历证据。API 通过 `X-User-ID` 识别本地用户；不传该请求头时使用 `.env` 中的 `DEFAULT_USER_ID`，默认值为 `local-user`。这只是开发阶段的身份占位，不等同于生产认证。

```text
GET   /api/profile
PUT   /api/profile
POST  /api/evidence
GET   /api/evidence
GET   /api/evidence/{evidence_id}
PATCH /api/evidence/{evidence_id}
```

经历证据的查询、读取和修改都会同时使用 `user_id + evidence_id` 过滤，不能通过已知证据 ID 读取其他用户的数据。证据包含类型、标题、事实陈述、技能标签和来源；求职偏好保存在用户画像的 JSON 字段中。

### M03 JD 导入与结构化 Schema

M03 先支持用户粘贴岗位文本，不执行网页抓取和模型解析。导入时保存原始岗位文本、来源类型、读取时间、追踪 ID 和 SHA-256 内容指纹。

```text
POST /api/jobs/import-text
GET  /api/jobs/{job_id}
```

`StructuredJobDescription` 是 M04 JD Parser 的基础输出，所有无法从岗位文本确认的字段都使用 `null`，不会用空字符串或模型猜测代替。M03 先完成可持久化的 Schema 基线，M04 已补齐模型输出所需的唯一事实来源、字段原文依据和跨字段语义校验。

### M04 JD Parser 约定

M04 使用可替换的 `StructuredModelClient`。Fake 和真实模型 Client 必须共享同一调用边界，Parser 之外的业务代码不能依赖某个模型供应商的响应格式。

```text
RawJobDocument
→ 构造带版本的解析提示词
→ StructuredModelClient
→ Pydantic 类型与语义校验
→ 字段原文依据校验
→ 保存岗位级 JobParseResult 和 AgentRun
```

结构化结果遵循以下规则：

- `JobRequirement` 是证据匹配和技能评分的规范输入；重复的技能列表只能由确定性代码派生；
- `required_skills` 和 `preferred_skills` 必须与 `requirements` 保持确定性关系，不能形成第二套岗位事实；
- 资格字段和通用资格条件不能由模型分别生成两套矛盾事实；
- 每个关键字段保存 `field_path`、原文片段和可选字符位置，Parser 还会检查原文片段确实来自岗位文本；
- `unknown` 表示岗位原文无法确认，不表示模型调用失败；
- 类型错误、非法操作符、缺少必要值或额外字段会使整次解析失败；
- 模型超时、无响应或校验失败时不保存半成品分析，并向页面返回可重试错误。

M04 提供同步解析接口 `POST /api/jobs/{job_id}/parse`。默认使用 Fake Client，便于本地重复演示；设置 `STRUCTURED_MODEL_PROVIDER=openai_compatible` 后，可通过 `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL` 和 `LLM_TIMEOUT_SECONDS` 接入 OpenAI-compatible 结构化模型。`JobParseResult` 保存与用户无关的岗位级解析缓存，`AgentRun` 记录用户、运行类型、目标实体、状态、模型、提示词版本、输入哈希、输出校验结果、起止时间、耗时和错误。M11 负责将这些运行记录与数据集版本组合成可重复评测，而不是到 M11 才首次加入运行轨迹。

M04 不负责完整分析持久化；M07 在 Parser、Eligibility 和 Evidence 接口稳定后实现 `JobAnalysis`，统一保存解析、资格、证据匹配和评分结果。

### M05 资格规则

M05 将资格判断与技能匹配分开，使用纯函数 `check_eligibility`，不调用模型，也不写数据库。输入为用户画像、经过校验的 `SearchPreferences` 和结构化 JD，输出总体资格结果及逐项检查：

```text
CandidateProfileInput + SearchPreferences + StructuredJobDescription
→ EligibilityInput
→ check_eligibility
→ EligibilityCheck[] + EligibilityResult
```

检查覆盖毕业年份、学历、专业、地点、岗位类型、实习时长、每周到岗天数和最早到岗时间。每条结果包含 `pass / fail / unknown`、规则名、原因、JD 原文依据和待补充信息；总体结果按 `fail > unknown > pass` 汇总。学历层级、专业族、北京/北京市等地点别名、日期和数值比较均使用确定性规则，无法安全规范化时返回 `unknown`。

`SearchPreferences` 明确以下字段的类型和范围：`preferred_locations`、`job_types`、`earliest_start_date`、`weekly_days(1～7)` 和 `internship_duration_months(>=0)`。`null` 表示信息未提供，相关规则返回 `unknown`；空列表表示明确没有该类限制。M02 旧字段 `target_roles` 和 `locations` 暂时保留兼容，但资格检查只使用规范字段。

### M06 证据匹配与确定性评分

M06 将岗位要求和用户经历拆成可独立测试的四个边界：

```text
JobRequirement
→ EvidenceRetriever
→ EvidenceMatcher
→ EvidenceValidator
→ RequirementMatch
→ MatchScoreCalculator
```

召回只使用当前用户的经历证据，支持大小写、空白和少量明确技能别名，结果按稳定规则排序。模型只能从召回候选中选择 `evidence_ids`；`supported / partial` 至少需要一个有效证据，`unsupported` 必须为空引用。无效 ID、跨用户引用或证据中不存在的项目、技能、数字会被安全降级为 `unsupported`，清空引用和解释，并在 `AgentRun` 中记录校验失败。

评分按规范化后的 `category + name` 去重，使用 `supported / partial / unsupported = 1 / 0.5 / 0`，原始权重为必备技能 60%、加分技能 20%、地点和岗位偏好 20%。只有 JD 明确没有某类要求时才标记 `not_applicable` 并重新分配权重；JD 信息缺失返回信息不足而不是假设不适用。硬性资格失败时标记不推荐，资格未知时保留可计算分数并要求用户确认。

### M07 分析持久化与 API 约定

MVP 采用同步分析接口，不引入后台队列和轮询任务：

```text
POST /api/jobs/{job_id}/analyze
→ 复用或创建岗位级 JobParseResult
→ 使用当前用户画像和证据重新计算完整分析
→ 全部成功后保存用户级 JobAnalysis
→ 返回新结果
```

`GET /api/jobs/{job_id}/analysis` 只返回当前用户最新且 `invalidated_at` 为空的成功结果。可安全处理的非法证据匹配降级为 `unsupported`，作为风险项保存；模型超时、结构化输出非法或无法安全降级的校验错误在 `AgentRun` 中记录失败并返回统一错误，不保存半成品 `JobAnalysis`。用户画像、证据、岗位文本或分析规则变化后，旧分析写入 `invalidated_at`，不得继续标记为最新。

M07 已实现 `JDAnalysisService` 和 SQLite `JobAnalysis` 迁移。岗位级解析缓存只按岗位原文指纹、Schema/Parser/Prompt 版本和模型复用；用户级分析每次使用当前画像与当前证据重新计算。默认 Fake 模式使用一个可重复的本地演示 Client，前端工作台可以载入明确标记的演示画像与 Memory-RAG 证据，完整展示结构化 JD、资格、要求证据、评分、风险和待补充信息；真实模型仍通过 M04 的同一 `StructuredModelClient` 接口接入。

## 15. 安全与数据边界

第一版至少实现以下约束：

- 将岗位网页视为不可信内容，网页文本不能覆盖系统指令；
- 限制可访问 URL、协议和目标地址，阻止访问内网和本机资源；
- 为 HTTP 和浏览器工具设置超时、响应大小和重试上限；
- 清理脚本、隐藏元素和与岗位无关的页面内容；
- 普通日志不保存完整简历、联系方式和其他敏感信息；
- 用户删除材料时，同步删除关联证据、建议和最终文本。

## 16. 推荐目录结构

```text
jobflow-agent/
├── src/
│   ├── api/
│   │   ├── dependencies.py
│   │   ├── profiles.py
│   │   ├── evidence.py
│   │   ├── jobs.py
│   │   └── schemas.py
│   ├── domain/
│   │   ├── models.py
│   │   ├── runs.py
│   │   ├── analysis.py
│   │   ├── job.py
│   │   ├── eligibility.py
│   │   └── matching.py
│   ├── services/
│   │   ├── profile_service.py
│   │   ├── evidence_service.py
│   │   ├── jd_parser.py
│   │   ├── job_parse_service.py
│   │   ├── eligibility_checker.py
│   │   ├── evidence_retriever.py
│   │   ├── evidence_matcher.py
│   │   ├── evidence_validator.py
│   │   ├── evidence_match_service.py
│   │   ├── jd_analysis_service.py
│   │   └── match_score.py
│   ├── infrastructure/
│   │   ├── database.py
│   │   ├── llm_client.py
│   │   └── __init__.py
│   ├── evaluation/
│   └── main.py
├── frontend/
├── tests/
├── datasets/
├── docs/
└── README.md
```

## 17. 开发阶段

具体模块边界、接口和完成标准见 [`docs/DEVELOPMENT_WORKFLOW.md`](docs/DEVELOPMENT_WORKFLOW.md)，当前开发进度见 [`TODO.md`](TODO.md)。

当前 M07 的核心实现已完成，核心进度为 7 / 11，下一步是 M08。M04 仍待配置真实模型后用 3 条真实中文 JD 完成手动验收；Fake、错误处理、迁移、解析缓存、资格规则、证据匹配、用户级分析、评分、失效和页面链路已经可重复测试。这个进度以 SQLite 核心 MVP 为准；PostgreSQL 切换验证使用独立的发布前检查表，不回退或阻塞核心里程碑。

### 阶段 A：岗位分析闭环

实现用户画像、经历证据、岗位文本导入、JD Parser、Eligibility Checker、Evidence Matcher 和分析结果页面。

完成条件：

```text
粘贴一个真实 JD
→ 输出结构化字段
→ 完成资格判断
→ 每条匹配结论引用具体经历证据
```

### 阶段 B：申请与审批闭环

实现 CandidateJob、Application、申请状态机、业务事件、材料建议、人工审批和申请看板。

完成条件：

```text
保存一个候选岗位
→ 用户点击准备申请
→ 原子创建 PREPARING 申请
→ 手动推进至 SUBMITTED 和 INTERVIEW
→ 审批岗位定制建议
→ 展示完整业务时间线
```

### 阶段 C：轻量岗位发现

实现岗位链接读取、URL 安全检查、1 个真实招聘来源 Adapter、岗位标准化和去重、用户手动触发发现以及岗位发现页。第 2 个招聘来源和定时同步为可选扩展。

完成条件：

```text
输入求职意向
→ 从真实来源发现候选岗位
→ 标准化和去重
→ 用户选择岗位并进入完整分析
```

### 阶段 D：评测与演示

实现 30～50 条人工标注样本、三组基础评测、AgentRun 汇总、失败案例、端到端测试和 UI 打磨。最小 AgentRun 已在 M04 引入，本阶段负责数据集版本、指标计算、复现实验和结果整理。

完成条件：

```text
完整演示真实岗位发现和申请闭环
→ 核心指标可通过脚本复现
→ unknown、读取失败和无证据场景可以正常展示
```

第 2 个来源、5～10 个来源规模、100～300 条岗位、岗位快照、变化检测和复杂 Playwright 回退属于核心 MVP 完成后的扩展目标。

在当前阶段达到完成条件之前，不进入下一阶段。

## 18. MVP 演示流程

最终版本至少能够完整演示：

```text
1. 用户录入求职偏好，并把真实项目、实习和技能拆成经历证据
2. Agent 从限定范围的公开招聘来源发现候选岗位
3. 用户选择一个感兴趣的岗位
4. 系统在允许的工具范围内读取岗位页面
5. 系统解析中文 JD
6. 系统检查届别、地点和实习时长
7. 系统引用真实经历解释岗位匹配情况
8. 用户点击“准备申请”，系统创建 PREPARING 申请记录
9. 用户选择建议目标并粘贴需要修改的简历片段，Agent 生成岗位定制建议
10. 用户查看证据并逐条审批
11. 系统保存审批状态和用户最终文本
12. 用户在看板中将状态推进至投递和面试
13. 系统展示完整事件时间线
```

如果用户已经找到岗位，也可以通过岗位链接或粘贴 JD 直接进入第 4 步。

## 19. 项目成功标准

项目完成时应当能够证明：

```text
Agent 能根据求职意向发现真实岗位
Agent 能读取真实岗位页面
Agent 能处理非结构化 JD
资格判断和技能匹配相互分离
每个匹配结论能够追溯到真实经历
候选岗位和正式申请使用独立状态
材料修改由用户最终确认
申请状态由确定性状态机管理
业务事件和 Agent Trace 能够分别追踪
核心效果能够通过评测复现
```

本项目不追求成为完整招聘平台，而是完成一个范围清晰、结果可解释、具备人工控制的求职 Agent 产品闭环。
