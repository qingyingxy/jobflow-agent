# AI Campus Core Parser v32 development plan

- Parser: `jd-core-parser-v32`
- Prompt: `jd-core-parser-prompt-v21`
- Schema: `core-job-fields-v8`
- Skill ontology: `skill-ontology-v4`
- API status: authorized and completed once; no retries or replay

## Rationale

V31 failed to decode all five model responses after adding a 4,096-token Core
output limit. Because the previous client discarded response termination
metadata on JSON decode failure, the saved artifacts cannot prove truncation.
V31 remains preserved as a rejected development result.

V32 removes the Core output limit. It also records `response_id`,
`finish_reason`, response character length, and a SHA-256 digest when content
cannot be decoded. It never stores the failed response body in prediction
failure details.

## Verification and sample boundary

A mocked `finish_reason=length` response must produce deterministic diagnostic
metadata without exposing content. All existing Parser and evaluation tests
must remain green.

The API structure smoke used `campus-ai-001`, `campus-ai-011`, and
`campus-ai-015`. These are public, non-blind dev cases that were not sent
during the v31 smoke. Blind-8, sealed holdout, and all five v31 API cases were
excluded. The three cases ran serially once with model retries and Parser
validation repairs disabled. No case was replayed after failure.

## Local result

- Focused Parser/client/split tests: `65 passed`
- Full test suite: `357 passed`
- Ruff rule check: passed
- External model cases for v32: `3`, each attempted once
- Successful predictions: `2 / 3`
- Failure: `campus-ai-001` reached the 240-second outer timeout
- Full-scope skill-concept F1: `0.4821`
- Successful-only skill-concept F1: `0.6067`
- Decision: v32 is not frozen because reliability and semantic metrics are
  below the acceptance gates

See `datasets/AI_CAMPUS_CORE_V32_DEV_SMOKE3_2026_09_02.md` for the permanent
result record and artifact hashes.
