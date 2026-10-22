# AI Campus Core Parser v39 other dev-5 result

## Scope

This non-blind development stability check excluded all five cases used by the
earlier v39 random dev-5 comparison. Before prediction, the remaining 16
human-reviewed dev cases were split by expected `any_of` presence and ranked by
`SHA-256(v39-other-dev5-2026-09-03|case_id)`. The first three positives and
first two negatives were frozen:

| Case | Stratum |
| --- | --- |
| `campus-ai-032` | `any_of` positive |
| `campus-ai-037` | `any_of` positive |
| `campus-ai-121` | `any_of` positive |
| `campus-ai-011` | `any_of` negative |
| `campus-ai-128` | `any_of` negative |

This is a development regression sample, not a sealed holdout or an unseen
generalization result.

## Run policy

The run used the unchanged Parser v39, Prompt v24, Schema v10, and skill
ontology v5. Calls were serial, with JSON mode, thinking disabled,
`max_tokens=4096`, zero model retries, and zero Parser validation repairs. Each
of the five public JDs was sent to the configured DeepSeek API exactly once.

All five calls returned non-empty JSON with `finish_reason=stop`; all five
predictions passed structural validation.

## Metrics

| Metric | Other dev-5 |
| --- | ---: |
| Parse success | 100% |
| Five-field Macro-F1 | 0.7996 |
| Skill detection precision / recall / F1 | 0.9136 / 0.7327 / 0.8132 |
| Skill concept precision / recall / F1 | 0.9383 / 0.7525 / 0.8352 |
| Skill strength Macro-F1 | 0.7345 |
| `any_of` positive exact-case accuracy | 66.7% (2/3) |
| `any_of` false-group rate | 0% (0/2) |
| Qualifier precision / recall / F1 | 1.0000 / 0.5000 / 0.6667 |

Field-level F1 was:

| Field | F1 |
| --- | ---: |
| `job_type` | 1.0000 |
| `locations` | 1.0000 |
| `required_skills` | 0.8649 |
| `required_skill_groups` | 0.6667 |
| `preferred_skills` | 0.4667 |

The result supports the v39 precision changes on a different sample: skill
concept precision was `0.9383`, all three positive cases produced the expected
option identities, and neither negative case produced a false group. It also
confirms that preferred-skill recall remains the main weakness.

## Error analysis

The only positive `any_of` case mismatch was `campus-ai-032`: all four expected
options were recovered, but the expected open group (`allow_other=true`) was
predicted as closed. `campus-ai-037` and `campus-ai-121` matched exactly,
including `allow_other`; both negative cases remained group-free.

Preferred-field errors have two sources:

- Real Parser omissions: `campus-ai-121` omitted several scheduler-domain
  abilities, including scheduling queues, resource models, affinity scheduling,
  co-location, and resource-utilization optimization.
- Representation differences: labels such as `AI Agent project` and `AI
  project` encode experience in a flat string, while v39 may emit the base
  concept plus a structured `project_experience` qualifier. Exact string F1
  penalizes that even when the concept is present.

Qualifier precision reached `1.0`, but recall remained `0.5`. This is preferable
to restoring broad qualifier inference: the next change should recover only
explicit project and open-source-practice evidence.

## API diagnostics

| Case | Prompt tokens | Completion tokens | Request time | Reasoning content |
| --- | ---: | ---: | ---: | --- |
| `campus-ai-032` | 1,432 | 330 | 1.98 s | absent |
| `campus-ai-037` | 1,355 | 328 | 2.04 s | absent |
| `campus-ai-121` | 1,317 | 391 | 2.27 s | absent |
| `campus-ai-011` | 1,276 | 422 | 2.29 s | absent |
| `campus-ai-128` | 1,356 | 341 | 1.93 s | absent |

Total generation time was `11.11 s`. No call used reasoning content or a retry.

## Artifact integrity

| Artifact | SHA-256 |
| --- | --- |
| Selection | `41568e0b2befef91a6e44cc3809809ca7298119a9375b54989f51d3bbbd225d0` |
| Execution freeze | `e0704edc3f0c70894d9981a39bea3b0db236fb29b12b4290ef665113e6f1a776` |
| Manifest | `29dc8f7932108f5d6f066dcdddac84e40ba107686b4046b0872e3d4d0aa0396a` |
| Predictions | `88131407828858863b6414f80fb33ddf07c987db450b868812656102b8dd82b1` |
| Checkpoint | `ab2d4be32da9ef207b62909417642289cb92adf87dbb6cc593fdfb116b8dce44` |
| Report | `b07eff159ca240f7287126fdc8cdfff2c784164c7565c14e03b425011d745e55` |

The API output and checkpoint must not be overwritten or rerun.
