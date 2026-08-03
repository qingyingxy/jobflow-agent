# 真实模型验收记录

## 配置

- 日期：2026-08-03
- Provider：OpenAI-compatible
- Base URL：`https://api.deepseek.com`
- Model：`deepseek-v4-flash`
- Parser Prompt：`jd-parser-prompt-v2`
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

## 回归结果

- `uv run ruff check src tests migrations`：通过
- `uv run pytest`：68 passed
- `uv run alembic check`：无新的迁移操作
- 前端 `npm run typecheck`：通过
- 前端 `npm run build`：通过
