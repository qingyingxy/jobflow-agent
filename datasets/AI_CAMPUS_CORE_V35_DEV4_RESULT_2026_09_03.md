# AI Campus Core Parser v35 same-four comparison

## Outcome

Parser v35 retained Prompt v23, Schema v10, skill ontology v4, the exact four
v34 public JD inputs, and their frozen owner-reviewed labels. The transport
change explicitly disabled DeepSeek thinking and added non-sensitive response
diagnostics.

The synthetic canary succeeded on its only run:

- valid prediction: `1/1`;
- generation duration: `642.02 ms`;
- `finish_reason=stop`;
- prompt/completion tokens: `714/33`;
- reasoning content: absent;
- output: campus, Beijing, and required Python, all correct.

The same-four comparison then ran once, serially, without model retries or
Parser repairs:

- valid predictions: `1/4` (`25%`);
- total generation duration: `13,926.78 ms`;
- timeout and `length` failures: `0`;
- `structured_output_invalid`: `3`.

This resolves the v34 empty-output failure: total duration fell from about
`140.4` seconds to `13.9` seconds and all calls reached JSON decoding. It does
not yet establish acceptable end-to-end Parser quality.

## Remaining failures

The three rejected JSON objects contained six empty `skills` arrays and ten
unsupported `qualifier` values. Schema v10 correctly rejected those clauses,
but Parser v35 discarded the rest of each otherwise decoded response. Failed
validation records also lost the transport diagnostics after the model client
returned, which prevents retrospective token inspection for those three cases.

The one structurally valid case was `external-dev-v34-002`. Its successful-only
five-field Macro-F1 was `0.4205`; this is diagnostic, not a headline metric.
It correctly identified campus recruitment and recalled all labeled required
skills, but overclassified responsibility-section and weak-knowledge mentions
as required skills, did not construct the reviewed `C++/Python` choice group,
and retained province-qualified location strings.

The all-case Macro-F1 is `0.1388`, combining three structural failures with the
single semantic prediction. It must not be reported as semantic accuracy.

## Artifact integrity

| Artifact | SHA-256 |
| --- | --- |
| V35 pre-run freeze | `12c7a464b2c93b9834c1c08d291126e4980bf2eaeab617d191ec8f5ea40db539` |
| Canary predictions | `251f310af59b868712b7cc8422e1f591c6bcaab30821e71bac101c253a3b22a9` |
| Canary checkpoint | `1eea9d9128379c48499c83c260c04ad539ade24e8767a027d6b91b59fb2cb717` |
| Four-case predictions | `972fa9333771606dafbeba763cd438f2ba4c63f11b68e15c5f12a95555226b16` |
| Four-case checkpoint | `61830877570d4f070bd4bcb83dee4df1a711e1daaa820a6398f032ef6a468d7f` |
| All-case report | `ce613066a2dc4d6490687d6f451d41edaf0bf6f9d183b905713adda8868aea9a` |
| Successful-only report | `4a23498d1c9e35553b1e4989625d377efd7acfd26e99956b8f60ad7983490a44` |

No v35 request may be repeated or overwritten. Any compatibility or semantic
change requires a new Parser version and separately named artifacts.
