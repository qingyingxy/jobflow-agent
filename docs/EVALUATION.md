# M11 评测与失败案例

M11 的评测先分为两个层次：自动化阶段建立可重复的评测契约、prediction 生成、AgentRun 汇总和开发集；人工阶段再补充最终标注集、真实模型验收和完整演示。当前仓库只把开发集结果用于验证评测代码，不把它当作模型效果或简历指标。

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
| `datasets/m11_evaluation_evidence.template.json` | 合成开发集的证据上下文模板 |
| `datasets/m11_evaluation_profile.template.json` | 合成开发集的用户画像和偏好模板 |

当前 dev manifest 有 12 个合成或固定 Fixture 案例，覆盖正常、字段缺失、`unknown`、无证据、多值字段、读取失败和非法模型输出。最终评测仍需补充 30～50 条人工标注样本，并将 `split` 冻结为 `eval`；在此之前不更新 README 的效果指标。

## 2. 标注和匹配规则

- `source` 必须记录来源类型、引用位置和授权边界。当前 dev 集只使用项目自有合成文本和固定 Fixture。
- `expected.fields` 中缺少某个字段键表示该字段未标注，不计入该字段指标；显式 `null` 表示“已标注为缺失”。
- 字符串先做 Unicode NFKC、去首尾空格、大小写折叠和连续空白归一化；列表字段按集合计算，不按顺序计算。
- 字段 Precision、Recall 和 F1 使用元素级 TP/FP/FN；Macro-F1 只平均有定义的字段 F1。
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

`predict.py` 不写入岗位、申请或用户数据库。它读取 manifest 中的岗位原文，复用产品正在使用的 Parser、Eligibility Checker 和 Evidence Matcher，然后只输出 prediction JSON。先复制两个合成模板作为本地上下文文件；最终评测时需要你用自己的真实经历证据和搜索偏好替换它们，这两个本地文件已加入 `.gitignore`。

```text
Copy-Item datasets/m11_evaluation_evidence.template.json datasets/m11_evaluation_evidence.json
Copy-Item datasets/m11_evaluation_profile.template.json datasets/m11_evaluation_profile.json
uv run python -m src.evaluation.predict --manifest datasets/m11_evaluation_manifest.json --evidence datasets/m11_evaluation_evidence.json --profile datasets/m11_evaluation_profile.json --output artifacts/evaluation/m11-dev-generated-predictions.json --user-id evaluation-user
uv run python -m src.evaluation.run --manifest datasets/m11_evaluation_manifest.json --predictions artifacts/evaluation/m11-dev-generated-predictions.json --output artifacts/evaluation/m11-dev-generated-report.json --model deepseek-v4-flash --prompt-version jd-parser-prompt-v2 --database-url sqlite:///./data/jobflow.db --user-id local-user
```

如果岗位原文或经历证据包含个人隐私，不能直接提交到 Git。真实评测前必须由你确认来源授权、证据内容和是否允许作为项目材料；模型生成 prediction 可以自动完成，正确标签仍需要人工审核。

## 5. 后续最终评测流程

1. 补充人工标注岗位，并为每条样本记录原文来源、授权边界、标注说明和失败场景。
2. 保持 dev manifest 和阈值不变，另建 `split=eval` 的最终 manifest；冻结后再运行模型。
3. 保存模型、提示词、Validator、数据集版本、随机参数、运行时间和环境信息，并关联已有 `AgentRun`。
4. 运行同一条命令生成 raw/validated 报告，检查失败案例和用户可见 Unsupported Claim Rate。
5. 只有真实评测和端到端演示完成后，才把结果写入 README 或简历。
