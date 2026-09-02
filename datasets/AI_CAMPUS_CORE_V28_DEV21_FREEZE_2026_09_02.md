# AI Campus Core Parser v28 dev-21 freeze

- Freeze date: `2026-09-02`
- Parser: `jd-core-parser-v28`
- Prompt: `jd-core-parser-prompt-v18`
- Schema: `core-job-fields-v6`
- Skill ontology: `skill-ontology-v3`
- Model: `deepseek-v4-flash`
- Labels: `ai_campus_label_overrides_v14_remaining51_dev21_reviewed.json`
- Split: `ai_campus_remaining_51_split_v1_2026_09_02.json`

## Frozen dev-21 result

| Field | F1 |
| --- | ---: |
| Job type | `1.0000` |
| Locations | `1.0000` |
| Required skills | `0.9055` |
| Required skill groups | `0.9091` |
| Preferred skills | `0.9600` |
| Five-field Macro-F1 | `0.9549` |

All 21 cases produced successful prediction records. There were no timeouts,
missing predictions, or schema failures.

## Provenance and boundary

The result uses saved real DeepSeek outputs followed by the current v28
deterministic normalization replay. The remaining 16 dev cases were generated
in one completed API batch with `jd-core-parser-prompt-v18`; the five earlier
dev cases include four reused model outputs and one v27 retry. Therefore this
result is a deterministic-normalization acceptance result, not a claim that all
21 model generations were freshly repeated after the v28 version bump.

The machine-readable predictions and full report remain under the ignored local
`artifacts/evaluation/` directory because they contain copied public job text
and detailed model output. This committed document records their aggregate
result and experimental boundary.

The sealed 30-case holdout was not inspected or executed during dev-21 tuning.
It must be evaluated once with the frozen versions above. Holdout content and
labels must not be used for additional v28 tuning.

## Holdout acceptance gate

- Five-field Macro-F1: at least `0.90`
- Required-skills F1: at least `0.85`
- Required-skill-groups F1: at least `0.85`
- Prediction success rate: at least `0.95`

If the holdout misses the gate, error classes may be documented, but further
development must use new development samples and a newly sealed holdout.
