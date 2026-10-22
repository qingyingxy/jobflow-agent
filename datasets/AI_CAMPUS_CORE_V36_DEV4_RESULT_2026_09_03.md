# AI Campus Core Parser v36 same-four comparison

## Outcome

Parser v36 retained Prompt v23, Schema v10, skill ontology v4, and the exact
four owner-reviewed public JD inputs. The run was serial, with DeepSeek thinking
disabled, zero model retries, and zero Parser repairs.

- valid predictions: `2/4` (`50%`);
- generation duration: `13,566.35 ms`;
- timeout and `length` failures: `0`;
- structured-output failures: `2`;
- all-case five-field Macro-F1: `0.3859`;
- successful-only five-field Macro-F1: `0.6000`.

Both failed cases (`external-dev-v34-001` and `external-dev-v34-003`) returned
complete JSON, but contained an `any_of` relation after the source policy had
downgraded the clause to `mention` or `preferred`. Schema v10 permits
qualification groups only for `required` clauses, so each whole response was
rejected.

The two successful cases exposed a separate deterministic defect: `任职资格`
was not recognized as a requirements heading. Its clauses inherited the prior
responsibility section and were downgraded to mentions, causing required-skill
recall to collapse.

These are generic Parser defects rather than API transport failures. They form
the evidence basis for v37.

## Artifact integrity

| Artifact | SHA-256 |
| --- | --- |
| V36 pre-run freeze | `6998fd95f339e852ca5918c49c8c914f8a6cfc505c8c9fb14c6d966a48a37152` |
| Four-case predictions | `2a52932966244cac72d97e2ae3e43a8b3b69b5e3395870957eb1e87aba88e31c` |
| Four-case checkpoint | `2b73d307402e4259c5c02a4d4688ecc2f09a9ed36700e7153019d04d038e353a` |
| All-case report | `da7c6ea6d5c5e54d366b04b51e06631298d8554b4740716618529be3ca619e6d` |
| Successful-only report | `ce648170c361ce7728ed47e62db9adbb5d5914eea20ddb537452d1fdcbd1122b` |

No v36 request may be repeated or overwritten.
