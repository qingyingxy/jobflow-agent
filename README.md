# JobFlow Agent

面向国内校招与实习场景的岗位发现、分析与申请管理 Agent。

> 当前状态：M01～M18、`v0.2 Trusted Discovery` 与 `v0.3 Verified Application Preparation` 已完成；从可信岗位发现到有限 ATS 辅助、真实凭证和后续跟进的闭环均已落地。
> 当前阶段：M19 端到端评测与安全加固进行中；Mock ATS、投递指标、数据导出/删除和本地安全边界已落地，真实身份提供方与 PostgreSQL 实机验证仍待完成。
> 项目名称：暂定，正式发布前需检查重名情况。

## 1. 项目简介

JobFlow Agent 在限定范围内的公开招聘来源中发现岗位，也支持用户直接导入岗位链接或 JD 文本。系统自动解析中文 JD，检查校招资格，将岗位要求与用户真实经历进行匹配，并在用户确认后创建可追踪的申请记录。

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

1. Agent 以 Plan → Act → Observe 的受控流程选择岗位读取工具，并记录观察、回退和停止原因。
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
→ 批准冻结投递包
→ 用户在官网手动提交并保存真实凭证
→ 跟踪申请状态
```

## 2.1 演示

![岗位发现严格匹配与拓展候选演示](docs/assets/jobflow-discovery-demo.gif)

[查看静态截图](docs/assets/jobflow-discovery-demo.png)。演示使用确定性 API fixture，不依赖招聘官网的实时可用性；真实来源 Adapter 和页面行为分别由后端集成测试与 Playwright E2E 覆盖。

## 3. 项目边界

### 第一版实现

- 用户画像、求职意向和筛选条件；
- 从已登记的 40 家公司官方招聘入口尝试即时发现公开岗位；
- 每次搜索最多保存 20 条岗位，仅自动分析严格匹配中排序靠前的 5 条；
- 不做每日定时同步，搜索由用户即时触发；
- 岗位链接和岗位文本直接导入；
- 岗位来源和页面读取工具选择；
- 中文 JD 结构化解析；
- 校招和实习资格检查；
- 基于简历证据的岗位匹配；
- 简历修改建议及逐条确认；
- 申请状态机；
- 申请事件时间线；
- 基础岗位发现、筛选和去重；
- 外部 Agent、第三方链接和手动 URL 的统一线索验证；
- 动态岗位页的只读浏览器接管，以及岗位开放/过期状态复查；
- 与公开分析画像隔离的候选人私密档案；
- 带文件哈希、用户归属和默认版本的简历材料库；
- 必须由用户明确确认的可复用答案库；
- 不可原地修改、必须由用户批准的冻结投递包；
- 人工官网投递、阻塞队列、执行检查和真实提交凭证；
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
→ 用户用自然语言描述想找的岗位，并多选目标公司范围
→ Agent 只在选定公司的官网中即时发现最多 20 条岗位
→ 系统标准化、去重，将结果分为严格匹配和拓展候选
→ 仅严格匹配中的前 5 条自动进入完整分析
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
→ 用户确认私密申请事实、简历版本和可复用答案
→ 用户批准内容冻结的投递包版本
→ 系统创建绑定岗位、官方 URL 和冻结版本的投递尝试
→ 用户打开官网、填写表单并记录阻塞
→ 用户真实提交后保存确认文本、编号或脱敏截图元数据
→ 系统校验凭证并在同一事务内确认已投递
→ 用户在看板中跟踪后续状态
```

## 5. 核心模块

项目控制在六个主要模块。

### 5.1 Discovery Agent & Ingestion Tools

负责根据用户求职意向编排岗位读取路径，并读取用户选中的岗位信息。当前 Planner 使用确定性策略，不允许模型自由生成 URL 或突破工具预算；来源 Adapter、URL Reader、岗位标准化与去重都是受控执行工具。

每次运行在发出网络请求前先持久化结构化 `search_plan`，其中包含用户允许的来源白名单、逐来源工具顺序、结果与分析预算以及停止条件。执行阶段再持久化 `agent_trace`，至少记录：

```text
plan：本次允许访问哪些来源，各来源采用什么有界工具顺序
act：已适配来源优先使用专用 Adapter，其余来源使用受控页面验证
observe：工具返回了岗位事实、空结果还是失败原因
fallback：为什么切换工具或请求用户粘贴 JD
stop：为什么生成候选岗位或拒绝把页面当作岗位
```

轨迹步骤同时保存发生时间、耗时、稳定错误码和关键计数。专用 Adapter 失败后回退静态页面时，两次真实执行都会保留，最终成功步骤不会覆盖前面的失败记录。

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
→ 公司官方来源注册表
→ Official Company Adapter 获取官网岗位列表
→ Job Normalizer
→ 确定性筛选和去重，最多保留 20 条
→ 按公司、地点、招聘类型和岗位方向划分严格匹配 / 拓展候选
→ 仅把严格匹配中的前 5 条送入完整分析流水线
→ 输出候选岗位和分析进度
```

岗位详情读取回退顺序：

```text
已知 ATS 结构化接口
→ 普通 HTTP 页面读取
→ 页面结构化数据解析
→ 请求用户粘贴文本
```

招聘首页、指南、流程页或无法验证的动态页面不会作为候选岗位保存。没有专用 Adapter 时，Agent 明确停止自动发现并建议用户粘贴具体 JD，不允许模型补造岗位事实。

Playwright 浏览器读取作为动态页面的可选扩展，不属于核心 MVP 的完成条件。

岗位发现阶段还需要完成：

- 将用户的自然语言求职目标转换为结构化筛选条件；
- 从已配置来源提取岗位列表；
- 标准化岗位字段；
- 按确定性条件进行筛选和去重；
- 为候选岗位生成可解释的粗粒度推荐原因。

发现阶段先提取公司、岗位名称、地点、招聘类型、发布时间等基础字段，通过确定性门控记录严格匹配或拓展候选，并只对严格匹配中排序靠前的 5 条执行完整的资格检查和 Evidence Matcher。拓展候选保留真实字段和放宽原因，用户可以手动运行完整分析。

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

`PREPARING → SUBMITTED` 虽然是领域状态图中的合法边，但通用状态 API 不允许直接执行。它只能由 M16 的投递确认事务完成，并且必须同时找到当前用户的已批准 `PacketRevision`、成功 `ApplicationAttempt` 和有效 `SubmissionReceipt`。保存岗位、创建申请、批准材料、打开表单或只记录凭证都不等于已经投递。

用户点击“准备申请”时，领域服务在同一事务中完成：

```text
CandidateJob → CONVERTED
创建 Application → PREPARING
记录 ApplicationCreated 事件
```

状态转换只能由领域服务执行。大模型可以提出状态建议，但不能直接修改数据库。

真实来源发现会创建 `DISCOVERED` CandidateJob；用户手动粘贴或导入的 `JobPosting` 也可以通过 `POST /api/candidates` 幂等创建 `SAVED` CandidateJob，因此申请闭环不依赖岗位发现功能先完成。

### 5.6 M10 岗位发现与来源同步

M10 已完成官方官网即时搜索闭环。用户在岗位发现页输入自然语言目标并多选公司范围，系统只访问所选公司在项目内登记的官方招聘入口，优先调用字节跳动、腾讯专用公开职位 Adapter，再回退到受控的官网页面读取。每次最多整理 20 条岗位，按公司、地点、招聘类型和岗位方向划分为严格匹配和拓展候选，仅严格匹配中的前 5 条在后台自动分析。搜索是用户即时触发的一次性任务，不做每日定时同步；每次运行保存查询目标、结果分层、分析完成数、失败摘要和 Agent 轨迹。

```text
用户输入自然语言求职目标
→ 用户多选公司范围
→ 官方公司来源注册表按 company_ids 建立访问白名单
→ URL / DNS / 重定向安全检查
→ 专用来源 Adapter / Official Company Adapter 读取公开职位接口或官网详情页
→ 公司、标题、地点、类型、正文标准化
→ 最多保留 20 条并按目标相关性排序
→ source_id + source_job_id / URL / 内容指纹去重
→ DiscoveryRun
→ JobPosting + DISCOVERED CandidateJob
→ Query Match Gate 划分严格匹配 / 拓展候选
→ 严格匹配前 5 条自动进入 JD Parser / Eligibility / Evidence Matcher
→ 拓展候选保留放宽原因，等待用户手动分析
→ 用户保存、忽略、查看分析或进入申请准备
```

发现流程不会自动创建 `Application`。即时搜索只对严格匹配中排序靠前的 5 条运行完整 JD 分析；拓展候选即使来自官方接口，也不会被描述成满足原始条件。字节跳动和腾讯来源通过公开职位接口返回可验证的职位 ID、标题、地点、职责和要求；地点、招聘类型或岗位方向不满足时，系统保留真实字段并记录“地点不匹配”“非校招”等原因。重复同步只更新 `last_seen_at` 和来源字段；岗位正文变化时，旧分析会失效并要求重新分析。读取失败会保存失败运行和摘要，超过运行时限的后台任务会被自动结束并允许重试；受限 URL 在发出实际请求前被拦截。所有来源均为 0 条时，页面进入人工接管，允许用户粘贴具体 JD 继续完整分析。原有 `POST /api/discovery/runs` Greenhouse 入口继续保留，作为指定来源的高级路径。

### 5.7 Event and Trace Log

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
本次允许访问哪些来源与工具
工具是否成功
工具耗时、输出数量和稳定错误码
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

第一版最重要的人工确认场景是创建申请、采用简历修改建议、批准冻结投递包，以及凭真实提交凭证确认投递。

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

材料建议请求使用 `SuggestionTargetInput` 显式提供 `original_text`、`target_type` 和可选 `target_label`；`ResumeSuggestion` 关联当前用户、Application 和 JobAnalysis，保存目标、原文、建议文本、引用证据、审批状态及最终文本。真实投递使用 M14 的 `ResumeAsset / ResumeVersion`，并把文件哈希和版本身份冻结进 M15 投递包。

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

- 用户用自然语言描述想找的岗位；
- 官方公司来源范围和只读安全说明；
- 最近一次即时搜索的发现、去重和自动分析进度；
- 岗位发现候选池；
- 岗位来源和最近更新时间；
- 岗位基本信息；
- 来源链接；
- 地点和招聘类型等基础字段；
- 保存、忽略和进入岗位分析操作；
- 最近的 DiscoveryRun 搜索轨迹；
- 指定 Greenhouse 来源的高级入口。

岗位发现页只自动分析严格匹配中排序靠前的 5 条；用户点击“进入分析”后，可以查看或重新运行任意岗位的完整 JD 解析、资格检查和证据匹配流程。

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
    DISCOVERY --> GATE["Deterministic Query Match Gate"]
    GATE -->|"Strict: top 5"| ANALYSIS
    GATE -->|"Expanded: manual"| HUMAN["Human Review"]

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
- 判断岗位与求职目标的语义相关性；
- 解析非结构化 JD；
- 判断岗位要求与经历之间的语义关系；
- 解释匹配结论；
- 生成材料修改建议。

### 确定性代码负责

- 数据模型校验；
- 生成并校验来源白名单、工具预算和停止条件；
- 判断页面类型并执行招聘来源注册和 Adapter 路由；
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

- 支持用户用自然语言填写求职意向；
- 支持从 40 家已登记公司官方招聘入口尝试即时发现公开岗位；
- 每次搜索最多保留 20 条，并持久化严格匹配 / 拓展候选及放宽原因；
- 仅严格匹配中的前 5 条自动分析，拓展候选默认等待用户手动确认；
- 支持搜索进度、来源失败隔离和运行轨迹；
- 支持岗位链接和文本直接导入；
- 实现手动文本和通用 HTML 两种读取方式；
- 支持基础字段标准化、筛选和内容指纹去重。

扩展目标：

- 覆盖 5～10 个招聘来源；
- 收集并解析 100～300 条真实岗位；
- 支持简单定时同步和岗位变化检测；
- 增加 Embedding 召回和 Playwright 动态页面回退。

当前适配器：

```text
OfficialCompanyRegistryAdapter
ByteDanceAdapter
TencentAdapter
GreenhouseAdapter
GenericHtmlAdapter
```

M10 通过项目内的公司来源注册表限定官方招聘入口，不调用第三方搜索服务，也不承诺搜索整个互联网。`ByteDanceAdapter` 和 `TencentAdapter` 分别调用两家公司公开职位接口，并对岗位 ID、招聘类型和字段证据做确定性校验；通用读取器只接受 JSON-LD `JobPosting` 或具备具体职位路径和职责/要求信号的页面，并排除招聘指南、流程、FAQ、活动、职位列表等非岗位页。依赖 JavaScript 且未提供可直接读取岗位数据的官网会记录“需要专用 Adapter”，不会把页面外壳保存成岗位。搜索只在用户点击后即时执行，不做每日定时同步；动态页面浏览器回退、定时同步和更多 ATS 适配器仍是后续扩展，不作为核心 MVP 的完成条件。Greenhouse board URL 仍可通过高级入口直接同步。

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

核心 MVP 已建立 12 条合成开发 Fixture 和 39 条公开岗位严格评测子集；后者采用规则标签与人工覆盖，并排除待复核或正文不可见字段。数据集具有版本、标注说明和固定格式，并区分开发样本与 `eval` 样本；正常、字段缺失、`unknown`、无证据、读取失败和非法模型输出均预先规定最小样本分布。若用于论文式公开比较，还需独立人工复核并报告标注一致性。

最终运行前冻结 Evaluation Manifest、指标口径和发布阈值，不能查看最终结果后再修改通过标准。原始模型输出和 Validator 后用户可见输出分别报告；用户可见 Unsupported Claim Rate 的发布要求为 0。评测结果同时记录模型、提示词、数据集版本、随机参数、运行时间和失败数，不在简历中使用未经实际运行的指标。

2026-08-09 使用 `deepseek-v4-flash` 对同一份 39 条严格子集完成真实运行：

| Parser | 成功率 | Macro-F1 | 超时率 |
|---|---:|---:|---:|
| Core | 100% (39/39) | 0.9890 | 0% (0/39) |
| Staged（Core + Detail + 本地组装） | 100% (39/39) | 0.9897 | 0% (0/39) |

这是 parser-only 字段评测，`supported_claim_count=0`，因此不能把报告中的 `Unsupported Claim Rate=0` 解读为完整证据匹配链“0% 幻觉”。公开精简报告见 [`docs/evaluation/m11-ai-campus-39-summary.json`](docs/evaluation/m11-ai-campus-39-summary.json)。

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
- Playwright，动态岗位页的只读验证兜底
- Embedding，可选

### 任务与测试

- 平台定时任务或独立同步命令，作为扩展能力
- Pytest
- Playwright Test，用于可重复的关键用户流程验收和演示素材生成
- 结构化日志

核心 MVP 不强制使用 LangGraph、Temporal、Redis 或独立向量数据库。如果工具选择和人工中断流程后续变复杂，再评估引入 LangGraph；如果需要跨月等待、外部事件唤醒和复杂故障恢复，再评估 Temporal。

Python 环境统一使用 `uv` 管理，提交 `pyproject.toml` 和 `uv.lock`，不维护单独的 `requirements.txt`。所有 Python 命令通过 `uv run` 执行。

本地后端开发：

```text
uv sync
uv run playwright install chromium
uv run alembic upgrade head
uv run uvicorn src.main:app --reload --host 127.0.0.1 --port 18001
uv run pytest
uv run ruff check src tests migrations
```

M14 私密材料的本地配置：

```text
PRIVATE_STORAGE_DIR=./data/private
RESUME_MAX_BYTES=5242880
```

`PRIVATE_STORAGE_DIR` 必须指向后端可写且不会由 Web Server 公开托管的目录。默认目录已加入 `.gitignore`；生产部署仍需使用受控持久卷、真实认证、备份和删除策略。

本地前端开发：

```powershell
Set-Location frontend
Copy-Item .env.example .env.local
npm install
npm run dev
```

前端默认运行在 `http://localhost:3000`，后端统一运行在 `http://127.0.0.1:18001`。如果端口被占用，一键启动脚本会在启动前直接报告冲突，不会留下不可见的半启动进程。生产构建和 TypeScript 检查：

```powershell
npm run typecheck
npm run build
```

完成后可以返回项目根目录：

```powershell
Set-Location ..
```

Windows 下也可以从仓库根目录一键完成依赖同步、数据库迁移并启动前后端：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start-dev.ps1
```

打开 `http://localhost:3000`。脚本会在前台运行 Next.js，并在退出时停止由它启动的后端；后端日志写入系统临时目录。

需要改端口时显式传入参数，前端 API 地址会随之更新：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start-dev.ps1 `
  -BackendPort 18002 -FrontendPort 3001
```

可重复的浏览器验收与作品集素材生成：

```powershell
Set-Location frontend
npx playwright install chromium
npm run test:e2e
Set-Location ..
powershell -ExecutionPolicy Bypass -File scripts/capture-demo.ps1
```

普通 E2E 不请求真实招聘网站，也不会改写演示素材；`capture-demo.ps1` 才会更新 `docs/assets/` 下的 PNG 和 GIF。

### SQLite-first 本地开发

默认配置使用 SQLite，适合先完成用户画像、岗位分析、资格判断、证据匹配和申请状态机，不需要安装数据库服务。数据库文件会自动创建在 `./data/jobflow.db`，并被 Git 忽略。

```powershell
Copy-Item .env.example .env
uv sync
uv run alembic upgrade head
uv run uvicorn src.main:app --reload --host 127.0.0.1 --port 18001
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

当前 M02 使用 SQLite 保存用户画像和经历证据。API 通过 `X-User-ID` 识别本地用户；不传该请求头时使用 `.env` 中的 `DEFAULT_USER_ID`，默认值为 `local-user`。这只是开发阶段的身份占位，不等同于生产认证。公开部署前必须由可信反向代理或身份提供方完成认证，并剥离客户端自行传入的身份头；本地作品集阶段不伪装成已实现多用户认证。

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

M04 提供同步解析接口 `POST /api/jobs/{job_id}/parse`。默认使用 Fake Client，便于本地重复演示；设置 `STRUCTURED_MODEL_PROVIDER=openai_compatible` 后，可通过 `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`、`LLM_RESPONSE_FORMAT` 和 `LLM_TIMEOUT_SECONDS` 接入 OpenAI-compatible 结构化模型。`LLM_RESPONSE_FORMAT=auto` 会为 DeepSeek 选择 `json_object`，其他兼容服务默认使用 `json_schema`；无论供应商响应格式如何，最终都必须经过 Pydantic 和原文证据校验。`JobParseResult` 保存与用户无关的岗位级解析缓存，`AgentRun` 记录用户、运行类型、目标实体、状态、模型、提示词版本、输入哈希、输出校验结果、起止时间、耗时和错误。M11 负责将这些运行记录与数据集版本组合成可重复评测，而不是到 M11 才首次加入运行轨迹。

M04 不负责完整分析持久化；M07 在 Parser、Eligibility 和 Evidence 接口稳定后实现 `JobAnalysis`，统一保存解析、资格、证据匹配和评分结果。

M04 的真实模型验收已完成：使用 DeepSeek `deepseek-v4-flash` 对 AI/RAG 实习、校招后端和搜索算法三类中文 JD 运行了完整解析与分析链路。验收记录见 [`docs/REAL_MODEL_ACCEPTANCE.md`](docs/REAL_MODEL_ACCEPTANCE.md)。

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

### M08 申请状态机与事件

M08 已实现 `CandidateJob`、`Application` 和 `DomainEvent` 的 SQLite 持久化，以及显式的候选岗位和申请状态转换表。用户从岗位分析页点击“准备申请”后，系统在同一事务内将候选岗位转换为 `CONVERTED`、创建唯一的 `PREPARING` 申请并写入 `ApplicationCreated` 事件；重复请求只返回已有申请。

申请状态可通过人工确认推进到 `SUBMITTED`、`ASSESSMENT`、`INTERVIEW`、`OFFER`、`REJECTED` 或 `WITHDRAWN`。所有读写都按当前用户归属过滤，非法转换返回结构化冲突错误。前端申请看板展示按状态分组的申请卡片、下一步动作、可用转换和申请事件时间线，Agent 不直接执行投递或修改状态。

### M09 材料建议与审批

M09 已实现 `SuggestionTargetInput`、`ResumeSuggestion` 和 `SuggestionService`。建议请求必须由用户提供明确的原文、目标类型和可选标签；系统自动绑定当前岗位最新有效的 `JobAnalysis`，模型只能从当前用户的经历证据中选择引用。建议生成会复用 M04 的 `StructuredModelClient` 和 `AgentRun`，Fake 与 OpenAI-compatible Client 使用同一个结构化输出契约。

建议只以 `PENDING` 状态保存。用户可以直接接受、编辑后接受或拒绝；前两者分别保存模型建议文本或用户编辑后的 `final_text`，拒绝时 `final_text` 保持为空。审批状态和 `SuggestionDecisionRecorded` 事件在同一事务内保存，事件只记录决策元数据和最终文本哈希，不保存材料正文。岗位看板的材料建议区展示原文、Agent 建议、证据数量、Diff 编辑区和审批结果。

### M10 岗位发现池与来源安全

M10 已完成 `SafeHTTPReader`、Generic HTML / JSON-LD 提取、`JobSourceAdapter`、`OfficialCompanyRegistryAdapter`、`GreenhouseAdapter`、字节跳动 / 腾讯专用 Adapter、40 家官方来源注册表、`DiscoveryRun` 和岗位发现页。发现搜索是用户手动触发的只读流程：网络请求前先保存经过 Schema 校验的 `search_plan`，锁定来源白名单、逐来源工具顺序、Top 20 / Top 5 预算和停止条件；执行轨迹保存每一步耗时、输出数量、错误码和真实回退顺序。系统限制协议、端口、凭据、DNS 解析结果、重定向、响应大小、超时和重试次数；页面正文中的脚本、样式、隐藏元素不会进入岗位原文。通用规则会拒绝招聘指南、投递流程、FAQ、活动和列表页；动态页面无法静态取得具体岗位时会记录来源失败并提示需要专用 Adapter。每次搜索最多保存 20 条岗位，持久化严格匹配 / 拓展候选及原因，并只自动分析严格匹配前 5 条；结果使用来源岗位 ID、规范 URL 和内容指纹按优先级去重，首次发现创建 `DISCOVERED` 候选，重复运行不会创建重复 `JobPosting` 或 `Application`。

如果本机使用 Mihomo/Clash 的 Fake-IP DNS，设置 `URL_FETCH_PROXY=http://127.0.0.1:7890` 后，读取器会通过显式本地代理访问官网。`URL_FETCH_PROXY_ALLOW_UNLISTED_HOSTS` 默认关闭；本地开发需要跟随官网跳转到飞书招聘、热招网等外部招聘域名时可以显式设为 `true`。该模式仍拒绝本机/内网字面量 IP、异常端口、带凭据 URL，并限制协议和重定向次数；生产环境应优先使用 `redir-host` 或维护明确的外部来源白名单。

```text
POST /api/jobs/import-url
POST /api/discovery/runs
POST /api/discovery/search
GET  /api/discovery/runs
GET  /api/discovery/runs/{run_id}
GET  /api/candidates?status=DISCOVERED
```

### M11 评测与可重复演示

M11 把评测做成独立、可版本化的模块，而不是把演示样例当成效果指标。当前已加入 `EvaluationManifest`、真实/Fixture prediction 生成入口、字段/资格/证据指标、失败码准确率、Evidence Validator 后的用户可见结果、AgentRun 汇总和可重复的机器可读报告。真实产品分析使用 `StagedJDParser`：先用 `CoreJDParser` 抽取核心字段，再用 `DetailJDParser` 抽取详情，最后由本地规则生成完整 `StructuredJobDescription`。除 12 条合成开发 Fixture 外，仓库已完成 39 条经严格筛选的公开中文 AI 校招岗位评测，并用 Playwright fixture 固化严格 / 拓展结果的关键用户流程。

```text
uv run python -m src.evaluation.run --manifest datasets/m11_evaluation_manifest.json --predictions datasets/m11_sample_predictions.json --output artifacts/evaluation/m11-dev-report.json --model sample-fixture --prompt-version m11-dev-v1
```

真实 prediction 生成命令、指标口径和 39 条结果见 [`docs/EVALUATION.md`](docs/EVALUATION.md) 与 [`docs/evaluation/m11-ai-campus-39-summary.json`](docs/evaluation/m11-ai-campus-39-summary.json)。开发预测夹具故意包含错误，只用于验收评测器能发现资格误接受和非法证据，不能作为模型效果或简历数据。

### M12 Discovery Agent 控制面评测

M12 用 13 个离线确定性场景单独验证 Agent 控制面，不把固定 Fixture 当成真实官网搜索效果。场景覆盖来源白名单和 SSRF 阻断、字节/腾讯专用 Adapter 路由、Adapter 失败与空结果回退、单来源故障隔离、动态页面和招聘指南拒收、人工 JD 接管、Top20 / Top5 预算门控，以及重复发现的状态幂等性。

当前固定版本 13/13 场景通过：来源越权访问率 0% (0/2)、轨迹完整率 100% (11/11)、工具路由准确率 100% (9/9)、回退正确率 100% (3/3)、非岗位误收率 0% (0/2)、人工接管准确率 100% (2/2)、预算合规率 100% (2/2)、状态一致率 100% (1/1)。这些比例只适用于已列明的离线控制面场景，不代表真实官网召回率或完整 Agent 准确率。

```text
uv run python -m src.evaluation.discovery_agent --manifest datasets/m12_discovery_agent_manifest.json --output docs/evaluation/m12-discovery-agent-summary.json --markdown docs/DISCOVERY_AGENT_EVALUATION.md
```

完整指标口径、逐场景结果和限制见 [`docs/DISCOVERY_AGENT_EVALUATION.md`](docs/DISCOVERY_AGENT_EVALUATION.md)。

### M13 可信岗位线索与验证

M13 与 `v0.2 Trusted Discovery` 已完成。官方 Adapter、外部 Agent、第三方链接和手动导入统一经过同一条可信边界：

```text
Official Adapter / External Agent / Manual URL / Third-party URL
→ JobLead
→ LeadVerification
→ verified: JobPosting + DISCOVERED CandidateJob
→ dynamic: read-only Browser Handoff → 同一验证边界
→ rejected / needs user / failed: 保留线索和验证记录，不创建正式岗位
```

统一 `LeadProvider` 协议只返回 `LeadCandidate`，不能写正式岗位。`OfficialAdapterLeadProvider` 把 Greenhouse、ByteDance、Tencent 和公司注册表接入该协议；`ExternalAgentProvider` 接收 URL、搜索摘要、推测公司/标题和发现时间；`ManualImportProvider` 同时负责手动 URL 与完整 JD 接管。外部 API 不允许声明 `official_adapter`。

`JobLead` 保存 Provider、原始 URL、规范 URL、来源岗位 ID、搜索摘要和用户归属。搜索摘要、公司提示和岗位提示只留在线索层，不能成为 `JobPosting` 事实。URL 或浏览器验证会重新执行 SSRF 防护、正文清洗和具体岗位页判断，并从页面正文、JSON-LD 或官方 Adapter 载荷重新验证公司、标题、地点、招聘类型、届别和岗位要求。每个字段的值、来源类型、原文片段和字符位置保存在不可变的 `LeadVerification.field_evidence` 中。只有验证成功后，系统才按来源岗位 ID、规范 URL 和正文哈希创建或关联 `JobPosting`。

```text
JobLead: NEW → VERIFYING → VERIFIED / DUPLICATE
                            NEEDS_BROWSER / NEEDS_USER
                            REJECTED_NON_JOB / FAILED

JobPosting.verification_status:
VERIFIED_OFFICIAL / VERIFIED_SOURCE / USER_PROVIDED / LEGACY_UNVERIFIED

JobPosting.availability_status:
ACTIVE / UNKNOWN / STALE / CLOSED
```

线索验证使用原子状态抢占；并发请求只有一个执行者能从可重试状态进入 `VERIFYING`，其余请求返回冲突，避免重复验证记录和正式岗位。来源岗位 ID、规范 URL 与内容指纹共同去重，低信任手动内容不能覆盖已验证的官方正文或降低验证等级。

动态页接管使用服务端 Playwright，只读取一个已绑定线索 URL 的可见正文，不登录、不填写、不下载、不提交。每个导航和子资源请求仍经过 URL 安全检查；遇到登录、CAPTCHA、Cloudflare、安全检查或 2FA 时进入 `NEEDS_USER` 并留存失败记录。它与 M18 的申请表填写自动化是两项独立能力。

岗位可用性由 `JobAvailabilityCheck` 留下不可变审计记录。第一次和第二次读取失败进入 `UNKNOWN`，连续第三次失败进入 `STALE`；普通读取失败永远不能自动关闭岗位。只有页面出现明确关闭文本或用户提交带原因的人工确认才能进入 `CLOSED`。重新读到具体岗位页或人工确认开放后可恢复 `ACTIVE`。迁移 `0014_job_availability_audit` 保存连续失败次数、最后检查时间和关闭时间。

当前线索 API：

```text
POST /api/discovery/leads
GET  /api/discovery/leads
GET  /api/discovery/leads/{lead_id}
POST /api/discovery/leads/{lead_id}/verify
POST /api/discovery/leads/{lead_id}/handoff/browser
POST /api/discovery/leads/{lead_id}/handoff/manual-jd
POST /api/jobs/{job_posting_id}/availability/check
POST /api/jobs/{job_posting_id}/availability/confirm
GET  /api/jobs/{job_posting_id}/availability/checks
```

外部调用方只能提交 `external_agent`、`manual_url` 或 `third_party` 线索，不能声明自己是官方 Adapter，也不能直接修改验证状态。每条线索根据当前状态返回结构化 `next_action`，用于区分验证、重试、打开浏览器、提供完整 JD 和查看正式岗位。重复提交、重复验证和重复接管是幂等的；岗位、验证记录、候选岗位和发现事件在同一事务中提交。迁移会把历史官方 Adapter 岗位标记为 `VERIFIED_OFFICIAL`，手动文本标记为 `USER_PROVIDED`，其余无法确认的数据保守标记为 `LEGACY_UNVERIFIED`。

岗位发现页提供 URL 线索录入、待处理/需接管/已验证筛选、正文验证、只读浏览器验证、原页跳转和粘贴 JD 接管。岗位卡片展示来源验证状态、开放状态、连续读取失败次数和最后检查时间，并可手动重新检查。浏览器无法验证时，用户仍可从原线索粘贴完整 JD；系统生成 `USER_PROVIDED / UNKNOWN` 岗位，保留原线索和验证历史，再继续 Parser、Eligibility 与 Evidence 流程。

M13 的 9 个离线确定性场景全部通过：官方验证率 100%、非岗位误收率 0%、去重准确率 100%、搜索摘要污染率 0%、可用状态准确率 100%、浏览器接管成功率 100%。这些数字只代表版本化 Fixture，不代表真实官网召回率或任意网站兼容性。复现命令与完整口径：

```text
uv run python -m src.evaluation.trusted_discovery --manifest datasets/m13_trusted_discovery_manifest.json --output docs/evaluation/m13-trusted-discovery-summary.json --markdown docs/TRUSTED_DISCOVERY_EVALUATION.md
```

完整报告见 [`docs/TRUSTED_DISCOVERY_EVALUATION.md`](docs/TRUSTED_DISCOVERY_EVALUATION.md) 与 [`docs/evaluation/m13-trusted-discovery-summary.json`](docs/evaluation/m13-trusted-discovery-summary.json)。

### M14 候选人私密档案与材料库

M14 已完成。申请准备资料不再写入现有公开 `UserProfile`，而是进入独立的私密边界：

```text
CandidatePrivateProfile
├── contact_email / contact_phone
├── current_status / availability_date
├── work_authorization / sponsorship_required
├── salary_strategy / relocation_willing
└── voluntary_disclosure_policy（只保存策略）

ResumeAsset ── file identity / MIME / size / SHA-256 / private storage key
    └── ResumeVersion ── version / job family / source version / reason / default

AnswerBankEntry ── normalized question / confirmed answer / scope / sensitivity
```

每个高影响档案字段都由状态和值组成，状态固定为：

```text
missing            没有事实，必须返回 needs_confirmation
provided           只能在同时存在合法值时使用
not_applicable     用户已明确该字段不适用
declined_to_store  不保存具体值，真实使用时再次向用户确认
```

`provided` 没有值，或其他状态暗带具体值，都会被 API 拒绝。档案响应统一返回 `readiness` 和逐字段 `needs_confirmation`；Agent 没有可用状态去表达“猜测值”。自愿身份披露默认只保存 `ask_each_time / prefer_not_to_answer / allow_user_entry` 处理策略，不提供默认保存具体身份答案的字段。

简历文件只接受 MIME、扩展名和文件魔数相互匹配的 PDF 或 DOCX，默认上限 5 MB。文件内容写入 `PRIVATE_STORAGE_DIR`（默认 `./data/private`），不在前端静态目录中；数据库只保存文件身份和相对存储标识。上传时按 SHA-256 做当前用户内去重，存储目录使用用户标识哈希，下载、建版本、设默认版本都重新检查用户归属。`ResumeVersion` 记录用户级递增版本号、岗位族、来源版本和生成原因，第一份版本自动成为默认版本。

答案库要求每次创建或修改都显式提交 `confirmed: true`，并重新记录确认时间。问题会规范化后按用户和适用范围去重；适用范围支持通用、岗位族、公司和具体岗位，敏感级别支持普通、个人信息和高影响。联系方式、简历正文和答案内容不会写入普通请求日志或 `DomainEvent`。

M14 API：

```text
GET    /api/private-profile
PUT    /api/private-profile
POST   /api/resumes/assets
GET    /api/resumes/assets
GET    /api/resumes/assets/{asset_id}/download
POST   /api/resumes/versions
GET    /api/resumes/versions
PATCH  /api/resumes/versions/{version_id}
POST   /api/answer-bank
GET    /api/answer-bank
PATCH  /api/answer-bank/{answer_id}
DELETE /api/answer-bank/{answer_id}
```

前端“投递资料”工作区按私密档案、简历版本、答案库三步组织。缺失和拒绝保存状态始终可见；简历文件与版本分开登记；答案编辑后必须再次勾选确认。后端测试覆盖跨用户访问、状态和值一致性、文件 MIME/大小/内容、哈希重复、敏感日志和高影响字段缺失，Playwright 同时覆盖桌面与移动端流程。

### M15 可审核冻结投递包

M15 已完成。投递准备不再引用一组会随时变化的资料，而是批准一个明确修订：

```text
ApplicationPacket ── user / application / job / current revision
    └── PacketRevision R01
        ├── JobPosting snapshot + JD content hash
        ├── valid JobAnalysis snapshot + analysis input hash
        ├── CandidatePrivateProfile revision + frozen values
        ├── ResumeVersion + file SHA-256 identity
        ├── selected evidence / confirmed form answers / open questions
        ├── risks / confirmation items / approval blockers
        └── payload hash + source fingerprint

PacketDecision ── one user approval audit record per revision
```

修订状态固定为：

```text
DRAFT → NEEDS_REVIEW → APPROVED → SUPERSEDED
```

用户或 Agent 可以生成和更新 `DRAFT`，但 Agent 不能确认开放题或批准修订。进入 `NEEDS_REVIEW` 后，服务会在批准时重新核对 JD 哈希、有效分析、私密画像修订、简历文件身份、经历证据和答案确认时间。资格未知或失败、私密画像未完成、简历缺失、敏感答案未确认、必备经历证据缺失、分析失效或任何来源漂移都会阻止批准。

审批使用 `status = NEEDS_REVIEW` 条件更新，并对同一修订的决定类型设置唯一约束；并发和重复批准最多生成一条 `PacketDecision`，重复请求返回同一个已批准结果。`APPROVED` 修订不能通过编辑 API 原地修改。岗位、画像、简历、证据或答案变化时，读取结果会显示 `source_changed`；创建新修订会冻结当前资料，并将上一批准版本转为 `SUPERSEDED`。普通 `DomainEvent` 只记录投递包、修订和决定 ID，不写入联系方式、简历内容或答案。

M15 API：

```text
POST   /api/applications/{application_id}/packet
GET    /api/application-packets
GET    /api/application-packets/{packet_id}
GET    /api/packet-revisions/{revision_id}
PATCH  /api/packet-revisions/{revision_id}/items
POST   /api/packet-revisions/{revision_id}/review
POST   /api/packet-revisions/{revision_id}/approve
POST   /api/application-packets/{packet_id}/revisions
```

前端“投递审核”工作区提供申请索引、修订历史、JD 快照、简历版本差异身份、证据来源、表单答案、开放题、风险和阻塞登记。批准按钮只在当前修订无阻塞且来源未变化时可用，桌面和移动端都覆盖生成、审核和批准流程。

`APPROVED` 只表示材料修订已经由用户批准，不表示真实招聘网站已经收到申请，也不会把现有 `Application` 推进到 `SUBMITTED`。

### M16 投递尝试、阻塞与提交凭证

M16 已完成。每个投递尝试固定绑定当前用户、`Application`、`JobPosting`、官方申请 URL 和当前已批准的 `PacketRevision`：

```text
ApplicationAttempt
├── CREATED → FORM_IN_PROGRESS
├── NEEDS_USER / BLOCKED → FORM_IN_PROGRESS
├── FORM_IN_PROGRESS → READY_TO_SUBMIT
└── READY_TO_SUBMIT + valid SubmissionReceipt → SUBMITTED

ApplicationBlocker
└── category / observation / stop reason / retryable / next strategy / required user action

SubmissionReceipt
└── confirmation text / confirmation URL / application number / redacted screenshot metadata / receipt hash
```

通用申请状态接口会拒绝 `PREPARING → SUBMITTED`。用户必须先打开官网并记录 `FORM_IN_PROGRESS`，解决所有开放阻塞，完成执行检查，再从真实成功页保存凭证。仅确认 URL 不足以构成凭证；确认文本必须包含明确成功语义，或提供申请编号、符合约束的脱敏截图元数据，并由用户明确确认。保存凭证后申请仍保持 `PREPARING`，最终确认接口才会在一个事务中条件更新 Attempt 和 Application。

M16 API：

```text
POST  /api/packet-revisions/{revision_id}/attempts
GET   /api/application-attempts
GET   /api/application-attempts/{attempt_id}
PATCH /api/application-attempts/{attempt_id}/status
POST  /api/application-attempts/{attempt_id}/blockers
POST  /api/application-attempts/{attempt_id}/blockers/{blocker_id}/resolve
POST  /api/application-attempts/{attempt_id}/receipt
POST  /api/application-attempts/{attempt_id}/finalize
```

数据库使用 Attempt 创建幂等键、申请与投递包版本唯一约束、每个 Attempt 一份 Receipt 以及每个 Application 一份 Receipt，配合条件状态更新防止刷新、重试或并发确认生成重复记录。`DomainEvent` 只保存 Attempt、Blocker、Receipt 和 PacketRevision 的 ID、状态及校验类型，不写确认文本、申请编号或截图信息。前端“投递执行”工作区提供执行清单、官方地址、阻塞队列、凭证录入和最终确认，桌面与移动端均有 Playwright 覆盖。

当前用户隔离仍建立在本地开发用 `X-User-ID` 上，不等同于生产认证。公开多用户部署前必须由可信身份层生成用户身份并移除客户端伪造请求头的能力。

### M17 跟进中心

M17 已完成。提交后的测评、笔试、面试、材料截止和主动联系统一记录为 `FollowUpTask`，并与具体 `Application` 和 `JobPosting` 绑定：

```text
FollowUpTask
├── event type: ASSESSMENT / WRITTEN_TEST / INTERVIEW
│               MATERIAL_DEADLINE / OUTREACH / CUSTOM
├── schedule: UTC time + IANA timezone + local display time
├── context: contact / channel / next action / private notes
└── PENDING → COMPLETED / CANCELLED
        └── OVERDUE 由当前时间动态计算，不持久化
```

只有处于 `SUBMITTED / ASSESSMENT / INTERVIEW / OFFER` 的申请可以创建跟进任务。创建、编辑、完成和取消都会写入现有 Application 时间线，但提醒状态不会自动改变 Application 状态；联系人、联系方式、下一步动作和备注正文不会进入普通 `DomainEvent`。重复请求通过显式幂等键和自然身份约束去重，完成与取消都是不可逆终态。

M17 API：

```text
GET   /api/follow-ups
GET   /api/follow-ups/summary
GET   /api/follow-ups/{task_id}
GET   /api/applications/{application_id}/follow-ups
POST  /api/applications/{application_id}/follow-ups
PATCH /api/follow-ups/{task_id}
POST  /api/follow-ups/{task_id}/complete
POST  /api/follow-ups/{task_id}/cancel
```

前端“跟进中心”提供今日、逾期、未来 7 天、未来 30 天和全部记录视图，并支持 30 天日期矩阵、按申请筛选、任务创建与编辑、完成和取消。时间范围使用用户指定的 IANA 时区和左闭右开日期边界。系统暂不监听邮箱或短信；外部消息必须由用户确认后手动录入。

后端测试覆盖时区午夜、日期边界、重复任务、跨用户访问、状态终态和事件脱敏；Playwright 覆盖桌面与移动端的完整任务生命周期、日期筛选、横向溢出和浏览器控制台错误。

### M18 有限 ATS 浏览器辅助

M18 已完成。系统只对 Greenhouse 和 Lever 两类结构相对稳定的 ATS 提供有限辅助，并复用 M16 的 `ApplicationAttempt`、`SubmissionReceipt` 与最终提交状态机：

```text
detect → inspect → map_fields → fill → verify
       → request_approval → submit → capture_receipt

INSPECTED → NEEDS_USER → READY_FOR_APPROVAL
          → AUTHORIZED → SUBMITTING → SUBMITTED / FAILED
```

`AtsAssistanceSession` 绑定用户、Attempt、岗位、已批准的 `PacketRevision`、申请 URL、ATS 类型、页面指纹和字段计划。系统只填写当前批准投递包中来源明确的值；个人信息、薪资、工作资格和法律确认等字段必须针对本次页面逐项确认。登录、CAPTCHA、Cloudflare、安全检查、2FA、必填值缺失、页面变化或上传/验证异常都会进入人工接管。

最终提交使用 `AtsSubmissionAuthorization`。原始令牌只返回一次，数据库仅保存 SHA-256 哈希；授权同时绑定岗位、URL、投递包版本、页面指纹和字段计划，并在浏览器点击提交前原子消费。刷新授权会撤销此前未使用令牌，令牌不能跨岗位、跨 Attempt 或跨投递包版本复用。

M18 API：

```text
GET  /api/ats-sessions
GET  /api/ats-sessions/{session_id}
POST /api/application-attempts/{attempt_id}/ats-session
POST /api/ats-sessions/{session_id}/retry
POST /api/ats-sessions/{session_id}/confirm-fields
POST /api/ats-sessions/{session_id}/authorization
POST /api/ats-sessions/{session_id}/submit
```

成功页必须产生可验证确认文本、确认 URL 或申请编号，随后沿用 M16 的 Receipt 校验与 `finalize_submission`；普通感谢页、伪成功页或任何不确定结果都不会创建 Receipt，也不会把 Application 标记为 `SUBMITTED`。提交结果不确定时禁止自动重试，必须先在官网人工核对。

前端“浏览器辅助”工作区提供 Attempt 队列、八阶段执行轨道、字段来源/风险/动作表、敏感字段确认、人工接管、最终摘要、一次性授权和凭证状态。Fixture 测试覆盖 Greenhouse/Lever 字段映射、简历上传、下拉框、CAPTCHA、跨用户隔离、授权撤销与消费、页面变化、伪成功页和执行器异常；Playwright 覆盖桌面与移动端。当前不支持任意网站、Workday、登录态接管或无人值守批量投递，也不绕过任何反自动化控制。

### M19 端到端评测与安全加固（进行中）

M19 第一批已完成。版本化 [`m19_assisted_apply_manifest.json`](datasets/m19_assisted_apply_manifest.json) 包含 14 个离线结构化 Mock ATS 场景，覆盖 Greenhouse/Lever、简历上传验证失败、非简历文件控件、原生/自定义下拉框、开放题缺失、敏感字段确认、登录、CAPTCHA、2FA、权限、安全检查、页面变化、明确成功、失败和伪成功。重复提交继续由 M18 的一次性授权服务测试覆盖。

评测命令：

```text
uv run python -m src.evaluation.assisted_apply `
  --manifest datasets/m19_assisted_apply_manifest.json `
  --output artifacts/evaluation/m19-assisted-apply-report.json `
  --markdown docs/evaluation/m19-assisted-apply-summary.md
```

当前固定 Fixture 为 14/14，通过字段填写准确率、简历版本准确率、人工接管准确率和凭证覆盖率四个阈值；敏感字段误填率与错误标记为已提交的比例均为 0。以上数字只代表冻结的结构化 Fixture，不代表真实 ATS 兼容率、真实投递成功率或线上耗时。真实操作数据使用 `src.evaluation.application_operations` 从 `Application.created_at`、Attempt `ready_at`、Blocker 和敏感字段确认记录计算：

```text
uv run python -m src.evaluation.application_operations `
  --user-id local-user `
  --output artifacts/evaluation/application-operations.json
```

账户数据生命周期 API：

```text
GET    /api/account/data-summary
POST   /api/account/export     {"confirmed": true}
DELETE /api/account            {"confirmation": "DELETE_MY_DATA"}
```

导出结果是 `no-store` ZIP，包含版本化 JSON 清单和经过哈希复核的原始简历文件；内部 `storage_key` 不对外暴露。彻底删除会清除全部用户归属表、关联 Application、仅该用户占用的岗位/解析缓存和哈希私密目录，同时保留其他用户仍在引用的共享岗位事实。文件先移动到私密目录内的隔离区，数据库提交失败时恢复，提交成功后再销毁。

安全加固包括 JSON 日志中的密钥、令牌、邮箱和手机号脱敏；PDF 活动内容/加密/嵌入对象拒绝；DOCX 宏、嵌入对象、路径穿越、加密条目和异常解压大小拒绝；以及 DomainEvent/Discovery trace 敏感元数据扫描。`staging`/`production` 若仍允许 `X-User-ID` 或没有配置可信身份头，会直接返回 `503`。这只是可信反向代理的防误配契约，不等同于已经接入 OIDC 等真实身份提供方；服务必须部署在会删除客户端同名头并注入可信主体的网关之后。

M19 尚未完成的发布门槛只有两项：接入并实测真实身份提供方；在全新 PostgreSQL 环境执行迁移、后端测试和核心端到端测试。完成前 `v0.4 Assisted Apply` 不标记发布完成。

## 15. 安全与数据边界

第一版至少实现以下约束：

- 将岗位网页视为不可信内容，网页文本不能覆盖系统指令；
- 限制可访问 URL、协议和目标地址，阻止访问内网和本机资源；
- 为 HTTP 和浏览器工具设置超时、响应大小和重试上限；
- 读取发现任务时自动把超过 `DISCOVERY_RUN_TIMEOUT_SECONDS` 的遗留 `RUNNING` 任务标记为失败、写入恢复轨迹，并允许用户重试；
- 清理脚本、隐藏元素和与岗位无关的页面内容；
- 普通日志不保存完整简历、联系方式和其他敏感信息；
- 私密简历保存在非公开目录，API 不返回任意文件系统路径；
- 账户级导出和彻底删除由 M19 数据生命周期 API 管理；删除单条答案仍不等同于账户数据已彻底清除。

## 16. 推荐目录结构

```text
jobflow-agent/
├── src/
│   ├── api/
│   │   ├── dependencies.py
│   │   ├── profiles.py
│   │   ├── evidence.py
│   │   ├── jobs.py
│   │   ├── applications.py
│   │   ├── application_attempts.py
│   │   ├── application_packets.py
│   │   ├── follow_ups.py
│   │   ├── follow_up_schemas.py
│   │   ├── attempt_schemas.py
│   │   ├── materials.py
│   │   ├── materials_schemas.py
│   │   ├── packet_schemas.py
│   │   └── schemas.py
│   ├── domain/
│   │   ├── models.py
│   │   ├── runs.py
│   │   ├── analysis.py
│   │   ├── application.py
│   │   ├── application_attempt.py
│   │   ├── application_packet.py
│   │   ├── follow_up.py
│   │   ├── suggestion.py
│   │   ├── job.py
│   │   ├── eligibility.py
│   │   ├── matching.py
│   │   └── materials.py
│   ├── services/
│   │   ├── profile_service.py
│   │   ├── evidence_service.py
│   │   ├── core_jd_parser.py
│   │   ├── detail_jd_parser.py
│   │   ├── jd_parser.py
│   │   ├── staged_jd_parser.py
│   │   ├── job_parse_service.py
│   │   ├── eligibility_checker.py
│   │   ├── evidence_retriever.py
│   │   ├── evidence_matcher.py
│   │   ├── evidence_validator.py
│   │   ├── evidence_match_service.py
│   │   ├── jd_analysis_service.py
│   │   ├── application_service.py
│   │   ├── application_attempt_service.py
│   │   ├── follow_up_service.py
│   │   ├── suggestion_generator.py
│   │   ├── suggestion_service.py
│   │   ├── candidate_material_service.py
│   │   ├── application_packet_service.py
│   │   └── match_score.py
│   ├── infrastructure/
│   │   ├── database.py
│   │   ├── llm_client.py
│   │   └── __init__.py
│   ├── evaluation/
│   │   ├── agent_runs.py
│   │   ├── models.py
│   │   ├── metrics.py
│   │   ├── run.py
│   │   └── predict.py
│   └── main.py
├── frontend/
├── tests/
│   ├── test_end_to_end.py
│   ├── test_evaluation.py
│   └── test_evaluation_predict.py
├── datasets/
├── docs/
│   ├── DEVELOPMENT_WORKFLOW.md
│   └── EVALUATION.md
└── README.md
```

## 17. 开发阶段

具体模块边界、接口和完成标准见 [`docs/DEVELOPMENT_WORKFLOW.md`](docs/DEVELOPMENT_WORKFLOW.md)，当前开发进度见 [`TODO.md`](TODO.md)。

M01～M18 的本地闭环已经完成：39 条真实岗位 Parser 评测、13 个 Discovery Agent 控制面场景、9 个 Trusted Discovery 固定场景、Playwright E2E、字节跳动 / 腾讯专用 Adapter、统一线索验证、动态页只读接管、开放状态审计、私密候选人档案、简历版本、确认答案库、冻结投递包、人工投递尝试、真实凭证、提交后跟进中心，以及 Greenhouse / Lever 有限 ATS 辅助均已落地。真实 API 默认通过 Core + Detail + 本地组装生成完整 JD，旧的一次性 `JDParser` 只保留用于兼容和对照。这个结论限定于 SQLite 单机与离线 Fixture 场景；公开多用户部署仍需真实认证、部署环境迁移验证和更强的跨进程任务恢复。

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
→ 审批岗位定制建议和冻结投递包
→ 在官网手动提交并保存有效 Receipt
→ 事务确认 SUBMITTED 后继续推进 INTERVIEW
→ 展示完整业务时间线
```

### 阶段 C：轻量岗位发现

实现岗位链接读取、URL 安全检查、40 家官方招聘入口注册、字节跳动 / 腾讯专用 Adapter、官网岗位聚合、岗位标准化和去重、严格 / 拓展分层、严格匹配前 5 条自动分析以及岗位发现页。M13 已补齐多渠道 `JobLead`、正文验证、Playwright 动态页只读接管和岗位开放状态审计；每日定时同步仍是可选扩展。

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

多渠道线索、官方验证、岗位快照、变化检测和复杂 Playwright 动态页面回退从 M13 起按下述路线继续实现；第 2 个大厂专用来源已由 `TencentAdapter` 完成。

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
12. 用户批准一个内容与来源均冻结的投递包版本
13. 用户在官网手动填写，系统记录阻塞和执行检查
14. 用户真实提交后保存成功页确认信息
15. 系统验证 Receipt 并事务性确认 SUBMITTED
16. 用户在看板中继续跟踪测评和面试
17. 系统展示完整事件时间线
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
任何 SUBMITTED 都能追溯到批准版本、投递尝试和有效凭证
每个提交后的下一步动作都有明确时间、状态和申请时间线记录
业务事件和 Agent Trace 能够分别追踪
核心效果能够通过评测复现
```

本项目不追求成为完整招聘平台，而是完成一个范围清晰、结果可解释、具备人工控制的求职 Agent 产品闭环。

## 20. M13～M19 改造路线

下一阶段的产品目标是从“岗位分析与申请管理作品集”演进为可信的人机协同求职投递系统。核心策略是：

```text
宽发现、严验证
→ 先实现人工提交但系统全程管理
→ 再加入范围明确的浏览器辅助
```

### 20.1 改造原则

- 保留现有 Discovery、Parser、Eligibility、Evidence 和 Application 状态机；
- 外部 Agent、第三方平台和网页搜索只能提交 `JobLead`，不能直接创建可信 `JobPosting`；
- 搜索摘要不作为岗位事实，正式岗位必须经过正文读取、来源验证、标准化和去重；
- 使用独立的 `ApplicationPacket` 和 `ApplicationAttempt` 管理投递准备与表单执行，不把临时状态塞入现有 `Application`；
- Agent 只能提出建议，不能确认敏感事实或直接改变提交状态；
- `SUBMITTED` 必须绑定真实 `SubmissionReceipt`；
- 已批准的投递包不可原地修改，任何变更生成新版本；
- 不绕过登录、验证码、Cloudflare、反自动化控制或 2FA。

### 20.2 目标架构

```mermaid
flowchart LR
    INTENT["用户求职意图"] --> QUERY["DiscoveryRun / Search Plan"]
    QUERY --> OFFICIAL["Official / ATS Providers"]
    QUERY --> AGENT["External Agent Web Search"]
    QUERY --> MANUAL["Manual Import"]
    OFFICIAL --> LEAD["JobLead"]
    AGENT --> LEAD
    MANUAL --> LEAD
    LEAD --> VERIFY["Lead Verifier"]
    VERIFY -->|"verified"| JOB["JobPosting"]
    VERIFY -->|"needs help"| HANDOFF["Browser / User Handoff"]
    JOB --> ANALYSIS["Parser / Eligibility / Evidence"]
    ANALYSIS --> APPLICATION["Application"]
    APPLICATION --> PACKET["ApplicationPacket"]
    PACKET --> ATTEMPT["ApplicationAttempt"]
    ATTEMPT --> APPROVAL["Human Approval"]
    APPROVAL --> RECEIPT["SubmissionReceipt"]
    RECEIPT --> FOLLOWUP["Follow-up Timeline"]
```

`JobLead` 只是待验证线索；只有验证成功后才生成 `JobPosting` 并进入严格匹配和完整分析。外部 Agent 可以扩大岗位覆盖范围，但不能绕过系统的来源、证据和状态边界。

### 20.3 里程碑

| 里程碑 | 目标 | 主要成果 |
|---|---|---|
| M13 | 多渠道岗位发现与可信验证 | `JobLead`、`LeadProvider`、Verifier、外部 Agent 接入 |
| M14（已完成） | 候选人档案与材料库 | 私密画像、简历版本、答案库 |
| M15（已完成） | 可审核投递包 | `ApplicationPacket`、审批页、版本冻结 |
| M16（已完成） | 投递尝试与提交凭证 | Attempt、Blocker、Receipt |
| M17（已完成） | 跟进中心 | 测评、面试、截止日期、日历和待办 |
| M18（已完成） | 有限浏览器辅助 | Greenhouse / Lever ATS Adapter、一次性授权与人工接管 |
| M19 | 端到端评测与安全加固 | Mock ATS、投递指标、隐私和权限 |

详细任务、依赖关系和验收条件见 [`TODO.md`](TODO.md)。

### 20.4 版本切分

- `v0.2 Trusted Discovery`：完成 M13，形成多渠道发现、官方验证、统一入库的岗位入口；
- `v0.3 Verified Application Preparation`（已完成）：完成 M14～M17，支持人工提交但系统管理投递包、阻塞、凭证和跟进；
- `v0.4 Assisted Apply`：完成 M18～M19，在明确授权和可审计边界内辅助填写有限 ATS。

下一阶段仍不以自动海投量为成功标准。核心指标是岗位事实可验证、材料内容可追溯、敏感答案不被猜测、最终提交有明确授权，并且任何 `SUBMITTED` 状态都能找到真实凭证。
