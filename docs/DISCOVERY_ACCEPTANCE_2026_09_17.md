# 岗位发现与分析闭环验收（2026-09-17）

本次完成范围：官方来源发现 → 正文核验与入库 → 真实模型解析 → 资格与经历匹配 → 保存候选 → 真实前后端展示。没有填写招聘表单、上传简历到招聘站或提交申请。

## 结果与证据

最终报告目录：`artifacts/acceptance/20260917T124055Z/`。

| 来源 | 查询 | 核验入库 | 真实模型分析 / 保存 | 重复发现 |
| --- | --- | ---: | ---: | --- |
| 字节跳动官方接口 | Python | 3 | 1 / 1 | 0 新增，3 重复 |
| 腾讯官方接口 | Python | 3 | 1 / 1 | 0 新增，3 重复 |
| Anthropic 官方 Greenhouse 招聘板 | Software Engineer | 3 | 1 / 1 | 0 新增，3 重复 |

三路发现与分析任务最终均为 `SUCCEEDED`，没有遗留运行中任务。使用真实模型 `gpt-5.6-terra`；运行时 Parser 为 `product-jd-parser-v4`，Prompt 为 `product-jd-two-stage-v7`。每家公司分析 1 条，合计 3 条；这不是大规模准确率评测。

- [机器可读报告](../artifacts/acceptance/20260917T124055Z/report.json)：查询、URL、正文、正文哈希、抓取时间、解析、资格、匹配、候选保存结果、发现/分析 trace、代码哈希。
- [模型运行记录](../artifacts/acceptance/20260917T124055Z/agent-runs.json)：从验收 SQLite 只读导出的模型执行、校验和耗时记录。
- [证据文件哈希清单](../artifacts/acceptance/20260917T124055Z/evidence-manifest.json)。
- [候选列表截图](../artifacts/acceptance/20260917T124055Z/saved-candidates.png)。
- [字节分析](../artifacts/acceptance/20260917T124055Z/bytedance-analysis.png)、[腾讯分析](../artifacts/acceptance/20260917T124055Z/tencent-analysis.png)、[Anthropic 分析](../artifacts/acceptance/20260917T124055Z/anthropic-analysis.png)。

验收使用独立 SQLite 和明确标记为 synthetic 的候选人资料（2027 届、计算机硕士、Python/RAG 项目），不是项目所有者的真实简历。修正规则后，三个岗位均为“信息不足”，没有为了验收成功强制制造推荐结果。岗位包含社招和类型待确认场景，不代表三家公司校招查询均已验收。

## 本次修复

1. 复杂届别保守判断。明确的简单年份列表才执行年份包含判断；国内/海外、毕业日期区间和其他无法可靠解释的限制返回 `unknown`。保留 `graduation_condition_kind` 与 `graduation_source_text`，前端展示原文及缺失信息。旧结构若保留了复杂届别原文，也不能继续误判 `pass`。
2. 贯穿验证。Product Parser → SQLite → Analysis API → Matcher 的 `any_of` 关系、候选项与证据保持一致；单项证据满足任选关系。另测学历不满足时总体可为 `fail`，但届别检查仍为 `unknown`，避免总体结果掩盖单项错误。
3. 搜索偏好与资格隔离。已有实现通过集成回归验证，城市/招聘类型偏好不进入硬资格结论。
4. 腾讯接口的 `Count=0, Posts=null` 是合法空结果，修复其导致整条发现链失败的问题；有岗位数量但无列表的异常仍报错。
5. Greenhouse 支持有界发现：先读不含正文的列表，再读取选定岗位详情。避免一次下载大公司全部 JD 超过响应大小限制；线上 Greenhouse 入口最多读取 20 个详情，验收设为 3。
6. 英文 `internal`、`international` 不再因包含 `intern` 而误判实习。
7. 英文 `or higher / at least / minimum` 按最低学历处理，硕士不再被“本科及以上”误拒；无法判定的 equivalent 备选路线保守返回待确认。
8. 本地匹配复用已有技能词表，复合条件中的已识别技能必须全部被证据覆盖，单独 Python 不再支撑 Python + React 或 SQL + Python 整句。

最后两项是在截图复核时发现并修复的。随后仅重放缓存解析，禁止新的模型调用；原始及中间报告保存在同目录 `report-before-local-rule-refresh*.json`。最终本地规则哈希记录在 `local_rule_sha256`，不覆盖最初网络验收时的代码哈希。模型运行导出同时包含原始执行和缓存命中记录，不能把缓存命中数量当成模型调用次数。

旧 `product_jd_parser.py` 保持历史冻结字节和 SHA-256；新入口在 `product_jd_runtime_parser.py` 中扩展。旧 100 条评测的 Parser/Prompt 版本及指标不改写、不冒充新版指标。分析版本同步升级，旧分析缓存不会作为新规则结果展示。

## 自动化验证

- 后端全量：`1123 passed`，有一条既有 Starlette/httpx 弃用警告。
- 本次涉及的 Python 文件通过 Ruff 检查；前端 `npm run typecheck` 通过。
- `npm run test:integration`：真实 FastAPI + 临时 SQLite + 浏览器；仅外部招聘来源和模型 HTTP 使用本地 fixture。验证发现、去重、点击开始匹配、复杂届别/任选关系、保存及刷新后持久化。没有 `page.route()` 拦截 JobFlow API。
- `npm run test:live-results`：读取本次真实验收库，逐家检查真实分析 API 与界面，保存四张截图；没有 API mock。截图关闭进场动画并回到页顶，已做视觉复核。

真实发现由验收脚本调用生产 DiscoveryService / 分析调度执行，浏览器负责查看已生成结果；这不等于对首页“公开网页搜索”另一条 provider 路由也做了真实浏览器搜索验收。原有旧版 mock 界面演示测试未作为本次真实验收依据。

## 复跑

在仓库根目录配置可用模型和网络代理后执行（会产生模型调用费用）：

```powershell
uv run python -m scripts.run_discovery_acceptance --sources bytedance tencent anthropic --query Python --source-query "anthropic=Software Engineer"
```

脚本每次创建新目录、新数据库；不会复用或清空日常数据库。记下输出的目录，然后在 `frontend` 下执行：

```powershell
$env:JOBFLOW_ACCEPTANCE_DIR = 'E:\code\jobflow-agent\artifacts\acceptance\20260917T124055Z'
npm run test:live-results
```

将上面的目录替换为新运行目录。浏览器检查使用 3001 / 18021 端口；本地 fixture E2E 另用 18022 端口。结束后测试服务自动停止。

回到根目录导出模型记录与证据哈希：

```powershell
uv run python -m scripts.export_acceptance_evidence artifacts/acceptance/20260917T124055Z
```

离线前后端集成验证：在 `frontend` 下运行 `npm run test:integration`。外部 fixture 仅存在于测试启动器，不改变生产 API 的行为。

## 验收边界

初次尝试失败的报告保留在 `artifacts/acceptance/20260917T121649Z/report.json`：腾讯空结果格式与 Greenhouse 响应过大均如实记录，未把失败计为成功。中间运行目录用于排障，最终结论以本文指定目录为准。

复杂届别分类采用保守规则，不是通用资格条件求解器；本地经历匹配仍是启发式证据匹配，多技能复合句的完整满足程度还需进一步评测。本次成功证明当时的有限来源能跑通及结果可追溯，不证明长期站点兼容、解析/推荐完全正确、真实 ATS 投递成功或新版 100 条 JD 指标提升。
