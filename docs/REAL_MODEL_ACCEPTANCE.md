# 真实模型验收记录

## 配置

- 日期：2026-08-03
- Provider：OpenAI-compatible
- Base URL：`https://api.deepseek.com`
- Model：`deepseek-v4-flash`
- Parser Prompt：`jd-parser-prompt-v4`
- Parser Schema：`structured-job-description-v1`
- 分析版本：`job-analysis-v1`
- 数据库：SQLite

API Key 只保存在本地 `.env`，该文件已被 Git 忽略，不进入提交和普通日志。

## 三类中文 JD

| 类型 | 解析结果 | 资格 | 分数 | 匹配与校验 |
|---|---|---:|---:|---|
| AI/RAG 实习 | `internship`，北京，Python/RAG/向量检索 | `unknown` | 100 | 3 条技能证据 `supported`；项目经验无证据，安全返回 `unsupported`；全部 Validator `passed` |
| 校招后端 | `campus`，上海，Python/Web 后端框架/SQL | `unknown` | 75 | Python、SQL 有证据；Web 后端框架无直接证据；全部 Validator `passed` |
| 搜索算法 | `campus`，深圳，BM25/向量检索/rerank | `unknown` | 100 | 3 条检索技能证据 `supported`；检索项目经验无证据，安全返回 `unsupported`；全部 Validator `passed` |

三条结果的推荐状态均为 `needs_confirmation`。`unknown` 不是模型失败，而是当前 JD 或用户画像缺少学历、专业、最早到岗等确认信息，符合 Eligibility 的设计约定。

## 真实问题与修复

1. DeepSeek 不接受原客户端发送的 `json_schema` 响应格式。新增 `LLM_RESPONSE_FORMAT`，`auto` 对 DeepSeek 使用 `json_object`，其他兼容服务保留 `json_schema`。
2. JSON Object 模式缺少服务端 Schema 约束。Parser 和 Evidence Matcher Prompt 现在显式携带 JSON Schema，并要求原文证据必须是连续原文片段。
3. “校招全职”容易被模型归类为 `full_time`。Parser 增加确定性规则：出现校招、校园招聘或应届招聘时，`campus` 优先。
4. 旧 Validator 要求 `requirements` 或 `qualification_conditions` 容器重复提供顶层证据。现在允许每个子项的完整 `evidence` 作为容器证据，同时仍强制每个子项可追溯到岗位原文。
5. 首次搜索算法 JD 验收使用 60 秒超时发生一次超时；本地真实模型配置提升为 120 秒后重试成功。
6. Parser v4 要求技能按原子粒度输出，使用紧凑输出契约减少长 JD 请求上下文，并从任职要求原文补回明确遗漏的技能；模型请求对超时、连接异常和 429/5xx 增加有限重试。

## 回归结果

- `uv run ruff check src tests migrations`：通过
- `uv run pytest`：68 passed
- `uv run alembic check`：无新的迁移操作
- 前端 `npm run typecheck`：通过
- 前端 `npm run build`：通过

## 最新 Core Parser 冒烟验收

- 日期：2026-08-06
- Parser：`CoreJDParser`
- Parser Prompt：`jd-core-parser-prompt-v1`
- 数据集：3 条 AI 校招中文 JD（OPPO、AI 产品、Agent 评测方向）
- 结果：3 / 3 成功，无模型超时；字段 Macro-F1 `1.0000`，`prediction_failure_count=0`
- 输出：[`m11-ai-campus-smoke-predictions-core-v1.json`](../artifacts/evaluation/m11-ai-campus-smoke-predictions-core-v1.json)
- 报告：[`m11-ai-campus-smoke-report-core-v1.json`](../artifacts/evaluation/m11-ai-campus-smoke-report-core-v1.json)

这次验收只覆盖发现阶段的三个核心字段。完整 `JDParser` 仍保留给岗位详情和后续资格/证据分析；它要求模型一次生成更多嵌套字段，长 JD 的稳定性需要单独优化，不能用 Core Parser 的结果替代完整解析指标。

## 最新 Staged Parser 验收

- 日期：2026-08-06
- Parser：`StagedJDParser`（`CoreJDParser` + `DetailJDParser` + 本地组装）
- Parser Prompt：`jd-staged-parser-prompt-v1`
- 数据集：同一批 3 条 AI 校招中文 JD
- 结果：3 / 3 完成，无超时、无最终结构校验失败；字段 Macro-F1 `1.0000`
- 输出：[`m11-ai-campus-smoke-predictions-staged-v1.json`](../artifacts/evaluation/m11-ai-campus-smoke-predictions-staged-v1.json)
- 报告：[`m11-ai-campus-smoke-report-staged-v1.json`](../artifacts/evaluation/m11-ai-campus-smoke-report-staged-v1.json)

其中第 2、3 条 Detail 模型返回了 `requirements` 字典而不是列表，Parser 通过兼容归一化转换后继续完成解析。这说明模型输出仍需经过适配和最终领域校验，不能直接写入数据库。

## 39 条严格子集全量验收

- 日期：2026-08-09
- 数据集：39 条公开中文 AI 校招岗位严格子集
- Model：`deepseek-v4-flash`
- Core：39 / 39 成功，Macro-F1 `0.9890`，模型超时率 `0%`
- Staged：39 / 39 成功，Macro-F1 `0.9897`，模型超时率 `0%`
- 本地证据门控修复：接受“应届生”作为可引用的 campus 信号；模型猜测但正文和元数据均无依据的 `job_type` 降为 `null`
- 公开报告：[`evaluation/m11-ai-campus-39-summary.json`](evaluation/m11-ai-campus-39-summary.json)

该运行只评测 `job_type`、`locations`、`required_skills` 三个 Parser 字段。由于没有生成 Evidence Matcher 的 `supported / partial` claim，用户可见 Unsupported Claim Rate 不适用；不能据此宣称完整产品链路“零幻觉”。
