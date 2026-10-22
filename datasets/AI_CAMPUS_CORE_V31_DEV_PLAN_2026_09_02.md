# AI Campus Core Parser v31 development plan

- Parser: `jd-core-parser-v31`
- Prompt: `jd-core-parser-prompt-v21`
- Schema: `core-job-fields-v8`
- Skill ontology: `skill-ontology-v4`
- Development selection: `ai-campus-v31-dev15-selection-v1-2026-09-02`
- Status: rejected after one-time dev smoke-5 structure failure

## Boundary

The 15 cases come only from the existing, human-reviewed non-blind dev-21
split. Five are explicit v30 regression cases and ten cover additional
generalization conditions. The frozen blind-8 JDs and their predictions are
excluded from selection, tuning, replay, and acceptance decisions.

This is a development set, not a holdout. Results on it may select or reject
v31 changes, but they cannot be presented as an unbiased final metric.

## V31 contract change

The model continues to own semantic classification and returns only job type,
locations, and source-backed skill clauses. Local code owns canonical skill
identity and public-field compilation.

Schema v8 adds `examples` to each clause. `skills` now contains only concepts
that inherit the clause strength; named frameworks, products, or methods that
merely illustrate a parent concept go into `examples` and deterministically
compile to `mention`. The schema also rejects `any_of` on preferred or mention
clauses because the public eligibility group represents required alternatives
only.

Core requests set a 4,096-token output ceiling. Prompt v21 removes accumulated
job-specific examples and states the annotation rules directly.

## Test sequence

1. Run schema, compiler, normalizer, and evaluation unit tests without an API.
2. If they pass, compare v30 and v31 on five non-blind dev cases with no
   automatic failure retry.
3. Run all 15 dev cases only if the first five show no structural regression.
4. Freeze v31 only after reviewing both aggregate metrics and individual error
   classes.
5. Collect a new blind set after the freeze; never reuse blind-8 as a final test.

## Provisional gates

| Metric | Minimum |
| --- | ---: |
| Prediction success rate | 0.9500 |
| Skill concept F1 | 0.7500 |
| Concept-strength Macro-F1 | 0.7000 |
| Required `any_of` positive exact accuracy | 0.7000 |
| False group creation rate | 0.1000 |

Qualifier F1 remains diagnostic until the selected dev cases receive a
complete concept-aware qualifier review. It must not be used as a release gate
against the legacy v14 labels.

## Local verification

- Full test suite: `355 passed`
- Ruff rule check: passed
- Selection integrity: 15 unique cases, all in dev-21, zero sealed-holdout
  overlap, blind-8 excluded
- External model calls: `0`

The repository-wide Ruff format check remains unsuitable as a scoped gate
because 98 pre-existing files would be reformatted. No unrelated formatting
changes were applied.

## API smoke outcome

The authorized one-time v31 smoke run was completed after local verification.
All five requests returned `model_response_invalid`; no prediction contained
scorable fields. No model retry, validation repair, checkpoint resume, or
failure replay was used. See `AI_CAMPUS_CORE_V31_DEV_SMOKE5_2026_09_02.md`.

V31 is therefore rejected before semantic evaluation and must not be frozen.
The reported zero F1 values are failure-accounting values, not estimates of
semantic classification quality.
