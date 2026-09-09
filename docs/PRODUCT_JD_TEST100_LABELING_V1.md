# Product JD test-100 独立标注说明

> 日期：2026-09-08
> 当前状态：28 个争议岗位已复核，标签已冻结，正式评测已完成一次

## 数据组成

- 30 条：复用已经人工确认关系与候选项边界的 sealed-30 标签。
- 54 条：原严格样本池中未进入 development-70 的岗位。
- 16 条：冻结前新增的字节跳动 2027 届官方岗位。
- development-70 与 test-100 的岗位 ID 和 URL 均不重叠。

## 独立标注

- 模型：`gpt-5.6-terra`
- 思考深度：`medium`
- 独立标注提示：`product-jd-independent-annotation-v3`
- 70 条 API 草案：70 条成功，0 条失败，共 75 次模型调用。
- 标注脚本没有导入、实例化或调用 `ProductJDParser`，也没有读取测试集预测。

标注结果依次通过 Pydantic 契约、逐字原文证据和事实原子值校验。校验失败时只允许
Terra 根据错误信息修复一次，本地代码不会自动判断或改写条件语义。

## 人工复核

自动筛选只用于决定哪些内容送人工检查，不会修改 API 草案。28 个岗位已经全部完成核对，
主要包括 API 主动保留的不确定关系、明确“至少一种/至少一门”却没有分的条件、泛化软素质
和职责空值。其中 9 组已经由人工确认关系、再由 Terra 提取逐字候选项边界。

复核入口：`docs/PRODUCT_JD_TEST100_REVIEW_CHECKLIST_V2.md`。

审核结果已机械应用到独立的 reviewed-100 文件，并通过 Pydantic、逐字证据、来源哈希和
ID 校验。标签与运行时代码已冻结，随后使用 `product-jd-two-stage-v6` /
`product-jd-parser-v3` 在 100 条测试集上完成了唯一一次正式评测。结果见
`docs/PRODUCT_JD_TEST100_RESULT_V1.md`。

## 复现命令

```powershell
uv run python scripts/draft_product_jd_test100_labels.py --max-new-cases 3 --max-model-calls 6 --concurrency 2
uv run python scripts/draft_product_jd_test100_labels.py --resume --max-model-calls 160 --concurrency 3
uv run python scripts/draft_product_jd_test100_labels.py --review-only
```
