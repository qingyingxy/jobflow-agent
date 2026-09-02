# AI Campus v5 技能标签终审清单

状态：`human_reviewed_v5_skill_schema`

范围：技能差异最大的 20 条岗位。用户已于 2026-09-01 确认 A1-A8
全部采用建议方案，这 20 条的 v5 技能字段可作为当前人工复核标签。

## 字段含义

- `required_skills`：必须同时满足的直接必备技能。列表中的每一项都按硬门槛计分。
- `required_skill_groups`：必备技能的备选组。`any_of` 中满足任意一项即可；`allow_other=true` 表示原文列出的只是示例，列表外同类技能也可以。
- `preferred_skills`：原文明示“优先、加分、bonus”的技术能力，不是硬门槛。
- `skill_mentions`：原文出现但不构成直接硬门槛的技术名，包括职责段技术、仅了解项、示例名和技能组内的具体选项。

普通枚举中的“等”本身不表示候选人只需满足其中一项。没有“至少一种、任选、或”
等选择信号时，标注上位必备能力，具体技术名保留在 `skill_mentions`。因此 077 和
152 的仿真平台枚举统一标为 `机器人仿真平台` 必备，不建立 `any_of`。

## 已确认项

### A1 `campus-ai-059`

涉及字段：`required_skills`，即每一项都必须满足的直接必备技能。

原文：“熟练掌握 Python、PyTorch 等编程语言与深度学习框架”。

- 确认结果：Python、PyTorch 都计为直接必备。
- 另一种：拆成两个开放技能组，允许其他语言或深度学习框架替代。

### A2 `campus-ai-087`

涉及字段：`required_skill_groups`，即 `any_of` 任一项满足即可；`allow_other` 决定是否接受列表外同类项。

原文：“至少一种主流推理框架（TensorRT/...）”。

- 确认结果：`allow_other=true`，括号中的框架视为示例。
- 另一种：`allow_other=false`，只接受括号中列出的框架。

### A3 `campus-ai-088`

涉及字段：`required_skill_groups`，表示候选方向中满足任一项即可。

原文：“目标跟随/语义分割/图像增强等图像算法相关科研经验”。

- 确认结果：建立开放的“图像算法方向”技能组，三项为示例，也接受其他图像算法方向。
- 另一种：只标上位能力“计算机视觉”，具体方向仅放入 `skill_mentions`。

### A4 `campus-ai-092`

涉及字段：`required_skill_groups`，表示三项不是同时必需，而是满足一项即可。

原文：“扎实的三维视觉、神经渲染或生成模型基础”。

- 确认结果：作为封闭的三选一技能组。
- 另一种：三项全部作为 `required_skills`，即三项都必须满足。

### A5 `campus-ai-105`

涉及字段：`required_skill_groups`，表示六个方向满足一个或多个即可。

原文：“以下方向满足其中一项或多项即可”。

- 确认结果：建立一个包含六个上位方向的封闭技能组，方向内的方法名放入 `skill_mentions`。
- 另一种：把六个方向拆成独立标签，但会错误表达为六项同时必需。

### A6 `campus-ai-106`

涉及字段：`required_skill_groups` 与 `skill_mentions`。前者计硬门槛且任选一项即可；后者只记录原文提及，不计硬门槛。

原文：“对机器人触觉感知或接触操作有基本理解”，且位于“必须要求”。

- 确认结果：建立“触觉感知 / 接触操作”二选一必备技能组。
- 另一种：因为强度只是“基本理解”，两项都只放入 `skill_mentions`。

### A7 `campus-ai-152`

涉及字段：`required_skills` 与 `skill_mentions`。前者是必须满足的上位能力；后者记录具体算法名但不把每个算法都当成独立硬门槛。

原文：“熟练掌握 PPO、SAC、RLHF、GAE、TD(λ) 等强化学习算法”。

- 确认结果：`required_skills` 标“强化学习”，五个算法放入 `skill_mentions`。
- 另一种：五个算法全部放入 `required_skills`，即要求五项都掌握。

### A8 `campus-ai-165`

涉及字段：`required_skills`，即明确点名且必须掌握的技能。

原文：“熟练掌握 Python 等编程语言”。

- 确认结果：Python 作为直接必备技能。
- 另一种：建立 `any_of=[Python]`、`allow_other=true` 的开放编程语言组，允许其他语言替代 Python。

## 后续执行

使用 reviewed override 生成 20 条正式 manifest，并运行 Core Parser smoke test。
完整 154 条评测仍需等待本轮结果通过后再决定是否执行。
