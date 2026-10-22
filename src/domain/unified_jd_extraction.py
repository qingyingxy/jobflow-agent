from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.domain.unified_jd import (
    ClauseLevel,
    ClauseRelation,
    ExperienceQualifier,
    FactFieldName,
    NonEmptyText,
)

SemanticClauseCategory = Literal[
    "skill",
    "capability",
    "experience",
    "responsibility",
]


class UnifiedFactMentionV2(BaseModel):
    """One source mention of a fact, before deterministic type conversion."""

    model_config = ConfigDict(extra="forbid")

    field: FactFieldName
    raw_items: list[NonEmptyText] = Field(min_length=1)
    level: ClauseLevel | None = None
    source_text: NonEmptyText


class UnifiedSemanticClauseV2(BaseModel):
    """A non-fact semantic decision made by the model."""

    model_config = ConfigDict(extra="forbid")

    category: SemanticClauseCategory
    level: ClauseLevel
    relation: ClauseRelation = "all_of"
    items: list[NonEmptyText] = Field(min_length=1)
    examples: list[NonEmptyText] | None = Field(default=None, min_length=1)
    group_name: NonEmptyText | None = None
    allow_other: bool = False
    qualifier: ExperienceQualifier | None = None
    source_text: NonEmptyText

    @model_validator(mode="after")
    def validate_relation(self) -> UnifiedSemanticClauseV2:
        if self.relation == "any_of":
            if len(self.items) < 2:
                raise ValueError("any_of 至少需要两个候选项")
            if self.group_name is None:
                raise ValueError("any_of 必须提供 group_name")
        else:
            if self.group_name is not None:
                raise ValueError("group_name 只能用于 any_of")
            if self.allow_other:
                raise ValueError("allow_other 只能用于 any_of")
        return self


class UnifiedJDExtractionV2(BaseModel):
    """Small model-owned contract; final facts and fact clauses are local-owned."""

    model_config = ConfigDict(extra="forbid")

    fact_mentions: list[UnifiedFactMentionV2] = Field(default_factory=list)
    clauses: list[UnifiedSemanticClauseV2] = Field(default_factory=list)


class UnifiedFactItemV3(BaseModel):
    """A model-owned fact value paired with its exact source expression."""

    model_config = ConfigDict(extra="forbid")

    raw_item: NonEmptyText
    surface_item: NonEmptyText


class UnifiedFactMentionV3(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: FactFieldName
    items: list[UnifiedFactItemV3] = Field(min_length=1)
    level: ClauseLevel | None = None
    source_text: NonEmptyText

    @model_validator(mode="after")
    def validate_surface_items(self) -> UnifiedFactMentionV3:
        missing = [
            item.surface_item
            for item in self.items
            if item.surface_item not in self.source_text
        ]
        if missing:
            raise ValueError("fact surface_item 必须是 source_text 的精确子串")
        return self


class UnifiedSemanticItemV3(BaseModel):
    """An independently understandable item paired with exact surface evidence."""

    model_config = ConfigDict(extra="forbid")

    semantic_item: NonEmptyText
    surface_item: NonEmptyText


class UnifiedSemanticClauseV3(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: SemanticClauseCategory
    level: ClauseLevel
    relation: ClauseRelation = "all_of"
    items: list[UnifiedSemanticItemV3] = Field(min_length=1)
    examples: list[UnifiedSemanticItemV3] | None = Field(default=None, min_length=1)
    group_name: NonEmptyText | None = None
    allow_other: bool = False
    qualifier: ExperienceQualifier | None = None
    source_text: NonEmptyText

    @model_validator(mode="after")
    def validate_clause(self) -> UnifiedSemanticClauseV3:
        if self.relation == "any_of":
            if len(self.items) < 2:
                raise ValueError("any_of 至少需要两个候选项")
            if self.group_name is None:
                raise ValueError("any_of 必须提供 group_name")
        else:
            if self.group_name is not None:
                raise ValueError("group_name 只能用于 any_of")
            if self.allow_other:
                raise ValueError("allow_other 只能用于 any_of")
        surface_items = [item.surface_item for item in self.items]
        surface_items.extend(item.surface_item for item in self.examples or [])
        if any(item not in self.source_text for item in surface_items):
            raise ValueError("clause surface_item 必须是 source_text 的精确子串")
        return self


class UnifiedJDExtractionV3(BaseModel):
    """Model-first contract with separate semantic and exact-surface values."""

    model_config = ConfigDict(extra="forbid")

    fact_mentions: list[UnifiedFactMentionV3] = Field(default_factory=list)
    clauses: list[UnifiedSemanticClauseV3] = Field(default_factory=list)
