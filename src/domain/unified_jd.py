from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

UNIFIED_JD_SCHEMA_VERSION = "unified-jd-v1"
UNIFIED_JD_GRANULARITY_VERSION = "unified-jd-annotation-granularity-v2"

JobType = Literal["campus", "internship", "full_time", "part_time"]
ClauseLevel = Literal["required", "preferred", "mention"]
ClauseRelation = Literal["all_of", "any_of"]
ClauseCategory = Literal[
    "skill",
    "capability",
    "experience",
    "responsibility",
    "fact",
]
FactFieldName = Literal[
    "job_type",
    "locations",
    "graduation_years",
    "education_requirements",
    "major_requirements",
    "internship_duration_months",
    "weekly_days",
    "earliest_start_date",
    "deadline",
]
ExperienceType = Literal[
    "project",
    "internship",
    "research",
    "development",
    "practical",
    "open_source",
    "employment",
    "industry",
]

NonEmptyText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=240),
]


def _unique_text(values: list[str] | None) -> list[str] | None:
    if values is None:
        return None
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip()
        key = normalized.casefold()
        if normalized and key not in seen:
            result.append(normalized)
            seen.add(key)
    if not result:
        raise ValueError("列表至少需要一个非空值；未提及时应使用 null")
    return result


class UnifiedFactEvidence(BaseModel):
    """One exact source quote supporting a populated fact field."""

    model_config = ConfigDict(extra="forbid")

    field: FactFieldName
    source_text: NonEmptyText


class UnifiedJobFacts(BaseModel):
    """The nine source-backed facts emitted by the unified parser."""

    model_config = ConfigDict(extra="forbid")

    job_type: JobType | None
    locations: list[NonEmptyText] | None = Field(min_length=1)
    graduation_years: list[int] | None = Field(min_length=1)
    education_requirements: list[NonEmptyText] | None = Field(min_length=1)
    major_requirements: list[NonEmptyText] | None = Field(min_length=1)
    internship_duration_months: int | None = Field(ge=1)
    weekly_days: int | None = Field(ge=1, le=7)
    earliest_start_date: date | None
    deadline: date | None
    evidence: list[UnifiedFactEvidence]

    @field_validator(
        "locations",
        "education_requirements",
        "major_requirements",
    )
    @classmethod
    def normalize_text_lists(cls, value: list[str] | None) -> list[str] | None:
        return _unique_text(value)

    @field_validator("graduation_years")
    @classmethod
    def normalize_graduation_years(
        cls,
        value: list[int] | None,
    ) -> list[int] | None:
        if value is None:
            return None
        years = list(dict.fromkeys(value))
        if not years:
            raise ValueError("毕业年份未提及时应使用 null")
        if any(year < 1900 or year > 2200 for year in years):
            raise ValueError("毕业年份必须在 1900 到 2200 之间")
        return sorted(years)

    @model_validator(mode="after")
    def require_evidence_for_populated_facts(self) -> UnifiedJobFacts:
        fact_fields = (
            "job_type",
            "locations",
            "graduation_years",
            "education_requirements",
            "major_requirements",
            "internship_duration_months",
            "weekly_days",
            "earliest_start_date",
            "deadline",
        )
        populated = {
            field_name
            for field_name in fact_fields
            if getattr(self, field_name) is not None
        }
        cited = {item.field for item in self.evidence}
        missing = sorted(populated - cited)
        if missing:
            raise ValueError(f"非空事实缺少原文证据：{', '.join(missing)}")
        unsupported = sorted(cited - populated)
        if unsupported:
            raise ValueError(
                f"空事实不能携带原文证据：{', '.join(unsupported)}"
            )
        return self


class ExperienceQualifier(BaseModel):
    """An explicit experience scope applying to every item in one clause."""

    model_config = ConfigDict(extra="forbid")

    experience_type: ExperienceType
    minimum_months: int | None = Field(default=None, ge=1)
    domain: NonEmptyText | None = None


class UnifiedJDClause(BaseModel):
    """One minimal semantic clause backed by an exact JD quote."""

    model_config = ConfigDict(extra="forbid")

    category: ClauseCategory
    fact_field: FactFieldName | None = None
    level: ClauseLevel
    relation: ClauseRelation = "all_of"
    items: list[NonEmptyText] = Field(min_length=1)
    examples: list[NonEmptyText] | None = Field(default=None, min_length=1)
    group_name: NonEmptyText | None = None
    allow_other: bool = False
    qualifier: ExperienceQualifier | None = None
    source_text: NonEmptyText

    @field_validator("items", "examples")
    @classmethod
    def normalize_items(cls, value: list[str] | None) -> list[str] | None:
        return _unique_text(value)

    @model_validator(mode="after")
    def validate_relation(self) -> UnifiedJDClause:
        if self.category == "fact" and self.fact_field is None:
            raise ValueError("fact clause 必须提供 fact_field")
        if self.category != "fact" and self.fact_field is not None:
            raise ValueError("fact_field 只能用于 fact clause")
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


class UnifiedJDModelOutput(BaseModel):
    """Frozen model-owned contract: exactly facts plus semantic clauses."""

    model_config = ConfigDict(extra="forbid")

    facts: UnifiedJobFacts
    clauses: list[UnifiedJDClause]

    @model_validator(mode="after")
    def require_populated_referenced_facts(self) -> UnifiedJDModelOutput:
        for index, clause in enumerate(self.clauses):
            if (
                clause.fact_field is not None
                and getattr(self.facts, clause.fact_field) is None
            ):
                raise ValueError(
                    f"clauses[{index}] 引用了空事实 {clause.fact_field}"
                )
        return self


TEXT_FACT_CLAUSE_FIELDS: tuple[FactFieldName, ...] = (
    "locations",
    "education_requirements",
    "major_requirements",
)


def validate_unified_fact_clause_granularity(
    output: UnifiedJDModelOutput,
) -> None:
    """Require text facts and their fact clauses to reuse identical atoms."""

    errors: list[str] = []
    for field_name in TEXT_FACT_CLAUSE_FIELDS:
        clauses = [
            clause for clause in output.clauses if clause.fact_field == field_name
        ]
        if not clauses:
            continue
        fact_values = getattr(output.facts, field_name)
        clause_values = list(
            dict.fromkeys(item for clause in clauses for item in clause.items)
        )
        if fact_values is None or set(fact_values) != set(clause_values):
            errors.append(
                f"{field_name}: facts={fact_values!r}, fact_clause_items={clause_values!r}"
            )
    if errors:
        raise ValueError("facts 与 fact clauses 粒度不一致：" + "; ".join(errors))


def validate_unified_jd_evidence(
    output: UnifiedJDModelOutput,
    source_content: str,
) -> None:
    """Reject model evidence that is not an exact contiguous JD substring."""

    invalid_paths: list[str] = []
    for index, evidence in enumerate(output.facts.evidence):
        if evidence.source_text not in source_content:
            invalid_paths.append(f"facts.evidence[{index}].source_text")
    for index, clause in enumerate(output.clauses):
        if clause.source_text not in source_content:
            invalid_paths.append(f"clauses[{index}].source_text")
    if invalid_paths:
        raise ValueError(
            "以下原文证据无法在 JD 中定位：" + ", ".join(invalid_paths)
        )
