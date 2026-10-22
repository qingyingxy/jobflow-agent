# AI Campus Core Parser v34 freeze

- Freeze time: `2026-09-03T09:45:05+08:00`
- Parser: `jd-core-parser-v34`
- Prompt: `jd-core-parser-prompt-v23`
- Schema: `core-job-fields-v10`
- Skill ontology: `skill-ontology-v4`
- Evaluation scope: four public, owner-reviewed non-blind development JDs

## Frozen boundary

The machine-readable freeze manifest is
`datasets/ai_campus_v34_dev4_freeze_manifest_v1_2026_09_03.json`. It records
SHA-256 hashes for the Parser, prompt/schema implementation, skill ontology,
model transport, frozen labels, local raw source, and evaluation manifest.

The frozen label file is
`datasets/ai_campus_v34_dev4_label_freeze_v1_2026_09_03.json` with SHA-256
`b3d50f3ce51646f7cf46148985fa6f3f4563d9595d4af19d7bc1899d4b78274a`.
All four cases were reviewed before prediction. The repository owner confirmed
A, C, and D as proposed, and revised B so `C++/Python` is a closed required
`any_of` group while Linux and programming fundamentals remain jointly
required.

No Parser, prompt, schema, ontology, normalization, raw input, or label content
may change during this run. Any change requires a new version and separately
named artifacts.

## Authorized run

The user authorized sending only these four public JD texts to the configured
DeepSeek API and running the frozen Parser once. The run policy is:

- serial execution with `concurrency=1`;
- model retries `0`;
- Parser validation repairs `0`;
- HTTP timeout `180` seconds;
- outer per-case timeout `210` seconds;
- no checkpoint resume and no failed-case replay.

Blind-8 and the sealed holdout are excluded. Candidate data is not read or
transmitted, and no application action is performed.

## Interpretation

This is a small non-blind development evaluation, not a final holdout result.
First-attempt success and latency must be reported separately from semantic
metrics. Failed predictions remain in the all-case report; a successful-only
report may be added only as a clearly labeled diagnostic.
