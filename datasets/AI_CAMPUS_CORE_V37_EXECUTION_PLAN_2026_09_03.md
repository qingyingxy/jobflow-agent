# AI Campus Core Parser v37 execution plan

## Scope

Parser v37 keeps Prompt v23, Schema v10, skill ontology v4, and the same four
owner-reviewed public JD inputs. No new JD is introduced.

The version contains two generic deterministic fixes derived from v36:

- recognize `任职资格`, `职位资格`, and `岗位资格` as requirement headings;
- convert `any_of` to an ordinary enumeration when the final clause strength is
  `preferred` or `mention`, because qualification groups are defined only for
  required clauses.

## Gate and run policy

- Core Parser focused tests and Ruff must pass.
- The existing four unrelated Fake-model workflow failures are recorded but do
  not block this parser-only comparison.
- DeepSeek thinking is disabled.
- The run is serial, with zero model retries and zero Parser repairs.
- Each of the same four public JDs is sent once. Existing v34-v36 artifacts are
  immutable and must not be overwritten.
