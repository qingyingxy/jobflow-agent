# AI Campus Core Parser v35 execution plan

## Scope

Parser v35 changes only model-transport behavior and diagnostics. Prompt v23,
Schema v10, skill ontology v4, the four JD inputs, and their owner-reviewed
labels remain unchanged.

For DeepSeek Chat Completions, `LLM_THINKING_MODE=auto` resolves to the
provider-supported request field `thinking.type=disabled`. Other compatible
providers receive no thinking field unless explicitly configured. The request
continues to use `max_tokens=4096` so the canary isolates the effect of disabling
thinking instead of changing two variables at once.

## Diagnostics

Successful and invalid responses record the following non-sensitive values:

- `prompt_tokens`;
- `completion_tokens`;
- `reasoning_tokens`, when exposed by the provider;
- `reasoning_content_present` and `reasoning_content_length`;
- requested `max_tokens` and effective `thinking_mode`;
- `finish_reason`, final content length, and final content SHA-256.

Reasoning text is never persisted.

## Execution gate

First run the short synthetic canary exactly once, with model retries and
Parser repairs set to zero. Only if it returns a valid structured prediction
will v35 process the same four public JDs used by v34, once each and serially.

The v34 predictions and report remain immutable. V35 uses separately named
manifests, checkpoints, predictions, reports, and hashes. The comparison tests
whether disabling thinking fixes first-attempt reliability on the already
reviewed cases; it is not a new blind evaluation.
