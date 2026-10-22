from __future__ import annotations

import copy
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from src.services.unified_jd_flat_atomic_v4_compatibility import (
    normalize_flat_atomic_v4_wire_output,
)

UNIFIED_JD_FLAT_ATOMIC_V4_2_COMPATIBILITY_VERSION = (
    "unified-jd-flat-atomic-v4.2-composed-compatibility-v1"
)

ROLE_ALIAS_CODE = "normalized_responsibility_role_alias"
EMPTY_FACT_CODE = "omitted_empty_absent_fact_placeholder"
LONG_EVIDENCE_CODE = "normalized_long_self_sufficient_evidence"
DIAGNOSTIC_CODES = (ROLE_ALIAS_CODE, EMPTY_FACT_CODE, LONG_EVIDENCE_CODE)


@dataclass(frozen=True)
class FlatAtomicV42CompatibilityDiagnostic:
    path: str
    code: str
    pipeline_order: int
    before: object
    after: object
    atom_index: int | None = None
    fact_index: int | None = None

    def as_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "path": self.path,
            "code": self.code,
            "pipeline_order": self.pipeline_order,
            "before": copy.deepcopy(self.before),
            "after": copy.deepcopy(self.after),
        }
        if self.atom_index is not None:
            value["atom_index"] = self.atom_index
        if self.fact_index is not None:
            value["fact_index"] = self.fact_index
        return value


@dataclass(frozen=True)
class FlatAtomicV42CompatibilityResult:
    output: object
    diagnostics: tuple[FlatAtomicV42CompatibilityDiagnostic, ...]

    @property
    def activation_count(self) -> int:
        return len(self.diagnostics)


def normalize_flat_atomic_v4_2_wire_output(
    raw_output: object,
) -> FlatAtomicV42CompatibilityResult:
    """Apply the three frozen compatibility mechanisms in registered order."""

    role_result = normalize_flat_atomic_v4_wire_output(raw_output)
    normalized = role_result.output
    diagnostics = [
        FlatAtomicV42CompatibilityDiagnostic(
            path=item.path,
            code=ROLE_ALIAS_CODE,
            pipeline_order=1,
            atom_index=item.atom_index,
            before=item.before_role,
            after=item.after_role,
        )
        for item in role_result.diagnostics
    ]
    if not isinstance(normalized, dict):
        return FlatAtomicV42CompatibilityResult(normalized, tuple(diagnostics))

    facts = normalized.get("fact_mentions")
    if isinstance(facts, list):
        retained: list[object] = []
        for fact_index, fact in enumerate(facts):
            if _is_exact_empty_absent_fact(fact):
                diagnostics.append(
                    FlatAtomicV42CompatibilityDiagnostic(
                        path=f"fact_mentions[{fact_index}]",
                        code=EMPTY_FACT_CODE,
                        pipeline_order=2,
                        fact_index=fact_index,
                        before=copy.deepcopy(fact),
                        after=None,
                    )
                )
            else:
                retained.append(fact)
        normalized["fact_mentions"] = retained

    atoms = normalized.get("clause_atoms")
    if isinstance(atoms, list):
        for atom_index, atom in enumerate(atoms):
            if not _has_long_self_sufficient_evidence(atom):
                continue
            before = atom["source_text"]
            after = atom["surface_item"]
            atom["source_text"] = after
            diagnostics.append(
                FlatAtomicV42CompatibilityDiagnostic(
                    path=f"clause_atoms[{atom_index}].source_text",
                    code=LONG_EVIDENCE_CODE,
                    pipeline_order=3,
                    atom_index=atom_index,
                    before=before,
                    after=after,
                )
            )

    return FlatAtomicV42CompatibilityResult(normalized, tuple(diagnostics))


def restore_flat_atomic_v4_2_wire_output(
    normalized_output: object,
    diagnostics: Iterable[FlatAtomicV42CompatibilityDiagnostic],
) -> object:
    """Reverse one v4.2 treatment using its immutable audit trail."""

    restored = copy.deepcopy(normalized_output)
    ordered = tuple(diagnostics)
    if not ordered:
        return restored
    if not isinstance(restored, dict):
        raise TypeError("diagnostics cannot target a non-object output")

    for item in reversed(ordered):
        if item.code == LONG_EVIDENCE_CODE:
            atom = _indexed_object(restored, "clause_atoms", item.atom_index)
            if atom.get("source_text") != item.after:
                raise ValueError("long-evidence diagnostic does not match output")
            atom["source_text"] = copy.deepcopy(item.before)
        elif item.code == EMPTY_FACT_CODE:
            facts = restored.get("fact_mentions")
            if not isinstance(facts, list) or item.fact_index is None:
                raise ValueError("fact-omission diagnostic does not match output")
            facts.insert(item.fact_index, copy.deepcopy(item.before))
        elif item.code == ROLE_ALIAS_CODE:
            atom = _indexed_object(restored, "clause_atoms", item.atom_index)
            if atom.get("role") != item.after:
                raise ValueError("role diagnostic does not match output")
            atom["role"] = copy.deepcopy(item.before)
        else:
            raise ValueError(f"unknown v4.2 diagnostic code: {item.code}")
    return restored


def _is_exact_empty_absent_fact(fact: object) -> bool:
    if not isinstance(fact, dict):
        return False
    raw_items = fact.get("raw_items")
    return (
        isinstance(raw_items, list)
        and not raw_items
        and fact.get("source_text") == ""
        and fact.get("level") is None
    )


def _has_long_self_sufficient_evidence(atom: object) -> bool:
    if not isinstance(atom, dict):
        return False
    source_text = atom.get("source_text")
    surface_item = atom.get("surface_item")
    return (
        isinstance(source_text, str)
        and len(source_text) > 240
        and isinstance(surface_item, str)
        and 0 < len(surface_item) <= 240
        and surface_item in source_text
        and atom.get("semantic_item") == surface_item
    )


def _indexed_object(
    root: dict[str, Any], field: str, index: int | None
) -> dict[str, Any]:
    values = root.get(field)
    if (
        not isinstance(values, list)
        or index is None
        or index < 0
        or index >= len(values)
        or not isinstance(values[index], dict)
    ):
        raise ValueError(f"diagnostic path does not resolve: {field}[{index}]")
    return values[index]
