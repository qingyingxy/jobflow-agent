# AI Campus Core Parser v38 random dev-5 plan

Parser v38 keeps Prompt v23, Schema v10, skill ontology v4, and the exact five
cases selected by `v37-random-dev5-2026-09-03`.

It adds one generic compatibility rule: an `any_of` relation with fewer than two
skills is normalized to an ordinary single-skill requirement with a warning.
This is logically equivalent for one candidate and prevents one malformed
clause from invalidating the complete JD response.

The comparison is serial, disables thinking, and permits zero model retries and
zero Parser repairs. It is a development regression test, not an unseen or
final evaluation.
