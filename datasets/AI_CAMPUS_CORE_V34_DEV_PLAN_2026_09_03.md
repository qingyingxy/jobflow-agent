# AI Campus Core Parser v34 development plan

- Parser: `jd-core-parser-v34`
- Prompt: `jd-core-parser-prompt-v23`
- Schema: `core-job-fields-v10`
- Skill ontology: `skill-ontology-v4`
- API status: not authorized or run

## Objective

V33 spent `1,179,437.70 ms` on five serial requests and returned only one
valid prediction. Two cases reached the 240-second outer timeout and two
responses failed Schema v9 validation. V34 addresses response size, common
contract drift, and missing timeout diagnostics without tuning against blind-8
or the sealed holdout.

## Compact wire contract

The model now returns `clauses`, where an ordinary clause contains only `id`,
`level`, and `skills`. `relation=all_of`, `open=false`, and absent examples,
group, or qualifier use local defaults and are omitted from the response.
Optional fields are emitted only for a real alternative, example list, or
experience qualifier.

For a representative required Python clause, compact JSON is 53 characters
instead of 161 characters for the v33 fully expanded object, a `67.1%`
reduction. Schema JSON is `10.6%` smaller. The five v33 smoke inputs produce
v34 prompts between 2,551 and 3,949 characters, so input size is not the
dominant latency risk.

Core requests now set `max_output_tokens=4096`. This is a safety ceiling, not
a performance claim; a truncated response remains a typed failure.

## Compatibility boundary

- `examples: []` is normalized to absence before strict validation.
- Legacy `source_clause_id`, `strength`, `group_name`, and `allow_other` keys
  map to the compact equivalents.
- `requirement_type` maps to `level` only when the resulting value validates as
  `required`, `preferred`, or `mention`.
- Conflicting canonical and alias keys remain invalid rather than being chosen
  silently.
- Existing source-backed `any_of` and evidence checks still run after compact
  decoding.

These are generic wire-format compatibility rules. They do not contain case
IDs, company names, or dataset-specific skill corrections.

## Timeout diagnostics

Prediction records now include per-case duration. HTTP client timeouts record
`timeout_scope=http_request`, timeout stage (`connect`, `read`, `write`, or
`pool`), configured seconds, and elapsed request time. The evaluation outer
guard records `timeout_scope=case_total`. Successful responses retain provider
request duration, finish reason, and token usage when supplied.

A future API smoke should keep the HTTP timeout below the outer case timeout,
for example 210 seconds and 240 seconds, so the lower layer can report its own
failure before the outer guard cancels it.

## Offline verification

- Focused Parser, model-client, and prediction tests: `70 passed`
- Full offline suite: `368 passed`
- Ruff: passed
- New DeepSeek calls: `0`

## Next gate

V34 is not frozen. Do not replay the five v33 cases merely to improve their
score. After explicit authorization, use three to five fresh public non-blind
dev JDs, serial execution, model retries zero, and Parser repairs zero. Record
first-attempt success, per-case latency, output tokens, schema failures, and
semantic metrics separately. A useful latency gate is a maximum case duration
below 90 seconds for this small smoke; semantic scores are evaluated only when
the first-attempt success gate is met.
