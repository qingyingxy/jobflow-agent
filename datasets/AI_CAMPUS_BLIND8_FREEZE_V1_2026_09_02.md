# AI Campus blind-8 freeze v1

- Freeze date: `2026-09-02`
- Cases: `8`
- Companies: `5`
- Campus roles: `6`
- Internship roles: `2`
- Concept labels: `202`
- Qualified concept labels: `27`
- Required `any_of` positive cases: `5` (`7` groups)
- Parser predictions generated during collection/annotation: `no`
- External model calls during collection/annotation: `no`

## Frozen baseline

The blind set was collected only after Core Parser v30 had been frozen at code
commit `219504f674a5752b9dbcdf78cdd0708744037242`. The frozen versions are:

- Parser: `jd-core-parser-v30`
- Prompt: `jd-core-parser-prompt-v20`
- Schema: `core-job-fields-v7`
- Skill ontology: `skill-ontology-v4`

No v30 prediction was generated or inspected while the eight cases were being
selected and annotated.

## Collection

All eight records came from official public job-detail pages for Alibaba,
ModelBest, Momenta, StepFun, and NIO. They were checked against the existing
catalog and prior raw-source file by URL, company/title, and SHA-256 of the JD
text. No duplicate was found.

The complete public JD text is retained locally at
`artifacts/evaluation/ai-campus-blind8-raw-v1-2026-09-02.json`. It remains in
the ignored evaluation-artifact directory, matching the repository's existing
metadata-only redistribution policy. Its SHA-256 is
`d97516c702895aaf5779998b1574e9ebc8086f601d48ca61b7e73ebf5a808047`.

The committed concept-aware labels are in
`ai_campus_blind8_label_freeze_v1_2026_09_02.json`. Their SHA-256 is
`9380a242c1cbfc19ce21fe9e5a8a9002a181b1e7c873f0bbb99dda81698f6109`.
The machine-readable freeze manifest records every source URL and per-JD text
hash.

## Validation

`scripts/validate_blind_jd_set.py` checks:

- raw and label case IDs match;
- all concept evidence is a verbatim substring of the corresponding JD;
- each stored skill ID agrees with local deterministic normalization;
- no current or prior URL, company/title, or raw-content hash is duplicated.

The frozen set passes with zero validation errors. The validator does not
import or run the JD parser and does not access an external model.

## Next boundary

V30 may now be run once on these eight cases. The labels and raw-source hashes
must not be edited after predictions are generated. Any later label correction
must create a new version and preserve this freeze.
