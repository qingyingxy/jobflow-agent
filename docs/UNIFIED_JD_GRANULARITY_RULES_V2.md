# Unified JD facts 与 clauses 粒度规则 v2

> 版本：`unified-jd-annotation-granularity-v2`  
> 基础 Schema：`unified-jd-v1`  
> 继承：`UNIFIED_JD_ANNOTATION_GUIDE_V1.md` 中未被本文替代的规则

## 完成状态

- [x] 文本 facts 的原子粒度已定义
- [x] facts 与 fact clauses 的对应关系已定义
- [x] dev-50 冻结 v1 已通过确定性迁移生成冻结 v2
- [x] Parser 与评测器使用同一粒度校验
- [ ] 使用固定 Parser/Prompt v2 生成新的 50 条正式预测

## 1. 总原则

`facts` 保存有类型、可复用的事实值；`category="fact"` clause 只补充该事实在
当前原文中的强度、逻辑关系和证据范围。两者不能分别使用“整句”和“拆分项”两种
粒度描述同一事实。

只要 `locations`、`education_requirements` 或 `major_requirements` 存在对应 fact
clause，这些 clauses 的全部 `items` 去重集合必须与 facts 数组完全一致，字符串也
必须原样复用。

## 2. 文本数组

- `locations`：一个城市或原文地域一个 item，例如 `["北京", "上海"]`。
- `education_requirements`：一个完整学历约束或一个明确备选层级一个 item。
- `major_requirements`：一个专业或一个开放范围标记一个 item。

示例：

```json
{
  "facts": {
    "major_requirements": ["计算机", "软件工程", "相关专业"]
  },
  "clause": {
    "category": "fact",
    "fact_field": "major_requirements",
    "level": "preferred",
    "relation": "any_of",
    "items": ["计算机", "软件工程", "相关专业"],
    "group_name": "专业范围",
    "allow_other": true,
    "source_text": "计算机、软件工程等相关专业优先"
  }
}
```

禁止把 facts 写成 `["计算机、软件工程等相关专业"]`，同时又把 clause items 拆成
三个值。`本科及以上` 是一个有下限的完整学历约束；`本科或硕士` 则拆为
`["本科", "硕士"]`，由 clause 的 `relation="any_of"` 表达任选。

## 3. 有类型 facts

以下字段保留其业务类型，不要求与字符串 clause items 字面相等：

- `graduation_years`：整数年份数组；
- `internship_duration_months`、`weekly_days`：整数；
- `earliest_start_date`、`deadline`：ISO 日期；
- `job_type`：固定枚举。

对应 fact clause 仍必须引用非空 fact，并准确表达强度。若 clause 需要保留比 typed
fact 更精确的范围，例如完整毕业日期窗口，可在 `items` 中保留该范围，不能为了字面
相等而丢失信息。

## 4. Clause 粒度

- 每个编号、项目符号或独立行至少单独形成一个 clause，不跨编号合并。
- 一条 clause 只能共享一个 `category + level + relation + qualifier`。
- `items` 是当前最小语义范围中的原子事项，不复制整段职责作为单个 item。
- 学历、专业 fact clause 必须直接复用对应 facts 原子字符串。
- `source_text` 必须是原文中不超过 240 字符的精确连续子字符串。

## 5. 版本与迁移

冻结 v2 只修改 `facts.education_requirements` 和 `facts.major_requirements` 的数组
粒度；新值来自同一岗位已经两轮人工复核的 fact clause items。原始岗位正文、证据、
clauses、强度和逻辑关系均保持不变，也不读取或复制任何模型 prediction。

构建器：`scripts/build_unified_dev50_granularity_v2.py`。
