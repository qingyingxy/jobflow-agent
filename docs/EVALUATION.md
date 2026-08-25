# 可重复评测与失败案例

项目评测分为两个独立层次。M11 使用 12 条合成 Fixture 验证评测器边界，并使用 39 条公开中文 AI 校招岗位严格子集评测 Core / Staged Parser 的字段抽取；M12 使用 13 个离线确定性场景回归 Discovery Agent 的来源授权、工具路由、回退、轨迹、人工接管、预算与状态一致性。公开报告只包含聚合指标，不提交岗位原文、模型 prediction、本地 AgentRun 或密钥。

## 1. 数据文件

| 文件 | 作用 |
|---|---|
| `datasets/m11_evaluation_manifest.json` | 版本化的 dev manifest、样本、标签和阈值 |
| `datasets/m11_sample_predictions.json` | 用于验证评测器的固定预测夹具，包含故意注入的错误 |
| `src/evaluation/models.py` | manifest 和 prediction 的 Pydantic 契约 |
| `src/evaluation/metrics.py` | Validator 边界、指标计算和阈值判断 |
| `src/evaluation/run.py` | 可重复运行的命令行入口 |
| `src/evaluation/agent_runs.py` | 从已有 AgentRun 表生成不含正文的汇总 |
| `src/evaluation/predict.py` | 复用现有 Parser、Eligibility 和 Evidence Matcher 生成 prediction |
| `src/evaluation/prepare_manifest.py` | 从人工复核 manifest 生成排除待复核样本和不可见元数据字段的 strict 子集 |
| `datasets/m11_evaluation_evidence.template.json` | 合成开发集的证据上下文模板 |
| `datasets/m11_evaluation_profile.template.json` | 合成开发集的用户画像和偏好模板 |

当前 dev manifest 有 12 个合成或固定 Fixture 案例，覆盖正常、字段缺失、`unknown`、无证据、多值字段、读取失败和非法模型输出。真实 Parser 报告使用单独冻结的 39 条 `split=eval` 严格子集；标签由规则草稿和人工覆盖生成，并排除了仍需复核或只能从外部元数据确认的案例。若将结果用于论文式公开比较，仍需独立人工复核并报告标注一致性。

## 2. 标注和匹配规则

- `source` 必须记录来源类型、引用位置和授权边界。当前 dev 集只使用项目自有合成文本和固定 Fixture。
- `expected.fields` 中缺少某个字段键表示该字段未标注，不计入该字段指标；显式 `null` 表示“已标注为缺失”。
- `expected.skill_mentions` 保存原文中更细的技术词，只用于追溯和人工检查；主指标只比较 `expected.fields.required_skills`，避免不同样本因为标签粒度不同而产生不公平扣分。
- 字符串先做 Unicode NFKC、去首尾空格、大小写折叠和连续空白归一化；列表字段按集合计算，不按顺序计算。
- 字段 Precision、Recall 和 F1 使用元素级 TP/FP/FN；Macro-F1 只平均有定义的字段 F1。
- 字段 `exact_match_accuracy` 统计一个案例中该字段集合是否整体完全一致；多值字段仍不按顺序比较。
- 资格准确率只统计 `expected.eligibility` 非空的案例；误接受率是“真实 `fail` 却预测为 `pass`”的比例。
- Evidence Precision 统计预测的证据 ID 中有多少属于该要求的标注集合；Evidence Coverage 统计标注证据被覆盖的比例。
- `supported` 和 `partial` 必须引用当前案例候选证据；无效 ID 会被 Validator 删除，失去有效证据的结论降级为 `unsupported`。
- Unsupported Claim Rate 只统计模型声称有支持的结论；没有任何声称时分母为零，按 0 处理。其他指标分母为零时返回 `null`，并在报告中标记为 undefined，不伪造 0 分。

报告同时保存 `raw` 和 `validated` 两组结果。前者用于观察模型原始输出，后者代表用户最终可见的证据边界结果；发布要求是 validated 的 Unsupported Claim Rate 为 0。

## 3. 运行开发集

```text
uv run python -m src.evaluation.run `
  --manifest datasets/m11_evaluation_manifest.json `
  --predictions datasets/m11_sample_predictions.json `
  --output artifacts/evaluation/m11-dev-report.json `
  --model sample-fixture `
  --prompt-version m11-dev-v1
```

命令会校验输入 JSON，输出阈值结果和机器可读报告。`artifacts/` 是本地生成目录，不提交到版本库。固定预测夹具故意包含一个资格误接受和非法证据引用，因此报告出现未通过阈值是预期的；它证明评测器和 Validator 能发现问题，不代表真实模型验收失败。

## 4. 生成真实模型 prediction

`predict.py` 不写入岗位、申请或用户数据库。它读取 manifest 中的岗位原文，复用产品正在使用的 Parser、Eligibility Checker 和 Evidence Matcher，然后只输出 prediction JSON。岗位解析有三种模式：`staged`（默认）使用 Core + Detail 两个小请求并在本地组装完整 JD；`core` 只输出发现页和字段评测需要的三个字段；`full` 保留旧的一次性完整输出路径，主要用于对照实验。先复制两个合成模板作为本地上下文文件；最终评测时需要你用自己的真实经历证据和搜索偏好替换它们，这两个本地文件已加入 `.gitignore`。

```text
Copy-Item datasets/m11_evaluation_evidence.template.json datasets/m11_evaluation_evidence.json
Copy-Item datasets/m11_evaluation_profile.template.json datasets/m11_evaluation_profile.json
uv run python -m src.evaluation.predict --manifest datasets/m11_evaluation_manifest.json --evidence datasets/m11_evaluation_evidence.json --profile datasets/m11_evaluation_profile.json --output artifacts/evaluation/m11-dev-generated-predictions.json --parser-mode staged --user-id evaluation-user
uv run python -m src.evaluation.run --manifest datasets/m11_evaluation_manifest.json --predictions artifacts/evaluation/m11-dev-generated-predictions.json --output artifacts/evaluation/m11-dev-generated-report.json --model deepseek-v4-flash --prompt-version jd-staged-parser-prompt-v1 --database-url sqlite:///./data/jobflow.db --user-id local-user
```

只验收字段抽取时，使用轻量 Core Parser，避免让模型一次生成完整的嵌套 JD：

```text
uv run python -m src.evaluation.predict --manifest artifacts/evaluation/m11-ai-campus-smoke-manifest-v3.json --output artifacts/evaluation/m11-ai-campus-smoke-predictions-core-v1.json --parser-only --parser-mode core --concurrency 1 --case-timeout 90 --checkpoint artifacts/evaluation/m11-ai-campus-smoke-predictions-core-v1.checkpoint.json
uv run python -m src.evaluation.run --manifest artifacts/evaluation/m11-ai-campus-smoke-manifest-v3.json --predictions artifacts/evaluation/m11-ai-campus-smoke-predictions-core-v1.json --output artifacts/evaluation/m11-ai-campus-smoke-report-core-v1.json --model deepseek-v4-flash --prompt-version jd-core-parser-prompt-v1 --database-url sqlite:///./data/jobflow.db --user-id local-user
```

Core Parser 不是第二套岗位事实：它只负责分阶段解析的第一步；最终仍由 staged Parser 组装成一套完整 `StructuredJobDescription`。

如果岗位原文或经历证据包含个人隐私，不能直接提交到 Git。真实评测前必须由你确认来源授权、证据内容和是否允许作为项目材料；模型生成 prediction 可以自动完成，正确标签仍需要人工审核。

## 5. 进一步人工验收

1. 补充人工标注岗位，并为每条样本记录原文来源、授权边界、标注说明和失败场景。
2. 保持 dev manifest 和阈值不变，另建 `split=eval` 的最终 manifest；冻结后再运行模型。
3. 保存模型、提示词、Validator、数据集版本、随机参数、运行时间和环境信息，并关联已有 `AgentRun`。
4. 运行同一条命令生成 raw/validated 报告，检查失败案例和用户可见 Unsupported Claim Rate。
5. 简历只写实际运行且带数据范围的指标；论文式或公开基准结论需等待独立人工复核。

## 6. AI 校招真实数据集的人工覆盖

AI 校招样本的规则草稿由 `src/evaluation/ai_campus_dataset.py` 生成；少量需要人工判断的字段放在 `datasets/m11_ai_campus_label_overrides.json`，不直接修改岗位原文。这样可以区分“页面原文”与“人工标签决定”，也能在重新抓取页面后重复生成 manifest。

```text
uv run python -m src.evaluation.ai_campus_dataset `
  --input artifacts/evaluation/m11-ai-campus-source-corrected-official.json `
  --manifest artifacts/evaluation/m11-ai-campus-eval-manifest-final-v1.json `
  --review artifacts/evaluation/m11-ai-campus-label-review-final-v1.json `
  --dataset-version m11-ai-campus-2026-08-05-final-v1 `
  --split eval `
  --overrides datasets/m11_ai_campus_label_overrides.json
```

最终生成的 46 条样本中，三个评测字段均有标注；`required_skills` 是统一后的匹配标签，页面中出现的 MCP、ReAct、KV Cache 等细粒度术语保存在 `expected.skill_mentions`，不伪装成另一套主指标。`review_required` 仍为 `true` 的 7 条不能直接用于最终指标：1 条官方页面未披露地点，6 条来自非官方转载。外部元数据只通过 `source_flags` 标记，不伪装成岗位正文。

严格评测子集使用下面的命令生成。当前版本包含 39 条样本；`job_type` 和 `locations` 中无法从正文确认的字段会被省略，不参与该字段指标，但仍保留在宽松 manifest 和 review 文件中。

```text
uv run python -m src.evaluation.prepare_manifest `
  --manifest artifacts/evaluation/m11-ai-campus-eval-manifest-final-v1.json `
  --review artifacts/evaluation/m11-ai-campus-label-review-final-v1.json `
  --output artifacts/evaluation/m11-ai-campus-eval-manifest-strict-v1.json `
  --review-output artifacts/evaluation/m11-ai-campus-label-review-strict-v1.json `
  --exclude-review-required `
  --exclude-metadata-only-fields
```

## 7. 2026-08-09 全量 Parser 结果

运行环境使用 OpenAI-compatible `deepseek-v4-flash`、温度 `0`。Core 与 Staged 都对同一份 39 条严格子集运行；Staged 是产品默认的 Core + Detail + 本地组装路径。

| 路径 | 成功率 | Macro-F1 | 超时率 | job_type F1 | locations F1 | required_skills F1 |
|---|---:|---:|---:|---:|---:|---:|
| Core | 100% (39/39) | 0.9890 | 0% (0/39) | 1.0000 | 1.0000 | 0.9671 |
| Staged | 100% (39/39) | 0.9897 | 0% (0/39) | 1.0000 | 1.0000 | 0.9691 |

`Unsupported Claim Rate` 在这次 parser-only 评测中的值为 `0`，但 `supported_claim_count=0`，因此用户可见幻觉率应报告为“不适用”，不能写成“0% 幻觉”。完整证据匹配链的幻觉指标必须在带候选证据和期望引用的评测集上单独报告。

机器可读的精简结果见 [`evaluation/m11-ai-campus-39-summary.json`](evaluation/m11-ai-campus-39-summary.json)。本地原始 prediction、checkpoint 和完整报告位于被 Git 忽略的 `artifacts/evaluation/`。

## 8. M12 Discovery Agent 控制面评测

M12 不调用真实官网，也不调用 LLM。评测通过内存 SQLite 和固定 HTTP/API Fixture 重放 13 个控制面场景，验证在外部页面不稳定时仍应保持不变的系统约束：

- 未登记公司和私有地址必须在网络访问前被拒绝；
- 字节、腾讯来源优先路由到专用 Adapter；
- 专用 Adapter 失败或返回空结果后，按计划回退静态读取；
- 单一来源失败不能中断其他来源；
- 动态页面壳和招聘指南不能被保存为岗位，并进入人工 JD 接管；
- 每次最多保留 20 条，仅严格匹配 Top5 自动分析；
- 拓展候选不占用自动分析预算；
- 重复发现不创建重复 `JobPosting` 或 `CandidateJob`；
- 每次执行轨迹均包含阶段、工具、结果、观察、决策和时间。

2026-08-09 的固定版本结果如下。百分比后保留了实际分子和分母，避免把少量回归样本包装成泛化能力：

| 指标 | 结果 |
|---|---:|
| 场景通过率 | 100% (13/13) |
| 来源越权访问率 | 0% (0/2) |
| Agent Trace 完整率 | 100% (11/11) |
| 工具路由准确率 | 100% (9/9) |
| Adapter 回退正确率 | 100% (3/3) |
| 非岗位误收率 | 0% (0/2) |
| 人工接管准确率 | 100% (2/2) |
| Top20 / Top5 预算合规率 | 100% (2/2) |
| 状态与幂等一致率 | 100% (1/1) |

复现命令：

```text
uv run python -m src.evaluation.discovery_agent `
  --manifest datasets/m12_discovery_agent_manifest.json `
  --output docs/evaluation/m12-discovery-agent-summary.json `
  --markdown docs/DISCOVERY_AGENT_EVALUATION.md
```

详细场景和限制见 [`DISCOVERY_AGENT_EVALUATION.md`](DISCOVERY_AGENT_EVALUATION.md)，机器可读报告见 [`evaluation/m12-discovery-agent-summary.json`](evaluation/m12-discovery-agent-summary.json)。这些结果只说明固定控制面回归场景通过，不代表真实官网召回率、真实网络稳定性或整个 Agent 的 100% 准确率。
