# Unified JD Canonical Items Contract v1

> Version: `canonical-items-contract-v1`  
> Scope: non-fact `responsibility`, `skill`, `experience`, and `capability` clauses  
> Fixture: `datasets/unified_jd_canonical_items_contract_v1.json`

## 1. Purpose

This contract separates two operations that the current `clauses[].items` field combines:

1. `surface_items`: source-grounded semantic units extracted from one clause's exact
   `source_text`.
2. `canonical_items`: stable category-specific names derived from those surface units.

The distinction is diagnostic and preparatory. It does not change the frozen
`unified-jd-v1` production schema yet. Until a later schema version is approved,
`canonical_items` in this contract correspond to the existing `clauses[].items` values.

## 2. Required Representation

Each contract fixture contains:

- `source_text`: the exact contiguous evidence quote from the frozen JD.
- `surface_items`: atomic strings that each occur verbatim inside `source_text`.
- `canonical_items`: the ordered target item list used by the frozen label.
- `surface_to_canonical`: one mapping per surface item, containing an exact
  `support_text` and one canonical target.
- `examples`: named instances that explain an upper-level item without inheriting the
  clause requirement independently.
- `relation`, `group_name`, and `allow_other`: logic over canonical items only.

`support_text` may be wider than its `surface_item`. This is necessary when a shared
predicate, subject, suffix, or experience scope applies to several coordinated items.
Both strings must remain exact substrings of `source_text`.

## 3. Invariants

1. A surface item is source text, not a paraphrase.
2. Every surface item maps to exactly one canonical item in the fixture.
3. Every canonical item has at least one surface mapping.
4. Canonical items are unique within a clause after trim and case-fold normalization.
5. Examples are not canonical items and do not affect `all_of` or `any_of`.
6. `any_of` is evaluated only after item mapping and requires at least two canonical
   items plus a non-empty `group_name`.
7. `all_of` has `group_name=null` and `allow_other=false`.
8. Unknown concepts must remain explicit as `unmapped`; they must not be replaced by
   the full source sentence and must not be guessed into an existing concept.
9. The canonicalizer must not read expected labels at runtime. The fixture is a test
   oracle, not a production lookup table.

## 4. Category Rules

### 4.1 Responsibility

Canonical responsibility items describe independently inspectable work objects,
actions, or outcomes. Introductory verbs such as “负责”, “参与”, “从事”, and “推动”
do not become items by themselves.

- Split coordinated work objects or actions when each can be inspected separately.
- Propagate a shared subject or predicate before canonicalization. For example,
  “模型的算法设计、训练与端侧部署” becomes `算法设计`, `模型训练`, and
  `端侧部署`.
- Preserve a domain object when it distinguishes the work, such as `大语言模型预训练`.
- Normalize action phrases into stable noun phrases, such as “设计解决方案” to
  `解决方案设计`.
- Do not copy a complete multi-action responsibility sentence as one canonical item.

### 4.2 Skill

Canonical skill items name technologies, languages, frameworks, algorithms, or a
clearly required technical class. Proficiency verbs such as “熟悉”, “掌握”, and
“了解” belong to level interpretation, not item names.

- Explicit alternatives such as `Java/Python/C++` become separate items.
- A required open class followed by “如” remains one upper-level item; the named
  instances go to `examples`.
- Parentheses may provide an alias. The alias goes to `examples` when the canonical
  item is the expanded term, for example `大语言模型原理` with example `LLM`.
- Normalize cosmetic internal spacing only when the concept identity is unchanged,
  for example `Agent 工作流` to `Agent工作流`.

### 4.3 Experience

Canonical experience items must retain the event or evidence type. A product,
technology, or organization name alone is not an experience item.

- Preserve or add the source-supported head such as `项目`, `研究`, `实践`,
  `使用经验`, or `工程经验`.
- When one experience requirement names illustrative tools or frameworks, keep one
  upper-level experience item and put names in `examples`.
- When the source explicitly offers different acceptable domains or paths, create one
  experience item per path and use `any_of`.
- Shared experience suffixes may be propagated across coordinated alternatives.

### 4.4 Capability

Canonical capability items are demonstrable abilities or outcomes rather than the
whole qualification sentence.

- Split coordinated abilities that can be evidenced independently.
- Remove generic wrappers such as “具备良好的” and nominalize the supported ability.
- Propagate shared words such as “能力” or “理解” to coordinated targets.
- Keep the outcome when it is separately meaningful, for example
  `复杂问题转化为产品方案` or `真实任务落地`.

## 5. Examples Versus Alternatives

The decision order is fixed:

1. Identify the required upper-level concept or the explicitly enumerated candidate
   paths.
2. Separate illustrative instances introduced by constructions such as “如”.
3. Produce canonical items.
4. Determine relation over canonical items.

Examples never create `any_of` by themselves. Therefore:

- “有 PyTorch/PaddlePaddle 等深度学习框架使用经验” is one
  `深度学习框架使用经验` item with two examples and `all_of`.
- “熟悉至少一种主流语言（Java/Python/C++等）” has three candidate items and
  `any_of` because the source explicitly requires at least one of the listed choices.
- “熟练掌握至少一门编程语言，如 Python、R、Matlab” keeps `编程语言` as the
  required item and treats the `如` list as examples.

## 6. Relation Dependency

Relation is downstream of item boundary resolution:

```text
source_text
  -> surface_items + examples
  -> canonical_items
  -> relation over canonical_items
```

A one-item output cannot faithfully encode a multi-candidate `any_of`. Implementations
must not repair this by flipping relation alone. They must first recover the missing
candidate items.

## 7. Unknown And Ambiguous Cases

When a surface item cannot be mapped confidently:

- preserve the atomic surface item;
- emit or record `unmapped` in the canonicalization result;
- retain its exact support text;
- exclude it from automatic alias substitution;
- report unmapped rate by category.

Ambiguous decisions should be added as new reviewed fixtures in a new contract version.
Do not silently change existing canonical strings or use fuzzy matching to hide a
contract mismatch.

## 8. Fixture Acceptance

Version 1 contains exactly 20 reviewed clauses, five for each non-fact category, drawn
from the five saved causal-probe jobs. Automated tests require:

- fixture provenance matches the frozen manifest SHA-256;
- every source and support string is locatable in the original JD;
- every fixture matches the frozen clause's category, level, canonical items,
  examples, relation, group name, and open-group flag;
- all four categories have balanced coverage;
- every surface and canonical item is covered by the explicit mapping;
- responsibility fixtures with multiple target items do not use the whole source
  sentence as their only surface item.

Passing these tests means the contract examples are internally consistent. It does not
yet demonstrate generalization to unseen JDs.
