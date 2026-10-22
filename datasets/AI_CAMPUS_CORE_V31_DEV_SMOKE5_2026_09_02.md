# AI Campus Core Parser v31 dev smoke-5

- Evaluation date: `2026-09-02`
- Parser: `jd-core-parser-v31`
- Prompt: `jd-core-parser-prompt-v21`
- Schema: `core-job-fields-v8`
- Skill ontology: `skill-ontology-v4`
- Model: `deepseek-v4-flash`
- Scope: five public, human-reviewed non-blind dev JDs

## Execution boundary

The user authorized sending `campus-ai-008`, `campus-ai-024`,
`campus-ai-037`, `campus-ai-078`, and `campus-ai-147` to DeepSeek once with
v31. Requests ran serially with a 240-second outer case timeout. Model retries
and parser validation repairs were both set to zero. No checkpoint resume or
failure replay was performed. V30 was not called again; its saved predictions
are used only as an offline reference.

No blind-8 or sealed-holdout JD was read, sent, replayed, or changed.

## Result

- Generation duration: `164,652.26 ms`
- Successful predictions: `0 / 5`
- Failure code: `model_response_invalid` on all five cases
- Scorable semantic predictions: `0`
- Retries: `0`

The deterministic report assigns zero to aggregate F1 when every prediction
is a failure. Those zero values are pipeline failure accounting and must not
be interpreted as semantic accuracy. V31 did not reach semantic evaluation.

For context, the saved v30 run on the same development cases had a 1.0000
success rate, 0.7574 skill-concept F1, and 0.8286 concept-strength Macro-F1.
V31 is rejected as a structure/runtime compatibility regression.

## Diagnosis boundary

The HTTP requests completed, but the returned content could not be decoded as
a JSON object. The current client does not persist `finish_reason`, response
length, or a response-content digest on decode failure, so the artifact cannot
prove whether the content was truncated or malformed.

The new 4,096-token output limit is the leading hypothesis because it is the
only new transport-level constraint and all five long JDs failed at the same
decode boundary. This remains a hypothesis, not a confirmed cause. The v31
cases must not be rerun merely to investigate it.

The next parser version should first add non-sensitive failure telemetry and
test truncated-output handling with a mocked transport. It should then remove
or revise the output cap and use different non-blind dev cases for any newly
authorized API smoke test.

## Artifact integrity

Artifacts remain in the ignored `artifacts/evaluation` directory:

| Artifact | SHA-256 |
| --- | --- |
| Input manifest | `ca025749a628224c58279a5ef510e9317c5d3d18dd0d32567a8e7946d97ef4e1` |
| V31 predictions | `73d0bbe943487898779775c749c64a1a6d3743b635b0e265cdd76aa82839e8f5` |
| V31 checkpoint | `f5658aead03c946e6061cccb95b473537e27127ca8be3928041ba4e9221c003c` |
| V31 report | `6a0d8ed59043f58669ef4a91bada3c9c013aa1f48653107c8124e6d1f5ab2b44` |
