# AI Campus Core Parser v33 dev smoke-5

- Evaluation date: `2026-09-02`
- Parser: `jd-core-parser-v33`
- Prompt: `jd-core-parser-prompt-v22`
- Schema: `core-job-fields-v9`
- Skill ontology: `skill-ontology-v4`
- Model: `deepseek-v4-flash`
- Scope: five public, human-reviewed non-blind dev JDs

## Execution boundary

The user authorized sending `campus-ai-023`, `campus-ai-027`,
`campus-ai-116`, `campus-ai-126`, and `campus-ai-142` to DeepSeek exactly
once. Requests ran serially. The model HTTP timeout and outer case timeout
were both 240 seconds. Model retries and Parser validation repairs were zero.
No checkpoint resume, failed-case replay, or second model call was performed.

No blind-8 or sealed-holdout JD was read, sent, replayed, or changed.

## Reliability result

- Generation duration: `1,179,437.70 ms`
- Successful predictions: `1 / 5` (`0.2000`)
- `campus-ai-023`: `model_timeout`
- `campus-ai-027`: `model_timeout`
- `campus-ai-116`: `structured_output_invalid`
- `campus-ai-126`: `structured_output_invalid`
- `campus-ai-142`: success with one coverage warning
- Retries and Parser repairs: `0`

The all-case five-field Macro-F1 is `0.2195`. Four empty failed predictions
contribute false negatives, so this score measures end-to-end reliability and
semantic output together. It must not be presented as the semantic accuracy
of valid v33 responses.

## Successful-only diagnostic

The following values cover only `campus-ai-142` and are not headline or
resume-ready metrics:

| Metric | Score |
| --- | ---: |
| Five-field Macro-F1 | `0.9167` |
| Required-skills F1 | `1.0000` |
| Preferred-skills F1 | `0.6667` |
| Skill-concept F1 | `0.5825` |
| Concept-strength Macro-F1 | `0.8054` |
| Qualifier F1 | `0.8000` |
| False group creation rate | `0.0000` |

Job type, location, required skills, and the negative `any_of` decision were
all exact. At the legacy string-field level, preferred output matched six
labels, omitted four, and added `LLM` and `Agent`. Concept-aware scoring
correctly recognized their project qualifiers, leaving one preferred-concept
false negative. The response also over-generated responsibility-section
mentions, which reduced skill-concept F1, and omitted indexed requirement
clause `SC041`, producing one `uncovered_requirement_clause` warning.

## Failure analysis

The two timeouts are transport/latency failures. They provide no semantic
prediction and should be investigated separately from classification quality.

`campus-ai-116` returned `examples: []` in nine semantic clauses. Schema v9
allows examples to be omitted or non-empty, so strict validation rejected the
otherwise returned structure.

`campus-ai-126` used `requirement_type` where Schema v9 requires `strength`,
and also returned empty example lists. The unknown field and missing required
field were rejected. This is a response-contract compatibility failure, not a
scored semantic prediction.

## Decision

V33 is not frozen because the first-attempt success rate misses the `1.0000`
gate. A generic v34 candidate may normalize `examples: []` to absence before
strict validation. A compatibility alias for `requirement_type` must only be
added if it maps unambiguously to `strength`; otherwise the response should
remain rejected. Timeout investigation and both changes must begin with
offline or mocked tests. These five cases cannot be called again without new
explicit authorization.

## Artifact integrity

Artifacts remain in the ignored `artifacts/evaluation` directory:

| Artifact | SHA-256 |
| --- | --- |
| Input manifest | `d86059416c11431fa3ec11ac7dda86ae1857766811d832be9d5e317950d0f85b` |
| Label review | `a9891e0bfc095a219c08e950eb3e745f42d18bf453ffd1dc30704fb639ed5d41` |
| V33 predictions | `0fdaa5e8df506e11006b0d378406c63a5e950b7470a72dbf6b0f8b9bfa971334` |
| V33 checkpoint | `46b016c7271f46aba1e29e156caa7adbf006e147241aca9ed269233ac301e61c` |
| V33 full report | `5b1cbd67be8c7007d21ed1e3c31c97759fd8c02f74f3f522e2cf11fd99163137` |
| V33 successful-only report | `d27880519df9471afcc83edec58744f6b8f8cb3331c5f1ea854be2016374faf2` |
