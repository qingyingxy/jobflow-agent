# JobFlow Agent TODO

> 当前阶段：M01 已完成，下一步 M02
> 核心实现进度：1 / 11

> 当前状态：已启用 SQLite-first 本地开发，并保留 Docker Compose 的 PostgreSQL + pgvector 升级路径。

产品设计见 [README.md](README.md)，实现约束和完成标准见 [docs/DEVELOPMENT_WORKFLOW.md](docs/DEVELOPMENT_WORKFLOW.md)。

## 维护规则

- 只有代码、测试和必要文档全部完成，里程碑才能勾选；
- 每次完成任务时，在同一次提交中更新本文件；
- 里程碑内部可以继续拆 GitHub Issue，但本文件只跟踪 M01～M11；
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
- [ ] 连接可用的 PostgreSQL 并执行真实迁移（切换验证）
- [x] 添加统一错误响应和结构化日志
- [x] 添加 `GET /health`
- [x] 配置 Pytest
- [x] 编写本地启动说明
- [x] 后端、前端、SQLite 迁移和测试均可运行

### M02 用户画像与经历证据

- [ ] 实现 `UserProfile`
- [ ] 使用兼容 SQLite 的 JSON 保存 `search_preferences`，切换 PostgreSQL 后再评估 JSONB
- [ ] 实现 `EvidenceItem`
- [ ] 实现用户画像 API
- [ ] 实现证据新增、查询和编辑 API
- [ ] 验证证据只能由所属用户访问
- [ ] 添加 Profile 和 Evidence 测试

### M03 JD 导入与结构化 Schema

- [ ] 实现 `JobPosting`
- [ ] 实现 `RawJobDocument`
- [ ] 实现岗位文本导入
- [ ] 定义结构化 JD Schema
- [ ] 定义资格条件和岗位要求 Schema
- [ ] 缺失字段统一使用 `null`
- [ ] 保存岗位原文、`content_hash` 和读取时间
- [ ] 添加 Schema 和文本导入测试

### M04 JD 解析与输出校验

- [ ] 定义 `StructuredModelClient`
- [ ] 实现 Fake Model Client
- [ ] 使用 Fake 跑通 JD Parser
- [ ] 实现 Pydantic 输出校验
- [ ] 保存字段原文依据
- [ ] 接入真实结构化模型
- [ ] 记录模型和提示词版本
- [ ] 添加正常、缺失和非法输出测试

### M05 资格规则

- [ ] 将 Eligibility Checker 实现为纯函数
- [ ] 支持 `pass / fail / unknown`
- [ ] 实现毕业年份检查
- [ ] 实现学历和专业检查
- [ ] 实现地点检查
- [ ] 实现实习时长和到岗时间检查
- [ ] 实现总体资格汇总
- [ ] 覆盖缺失信息和边界条件测试

### M06 证据召回、匹配与确定性评分

- [ ] 实现关键词和技能标签召回
- [ ] 实现 `RequirementMatch`
- [ ] 支持 `supported / partial / unsupported`
- [ ] 验证 `evidence_ids` 存在且属于当前用户
- [ ] 禁止生成证据中不存在的项目、技能和数字
- [ ] 实现 Evidence Validator
- [ ] 实现 `MatchScoreCalculator`
- [ ] 使用 `1 / 0.5 / 0` 计算 supported / partial / unsupported
- [ ] 实现 60% 必备技能、20% 加分技能、20% 偏好权重
- [ ] 实现硬性资格 `fail` 门控和 `unknown` 提醒
- [ ] 添加无证据、错误引用和评分边界测试

### M07 岗位分析页面

- [ ] 实现岗位分析 API
- [ ] 展示结构化 JD
- [ ] 展示资格检查结果
- [ ] 展示每条要求的证据引用
- [ ] 展示匹配分数、风险项和缺失项
- [ ] 展示 `unknown` 的补充信息请求
- [ ] 准备 10～20 条初始测试样本
- [ ] 完成手动 JD 分析演示

## B：申请与审批闭环

### M08 申请状态机与事件

- [ ] 实现轻量 `CandidateJob`
- [ ] 实现完整 Candidate 状态转换
- [ ] 实现 `Application`
- [ ] 实现 Application 状态转换
- [ ] 实现 `prepare_application` 数据库事务
- [ ] 使用唯一约束防止重复申请
- [ ] 实现 `DomainEvent`
- [ ] 每次状态转换写入事件
- [ ] 拒绝非法状态转换
- [ ] 实现申请看板和事件时间线

### M09 材料建议与审批

- [ ] 实现 `ResumeSuggestion`
- [ ] 建议必须引用有效 `evidence_ids`
- [ ] Agent 只能创建 `PENDING` 建议
- [ ] 支持接受建议
- [ ] 支持编辑后接受
- [ ] 支持拒绝建议
- [ ] 保存审批状态和 `final_text`
- [ ] 前端展示原文、建议文本和 Diff
- [ ] 未接受内容不能成为最终文本
- [ ] 审批操作写入 `DomainEvent`

## C：轻量岗位发现

### M10 一个真实来源与岗位发现池

- [ ] 实现岗位 URL 安全检查
- [ ] 阻止本机、内网和云元数据地址
- [ ] 实现 Generic HTML 读取
- [ ] 实现页面结构化数据读取
- [ ] 限制重定向、响应大小、超时和重试
- [ ] 实现 `JobSourceAdapter` 接口
- [ ] 完成 1 个真实招聘来源 Adapter
- [ ] 使用固定 HTML Fixture 测试 Adapter
- [ ] 实现岗位标准化和内容指纹去重
- [ ] 实现用户手动触发发现
- [ ] 实现岗位发现页和基础筛选
- [ ] 用户选择岗位后可以进入完整分析

## D：评测与演示

### M11 评测、失败案例与演示

- [ ] 准备 30～50 条人工标注样本
- [ ] 实现字段级 Precision
- [ ] 实现字段级 Recall
- [ ] 实现 Macro-F1
- [ ] 实现资格分类准确率
- [ ] 实现误判符合率
- [ ] 实现 Evidence Precision
- [ ] 实现 Evidence Coverage
- [ ] 实现 Unsupported Claim Rate
- [ ] 实现 `AgentRun`
- [ ] 记录模型、提示词和数据集版本
- [ ] 增加 `unknown` 案例
- [ ] 增加无证据案例
- [ ] 增加网页读取失败案例
- [ ] 完成核心端到端测试
- [ ] 完成真实岗位发现到申请管理的演示
- [ ] 整理实际评测结果和项目截图

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
