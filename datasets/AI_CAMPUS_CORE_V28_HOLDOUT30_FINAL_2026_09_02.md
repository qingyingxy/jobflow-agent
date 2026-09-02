# AI Campus Core Parser v28 sealed holdout-30 final evaluation

- Evaluation date: `2026-09-02`
- Parser: `jd-core-parser-v28`
- Prompt: `jd-core-parser-prompt-v18`
- Schema: `core-job-fields-v6`
- Skill ontology: `skill-ontology-v3`
- Model: `deepseek-v4-flash`
- Parser freeze commit: `ab77fde71b82dfc42673c80dcba142cf8f4457ab`
- Label freeze commit: `2c4f0a6`
- Labels: `ai_campus_label_overrides_v15_remaining51_holdout30_reviewed.json`
- Split: `ai_campus_remaining_51_split_v1_2026_09_02.json`

## Execution boundary

The 30 public JD texts were sent to DeepSeek only after the parser and labels
were frozen. No resume, contact, application, or other private data was sent.
The main run used core parser-only mode, concurrency `3`, a `300` second per-case
timeout, and a checkpoint. `campus-ai-014` timed out once and was retried alone
with `--resume --retry-failures`; successful cases were not called again.

All 30 final prediction records succeeded. There were no missing predictions,
schema failures, or final timeouts.

## Final metrics

| Field | Precision | Recall | F1 | Exact match |
| --- | ---: | ---: | ---: | ---: |
| Job type | `1.0000` | `1.0000` | `1.0000` | `1.0000` |
| Locations | `1.0000` | `1.0000` | `1.0000` | `1.0000` |
| Required skills | `0.6121` | `0.6150` | `0.6136` | `0.1000` |
| Required skill groups | `0.6250` | `0.7895` | `0.6977` | `0.7000` |
| Preferred skills | `0.5350` | `0.5714` | `0.5526` | `0.3333` |

- Five-field Macro-F1: `0.7728`
- Prediction success rate: `1.0000` (`30/30`)
- Required skills: `TP=131`, `FP=83`, `FN=82`
- Required skill groups: `TP=15`, `FP=9`, `FN=4`
- Preferred skills: `TP=84`, `FP=73`, `FN=63`
- Expected-positive group exact match: `11/17` (`0.6471`)
- False group creation: `3/13` expected-negative cases (`0.2308`)

## Acceptance gate

| Gate | Required | Actual | Result |
| --- | ---: | ---: | --- |
| Five-field Macro-F1 | `>= 0.90` | `0.7728` | FAIL |
| Required-skills F1 | `>= 0.85` | `0.6136` | FAIL |
| Required-skill-groups F1 | `>= 0.85` | `0.6977` | FAIL |
| Prediction success rate | `>= 0.95` | `1.0000` | PASS |

The sealed holdout does not pass the v28 acceptance gate.

## Error classes

1. Atomic normalization and granularity gaps. Semantically close outputs remain
   different labels, for example `HTTP协议` vs `HTTP`, `工程实现能力` vs
   `工程实现`, and `大模型API调用` vs `LLM API`. Slash compounds such as
   `LLM/VLM`, `JavaScript/TypeScript`, and `RLHF/RLAIF` were often kept as one
   item instead of split into atomic labels.
2. Parent-category versus concrete-example disagreement. The model emitted
   concrete frameworks or algorithms where the frozen labels use an explicit
   upper category, including `Transformer/GPT/BERT` vs `模型架构`, and
   `SGLang/vLLM/Megatron` vs `推理框架`.
3. Experience-strength granularity loss. Preferred project or internship
   conditions were often shortened to the base technology, such as `VLA`
   instead of `VLA项目`, or `智能制造` instead of `智能制造项目`.
4. Incorrect `any_of` construction. The model invented required groups for
   ordinary or weak clauses in `campus-ai-003`, `005`, `021`, `095`, and `149`.
   It also disagreed on openness or exact option boundaries in `019`, `118`,
   and `133`.
5. Over-extraction and unstable phrasing. Several predictions emitted generic
   abilities or copied longer surface phrases rather than stable atomic skills,
   increasing both false positives and apparent lexical false negatives.

The largest per-case difference counts were `campus-ai-149` (`39`), `062`
(`24`), `151` (`22`), `014` (`18`), and `039` (`16`). These are diagnostic
counts across required, group, and preferred fields, not additional metrics.

## Artifact integrity

- Predictions SHA-256:
  `a52fc4ee79920d389408740b5f2168b347137c222138b71e11ebc6f5830e3583`
- Report SHA-256:
  `0b34d8df65d1f29c9ca51059c4cf0ac49299ff204fe282b47a260a4bd96a11bd`

The detailed prediction and report files remain under ignored local
`artifacts/evaluation/` paths because they contain copied public JD text and
per-case outputs.

## Holdout policy after evaluation

Parser v28, prompt v18, schema v6, ontology v3, and label v15 must not be tuned
or silently revised against this holdout. No post-hoc corrected score is
reported. Further parser development must turn the error classes above into
general rules using new development samples, then seal a new untouched holdout
for the next final evaluation.
