# AI Campus blind-8 human review v2

- Review date: `2026-09-02`
- Reviewer: repository owner
- Annotation guide: `ai-campus-annotation-guide-v1`
- Cases reviewed: `8`
- Parser predictions viewed during review: `no`
- External model calls during review: `no`

## Version boundary

The original independent annotation remains unchanged at
`ai_campus_blind8_label_freeze_v1_2026_09_02.json`. Its SHA-256 remains
`c943ac8dc71bbfc9b774f41e21622048a3b783338df1b97b1a7d30dcbc628d0a`.

The reviewed labels are stored separately at
`ai_campus_blind8_label_human_reviewed_v2_2026_09_02.json`. Their SHA-256 is
`e5100aef8dbfd1437791718b0e478414c146e2f23885ee310bac85fdb15e58be`.

The raw source file is unchanged, remains local and ignored, and has SHA-256
`d97516c702895aaf5779998b1574e9ebc8086f601d48ca61b7e73ebf5a808047`.

## Review decisions

- `blind27-001`: A1-A5 retained.
- `blind27-002`: B1-B5 retained.
- `blind27-003`: C1-C5 retained.
- `blind27-004`: D1-D5 retained; D6 added `任务调度框架` as a responsibility mention.
- `blind27-005`: E1-E4 retained; E5-E6 moved vendor examples under the preferred parent concepts `Switch量产` and `SOC芯片SDK`.
- `blind27-006`: F1-F4 retained; F5-F7 made `AI编程工具` the required parent, demoted named products to examples, added `现代前端工程化`, and completed three missing Agent mentions.
- `blind27-007`: G1-G4 retained; G5-G6 completed research/project/practical qualifiers and responsibility-only technical mentions.
- `blind27-008`: H1-H2 and H4 retained; H3 and H5-H6 made `AI工具` the required parent, completed three preferred domains, and added missing product-work mentions.

## Reviewed label summary

- Skill concepts: `246`
- Concepts with experience qualifiers: `35`
- Cases with required `any_of`: `5`
- Validation errors: `0`

The reviewed labels passed JSON parsing and `scripts.validate_blind_jd_set`.
Every concept evidence span is present verbatim in its JD, and every stored
skill ID agrees with deterministic ontology normalization.

## Evaluation boundary

Frozen v30 may be run once against this reviewed v2 label set. Do not edit the
reviewed labels after predictions are generated. Any later correction must
create v3 and preserve v1, v2, predictions, and reports.
