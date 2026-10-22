# Unified JD 人工标注规范 v1

> 版本：`unified-jd-annotation-guide-v1`  
> Schema：`unified-jd-v1`  
> 适用范围：`dev-50` 与 `sealed-blind-30` 的 `facts + clauses` 人工真值  
> 核心原则：只标注当前 `raw_content` 中逐字可证实的信息，不参考模型 prediction，
> 不把旧 Parser 的技能字段复制为新 Schema 真值。

## 1. 标注前检查

- [ ] 确认 URL 是公司官方具体岗位页，不是搜索摘要、列表页或第三方转载。
- [ ] 确认 `raw_content` 是同一个岗位的完整正文，包含职责和任职要求。
- [ ] 核对 `source_content_sha256`，标注期间不修改原始正文。
- [ ] 第一轮标注时不打开任何 Unified prediction。
- [ ] 原文不明确的信息保留为 `null`，不能用公司、岗位标题或常识补齐。

公司、岗位名称和申请 URL 是网页验证结果，不属于 Parser 输出，也不进入
`expected.facts`。

## 2. Facts 标注

九个 facts 必须全部出现；未提及使用 `null`，不能使用空字符串、空列表、
`unknown` 或推测值。

| 字段 | 标注规则 | 常见误区 |
|---|---|---|
| `job_type` | 只标正文明确表达的 `campus / internship / full_time / part_time` | “面向学生”不自动等于实习 |
| `locations` | 标岗位工作地点，去掉地址细节，保留城市或原文地域 | 公司总部所在地不能补为工作地点 |
| `graduation_years` | 只标明确届别或明确毕业年份 | 招聘页面年份不等于毕业年份 |
| `education_requirements` | 保留学历层级及必要限定，如“硕士及以上” | 不从岗位级别推测学历 |
| `major_requirements` | 保留原文明示专业范围 | 专业“优先”仍是 fact，但不是硬门槛 |
| `internship_duration_months` | 标最低连续实习月数 | “长期实习”不能猜成 3 个月 |
| `weekly_days` | 标每周最低到岗天数 | “尽快到岗”不产生天数 |
| `earliest_start_date` | 只标明确最早到岗日期 | 发布日期不是到岗日期 |
| `deadline` | 只标明确申请截止日期 | 页面更新时间不是截止日期 |

每个非空 fact 至少引用一段最短、连续、逐字一致的 `source_text`。同一证据可以
支持多个字段，但要分别建立对应 field 的 evidence。

## 3. Fact Clause

facts 保存“是什么”，fact clause 保存“它是必须、优先还是仅提及”。只要以下条件
带有资格强度，就同时建立 `category="fact"` 的 clause，并设置 `fact_field`：

- 岗位类型、地点、毕业年份、学历、专业；
- 实习月份、每周天数、最早到岗日、申请截止日。

示例：`计算机相关专业优先` 应标为：

```json
{
  "facts": {"major_requirements": ["计算机相关专业"]},
  "clause": {
    "category": "fact",
    "fact_field": "major_requirements",
    "level": "preferred",
    "items": ["计算机相关专业"],
    "source_text": "计算机相关专业优先"
  }
}
```

`每周可实习 4 天者优先` 同理：`weekly_days=4`，fact clause 的 level 是
`preferred`。它不能被本地资格判断当作硬性到岗条件。

标注层仍需忠实保留实习月份、每周到岗天数和最早到岗日期及其原文强度，用于 Parser 评测和页面展示；产品匹配层统一不把这些安排与简历比较，也不据此自动淘汰候选岗位。是否远程、是否可转正保留在完整 JD 快照中展示，不新增 fact。

## 4. Clause 切分

一条 clause 只允许共享同一个 `category + level + relation + qualifier`。原文中有
转折或强度变化时必须拆开。

- `skill`：具名语言、框架、工具、算法或技术概念。
- `capability`：可由经历证明的技术能力，如“模型部署能力”。
- `experience`：项目、实习、科研、研发、开源、工作或行业经验要求。
- `responsibility`：岗位职责中应该突出、但不是候选人资格门槛的事项。
- `fact`：九个 facts 的资格强度，必须设置 `fact_field`。

Level 规则：

- `required`：必须、要求、掌握、熟悉、具备、能够等明确资格条件。
- `preferred`：优先、加分、具备更佳、有则更好等软条件。
- `mention`：岗位职责、工作对象、示例或普通上下文提及。

“负责 RAG 系统研发”是 `responsibility + mention`，不能仅因技术名出现就升级为
`skill + required`。“有 RAG 项目经验者优先”是 `experience + preferred`。

## 5. 逻辑关系

- 普通并列默认使用 `all_of`。
- 只有原文明示“至少一种、任一种、任选其一、A 或 B”时使用 `any_of`。
- `any_of` 至少有两个 `items`，并填写便于查看的 `group_name`。
- 原文明示“等、其他、包括但不限于”且允许未列出的同类项时，才设置
  `allow_other=true`。
- `group_name` 只用于显示，不得改变候选项范围。

`熟悉 Python、SQL` 是 `all_of`；`熟悉 Python 或 Go 中至少一种` 是封闭
`any_of`；`至少掌握一种 Agent 框架，如 LangChain、AutoGen 等` 是开放
`any_of`。

`examples` 只保存上位概念的例子。例如“熟悉深度学习框架，如 PyTorch”中，
“深度学习框架”可作为 required item，`PyTorch` 是 example；若原文明确要求在
PyTorch/TensorFlow 中任选一种，两者应直接作为 any_of items。

## 6. Experience Qualifier

只有原文明示经验范围时才填写 qualifier：

`project / internship / research / development / practical / open_source /
employment / industry`

- `minimum_months` 只记录当前经验条款明确给出的最低月数。
- `domain` 只记录当前经验限定的领域。
- qualifier 不能从相邻条款或岗位职责传播过来。

## 7. 证据规则

- [ ] 每个非空 fact 至少有一条对应 evidence。
- [ ] 每条 clause 都有一段连续原文 `source_text`。
- [ ] 引文保持原始大小写、标点和空格，不做同义改写。
- [ ] 引文足以判断当前值、level 和 relation，不能只截取技能名。
- [ ] 不引用岗位标题来补正文没有表达的资格条件。
- [ ] 不把搜索摘要、旧标签或模型解释写入 evidence。

字符偏移由本地评测器计算，标注者不填写。Schema 能通过但证据无法逐字定位的结果，
仍算解析失败。

## 8. 复核与冻结

每个样本至少经过两轮：第一轮独立标注，第二轮重点复核强度、any_of、fact clause、
qualifier 和原文证据。

- [ ] `facts` 九个字段全部存在，空值确实未提及。
- [ ] “优先/加分”没有进入 required。
- [ ] 职责提及没有被升级为资格要求。
- [ ] any_of 没有被错误展开成多项全部必需。
- [ ] 开放组的 `allow_other` 有明确原文支持。
- [ ] mixed-strength 原文已拆成多个 clause。
- [ ] 所有引文均可在冻结正文中逐字定位。
- [ ] `coverage_tags` 已人工填写，用于确认数据集覆盖面。
- [ ] 争议已写入 `review_notes`，并由第二轮复核解决。
- [ ] 冻结前运行 Schema 和证据校验；冻结后只新建版本，不静默改标签。

推荐的人工 coverage tags 包括：`required`、`preferred`、`mention`、`any_of`、
`open_group`、`fact_preferred`、`experience_qualifier`、`fact_missing` 和
`mixed_strength`。这些 tag 只描述覆盖情况，不参与真值计算。

## 9. 指标口径与上线门槛

- Schema 合法率：原始 output 能被 `UnifiedJDModelOutput` 完整校验的 case 比例。
- 解析成功率：无 failure code、Schema 合法且所有证据均可定位的 case 比例。
- 9 facts Macro-F1：逐字段聚合集合 F1 后，对固定九个字段取平均。
- clauses 类型及逻辑关系 F1：按 category、fact field、level、relation、items、
  examples、allow_other 和 qualifier 的完整语义签名计算；`group_name` 和证据文本
  不参与该签名。
- 必须条件召回率：只对 `level=required` 的完整 clause 签名计算召回。
- required/preferred 混淆：items 等语义相同但两种 level 互换的数量。
- 无依据关键事实：非空 fact 没有任何可定位的同字段 evidence，或预测值超出人工
  source-backed 真值；这可以拦截“引用真实发布日期却声称是截止日期”等语义错配。
- 原文证据定位率：可定位的非空 fact 和 clause 结论数 / 全部非空结论数。

`sealed-blind-30` 的上线门槛固定为：Schema `100%`；成功解析至少 `29/30`；
facts Macro-F1 `>=0.90`；clauses F1 `>=0.88`；required recall `>=0.95`；
required/preferred 混淆 `<=1`；无依据关键事实 `=0`；证据定位率 `100%`。
任一项失败都不能切换线上 Parser。

## 10. 文件与离线运行

- 固定样本清单：`datasets/unified_jd_eval_split_v1_2026_09_03.json`
- 本地开发集骨架：
  `artifacts/evaluation/unified-jd-dev50-annotation-skeleton-v1-2026-09-03.json`
- 骨架生成器：`scripts/build_unified_dev50_skeleton.py`
- 离线评测入口：`src/evaluation/run_unified.py`

重新验证骨架可复现性：

```powershell
.\.venv\Scripts\python.exe -m scripts.build_unified_dev50_skeleton
```

人工标注完成后，将 manifest 与每条 case 的 `label_status / annotation_status`
先设为 `draft`。机器辅助的一稿只能使用这个状态，评测器会拒绝计算成绩。人工逐条
复核后才改为 `human_reviewed`，通过第二轮复核后再新建冻结版本并设为 `frozen`。
不要覆盖原始 pending 骨架。

prediction 文件只保存原始结构化 output，不先用 Pydantic 过滤；否则无法计算真实的
Schema 合法率。格式如下：

```json
{
  "prediction_version": "unified-jd-dev50-predictions-v1",
  "schema_version": "unified-jd-v1",
  "parser_version": "unified-jd-parser-v1",
  "prompt_version": "unified-jd-prompt-v1",
  "model": "configured-model",
  "predictions": [
    {
      "case_id": "campus-ai-001",
      "output": {"facts": {}, "clauses": []},
      "failure_code": null,
      "model_call_count": 1,
      "diagnostics": {}
    }
  ]
}
```

上例中的 `output.facts` 仅为缩写展示；真实 prediction 必须保留九个 fact 字段和
`evidence`，不能提交空对象。

生成 dev-50 正式 prediction 时使用一次调用版入口。它对每个尚未写入 checkpoint
的岗位只发起一次逻辑模型请求，不做 Parser 校验修复，并强制关闭客户端传输重试；
即使输出不合法也会原样保存，供 Schema 指标统计。中断后使用同一命令加
`--resume`，已完成 case 不会再次调用模型。

```powershell
.\.venv\Scripts\python.exe -m src.evaluation.predict_unified `
  --manifest artifacts/evaluation/unified-jd-dev50-frozen-v1-2026-09-04.json `
  --checkpoint artifacts/evaluation/unified-jd-dev50-predictions-v1.checkpoint.json `
  --output artifacts/evaluation/unified-jd-dev50-predictions-v1.json `
  --concurrency 1
```

该命令要求真实结构化模型配置；默认 `fake` provider 会被拒绝。完整 dev-50 在没有
checkpoint 的情况下固定为 50 次模型请求。不要使用普通 `UnifiedJDParser.parse`
批量生成正式基准，因为其默认允许一次校验修复，可能把单岗位调用数增加到 2。

运行确定性指标计算（该命令不会调用模型）：

```powershell
.\.venv\Scripts\python.exe -m src.evaluation.run_unified `
  --manifest artifacts/evaluation/unified-jd-dev50-frozen-v1-2026-09-04.json `
  --predictions artifacts/evaluation/unified-jd-dev50-predictions-v1.json `
  --output artifacts/evaluation/unified-jd-dev50-report-v1.json `
  --fail-on-gate
```

pending 骨架和 draft 标签都会被运行器明确拒绝。`--fail-on-gate` 在任一门槛失败时
返回退出码 2，便于后续接入 CI。
