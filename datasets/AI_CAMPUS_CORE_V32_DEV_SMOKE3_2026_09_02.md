# AI Campus Core Parser v32 dev smoke-3

- Evaluation date: `2026-09-02`
- Parser: `jd-core-parser-v32`
- Prompt: `jd-core-parser-prompt-v21`
- Schema: `core-job-fields-v8`
- Skill ontology: `skill-ontology-v4`
- Model: `deepseek-v4-flash`
- Scope: three public, human-reviewed non-blind dev JDs

## Execution boundary

The user authorized sending `campus-ai-001`, `campus-ai-011`, and
`campus-ai-015` to DeepSeek once with v32. Requests ran serially with a
240-second outer case timeout. Model retries and Parser validation repairs
were both set to zero. No checkpoint resume, failed-case replay, or second
model call was performed.

No blind-8 or sealed-holdout JD was read, sent, replayed, or changed.

## Result

- Generation duration: `576,612.49 ms`
- Successful predictions: `2 / 3`
- `campus-ai-001`: `model_timeout`
- `campus-ai-011`: success
- `campus-ai-015`: success
- Retries: `0`

Metrics over all three cases, where the timeout counts as a failed
prediction:

| Metric | Score |
| --- | ---: |
| Success rate | `0.6667` |
| Five-field Macro-F1 | `0.5029` |
| Skill-concept F1 | `0.4821` |
| Concept-strength Macro-F1 | `0.4885` |
| Qualifier F1 | `0.0000` |
| False group rate | `0.5000` |

Diagnostic metrics over the two successful predictions only:

| Metric | Score |
| --- | ---: |
| Five-field Macro-F1 | `0.6933` |
| Required-skills F1 | `0.8000` |
| Preferred-skills F1 | `0.6667` |
| Skill-concept F1 | `0.6067` |
| Concept-strength Macro-F1 | `0.6239` |
| False group rate | `0.5000` |

The successful-only table is diagnostic and is not the headline result. It
excludes a production-visible timeout and therefore cannot be used to claim
overall Parser performance. Qualifier F1 also remains diagnostic because the
legacy dev labels are not fully concept-aware.

## Error analysis

`campus-ai-011` incorrectly turned `PyTorch/PaddlePaddle` examples under the
required parent category `deep learning framework` into an `any_of` group.
The source does not contain an explicit choice signal such as “at least one”
or “any one”. This is a general ordinary-enumeration versus explicit-choice
classification error, not a case-specific exception.

`campus-ai-015` missed directly required abilities for model optimization,
model-effect analysis, training-strategy diagnosis, and data-problem
diagnosis. Its preferred prediction also used the broader concept `foundation
model` instead of the labeled `industrial foundation-model development`
experience. This is primarily a recall and granularity problem.

`campus-ai-001` timed out before producing a scorable prediction, so no
semantic error conclusion is drawn for that case.

## Decision

V32 is not frozen. Its `2 / 3` success rate and successful-only semantic
scores do not meet the acceptance gates. Any follow-up implementation must be
versioned as v33 and developed only against non-blind dev data. These three
cases must not be called again without new explicit user authorization.

The next general changes should require explicit source-language choice
signals before retaining an `any_of` group, preserve a required parent
category when listed frameworks are merely examples, and improve recall for
directly required analysis, diagnosis, optimization, and engineering
abilities. Long-response latency should be studied with mocked or new dev
cases rather than replaying this run.

## Artifact integrity

Artifacts remain in the ignored `artifacts/evaluation` directory:

| Artifact | SHA-256 |
| --- | --- |
| Input manifest | `a5c61b90831d6ca200e150cf78e881e9d88c135ca05a84a5fb99bf8f559ec553` |
| V32 predictions | `fcb570a06a01209a657dec49e4dccd5d8b9c906bcf33699dff72b943e427c123` |
| V32 checkpoint | `df88eb31b012f2408125f2e707f85fedc68d09743cd1dd743e79f5bc389987e6` |
| V32 full report | `fa120bec94c4ef8c47abe84d5cc0a6382260c10315bb30dd4ece0f8f4726af96` |
| V32 successful-only report | `53bc57d2f4a0b3b267b4e6f2b3340a35d13d0dcaf38e8f445338b23e66e72cd4` |
