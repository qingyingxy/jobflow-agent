from __future__ import annotations

import copy
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from src.services.unified_jd_flat_atomic_v4_3_compatibility import (
    FlatAtomicV42CompatibilityDiagnostic,
    normalize_flat_atomic_v4_3_wire_output,
    restore_flat_atomic_v4_3_wire_output,
)

UNIFIED_JD_FLAT_ATOMIC_V4_4_COMPATIBILITY_VERSION = (
    "unified-jd-flat-atomic-v4.4-compatibility-v1"
)

CATEGORY_ALIAS_CODE = "normalized_category_vocabulary_alias"
ZERO_LOWER_BOUND_CODE = "normalized_zero_lower_bound_to_absent_minimum"
CATEGORY_ALIASES = {"knowledge": "skill", "motivation": "capability"}
QUALIFIER_FIELDS = {"experience_type", "minimum_months", "domain"}
ZERO_LOWER_BOUND_PATTERN = re.compile(
    r"(?<!\d)0\s*(?:-|–|—|to)\s*\d+\s*(?:years?|yrs?|months?)\b",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class FlatAtomicV44CompatibilityDiagnostic:
    path: str
    code: str
    pipeline_order: int
    before: object
    after: object
    atom_index: int
    source_text: str | None = None

    def as_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "path": self.path,
            "code": self.code,
            "pipeline_order": self.pipeline_order,
            "before": copy.deepcopy(self.before),
            "after": copy.deepcopy(self.after),
            "atom_index": self.atom_index,
        }
        if self.source_text is not None:
            value["source_text"] = self.source_text
        return value


CompatibilityDiagnostic = (
    FlatAtomicV42CompatibilityDiagnostic | FlatAtomicV44CompatibilityDiagnostic
)


@dataclass(frozen=True)
class FlatAtomicV44CompatibilityResult:
    output: object
    diagnostics: tuple[CompatibilityDiagnostic, ...]

    @property
    def activation_count(self) -> int:
        return len(self.diagnostics)


def normalize_flat_atomic_v4_4_wire_output(
    raw_output: object,
) -> FlatAtomicV44CompatibilityResult:
    """Apply frozen v4.3 followed by the preregistered stages 4 and 5."""

    v4_3 = normalize_flat_atomic_v4_3_wire_output(raw_output)
    normalized = copy.deepcopy(v4_3.output)
    diagnostics: list[CompatibilityDiagnostic] = list(v4_3.diagnostics)
    if not isinstance(normalized, dict):
        return FlatAtomicV44CompatibilityResult(normalized, tuple(diagnostics))
    atoms = normalized.get("clause_atoms")
    if not isinstance(atoms, list):
        return FlatAtomicV44CompatibilityResult(normalized, tuple(diagnostics))

    for atom_index, atom in enumerate(atoms):
        if not isinstance(atom, dict):
            continue
        category = atom.get("category")
        if category not in CATEGORY_ALIASES:
            continue
        after = CATEGORY_ALIASES[category]
        atom["category"] = after
        diagnostics.append(
            FlatAtomicV44CompatibilityDiagnostic(
                path=f"clause_atoms[{atom_index}].category",
                code=CATEGORY_ALIAS_CODE,
                pipeline_order=4,
                atom_index=atom_index,
                before=category,
                after=after,
            )
        )

    for atom_index, atom in enumerate(atoms):
        if not _zero_lower_bound_eligible(atom):
            continue
        qualifier = atom["qualifier"]
        qualifier["minimum_months"] = None
        diagnostics.append(
            FlatAtomicV44CompatibilityDiagnostic(
                path=f"clause_atoms[{atom_index}].qualifier.minimum_months",
                code=ZERO_LOWER_BOUND_CODE,
                pipeline_order=5,
                atom_index=atom_index,
                before=0,
                after=None,
                source_text=atom["source_text"],
            )
        )

    return FlatAtomicV44CompatibilityResult(normalized, tuple(diagnostics))


def restore_flat_atomic_v4_4_wire_output(
    normalized_output: object,
    diagnostics: Iterable[CompatibilityDiagnostic],
) -> object:
    """Reverse stages 5 and 4, then delegate stages 3-1 to frozen v4.3."""

    ordered = tuple(diagnostics)
    restored = copy.deepcopy(normalized_output)
    if not ordered:
        return restored
    if not isinstance(restored, dict):
        raise TypeError("diagnostics cannot target a non-object output")

    v4_3_diagnostics, stage_4, stage_5 = _validate_and_group_diagnostics(ordered)
    for item in reversed(stage_5):
        atom = _indexed_atom(restored, item.atom_index)
        if not _matches_zero_restoration(atom, item):
            raise ValueError("zero-lower-bound diagnostic does not match output")
        atom["qualifier"]["minimum_months"] = 0

    for item in reversed(stage_4):
        atom = _indexed_atom(restored, item.atom_index)
        if atom.get("category") != item.after:
            raise ValueError("category-alias diagnostic does not match output")
        atom["category"] = copy.deepcopy(item.before)

    restored = restore_flat_atomic_v4_3_wire_output(restored, v4_3_diagnostics)
    replayed = normalize_flat_atomic_v4_4_wire_output(restored)
    if replayed.output != normalized_output or replayed.diagnostics != ordered:
        raise ValueError("restored output does not replay to the supplied treatment")
    return restored


def _validate_and_group_diagnostics(
    diagnostics: tuple[CompatibilityDiagnostic, ...],
) -> tuple[
    tuple[FlatAtomicV42CompatibilityDiagnostic, ...],
    tuple[FlatAtomicV44CompatibilityDiagnostic, ...],
    tuple[FlatAtomicV44CompatibilityDiagnostic, ...],
]:
    v4_3: list[FlatAtomicV42CompatibilityDiagnostic] = []
    stage_4: list[FlatAtomicV44CompatibilityDiagnostic] = []
    stage_5: list[FlatAtomicV44CompatibilityDiagnostic] = []
    seen: dict[int, set[int]] = {4: set(), 5: set()}
    previous_order = 0
    for item in diagnostics:
        if isinstance(item, FlatAtomicV42CompatibilityDiagnostic):
            if item.pipeline_order not in (1, 2, 3):
                raise ValueError("invalid carried v4.3 diagnostic order")
            order = item.pipeline_order
            v4_3.append(item)
        elif isinstance(item, FlatAtomicV44CompatibilityDiagnostic):
            expected_order = {
                CATEGORY_ALIAS_CODE: 4,
                ZERO_LOWER_BOUND_CODE: 5,
            }.get(item.code)
            if expected_order is None or item.pipeline_order != expected_order:
                raise ValueError("invalid v4.4 diagnostic mechanism or order")
            order = expected_order
            if item.atom_index in seen[order]:
                raise ValueError("duplicate v4.4 diagnostic target")
            seen[order].add(item.atom_index)
            if order == 4:
                _validate_category_diagnostic(item)
                stage_4.append(item)
            else:
                _validate_zero_diagnostic(item)
                stage_5.append(item)
        else:
            raise TypeError("v4.4 reverse requires compatibility diagnostics")
        if order < previous_order:
            raise ValueError("diagnostics are not in forward pipeline order")
        previous_order = order
    return tuple(v4_3), tuple(stage_4), tuple(stage_5)


def _validate_category_diagnostic(
    item: FlatAtomicV44CompatibilityDiagnostic,
) -> None:
    if (
        not _is_nonnegative_index(item.atom_index)
        or item.path != f"clause_atoms[{item.atom_index}].category"
        or item.before not in CATEGORY_ALIASES
        or item.after != CATEGORY_ALIASES[item.before]
        or item.source_text is not None
    ):
        raise ValueError("invalid category-alias diagnostic")


def _validate_zero_diagnostic(item: FlatAtomicV44CompatibilityDiagnostic) -> None:
    if (
        not _is_nonnegative_index(item.atom_index)
        or item.path
        != f"clause_atoms[{item.atom_index}].qualifier.minimum_months"
        or type(item.before) is not int
        or item.before != 0
        or item.after is not None
        or not isinstance(item.source_text, str)
    ):
        raise ValueError("invalid zero-lower-bound diagnostic")


def _zero_lower_bound_eligible(atom: object) -> bool:
    if not isinstance(atom, dict) or atom.get("category") != "experience":
        return False
    qualifier = atom.get("qualifier")
    source_text = atom.get("source_text")
    surface_item = atom.get("surface_item")
    return bool(
        isinstance(qualifier, dict)
        and set(qualifier) == QUALIFIER_FIELDS
        and type(qualifier.get("minimum_months")) is int
        and qualifier["minimum_months"] == 0
        and isinstance(source_text, str)
        and isinstance(surface_item, str)
        and surface_item in source_text
        and (
            ZERO_LOWER_BOUND_PATTERN.search(source_text)
            or ZERO_LOWER_BOUND_PATTERN.search(surface_item)
        )
    )


def _matches_zero_restoration(
    atom: object,
    diagnostic: FlatAtomicV44CompatibilityDiagnostic,
) -> bool:
    if not isinstance(atom, dict) or atom.get("category") != "experience":
        return False
    qualifier = atom.get("qualifier")
    source_text = atom.get("source_text")
    surface_item = atom.get("surface_item")
    return bool(
        isinstance(qualifier, dict)
        and set(qualifier) == QUALIFIER_FIELDS
        and qualifier.get("minimum_months") is None
        and source_text == diagnostic.source_text
        and isinstance(surface_item, str)
        and surface_item in source_text
        and (
            ZERO_LOWER_BOUND_PATTERN.search(source_text)
            or ZERO_LOWER_BOUND_PATTERN.search(surface_item)
        )
    )


def _indexed_atom(root: dict[str, object], index: int) -> dict[str, object]:
    atoms = root.get("clause_atoms")
    if (
        not isinstance(atoms, list)
        or not _is_nonnegative_index(index)
        or index >= len(atoms)
        or not isinstance(atoms[index], dict)
    ):
        raise ValueError(f"diagnostic path does not resolve: clause_atoms[{index}]")
    return atoms[index]


def _is_nonnegative_index(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0
