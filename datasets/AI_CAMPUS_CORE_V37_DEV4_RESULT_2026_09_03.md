# AI Campus Core Parser v37 same-four comparison

## Outcome

Parser v37 kept Prompt v23, Schema v10, skill ontology v4, and the exact same
four frozen public JDs and owner-reviewed labels. It added only two generic
deterministic changes:

- recognize `任职资格`, `职位资格`, and `岗位资格` as requirement headings;
- normalize a non-required `any_of` clause to an ordinary enumeration instead
  of rejecting the entire model response.

The one authorized run was serial, with DeepSeek thinking disabled, zero model
retries, and zero Parser repairs.

- valid predictions: `4/4` (`100%`), up from v36 `2/4`;
- generation duration: `15,990.65 ms`;
- `finish_reason=stop`: `4/4`;
- output content length: `1,299` to `2,607` characters;
- prompt tokens: `1,162` to `1,554`;
- completion tokens: `443` to `861`;
- reasoning content present: `0/4`;
- timeout, `length`, and structured-output failures: `0`.

The original empty-content problem is therefore resolved for this comparison.
It was a generation-budget problem caused by reasoning being enabled, not a web
page parsing problem. With thinking disabled, all four calls returned ordinary
JSON quickly enough for deterministic validation.

## Metrics

All-case and successful-only metrics are identical because all four predictions
succeeded.

| Metric | V35 | V36 | V37 |
| --- | ---: | ---: | ---: |
| Parse success rate | 25% | 50% | 100% |
| Five-field Macro-F1 | 0.1388 | 0.3859 | 0.7979 |
| Skill concept F1 | 0.1839 | 0.3981 | 0.6419 |
| Skill concept strength Macro-F1 | 0.0589 | 0.2492 | 0.6730 |
| `any_of` positive accuracy | 0% | 0% | 33.3% |

Additional v37 diagnostics:

- required-skill F1: `0.7308`;
- preferred-skill F1: `0.7586`;
- skill qualifier F1: `0.1622`;
- unsupported-claim rate: `0`.

This is a useful dev result, not a production or resume headline. The four cases
were already used to diagnose v37, and the sample is too small. Remaining errors
are semantic: over-specific task phrases, canonical-name differences, missed
alternative groups, and experience-qualifier scope. Repeatedly tuning against
these same four labels would no longer measure generalization.

## Artifact integrity

| Artifact | SHA-256 |
| --- | --- |
| V37 pre-run freeze | `cee7ff4018a2abd907e2d4a059de449b41f61962dee578442779286747a7731f` |
| Frozen comparison manifest | `fa2191406485a6eb1464c9ccf0eeebd30fa7c50577b62d54236872bcc3f48aee` |
| Four-case predictions | `1963c65eedf04b7da8518509eb5679a566fcc8571d0e08facec0b2c226bf5d8a` |
| Four-case checkpoint | `3030a1814148421a4c9983c5aef57862e1a5693f0a288ed7b591cc5a59f5a970` |
| All-case report | `59bb67c9c44a6c9d6fe6f93cf5fe3a4ce4f0d95eb032a2c22dfb8a3064b3bd89` |
| Successful-only report | `946de01cfe5ec3aedec92321dd94226c4b2fbddc1404d5cc1229d354adb9ad91` |

No v37 request may be repeated or overwritten. Any further behavior change must
use a new Parser version and separately named artifacts.
