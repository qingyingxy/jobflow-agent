from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any

ZERO_LOWER_BOUND_CODE = "normalized_zero_lower_bound_to_absent_minimum"
ZERO_LOWER_BOUND_PATTERN = re.compile(
    r"(?<!\d)0\s*(?:-|–|—|to)\s*\d+\s*(?:years?|yrs?|months?)\b",
    flags=re.IGNORECASE,
)
QUALIFIER_FIELDS = {"experience_type", "minimum_months", "domain"}


@dataclass(frozen=True)
class ZeroLowerBoundQualifierDiagnostic:
    record_index: int
    atom_index: int
    path: str
    before: int
    after: None
    source_text: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "record_index": self.record_index,
            "atom_index": self.atom_index,
            "path": self.path,
            "before": self.before,
            "after": self.after,
            "source_text": self.source_text,
        }


@dataclass(frozen=True)
class ZeroLowerBoundQualifierResult:
    output: object
    diagnostics: tuple[ZeroLowerBoundQualifierDiagnostic, ...]

    @property
    def activation_count(self) -> int:
        return len(self.diagnostics)


def normalize_zero_lower_bound_qualifier(
    v4_3_output: object,
    *,
    record_index: int,
) -> ZeroLowerBoundQualifierResult:
    """Apply the preregistered zero-to-null treatment to a copied v4.3 output."""

    normalized = copy.deepcopy(v4_3_output)
    diagnostics: list[ZeroLowerBoundQualifierDiagnostic] = []
    if not isinstance(normalized, dict):
        return ZeroLowerBoundQualifierResult(normalized, ())
    atoms = normalized.get("clause_atoms")
    if not isinstance(atoms, list):
        return ZeroLowerBoundQualifierResult(normalized, ())
    for atom_index, atom in enumerate(atoms):
        if not _eligible(atom):
            continue
        qualifier = atom["qualifier"]
        qualifier["minimum_months"] = None
        diagnostics.append(
            ZeroLowerBoundQualifierDiagnostic(
                record_index=record_index,
                atom_index=atom_index,
                path=f"clause_atoms[{atom_index}].qualifier.minimum_months",
                before=0,
                after=None,
                source_text=atom["source_text"],
            )
        )
    return ZeroLowerBoundQualifierResult(normalized, tuple(diagnostics))


def restore_zero_lower_bound_qualifier(
    treated_output: object,
    diagnostics: tuple[ZeroLowerBoundQualifierDiagnostic, ...],
    *,
    record_index: int,
) -> object:
    """Reverse a treatment only when every recorded activation still matches."""

    restored = copy.deepcopy(treated_output)
    if not diagnostics:
        return restored
    if not isinstance(restored, dict):
        raise TypeError("diagnostics cannot target a non-object output")
    atoms = restored.get("clause_atoms")
    if not isinstance(atoms, list):
        raise TypeError("diagnostic path does not resolve to clause atoms")
    seen: set[int] = set()
    for diagnostic in reversed(diagnostics):
        if (
            diagnostic.record_index != record_index
            or diagnostic.atom_index in seen
            or diagnostic.atom_index < 0
            or diagnostic.atom_index >= len(atoms)
            or diagnostic.path
            != (
                f"clause_atoms[{diagnostic.atom_index}].qualifier.minimum_months"
            )
            or diagnostic.before != 0
            or diagnostic.after is not None
        ):
            raise ValueError("invalid zero-lower-bound diagnostic")
        atom = atoms[diagnostic.atom_index]
        if not _matches_restoration_evidence(atom, diagnostic):
            raise ValueError("zero-lower-bound diagnostic does not match output")
        atom["qualifier"]["minimum_months"] = 0
        seen.add(diagnostic.atom_index)

    replayed = normalize_zero_lower_bound_qualifier(
        restored,
        record_index=record_index,
    )
    if replayed.output != treated_output or replayed.diagnostics != diagnostics:
        raise ValueError("restored output does not replay to the supplied treatment")
    return restored


def _eligible(atom: object) -> bool:
    if not isinstance(atom, dict) or atom.get("category") != "experience":
        return False
    qualifier = atom.get("qualifier")
    source_text = atom.get("source_text")
    surface_item = atom.get("surface_item")
    if (
        not isinstance(qualifier, dict)
        or set(qualifier) != QUALIFIER_FIELDS
        or type(qualifier.get("minimum_months")) is not int
        or qualifier["minimum_months"] != 0
        or not isinstance(source_text, str)
        or not isinstance(surface_item, str)
        or surface_item not in source_text
    ):
        return False
    return bool(
        ZERO_LOWER_BOUND_PATTERN.search(source_text)
        or ZERO_LOWER_BOUND_PATTERN.search(surface_item)
    )


def _matches_restoration_evidence(
    atom: object,
    diagnostic: ZeroLowerBoundQualifierDiagnostic,
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
