# AI Campus Core Parser v39 random dev-5 result

## Scope and run policy

Parser v39 reused the exact five public development JDs and frozen labels from
the v38 random dev-5 comparison:

- `campus-ai-024`
- `campus-ai-126`
- `campus-ai-080`
- `campus-ai-023`
- `campus-ai-001`

The user explicitly authorized sending these five public JDs to the configured
DeepSeek API once. The run used Parser v39, Prompt v24, Schema v10, and skill
ontology v5, with JSON mode, thinking disabled, `max_tokens=4096`, concurrency
`1`, a 60-second HTTP timeout, a 90-second case timeout, zero model retries,
and zero Parser validation repairs. No failed-case reruns were allowed.

This is a same-sample development comparison. These cases informed v39
development, so the result must not be reported as unseen generalization.

## Result

All five calls returned non-empty JSON with `finish_reason=stop`. All five
predictions passed structural validation, and no call was retried.

| Metric | v38 | v39 | Delta |
| --- | ---: | ---: | ---: |
| Parse success | 100% | 100% | 0 pp |
| Five-field Macro-F1 | 0.7255 | 0.7900 | +0.0645 |
| Skill detection F1 | 0.5934 | 0.7022 | +0.1088 |
| Skill concept F1 | 0.6029 | 0.7200 | +0.1171 |
| Skill strength Macro-F1 | 0.6115 | 0.6854 | +0.0739 |
| `any_of` positive exact-case accuracy | 33.3% | 33.3% | 0 pp |
| `any_of` false-group rate | 0% | 0% | 0 pp |
| Qualifier F1 | 0.1111 | 0.3333 | +0.2222 |
| Mention false positives | 69 | 24 | -45 |
| Qualifier false positives | 15 | 3 | -12 |

The five-field components were:

| Field F1 | v38 | v39 | Delta |
| --- | ---: | ---: | ---: |
| `job_type` | 1.0000 | 1.0000 | 0.0000 |
| `locations` | 1.0000 | 1.0000 | 0.0000 |
| `required_skills` | 0.5205 | 0.7667 | +0.2461 |
| `required_skill_groups` | 0.2500 | 0.6000 | +0.3500 |
| `preferred_skills` | 0.8571 | 0.5833 | -0.2738 |

The main intended precision fix worked: generic responsibilities and business
objects produced far fewer mention false positives. Required-strength F1 rose
from `0.6105` to `0.8409`, and mention-strength F1 rose from `0.2953` to
`0.5487`. Preferred-strength F1 fell from `0.9286` to `0.6667`, so the result
does not support a claim that every strength class improved.

## `any_of` diagnosis

V39 recovered the option identities for all five expected groups across the
three positive cases. The official metric is stricter than option recall: a
positive case counts only when its complete set of normalized groups, including
each group's `allow_other` value, is exactly correct.

- `campus-ai-023` matched exactly.
- `campus-ai-080` recovered both groups, but marked the closed `C++ or Python`
  group as open (`allow_other=true`).
- `campus-ai-001` recovered both groups, but marked the closed `generative
  algorithms or reinforcement learning` group as open.

Therefore the positive exact-case accuracy remains `1/3`, even though no
expected option group is absent. The next targeted change should distinguish
closed direct alternatives from open category examples; it should not further
relax group creation.

## API diagnostics

| Case | Prompt tokens | Completion tokens | Request time | Reasoning content |
| --- | ---: | ---: | ---: | --- |
| `campus-ai-024` | 1,571 | 337 | 2.46 s | absent |
| `campus-ai-126` | 1,517 | 286 | 2.25 s | absent |
| `campus-ai-080` | 1,352 | 511 | 2.74 s | absent |
| `campus-ai-023` | 1,554 | 288 | 1.93 s | absent |
| `campus-ai-001` | 1,393 | 502 | 13.18 s | absent |

Total prediction generation time was `23.34 s`. Diagnostics confirm
`thinking_mode=disabled`, no reasoning content, and an actual output cap of
4,096 tokens for every call.

## Artifact integrity

| Artifact | SHA-256 |
| --- | --- |
| V39 execution freeze | `777ee12447e5826c3d2d35de5eeb12ee1f3df09fe209b51245ee3286fce7b439` |
| V39 manifest | `921c666a9dd2c26a56c448e985d2949ed8bf656fd38f9ff209147307ff19f05c` |
| V39 predictions | `8e038af3c25bbf56aa704ba016b5d8806170d5ef3f53518f7dd0e554c6492870` |
| V39 checkpoint | `2c4ed9e1395da7ed4a412d5fe29a5eee54d598cd7327bc3dde829774c6f60a22` |
| V39 report | `023999cebaa3df6f8271e4ef6ad4ea61dff6e37380624cd030a159a9506de35b` |

The v39 API output and checkpoint must not be deleted, overwritten, or rerun.
