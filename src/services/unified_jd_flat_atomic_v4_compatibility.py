from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

UNIFIED_JD_FLAT_ATOMIC_V4_COMPATIBILITY_VERSION = (
    "unified-jd-flat-atomic-v4.1-responsibility-role-alias-v1"
)


@dataclass(frozen=True)
class FlatAtomicV4CompatibilityDiagnostic:
    path: str
    atom_index: int
    code: str = "normalized_responsibility_role_alias"
    before_role: str = "responsibility"
    after_role: str = "item"

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "atom_index": self.atom_index,
            "code": self.code,
            "before_role": self.before_role,
            "after_role": self.after_role,
        }


@dataclass(frozen=True)
class FlatAtomicV4CompatibilityResult:
    output: object
    diagnostics: tuple[FlatAtomicV4CompatibilityDiagnostic, ...]

    @property
    def activation_count(self) -> int:
        return len(self.diagnostics)


def normalize_flat_atomic_v4_wire_output(
    raw_output: object,
) -> FlatAtomicV4CompatibilityResult:
    """Normalize one observed role alias without weakening the v4 schema."""

    normalized = copy.deepcopy(raw_output)
    if not isinstance(normalized, dict):
        return FlatAtomicV4CompatibilityResult(normalized, ())
    atoms = normalized.get("clause_atoms")
    if not isinstance(atoms, list):
        return FlatAtomicV4CompatibilityResult(normalized, ())

    diagnostics: list[FlatAtomicV4CompatibilityDiagnostic] = []
    for index, atom in enumerate(atoms):
        if not isinstance(atom, dict):
            continue
        if (
            atom.get("role") == "responsibility"
            and atom.get("category") == "responsibility"
            and atom.get("level") == "mention"
        ):
            atom["role"] = "item"
            diagnostics.append(
                FlatAtomicV4CompatibilityDiagnostic(
                    path=f"clause_atoms[{index}].role",
                    atom_index=index,
                )
            )
    return FlatAtomicV4CompatibilityResult(normalized, tuple(diagnostics))
