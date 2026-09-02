# AI 校招岗位数据集（2026-08-31 快照）

本数据集面向 JD 解析、岗位检索和证据约束匹配评测，以 2027 届校招为主，覆盖 AI Agent、大模型、多模态、具身智能、机器人算法和 AI 基础设施等方向。

## 数据规模

- 原始记录：165 条
- 公司/品牌：25 家
- 公司官方来源：155 条
- 正文完整、可用于 Parser：161 条
- 严格评测集：154 条
- 仍需人工复核：7 条（均来自旧基线；104 条官方增量为 0）

## 可提交文件

- `ai_campus_job_catalog_2026_08_31.json`：165 条公开元数据总目录，不包含完整 JD 正文。
- `official_job_sources_2026_08_31.json`：编号 051-061 的 11 条官方来源增量。
- `official_job_sources_2027_expansion_2026_08_31.json`：编号 062-165 的 104 条官方校招及实习来源增量，以 2027 届为优先。
- `official_job_sources_full_2026_08_31_overrides.json`：合并后的人工字段覆盖。
- `ai_campus_label_overrides_v4_audit.json`：v4 部分人工审计增量，不覆盖 v3 原始覆盖文件。
- `AI_CAMPUS_LABEL_AUDIT_V4.md`：v4 标注规则、审计范围、重算结果和限制。

## 本地评测文件

完整 JD 和生成的 manifest 位于 Git 忽略的 `artifacts/evaluation/`：

- `m11-ai-campus-source-full-2026-08-31.json`：165 条完整本地 source。
- `m11-ai-campus-manifest-full-2026-08-31.json`：161 条 Parser 可用样本。
- `m11-ai-campus-manifest-full-strict-2026-08-31.json`：154 条严格评测样本。
- `m11-ai-campus-review-full-2026-08-31.json`：待复核项。
- `m11-ai-campus-manifest-full-v4-strict-2026-08-31.json`：叠加 v4 审计增量后的 154 条 provisional strict manifest。
- `m11-ai-campus-report-v4-audit-scope-2026-08-31.json`：仅统计本轮人工审计字段的报告。

## 质量口径

新增岗位只在官方详情页正文可读、且申请按钮可用时纳入。页面下线、申请关闭、仅有搜索摘要或无法读取完整职责要求的岗位不进入新增严格集。岗位状态具有时效性，实际申请前应重新访问 `source_url` 核验。

编号 151-165 新增智元机器人、阶跃星辰、月之暗面、生数科技和逐际动力 5 家公司，每家公司 3 条。阶跃星辰 3 条为明确的 2027 届岗位，月之暗面的 Agent 产品工程实习岗位明确写有“27 届及以后优先”；其余岗位为当前官方校园招聘或技术实习岗位，未将官网未披露的届次推断为 2027 届。

公开仓库仅分发岗位元数据、人工标签和来源链接；完整第三方招聘正文只用于本地评测。
