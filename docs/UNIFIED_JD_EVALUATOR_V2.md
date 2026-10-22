# Unified JD Evaluator V2

## Purpose

Evaluator v2 separates extraction quality into six independently inspectable dimensions:

1. fact values
2. evidence spans
3. clause category
4. clause level
5. clause relation
6. canonical items

The previous full-clause signature remains in `clauses` for report and gate compatibility. It is no longer the only explanation of clause quality.

## Output Contract

Every report includes `evaluation_version: unified-jd-evaluator-v2` and a `dimensions` object:

```text
dimensions
|- facts
|- evidence_spans
|  |- fact_evidence
|  |- clause_evidence
|  `- all
|- category
|- level
|- relation
`- canonical_items
```

Legacy `facts`, `clauses`, `evidence`, `metrics`, and `gate` fields are preserved.

## Scoring Population

- Legacy fact and clause metrics use parse-successful outputs, preserving v1 behavior.
- V2 independent dimensions use every schema-valid output.
- Consequently, an invalid evidence quote reduces span quality and parse success without erasing otherwise valid fact, category, level, relation, or item predictions.
- Schema-invalid or missing outputs contribute empty predictions to every dimension.

## Facts

`dimensions.facts` scores each of the nine fact fields independently and reports per-field precision, recall, F1, and exact case accuracy.

Normalization is deterministic: dates use ISO format, strings use NFKC/casefold/whitespace normalization, and location values ignore a terminal Chinese `市` suffix. No model call is involved.

## Evidence Spans

Fact evidence and clause evidence are scored separately. A source quote is resolved to character offsets in the complete JD. Fact evidence can only match expected evidence for the same fact field.

Each span group reports:

- `exact`: one-to-one offset equality.
- `overlap`: deterministic one-to-one matching when character intersection is positive, plus mean IoU.
- `character_coverage`: micro precision, recall, and F1 over covered source characters.
- localized expected and predicted citation counts.

The matcher prioritizes exact offsets, then higher IoU, then larger overlap. Identical text that appears multiple times is currently resolved to its first occurrence; repeated-source ambiguity should therefore be inspected separately if introduced into a future dataset.

## Category, Level, And Relation

Each attribute has two views:

- `overall`: per-case multiset precision, recall, and F1. This measures whether the output contains the right number of each value without requiring items or the other clause fields to match.
- `span_aligned`: accuracy and a confusion list on clause pairs matched only by evidence overlap. This measures classification quality conditional on finding the same source region.

The span-aligned view intentionally does not use category, level, relation, or items during matching, preventing the scored attribute from choosing its own alignment.

## Canonical Items

`canonical_items.overall` flattens clause items within each case and compares their normalized multisets independently of category, level, relation, and clause grouping.

Current canonicalization is deliberately narrow: NFKC, trim, casefold, and whitespace collapse. `semantic_alias_expansion` is `false`. The evaluator does not claim that two paraphrases are the same concept without a versioned ontology.

Additional diagnostics include:

- `by_category`: item metrics within predicted and expected category buckets.
- `span_aligned_same_category`: item metrics after evidence alignment when both clauses have the same category.

## Optional Gates

Manifests may set these v2 thresholds independently:

- `facts_value_macro_f1_min`
- `evidence_span_character_f1_min`
- `clause_category_f1_min`
- `clause_level_f1_min`
- `clause_relation_f1_min`
- `canonical_items_f1_min`

Existing thresholds remain valid. Frozen manifests do not change behavior until a new threshold is explicitly added.

## Running Offline

```powershell
uv run python -m src.evaluation.run_unified `
  --manifest artifacts/evaluation/unified-jd-dev50-frozen-v2-2026-09-04.json `
  --predictions artifacts/evaluation/unified-jd-dev50-frozen-v2-predictions-v1.json `
  --output artifacts/evaluation/unified-jd-dev50-frozen-v2-dimensional-report-v2-2026-09-04.json
```

This command reads saved predictions and does not call a model API.
