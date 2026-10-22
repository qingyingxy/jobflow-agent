# AI Campus Core Parser v38 random dev-5 result

## Sample

Five cases were selected from the 21 owner-reviewed, non-holdout development
cases by ascending `SHA-256(seed|case_id)`, using seed
`v37-random-dev5-2026-09-03`.

| Case | Position | Source |
| --- | --- | --- |
| `campus-ai-024` | 豆包大模型 Agent Harness 算法工程师 - Data AML | [ByteDance](https://jobs.bytedance.com/campus/position/7668635915050912005/detail) |
| `campus-ai-126` | AI Native 移动开发工程师-懂车帝（2027 届校招） | [懂车帝](https://dcar.jobs.feishu.cn/campus/position/7659806674613750059/detail) |
| `campus-ai-080` | 【2027 届校招】AI Infra 工程师 | [阶跃星辰](https://nwd4iy9rd2s.jobs.feishu.cn/campusofSpiritAI/position/7672029899397744902/detail) |
| `campus-ai-023` | Agent 工程师 - 抖音用户增长 | [ByteDance](https://jobs.bytedance.com/campus/position/7667419628440242485/detail) |
| `campus-ai-001` | 算法工程师（大模型/智能体方向） | [OPPO](https://careers.oppo.com/university/oppo/campus/post/1799) |

The sample contains no sealed holdout cases. It is a reproducible development
regression sample and is not claimed to be unseen.

## V37 baseline

Parser v37 ran once, serially, with thinking disabled, zero model retries, and
zero Parser repairs.

- parse success: `4/5` (`80%`);
- generation duration: `13,771.75 ms`;
- all-case five-field Macro-F1: `0.6602`;
- successful-only five-field Macro-F1: `0.7373`.

`campus-ai-080` returned complete JSON but failed Schema validation because one
clause used `any_of` with only one skill. This is a generic wire-compatibility
failure: a one-item choice is logically an ordinary single-skill requirement.

## V38 comparison

Parser v38 added only a generic fallback that converts singleton `any_of` to
`all_of` and records `unsupported_any_of_relation`. It reused the exact five
cases and labels under the same run policy.

- parse success: `5/5` (`100%`);
- generation duration: `13,314.27 ms`;
- `finish_reason=stop`: `5/5`;
- non-empty JSON content: `5/5`;
- five-field Macro-F1: `0.7255`;
- skill detection F1: `0.5934`;
- skill concept F1: `0.6029`;
- skill concept strength Macro-F1: `0.6115`;
- `any_of` positive accuracy: `33.3%`;
- `any_of` false-positive rate: `0%`;
- qualifier F1: `0.1111`.

The v38 change fixed the structural failure without retries. Semantic quality is
still moderate: alternative groups and experience qualifiers remain the weakest
dimensions. Further tuning on these same five cases would risk overfitting and
should not be reported as generalization.

## Artifact integrity

| Artifact | SHA-256 |
| --- | --- |
| Random selection | `8433343d8fce01b209e726efc8ffd03e62994452dba13f95e575aae06b1a7222` |
| V37 execution freeze | `e5f77018d31df58c428ce720ceb7b0f2e63a7464bf2b61c7541630a86e8871d3` |
| V37 predictions | `3975d4ec177f7c783bf6d951016fe9d241f9e081a44d959782eefa6f43f34d70` |
| V37 report | `4d928414967da1101a77d4c6b73db8e0772dcad211de42b9f2aae307effa48a0` |
| V37 successful-only report | `c0d650555392292b10fa613dbef769d1bb49d882d13be9cd96f833d1c0eebf46` |
| V38 execution freeze | `45d2c4a8d5ea03d0f41fb728c5076f527477df24c65467b4449b9b28c126d6c4` |
| V38 manifest | `4411a4357044f10c9af106561826d839e9dd8f950fa723fe07ddd38fef325547` |
| V38 predictions | `8456cf7c22f383b364b75fba10b8f39257a230b70abbf3c79a7212eb15c02fc5` |
| V38 checkpoint | `c63be6aefb9891cb8aac38648c35d5d1009b3276c5864940da9abf204a49b913` |
| V38 report | `48c07f5b81533a2b2f7c713fbea513c7e9bd35fd0b6bb33fece2b3a7a3df107b` |
| V38 successful-only report | `947f727daea74f5924ce0a6cf8dbc2d8a8b8e841c11c6483be160adbfa18eaad` |

No v37 or v38 API request in this comparison may be repeated or overwritten.
