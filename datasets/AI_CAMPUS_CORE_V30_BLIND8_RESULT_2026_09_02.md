# AI Campus Core Parser v30 blind-8 result

- Evaluation date: `2026-09-02`
- Evaluation type: one-time unseen evaluation
- Cases: `8` human-reviewed public JDs
- Label version: `ai-campus-blind8-labels-v2-human-reviewed-2026-09-02`
- Label freeze commit: `b869df6aa8b53067424801fccb63eb1778b4e95d`
- Parser: `jd-core-parser-v30`
- Prompt: `jd-core-parser-prompt-v20`
- Schema: `core-job-fields-v7`
- Skill ontology: `skill-ontology-v4`
- Model: `deepseek-v4-flash`

## Evaluation boundary

The eight labels were reviewed without inspecting v30 predictions. The frozen
configuration was then run once, serially, with a 240-second per-case timeout.
Failed cases were not retried. The blind JDs must not be sent to the model
again, and neither v30 nor reviewed label v2 may be changed in response to
these results.

Any subsequent parser work must use a new version, beginning with v31, and be
developed only on non-blind development samples. A later unbiased evaluation
requires a newly collected and independently reviewed blind set.

## Execution result

- Total prediction duration: `1,537,581.49 ms` (about 25.6 minutes)
- Successful predictions: `6 / 8`
- Success rate: `0.7500`
- Failures: `2` `model_timeout`
- Timed-out cases: `blind27-004`, `blind27-006`
- Retries: `0`

## Metrics

The complete-set metrics count both timeouts as prediction failures and are
the primary result. Successful-only metrics are diagnostic and must not be
reported without the `6 / 8` scope.

| Metric | Complete 8 cases | Successful 6 cases |
| --- | ---: | ---: |
| Five-field Macro-F1 | 0.5201 | 0.6158 |
| Job type F1 | 0.8571 | 1.0000 |
| Locations F1 | 0.8333 | 1.0000 |
| Required skills F1 | 0.4304 | 0.5152 |
| Required skill groups F1 | 0.1538 | 0.2000 |
| Preferred skills F1 | 0.3256 | 0.3636 |
| Skill concept F1 | 0.4987 | 0.5975 |
| Concept-strength Macro-F1 | 0.4143 | 0.4970 |
| Qualifier F1 | 0.0000 | 0.0000 |
| `any_of` positive exact accuracy | 0.2000 | 0.3333 |
| False group creation rate | 0.3333 | 0.3333 |

## Observed error classes

- Required and preferred skill recall is low, especially for engineering,
  modeling, project, and domain-experience concepts.
- Parent categories and named examples are confused in both directions.
- Enumeration text is sometimes converted into a false `any_of` group, while
  real alternatives are sometimes incomplete.
- Experience qualifiers are omitted or attached to a different normalized
  concept, producing no exact qualifier matches.
- Some Chinese and English aliases are not normalized to the same concept.
- Long model responses can exceed the per-case timeout.

These are general error classes, not authorization to tune against individual
blind cases. The result is not strong enough for a public quality claim or a
resume metric.

## Artifact integrity

Raw evaluation artifacts remain under the ignored `artifacts/evaluation`
directory. They are preserved locally and identified by SHA-256:

| Artifact | SHA-256 |
| --- | --- |
| Human-reviewed label v2 | `e5100aef8dbfd1437791718b0e478414c146e2f23885ee310bac85fdb15e58be` |
| Evaluation manifest | `06ceb2b3ade343ca38d99ef0ae3487bd8fc98acb2150b278a4c53b1e00a2b44d` |
| Predictions | `fa4d158a1dbd6e2e802373c16d2970ab0825e195f3b9056ccf4013dfbbcadd1e` |
| Prediction checkpoint | `c2b6dc94a3745fab121ee80a74148dda784a9c1e84645764a06de1686904cd54` |
| Complete 8-case report | `ba3569515e27fdd4b783f3c77181d617c919ab784c1d51b4c0e5f7f09fca737b` |
| Successful-only 6-case report | `bc7c6c6b7af5a4500a1cd73cbdb83ffa5d5de4baa24fc73176044d419757be1d` |
