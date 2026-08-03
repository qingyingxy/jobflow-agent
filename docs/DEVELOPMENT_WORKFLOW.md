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

系统由 Next.js、FastAPI 和数据库组成。SQLite 是 M01～M11 核心 MVP 的开发和验收数据库；PostgreSQL + pgvector 是发布前切换验证以及 JSONB、向量检索等可选能力的升级路径，不计入核心里程碑进度。后端保持一个部署单元，通过 `api / domain / services / infrastructure` 保持边界，不为每个小实体分别创建 Repository、Schema 和 Service 文件。

PostgreSQL 基础设施复用 Memory-RAG 的方案：使用 `pgvector/pgvector:pg16` Docker 镜像、固定数据库用户和数据库名、持久化卷以及 `pg_isready` 健康检查。JobFlow 的数据库访问仍使用 SQLAlchemy，表结构变更仍使用 Alembic；这里只复用数据库运行方式，不复用 Memory-RAG 的手写 SQL 存储层。没有 Docker 或 PostgreSQL 环境时，开发者仍可完整推进核心 MVP；切换验证集中放在发布前检查中完成。

数据库范围：

| 场景 | 数据库 | 是否阻塞 M01～M11 | 必须验证的内容 |
|---|---|---:|---|
| 本地开发、测试和核心演示 | SQLite | 是 | 迁移、规则、事务、API 和端到端链路 |
| 发布前切换验证 | PostgreSQL 16 | 否 | 全新迁移、核心测试、JSON/时间/约束兼容性 |
| 可选向量召回 | PostgreSQL + pgvector | 否 | 扩展迁移、向量索引和召回回归测试 |

Python 环境统一使用 `uv` 管理。依赖声明写入 `pyproject.toml`，锁文件使用 `uv.lock`，不维护单独的 `requirements.txt`。所有 Python 命令通过 `uv run` 执行。

初始化和常用命令：

```text
uv python install 3.12
uv init --python 3.12
uv python pin 3.12
uv add fastapi "uvicorn[standard]" pydantic-settings sqlalchemy alembic psycopg[binary] httpx
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

数据库文件默认位于 `./data/jobflow.db`。到发布前检查或确实需要 PostgreSQL 专有能力时，再执行切换验证：

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
│   ├── config.py
│   └── main.py
├── frontend/
├── tests/
│   ├── fixtures/
│   ├── test_eligibility.py
│   ├── test_evidence_matching.py
│   ├── test_jd_parser.py
│   ├── test_job_import.py
│   ├── test_job_parse.py
│   ├── test_profile_evidence.py
│   └── test_health.py
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
| `RawJobDocument` | 岗位原始文档 Schema | source_url、source_type、raw_content、retrieved_at、trace_id |
| `JobSource` | 招聘来源配置 | name、adapter_type、entry_url、enabled |
| `JobPosting` | 外部岗位事实 | company、title、raw_content、content_hash、source_url、retrieved_at |
| `JobParseResult` | 与用户无关的岗位解析缓存 | job_posting_id、content_hash、schema_version、parser_version、prompt_version、model、structured_jd |
| `CandidateJob` | 用户与岗位关系 | user_id、job_posting_id、status |
| `JobAnalysis` | 当前用户的资格与匹配分析 | user_id、job_posting_id、parse_result_id、analysis_version、eligibility、matches、score、risks、created_at、invalidated_at |
| `RequirementMatch` | 要求与证据对应 | requirement、support_level、evidence_ids |
| `Application` | 正式申请 | candidate_job_id、status、next_action |
| `ResumeSuggestion` | 建议和审批结果 | user_id、application_id、job_analysis_id、target_type、original_text、suggested_text、evidence_ids、status、final_text |
| `DomainEvent` | 用户可见时间线 | entity_type、entity_id、event_type、payload |
| `AgentRun` | 从 M04 开始保存的必要技术轨迹 | user_id、run_type、target、status、model、prompt_version、input_hash、output、validation_result、started_at、finished_at、error |
| `DiscoveryRun` | 用户手动发现运行 | user_id、source、status、found_count、created_count、duplicate_count、failure_summary、started_at、finished_at |

求职偏好直接保存在 `UserProfile.search_preferences`，但写入和读取必须经过 `SearchPreferences` Schema。参与资格判断的字段至少包括 `preferred_locations`、`job_types`、`earliest_start_date`、`weekly_days` 和 `internship_duration_months`，并明确类型、范围和 `null` 语义；其他纯展示偏好仍可保留在 JSON 中。`RawJobDocument` 是导入和后续解析之间传递的 Schema，不单独建表；岗位原文、内容指纹和读取时间直接保存在 `JobPosting`。审批状态和最终文本直接保存在 `ResumeSuggestion`。

`JobParseResult` 只缓存与用户无关的结构化 JD，可按 `content_hash + schema_version + parser_version + prompt_version + model` 复用。`JobAnalysis` 必须包含 `user_id`、`analysis_version` 和可选 `invalidated_at`，每次分析都使用当前画像和当前证据重新计算资格、匹配与分数，不允许仅凭岗位 `content_hash` 跨用户复用完整结果。

第一版不创建：

```text
SearchPreference 独立表
JobSnapshot
ResumeVersion
ApprovalDecision 独立表
ToolCallTrace 独立表
```

`CandidateJob` 仍然保留，用于隔离外部岗位事实和用户侧状态，但不为它建设复杂分层。真实来源发现创建 `DISCOVERED` CandidateJob；手动导入的 JobPosting 可以通过候选创建 API 幂等生成 `SAVED` CandidateJob。

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
→ JobParseResult
→ Eligibility Checker
→ Evidence Retriever
→ Evidence Matcher
→ Evidence Validator
→ JobAnalysis
```

模型通过可替换接口调用：

```python
class StructuredModelClient(Protocol):
    async def generate(self, request: StructuredModelRequest) -> StructuredModelResponse:
        ...
```

测试使用 Fake Client。Eligibility Checker 保持为纯函数，输出 `pass / fail / unknown`。

M04 起采用以下结构化输出约束：

- 模型只产生一套规范结果；用于页面展示、资格规则和评分的重复视图由确定性代码派生；
- `JobRequirement` 是证据匹配和技能评分的规范输入；
- `required_skills` 和 `preferred_skills` 只能与 `requirements` 保持确定性派生关系，不能形成第二套技能事实；
- 资格条件必须有明确字段、操作符和值，`unknown` 表示原文无法确认，而不是模型调用失败；
- 每个关键字段和要求保存原文依据，至少包含 `field_path`、`source_text` 和可选的字符位置；Parser 还会检查依据片段确实出现在岗位原文中；
- 缺失字段使用 `null`，不得使用空字符串、默认通过或模型猜测填充；
- Pydantic 类型或语义校验失败时，整次解析失败，不保存半成品 `JobAnalysis`。

`StructuredModelClient` 只负责结构化模型调用。Parser 负责提示词、Schema 和错误转换，Service 负责事务、`JobParseResult` 和 `AgentRun`。Fake Client 至少支持正常输出、字段缺失、额外字段、非法类型、超时和模型异常，使上层逻辑不依赖真实模型即可测试。

`AgentRun` 的 `run_type` 至少支持 `jd_parse / evidence_match / resume_suggestion`。运行状态使用 `succeeded / failed`，输出校验结果独立使用 `passed / failed`；因此模型调用成功但输出被安全降级时，可以记录为运行成功、校验失败。模型或不可恢复的校验错误保存失败状态和必要诊断，但普通日志不写入完整 JD、简历原文或联系方式。

M04 当前提供同步解析接口：

```text
POST /api/jobs/{job_id}/parse
→ 创建 jd_parse AgentRun
→ 调用 Fake 或 OpenAI-compatible StructuredModelClient
→ 校验结构化 JD 和字段原文依据
→ 成功时保存 JobParseResult 与 AgentRun
→ 失败时只更新失败 AgentRun，不保存半成品 JobParseResult
```

默认 `STRUCTURED_MODEL_PROVIDER=fake`，本地开发无需模型密钥。真实模型使用 `STRUCTURED_MODEL_PROVIDER=openai_compatible`、`LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`、`LLM_RESPONSE_FORMAT` 和 `LLM_TIMEOUT_SECONDS` 配置。`LLM_RESPONSE_FORMAT=auto` 会为 DeepSeek 选择 JSON Object 模式，其他兼容服务默认使用 JSON Schema 模式；Parser 仍通过统一 Client 接口工作，并在响应后执行相同的 Pydantic 和原文证据校验。

### 5.2 EligibilityChecker

M05 将资格判断与技能匹配分开。`SearchPreferences` 是用户偏好的唯一输入 Schema，至少包含：

```text
preferred_locations: list[str] | null
job_types: list[campus | internship | full_time | part_time] | null
earliest_start_date: date | null
weekly_days: int(1..7) | null
internship_duration_months: int(>=0) | null
```

`null` 表示没有提供足够信息，参与相关规则时返回 `unknown`；空列表表示用户明确没有设置该类限制。用户可提供的实习月数和每周到岗天数分别按“可提供时长”和“可到岗天数”解释，必须达到岗位要求。用户最早可到岗日期必须早于或等于岗位要求日期。

输入输出保持显式边界：

```text
CandidateProfileInput + SearchPreferences + StructuredJobDescription
→ EligibilityInput
→ check_eligibility（纯函数）
→ EligibilityCheck[] + EligibilityResult
```

每个 `EligibilityCheck` 保存规则名、字段、`pass / fail / unknown`、原因、JD 原文依据和待补充信息。规则对学历层级、专业族、地点别名、日期和数值使用确定性规范化；无法安全规范化时返回 `unknown`，不交给评分逻辑猜测。总体结果固定按 `fail > unknown > pass` 汇总。

### 5.3 EvidenceMatcher 与 MatchScoreCalculator

M06 的匹配链路保持四个可替换边界：

```text
JobRequirement
→ EvidenceRetriever（当前用户的关键词/技能别名召回）
→ EvidenceMatcher（Fake 或真实 StructuredModelClient）
→ EvidenceValidator（ID、归属、事实和数字校验）
→ RequirementMatch
→ MatchScoreCalculator
```

`JobRequirement` 是唯一规范输入，`required_skills` 和 `preferred_skills` 不参与第二次事实生成。召回只接收当前用户的 `EvidenceRecord`，使用大小写、空白、显式技能别名和稳定 ID 排序；没有候选证据时直接返回合法的 `unsupported`。

模型只能选择候选证据 ID、匹配等级和解释。`supported / partial` 必须引用至少一个当前用户证据，`unsupported` 必须使用空引用；无效 ID、跨用户 ID、证据中不存在的事实或数字会被安全降级为 `unsupported`，清空引用和解释，并将 `AgentRun.validation_status` 记录为 `failed`。模型调用失败则记录失败运行并返回可重试错误。

评分先按规范化后的 `category + name` 去重，再按 `1 / 0.5 / 0` 计算必备技能、加分技能和地点/岗位偏好三组。原始权重为 `60% / 20% / 20%`；只有 JD 明确没有某组要求时才标记 `not_applicable` 并重分配权重，JD 缺失属于 `insufficient_data`。硬性资格 `fail` 门控为 `not_recommended`，`unknown` 保留可计算分数但标记 `needs_confirmation`。

Evidence Validator 必须保证：

- `supported / partial` 至少引用一个有效 `evidence_id`；
- 证据属于当前用户；
- `unsupported` 的 `evidence_ids` 为空，且不表述为用户已掌握；
- 项目、技能和数字能在证据中找到。

无效 ID、跨用户引用或虚构事实不会直接进入用户结果。对应匹配安全降级为 `unsupported`，清空非法引用和解释，同时在 AgentRun 中记录 `validation_failed`，使产品结果安全而评测仍能统计模型错误。

`MatchScoreCalculator` 使用确定性规则计算详情页分数：

```text
硬性资格：门控条件
必备技能覆盖率：60%
加分技能覆盖率：20%
地点和岗位偏好：20%
```

`supported / partial / unsupported` 分别按 `1 / 0.5 / 0` 计入覆盖率。硬性资格出现 `fail` 时标记为不推荐；出现 `unknown` 时保留分数但要求用户确认。评分结果必须和证据、风险项一起展示。

资格汇总固定使用以下优先级：任一单项为 `fail` 时总体为 `fail`；没有 `fail` 但存在 `unknown` 时总体为 `unknown`；全部为 `pass` 时总体才是 `pass`。缺少用户信息或 JD 信息必须生成 `unknown` 和补充信息请求，不能自动推断为通过。

要求先按规范化后的 `category + name` 去重。只有 JD 明确不存在某类要求时，该分组才标记为 `not_applicable`，其权重按原比例重分配给其他适用分组；字段缺失属于信息不足，不能当作不适用。所有软评分分组都不可用时，分数返回 `null` 并要求补充信息。保存的评分明细必须能够确定性复算总分。

MVP 使用同步分析 API。`POST /api/jobs/{job_id}/analyze` 等待 Parser、资格、证据和评分全部完成后返回新结果；可安全处理的非法证据匹配降级为 `unsupported` 并作为风险保存，只有无法降级的模型或校验错误才终止分析。只有整条流水线成功才保存 JobAnalysis；失败只写 AgentRun 并返回统一错误，不保存 `pending` 或半成品结果。`GET /api/jobs/{job_id}/analysis` 只读取当前用户最新、成功且 `invalidated_at` 为空的结果。用户画像、证据、岗位文本或分析规则变化时，相关旧分析写入失效时间。

### 5.4 JDAnalysisService

M07 使用同步编排服务完成一次用户级岗位分析：

```text
JobPosting
→ JobParseService（按岗位原文和版本复用 JobParseResult）
→ EligibilityChecker（当前用户画像 + SearchPreferences）
→ EvidenceMatchService（当前用户证据 + EvidenceValidator）
→ MatchScoreCalculator
→ 保存 JobAnalysis
```

`JobParseResult` 是岗位级缓存，不包含用户画像、证据或评分；`JobAnalysis` 是用户级结果，保存 `eligibility`、`matches`、`score`、`risks`、`input_hash` 和 `invalidated_at`。每次重新分析都会重新读取当前用户画像和证据，成功后才使该用户该岗位的旧结果失效并写入新结果；模型失败时只保留 `AgentRun`，不写入半成品 `JobAnalysis`。

画像或证据通过 Service 更新时，当前用户的分析统一写入 `invalidated_at`。删除证据时先硬删除引用该证据的用户级分析，再删除证据本身；岗位原文指纹变化时，最新分析接口返回可重试的 `analysis_content_changed` 错误。MVP 不创建独立 `RequirementMatch` 表，匹配明细作为经过 Schema 校验的 JSON 保存在 `JobAnalysis.matches`，M09 再扩展材料建议引用。

API 提供：

```text
POST /api/jobs/{job_id}/analyze
→ 复用或创建 JobParseResult
→ 运行当前用户的完整分析
→ 保存成功的 JobAnalysis
→ 返回结构化 JD、资格、证据、分数和风险

GET /api/jobs/{job_id}/analysis
→ 只读当前用户最新且未失效结果
```

前端 M07 工作台覆盖空状态、加载中、失败重试、内容变化、结构化 JD、资格检查、要求证据、评分和待补充信息；M08 在此基础上接入“准备申请”人工确认和申请看板。默认 Fake 模式使用确定性的本地演示 Client；真实模型复用 M04 的 `StructuredModelClient` 接口。

### 5.5 ApplicationService

核心方法：

```text
create_candidate
list_candidates
get_candidate
transition_candidate
prepare_application
list_applications
get_application
transition_application
list_events
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

`create_candidate` 接收当前用户和 `job_posting_id`。手动导入岗位幂等创建或返回 `SAVED` CandidateJob；发现流程使用同一唯一约束创建 `DISCOVERED` CandidateJob。

材料建议不依赖完整 Resume 实体。`SuggestionTargetInput` 由用户请求提供 `original_text`、`target_type` 和可选 `target_label`；Suggestion Generator 只对这段明确文本提出建议。ResumeSuggestion 关联当前用户、Application 和当前岗位最新有效的 JobAnalysis，Agent 只能创建 `PENDING`，最终文本只能由用户接受或编辑后接受产生。

M09 已实现 `SuggestionService`：生成阶段复用 M04 的 `StructuredModelClient` 和 `AgentRun`，结构化输出必须包含 `suggestion_text`、`evidence_ids` 和 `claims`；Evidence Validator 会校验引用归属、项目、技能和数字。生成失败或证据校验失败时只保存失败/校验失败的 AgentRun，不创建建议。审批阶段只允许 `PENDING` 建议进入 `accept / edit / reject` 三种决策，最终文本和 `SuggestionDecisionRecorded` DomainEvent 在同一事务内保存。事件只保存决策元数据、长度和哈希，不保存材料正文。

### 5.6 DiscoveryService

```text
求职偏好
→ 结构化检索条件
→ 真实招聘来源 Adapter
→ 标准化和去重
→ 基础筛选
→ DiscoveryRun
→ CandidateJob
```

Adapter 接口：

```python
class JobSourceAdapter(Protocol):
    async def list_jobs(self) -> list[JobStub]: ...
    async def fetch_job(self, source_job_id: str) -> RawJobDocument: ...
```

必须完成 1 个真实来源。每次用户手动触发都保存轻量 DiscoveryRun，包括来源、状态、发现/新增/重复数量、失败摘要和起止时间。发现页只做基础筛选，打开详情后才执行完整分析。

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
GET  /api/evidence/{evidence_id}
PATCH /api/evidence/{evidence_id}
DELETE /api/evidence/{evidence_id}

POST /api/jobs/import-text
GET  /api/jobs/{job_id}
POST /api/jobs/{job_id}/parse

POST /api/jobs/import-url
POST /api/jobs/{job_id}/analyze
GET  /api/jobs/{job_id}/analysis

POST /api/candidates
GET  /api/candidates
GET  /api/candidates/{candidate_id}
PATCH /api/candidates/{candidate_id}/status
POST /api/candidates/{candidate_id}/prepare-application

GET  /api/applications
GET  /api/applications/{application_id}
PATCH /api/applications/{application_id}/status
GET  /api/applications/{application_id}/events
POST /api/applications/{application_id}/suggestions
GET  /api/applications/{application_id}/suggestions
GET  /api/suggestions/{suggestion_id}
POST /api/suggestions/{suggestion_id}/decide

POST /api/discovery/runs
```

API 只负责请求校验、身份识别、调用 Service 和错误转换。

岗位分析 API 在核心 MVP 中同步执行，不返回后台 Job ID，也不要求前端轮询。`POST /api/candidates` 让手动岗位在 M10 完成前即可进入申请闭环。材料建议请求必须包含 SuggestionTargetInput，不能从不存在的 ResumeVersion 猜测原文。

M03 的文本导入只保存事实，不负责调用模型解析。手动文本入口的来源类型固定为 `manual_text`；真实招聘来源只能由 M10 Adapter 写入。`StructuredJobDescription` 是 M04 JD Parser 的基础输出形状；M04 已补齐唯一事实来源、字段原文依据、跨字段语义校验、可替换 Model Client、`JobParseResult`、`AgentRun` 和解析接口。M05 的 `EligibilityInput` 只接受经过 `SearchPreferences` 校验的用户偏好，不直接读取任意 JSON 字段。字段缺失统一保留为 `null`，不在导入阶段填充猜测值。

M02 的本地身份通过可选的 `X-User-ID` 请求头传入，缺省使用 `DEFAULT_USER_ID`。这不是生产认证实现，只是为了在尚未接入登录系统时保留用户归属边界。`EvidenceService` 的所有读取、修改和删除必须同时过滤 `user_id` 与 `evidence_id`，不能先按 ID 查询再在接口层判断归属。硬删除证据后，同时删除引用它的 RequirementMatch、JobAnalysis、ResumeSuggestion 和 `final_text`；DomainEvent 只保留不含材料正文的审计元数据。

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

完成：30～50 条标注样本、字段级 Precision / Recall / Macro-F1、资格分类准确率、误判符合率、Evidence Precision、Evidence Coverage、Unsupported Claim Rate、AgentRun 汇总、失败案例、端到端测试和 UI 打磨。`AgentRun` 的最小持久化在 M04 首次接入模型时实现，M11 负责把运行轨迹纳入可重复评测。

验收：最终运行前已冻结 Evaluation Manifest、指标口径和发布阈值；评测可重复运行并记录模型、提示词和数据集版本；原始模型输出和 Validator 后结果分别报告，用户可见 Unsupported Claim Rate 为 0；真实岗位发现到申请管理可以完整演示；unknown、无证据和读取失败场景可以正常处理。

## 9. 测试重点

| 范围 | 必测路径 |
|---|---|
| 文本导入 | 规范化、最短长度、纯空白、内容哈希、固定手动来源、404 |
| JD Parser | 正常、缺失、额外字段、类型错误、语义非法、超时、模型异常、原文依据 |
| Eligibility | 边界年份、学历层级、地点别名、日期边界、信息缺失、多条件汇总 |
| Evidence | 无证据、跨用户证据、错误 ID、虚构技能或数字、安全降级、删除失效、重复要求、评分零分母 |
| JobAnalysis | Fake 编排、岗位级解析缓存、用户级重新计算、内容/版本变化、失败不留半成品、同步 API 错误转换 |
| 状态机 | 完整转换矩阵、非法转换、重复请求、跨用户访问、事务回滚 |
| 材料审批 | 明确原文输入、接受、编辑后接受、拒绝、重复审批、无效/已删除证据、事件原子性 |
| URL 和 Adapter | SSRF、DNS/重定向、超时、超大响应、恶意 HTML、固定 Fixture、去重 |
| 端到端 | 手动 JD 完整闭环、真实来源发现闭环、unknown、读取失败、无证据 |

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

关键依赖顺序：

```text
M04 Parser + AgentRun
→ M05 Eligibility
→ M06 Evidence + Score
→ M07 JobAnalysis API/UI
→ M08 Application State Machine
→ M09 Suggestion Approval
→ M10 Real-source Discovery
→ M11 Evaluation + Demo
```

M04～M06 可以分别用纯 Schema、纯函数和 Fake 并行开发，但 M07 的完整分析编排必须等三者接口稳定。M09 复用 M04 的模型边界和 M06 的证据校验。M11 不再首次引入运行轨迹，只评测和汇总从 M04 开始产生的 `AgentRun`。

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

里程碑完成不要求 PostgreSQL 可用。PostgreSQL 发布前验证使用独立检查表，不回写 M01～M11 的核心进度。

## 12. PostgreSQL 发布前切换验证

这部分不计入核心里程碑进度。当项目需要部署到 PostgreSQL、启用 JSONB/pgvector，或准备对外演示部署环境时执行：

```text
启动 pgvector/pgvector:pg16
→ 对全新数据库执行 alembic upgrade head
→ 运行后端测试和核心 API 冒烟测试
→ 核对 JSON、时区、唯一约束和事务行为
→ 记录镜像版本、迁移版本、验证日期和已知差异
```

如果 SQLite 与 PostgreSQL 行为不同，应优先通过 SQLAlchemy 类型、约束和显式业务规则消除差异。只有确实使用 PostgreSQL 专有能力时才增加方言分支，并为该分支增加回归测试。
