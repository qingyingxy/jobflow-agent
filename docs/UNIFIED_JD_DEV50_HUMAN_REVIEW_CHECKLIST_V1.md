# Unified JD dev-50 人工复核清单 v1

- [x] 第一轮语义决策复核完成（含用户授权的无争议项自动确认）
- [x] 所有第一轮修改已写入新的 review candidate
- [x] 第二轮独立复核完成（50/50；18 个岗位共 24 处确定性修正；无待确认项）
- [x] 冻结版本及哈希已生成
- [x] dev-50 一次调用校准批次已完成并计算指标（50 次真实模型调用；未修复重调或传输重试）
- [x] facts 与 fact clauses 粒度规则 v2 已冻结（44/50 个岗位确定性迁移）
- [x] 使用固定的 Parser/Prompt v2 重新生成可比较的正式基线（50 次真实模型调用；未修复重调或传输重试）

> 草稿来源：`artifacts/evaluation/unified-jd-dev50-draft-v1-2026-09-03.json`  
> 草稿 SHA-256：`269b06f1ea88a76a055f4c2b448ebcd36dcdcdd064a6ae8b37e39bfc74868de3`  
> 第一轮 candidate：`artifacts/evaluation/unified-jd-dev50-review-candidate-v1-2026-09-04.json`  
> Candidate SHA-256：`333c4937f47e6ea5462e9407a005835e3b6398183b1ee239c69767b07e70b068`  
> 第二轮决策：`datasets/unified_jd_dev50_human_review_round2_decisions_v1_2026_09_04.json`  
> Human-reviewed 标签：`artifacts/evaluation/unified-jd-dev50-human-reviewed-v1-2026-09-04.json`  
> Human-reviewed SHA-256：`d3edc8b3dc448e499236987d61e322112ebca594a481320f28bd4ec61cc02b0f`  
> 冻结标签：`artifacts/evaluation/unified-jd-dev50-frozen-v1-2026-09-04.json`  
> 冻结 SHA-256：`d4d3959009825f4b36448434df0b01d5e0c73eae343df12aa2a62a6715d2cbe7`  
> 冻结凭据：`datasets/unified_jd_dev50_freeze_receipt_v1_2026_09_04.json`  
> 校准预测：`artifacts/evaluation/unified-jd-dev50-predictions-v1.json`  
> 预测 SHA-256：`ece7d9f9311288c416cf8fadaa0c9b6135bc4230e6d0c34c2385cab627c86aa1`  
> 校准报告：`artifacts/evaluation/unified-jd-dev50-report-v1.json`  
> 报告 SHA-256：`ffa14c4f7640a672a43ff8d456ff4a4c8479aab5405a56a2dbfb25a1fabf2bed`
> 粒度规则：`docs/UNIFIED_JD_GRANULARITY_RULES_V2.md`  
> 粒度统一标签：`artifacts/evaluation/unified-jd-dev50-frozen-v2-2026-09-04.json`  
> 粒度统一标签 SHA-256：`58d0e5928f20181d9dd6cf7e598f09b3a7e25b1fdde7a426ab2ff135902fdd43`  
> 粒度 v2 冻结凭据：`datasets/unified_jd_dev50_freeze_receipt_v2_2026_09_04.json`  
> 固定 v2 正式预测：`artifacts/evaluation/unified-jd-dev50-frozen-v2-predictions-v1.json`  
> 固定 v2 正式预测 SHA-256：`cc83ed140a1e8e440d51d2c3dcf1d5e7f2a378b6ce3580ca1bd510ca9c2da3dc`  
> 固定 v2 正式报告：`artifacts/evaluation/unified-jd-dev50-frozen-v2-report-v1.json`  
> 固定 v2 正式报告 SHA-256：`a74dd7a3fa261a64998ab418b575e9629671f1ba5e9bcfad0d8c2c4c088663a2`

第二轮已统一复核每个岗位的 facts、强度、逻辑组、经验限定和逐字证据。下方逐案复选框是第一轮过程底稿，保留用于追溯；当前完成状态以上方四项、第二轮决策文件和冻结凭据为准。所有版本均为新增文件，未覆盖原 draft 或第一轮 candidate。

## 一次调用校准结果（已完成）

- [x] `deepseek-v4-flash` 对 50 个冻结岗位各调用一次，共 50 次模型调用
- [x] `validation_repairs=0`、`transport_retries=0`，每条完成后写入 checkpoint
- [x] 50 条全部生成原始预测；30 条解析成功，20 条保留原始失败结果
- [x] Schema 合法率 `0.6200`，解析成功率 `0.6000`
- [x] facts Macro-F1 `0.6743`，clauses F1 `0.1096`，required recall `0.1650`
- [x] required/preferred 混淆 `1`，无依据关键事实 `46`，证据定位率 `0.9912`
- [x] 总用量 `151216` tokens（prompt `65625`，completion `85591`），累计请求耗时约 `392.53s`
- [x] 后 29 条使用最终约束提示词并连续通过 Schema 与证据校验（`29/29`）
- [x] 后 29 条诊断指标：facts Macro-F1 `0.7998`、clauses F1 `0.1418`、required recall `0.2487`
- [x] 校准门槛未通过；主要剩余问题是 facts/clauses 与人工标签的语义粒度不一致，不只是 JSON 格式

本批次执行过程中依据首个失败逐步收紧提示词，因此文件级 `prompt_version=unified-jd-prompt-v1` 包含多个校准修订，不应作为固定提示词的正式可比基线。最终提示词已升为 `unified-jd-prompt-v2`；在获得新增调用授权前，不重跑已完成岗位。

## 固定 v2 正式基线（已完成）

- [x] 固定 `unified-jd-parser-v2`、`unified-jd-prompt-v2` 和 `deepseek-v4-flash`，运行期间未修改 Parser、Prompt 或标签
- [x] 对粒度统一后的冻结 v2 共执行 `50` 次新模型调用；`validation_repairs=0`、`transport_retries=0`
- [x] 50 条均有预测记录：成功 `22` 条、`unified_output_invalid` `27` 条、`model_timeout` `1` 条
- [x] Schema 合法率 `0.4600`，解析成功率 `0.4400`
- [x] facts Macro-F1 `0.6703`，clauses F1 `0.0915`，required recall `0.1262`
- [x] required/preferred 混淆 `0`，无依据关键事实 `12`，证据定位率 `0.9948`
- [x] 总用量 `161906` tokens（prompt `79271`，completion `82635`），累计请求耗时约 `572.95s`
- [x] 结构校验共发现 `31` 处错误：字符串类型错误 `24`、非法 `any_of` `4`、非法 `experience_type` `3`
- [x] 正式门槛未通过；当前首要结构问题是模型未稳定遵守 `clauses[].items` 的字符串元素类型（典型情况是将毕业年份输出为整数），其次是 clause 语义召回，而不是继续调整冻结标签

本次结果是固定 v2 的首个可比较正式基线。失败项保留原始响应且未重跑；离线评测没有调用模型，也没有修改预测。

## facts 与 clauses 粒度统一（已完成）

- [x] `education_requirements` 改为一个完整学历约束或一个备选层级一个 item
- [x] `major_requirements` 改为一个专业或开放范围标记一个 item
- [x] 对应 fact clauses 必须复用与 facts 完全相同的原子字符串集合
- [x] 学历调整 `5` 个岗位，专业调整 `43` 个岗位，合计影响 `44/50` 个岗位
- [x] 原始 JD、source hash、evidence、clauses、level、relation 和 qualifier 均未修改
- [x] 旧模型的 30 条原始合法输出中有 13 条违反新粒度约束，已由离线评测器明确报告
- [x] v1 冻结标签保持原哈希，v2 使用新文件和新冻结凭据

## 第二轮结果（已完成）

- [x] 50 个 case 均被 `reviewed_case_ids` 唯一覆盖
- [x] 原文明确“或”的逻辑组已复核，错误的 `all_of` 已修正
- [x] required / preferred / mention 作用域已复核
- [x] 开放组、上位类别与 examples 已复核
- [x] experience qualifier 已复核
- [x] facts 与 clauses 的逐字证据均可定位
- [x] 岗位标题不再作为 fact 证据；可用招聘项目原文的 5 条已改绑
- [x] `campus-ai-068` 的“2027校招”未被推断为毕业届别，`graduation_years` 已置空
- [x] 无需项目负责人再次裁决的争议项
- [x] 完整测试和代码检查通过
- [x] 一次调用版预测生成器已就绪；禁用校验修复和传输重试，支持逐条 checkpoint

## 第一轮逐案记录（历史）

## 高优先级：已知争议（12）

### [ ] `campus-ai-001` OPPO - 算法工程师（大模型/智能体方向）

- 官方岗位：[打开原文](https://careers.oppo.com/university/oppo/campus/post/1799)
- 非空 facts：`job_type, locations, graduation_years, education_requirements, major_requirements`
- clauses：`required=9`、`preferred=2`、`mention=3`
- 已知问题：需人工确认‘相关专业’是否足以令专业 any_of 使用 allow_other=true。
- [ ] 九个 facts 的值、空值和事实强度正确
- [ ] required / preferred / mention 没有混淆
- [ ] all_of / any_of / allow_other 的作用域正确
- [ ] experience qualifier 没有错误传播或丢失
- [ ] 每段 source_text 连续、逐字一致且足以支持结论
- 争议决策：[x] 保持专业开放 `any_of`，`allow_other=true`
- 复核结论：`争议已确认；完整复核未完成`
- 修改或讨论说明：用户于 2026-09-03 明确回复“同意”。

### [ ] `campus-ai-008` OPPO - 机器学习研究员（健康方向）

- 官方岗位：[打开原文](https://careers.oppo.com/university/oppo/campus/post/1615)
- 非空 facts：`locations, education_requirements, major_requirements`
- clauses：`required=7`、`preferred=4`、`mention=7`
- 已知问题：方向经验包含分支内条件，当前 Schema 只能用上位 any_of 加 branch mention 表达，需人工确认。
- [ ] 九个 facts 的值、空值和事实强度正确
- [ ] required / preferred / mention 没有混淆
- [ ] all_of / any_of / allow_other 的作用域正确
- [ ] experience qualifier 没有错误传播或丢失
- [ ] 每段 source_text 连续、逐字一致且足以支持结论
- 争议决策：[x] 保留顶层方向 `any_of`，分支细节维持 mention，并补回论文或竞赛成果
- 复核结论：`修改；完整复核未完成`
- 修改或讨论说明：用户于 2026-09-03 明确回复“同意”；自动匹配该嵌套条件时返回“待确认”。

### [ ] `campus-ai-029` 字节跳动 - Agent开发工程师 - Coze

- 官方岗位：[打开原文](https://jobs.bytedance.com/campus/position/7667160543863343365/detail)
- 非空 facts：`job_type, locations, graduation_years, education_requirements, major_requirements`
- clauses：`required=7`、`preferred=1`、`mention=3`
- 已知问题：Python/Golang 使用斜杠且名词为单数，暂按封闭 any_of；需人工确认是否要求二者都掌握。
- [ ] 九个 facts 的值、空值和事实强度正确
- [ ] required / preferred / mention 没有混淆
- [ ] all_of / any_of / allow_other 的作用域正确
- [ ] experience qualifier 没有错误传播或丢失
- [ ] 每段 source_text 连续、逐字一致且足以支持结论
- 争议决策：[x] Python / Golang 保持封闭 `required any_of`
- 复核结论：`争议已确认；完整复核未完成`
- 修改或讨论说明：用户于 2026-09-03 明确回复“同意”。

### [ ] `campus-ai-128` 它石智航 - 2027校招-机器人力学仿真工程师

- 官方岗位：[打开原文](https://tarsrobot.jobs.feishu.cn/021343/position/7668524839929628966/detail)
- 非空 facts：`job_type, locations, graduation_years, education_requirements, major_requirements`
- clauses：`required=4`、`preferred=3`、`mention=4`
- 已知问题：Python/MATLAB 与数据处理/仿真自动化形成交叉选择，当前用两个复合 items 近似表达。
- [ ] 九个 facts 的值、空值和事实强度正确
- [ ] required / preferred / mention 没有混淆
- [ ] all_of / any_of / allow_other 的作用域正确
- [ ] experience qualifier 没有错误传播或丢失
- [ ] 每段 source_text 连续、逐字一致且足以支持结论
- 争议决策：[x] 保留 Python/MATLAB 与两类用途的开放复合 `preferred any_of`
- 复核结论：`争议已确认；完整复核未完成`
- 修改或讨论说明：用户于 2026-09-03 明确回复“同意”；不扩展嵌套逻辑 Schema。

### [ ] `campus-ai-142` 蔚来 - 校招-AI安全工程师

- 官方岗位：[打开原文](https://nio.jobs.feishu.cn/campus/position/7673026997753661742/detail)
- 当前来源状态：`已下线`（2026-09-03 官网明确显示“该职位已下线”）
- 实时使用策略：保留历史 JD 用于离线 Parser 评测，不进入可申请岗位池
- 来源状态处理：[x] 用户确认标记为已下线
- 非空 facts：`job_type, locations, graduation_years, education_requirements, major_requirements`
- clauses：`required=6`、`preferred=3`、`mention=7`
- 已知问题：页面元数据写硕士及以上，职位要求写本科及以上，二者冲突；草稿保留两条事实和两条 required clause，必须人工裁决。
- [ ] 九个 facts 的值、空值和事实强度正确
- [ ] required / preferred / mention 没有混淆
- [ ] all_of / any_of / allow_other 的作用域正确
- [ ] experience qualifier 没有错误传播或丢失
- [ ] 每段 source_text 连续、逐字一致且足以支持结论
- 争议决策：[x] 以正文“2027届本科及以上”为准，删除页头“硕士及以上”的 fact、证据和 clause
- 复核结论：`修改；完整复核未完成`
- 修改或讨论说明：用户于 2026-09-04 明确回复“同意”；本科及以上均符合；岗位已下线，仅用于离线 Parser 评测。

### [ ] `campus-ai-160` 生数科技 - 流式视频Agent实习生

- 官方岗位：[打开原文](https://shengshu.jobs.feishu.cn/index/position/7670063623927515455/detail)
- 非空 facts：`job_type, locations, major_requirements, internship_duration_months, weekly_days`
- clauses：`required=8`、`preferred=1`、`mention=6`
- 已知问题：不支持远程不在九 facts 中；保留在原文但当前契约无法结构化，需产品层另行决定。
- [ ] 九个 facts 的值、空值和事实强度正确
- [ ] required / preferred / mention 没有混淆
- [ ] all_of / any_of / allow_other 的作用域正确
- [ ] experience qualifier 没有错误传播或丢失
- [ ] 每段 source_text 连续、逐字一致且足以支持结论
- 争议决策：[x] 整句实习安排只展示，不进入简历自动匹配；不为“不支持远程”增加 fact 或 required 匹配 clause
- 复核结论：`保持；完整复核未完成`
- 修改或讨论说明：2026-09-04 用户确认全局实习安排规则，取代 2026-09-03 的现场到岗硬门槛决定；Parser 标签仍保留原文中的 required 强度。

### [ ] `campus-ai-051` 阿里巴巴 - AI Agent研发工程师

- 官方岗位：[打开原文](https://campus-talent.alibaba.com/campus/position/199907620027)
- 非空 facts：`job_type, locations, graduation_years, education_requirements, major_requirements`
- clauses：`required=5`、`preferred=2`、`mention=4`
- 已知问题：毕业日期窗口跨 2026 和 2027，graduation_years 保留两个年份；Java/Python 的斜杠语义需人工确认。
- [ ] 九个 facts 的值、空值和事实强度正确
- [ ] required / preferred / mention 没有混淆
- [ ] all_of / any_of / allow_other 的作用域正确
- [ ] experience qualifier 没有错误传播或丢失
- [ ] 每段 source_text 连续、逐字一致且足以支持结论
- 争议决策：[x] 年份 facts 保留 2026/2027，并增加精确毕业日期窗口；Java/Python 保持封闭 `required any_of`
- 复核结论：`修改；完整复核未完成`
- 修改或讨论说明：用户于 2026-09-03 明确回复“同意”；匹配时优先使用 2026-11-01 至 2027-10-31 的精确窗口。

### [ ] `campus-ai-161` 生数科技 - 流式视频生成训练实习生

- 官方岗位：[打开原文](https://shengshu.jobs.feishu.cn/index/position/7647489944366172422/detail)
- 非空 facts：`job_type, locations, major_requirements, internship_duration_months, weekly_days`
- clauses：`required=7`、`preferred=1`、`mention=3`
- 已知问题：可转正与不支持远程不在九 facts 中；保留在原文但当前契约无法单独结构化。
- [ ] 九个 facts 的值、空值和事实强度正确
- [ ] required / preferred / mention 没有混淆
- [ ] all_of / any_of / allow_other 的作用域正确
- [ ] experience qualifier 没有错误传播或丢失
- [ ] 每段 source_text 连续、逐字一致且足以支持结论
- 争议决策：[x] 整句实习安排只展示，不进入简历自动匹配或淘汰
- 复核结论：`保持；完整复核未完成`
- 修改或讨论说明：用户于 2026-09-04 确认沿用全局规则；Parser 标签仍保留 `weekly_days=5`、`internship_duration_months=3` 及原文 required 强度。

### [ ] `campus-ai-068` 影石创新 - AI开发工程师（C++方向）-2027校招

- 官方岗位：[打开原文](https://arashivision.jobs.feishu.cn/campus/position/7663402599408126246/detail)
- 非空 facts：`job_type, locations, graduation_years`
- clauses：`required=4`、`preferred=1`、`mention=4`
- 已知问题：安全方向经历同时包含“项目或课程设计”，当前以 project qualifier 近似，需人工复核该粒度。
- [ ] 九个 facts 的值、空值和事实强度正确
- [ ] required / preferred / mention 没有混淆
- [ ] all_of / any_of / allow_other 的作用域正确
- [ ] experience qualifier 没有错误传播或丢失
- [ ] 每段 source_text 连续、逐字一致且足以支持结论
- 争议决策：[x] 保留“项目或课程设计”的 `preferred any_of`，删除错误覆盖两项的 `project` qualifier
- 复核结论：`修改；完整复核未完成`
- 修改或讨论说明：用户于 2026-09-04 同意无需修改全局字段后继续；`qualifier` 仍作为其他明确经验类型的可选结构。

### [ ] `campus-ai-158` 月之暗面 - 后端研发实习生（Agent 产品工程方向）

- 官方岗位：[打开原文](https://app.mokahr.com/campus-recruitment/moonshot/148507?sourceToken=36ae0fe79b871e0600f2b2cfe0a81ebb#/job/52134dbe-419c-4251-9af6-6d3a9e4e04c3)
- 非空 facts：`job_type, locations, graduation_years, education_requirements, major_requirements, internship_duration_months, weekly_days`
- clauses：`required=10`、`preferred=4`、`mention=1`
- 已知问题：“27届及以后”是开放年份范围；facts 仅保存原文可枚举的 2027，clause 保留“及以后”，需人工确认契约是否应支持开放边界。
- [ ] 九个 facts 的值、空值和事实强度正确
- [ ] required / preferred / mention 没有混淆
- [ ] all_of / any_of / allow_other 的作用域正确
- [ ] experience qualifier 没有错误传播或丢失
- [ ] 每段 source_text 连续、逐字一致且足以支持结论
- 争议决策：[x] `[2027]` 保存边界年份，preferred clause 保留“2027届及以后”，不扩展 Schema
- 复核结论：`保持；完整复核未完成`
- 修改或讨论说明：用户于 2026-09-04 明确回复“同意”；2028 届及以后也满足优先项，其他年份不因此被自动淘汰；实习安排只展示。

### [ ] `campus-ai-140` 蔚来 - 校招-AI原生产品经理/产品工程师

- 官方岗位：[打开原文](https://nio.jobs.feishu.cn/campus/position/7673026981593024819/detail)
- 非空 facts：`job_type, locations, graduation_years, education_requirements, major_requirements`
- clauses：`required=6`、`preferred=4`、`mention=8`
- 已知问题：页面元数据写“硕士及以上”，职位要求写“本科或硕士”，草稿同时保留两条 source-backed 学历事实，必须人工裁决。
- [ ] 九个 facts 的值、空值和事实强度正确
- [ ] required / preferred / mention 没有混淆
- [ ] all_of / any_of / allow_other 的作用域正确
- [ ] experience qualifier 没有错误传播或丢失
- [ ] 每段 source_text 连续、逐字一致且足以支持结论
- 争议决策：[x] 以正文“本科或硕士”为准；页头“硕士及以上”只保留为冲突记录
- 复核结论：`修改；完整复核未完成`
- 修改或讨论说明：用户于 2026-09-04 明确回复“同意”；本科或硕士通过，博士待确认，不由系统推断。

### [ ] `campus-ai-072` 普源精电 - 数据科学家-2027届

- 官方岗位：[打开原文](https://rigolportal.jobs.feishu.cn/campus/position/7647752762708510985/detail)
- 非空 facts：`job_type, locations, graduation_years, education_requirements, major_requirements`
- clauses：`required=8`、`preferred=2`、`mention=6`
- 已知问题：“熟悉 LLM 原理、Prompt Engineering 或 RAG”拆为 LLM 原理必需，以及 Prompt/RAG 二选一，需人工确认原句作用域。
- [ ] 九个 facts 的值、空值和事实强度正确
- [ ] required / preferred / mention 没有混淆
- [ ] all_of / any_of / allow_other 的作用域正确
- [ ] experience qualifier 没有错误传播或丢失
- [ ] 每段 source_text 连续、逐字一致且足以支持结论
- 争议决策：[x] 将 LLM 原理、Prompt Engineering、RAG 架构合并为封闭 `required any_of`
- 复核结论：`修改；完整复核未完成`
- 修改或讨论说明：用户于 2026-09-04 明确回复“同意”；三项满足任一即可，不扩展 Schema。

## 中优先级：复杂语义（37）

### [ ] `campus-ai-011` 百度 - 北京-大模型算法工程师(J100728)

- 官方岗位：[打开原文](https://talent.baidu.com/jobs/detail/GRADUATE/ccfdea4e-4ae4-4954-9062-fd94960a2861)
- 非空 facts：`job_type, locations, education_requirements, major_requirements`
- clauses：`required=4`、`preferred=3`、`mention=5`
- 已知问题：招聘项目仅写‘校招’，未推测毕业年份。
- [ ] 九个 facts 的值、空值和事实强度正确
- [ ] required / preferred / mention 没有混淆
- [ ] all_of / any_of / allow_other 的作用域正确
- [ ] experience qualifier 没有错误传播或丢失
- [ ] 每段 source_text 连续、逐字一致且足以支持结论
- 争议决策：[x] 保留 `job_type=campus`、`graduation_years=null`，不从“应届生/校招”推测年份
- 复核结论：`保持；完整复核未完成`
- 修改或讨论说明：用户于 2026-09-04 明确回复“同意”；其余 clauses 保持草稿结果。

### [ ] `campus-ai-015` 百度 - 北京-大模型算法工程师（基座研发方向）(J101234)

- 官方岗位：[打开原文](https://talent.baidu.com/jobs/detail/GRADUATE/33f41590-5770-4a91-9395-3c05e7ed1571)
- 非空 facts：`job_type, locations, education_requirements, major_requirements`
- clauses：`required=5`、`preferred=2`、`mention=6`
- 已知问题：顶会论文与竞赛成绩按原文‘或’保留为 preferred any_of。
- [ ] 九个 facts 的值、空值和事实强度正确
- [ ] required / preferred / mention 没有混淆
- [ ] all_of / any_of / allow_other 的作用域正确
- [ ] experience qualifier 没有错误传播或丢失
- [ ] 每段 source_text 连续、逐字一致且足以支持结论
- 争议决策：[x] 顶会论文与编程/AI 竞赛成绩保持 `preferred any_of`，具体名称只作 examples
- 复核结论：`保持；完整复核未完成`
- 修改或讨论说明：用户于 2026-09-04 明确回复“同意”；两类成果满足任一即可获得加分。

### [ ] `campus-ai-023` 字节跳动 - Agent工程师 - 抖音用户增长

- 官方岗位：[打开原文](https://jobs.bytedance.com/campus/position/7667419628440242485/detail)
- 非空 facts：`job_type, locations, graduation_years, education_requirements, major_requirements`
- clauses：`required=4`、`preferred=6`、`mention=5`
- 已知问题：加分项标题使其下四条均标为 preferred。
- [ ] 九个 facts 的值、空值和事实强度正确
- [ ] required / preferred / mention 没有混淆
- [ ] all_of / any_of / allow_other 的作用域正确
- [ ] experience qualifier 没有错误传播或丢失
- [ ] 每段 source_text 连续、逐字一致且足以支持结论
- 争议决策：[x] “加分项”标题下四条全部保持 `preferred`，不提升为 required
- 争议决策：[x] “等技术领域之一或多个”改为开放 `required any_of`，`allow_other=true`
- 复核结论：`修改；完整复核未完成`
- 修改或讨论说明：用户于 2026-09-04 两次明确回复“同意”；任一加分项均可作证据，Agent 技术组允许其他同类项。

### [ ] `campus-ai-027` 字节跳动 - AI Agent后端研发工程师 - Data AML

- 官方岗位：[打开原文](https://jobs.bytedance.com/campus/position/7669700362425190709/detail)
- 非空 facts：`job_type, locations, graduation_years, education_requirements, major_requirements`
- clauses：`required=6`、`preferred=2`、`mention=6`
- 已知问题：LLM应用开发后的框架使用或自主架构设计是混合类别备选，暂按 capability any_of 表达。
- [ ] 九个 facts 的值、空值和事实强度正确
- [ ] required / preferred / mention 没有混淆
- [ ] all_of / any_of / allow_other 的作用域正确
- [ ] experience qualifier 没有错误传播或丢失
- [ ] 每段 source_text 连续、逐字一致且足以支持结论
- 争议决策：[x] LLM 应用开发经验单独 required；框架使用或自主架构设计为封闭 `required any_of`
- 复核结论：`修改；完整复核未完成`
- 修改或讨论说明：用户于 2026-09-04 明确回复“同意”；框架名称只作开放 examples，顶层 `allow_other=false`，不扩展 Schema。

### [ ] `campus-ai-032` 字节跳动 - AI Agent开发工程师 - 抖音研发

- 官方岗位：[打开原文](https://jobs.bytedance.com/campus/position/7667476145728080133/detail)
- 非空 facts：`job_type, locations, graduation_years, education_requirements, major_requirements`
- clauses：`required=4`、`preferred=2`、`mention=5`
- 已知问题：与 campus-ai-023 共用主体要求，但本样本没有额外加分项，未从相邻岗位复制。
- [ ] 九个 facts 的值、空值和事实强度正确
- [ ] required / preferred / mention 没有混淆
- [ ] all_of / any_of / allow_other 的作用域正确
- [ ] experience qualifier 没有错误传播或丢失
- [ ] 每段 source_text 连续、逐字一致且足以支持结论
- 争议决策：[x] 不复制相邻岗位的额外加分项；Agent 技术组改为开放 `required any_of`，`allow_other=true`
- 复核结论：`修改；完整复核未完成`
- 修改或讨论说明：用户于 2026-09-04 明确回复“同意”；列出的四项或其他同类 Agent 技术满足任一即可。

### [ ] `campus-ai-037` 字节跳动 - Agent研发工程师 - 飞书

- 官方岗位：[打开原文](https://jobs.bytedance.com/campus/position/7668280227769157893/detail)
- 非空 facts：`job_type, graduation_years, education_requirements, major_requirements`
- clauses：`required=3`、`preferred=2`、`mention=4`
- 已知问题：原文未提供工作地点，locations 保持 null。
- [ ] 九个 facts 的值、空值和事实强度正确
- [ ] required / preferred / mention 没有混淆
- [ ] all_of / any_of / allow_other 的作用域正确
- [ ] experience qualifier 没有错误传播或丢失
- [ ] 每段 source_text 连续、逐字一致且足以支持结论
- 争议决策：[x] `locations=null`；补回“大模型应用开发” skill mention，不提升为 required
- 复核结论：`修改；完整复核未完成`
- 修改或讨论说明：用户于 2026-09-04 明确回复“同意”；其余四项保持 `mention any_of`。

### [ ] `campus-ai-078` 千寻智能 - 【2027 届校招】多模态世界模型算法工程师

- 官方岗位：[打开原文](https://nwd4iy9rd2s.jobs.feishu.cn/campusofSpiritAI/position/7672030617039292713/detail)
- 非空 facts：`job_type, locations, graduation_years, education_requirements, major_requirements`
- clauses：`required=7`、`preferred=2`、`mention=5`
- 已知问题：博士既是 education fact 的可接受值，也是相对于硕士门槛的 preferred fact clause。
- [ ] 九个 facts 的值、空值和事实强度正确
- [ ] required / preferred / mention 没有混淆
- [ ] all_of / any_of / allow_other 的作用域正确
- [ ] experience qualifier 没有错误传播或丢失
- [ ] 每段 source_text 连续、逐字一致且足以支持结论
- 争议决策：[x] “硕士及以上”保持 required，“博士优先”保持同一 fact 下的 preferred clause
- 复核结论：`保持；完整复核未完成`
- 修改或讨论说明：用户于 2026-09-04 明确回复“同意”；硕士满足门槛，博士额外加分。

### [ ] `campus-ai-080` 千寻智能 - 【2027 届校招】AI Infra工程师

- 官方岗位：[打开原文](https://nwd4iy9rd2s.jobs.feishu.cn/campusofSpiritAI/position/7672029899397744902/detail)
- 非空 facts：`job_type, locations, graduation_years`
- clauses：`required=6`、`preferred=0`、`mention=4`
- 已知问题：JD 未写学历或专业，两个 facts 保持 null。
- [ ] 九个 facts 的值、空值和事实强度正确
- [ ] required / preferred / mention 没有混淆
- [ ] all_of / any_of / allow_other 的作用域正确
- [ ] experience qualifier 没有错误传播或丢失
- [ ] 每段 source_text 连续、逐字一致且足以支持结论
- 争议决策：[x] 学历、专业保持 null；PyTorch 改为“深度学习框架架构与原理”的 example
- 复核结论：`修改；完整复核未完成`
- 修改或讨论说明：用户于 2026-09-04 明确回复“同意”；其他同类深度学习框架也可满足该 required item。

### [ ] `campus-ai-097` MiniMax - 可观测平台研发工程师-2027届

- 官方岗位：[打开原文](https://vrfi1sk8a0.jobs.feishu.cn/379481/position/7662376183711222058/detail)
- 非空 facts：`job_type, locations, graduation_years, education_requirements, major_requirements`
- clauses：`required=5`、`preferred=2`、`mention=5`
- 已知问题：‘操作系统、网络、数据库或分布式系统’按原文明示的或标为 any_of。
- [ ] 九个 facts 的值、空值和事实强度正确
- [ ] required / preferred / mention 没有混淆
- [ ] all_of / any_of / allow_other 的作用域正确
- [ ] experience qualifier 没有错误传播或丢失
- [ ] 每段 source_text 连续、逐字一致且足以支持结论
- 争议决策：[x] 系统基础四选一；编程语言四选一并改为封闭 `required any_of`、`allow_other=false`
- 复核结论：`修改；完整复核未完成`
- 修改或讨论说明：用户于 2026-09-04 明确回复“同意”；其他语言不能直接替代原文列出的四种语言。

### [ ] `campus-ai-102` 它石智航 - 2027校招-强化学习算法工程师

- 官方岗位：[打开原文](https://tarsrobot.jobs.feishu.cn/021343/position/7667918400576981291/detail)
- 非空 facts：`job_type, locations, graduation_years, education_requirements, major_requirements`
- clauses：`required=7`、`preferred=5`、`mention=5`
- 已知问题：‘硕士/博士优先’与硕士及以上硬门槛语义重复，保留原文 preferred fact 供人工复核。
- [ ] 九个 facts 的值、空值和事实强度正确
- [ ] required / preferred / mention 没有混淆
- [ ] all_of / any_of / allow_other 的作用域正确
- [ ] experience qualifier 没有错误传播或丢失
- [ ] 每段 source_text 连续、逐字一致且足以支持结论
- 争议决策：[x] 保留“硕士/博士优先”的原文 preferred clause，但不产生重复排序加分
- 复核结论：`保持；完整复核未完成`
- 修改或讨论说明：用户于 2026-09-04 明确回复“同意”；基础门槛仍是硕士及以上，硕士不会受影响。

### [ ] `campus-ai-116` 自变量机器人 - 【27届】集成工具链开发

- 官方岗位：[打开原文](https://x2-robot.jobs.feishu.cn/912130/position/7673866807501916458/detail)
- 非空 facts：`job_type, locations, graduation_years, education_requirements, major_requirements`
- clauses：`required=5`、`preferred=3`、`mention=4`
- 已知问题：ROS2/ROS 是备选，通信框架是并列 preferred；拆成两条以避免错误地三选一。
- [ ] 九个 facts 的值、空值和事实强度正确
- [ ] required / preferred / mention 没有混淆
- [ ] all_of / any_of / allow_other 的作用域正确
- [ ] experience qualifier 没有错误传播或丢失
- [ ] 每段 source_text 连续、逐字一致且足以支持结论
- 争议决策：[x] ROS2/ROS 保持 `preferred any_of`，通信框架保持并列 preferred，不扩展嵌套 Schema
- 复核结论：`保持；完整复核未完成`
- 修改或讨论说明：用户于 2026-09-04 明确回复“同意”；不能解析成三选一，缺少任一项不自动淘汰。

### [ ] `campus-ai-121` MiniMax - 资源调度研发工程师-2027届

- 官方岗位：[打开原文](https://vrfi1sk8a0.jobs.feishu.cn/379481/position/7662380007045761343/detail)
- 非空 facts：`job_type, locations, graduation_years, education_requirements, major_requirements`
- clauses：`required=6`、`preferred=3`、`mention=4`
- 已知问题：末条同时允许项目、实习或开源三种经历类型，当前 qualifier 无法表达多种类型，故保留为空。
- [ ] 九个 facts 的值、空值和事实强度正确
- [ ] required / preferred / mention 没有混淆
- [ ] all_of / any_of / allow_other 的作用域正确
- [ ] experience qualifier 没有错误传播或丢失
- [ ] 每段 source_text 连续、逐字一致且足以支持结论
- 争议决策：[x] 项目、实习、开源经历改为 `preferred any_of` items，技术方向作为 examples，qualifier=null
- 复核结论：`修改；完整复核未完成`
- 修改或讨论说明：用户于 2026-09-04 明确回复“同意”；三种经历形式满足任一即可，不扩展 Schema。

### [ ] `campus-ai-126` 懂车帝 - AI Native 移动开发工程师-懂车帝（2027届校招）

- 官方岗位：[打开原文](https://dcar.jobs.feishu.cn/campus/position/7659806674613750059/detail)
- 非空 facts：`job_type, locations, graduation_years, education_requirements, major_requirements`
- clauses：`required=5`、`preferred=7`、`mention=4`
- 已知问题：‘有相关项目经验者优先’依据同一句限定为 AI Coding 项目，不向其他条款传播。
- [ ] 九个 facts 的值、空值和事实强度正确
- [ ] required / preferred / mention 没有混淆
- [ ] all_of / any_of / allow_other 的作用域正确
- [ ] experience qualifier 没有错误传播或丢失
- [ ] 每段 source_text 连续、逐字一致且足以支持结论
- 争议决策：[x] AI Coding 项目限定在同句；跨平台、多端、Agent 项目的具体名称改为 examples
- 复核结论：`修改；完整复核未完成`
- 修改或讨论说明：用户于 2026-09-04 明确回复“同意”；多端经验不能由单端替代，Agent 三个方向不要求全部具备。

### [ ] `campus-ai-147` 影石创新 - AI应用产品管培生-2027校招

- 官方岗位：[打开原文](https://arashivision.jobs.feishu.cn/campus/position/7664585052421196041/detail)
- 非空 facts：`job_type, locations, graduation_years, education_requirements, major_requirements`
- clauses：`required=3`、`preferred=2`、`mention=6`
- 已知问题：专业不限作为显式 major fact，并用 mention fact clause 表示它不是门槛。
- [ ] 九个 facts 的值、空值和事实强度正确
- [ ] required / preferred / mention 没有混淆
- [ ] all_of / any_of / allow_other 的作用域正确
- [ ] experience qualifier 没有错误传播或丢失
- [ ] 每段 source_text 连续、逐字一致且足以支持结论
- 争议决策：[x] `major_requirements` 保持“专业不限”；列举背景另作 mention 示例，不形成门槛
- 复核结论：`修改；完整复核未完成`
- 修改或讨论说明：用户于 2026-09-04 明确回复“同意”；未列举的专业同样可以申请，不淘汰、不扣分。

### [ ] `campus-ai-153` 智元机器人 - 具身Agent算法工程师-通用业务部

- 官方岗位：[打开原文](https://agirobot.jobs.feishu.cn/campusrecruitment/position/7675561002955639086/detail)
- 非空 facts：`job_type, locations, education_requirements, major_requirements`
- clauses：`required=6`、`preferred=1`、`mention=4`
- 已知问题：完整项目或开源项目是跨 experience_type 的 any_of，当前 qualifier 留空以免错误限定整个组。
- [ ] 九个 facts 的值、空值和事实强度正确
- [ ] required / preferred / mention 没有混淆
- [ ] all_of / any_of / allow_other 的作用域正确
- [ ] experience qualifier 没有错误传播或丢失
- [ ] 每段 source_text 连续、逐字一致且足以支持结论
- 争议决策：[x] 完整具身 Agent 项目与具身开源项目参与为 `required any_of`，项目名称仅作示例，qualifier=null
- 复核结论：`保持；完整复核未完成`
- 修改或讨论说明：用户于 2026-09-04 明确回复“同意”；两条路径满足任一即可，其他同类开源项目也可。

### [ ] `campus-ai-069` 面壁智能 - 大模型算法工程师 - 智能体方向

- 官方岗位：[打开原文](https://modelbest.jobs.feishu.cn/campus/position/7516643657231911180/detail)
- 非空 facts：`job_type, locations, graduation_years, education_requirements, major_requirements`
- clauses：`required=7`、`preferred=3`、`mention=3`
- 已知问题：专业与毕业届别由同一资格句支持；未从页面职位标题补充其他事实。
- [ ] 九个 facts 的值、空值和事实强度正确
- [ ] required / preferred / mention 没有混淆
- [ ] all_of / any_of / allow_other 的作用域正确
- [ ] experience qualifier 没有错误传播或丢失
- [ ] 每段 source_text 连续、逐字一致且足以支持结论
- 争议决策：[x] 同一资格句可分别支持专业和毕业年份；专业与主流语言均为开放 `required any_of`
- 复核结论：`保持；完整复核未完成`
- 修改或讨论说明：用户于 2026-09-04 明确回复“同意”；框架名称仅作示例，三个 preferred 项均不自动淘汰，不从标题额外推测事实。

### [ ] `campus-ai-058` 腾讯 - Agent开发工程师

- 官方岗位：[打开原文](https://join.qq.com/post_detail.html?postid=1282707395466077184&activity=1289677625995575296)
- 非空 facts：`job_type, graduation_years`
- clauses：`required=6`、`preferred=1`、`mention=5`
- 已知问题：原文没有工作地点、学历和专业，相关 facts 保持 null。
- [ ] 九个 facts 的值、空值和事实强度正确
- [ ] required / preferred / mention 没有混淆
- [ ] all_of / any_of / allow_other 的作用域正确
- [ ] experience qualifier 没有错误传播或丢失
- [ ] 每段 source_text 连续、逐字一致且足以支持结论
- 争议决策：[x] 保持标准化显示“Agent实际搭建经验”，按同句上下文理解，不扩展当前 source_text
- 复核结论：`保持；完整复核未完成`
- 修改或讨论说明：用户于 2026-09-04 明确回复“同意”；地点、学历和专业保持 null，语言组开放，末条经历为 preferred any_of。

### [ ] `campus-ai-109` 信华信 - 【27届校招】Harness算法工程师

- 官方岗位：[打开原文](https://il6pr702sp.jobs.feishu.cn/443656/position/7675207734677817642/detail)
- 非空 facts：`job_type, locations, graduation_years, education_requirements, major_requirements`
- clauses：`required=7`、`preferred=4`、`mention=6`
- 已知问题：岗位职责长句按共享语义范围截取；未把运行时模块自动提升为候选人硬要求。
- [ ] 九个 facts 的值、空值和事实强度正确
- [ ] required / preferred / mention 没有混淆
- [ ] all_of / any_of / allow_other 的作用域正确
- [ ] experience qualifier 没有错误传播或丢失
- [ ] 每段 source_text 连续、逐字一致且足以支持结论
- 争议决策：[x] 岗位职责技术名词只作 mention；末句按 required 意识与 preferred 经验拆分
- 复核结论：`保持；完整复核未完成`
- 修改或讨论说明：用户于 2026-09-04 明确回复“同意”；基础设施与成果经历均按 preferred any_of，框架名称只作项目示例。

### [ ] `campus-ai-089` 大疆创新 - 空间智能基础模型算法工程师（深圳）

- 官方岗位：[打开原文](https://apply.careers.dji.com/campus-recruitment/dji/143359?locale=zh-CN#/job/e37d49d0-3b31-4d50-9b5c-43fce020dbbe)
- 非空 facts：`job_type, locations, graduation_years, education_requirements, major_requirements`
- clauses：`required=7`、`preferred=4`、`mention=4`
- 已知问题：3D视觉分支内部斜杠表示同一分支技术族，暂保留为复合 item，避免错误拆成全部独立候选。
- [ ] 九个 facts 的值、空值和事实强度正确
- [ ] required / preferred / mention 没有混淆
- [ ] all_of / any_of / allow_other 的作用域正确
- [ ] experience qualifier 没有错误传播或丢失
- [ ] 每段 source_text 连续、逐字一致且足以支持结论
- 争议决策：[x] 三个复合技术族保持 `required any_of`；因原文有“等”，改为 `allow_other=true`
- 复核结论：`修改；完整复核未完成`
- 修改或讨论说明：用户于 2026-09-04 明确回复“同意”；斜杠内名称不拆成必须全部掌握的独立项，其他同类分支也可。

### [ ] `campus-ai-157` 月之暗面 - 【校招】大模型算法研究员/工程师（预训练）

- 官方岗位：[打开原文](https://app.mokahr.com/campus-recruitment/moonshot/148507?sourceToken=36ae0fe79b871e0600f2b2cfe0a81ebb#/job/e3a6bf00-f9bd-4daa-a03a-f965220c6bf1)
- 非空 facts：`job_type, locations, education_requirements, major_requirements`
- clauses：`required=4`、`preferred=4`、`mention=4`
- 已知问题：学历条件同时包含院校类型和例外本科生，原样保留，未简化成普通硕士门槛。
- [ ] 九个 facts 的值、空值和事实强度正确
- [ ] required / preferred / mention 没有混淆
- [ ] all_of / any_of / allow_other 的作用域正确
- [ ] experience qualifier 没有错误传播或丢失
- [ ] 每段 source_text 连续、逐字一致且足以支持结论
- 争议决策：[x] 学历例外原样保留；PyTorch/JAX 与 Triton/CUDA 改为对应技术类别的 examples
- 复核结论：`修改；完整复核未完成`
- 修改或讨论说明：用户于 2026-09-04 明确回复“同意”；不把学历简化为硕士门槛，也不要求示例框架全部掌握。

### [ ] `campus-ai-164` 逐际动力 - 机器人强化学习实习生

- 官方岗位：[打开原文](https://career.limxdynamics.com/index/position/7436212279131687178/detail)
- 非空 facts：`job_type, locations, education_requirements, major_requirements, internship_duration_months`
- clauses：`required=3`、`preferred=2`、`mention=6`
- 已知问题：专业明确写优先，未因机器人岗位将其升级为 required。
- [ ] 九个 facts 的值、空值和事实强度正确
- [ ] required / preferred / mention 没有混淆
- [ ] all_of / any_of / allow_other 的作用域正确
- [ ] experience qualifier 没有错误传播或丢失
- [ ] 每段 source_text 连续、逐字一致且足以支持结论
- 争议决策：[x] 专业保持 preferred；C++ 与 Python 均为 required；三个月时长只展示、不匹配
- 复核结论：`保持；完整复核未完成`
- 修改或讨论说明：用户于 2026-09-04 明确回复“同意”；“了解”类技术保持 mention，机器人操作项目经验保持 preferred。

### [ ] `campus-ai-155` 阶跃星辰 - 27届Stepstar-大语言模型pre-train 算法研究员

- 官方岗位：[打开原文](https://app.mokahr.com/campus-recruitment/step/94905#/job/e1b32746-3aff-47b6-bef5-7370840c3db0)
- 非空 facts：`job_type, locations, graduation_years, major_requirements`
- clauses：`required=4`、`preferred=1`、`mention=4`
- 已知问题：明确毕业日期窗口跨两个自然年，因此 graduation_years 标 2026 和 2027。
- [ ] 九个 facts 的值、空值和事实强度正确
- [ ] required / preferred / mention 没有混淆
- [ ] all_of / any_of / allow_other 的作用域正确
- [ ] experience qualifier 没有错误传播或丢失
- [ ] 每段 source_text 连续、逐字一致且足以支持结论
- 争议决策：[x] 保留 `[2026, 2027]` 并新增 `2026-09 至 2027-08` 精确毕业窗口
- 复核结论：`修改；完整复核未完成`
- 修改或讨论说明：用户于 2026-09-04 明确回复“同意”；实际判断优先使用月份，简历缺少月份时返回信息不足；学历保持 null。

### [ ] `campus-ai-124` 普源精电 - 算法工程师-2027届

- 官方岗位：[打开原文](https://rigolportal.jobs.feishu.cn/campus/position/7647747667494652169/detail)
- 非空 facts：`job_type, locations, graduation_years, education_requirements, major_requirements`
- clauses：`required=12`、`preferred=2`、`mention=11`
- 已知问题：博士是硕士及以上硬门槛之上的优先学历，因此同时保留 education fact 和 preferred fact clause。
- [ ] 九个 facts 的值、空值和事实强度正确
- [ ] required / preferred / mention 没有混淆
- [ ] all_of / any_of / allow_other 的作用域正确
- [ ] experience qualifier 没有错误传播或丢失
- [ ] 每段 source_text 连续、逐字一致且足以支持结论
- 争议决策：[x] 硕士 required、博士 preferred；硬件或软件实现流程改为 `mention any_of`
- 复核结论：`修改；完整复核未完成`
- 修改或讨论说明：用户于 2026-09-04 明确回复“同意”；一般项目经验 required、具体算法项目 preferred，C/C++ 或 Python 为封闭 required any_of。

### [ ] `campus-ai-075` 小鹏汽车 - 【27届校招】智能座舱云端Agent研发工程师（北京）

- 官方岗位：[打开原文](https://xiaopeng.jobs.feishu.cn/campus/position/7658239772267186470/detail)
- 非空 facts：`job_type, locations, graduation_years, education_requirements, major_requirements`
- clauses：`required=6`、`preferred=3`、`mention=3`
- 已知问题：“了解大语言模型基本原理”位于加分项中，按 preferred 而不是普通 mention 标注。
- [ ] 九个 facts 的值、空值和事实强度正确
- [ ] required / preferred / mention 没有混淆
- [ ] all_of / any_of / allow_other 的作用域正确
- [ ] experience qualifier 没有错误传播或丢失
- [ ] 每段 source_text 连续、逐字一致且足以支持结论
- 争议决策：[x] 加分项中的“了解大模型”保持 preferred；四类相关经历改为 `preferred any_of`
- 复核结论：`修改；完整复核未完成`
- 修改或讨论说明：用户于 2026-09-04 明确回复“同意”；任一类经历即可加分，智能座舱和智能语音助手只是重点方向示例。

### [ ] `campus-ai-085` 沐瞳科技 - 【2027届秋招】AI Agent 产品经理（平台）

- 官方岗位：[打开原文](https://moonton.jobs.feishu.cn/campus/position/7669735314894555411/detail)
- 非空 facts：`job_type, locations, graduation_years, education_requirements, major_requirements`
- clauses：`required=8`、`preferred=7`、`mention=7`
- 已知问题：加分项统一保持 preferred；只在原文明示“或”时使用 any_of，工具清单作为上位经验的 examples。
- [ ] 九个 facts 的值、空值和事实强度正确
- [ ] required / preferred / mention 没有混淆
- [ ] all_of / any_of / allow_other 的作用域正确
- [ ] experience qualifier 没有错误传播或丢失
- [ ] 每段 source_text 连续、逐字一致且足以支持结论
- 争议决策：[x] 专业保持 preferred；加分项统一 preferred，显式“或”使用 any_of，工具名称只作 examples
- 复核结论：`保持；完整复核未完成`
- 修改或讨论说明：用户于 2026-09-04 明确回复“同意”，并授权后续无争议条目直接确认。

### [ ] `campus-ai-070` Momenta - 2027届-SDK开发工程师

- 官方岗位：[打开原文](https://momenta.jobs.feishu.cn/campus/position/7665626835951159603/detail)
- 非空 facts：`job_type, locations, graduation_years, education_requirements, major_requirements`
- clauses：`required=1`、`preferred=5`、`mention=2`
- 已知问题：该岗位除本科门槛外，其余任职条件均明确写为优先，未升级为 required。
- [ ] 九个 facts 的值、空值和事实强度正确
- [ ] required / preferred / mention 没有混淆
- [ ] all_of / any_of / allow_other 的作用域正确
- [ ] experience qualifier 没有错误传播或丢失
- [ ] 每段 source_text 连续、逐字一致且足以支持结论
- 自动确认：[x] 本科 required，其余原文明示条件均为 preferred
- 复核结论：`保持；完整复核未完成`
- 修改或讨论说明：用户授权无争议条目直接确认；未把任何优先项升级为硬门槛。

### [ ] `campus-ai-107` 自变量机器人 - 【27届】大模型infra工程师

- 官方岗位：[打开原文](https://x2-robot.jobs.feishu.cn/912130/position/7652253703286720814/detail)
- 非空 facts：`job_type, locations, graduation_years, education_requirements, major_requirements`
- clauses：`required=2`、`preferred=3`、`mention=3`
- 已知问题：毕业日期区间跨 2026、2027 两个自然年；专业明确为优先，未升级为硬门槛。
- [ ] 九个 facts 的值、空值和事实强度正确
- [ ] required / preferred / mention 没有混淆
- [ ] all_of / any_of / allow_other 的作用域正确
- [ ] experience qualifier 没有错误传播或丢失
- [ ] 每段 source_text 连续、逐字一致且足以支持结论
- 自动确认：[x] 新增 `2026-09 至 2027-08` 精确毕业窗口；专业保持开放 preferred
- 复核结论：`修改；完整复核未完成`
- 修改或讨论说明：复用已确认的精确日期规则；简历缺少月份时返回信息不足。

### [ ] `campus-ai-152` 智元机器人 - 具身算法工程师（VLA+RL）-通用业务部

- 官方岗位：[打开原文](https://agirobot.jobs.feishu.cn/campusrecruitment/position/7677544840104757550/detail)
- 非空 facts：`job_type, locations, education_requirements, major_requirements`
- clauses：`required=10`、`preferred=2`、`mention=5`
- 已知问题：“精通 PyTorch”与后续“CUDA/vLLM/Triton 者优先”强度不同，已拆为 required 和 preferred。
- [ ] 九个 facts 的值、空值和事实强度正确
- [ ] required / preferred / mention 没有混淆
- [ ] all_of / any_of / allow_other 的作用域正确
- [ ] experience qualifier 没有错误传播或丢失
- [ ] 每段 source_text 连续、逐字一致且足以支持结论
- 自动确认：[x] 强化学习算法与仿真环境名称改为 examples；PyTorch required、CUDA/vLLM/Triton preferred
- 复核结论：`修改；完整复核未完成`
- 修改或讨论说明：复用 `campus-ai-157` 已确认规则；不要求列举算法或仿真环境全部掌握。

### [ ] `campus-ai-059` 腾讯 - 腾讯云大数据—DataAgent-数据决策智能体关键技术研究

- 官方岗位：[打开原文](https://join.qq.com/post_detail.html?postid=1231829074692139099)
- 非空 facts：`job_type, education_requirements, major_requirements`
- clauses：`required=6`、`preferred=0`、`mention=2`
- 已知问题：原文未给工作地点、实习时长和每周到岗天数，均保持 null；不从 CSIG 部门信息推断地点。
- [ ] 九个 facts 的值、空值和事实强度正确
- [ ] required / preferred / mention 没有混淆
- [ ] all_of / any_of / allow_other 的作用域正确
- [ ] experience qualifier 没有错误传播或丢失
- [ ] 每段 source_text 连续、逐字一致且足以支持结论
- 自动确认：[x] 缺失地点和实习安排保持 null；博士或优秀硕士为 required any_of
- 复核结论：`保持；完整复核未完成`
- 修改或讨论说明：用户授权无争议条目直接确认；不从部门信息推断岗位事实。

### [ ] `campus-ai-108` 信华信 - 【27届校招】Agent算法应用工程师

- 官方岗位：[打开原文](https://il6pr702sp.jobs.feishu.cn/443656/position/7675209597687564570/detail)
- 非空 facts：`job_type, locations, graduation_years, education_requirements, major_requirements`
- clauses：`required=12`、`preferred=2`、`mention=5`
- 已知问题：主流框架名称是“至少一种框架”的 examples，不把所有框架误标成同时必需。
- [ ] 九个 facts 的值、空值和事实强度正确
- [ ] required / preferred / mention 没有混淆
- [ ] all_of / any_of / allow_other 的作用域正确
- [ ] experience qualifier 没有错误传播或丢失
- [ ] 每段 source_text 连续、逐字一致且足以支持结论
- 自动确认：[x] “相关专业”改为开放组；TypeScript/JavaScript 保持同一技术族
- 复核结论：`修改；完整复核未完成`
- 修改或讨论说明：用户授权无争议条目直接确认；Python 与 TypeScript/JavaScript 生态仍同时 required，框架名称只作 examples。

### [ ] `campus-ai-110` 懂车帝 - AI应用研发工程师-懂车帝（2027届校招）

- 官方岗位：[打开原文](https://dcar.jobs.feishu.cn/campus/position/7659354517679655177/detail)
- 非空 facts：`job_type, locations, graduation_years, education_requirements, major_requirements`
- clauses：`required=8`、`preferred=6`、`mention=3`
- 已知问题：加分项 8-10 的“了解”和项目经验均受加分项标题约束，保持 preferred。
- [ ] 九个 facts 的值、空值和事实强度正确
- [ ] required / preferred / mention 没有混淆
- [ ] all_of / any_of / allow_other 的作用域正确
- [ ] experience qualifier 没有错误传播或丢失
- [ ] 每段 source_text 连续、逐字一致且足以支持结论
- 自动确认：[x] 专业与第 8-10 条均保持 preferred，其余职位要求按原文保持 required
- 复核结论：`保持；完整复核未完成`
- 修改或讨论说明：用户授权无争议条目直接确认；加分项标题控制其中“了解”和项目经历的强度。

### [ ] `campus-ai-091` 大疆创新 - 端到端决策规划算法工程师（北京）

- 官方岗位：[打开原文](https://apply.careers.dji.com/campus-recruitment/dji/143359?locale=zh-CN#/job/db251970-b5e8-4a62-981a-97efb24d8c80)
- 非空 facts：`job_type, locations, graduation_years, education_requirements, major_requirements`
- clauses：`required=5`、`preferred=4`、`mention=4`
- 已知问题：加分项标题为其中四条统一提供 preferred 强度；框架和论文名称保留为 examples。
- [ ] 九个 facts 的值、空值和事实强度正确
- [ ] required / preferred / mention 没有混淆
- [ ] all_of / any_of / allow_other 的作用域正确
- [ ] experience qualifier 没有错误传播或丢失
- [ ] 每段 source_text 连续、逐字一致且足以支持结论
- 自动确认：[x] 四个基本实践方向为 required any_of；四条加分项统一 preferred
- 复核结论：`保持；完整复核未完成`
- 修改或讨论说明：用户授权无争议条目直接确认；会议和 VLA 工作名称只作 examples。

### [ ] `campus-ai-052` 阿里巴巴 - AI Agent算法工程师（大模型方向）

- 官方岗位：[打开原文](https://campus-talent.alibaba.com/campus/position/199903900038)
- 非空 facts：`job_type, locations, graduation_years, education_requirements, major_requirements, internship_duration_months`
- clauses：`required=7`、`preferred=4`、`mention=5`
- 已知问题：毕业时间是明确日期区间，因此枚举覆盖到的 2026-2029；更新日期不标为截止日期。
- [ ] 九个 facts 的值、空值和事实强度正确
- [ ] required / preferred / mention 没有混淆
- [ ] all_of / any_of / allow_other 的作用域正确
- [ ] experience qualifier 没有错误传播或丢失
- [ ] 每段 source_text 连续、逐字一致且足以支持结论
- 自动确认：[x] 新增 `2026-11-01 至 2029-09-30` 精确毕业窗口；实习三个月只展示
- 复核结论：`修改；完整复核未完成`
- 修改或讨论说明：复用已确认的精确日期与实习安排规则；更新日期不是截止日期。

### [ ] `campus-ai-165` 逐际动力 - 具身智能前沿算法实习生

- 官方岗位：[打开原文](https://career.limxdynamics.com/index/position/7552721156127263027/detail)
- 非空 facts：`job_type, locations, education_requirements, major_requirements`
- clauses：`required=7`、`preferred=2`、`mention=2`
- 已知问题：职位描述中的多个“熟悉”是在列研究方向，按 responsibility + mention，而不是任职硬门槛。
- [ ] 九个 facts 的值、空值和事实强度正确
- [ ] required / preferred / mention 没有混淆
- [ ] all_of / any_of / allow_other 的作用域正确
- [ ] experience qualifier 没有错误传播或丢失
- [ ] 每段 source_text 连续、逐字一致且足以支持结论
- 自动确认：[x] 六类研究方向保持 responsibility mention，模型名称只作 examples
- 复核结论：`保持；完整复核未完成`
- 修改或讨论说明：用户授权无争议条目直接确认；不因职责描述中的“熟悉”生成硬门槛。

### [ ] `campus-ai-156` 阶跃星辰 - 27届Stepstar-大语言模型pre-train 数据算法工程师

- 官方岗位：[打开原文](https://app.mokahr.com/campus-recruitment/step/94905#/job/9fd48889-12c5-4613-b0f7-1f459c6340b0)
- 非空 facts：`job_type, locations, graduation_years, major_requirements`
- clauses：`required=6`、`preferred=2`、`mention=5`
- 已知问题：岗位没有明确学历层级，education_requirements 保持 null；不从“优秀应届毕业生”推断本科或硕士。
- [ ] 九个 facts 的值、空值和事实强度正确
- [ ] required / preferred / mention 没有混淆
- [ ] all_of / any_of / allow_other 的作用域正确
- [ ] experience qualifier 没有错误传播或丢失
- [ ] 每段 source_text 连续、逐字一致且足以支持结论
- 自动确认：[x] 学历保持 null，并新增 `2026-09 至 2027-08` 精确毕业窗口
- 复核结论：`修改；完整复核未完成`
- 修改或讨论说明：复用已确认的精确日期规则；“优秀应届毕业生”不支持推断学历层级。

### [ ] `campus-ai-073` 小鹏汽车 - 【27届校招】AI前瞻培训生

- 官方岗位：[打开原文](https://xiaopeng.jobs.feishu.cn/campus/position/7658239651849996570/detail)
- 非空 facts：`job_type, locations, graduation_years, education_requirements, major_requirements`
- clauses：`required=7`、`preferred=3`、`mention=6`
- 已知问题：原文“有项目经验的优先”仅由同一句 Agent 框架上下文限定，未向其他技能条款传播。
- [ ] 九个 facts 的值、空值和事实强度正确
- [ ] required / preferred / mention 没有混淆
- [ ] all_of / any_of / allow_other 的作用域正确
- [ ] experience qualifier 没有错误传播或丢失
- [ ] 每段 source_text 连续、逐字一致且足以支持结论
- 自动确认：[x] 项目经验优先只承接同句 Agents 开发框架，不向其他技能传播
- 复核结论：`保持；完整复核未完成`
- 修改或讨论说明：用户授权无争议条目直接确认；框架和模型名称保持 examples。

### [ ] `campus-ai-086` 沐瞳科技 - 【2027届秋招】Agent开发工程师（平台）

- 官方岗位：[打开原文](https://moonton.jobs.feishu.cn/campus/position/7668253932858362118/detail)
- 非空 facts：`job_type, locations, graduation_years, education_requirements, major_requirements`
- clauses：`required=10`、`preferred=5`、`mention=10`
- 已知问题：职位要求中的“了解”保持 mention；加分项中的“了解…者优先”保持 preferred，避免由动词单独决定强度。
- [ ] 九个 facts 的值、空值和事实强度正确
- [ ] required / preferred / mention 没有混淆
- [ ] all_of / any_of / allow_other 的作用域正确
- [ ] experience qualifier 没有错误传播或丢失
- [ ] 每段 source_text 连续、逐字一致且足以支持结论
- 自动确认：[x] 职位要求中的“了解”保持 mention，加分项中的“了解…者优先”保持 preferred
- 复核结论：`保持；完整复核未完成`
- 修改或讨论说明：用户授权无争议条目直接确认；课程、实习或个人项目经历为 required any_of。

## 常规复核（1）

### [ ] `campus-ai-024` 字节跳动 - 豆包大模型Agent Harness算法工程师 - Data AML

- 官方岗位：[打开原文](https://jobs.bytedance.com/campus/position/7668635915050912005/detail)
- 非空 facts：`job_type, locations, graduation_years, education_requirements`
- clauses：`required=6`、`preferred=0`、`mention=7`
- 已知问题：按规范将‘了解’条款标为 mention，不提升为 required。
- [ ] 九个 facts 的值、空值和事实强度正确
- [ ] required / preferred / mention 没有混淆
- [ ] all_of / any_of / allow_other 的作用域正确
- [ ] experience qualifier 没有错误传播或丢失
- [ ] 每段 source_text 连续、逐字一致且足以支持结论
- 自动确认：[x] 三条“了解”要求保持 mention，具体技术和 Agent 应用名称只作 examples
- 复核结论：`保持；完整复核未完成`
- 修改或讨论说明：用户授权无争议条目直接确认；2027届、本科及以上及两类实际经验保持 required。
