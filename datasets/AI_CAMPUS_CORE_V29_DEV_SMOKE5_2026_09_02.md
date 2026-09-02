# AI Campus Core Parser v29 dev smoke-5

- Evaluation date: `2026-09-02`
- Parser: `jd-core-parser-v29`
- Prompt: `jd-core-parser-prompt-v19`
- Schema: `core-job-fields-v7`
- Skill ontology: `skill-ontology-v4`
- Model: `deepseek-v4-flash`
- Scope: five public JD cases reused from the human-reviewed dev-21 split

This is a development smoke test, not a new holdout. The five public JD texts
were sent to DeepSeek in core parser-only mode. No resume, application,
contact, candidate evidence, or other private data was read or sent.

## Cases

| Case | Main reason for inclusion |
| --- | --- |
| `campus-ai-008` | Nested direction alternative and project experience |
| `campus-ai-024` | Weak mentions and a negative `any_of` case |
| `campus-ai-037` | Open language group, project, and open-source experience |
| `campus-ai-078` | Direction group, required understanding, robot experience |
| `campus-ai-147` | Product internship, AI project, and a negative `any_of` case |

All five prediction records succeeded with no parser warnings or final
timeouts. Total wall-clock generation time was `503109.48 ms`.

## Results

The v28 row reuses saved dev-21 predictions for the same five cases and applies
the current v4 concept metrics offline. It is a diagnostic baseline, not a
fresh prompt A/B call.

| Metric | v28 saved baseline | v29 fresh call | v30 fresh call |
| --- | ---: | ---: | ---: |
| Prediction success rate | `1.0000` | `1.0000` | `1.0000` |
| Five-field Macro-F1 | `0.9015` | `0.7577` | `0.8386` |
| Required-skills F1 | `0.8727` | `0.5600` | `0.8182` |
| Required-groups F1 | `0.8571` | `0.8000` | `1.0000` |
| Preferred-skills F1 | `0.7778` | `0.4286` | `0.3750` |
| Skill-concept F1 | `0.7350` | `0.7089` | `0.7574` |
| Concept-strength Macro-F1 | `0.8045` | `0.6727` | `0.8286` |
| Qualifier F1 against legacy-derived labels | `0.7273` | `0.4000` | `0.3333` |
| `any_of` positive exact accuracy | `0.6667` | `0.3333` | `1.0000` |
| False group creation rate | `0.0000` | `0.5000` | `0.0000` |

The shorter v19 prompt did not improve semantic classification on this smoke
set. It must not be used as evidence for a resume metric or release gate.

## Error analysis

1. Required-strength scope regressed. In `078`, the requirement-section phrase
   "理解真实机器人系统中的...问题" was classified as mention. In `147`,
   directly required technical understanding, requirement analysis, logical
   decomposition, and documentation were omitted.
2. Nested alternatives regressed. In `008`, the upper direction alternatives
   were missed while option-specific examples were promoted to global required
   skills.
3. Non-required alternatives created false groups. Mention-level alternatives
   in `037` and preferred tools in `147` were emitted as `any_of`, although the
   evaluation contract only represents required eligibility alternatives.
4. Mixed qualifier scopes were incomplete. `037` retained AI project experience
   but omitted open-source experience; `147` omitted both product internship and
   AI project experience.
5. Legacy v14 labels are not sufficient for a final qualifier score. They do
   not label every development/practical experience and sometimes encode a
   generic experience as a project suffix. Qualifier evaluation needs a new
   concept-aware annotation layer before any final claim.

## Follow-up

Prompt v20 / Parser v30 has been prepared from these general error classes. It
adds requirement-section scope, required `理解`, nested-direction handling,
required-only eligibility groups, mixed-qualifier clause splitting, and direct
technical work abilities.

The first authorized v30 attempt was rejected before model generation with
HTTP `402`. After the DeepSeek balance was restored, the checkpoint was resumed
with `--retry-failures`. One `campus-ai-037` timeout was retried alone. The
final v30 prediction file contains five successful records and no warnings.

V30 fixed the targeted grouping regression: all three positive cases had exact
concept-level `any_of` groups and neither negative case created a false group.
It also restored all four required work abilities in `147`. Remaining semantic
misses include `编程基础扎实` in `037`, the required `理解真实机器人系统...`
clause in `078`, and unstable project qualification in `008`.

The low legacy preferred-field and qualifier scores mix real omissions with a
representation mismatch. V30 correctly represents `AI项目` as concept `AI`
plus `project_experience` and `开源实践` as concept `开源` plus
`open_source_experience`, while the v14 labels store those as suffixed strings.
V14 also omits some explicit development/practical experience qualifiers.
Concept-aware qualifier labels are required before making a final qualifier
quality claim.

Machine-readable manifests, predictions, checkpoints, and reports remain under
the ignored `artifacts/evaluation/` directory.
