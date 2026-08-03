# JobFlow Agent 轻量开发流程

本文档面向一个 2～4 周可完成的简历第二项目。目标是保留证据约束、人工审批、状态机、真实岗位发现和基础评测，同时减少不必要的分层、实体和基础设施代码。

## 1. 最终交付

核心演示链路：

```text
录入求职偏好和真实经历
→ 从 1 个真实招聘来源发现岗位
→ 选择岗位并解析 JD
→ 检查硬性资格
→ 引用经历证据解释匹配情况
→ 用户确认创建申请
→ 用户审批材料建议
→ 手动推进申请状态
→ 查看事件时间线和评测结果
```

岗位链接和粘贴 JD 作为直接入口。第 2 个招聘来源为可选项。

核心 MVP 不实现：

```text
LangGraph / Temporal / Redis
独立向量数据库和多 Agent
自动投递和完整简历版本系统
岗位历史快照和复杂可观测平台
```

## 2. 架构原则

### 2.1 轻量模块化单体

系统由 Next.js、FastAPI 和数据库组成。SQLite 用于本地 MVP，PostgreSQL + pgvector 用于需要接近部署环境、JSONB 或向量检索的阶段。后端保持一个部署单元，通过 `api / domain / services / infrastructure` 保持边界，不为每个小实体分别创建 Repository、Schema 和 Service 文件。

PostgreSQL 基础设施复用 Memory-RAG 的方案：使用 `pgvector/pgvector:pg16` Docker 镜像、固定数据库用户和数据库名、持久化卷以及 `pg_isready` 健康检查。JobFlow 的数据库访问仍使用 SQLAlchemy，表结构变更仍使用 Alembic；这里只复用数据库运行方式，不复用 Memory-RAG 的手写 SQL 存储层。

Python 环境统一使用 `uv` 管理。依赖声明写入 `pyproject.toml`，锁文件使用 `uv.lock`，不维护单独的 `requirements.txt`。所有 Python 命令通过 `uv run` 执行。

初始化和常用命令：

```text
uv python install 3.12
uv init --python 3.12
uv python pin 3.12
uv add fastapi "uvicorn[standard]" pydantic-settings sqlalchemy alembic psycopg[binary]
uv add --dev pytest pytest-asyncio ruff
uv sync
uv run pytest
uv run alembic upgrade head
```

`uv.lock` 应提交到版本库，`.venv`、`.env` 和本地数据库文件不提交。

前端使用 Node.js、npm、Next.js 和 TypeScript：

```text
cd frontend
npm install
npm run typecheck
npm run build
npm run dev
```

前端依赖通过 `frontend/package.json` 和 `frontend/package-lock.json` 管理，不与 Python 的 `uv.lock` 混用。

默认本地启动 SQLite：

```text
Copy-Item .env.example .env
uv run alembic upgrade head
```

数据库文件默认位于 `./data/jobflow.db`。如果需要验证 PostgreSQL：

```text
docker compose up -d postgres
$env:DATABASE_URL = 'postgresql+psycopg://jobflow:jobflow@localhost:5432/jobflow?connect_timeout=3'
uv run alembic upgrade head
```

宿主机运行 API 时使用 `localhost`；API 和数据库位于同一个 Compose 网络时使用服务名 `postgres`。当前 `docker-compose.yml` 只启动数据库，API 和前端暂时分别通过 `uv run` 与 Node.js 脚本启动。

### 2.2 权限边界

Agent 负责：

- 理解模糊求职目标；
- 解析非结构化 JD；
- 判断岗位要求和经历的语义关系；
- 解释结论并生成材料建议。

确定性代码负责：

- Schema、Evidence ID 和数字事实校验；
- 资格规则、分数和状态转换；
- 用户审批、数据保存和事件记录；
- 工具路由、URL 安全和重试上限。

Agent 不能直接创建申请、接受建议、修改最终文本、推进状态或自动投递。

### 2.3 纵向开发

每个功能按以下顺序完成：

```text
定义输入输出
→ 实现纯规则和测试
→ 使用 Fake 完成 Service
→ 接入数据库、模型或网页
→ 添加 API 和最小页面
→ 用真实案例验收
```

## 3. 最终目录

```text
jobflow-agent/
├── pyproject.toml
├── uv.lock
├── .python-version
├── src/
│   ├── api/
│   │   ├── profiles.py
│   │   ├── jobs.py
│   │   ├── applications.py
│   │   └── suggestions.py
│   ├── domain/
│   │   ├── profile.py
│   │   ├── job.py
│   │   ├── analysis.py
│   │   ├── application.py
│   │   └── suggestion.py
│   ├── services/
│   │   ├── jd_analysis.py
│   │   ├── evidence_matching.py
│   │   ├── application_service.py
│   │   └── discovery_service.py
│   ├── infrastructure/
│   │   ├── database.py
│   │   ├── llm_client.py
│   │   ├── job_reader.py
│   │   └── job_sources/
│   ├── evaluation/
│   ├── config.py
│   └── main.py
├── frontend/
├── tests/
│   ├── fixtures/
│   ├── test_analysis.py
│   ├── test_eligibility.py
│   ├── test_evidence_matching.py
│   ├── test_application.py
│   ├── test_job_reader.py
│   └── test_api.py
├── migrations/
├── datasets/
└── docs/
```

只有单个文件内容明显变大时才继续拆分。测试通过文件名和标记区分，不预先建设四套测试目录。

## 4. 核心数据模型

| 实体 | 作用 | MVP 关键字段 |
|---|---|---|
| `UserProfile` | 用户信息和偏好 | graduation_year、degree、search_preferences JSON（PostgreSQL 可升级为 JSONB） |
| `EvidenceItem` | 真实经历证据 | type、title、claim、skills、source |
| `JobSource` | 招聘来源配置 | name、adapter_type、entry_url、enabled |
| `JobPosting` | 外部岗位事实 | company、title、raw_content、content_hash、source_url |
| `CandidateJob` | 用户与岗位关系 | user_id、job_posting_id、status |
| `JobAnalysis` | JD 和资格分析 | parsed_jd、eligibility、score、content_hash |
| `RequirementMatch` | 要求与证据对应 | requirement、support_level、evidence_ids |
| `Application` | 正式申请 | candidate_job_id、status、next_action |
| `ResumeSuggestion` | 建议和审批结果 | original_text、suggested_text、status、final_text |
| `DomainEvent` | 用户可见时间线 | entity_type、entity_id、event_type、payload |
| `AgentRun` | 必要技术轨迹 | model、prompt_version、output、validation_result、trace |

求职偏好直接保存在 `UserProfile.search_preferences`。岗位原文、内容指纹和读取时间直接保存在 `JobPosting`。审批状态和最终文本直接保存在 `ResumeSuggestion`。

第一版不创建：

```text
SearchPreference 独立表
JobSnapshot
ResumeVersion
ApprovalDecision 独立表
ToolCallTrace 独立表
```

`CandidateJob` 仍然保留，用于隔离外部岗位事实和用户侧状态，但不为它建设复杂分层。

候选岗位状态：

```text
DISCOVERED → SAVED / IGNORED / CONVERTED
SAVED → IGNORED / CONVERTED
IGNORED → SAVED
```

申请状态：

```text
PREPARING → SUBMITTED / WITHDRAWN
SUBMITTED → ASSESSMENT / INTERVIEW / REJECTED / WITHDRAWN
ASSESSMENT → INTERVIEW / REJECTED / WITHDRAWN
INTERVIEW → INTERVIEW / OFFER / REJECTED / WITHDRAWN
```

建议状态：

```text
PENDING → ACCEPTED / EDITED_AND_ACCEPTED / REJECTED
```

## 5. 核心服务

### 5.1 JDAnalysisService

```text
RawJobDocument
→ JD Parser
→ Pydantic 校验
→ Eligibility Checker
→ Evidence Retriever
→ Evidence Matcher
→ Evidence Validator
→ JobAnalysis
```

模型通过可替换接口调用：

```python
class StructuredModelClient(Protocol):
    async def generate(self, *, schema, messages):
        ...
```

测试使用 Fake Client。Eligibility Checker 保持为纯函数，输出 `pass / fail / unknown`。

Evidence Validator 必须保证：

- `supported` 至少引用一个有效 `evidence_id`；
- 证据属于当前用户；
- `unsupported` 不表述为用户已掌握；
- 项目、技能和数字能在证据中找到。

`MatchScoreCalculator` 使用确定性规则计算详情页分数：

```text
硬性资格：门控条件
必备技能覆盖率：60%
加分技能覆盖率：20%
地点和岗位偏好：20%
```

`supported / partial / unsupported` 分别按 `1 / 0.5 / 0` 计入覆盖率。硬性资格出现 `fail` 时标记为不推荐；出现 `unknown` 时保留分数但要求用户确认。评分结果必须和证据、风险项一起展示。

### 5.2 ApplicationService

核心方法：

```text
save_candidate
ignore_candidate
prepare_application
transition_application
decide_suggestion
```

`prepare_application` 使用一个普通数据库事务：

```text
校验 CandidateJob
→ 标记为 CONVERTED
→ 创建 PREPARING Application
→ 写入 ApplicationCreated
→ 提交事务
```

使用唯一约束防止重复创建申请，不引入分布式锁和复杂并发重试。

### 5.3 DiscoveryService

```text
求职偏好
→ 结构化检索条件
→ 真实招聘来源 Adapter
→ 标准化和去重
→ 基础筛选
→ CandidateJob
```

Adapter 接口：

```python
class JobSourceAdapter(Protocol):
    async def list_jobs(self) -> list[JobStub]: ...
    async def fetch_job(self, source_job_id: str) -> RawJobDocument: ...
```

必须完成 1 个真实来源。发现页只做基础筛选，打开详情后才执行完整分析。

## 6. URL 读取与安全

岗位文本直接转换为 `RawJobDocument`。岗位 URL 按以下顺序读取：

```text
Generic HTML
→ 页面结构化数据
→ 请求用户粘贴文本
```

Playwright 是动态页面的可选扩展，不属于核心 MVP。只有普通读取无法工作且确有演示价值时才增加。

必须实现：

- 仅允许 HTTP 和 HTTPS；
- 阻止本机、内网和云元数据地址；
- 限制重定向、响应大小、超时和重试；
- 将网页内容视为不可信数据；
- 清理脚本、隐藏元素和无关文本；
- 普通日志不保存完整简历和联系方式。

## 7. API 范围

```text
PUT  /api/profile
POST /api/evidence
GET  /api/evidence

POST /api/jobs/import-text
POST /api/jobs/import-url
POST /api/jobs/{job_id}/analyze
GET  /api/jobs/{job_id}/analysis

POST /api/candidates/{candidate_id}/save
POST /api/candidates/{candidate_id}/ignore
POST /api/candidates/{candidate_id}/prepare

GET  /api/applications
POST /api/applications/{application_id}/transitions
POST /api/applications/{application_id}/suggestions
POST /api/suggestions/{suggestion_id}/decide

POST /api/discovery/runs
GET  /api/candidates
```

API 只负责请求校验、身份识别、调用 Service 和错误转换。

M02 的本地身份通过可选的 `X-User-ID` 请求头传入，缺省使用 `DEFAULT_USER_ID`。这不是生产认证实现，只是为了在尚未接入登录系统时保留用户归属边界。`EvidenceService` 的所有读取和修改必须同时过滤 `user_id` 与 `evidence_id`，不能先按 ID 查询再在接口层判断归属。

## 8. 四个开发里程碑

### A：岗位分析闭环

完成：uv 工程骨架、数据库、用户画像、证据、JobPosting、JD 文本导入、结构化解析、Fake 和真实模型客户端、资格规则、证据匹配、确定性评分、分析 API 和页面、10～20 条初始样本。

验收：

```text
粘贴真实 JD
→ 输出结构化字段
→ 给出 pass / fail / unknown
→ supported 结论引用有效 evidence_id
→ 无证据时不虚构经历
```

### B：申请与审批闭环

完成：CandidateJob、Application 状态机、普通数据库事务、DomainEvent、ResumeSuggestion、审批交互和申请看板。

验收：

```text
用户创建 PREPARING 申请
→ 生成有证据的材料建议
→ 用户审批并保存 final_text
→ 手动推进至 SUBMITTED 和 INTERVIEW
→ 展示事件时间线
```

### C：轻量岗位发现

完成：岗位 URL 读取、SSRF 防护、1 个真实来源 Adapter、用户手动触发发现、岗位标准化和去重、岗位发现页。

验收：

```text
输入求职偏好
→ 获取真实岗位
→ 标准化和去重
→ 进入发现池
→ 选择岗位后运行完整分析
```

第 2 个来源、定时同步和 Playwright 为可选项。

### D：评测与演示

完成：30～50 条标注样本、字段级 Precision / Recall / Macro-F1、资格分类准确率、误判符合率、Evidence Precision、Evidence Coverage、Unsupported Claim Rate、AgentRun、失败案例、端到端测试和 UI 打磨。

验收：评测可重复运行并记录模型、提示词和数据集版本；真实岗位发现到申请管理可以完整演示；unknown、无证据和读取失败场景可以正常处理。

## 9. 测试重点

- Eligibility Checker 边界条件；
- Evidence Matcher 输出校验；
- 候选岗位和申请状态转换；
- `prepare_application` 原子性和唯一约束；
- 材料建议审批规则；
- 岗位去重和 URL SSRF；
- 真实来源 Adapter 的固定 HTML Fixture；
- 核心演示链路端到端测试。

Adapter Fixture 测试直接放在对应测试文件中，不建设独立 Contract 测试目录。

## 10. 任务里程碑

当前完成进度和子任务见 [`TODO.md`](../TODO.md)。

```text
M01 工程骨架与数据库
M02 用户画像与经历证据
M03 JD 导入与结构化 Schema
M04 JD 解析与输出校验
M05 资格规则
M06 证据召回、匹配与确定性评分
M07 岗位分析页面
M08 申请状态机与事件
M09 材料建议与审批
M10 一个真实来源与岗位发现池
M11 评测、失败案例与演示
```

GitHub Issue 可以继续拆小任务，但 README、TODO 和项目看板只展示这 11 个里程碑。

## 11. Definition of Done

一个功能只有同时满足以下条件才算完成：

- 输入输出有明确 Schema；
- 核心规则有测试；
- 模型和外部来源可以使用 Fake 或 Fixture 替换；
- Agent 输出经过程序校验；
- 副作用经过用户确认和 Service；
- 错误和 unknown 路径可展示；
- 必要的 DomainEvent 或 AgentRun 已记录；
- API 和最小页面可以完成交互；
- 文档、TODO 和实现保持一致。
