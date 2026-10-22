from __future__ import annotations

import copy
from collections.abc import Iterable

from src.services.unified_jd_flat_atomic_v4_2_compatibility import (
    EMPTY_FACT_CODE,
    LONG_EVIDENCE_CODE,
    ROLE_ALIAS_CODE,
    FlatAtomicV42CompatibilityDiagnostic,
    FlatAtomicV42CompatibilityResult,
    normalize_flat_atomic_v4_2_wire_output,
)

UNIFIED_JD_FLAT_ATOMIC_V4_3_COMPATIBILITY_VERSION = (
    "unified-jd-flat-atomic-v4.3-compatibility-v1"
)

_PIPELINE_ORDER_BY_CODE = {
    ROLE_ALIAS_CODE: 1,
    EMPTY_FACT_CODE: 2,
    LONG_EVIDENCE_CODE: 3,
}


def normalize_flat_atomic_v4_3_wire_output(
    raw_output: object,
) -> FlatAtomicV42CompatibilityResult:
    """Return the frozen v4.2 forward result without alteration."""

    return normalize_flat_atomic_v4_2_wire_output(raw_output)


def restore_flat_atomic_v4_3_wire_output(
    normalized_output: object,
    diagnostics: Iterable[FlatAtomicV42CompatibilityDiagnostic],
) -> object:
    """Reverse stages 3-2-1, restoring omitted facts by ascending source index."""

    ordered = tuple(diagnostics)
    restored = copy.deepcopy(normalized_output)
    if not ordered:
        return restored
    if not isinstance(restored, dict):
        raise TypeError("diagnostics cannot target a non-object output")

    stages = _validate_and_group_diagnostics(ordered)
    for _, item in reversed(stages[3]):
        atom = _indexed_object(restored, "clause_atoms", item.atom_index)
        if (
            atom.get("source_text") != item.after
            or atom.get("surface_item") != item.after
            or atom.get("semantic_item") != item.after
        ):
            raise ValueError("long-evidence diagnostic does not match output")
        atom["source_text"] = copy.deepcopy(item.before)

    facts = restored.get("fact_mentions")
    if stages[2] and not isinstance(facts, list):
        raise ValueError("fact-omission diagnostics require a fact list")
    for _, item in sorted(stages[2], key=lambda pair: (pair[1].fact_index, pair[0])):
        if item.fact_index is None or item.fact_index > len(facts):
            raise ValueError("fact-omission index cannot restore the original order")
        facts.insert(item.fact_index, copy.deepcopy(item.before))

    for _, item in reversed(stages[1]):
        atom = _indexed_object(restored, "clause_atoms", item.atom_index)
        if (
            atom.get("role") != item.after
            or atom.get("category") != "responsibility"
            or atom.get("level") != "mention"
        ):
            raise ValueError("role diagnostic does not match output")
        atom["role"] = copy.deepcopy(item.before)

    replayed = normalize_flat_atomic_v4_2_wire_output(restored)
    if replayed.output != normalized_output or replayed.diagnostics != ordered:
        raise ValueError("restored output does not replay to the supplied treatment")
    return restored


def _validate_and_group_diagnostics(
    diagnostics: tuple[FlatAtomicV42CompatibilityDiagnostic, ...],
) -> dict[int, list[tuple[int, FlatAtomicV42CompatibilityDiagnostic]]]:
    stages: dict[int, list[tuple[int, FlatAtomicV42CompatibilityDiagnostic]]] = {
        1: [],
        2: [],
        3: [],
    }
    omission_indexes: set[int] = set()
    previous_order = 0
    for position, item in enumerate(diagnostics):
        if not isinstance(item, FlatAtomicV42CompatibilityDiagnostic):
            raise TypeError("v4.3 reverse requires frozen v4.2 diagnostics")
        expected_order = _PIPELINE_ORDER_BY_CODE.get(item.code)
        if expected_order is None:
            raise ValueError(f"unknown v4.3 diagnostic code: {item.code}")
        if (
            item.pipeline_order != expected_order
            or item.pipeline_order < previous_order
        ):
            raise ValueError("diagnostic pipeline order does not match its mechanism")
        previous_order = item.pipeline_order
        if item.code == ROLE_ALIAS_CODE:
            _validate_role_diagnostic(item)
        elif item.code == EMPTY_FACT_CODE:
            _validate_omission_diagnostic(item, omission_indexes)
        else:
            _validate_long_evidence_diagnostic(item)
        stages[item.pipeline_order].append((position, item))
    return stages


def _validate_role_diagnostic(
    item: FlatAtomicV42CompatibilityDiagnostic,
) -> None:
    if (
        not _is_nonnegative_index(item.atom_index)
        or item.fact_index is not None
        or item.path != f"clause_atoms[{item.atom_index}].role"
        or item.before != "responsibility"
        or item.after != "item"
    ):
        raise ValueError("invalid responsibility-role diagnostic")


def _validate_omission_diagnostic(
    item: FlatAtomicV42CompatibilityDiagnostic,
    seen_indexes: set[int],
) -> None:
    if (
        not _is_nonnegative_index(item.fact_index)
        or item.atom_index is not None
        or item.path != f"fact_mentions[{item.fact_index}]"
        or item.after is not None
        or not _is_exact_empty_absent_fact(item.before)
        or item.fact_index in seen_indexes
    ):
        raise ValueError("invalid or duplicate fact-omission diagnostic")
    seen_indexes.add(item.fact_index)


def _validate_long_evidence_diagnostic(
    item: FlatAtomicV42CompatibilityDiagnostic,
) -> None:
    if (
        not _is_nonnegative_index(item.atom_index)
        or item.fact_index is not None
        or item.path != f"clause_atoms[{item.atom_index}].source_text"
        or not isinstance(item.before, str)
        or len(item.before) <= 240
        or not isinstance(item.after, str)
        or not 0 < len(item.after) <= 240
        or item.after not in item.before
    ):
        raise ValueError("invalid long-evidence diagnostic")


def _is_exact_empty_absent_fact(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    raw_items = value.get("raw_items")
    return (
        isinstance(raw_items, list)
        and not raw_items
        and value.get("source_text") == ""
        and value.get("level") is None
    )


def _is_nonnegative_index(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _indexed_object(
    root: dict[str, object], field: str, index: int | None
) -> dict[str, object]:
    values = root.get(field)
    if (
        not isinstance(values, list)
        or not _is_nonnegative_index(index)
        or index >= len(values)
        or not isinstance(values[index], dict)
    ):
        raise ValueError(f"diagnostic path does not resolve: {field}[{index}]")
    return values[index]
