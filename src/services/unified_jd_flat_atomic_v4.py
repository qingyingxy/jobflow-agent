from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.domain.unified_jd_flat_atomic_v4 import (
    UnifiedJDFlatAtomicClausesV4,
    UnifiedJDFlatAtomicClauseV4,
    UnifiedJDGroupedClauseV4,
)

UNIFIED_JD_FLAT_ATOMIC_V4_COMPILER_VERSION = (
    "unified-jd-flat-atomic-grouping-compiler-v4"
)


@dataclass
class _ClauseGroup:
    atom: UnifiedJDFlatAtomicClauseV4
    items: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)


def compile_flat_atomic_clauses_v4(
    raw_output: dict[str, Any] | UnifiedJDFlatAtomicClausesV4,
    source_content: str,
) -> list[UnifiedJDGroupedClauseV4]:
    """Group flat atoms using only explicit clause metadata and exact evidence."""

    extraction = (
        raw_output
        if isinstance(raw_output, UnifiedJDFlatAtomicClausesV4)
        else UnifiedJDFlatAtomicClausesV4.model_validate(raw_output)
    )
    groups: dict[tuple[Any, ...], _ClauseGroup] = {}
    for index, atom in enumerate(extraction.clause_atoms):
        if atom.source_text not in source_content:
            raise ValueError(
                f"clause_atoms[{index}].source_text 必须是岗位正文的精确子串"
            )
        key = _group_key(atom)
        group = groups.setdefault(key, _ClauseGroup(atom=atom))
        target = group.items if atom.role == "item" else group.examples
        target.append(atom.semantic_item)

    clauses: list[UnifiedJDGroupedClauseV4] = []
    for group in groups.values():
        if not group.items:
            raise ValueError("每个原子分组至少需要一个 role=item 的记录")
        atom = group.atom
        clauses.append(
            UnifiedJDGroupedClauseV4(
                category=atom.category,
                level=atom.level,
                relation=atom.relation,
                items=group.items,
                examples=group.examples or None,
                group_name=atom.group_name,
                allow_other=atom.allow_other,
                qualifier=atom.qualifier,
                source_text=atom.source_text,
            )
        )
    return clauses


def _group_key(atom: UnifiedJDFlatAtomicClauseV4) -> tuple[Any, ...]:
    qualifier = (
        tuple(atom.qualifier.model_dump(mode="json").items())
        if atom.qualifier is not None
        else None
    )
    return (
        atom.source_text,
        atom.category,
        atom.level,
        atom.relation,
        atom.group_name,
        atom.allow_other,
        qualifier,
    )
