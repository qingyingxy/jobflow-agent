from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.domain.unified_jd import (
    ClauseLevel,
    ClauseRelation,
    NonEmptyText,
)
from src.domain.unified_jd_extraction import SemanticClauseCategory

UNIFIED_JD_FLAT_ATOMIC_V4_SCHEMA_VERSION = "unified-jd-flat-atomic-v4"

FlatAtomicRole = Literal["item", "example"]


class UnifiedJDFlatAtomicQualifierV4(BaseModel):
    """An explicit qualifier preserved without legacy enum coercion."""

    model_config = ConfigDict(extra="forbid")

    experience_type: NonEmptyText
    minimum_months: int | None = Field(default=None, ge=1)
    domain: NonEmptyText | None = None


class UnifiedJDFlatAtomicClauseV4(BaseModel):
    """One model-owned semantic atom with an optional exact surface expression."""

    model_config = ConfigDict(extra="forbid")

    role: FlatAtomicRole = "item"
    category: SemanticClauseCategory
    level: ClauseLevel
    relation: ClauseRelation
    semantic_item: NonEmptyText
    surface_item: NonEmptyText | None = None
    source_text: NonEmptyText
    group_name: NonEmptyText | None = None
    allow_other: bool = False
    qualifier: UnifiedJDFlatAtomicQualifierV4 | None = None

    @model_validator(mode="after")
    def validate_atom(self) -> UnifiedJDFlatAtomicClauseV4:
        if self.relation == "all_of":
            if self.group_name is not None:
                raise ValueError("group_name 只能用于 any_of atom")
            if self.allow_other:
                raise ValueError("allow_other 只能用于 any_of atom")
        if self.surface_item is not None and self.surface_item not in self.source_text:
            raise ValueError("surface_item 必须是 source_text 的精确子串或 null")
        return self


class UnifiedJDGroupedClauseV4(BaseModel):
    """One clause reconstructed solely from identical explicit atom metadata."""

    model_config = ConfigDict(extra="forbid")

    category: SemanticClauseCategory
    level: ClauseLevel
    relation: ClauseRelation
    items: list[NonEmptyText] = Field(min_length=1)
    examples: list[NonEmptyText] | None = Field(default=None, min_length=1)
    group_name: NonEmptyText | None = None
    allow_other: bool = False
    qualifier: UnifiedJDFlatAtomicQualifierV4 | None = None
    source_text: NonEmptyText

    @model_validator(mode="after")
    def validate_group(self) -> UnifiedJDGroupedClauseV4:
        if self.relation == "any_of":
            if len(self.items) < 2:
                raise ValueError("any_of 分组至少需要两个 item atoms")
        else:
            if self.group_name is not None:
                raise ValueError("group_name 只能用于 any_of 分组")
            if self.allow_other:
                raise ValueError("allow_other 只能用于 any_of 分组")
        return self


class UnifiedJDFlatAtomicClausesV4(BaseModel):
    """Flat non-fact clause response; facts remain in the independent V3 layers."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["unified-jd-flat-atomic-v4"] = (
        UNIFIED_JD_FLAT_ATOMIC_V4_SCHEMA_VERSION
    )
    clause_atoms: list[UnifiedJDFlatAtomicClauseV4] = Field(default_factory=list)
