# AI Campus Core Parser v34 dev-4 result

## Outcome

The four owner-reviewed public development JDs were frozen before prediction
and sent to the configured DeepSeek API exactly once with the frozen contract:

- Parser: `jd-core-parser-v34`
- Prompt: `jd-core-parser-prompt-v23`
- Schema: `core-job-fields-v10`
- Skill ontology: `skill-ontology-v4`

The run produced `0/4` successful predictions and four
`model_response_invalid` failures. No request timed out, and no retry, repair,
resume, or failed-case replay was performed.

## Failure classification

All four API responses ended with `finish_reason=length`, returned zero
characters of final content, and therefore contained no JSON for the Parser to
validate. The SHA-256 of each empty response body was
`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`.

Per-case durations were:

| Case | Duration | Result |
| --- | ---: | --- |
| `external-dev-v34-001` | 34,668.40 ms | `model_response_invalid` |
| `external-dev-v34-002` | 36,966.28 ms | `model_response_invalid` |
| `external-dev-v34-003` | 32,903.88 ms | `model_response_invalid` |
| `external-dev-v34-004` | 35,849.59 ms | `model_response_invalid` |

Total generation duration was `140,393.20 ms`. This is a model generation or
output-budget failure, not an HTTP timeout and not evidence that the four
semantic predictions were wrong.

## Metric interpretation

The generated all-case report contains `0.0000` field and skill scores because
failed predictions are represented as empty outputs. Those scores are useful
for end-to-end reliability accounting only. They must not be presented as the
semantic accuracy of Parser v34 because there are zero successful predictions
from which semantic quality can be measured.

For this run, the reportable results are:

- first-attempt parse success rate: `0/4 = 0%`;
- timeout rate: `0/4 = 0%`;
- invalid model response rate: `4/4 = 100%`;
- semantic field, skill, qualifier, and `any_of` metrics: unavailable.

## Reproducibility

Frozen inputs and contract:

| Item | SHA-256 |
| --- | --- |
| Frozen labels | `b3d50f3ce51646f7cf46148985fa6f3f4563d9595d4af19d7bc1899d4b78274a` |
| Raw public JD source | `31e65094b7b7cb9fff76f84bf8bbbb15f04ba9615b36b446fd58f4cf3586298c` |
| Evaluation manifest | `13e7bee638c10aa314f6cb2622213d984c27bd1088cc9286e032f85d7214edc6` |

Run artifacts:

| Item | Size | SHA-256 |
| --- | ---: | --- |
| Predictions | 2,506 bytes | `380695be529609776e46d715dff5c31ceca042e8ece93728e5a7171eda6970b5` |
| Checkpoint | 2,409 bytes | `85fe9e85a003bcaa28c4529ffba2e9eff785233bc040142ea747b7b62d3e4358` |
| Evaluation report | 10,592 bytes | `01292259b442e370e0235c0dde24a151168b09f63570f30a0ab6ee61d314884a` |

The freeze manifest remains unchanged after the run. Its
`prediction_status=not_generated_at_freeze_time` value describes the state at
the moment of freezing, not the current run status. The selection ledger is the
authoritative post-run status record.

## Verification note

Before the API run, focused Parser and evaluation tests passed (`81 passed`).
The full suite produced `364 passed, 4 failed`; the four failures were existing
`/parse` and `/analyze` workflow integration failures and did not change the
frozen Parser contract. They remain a separate repository issue.

Any attempt to change output limits, model parameters, prompts, schemas,
normalization, or parsing behavior requires a new version and a separately
authorized run. This frozen four-case run must not be overwritten or retried.
