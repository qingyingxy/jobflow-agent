# 分段教育经历与资格判断 v1

本次实现打通简历抽取、资料编辑、持久化、JD 资格解释、本地判断和证据展示。模型解释自然语言，本地代码校验结构及引用并执行条件；没有新增用于匹配的模型调用。

后续运行入口已升级到 `ProductJDExecutionParser`（默认 parser-v8，两阶段，复用本文教育编译器），并增加第一阶段持久化恢复及可选单次调用；分析版本为 `job-analysis-v7-cohort-subject`。当前配置与真实模型小规模对照见 [JD 解析调用优化](PRODUCT_JD_EXECUTION_MODES.md)。下文保留教育功能首次接入及边界修复时的版本、验证记录。

## 实际处理链路

1. `ResumeEvidenceExtractor` 的既有一次模型调用升级到 `resume-evidence-extraction-v3`。教育经历逐段输出 `education`，分别保留入学年份、毕业/预计毕业年份及日期引用，其他经历保持原结构。本地校验专业、学校和日期引用属于该段原文，还校验年份的入学/毕业角色；不能从另一学历借字段，学历名称不等于已经毕业。失败会按既有次数请求模型修复，仍失败则报告抽取失败。
2. `ResumeIngestionService` 把教育记录写入 `UserProfile.educations`。教育记录不再另存一份可独立编辑的通用经历证据。每条记录有稳定 ID、原文和来源；手动记录保留，重新导入简历替换简历来源的记录，并将完整性确认重置为 false。
3. “简历资料”页面可以分别核对本科、硕士的专业、学校、入学年份、毕业/预计毕业年份、年份类型、就读状态。自动抽取的原文只读，修改字段记录 `reviewed=true`。毕业年份另设 `graduation_year_confirmed`：直接修改毕业年份或勾选核对年份才确认它，修改专业不会顺带确认日期。修改自动记录仍保留简历来源，后续切换简历时会替换；手动添加的记录独立保留。
4. API 使用新的 `product_jd_education_parser.ProductJDParser`（parser-v6 / two-stage-v9 / extraction-v8 / relation-v7 / schema-v4）。第一阶段保留完整资格原文，第二阶段在关系判断中增加 `education` 谓词。学历、专业、分支年份必须引用该分支原文；`scope` 另引用完整 JD 中的适用范围上下文，并保存原文字符位置。原 v3、v4 解析器保持可用，供历史评测使用。
5. `education_evaluator.evaluate_education` 在同一条教育记录上同时判断学历、专业、年份和状态。主分析复用资格检查结果生成匹配状态。简单的全局毕业年份只作用于 `scope=application` 的申请学历；`historical` 的历史背景不套用全局届别，分支自己明确写出的年份仍须满足；适用范围不明时待确认。含地区、身份等附加条件的届别继续提示待确认。
6. 分析保存并展示 JD 原文与教育记录快照。资料修改使旧分析失效；分析版本升级为 `job-analysis-v6-education-scope-dates`。分析入口会从分段教育记录重新生成安全的兼容摘要，避免旧自动记录里错误的入学年份通过旧标量字段参与毕业判断。

## 核心结构（省略可选字段）

候选人：

```json
{
  "educations": [
    {"id": "edu_1", "level": "bachelor", "major_raw": "机械专业", "status": "unknown", "source_text": "本科是机械专业"},
    {"id": "edu_2", "level": "master", "major_raw": "金融专业", "status": "unknown", "source_text": "硕士是金融专业"}
  ],
  "education_history_complete": false
}
```

第二阶段给“本科要求计算机相关专业，硕士不限专业”添加的结构：

```json
{
  "education": {
    "relation": "any_of",
    "branches": [
      {
        "source_text": "本科要求计算机相关专业",
        "scope": "application",
        "scope_source_text": "本科要求计算机相关专业，硕士不限专业",
        "degree": {"operator": "eq", "level": "bachelor", "source_text": "本科"},
        "major": {"mode": "related", "values": ["计算机"], "source_text": "计算机相关专业"}
      },
      {
        "source_text": "硕士不限专业",
        "scope": "application",
        "scope_source_text": "本科要求计算机相关专业，硕士不限专业",
        "degree": {"operator": "eq", "level": "master", "source_text": "硕士"},
        "major": {"mode": "any", "source_text": "不限专业"}
      }
    ]
  }
}
```

对上面的候选人，第二个分支通过，整条资格条件通过，引用 `edu_2`。专业不限不会取消硕士学历约束。其他岗位条件仍独立检查；例如 JD 未明确届别时，现有届别检查仍可能使岗位总建议为信息不足，不能把一条条件通过描述成整份 JD 通过。

### 申请学历和历史背景

对于“面向2027届应届毕业生，要求硕士学历，本科为计算机相关专业”，第二阶段输出 `all_of`，硕士分支为 `application`，本科分支为 `historical`，两者都引用整句作为适用范围依据。候选人本科计算机 2024 毕业、硕士金融 2027 毕业时通过；硕士改为 2026 年且教育经历已确认完整时不通过，硕士年份缺失时待确认。

全局届别不能因为只有历史本科条件而被跳过。对于 `all_of`，至少一项必须约束申请学历；对于 `any_of`，每条可接受路径都必须包含申请学历约束，否则总体保留届别待确认。代码不把“最高学历”自动当作结构化分支的申请学历。

### 日期角色

```json
{
  "level": "master",
  "major_raw": "金融",
  "enrollment_year": 2024,
  "enrollment_source_text": "2024-2027",
  "graduation_year": 2027,
  "graduation_source_text": "2024-2027 预计毕业",
  "graduation_year_kind": "expected",
  "graduation_year_confirmed": false,
  "status": "enrolled",
  "source_text": "硕士 金融 2024-2027 预计毕业",
  "source": "resume_asset:v3:example"
}
```

`2020-2024` 的起点只支持入学年份，终点支持毕业年份；区间本身不证明已毕业，年份类型保持 unknown，除非另有明确实际/预计毕业表述。`2024至今` 不产生毕业年份。仅摘录 `2024` 不证明日期角色；同段存在多个冲突毕业年份时，不能通过裁剪引用来选定一个。规则支持常见中文和数字日期、明确的入学/毕业标签；没有覆盖的表达应留空或请求修复，不宣称通用时间语义解析。

自动简历记录（包括旧 v2）每次参与本地判断都会重验毕业年份依据；不合格则按年份未知处理。用户明确核对毕业年份后，以用户确认值为准，保留原文便于核对。旧记录不会在后台自动改写或重新调用模型。

## 判断边界

- `any_of` 任一分支通过即通过；`all_of` 所有分支通过才通过。
- 未填写与明确不限不同：`not_specified` 表示原文未设置该维度约束，`any` 表示明确不限，`unknown` 表示无法可靠解释。
- 未找到支持记录时，只有用户确认教育经历完整且现有记录明确均不满足，才返回 fail。字段缺失、专业无法归类、关系不确定等返回 unknown。
- 专业保留原名。`education-major-v2-positive-only` 是一份有限的正向专业映射，不是完整学科目录。对“相关专业”，精确命中或已收录的正向关联可通过；不同学科族、交叉学科或未收录名称返回 unknown，不能据此证明不符合。明确的 exact 专业限制仍可返回 fail。机械本科没有硕士时，对“计算机相关本科或专业不限硕士”返回待确认；金融硕士可使硕士分支通过。
- 本科条件不会使用硕士的专业或毕业年份。多段同层级教育均保留；旧标量字段只从唯一最高层级记录投影，有歧义则留空。
- 学校层次、同等学历、复杂日期区间等尚不能执行的限定必须保留 `unresolved=true`，不能省略后判通过。
- 适用范围由第二阶段模型根据 JD 解释，本地代码只验证结构、原文引用并执行规则，无法仅凭引用证明 scope 的语义解释一定正确。本次使用受控模型响应验证链路，没有跑真实模型准确率评测，也没有更新原有 Macro-F1。

## 兼容与迁移

迁移 `0023_education_records` 仅给画像增加教育记录 JSON 和完整性布尔字段。旧资料不自动猜测或拆成多段；尚未建立教育记录时，旧学历/专业/年份可作为一段不完整的兼容记录参与判断。已有分段记录后，旧标量接口不能单独修改学历字段，需要编辑 `educations`。

旧简历需要重新上传或激活，才会使用 v3 抽取分段教育及日期角色；也可以直接手动补充。简历来源带 v3 标记，避免旧抽取结果被当作新结构缓存命中。此次新增字段均位于教育记录 JSON 内，无须增加数据库迁移。

已用临时 SQLite 验证升级、保留旧资料与降级；本地工作区数据库已先备份再升级。测试覆盖 OR/AND、专业与年份作用域、完整性、未知状态、抽取原文校验、二阶段修复、上传替换、用户隔离和分析失效，并验证桌面及移动端编辑保存。

不包含本轮以外的搜索选择器对照实验、JD 第一阶段断点恢复或指标口径重算。

## 首版验证记录（2026-10-08）

- `python -m pytest -q --maxfail=5`：1197 passed，2 failed。两个失败均为既有 `evaluation_runner` 冻结哈希校验：`scripts/run_product_jd_baseline.py` 在本轮开始前已有修改，本轮未改该文件。冻结的原解析器、输出契约、评测指标文件哈希仍一致。
- 新增教育链路测试 25 项，包含在上述通过项中；使用 `FakeModelClient` 控制模型返回，未发起付费真实模型评测。
- `npm run typecheck`：通过。修正原 Playwright live 配置中 `reducedMotion` 的位置为 `contextOptions.reducedMotion`，行为含义不变。
- 教育编辑和工作区桌面/移动端 Playwright：4 passed。截图位于 `frontend/test-results/`。
- 本次涉及的 Python 文件 Ruff 检查通过；全仓 Ruff 仍有 23 处本轮开始前即存在于其他实验脚本/文件中的问题，未自动改动那些实验内容。
- `git diff --check` 通过。SQLite 本地备份为 `data/backups/before-education-records-20261007T170139Z.db`（已在忽略范围内），工作区数据库版本为 `0023_education_records`。

## 边界修复验证（2026-10-08）

- 全量后端：1242 passed，2 failed；仍是上述两个既有 `evaluation_runner` 冻结哈希失败，没有新增失败。原 v3/v4 解析器、`product_jd.py` 和 `product_metrics.py` 无变更。
- 新增 `tests/test_education_boundaries.py`，覆盖申请/历史学历与届别绑定、多个必要条件、混合 OR 路径、相关专业待确认、入学/毕业角色、中文/英文日期区间、开放区间、否定及冲突日期、旧 v2 自动记录、人工日期确认、模型纠错重试、范围引用字符位置及 API 保存读取。模型测试均使用 `FakeModelClient`。
- 前端 TypeScript 检查通过；教育编辑和工作区桌面/移动端 Playwright 共 4 项通过。编辑专业不会确认日期，编辑毕业年份会单独确认且不改变其他学历。核对了截图并修正确认框继承整行输入框尺寸的问题。
- 本轮修改的 Python 文件 Ruff 通过，`git diff --check` 通过。未运行真实模型评测，原 Macro-F1 不作为这些新增关系、作用域或资格结论的准确率。
- 后续仍需独立评估真实模型的 scope/日期抽取准确率；切换或重新抽取简历时保留逐字段人工修正，也仍是后续工作。
