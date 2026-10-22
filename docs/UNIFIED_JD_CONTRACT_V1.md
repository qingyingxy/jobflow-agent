# Unified JD Contract v1

> Schema 版本：`unified-jd-v1`  
> 状态：已冻结，尚未接入线上 Parser  
> 实现：`src/domain/unified_jd.py`  
> 编译器：`src/services/unified_jd_compiler.py`  
> Parser：`src/services/unified_jd_parser.py`

## 1. 设计目标

- [x] 每份 JD 正常只需要一次模型解析调用。
- [x] 模型顶层只输出 `facts` 和 `clauses`。
- [x] 公司、岗位名称和申请 URL 继续来自已验证网页，不由模型生成。
- [x] 模型负责原文语义分类，本地代码负责规范化、校验和兼容字段编译。
- [x] `required_skills` 等兼容字段不是第二份事实源，可以随时从 clauses 重建。
- [x] 每个非空事实和每条 clause 都必须引用 JD 中的连续原文。

## 2. 顶层结构

```json
{
  "facts": {},
  "clauses": []
}
```

- [x] 不允许第三个顶层字段。
- [x] 未提及的事实使用 `null`，不使用猜测值、`unknown` 或空列表。
- [x] `clauses` 没有内容时使用空列表。
- [x] 未知字段由 Pydantic `extra="forbid"` 拒绝。

## 3. Facts

`facts` 固定包含 9 个业务事实字段和一个随附的 `evidence` 列表：

| 字段 | 类型 | 含义 |
|---|---|---|
| `job_type` | enum / null | `campus / internship / full_time / part_time` |
| `locations` | string[] / null | 岗位工作地点 |
| `graduation_years` | int[] / null | 明确接受的毕业届别 |
| `education_requirements` | string[] / null | 原文中的学历条件 |
| `major_requirements` | string[] / null | 原文中的专业条件 |
| `internship_duration_months` | int / null | 最低连续实习月数 |
| `weekly_days` | int / null | 每周最低到岗天数 |
| `earliest_start_date` | ISO date / null | JD 要求的最早到岗日期 |
| `deadline` | ISO date / null | 明确的申请截止日期 |

实习安排采用“解析并展示，但不自动判断”的产品规则：`internship_duration_months`、`weekly_days` 和 `earliest_start_date` 继续作为有证据的岗位事实参与 Parser 评测，但不进入简历自动匹配、申请建议档位或自动淘汰。远程限制、转正机会等未单列字段的信息保留在 JD 快照中展示，不为此扩展 facts 或再次调用模型。

### 3.1 Fact evidence

```json
{
  "field": "locations",
  "source_text": "工作地点：上海、深圳"
}
```

- [x] 每个非空事实至少有一条同字段证据。
- [x] 空事实不能携带证据。
- [x] 同一字段可以有多条证据。
- [x] `source_text` 必须能在当前 JD 快照中逐字定位。
- [x] 字符偏移由本地校验器计算，不要求模型预测。

## 4. Clauses

一条 clause 表示一个最小且共享相同语义强度、逻辑关系和经验限定的原文范围。

```json
{
  "category": "skill",
  "fact_field": null,
  "level": "required",
  "relation": "any_of",
  "items": ["Python", "Go"],
  "examples": null,
  "group_name": "编程语言",
  "allow_other": false,
  "qualifier": null,
  "source_text": "熟悉 Python 或 Go 中至少一种"
}
```

### 4.1 Category

- [x] `skill`：具名技术、工具、框架、模型或算法。
- [x] `capability`：可由候选人证明的技术能力。
- [x] `experience`：项目、研发、行业或工作经历要求。
- [x] `responsibility`：职责中值得在申请材料突出、但不是资格门槛的事项。
- [x] `fact`：表达某个 facts 字段是必须、优先还是仅提及；必须同时提供 `fact_field`。
- [x] 非 fact clause 不得提供 `fact_field`。

### 4.2 Level

- [x] `required`：原文明示必须、掌握、熟悉、具备、能够等硬要求。
- [x] `preferred`：原文明示优先、加分、具备更佳等软条件。
- [x] `mention`：职责或上下文提及，不能提升为资格要求。

例如“计算机相关专业优先”：

- `facts.major_requirements` 保存原文事实 `计算机相关专业`；
- clause 使用 `category=fact`、`fact_field=major_requirements` 和 `level=preferred`；
- 本地资格判断不能把它当成硬性专业门槛。

### 4.3 Relation 与开放组

- [x] `all_of` 表示本条中的所有事项同时成立。
- [x] `any_of` 表示候选项满足任意一个即可。
- [x] `any_of` 至少包含两个候选项，并且必须提供 `group_name`。
- [x] `allow_other=true` 只用于“等、其他、包括但不限于”等开放列表。
- [x] `group_name` 和 `allow_other` 不能用于 `all_of`。
- [x] required、preferred 和 mention 均可保留原文中的 any_of 语义。

### 4.4 Examples

- [x] `examples` 只解释 items，不自动继承 required 或 preferred 强度。
- [x] 本地兼容编译时，examples 进入 `skill_mentions`。
- [x] “至少一种框架，例如 PyTorch、TensorFlow”如果具体框架就是候选项，应直接建为开放 any_of，而不是 examples。

### 4.5 Experience qualifier

`qualifier` 只保存原文明示的经验范围：

- `project`
- `internship`
- `research`
- `development`
- `practical`
- `open_source`
- `employment`
- `industry`

可同时保存 `minimum_months` 和 `domain`。限定只作用于当前 clause，不得传播到其他条款。

## 5. 本地四字段编译

本地编译器固定输出：

1. `required_skills`
2. `required_skill_groups`
3. `preferred_skills`
4. `skill_mentions`

编译规则：

- [x] required + all_of -> `required_skills`。
- [x] required + any_of -> `required_skill_groups`，候选项不进入 `required_skills`。
- [x] preferred -> `preferred_skills`；兼容视图可以展平 preferred any_of，但 clauses 保留真实逻辑。
- [x] mention -> `skill_mentions`。
- [x] examples -> `skill_mentions`。
- [x] fact clause 不进入技能字段。
- [x] 同一技能同时出现时遵循 required > required group option > preferred > mention 的显示优先级。
- [x] 编译器不改变 clause 的 level，也不从关键词重新判断强度。

## 6. 完整示例

```json
{
  "facts": {
    "job_type": "internship",
    "locations": ["上海"],
    "graduation_years": [2027],
    "education_requirements": ["本科及以上"],
    "major_requirements": ["计算机相关专业"],
    "internship_duration_months": 3,
    "weekly_days": 4,
    "earliest_start_date": null,
    "deadline": "2026-09-30",
    "evidence": [
      {"field": "job_type", "source_text": "算法实习生"},
      {"field": "locations", "source_text": "工作地点：上海"},
      {"field": "graduation_years", "source_text": "面向2027届毕业生"},
      {"field": "education_requirements", "source_text": "本科及以上学历"},
      {"field": "major_requirements", "source_text": "计算机相关专业优先"},
      {"field": "internship_duration_months", "source_text": "连续实习至少3个月"},
      {"field": "weekly_days", "source_text": "每周到岗4天"},
      {"field": "deadline", "source_text": "申请截止日期：2026年9月30日"}
    ]
  },
  "clauses": [
    {
      "category": "skill",
      "level": "required",
      "relation": "any_of",
      "items": ["Python", "Go"],
      "group_name": "编程语言",
      "allow_other": false,
      "source_text": "熟悉 Python 或 Go 中至少一种"
    },
    {
      "category": "skill",
      "level": "preferred",
      "items": ["PyTorch"],
      "source_text": "熟悉 PyTorch 者优先"
    },
    {
      "category": "fact",
      "fact_field": "major_requirements",
      "level": "preferred",
      "items": ["计算机相关专业"],
      "source_text": "计算机相关专业优先"
    },
    {
      "category": "responsibility",
      "level": "mention",
      "items": ["RAG", "向量检索"],
      "source_text": "负责 RAG 与向量检索研发"
    }
  ]
}
```

JSON 中使用默认值的字段可以省略，例如普通 all_of clause 可以省略 `relation`，关闭的开放组可以省略 `allow_other`。

## 7. 新旧结构迁移方案

### 7.1 阶段 1 不修改数据库

- [x] `job_parse_results.structured_jd` 已经是 JSON，并且记录 `schema_version`、`parser_version` 和 `prompt_version`。
- [x] 当前阶段只新增独立契约和编译器，不需要 Alembic 迁移。
- [x] 旧解析结果保持原样，不进行破坏性批量改写。

### 7.2 接入期双读

- [ ] 新 Parser 使用 `schema_version=unified-jd-v1` 写入新的解析结果行。
- [ ] API 根据 schema_version 选择 Unified 或 legacy 读取适配器。
- [ ] Unified 适配器从 JobPosting 读取 company、title 和 application_url，从 facts 读取 9 个事实，从 clauses 编译四个技能字段。
- [ ] facts 的兼容适配必须读取对应 fact clause level；preferred 条件不能进入旧的硬性资格判断。
- [ ] 用户纠错作为单独覆盖层保存，不能修改原始 structured_jd。

### 7.3 切换与回滚

- [ ] Unified 未通过 `sealed-blind-30` 前，线上仍使用当前稳定 Parser。
- [ ] 验收期允许显式选择新旧 Parser 做离线对照，但同一次用户分析不能静默混用。
- [ ] Unified 达标后，线上新解析只走 Unified；旧 Parser 仅保留离线复现入口。
- [ ] Unified 失败时按本地修复和最多一次重试处理，不在线回退到旧多阶段 Parser。
- [ ] 回滚只通过明确版本发布完成，不在单个请求内静默切换 Schema。

## 8. 已冻结的相邻契约

- [x] 首次设置：目标方向、1～3 个城市、接受远程、毕业年份、求职类型。
- [x] 实习安排只展示：实习月份、每周天数、最早到岗日、远程限制和转正机会不参与简历自动资格判断。
- [x] 简历证据：经历类型、名称、组织、时间、原文、技能、页码或字符位置、来源类型。
- [x] 申请建议：`recommended_application / consider / not_recommended / insufficient_information`。
- [x] 看板状态：`to_decide / planned / applied / interviewing / closed`。
- [x] 结束结果：`skipped / job_closed / rejected / withdrawn / offered`。

## 9. 阶段 1 验收

- [x] Pydantic Schema 已实现。
- [x] 本地四字段编译器已实现。
- [x] required、preferred、mention、any_of、开放组和证据约束已有单元测试。
- [x] 简历证据、首次设置、申请建议和看板枚举已实现为独立领域契约。
- [x] 当前运行路径没有切换，v39 实验代码没有被覆盖。
- [x] 已实现真实模型 Prompt、结构化调用、本地证据校验和最多一次定向修复。
- [x] Schema 合法但事实为 null 时不会触发重试。
- [x] 模型连接或超时错误不会错误地进入 Schema 修复流程。
- [x] 建立独立 Unified 评测模型、指标和离线运行器。
- [x] 冻结 `dev-50` 与 `sealed-blind-30` 样本 ID，并生成待人工标注的开发集骨架。
- [ ] 完成 `dev-50` 人工标注；当前不得把待标注骨架当作评测成绩。
