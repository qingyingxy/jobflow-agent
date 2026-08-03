# JobFlow Agent TODO

> 当前阶段：M06 核心实现已完成，下一步 M07
> 核心实现进度：6 / 11
> 外部验收：M04 还需要配置真实模型，用 3 条真实中文 JD 做手动解析验收；Fake、错误处理和持久化链路已完成。

> 当前状态：核心 MVP 采用 SQLite-first；PostgreSQL + pgvector 仅作为发布前切换验证和可选升级路径，不计入 M01～M11 核心进度。

产品设计见 [README.md](README.md)，实现约束和完成标准见 [docs/DEVELOPMENT_WORKFLOW.md](docs/DEVELOPMENT_WORKFLOW.md)。

## 维护规则

- 只有代码、测试和必要文档全部完成，里程碑才能勾选；
- 每次完成任务时，在同一次提交中更新本文件；
- 里程碑内部可以继续拆 GitHub Issue，但本文件只跟踪 M01～M11；
- 里程碑清单描述可验收结果，具体编码步骤、负责人和排期放到 GitHub Issue；
- SQLite 是核心 MVP 的验收数据库；PostgreSQL 切换验证单独列为发布前检查，不阻塞 M01～M11；
- 可选扩展不能阻塞核心 MVP；
- 未经实际评测的指标不能写入简历。

## 已完成的设计工作

- [x] 明确项目定位和核心用户闭环
- [x] 明确 Agent、确定性代码和用户的权限边界
- [x] 设计轻量模块化单体架构
- [x] 设计核心数据模型和状态机
- [x] 确定 1 个真实来源必做、第 2 个来源可选
- [x] 编写轻量开发流程和完成标准
- [x] 统一 README 与开发流程

## A：岗位分析闭环

### M01 工程骨架与数据库

- [x] 确认当前环境已安装 `uv`
- [x] 使用 uv 初始化 Python 项目
- [x] 使用 `uv python pin 3.12` 固定 Python 版本
- [x] 添加 FastAPI、SQLAlchemy、Alembic、Pydantic Settings 和 PostgreSQL 驱动
- [x] 复用 `pgvector/pgvector:pg16` Docker Compose 数据库方案
- [x] 配置 SQLite-first 本地开发数据库
- [x] 添加 Pytest、pytest-asyncio 和 Ruff 开发依赖
- [x] 提交 `pyproject.toml` 和 `uv.lock`
- [x] 创建 FastAPI 应用入口
- [x] 初始化 Next.js 和 TypeScript
- [x] 配置 Pydantic Settings
- [x] 配置 SQLAlchemy 和 Alembic
- [x] 添加首个数据库迁移基线
- [x] 保留 PostgreSQL 驱动、Docker Compose 和数据库 URL 切换入口
- [x] 添加统一错误响应和结构化日志
- [x] 添加 `GET /health`
- [x] 配置 Pytest
- [x] 编写本地启动说明
- [x] 后端、前端、SQLite 迁移和测试均可运行

### M02 用户画像与经历证据（SQLite-first）

- [x] 实现 `UserProfile`
- [x] 使用兼容 SQLite 的 JSON 保存 `search_preferences`，切换 PostgreSQL 后再评估 JSONB
- [x] 实现 `EvidenceItem`
- [x] 实现用户画像 API
- [x] 实现证据新增、查询和编辑 API
- [x] 验证证据只能由所属用户访问
- [x] 添加 Profile 和 Evidence 测试

### M03 JD 导入与结构化 Schema（SQLite-first）

- [x] 实现 `JobPosting`
- [x] 实现 `RawJobDocument`
- [x] 实现岗位文本导入
- [x] 定义结构化 JD Schema
- [x] 定义资格条件和岗位要求 Schema
- [x] 缺失字段统一使用 `null`
- [x] 保存岗位原文、`content_hash` 和读取时间
- [x] 添加 Schema 和文本导入测试

### M04 JD 解析与输出校验

#### M04-A 导入边界加固

- [x] 收紧文本导入边界：规范化后不足 20 字符返回 422，而不是 500
- [x] 固定手动导入的 `source_type=manual_text`，真实来源仅由 Adapter 写入

#### M04-B 结构化输出契约

- [x] 明确结构化 JD 的唯一事实来源，避免技能列表、要求列表和资格条件互相矛盾
- [x] 定义字段原文依据 Schema，至少包含 `field_path`、`source_text` 和可选文本位置
- [x] 为资格条件增加跨字段校验，例如非 `unknown` 操作符必须有合法值

#### M04-C Model Client 与 Parser

- [x] 定义异步 `StructuredModelClient` 协议和统一请求/响应类型
- [x] 实现可配置的 Fake Model Client，支持正常、缺失字段、非法字段、非法类型和模型异常
- [x] 实现 JD Parser：构造提示词、调用 Client、执行 Pydantic 校验并返回结构化结果
- [x] 定义模型超时、无响应和校验失败的错误类型；失败时不得保存半成品分析

#### M04-D 运行记录与真实模型

- [x] 实现最小 `AgentRun`，记录 `user_id`、`run_type`、目标实体、状态、模型、提示词版本、输入哈希、结构化输出、校验结果、起止时间、耗时和错误
- [x] 区分运行状态 `succeeded / failed` 与输出校验结果 `passed / failed`，避免“模型调用成功但输出被安全降级”被误记为运行失败
- [x] 支持 `jd_parse / evidence_match / resume_suggestion` 三种 `run_type`，后续模型能力复用同一记录结构
- [x] 接入一个 OpenAI-compatible 结构化模型，并通过配置选择 Fake 或真实 Client
- [x] 记录实际使用的模型名和提示词版本，不记录完整敏感输入到普通日志

#### M04-E 测试与验收

- [x] 添加正常、缺失、额外字段、类型错误、语义非法、超时和模型异常测试
- [ ] 使用至少 3 条真实中文 JD 完成手动解析验收

验收：Fake 和真实 Client 使用同一 Parser；合法输出经过校验并写入 `AgentRun`，业务级 `JobAnalysis` 留到 M07 保存；非法输出可解释地失败；同一字段不存在两套互相冲突的模型结果。

### M05 资格规则

- [x] 定义 `EligibilityInput`、单项结果和总体结果 Schema
- [x] 定义 `SearchPreferences` Schema，至少明确 `preferred_locations`、`job_types`、`earliest_start_date`、`weekly_days` 和 `internship_duration_months` 的类型、范围和 `null` 语义
- [x] 将 Eligibility Checker 实现为纯函数
- [x] 支持 `pass / fail / unknown`
- [x] 实现毕业年份检查
- [x] 实现学历和专业检查
- [x] 实现地点检查
- [x] 实现实习时长和到岗时间检查
- [x] 对学历、专业、地点和日期使用确定性规范化，不把模糊语义交给评分函数猜测
- [x] 每条结果保存规则名、结论、原因、JD 原文依据和需要用户补充的信息
- [x] 实现总体资格汇总：任一 `fail` 则总体 `fail`，否则有 `unknown` 则总体 `unknown`
- [x] 覆盖信息缺失、边界年份、学历层级、地点别名、日期边界和多条件组合测试

验收：相同输入始终得到相同结果；缺少用户信息或 JD 信息时返回 `unknown`，不能默认通过或失败。

### M06 证据召回、匹配与确定性评分

- [x] 明确 `JobRequirement` 是匹配与评分的规范输入，派生技能列表不得形成第二套事实
- [x] 实现关键词和技能标签召回
- [x] 限制召回范围为当前用户证据，并定义大小写、别名、重复技能和空查询处理
- [x] 实现 `RequirementMatch`
- [x] 支持 `supported / partial / unsupported`
- [x] 使用 Fake Model Client 跑通语义匹配，真实模型复用 M04 的 Client 边界
- [x] 验证 `evidence_ids` 存在且属于当前用户
- [x] 禁止生成证据中不存在的项目、技能和数字
- [x] 实现 Evidence Validator
- [x] 将无效 ID、跨用户引用或虚构事实的匹配安全降级为 `unsupported`，清空 `evidence_ids` 和非法解释，并在 `AgentRun` 中记录 `validation_failed`
- [x] 规定合法 `unsupported` 的 `evidence_ids` 必须为空；`supported / partial` 必须至少引用一个有效证据
- [x] 实现 `MatchScoreCalculator`
- [x] 使用 `1 / 0.5 / 0` 计算 supported / partial / unsupported
- [x] 实现 60% 必备技能、20% 加分技能、20% 偏好权重
- [x] 实现硬性资格 `fail` 门控和 `unknown` 提醒
- [x] 对要求按规范化后的 `category + name` 去重，再计算各分组分母
- [x] 仅在 JD 明确不存在某类要求时将该分组标记为 `not_applicable`，并在其他适用分组间按原比例重分配权重
- [x] JD 信息缺失不能当作 `not_applicable`；所有软评分分组都不可用时分数返回 `null` 并提示信息不足
- [x] 添加无证据、跨用户证据、错误引用、虚构数字、重复要求和评分边界测试

验收：每个 `supported / partial` 结论都有当前用户的有效证据，用户可见结果不包含非法引用；分数可由保存的明细确定性复算。

### M07 岗位分析页面

- [x] 实现岗位级 `JobParseResult` 模型和迁移，保存 `job_posting_id`、`content_hash`、Schema/Parser/Prompt 版本、模型和结构化 JD
- [ ] 让 M04 创建的 `JobParseResult` 按 `content_hash + schema_version + parser_version + prompt_version + model` 复用，不包含任何用户画像、证据或评分结果
- [ ] 实现用户级 `JobAnalysis` 模型和迁移，保存 `user_id`、`job_posting_id`、`parse_result_id`、`analysis_version`、资格结果、匹配结果、分数、风险、`created_at` 和可选 `invalidated_at`
- [ ] 实现 `JDAnalysisService` 编排 Parser、Eligibility、Retriever、Matcher、Validator 和 Score Calculator
- [ ] 每次分析都使用当前用户画像和当前证据重新计算资格、匹配与分数，不跨用户复用完整 `JobAnalysis`
- [ ] 用户画像、证据、岗位文本或分析规则变化后设置旧分析的 `invalidated_at`；最新结果查询排除已失效记录并允许重新分析
- [ ] 实现 `DELETE /api/evidence/{evidence_id}`；硬删除证据以及引用它的 RequirementMatch 和 JobAnalysis，M09 再扩展到材料建议
- [ ] 实现同步岗位分析 API；MVP 不引入后台队列和轮询任务
- [ ] `POST /api/jobs/{job_id}/analyze` 等待完整分析后返回新结果，`GET /api/jobs/{job_id}/analysis` 读取当前用户最新的成功结果
- [ ] 只在整条流水线成功后保存 `JobAnalysis`；可安全降级的非法匹配以 `unsupported + risk` 继续，无法降级的模型或校验错误写入 `AgentRun` 并返回统一错误
- [ ] API 返回不存在、分析失败、模型不可用和校验失败等统一错误
- [ ] 展示结构化 JD
- [ ] 展示资格检查结果
- [ ] 展示每条要求的证据引用
- [ ] 展示匹配分数、风险项和缺失项
- [ ] 展示 `unknown` 的补充信息请求
- [ ] 页面覆盖加载、空结果、失败、重试和内容已变化状态
- [ ] 准备 10～20 条初始测试样本
- [ ] 添加分析 Service 集成测试和 API 测试
- [ ] 完成手动 JD 分析演示

验收：粘贴一条真实 JD 后，页面可以完整展示结构化字段、资格、证据引用、分数和风险；Fake 模式可重复演示，真实模型失败时不会展示半成品。

## B：申请与审批闭环

### M08 申请状态机与事件

- [ ] 实现轻量 `CandidateJob`
- [ ] 为 `CandidateJob` 添加 `user_id + job_posting_id` 唯一约束和必要索引
- [ ] 实现 `POST /api/candidates`，允许当前用户从手动导入的 `JobPosting` 创建或幂等获取 `SAVED` CandidateJob，不依赖 M10 发现流程
- [ ] 将 Candidate 和 Application 状态定义为枚举，并实现显式转换表
- [ ] 实现完整 Candidate 状态转换
- [ ] 实现 `Application`
- [ ] 实现 Application 状态转换
- [ ] 实现 `prepare_application` 数据库事务
- [ ] 使用 `candidate_job_id` 唯一约束防止重复申请
- [ ] 实现 `DomainEvent`
- [ ] 每次创建和状态转换在同一事务内写入事件
- [ ] 所有读取和写入同时校验当前用户归属
- [ ] 拒绝非法状态转换
- [ ] 定义重复请求、事务回滚和数据库唯一约束冲突的响应
- [ ] 实现 Candidate 和 Application API
- [ ] 实现申请看板和事件时间线
- [ ] 添加完整转换矩阵、非法转换、重复准备申请、跨用户访问和事务回滚测试

验收：一次“准备申请”只能产生一个 `PREPARING` Application 和一个对应事件；事务任一步失败时不得留下部分状态。

### M09 材料建议与审批

- [ ] 定义 `SuggestionTargetInput`，由用户请求直接提供 `original_text`、`target_type` 和可选 `target_label`；MVP 不创建完整 Resume 实体
- [ ] 实现 `ResumeSuggestion`，关联 `user_id`、`application_id`、`job_analysis_id`，保存目标信息、原文、建议、引用证据、状态和最终文本
- [ ] 定义 Suggestion Generator 输入输出，并使用 Fake 跑通生成流程；生成接口必须接收明确的建议目标和原文
- [ ] 接入真实模型生成建议，复用 M04 的模型配置、版本记录和失败处理
- [ ] 建议必须引用有效 `evidence_ids`
- [ ] 对建议中的项目、技能和数字执行 Evidence Validator
- [ ] Agent 只能创建 `PENDING` 建议
- [ ] 支持接受建议
- [ ] 支持编辑后接受
- [ ] 支持拒绝建议
- [ ] 保存审批状态和 `final_text`
- [ ] 明确三种决策的 `final_text` 规则：接受使用建议文本，编辑后接受使用用户文本，拒绝时为空
- [ ] 前端展示原文、建议文本和 Diff
- [ ] 未接受内容不能成为最终文本
- [ ] 审批状态和 `DomainEvent` 在同一事务内保存
- [ ] 拒绝重复审批、跨用户审批和对非 `PENDING` 建议再次决策
- [ ] 删除被引用证据时，删除关联建议及其 `final_text`，事件只保留不含材料正文的审计元数据
- [ ] 添加虚构证据、三种审批路径、非法状态、事务回滚和 Diff 展示测试

验收：Agent 只能提出建议，只有用户决策才能产生最终文本；每条被接受的事实都可追溯到有效证据。

## C：轻量岗位发现

### M10 一个真实来源与岗位发现池

- [ ] 在开发前明确首个真实来源、公开访问方式、使用边界和固定 Fixture
- [ ] 实现仅允许 HTTP/HTTPS 的岗位 URL 规范化和安全检查
- [ ] 阻止本机、私网、保留地址和云元数据地址，并对每次重定向重新校验
- [ ] 防止 DNS 解析后落入受限地址；限制端口和凭据型 URL
- [ ] 实现带响应大小、连接/读取超时、重定向次数和有限重试的 HTTP Reader
- [ ] 实现 Generic HTML 读取，移除脚本、样式、隐藏元素和无关文本
- [ ] 优先读取 JSON-LD 等页面结构化数据，缺失时回退到正文提取
- [ ] 定义读取失败类型和回退提示，不把网页内容当作系统指令
- [ ] 实现 `JobSourceAdapter` 接口
- [ ] 完成 1 个真实招聘来源 Adapter
- [ ] 使用固定 HTML Fixture 测试列表、详情、字段缺失和页面结构变化
- [ ] 实现公司、标题、地点、URL 和正文的标准化
- [ ] 定义同来源岗位 ID、规范 URL 和内容指纹的去重优先级
- [ ] 实现用户手动触发发现
- [ ] 实现轻量 `DiscoveryRun`，保存当前用户、来源、状态、发现/新增/重复数量、失败摘要和起止时间
- [ ] 将发现结果写入 `JobPosting + CandidateJob`，不自动创建 Application
- [ ] 实现岗位发现页和基础筛选
- [ ] 用户选择岗位后可以进入完整分析
- [ ] 添加 SSRF、重定向、超时、超大响应、恶意 HTML、Fixture、去重和发现 API 测试

验收：用户手动触发后可从一个真实公开来源获得岗位并进入发现池；重复运行不制造重复岗位；任何受限 URL 都不能发起实际业务请求。

## D：评测与演示

### M11 评测、失败案例与演示

- [ ] 定义可版本化的数据集格式、字段标签、资格标签和证据标注规范
- [ ] 准备 30～50 条人工标注样本，并记录来源、授权边界和标注说明
- [ ] 为正常、字段缺失、`unknown`、无证据、读取失败和非法模型输出预先规定最小样本分布
- [ ] 区分开发样本和最终评测样本，避免只对演示案例调参
- [ ] 实现字段级 Precision
- [ ] 实现字段级 Recall
- [ ] 实现 Macro-F1
- [ ] 实现资格分类准确率
- [ ] 实现误判符合率
- [ ] 实现 Evidence Precision
- [ ] 实现 Evidence Coverage
- [ ] 实现 Unsupported Claim Rate
- [ ] 明确各指标的匹配、空值、分母为零和聚合规则
- [ ] 在最终评测前冻结 Evaluation Manifest 和发布阈值，不能查看最终结果后再调整通过标准
- [ ] 分别报告原始模型输出和 Validator 后用户可见输出；用户可见 Unsupported Claim Rate 的发布要求为 0
- [ ] 实现可重复运行的评测命令和机器可读结果文件
- [ ] 汇总 M04 起保存的 `AgentRun`，记录模型、提示词和数据集版本
- [ ] 记录随机参数、运行时间、失败数和环境信息
- [ ] 增加 `unknown` 案例
- [ ] 增加无证据案例
- [ ] 增加网页读取失败案例
- [ ] 增加非法模型输出、跨用户证据和重复申请案例
- [ ] 完成从手动 JD 到分析、申请、审批和时间线的核心端到端测试
- [ ] 完成从真实来源发现到岗位分析的端到端测试
- [ ] 完成真实岗位发现到申请管理的演示
- [ ] 整理实际评测结果和项目截图
- [ ] 只在指标实际运行后更新 README 和简历表述

验收：在固定数据集和配置上可以一条命令复现指标；失败案例有明确输出；演示链路不依赖手工修改数据库。

## 发布前验证（不计入 M01～M11 核心进度）

- [ ] 在安装 Docker Desktop 或可连接 PostgreSQL 的环境中启动 `pgvector/pgvector:pg16`
- [ ] 使用全新 PostgreSQL 数据库执行 `alembic upgrade head`
- [ ] 在 PostgreSQL 下运行后端测试和核心 API 冒烟测试
- [ ] 验证 JSON、时间字段、唯一约束和事务行为与 SQLite 结果一致
- [ ] 若启用 JSONB 或 pgvector，增加对应方言迁移和回归测试
- [ ] 记录验证日期、PostgreSQL 镜像版本、迁移版本和已知差异

## 可选扩展

- [ ] 第 2 个真实招聘来源 Adapter
- [ ] 平台定时同步
- [ ] Playwright 动态页面兜底
- [ ] Embedding 证据召回
- [ ] 5～10 个招聘来源
- [ ] 100～300 条岗位数据
- [ ] `JobSnapshot` 和岗位变化检测
- [ ] `ResumeVersion`
- [ ] 独立 `ToolCallTrace`
