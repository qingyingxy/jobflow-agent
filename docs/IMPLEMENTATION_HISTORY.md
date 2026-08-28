# JobFlow Agent 里程碑与实现记录

> 本文档保留 `v0.1` 至 `v0.4` 的验收清单。未完成项均为当前本地版本之外的
> 可选扩展，不影响 `v0.4 Assisted Apply` 的发布状态。

> 当前阶段：M01～M19 与 `v0.4 Assisted Apply` 已完成。
> 已完成里程碑：19 / 19
> 外部与离线验收：DeepSeek `deepseek-v4-flash` 已完成 39 条严格 AI 校招岗位的 Core / Staged Parser 评测；M12 的 13 个 Discovery Agent、M13 的 9 个 Trusted Discovery 与 M19 的 14 个 Assisted Apply 固定场景全部通过。

> 当前状态：项目采用 SQLite-only 单机发布范围；公网多用户托管与跨进程调度属于后续扩展。

项目概览见 [README](../README.md)，实现约束和完成标准见
[DEVELOPMENT_WORKFLOW.md](DEVELOPMENT_WORKFLOW.md)。

## 维护规则

- 只有代码、测试和必要文档全部完成，里程碑才能勾选；
- 每次完成任务时，在同一次提交中更新本文件；
- 里程碑内部可以继续拆 GitHub Issue，本文件跟踪 M01～M19 的产品级可验收结果；
- 里程碑清单描述可验收结果，具体编码步骤、负责人和排期放到 GitHub Issue；
- SQLite 是唯一业务数据库和发布验收数据库；
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
- [x] 添加 FastAPI、SQLAlchemy、Alembic 和 Pydantic Settings
- [x] 配置 SQLite-only 本地数据库
- [x] 添加 Pytest、pytest-asyncio 和 Ruff 开发依赖
- [x] 提交 `pyproject.toml` 和 `uv.lock`
- [x] 创建 FastAPI 应用入口
- [x] 初始化 Next.js 和 TypeScript
- [x] 配置 Pydantic Settings
- [x] 配置 SQLAlchemy 和 Alembic
- [x] 添加首个数据库迁移基线
- [x] 启用 SQLite 外键、WAL 和忙等待保护
- [x] 添加统一错误响应和结构化日志
- [x] 添加 `GET /health`
- [x] 配置 Pytest
- [x] 编写本地启动说明
- [x] 后端、前端、SQLite 迁移和测试均可运行

### M02 用户画像与经历证据（SQLite）

- [x] 实现 `UserProfile`
- [x] 使用 SQLite JSON 保存 `search_preferences`
- [x] 实现 `EvidenceItem`
- [x] 实现用户画像 API
- [x] 实现证据新增、查询和编辑 API
- [x] 验证证据只能由所属用户访问
- [x] 添加 Profile 和 Evidence 测试

### M03 JD 导入与结构化 Schema（SQLite）

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
- [x] 使用至少 3 条真实中文 JD 完成手动解析验收

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
- [x] 让 M04 创建的 `JobParseResult` 按 `content_hash + schema_version + parser_version + prompt_version + model` 复用，不包含任何用户画像、证据或评分结果
- [x] 实现用户级 `JobAnalysis` 模型和迁移，保存 `user_id`、`job_posting_id`、`parse_result_id`、`analysis_version`、资格结果、匹配结果、分数、风险、`created_at` 和可选 `invalidated_at`
- [x] 实现 `JDAnalysisService` 编排 Parser、Eligibility、Retriever、Matcher、Validator 和 Score Calculator
- [x] 每次分析都使用当前用户画像和当前证据重新计算资格、匹配与分数，不跨用户复用完整 `JobAnalysis`
- [x] 用户画像、证据、岗位文本或分析规则变化后设置旧分析的 `invalidated_at`；最新结果查询排除已失效记录并允许重新分析
- [x] 实现 `DELETE /api/evidence/{evidence_id}`；硬删除证据以及引用它的 RequirementMatch 和 JobAnalysis，M09 再扩展到材料建议
- [x] 实现同步岗位分析 API；MVP 不引入后台队列和轮询任务
- [x] `POST /api/jobs/{job_id}/analyze` 等待完整分析后返回新结果，`GET /api/jobs/{job_id}/analysis` 读取当前用户最新的成功结果
- [x] 只在整条流水线成功后保存 `JobAnalysis`；可安全降级的非法匹配以 `unsupported + risk` 继续，无法降级的模型或校验错误写入 `AgentRun` 并返回统一错误
- [x] API 返回不存在、分析失败、模型不可用和校验失败等统一错误
- [x] 展示结构化 JD
- [x] 展示资格检查结果
- [x] 展示每条要求的证据引用
- [x] 展示匹配分数、风险项和缺失项
- [x] 展示 `unknown` 的补充信息请求
- [x] 页面覆盖加载、空结果、失败、重试和内容已变化状态
- [x] 准备 10～20 条初始测试样本
- [x] 添加分析 Service 集成测试和 API 测试
- [x] 完成手动 JD 分析演示（Fake 模式）

验收：粘贴一条真实 JD 后，页面可以完整展示结构化字段、资格、证据引用、分数和风险；Fake 模式可重复演示，真实模型失败时不会展示半成品。

## B：申请与审批闭环

### M08 申请状态机与事件

- [x] 实现轻量 `CandidateJob`
- [x] 为 `CandidateJob` 添加 `user_id + job_posting_id` 唯一约束和必要索引
- [x] 实现 `POST /api/candidates`，允许当前用户从手动导入的 `JobPosting` 创建或幂等获取 `SAVED` CandidateJob，不依赖 M10 发现流程
- [x] 将 Candidate 和 Application 状态定义为枚举，并实现显式转换表
- [x] 实现完整 Candidate 状态转换
- [x] 实现 `Application`
- [x] 实现 Application 状态转换
- [x] 实现 `prepare_application` 数据库事务
- [x] 使用 `candidate_job_id` 唯一约束防止重复申请
- [x] 实现 `DomainEvent`
- [x] 每次创建和状态转换在同一事务内写入事件
- [x] 所有读取和写入同时校验当前用户归属
- [x] 拒绝非法状态转换
- [x] 定义重复请求、事务回滚和数据库唯一约束冲突的响应
- [x] 实现 Candidate 和 Application API
- [x] 实现申请看板和事件时间线
- [x] 添加完整转换矩阵、非法转换、重复准备申请、跨用户访问和事务回滚测试

验收：一次“准备申请”只能产生一个 `PREPARING` Application 和一个对应事件；事务任一步失败时不得留下部分状态。当前已通过完整测试和 SQLite 迁移检查。

### M09 材料建议与审批

- [x] 定义 `SuggestionTargetInput`，由用户请求直接提供 `original_text`、`target_type` 和可选 `target_label`；MVP 不创建完整 Resume 实体
- [x] 实现 `ResumeSuggestion`，关联 `user_id`、`application_id`、`job_analysis_id`，保存目标信息、原文、建议、引用证据、状态和最终文本
- [x] 定义 Suggestion Generator 输入输出，并使用 Fake 跑通生成流程；生成接口必须接收明确的建议目标和原文
- [x] 接入真实模型生成建议，复用 M04 的模型配置、版本记录和失败处理
- [x] 建议必须引用有效 `evidence_ids`
- [x] 对建议中的项目、技能和数字执行 Evidence Validator
- [x] Agent 只能创建 `PENDING` 建议
- [x] 支持接受建议
- [x] 支持编辑后接受
- [x] 支持拒绝建议
- [x] 保存审批状态和 `final_text`
- [x] 明确三种决策的 `final_text` 规则：接受使用建议文本，编辑后接受使用用户文本，拒绝时为空
- [x] 前端展示原文、建议文本和 Diff
- [x] 未接受内容不能成为最终文本
- [x] 审批状态和 `DomainEvent` 在同一事务内保存
- [x] 拒绝重复审批、跨用户审批和对非 `PENDING` 建议再次决策
- [x] 删除被引用证据时，删除关联建议及其 `final_text`，事件只保留不含材料正文的审计元数据
- [x] 添加虚构证据、三种审批路径、非法状态、事务回滚和 Diff 展示测试

验收：Agent 只能提出 `PENDING` 建议，只有用户决策才能产生最终文本；每条被接受的事实都可追溯到有效证据。当前已通过 Fake、模型失败、非法证据、三种审批路径、跨用户访问和删除联动测试。

## C：轻量岗位发现

### M10 一个真实来源与岗位发现池

- [x] 在开发前明确首个真实来源、公开访问方式、使用边界和固定 Fixture（Greenhouse public Job Board API）
- [x] 实现仅允许 HTTP/HTTPS 的岗位 URL 规范化和安全检查
- [x] 阻止本机、私网、保留地址和云元数据地址，并对每次重定向重新校验
- [x] 防止 DNS 解析后落入受限地址；限制端口和凭据型 URL
- [x] 实现带响应大小、连接/读取超时、重定向次数和有限重试的 HTTP Reader
- [x] 实现 Generic HTML 读取，移除脚本、样式、隐藏元素和无关文本
- [x] 优先读取 JSON-LD 等页面结构化数据，缺失时回退到正文提取
- [x] 定义读取失败类型和回退提示，不把网页内容当作系统指令
- [x] 实现 `JobSourceAdapter` 接口
- [x] 完成 1 个真实招聘来源 Adapter（Greenhouse）
- [x] 完成第 2 个真实招聘来源 Adapter（ByteDance 公开职位接口）
- [x] 完成第 3 个真实招聘来源 Adapter（Tencent 公开职位接口），验证来源架构可扩展
- [x] 使用固定 HTML / JSON Fixture 测试列表、详情、字段缺失和页面结构变化
- [x] 实现公司、标题、地点、URL 和正文的标准化
- [x] 定义同来源岗位 ID、规范 URL 和内容指纹的去重优先级
- [x] 实现用户手动触发发现
- [x] 实现轻量 `DiscoveryRun`，保存当前用户、来源、状态、发现/新增/重复数量、失败摘要和起止时间
- [x] 将发现结果写入 `JobPosting + CandidateJob`，不自动创建 Application
- [x] 实现岗位发现页和基础筛选
- [x] 用户选择岗位后可以进入完整分析
- [x] 添加 SSRF、重定向、超时、超大响应、恶意 HTML、Fixture、去重和发现 API 测试
- [x] 将 40 家目标公司表转为官方招聘入口来源注册表
- [x] 支持用户用自然语言目标触发官方官网即时搜索
- [x] 支持目标公司多选，并将 `company_ids` 作为 Agent 的确定性来源边界
- [x] 每次搜索最多保存 20 条岗位，并按目标相关性排序
- [x] 对严格匹配中排序靠前的 5 条岗位自动运行 JD 解析、资格检查和证据匹配
- [x] 保存搜索目标、分析进度、失败摘要，并提供运行状态查询接口
- [x] 自动恢复超过配置时限仍为 `RUNNING` 的发现任务，保留已保存岗位事实并写入恢复轨迹
- [x] 支持官网 JSON-LD JobPosting 和岗位详情链接两种读取路径
- [x] 将岗位标题和来源元数据作为可审计的字段证据，不再因正文缺少类型词而误失败
- [x] 排除招聘指南、流程、FAQ、活动和职位列表等非具体岗位页面
- [x] 动态官网静态读取不到具体岗位时记录专用 Adapter 提示，不再生成假岗位
- [x] 增加小马智行 `guideline` 误收和动态页面空壳的回归测试
- [x] 目标地区无结果时透明放宽地点，并保留候选岗位真实地点
- [x] 所有来源均为 0 条时进入人工接管，支持粘贴 JD 继续分析

验收：用户用自然语言目标即时触发后，系统从官方公司入口获取最多 20 条岗位，划分严格匹配 / 拓展候选并只自动分析严格匹配前 5 条；动态来源显示可操作的失败原因，不把说明页当成岗位；重复运行不制造重复岗位；任何受限 URL 都不能发起实际业务请求。

## D：评测与演示

### M11 评测、失败案例与演示

- [x] 定义可版本化的数据集格式、字段标签、资格标签和证据标注规范
- [x] 基于公开招聘页面准备 39 条严格评测子集，记录来源、授权边界、规则标签和人工覆盖
- [x] 为正常、字段缺失、`unknown`、无证据、读取失败和非法模型输出预先规定最小样本分布
- [x] 区分开发样本和最终评测样本，避免只对演示案例调参
- [x] 实现字段级 Precision
- [x] 实现字段级 Recall
- [x] 实现 Macro-F1
- [x] 实现资格分类准确率
- [x] 实现误判符合率
- [x] 实现 Evidence Precision
- [x] 实现 Evidence Coverage
- [x] 实现 Unsupported Claim Rate
- [x] 明确各指标的匹配、空值、分母为零和聚合规则
- [x] 冻结开发集与 39 条 `split=eval` 严格 Evaluation Manifest
- [x] 分别报告原始模型输出和 Validator 后用户可见输出；用户可见 Unsupported Claim Rate 的发布要求为 0
- [x] 实现可重复运行的评测命令和机器可读结果文件
- [x] 增加 Core Parser 轻量字段路径，降低发现阶段完整 JD 输出超时风险
- [x] 增加 Detail Parser 与 Staged Parser，API 默认使用两阶段解析并在本地组装完整 JD
- [x] 汇总 M04 起保存的 `AgentRun`，记录模型、提示词和数据集版本
- [x] 记录随机参数、运行时间、失败数和环境信息
- [x] 增加 `unknown` 案例
- [x] 增加无证据案例
- [x] 增加网页读取失败案例
- [x] 覆盖非法模型输出、跨用户证据和重复申请案例（评测 Fixture、M06/M08 测试和端到端回归）
- [x] 完成从手动 JD 到分析、申请、审批和时间线的核心端到端测试
- [x] 完成从真实来源发现到岗位分析的端到端测试
- [x] 增加可重复的 Playwright 岗位发现 E2E 演示
- [x] 整理实际评测结果、PNG 和 GIF
- [x] 只在指标实际运行后更新 README；简历仅使用带评测范围的表述

验收：在固定数据集和配置上可以一条命令复现指标；失败案例有明确输出；演示链路不依赖手工修改数据库。

### M12 Discovery Agent 控制面评测

- [x] 在网络请求前持久化经过 Schema 校验的 `search_plan`
- [x] 在计划中锁定来源白名单、逐来源工具顺序、Top 20 / Top 5 预算和停止条件
- [x] 为执行轨迹补充发生时间、耗时、稳定错误码、输出数量和真实回退顺序
- [x] 覆盖未登记来源、私有地址和 SSRF 请求在访问前被拒绝
- [x] 覆盖字节、腾讯专用 Adapter 的确定性工具路由
- [x] 覆盖专用 Adapter 失败或空结果后的静态读取回退
- [x] 验证单一来源失败不影响其他来源
- [x] 验证动态页面壳和招聘指南不会被保存为岗位
- [x] 验证无有效岗位时进入人工粘贴 JD 接管
- [x] 验证每次最多保存 20 条，且只有严格匹配 Top 5 自动分析
- [x] 验证拓展候选不消耗自动分析预算
- [x] 验证重复发现不会创建重复 `JobPosting` 或 `CandidateJob`
- [x] 实现可重复的 Discovery Agent 离线评测命令和机器可读结果
- [x] 记录 13/13 固定场景结果及其离线 Fixture 边界

验收：13 个离线控制面场景全部通过；来源越权访问率和非岗位误收率为 0；所有成功、失败和回退路径都有可复现轨迹。结果只代表固定控制面场景，不扩展为真实官网召回率或完整 Agent 准确率。

## E：可信岗位发现

### M13 多渠道岗位发现与官方验证

#### M13-A 数据模型与兼容迁移

- [x] 扩展现有 `DiscoveryRun` 和 `DiscoverySearchPlan`，保存原始意图、结构化条件、允许来源和预算，不新增第二套查询事实源
- [x] 定义 `JobLead`，保存线索 URL、来源 Provider、搜索摘要、公司/岗位提示、发现时间和当前状态
- [x] 定义 `LeadVerification`，保存正文来源、验证结论、失败原因、验证时间和可审计证据
- [x] 为线索定义 `NEW / VERIFYING / VERIFIED / NEEDS_BROWSER / NEEDS_USER / DUPLICATE / REJECTED_NON_JOB / FAILED` 状态
- [x] 为正式岗位单独定义 `ACTIVE / UNKNOWN / STALE / CLOSED` 可用状态，不能与线索验证状态混用
- [x] 为来源身份、规范 URL、来源岗位 ID、内容指纹和用户归属添加约束与索引
- [x] 增加兼容迁移：专用官方 Adapter 数据标记为官方来源，手动文本标记为 `USER_PROVIDED`，无法确认的历史数据标记为 `LEGACY_UNVERIFIED`
- [x] 保持现有 `JobPosting`、`CandidateJob` 和分析 API 向后兼容

#### M13-B 多渠道 LeadProvider

- [x] 定义统一 `LeadProvider` 协议，Provider 只能返回线索，不能绕过验证直接创建可信岗位
- [x] 将 Greenhouse、ByteDance、Tencent 和官方公司注册表接入 `JobLead` 验证边界
- [x] 将现有手动 URL 与完整 JD 接管整理为统一 `ManualImportProvider` 协议实现
- [x] 支持手动 URL 建立线索，并用完整 JD 完成原线索接管，结果明确标记为 `USER_PROVIDED`
- [x] 实现受控的 `ExternalAgentProvider` 接口，接收 URL、搜索摘要、推测字段和发现时间
- [x] 外部 Agent 只能通过 API 提交 `JobLead`，不能声明官方 Provider 或修改岗位验证状态
- [x] 为第三方平台线索保留来源说明，不把第三方摘要描述成官方事实

#### M13-C 验证、去重与可用性

- [x] 实现 `JobLeadVerifier`，复用 URL 安全检查、受控读取、JSON-LD 和页面正文解析
- [x] 验证页面是具体岗位，而不是招聘首页、列表、指南、新闻、活动或搜索摘要
- [x] 从正文重新验证公司、标题、地点、招聘类型、届别和岗位要求
- [x] 只有验证成功的线索才能生成或关联正式 `JobPosting`
- [x] `NEEDS_BROWSER`、`NEEDS_USER` 和失败状态提供明确原因与结构化 `next_action`
- [x] 按来源岗位 ID、规范 URL 和内容指纹执行统一去重
- [x] 在正式岗位上保存 `first_seen_at`、`last_seen_at`、`last_verified_at`、内容哈希和可用状态
- [x] 连续读取失败只能进入 `UNKNOWN` 或 `STALE`；只有明确关闭证据或人工确认才能进入 `CLOSED`
- [x] 未验证线索不能进入严格匹配、Top 5 自动分析或申请准备

#### M13-D API、页面与评测

- [x] 实现线索提交、列表、验证和验证结果查询 API
- [x] 实现用户粘贴完整 JD 的接管 API，并保持原 `JobLead`、验证历史和候选岗位关联
- [x] 实现浏览器接管执行 API；登录、验证码和 2FA 仍必须停下交给用户
- [x] 岗位发现页明确区分已验证岗位、待验证线索、需要浏览器和需要用户处理
- [x] 展示 Provider、官方验证状态、最后验证时间和失败原因
- [x] 添加用户越权、非岗位误收、重复线索和重复验证幂等测试
- [x] 添加搜索摘要污染、过期状态和并发验证测试
- [x] 增加官方验证率、非岗位误收率、去重准确率和验证失败分布指标

验收：官方 Adapter、外部 Agent、第三方链接和手动导入都先产生可追踪线索；只有通过正文与来源验证的线索才能成为可信岗位并进入自动分析。外部搜索扩大召回范围，但不能绕过现有安全和事实校验。

## F：可审核的人工投递闭环

### M14 候选人档案与材料库

- [x] 定义 `CandidatePrivateProfile`，与现有搜索偏好和公开分析画像分开存储
- [x] 覆盖联系方式、当前状态、到岗时间、工作资格、赞助需求、薪资策略和搬迁意愿
- [x] 自愿身份披露默认只保存处理策略，不默认保存具体敏感答案
- [x] 为敏感字段定义 `missing / provided / not_applicable / declined_to_store` 语义
- [x] 定义 `ResumeAsset` 和 `ResumeVersion`，保存文件身份、内容哈希、版本、岗位族、来源版本和生成原因
- [x] 定义 `AnswerBankEntry`，保存问题模式、已确认答案、适用范围、敏感级别和确认时间
- [x] 增加简历文件类型、大小、哈希、重复上传和用户归属校验
- [x] 普通日志和 DomainEvent 不记录简历正文、联系方式和敏感答案
- [x] 实现档案、简历版本和答案库 API
- [x] 实现分步初始化与材料库页面，明确展示缺失、拒绝保存和需要确认状态
- [x] 添加跨用户访问、敏感日志脱敏、文件校验和高影响字段缺失测试

验收：系统具备准备真实申请所需的最小资料来源；任何高影响字段缺失时只能产生 `needs_confirmation`，Agent 不能猜测或静默填充。

### M15 可审核投递包

- [x] 定义 `ApplicationPacket`、`PacketRevision` 和 `PacketDecision`
- [x] 投递包绑定当前用户、Application、JobPosting、有效 JobAnalysis 和 JD 内容哈希
- [x] 冻结画像版本、简历版本、选中证据、表单答案、开放题、风险和待确认项
- [x] 定义 `DRAFT / NEEDS_REVIEW / APPROVED / SUPERSEDED` 状态及转换表
- [x] Agent 只能创建或更新草稿，只有用户可以批准投递包
- [x] 已批准版本不可原地修改；岗位、画像、简历或答案变化后生成新版本并使旧版本失效
- [x] 资格未知、敏感答案未确认、材料缺失或分析失效时禁止批准
- [x] 实现生成、读取、逐项编辑、批准和创建新版本 API
- [x] 实现投递包审核页，展示 JD 快照、简历 Diff、证据来源、敏感答案和阻塞项
- [x] 添加并发审批、重复审批、过期分析、跨用户访问和版本不可变测试

验收：用户批准的是一份内容明确、版本冻结、事实可追溯的投递材料；任何关键输入变化都不能悄悄修改已批准内容。

### M16 投递尝试、阻塞与提交凭证

- [x] 定义 `ApplicationAttempt`、`ApplicationBlocker` 和 `SubmissionReceipt`
- [x] 定义 `CREATED / FORM_IN_PROGRESS / NEEDS_USER / BLOCKED / READY_TO_SUBMIT / SUBMITTED / FAILED / ABANDONED` 状态
- [x] Attempt 必须绑定具体岗位、官方申请 URL 和已批准的 PacketRevision
- [x] 第一版支持用户手动打开官网和提交，系统负责检查清单、阻塞记录和凭证保存
- [x] Blocker 保存类别、观察、停止原因、可否重试、下一步策略和用户动作
- [x] Receipt 支持确认文本、确认 URL、申请编号和脱敏截图元数据
- [x] 只有 Attempt 成功且存在有效 Receipt，才能在同一事务内将现有 Application 推进至 `SUBMITTED`
- [x] 重复请求、刷新、失败重试和并发提交不得创建重复 Application 或 Receipt
- [x] 实现投递执行检查页、阻塞队列和提交凭证页面
- [x] 添加伪成功、无凭证提交、重复提交、跨用户访问和事务回滚测试

验收：保存岗位、准备申请和打开表单都不等于提交；任何 `SUBMITTED` Application 都能追溯到已批准投递包、投递尝试和真实凭证。

### M17 跟进中心

- [x] 定义 `FollowUpTask`，保存事件类型、日期时间、联系人、渠道、状态、下一步动作和备注
- [x] 支持测评、笔试、面试、材料截止、主动跟进和自定义事件
- [x] 实现创建、编辑、完成、取消和逾期状态
- [x] 将跟进任务与 Application 时间线关联，但不把提醒状态作为申请状态事实
- [x] 实现今日待办、逾期、未来 7 天和未来 30 天视图
- [x] 实现日历和申请详情时间线
- [x] 暂不监听邮箱或短信，外部消息由用户手动确认后录入
- [x] 添加时区、边界日期、重复事件、跨用户访问和状态转换测试

验收：用户可以从已提交申请持续跟踪到测评、面试、Offer、拒绝或撤回，且每个下一步动作都有明确时间和状态。

## G：有限浏览器辅助与发布验证

### M18 有限 ATS 浏览器辅助

- [x] 定义 `detect → inspect → map_fields → fill → verify → request_approval → submit → capture_receipt` Adapter 契约
- [x] 先选择 1～2 个结构稳定且符合访问边界的 ATS，优先评估 Greenhouse 和 Lever
- [x] 浏览器执行必须绑定具体申请 URL、已批准 PacketRevision 和当前 Attempt
- [x] 只自动填写来源明确且已批准的低风险字段
- [x] 薪资、工作资格、法律问题和表述不一致的字段必须暂停并请求用户确认
- [x] 登录、CAPTCHA、Cloudflare、2FA、权限提示和异常上传必须进入用户接管
- [x] 最终提交前展示公司、岗位、简历版本、关键答案、开放题和风险摘要
- [x] 使用与岗位、URL、PacketRevision 绑定的一次性授权；授权不得跨任务复用
- [x] 提交后验证成功页或确认信息并创建 Receipt；无法验证时不得标记 `SUBMITTED`
- [x] 使用本地 Fixture 覆盖字段映射、上传、下拉框、接管、授权和凭证捕获
- [x] 暂不支持任意网站、Workday 和无人值守批量提交

验收：有限 ATS 可以在明确授权下完成可重复辅助填写；所有敏感、不可验证和不可逆操作都能正确暂停，且提交状态仍由确定性代码和真实凭证控制。

### M19 端到端评测、安全与发布加固

- [x] 建立本地 Mock ATS，覆盖上传异常、原生/自定义下拉框、开放题、敏感问题和动态页面变化
- [x] 覆盖登录、CAPTCHA、权限接管、重复提交、成功页、失败页和伪成功页
- [x] 评测岗位线索官方验证率、非岗位误收率、去重准确率和过期状态准确率
- [x] 评测字段填写正确率、简历版本选择准确率、人工接管准确率和提交凭证覆盖率
- [x] 敏感字段误填率和错误标记为已提交的比例发布阈值均为 0
- [x] 记录从用户选择岗位到 `READY_TO_SUBMIT` 的耗时和人工干预次数
- [x] 实现用户数据导出、彻底删除和文件清理流程
- [x] 完成日志脱敏、文件内容校验、敏感配置管理和审计元数据检查
- [x] 实现 OIDC Bearer Token 服务端验签、可信网关模式和 fail-closed 配置，客户端不能用 `X-User-ID` 覆盖生产身份
- [x] 增加 SQLite 全新迁移、全量 pytest、Ruff、前端构建和 Playwright E2E CI 门禁
- [x] 明确 OIDC 真实租户演练属于公网托管范围，不阻塞本地版本
- [x] 文档明确 Fixture、单机、真实官网和真实投递评测的边界，不夸大指标

验收：从多渠道发现、官方验证、岗位分析、投递包审批、辅助填写到提交凭证和后续跟进形成可重复端到端链路；系统不会猜测敏感事实，也不会把未验证提交描述为成功。

## 版本切分

- [x] `v0.2 Trusted Discovery`：完成 M13，多渠道线索统一经过官方验证后入库
- [x] `v0.3 Verified Application Preparation`：完成 M14～M17，支持人工提交但系统全程管理
- [x] `v0.4 Assisted Apply`：完成 M18～M19，在可审计授权边界内辅助填写有限 ATS

## 后续可选验证（不阻塞 v0.4 本地版）

- [ ] 对 39 条规则标签完成独立人工复核；对外发布时说明标注者数量和一致性
- [x] 实现真实 OIDC/JWT 服务端验证与可信网关接入契约，生产模式忽略客户端 `X-User-ID`
- [ ] 配置实际身份租户或网关并完成 staging 登录演练
- [ ] 将单进程超时恢复升级为跨进程持久任务恢复

## 可选扩展

- [x] ByteDance 与 Tencent 两个大厂公开职位专用 Adapter
- [ ] Embedding 证据召回
- [ ] M13 后扩展到 5～10 个稳定 LeadProvider / ATS 来源
- [ ] 100～300 条岗位数据
- [ ] 独立 `ToolCallTrace`
- [ ] Workday、Oracle 等长流程 ATS
- [ ] 邮件和短信事件导入
- [ ] 定时订阅同步与跨进程持久任务调度
- [ ] 更复杂的 Playwright 动态页面发现回退
