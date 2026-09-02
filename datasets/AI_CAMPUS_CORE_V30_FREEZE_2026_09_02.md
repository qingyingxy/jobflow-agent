# AI Campus Core Parser v30 freeze

- Freeze date: `2026-09-02`
- Code commit: `219504f674a5752b9dbcdf78cdd0708744037242`
- Parser: `jd-core-parser-v30`
- Prompt: `jd-core-parser-prompt-v20`
- Schema: `core-job-fields-v7`
- Skill ontology: `skill-ontology-v4`
- Model used in the development comparison: `deepseek-v4-flash`

## Frozen implementation

This freeze adds a concept-aware skill representation while retaining the
legacy Core fields. Stable skill identities and alias normalization are owned
locally; the model remains responsible for semantic strength, experience
qualifier, and `all_of` versus required `any_of` classification.

The frozen version also adds concept, strength, qualifier, and relation metrics.
No parser, prompt, schema, ontology, normalization, or metric code may be changed
while the new blind set is being collected and annotated. Any later change must
use a new version and a separately named evaluation run.

## Verification

- Full test suite: `352 passed`
- Ruff: passed
- `git diff --check`: passed

The five-case development comparison is documented in
`AI_CAMPUS_CORE_V29_DEV_SMOKE5_2026_09_02.md`. V30 improved concept-level
grouping and strength classification on that small development sample, but the
sample is not an unseen holdout and must not be used as a final quality claim.

## Blind-set boundary

The next evaluation set must contain 8--10 public JD pages that are absent from
the existing 154-case catalog. Collection and concept-aware annotation must be
completed before any v30 predictions are generated or inspected.

During blind annotation:

- Save the public source URL, retrieval date, company, title, and verbatim JD.
- Deduplicate against the existing catalog by URL, company/title, and text hash.
- Annotate explicit evidence only; do not infer requirements from common sense.
- Record `skill_id`, `canonical_name`, `strength`, `qualifier`, `relation`,
  `group_name`, `allow_other`, and exact `source_text` for each skill concept.
- Do not call DeepSeek or another parsing model and do not run the frozen parser.
- Freeze the raw-source and label files with SHA-256 hashes before evaluation.

After the blind-set files are frozen, v30 may be run once to obtain a genuine
unseen result. Errors from that run may be analyzed, but must not be used to
alter v30 or the frozen labels.
