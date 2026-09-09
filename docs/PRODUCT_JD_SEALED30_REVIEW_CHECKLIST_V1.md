# Product JD sealed-test-30 人工复核清单 v1

日期：2026-09-08

## 使用方法

本清单只列出会改变 `any_of` 关系识别 F1 的 10 个分歧。请按原句实际含义判断，
不要因为 API 的答案或最终分数选择标签。回复格式可以继续使用：

```text
1 草案
2 API
3 你的修改说明
```

“草案”表示保留现有标签；“API”表示采用当前预测的关系判断。items 边界差异将在关系
裁定后单独处理，不影响这 10 项的语义选择。

## 关系分歧

### 1. `campus-ai-005`

原文：`能够提出新算法、新架构或新范式`

- 草案：`all_of`，把它视为一项完整的科研创新能力。
- API：`any_of`，候选项为“新算法 / 新架构 / 新范式”。

### 2. `campus-ai-034`

原文：`扎实的Web前端基础，熟悉HTML、CSS、JavaScript/TypeScript与HTTP协议，了解浏览器渲染与常见性能问题`

- 草案：`all_of`，整条包含共同要求，只在局部出现 JavaScript/TypeScript。
- API：`any_of`，候选项为“JavaScript / TypeScript”。

### 3. `campus-ai-038`

原文：`熟悉SQL/HQL及数据分析工具`

- 草案：`all_of`，把 SQL/HQL 视为技术组合写法。
- API：`any_of`，候选项为“SQL / HQL”。

### 4. `campus-ai-096`

原文：`有项目/开源经验（Web开发、系统设计、自动化工具）`

- 草案：`all_of`，把“项目/开源经验”作为一类完整经历。
- API：`any_of`，候选项为“项目 / 开源”。

### 5. `campus-ai-154`

原文：`熟悉 SGLang、vLLM、Megatron 等框架，有开源项目贡献或相关经验者优先`

- 草案：`all_of`，框架熟悉度是共同条件，后半句只是局部备选。
- API：拆出`有开源项目贡献或相关经验者优先`并判 `any_of`。

### 6. `campus-ai-014`

原文：`熟练掌握Python及PyTorch/TensorFlow/PaddlePaddle等深度学习框架`

- 草案：拆出框架部分并判 `any_of`，Python 是独立共同条件。
- API：整句保留并判 `all_of`。

### 7. `campus-ai-062`

原文：`熟练使用Python，了解C#/C++等工业开发语言`

- 草案：拆出 C#/C++ 并判 `any_of`，Python 是独立共同条件。
- API：整句保留并判 `all_of`。

### 8. `campus-ai-074`

原文：`熟悉 LLM/VLM 相关技术`

- 草案：`any_of`，候选项为“LLM / VLM”。
- API：未把该句提取为申请条件。

### 9. `campus-ai-081`

原文：`有相关论文产出，数据竞赛获奖经历或开源数据集贡献优先`

- 草案：`any_of`，三个成果分支满足其一即可。
- API：`uncertain`。

### 10. `campus-ai-095`

原文：`扎实的 Python/Java/Scala/C++/Go 等高级语言编程功底`

- 草案：`any_of`，五种语言满足其一即可。
- API：`all_of`，原文没有明确“至少一种”等数量词。

## 暂不裁定的 items 边界

另有 11 组关系判断一致、仅 items 边界不同，例如 `C/C++` 是一个表面项还是拆成
`C / C++`、是否保留“较强的”“经验”等修饰词。这些差异影响关系 + items 精确 F1，
但不影响更重要的关系识别 F1。先完成上面的 10 项，再生成精简边界清单。
