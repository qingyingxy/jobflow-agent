# JD 解析调用优化与阶段恢复

手动解析、手动分析以及搜索后的自动分析统一通过 `src/services/analysis_runtime.py` 使用 `ProductJDExecutionParser`。默认仍为两阶段；单次调用作为显式可选模式。两个模式共用教育校验、原文引用校验、编译和本地资格判断。

普通能力匹配单独由 `EVIDENCE_MATCHING_MODE` 控制，默认 `local` 不调用匹配模型。显式启用 `semantic` 后，每个有普通要求且有经历证据的岗位另加一次批量匹配调用；有效缓存命中时为零次。以下表格只统计 **JD 解析**，不包含搜索、简历抽取和可选的能力匹配。

## 配置和调用次数

```dotenv
PRODUCT_PARSE_MODE=two_stage
PRODUCT_PROMPT_VERSION=product-jd-two-stage-v10
PRODUCT_SINGLE_CALL_PROMPT_VERSION=product-jd-single-call-v1
PRODUCT_PARSER_VERSION=product-jd-parser-v8
```

将 `PRODUCT_PARSE_MODE` 改成 `single_call` 并重启后端即可切换。实际 parser 版本会追加 `-single-call`，使用单独的 prompt 版本，完整解析缓存不会跨模式复用。此次未修改本地 `.env` 的模式，运行默认仍为两阶段。

| 路径 | 正常模型调用次数 |
| --- | ---: |
| 两阶段首次解析，有要求 | 2 |
| 两阶段首次解析，无要求 | 1 |
| 两阶段第一阶段已保存，重试第二阶段 | 1 |
| 单次模式首次解析 | 1 |
| 完整解析缓存命中 | 0 |

每个模型阶段默认最多一次校验修复。单次模式会重发完整组合请求，不会暗中回退两阶段。这里统计 `client.generate` 的逻辑调用；生产客户端内部的 HTTP 重试可能产生额外请求。实际成本应看 provider 的用量/账单，不能将调用次数等同于 token 或费用。

## 两阶段恢复

第一阶段抽取并通过本地校验后，立即把 `checkpoint` 写入本次 `AgentRun.validation_result` 并提交数据库，然后才调用第二阶段。快照包含抽取结果、身份指纹、原始阶段诊断和来源运行 ID。

第二阶段失败仍返回错误，不创建部分 `JobParseResult`，不输出成功匹配结论。下次用户重试解析或分析时，服务查找相同用户、岗位、正文、模型和版本的快照，重新校验后仅执行第二阶段。取消任务或进程中断也能保留已经提交的快照；它不会触发后台自动重试。

指纹包含实际抽取提示、Schema、输出上限、模型、provider、endpoint、推理配置和版本。正文、契约或模型配置变化，以及损坏的快照，都不会被复用。密钥不写入快照。查找范围为当前用户匹配的最近 50 次运行；找不到有效快照就重新抽取。

快照使用既有 JSON 字段，无需新迁移。`AgentRun.output` 仍只保存完整成功结果；沿用既有状态枚举，未完成运行不会被标记为 succeeded。恢复后的诊断只累计本次新调用，旧抽取用量保留在 `origin_attempts`，避免重复计算。此机制不提供并发请求合并或恰好一次执行保证。

## 单次模式

模型一次返回：

```json
{
  "extraction": {"facts": {}, "requirements": [], "responsibilities": []},
  "relations": {"decisions": []}
}
```

`relations.decisions` 按索引引用同一响应的 `extraction.requirements`。本地依次校验抽取内容、完整索引、AND/OR、教育谓词及同分支证据，再编译为与两阶段相同的输出结构。完整 Schema 同时写入 system 消息，兼容当前 `json_object` 接口。

两个模式仍然只能验证结构和证据约束，无法仅靠 JSON 合法性证明模型理解正确。因此模式选择需要独立核对关系、范围和最终资格结果。

## 真实模型小规模对照：2026-10-08

新建的四条合成开发样例在调用前完成标签及文件哈希记录，未使用原冻结 test-100。使用同一 `gpt-5.6-terra`、medium、json_object，交替执行模式，每模式每条一次，不使用解析缓存。每请求超时 60 秒、每条每模式总预算 120 秒、HTTP 重试 0、校验修复最多 1 次。单次输出上限 12000；两阶段分别 4096 和 8000。

原始实验采用 parser-v7，结果保持原样：

| 指标 | 两阶段 | 单次调用 |
| --- | ---: | ---: |
| 成功得到合法解析 | 4/4 | 4/4 |
| 全部预设语义/资格检查通过 | 3/4 | 3/4 |
| 模型调用总数（含修复） | 9 | 4 |
| 四条总耗时 | 68.95 秒 | 52.47 秒 |
| 输入 token | 43,012 | 44,289 |
| 输出 token | 1,621 | 1,605 |

本次单次模式总耗时约少 24%，但总 token 略高，不能据此声称更省费用。样本量和重复次数不足以证明准确率持平或稳定提速。

唯一失败用例在两个模式上相同：模型正确提取“本岗位面向2028届毕业生”，正确区分申请硕士与历史本科，但本地届别分类器不认识“本岗位”前缀，导致合格/不合格都变成待确认。已为“本/该岗位/职位”添加有界前缀支持，同时保留地区、否定和附加条件的保守判断。修复前分类器 SHA-256 为 `65790533af471c957308d03fea1f9cd60ca8f2782095ddc7d1f3378b9997a5a8`。

修复后只回放已经保存的输出，两个模式均通过 4/4 预设检查，新增模型调用为 0。该结果是已见开发样例的本地回放，不是新的模型评测；原始 3/4 成绩未覆盖。当前 parser-v8 和 analysis-v7 使旧的届别分类缓存失效。

报告：

- `artifacts/evaluation/product-jd-execution-smoke-v1-20261008.json`：原始请求次数、用量、耗时、预先保存标签、输出和检查结果。
- `artifacts/evaluation/product-jd-execution-smoke-v1-20261008-cohort-replay.json`：原报告哈希和本地规则修复后的零调用回放。

复现实验（会调用配置的真实模型；输出路径必须尚不存在）：

```powershell
.venv\Scripts\python.exe -m scripts.compare_product_jd_execution --live --output artifacts/evaluation/new-comparison.json
```

不加 `--live` 只写实验清单，不调用模型。对已有报告重放本地届别检查：

```powershell
.venv\Scripts\python.exe -m scripts.compare_product_jd_execution --replay artifacts/evaluation/product-jd-execution-smoke-v1-20261008.json --output artifacts/evaluation/new-local-replay.json
```

## 验证和边界

新增测试覆盖持久化后超时/校验失败/取消、独立服务会话恢复、正文/模型/provider/版本/Schema/用户变化、损坏快照、模式缓存隔离、单次校验修复、API 模式选择和本地语义计分。原 v3/v4 解析器、历史输出契约及 Macro-F1 指标代码保持不变。

最终全量后端结果：1273 passed，2 failed。两个失败仍为本轮之前已存在的 `evaluation_runner` 冻结哈希不一致（`tests/test_product_jd_test100_evaluation_receipt.py`），未更改冻结回执来掩盖差异。本轮涉及的 Python 文件 Ruff 和 `git diff --check` 均通过。

完整的真实模型留出集、多次重复实验，以及价格口径下的成本比较仍待后续执行。当前保留默认两阶段，单次模式可显式试用。
