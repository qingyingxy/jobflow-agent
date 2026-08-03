from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database import Base


def generate_job_id() -> str:
    return f"job_{uuid4().hex[:20]}"


def generate_trace_id() -> str:
    return f"trace_{uuid4().hex[:20]}"


def normalize_job_text(value: str) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(normalized) < 20:
        raise ValueError("岗位文本规范化后至少需要 20 个字符")
    return normalized


class JobPosting(Base):
    __tablename__ = "job_postings"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    source_type: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="manual_text",
        server_default="manual_text",
    )
    company: Mapped[str | None] = mapped_column(String(160), nullable=True)
    title: Mapped[str | None] = mapped_column(String(160), nullable=True)
    raw_content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class RawJobDocument(BaseModel):
    """The normalized raw document passed from an importer to later JD analysis."""

    model_config = ConfigDict(extra="forbid")

    source_url: str | None = Field(default=None, max_length=2048)
    source_type: str = Field(default="manual_text", min_length=1, max_length=40)
    raw_content: str = Field(min_length=20)
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    trace_id: str = Field(default_factory=generate_trace_id, max_length=64)

    @field_validator("raw_content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        return normalize_job_text(value)


class FieldEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_path: str = Field(min_length=1, max_length=160)
    source_text: str = Field(min_length=1)
    start_char: int | None = Field(default=None, ge=0)
    end_char: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_position(self) -> FieldEvidence:
        if (
            self.start_char is not None
            and self.end_char is not None
            and self.end_char < self.start_char
        ):
            raise ValueError("原文位置的 end_char 不能小于 start_char")
        return self


class QualificationCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str = Field(min_length=1, max_length=80)
    operator: Literal["eq", "in", "contains", "gte", "lte", "unknown"]
    value: Any | None = None
    source_text: str | None = None
    evidence: list[FieldEvidence] | None = None

    @model_validator(mode="after")
    def validate_value(self) -> QualificationCondition:
        if self.operator == "unknown" and self.value is not None:
            raise ValueError("unknown 条件不能同时提供 value")
        if self.operator != "unknown" and self.value is None:
            raise ValueError("非 unknown 条件必须提供 value")
        return self


class JobRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: Literal[
        "required_skill",
        "preferred_skill",
        "education",
        "major",
        "experience",
        "other",
    ]
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1)
    mandatory: bool = True
    evidence: list[FieldEvidence] | None = None


class StructuredJobDescription(BaseModel):
    """Validated target shape for the JD parser introduced in M04."""

    model_config = ConfigDict(extra="forbid")

    company: str | None = None
    title: str | None = None
    job_type: Literal["campus", "internship", "full_time", "part_time", "unknown"] | None = None
    graduation_years: list[int] | None = None
    recruitment_batch: str | None = None
    locations: list[str] | None = None
    education_requirements: list[str] | None = None
    major_requirements: list[str] | None = None
    required_skills: list[str] | None = None
    preferred_skills: list[str] | None = None
    internship_duration_months: int | None = Field(default=None, ge=0)
    weekly_days: int | None = Field(default=None, ge=1, le=7)
    earliest_start_date: date | None = None
    deadline: date | None = None
    application_url: str | None = None
    qualification_conditions: list[QualificationCondition] | None = None
    requirements: list[JobRequirement] | None = None
    field_evidence: list[FieldEvidence] | None = None

    @model_validator(mode="after")
    def validate_requirement_consistency(self) -> StructuredJobDescription:
        if self.requirements is None:
            return self

        def canonical_names(category: str) -> list[str]:
            names: list[str] = []
            seen: set[str] = set()
            for requirement in self.requirements:
                if requirement.category != category:
                    continue
                normalized = requirement.name.strip().casefold()
                if normalized not in seen:
                    names.append(requirement.name)
                    seen.add(normalized)
            return names

        required_skills = canonical_names("required_skill")
        preferred_skills = canonical_names("preferred_skill")

        for field_name, expected in (
            ("required_skills", required_skills),
            ("preferred_skills", preferred_skills),
        ):
            actual = getattr(self, field_name)
            if actual is not None:
                actual_keys = [skill.strip().casefold() for skill in actual]
                expected_keys = [skill.strip().casefold() for skill in expected]
                if actual_keys != expected_keys:
                    raise ValueError(f"{field_name} 必须由 requirements 按确定顺序派生")
            if expected:
                setattr(self, field_name, expected)
        return self


def validate_field_evidence(
    structured: StructuredJobDescription,
    source_content: str | None = None,
) -> None:
    """Ensure every populated top-level field has traceable source text."""

    if structured.field_evidence is None:
        raise ValueError("缺少 field_evidence")

    paths = {item.field_path for item in structured.field_evidence}
    top_level_fields = (
        "company",
        "title",
        "job_type",
        "graduation_years",
        "recruitment_batch",
        "locations",
        "education_requirements",
        "major_requirements",
        "required_skills",
        "preferred_skills",
        "internship_duration_months",
        "weekly_days",
        "earliest_start_date",
        "deadline",
        "application_url",
        "qualification_conditions",
        "requirements",
    )
    for field_name in top_level_fields:
        value = getattr(structured, field_name)
        direct_evidence = any(
            path == field_name or path.startswith(f"{field_name}[") for path in paths
        )
        nested_evidence = (
            field_name == "requirements"
            and bool(value)
            and all(item.evidence for item in value)
        ) or (
            field_name == "qualification_conditions"
            and bool(value)
            and all(item.evidence for item in value)
        )
        if value is not None and not (direct_evidence or nested_evidence):
            raise ValueError(f"字段 {field_name} 缺少原文依据")

    for requirement in structured.requirements or []:
        if not requirement.evidence:
            raise ValueError(f"岗位要求 {requirement.name} 缺少原文依据")
    for condition in structured.qualification_conditions or []:
        if not condition.evidence:
            raise ValueError(f"资格条件 {condition.field} 缺少原文依据")

    if source_content is not None:
        all_evidence = list(structured.field_evidence)
        for requirement in structured.requirements or []:
            all_evidence.extend(requirement.evidence or [])
        for condition in structured.qualification_conditions or []:
            all_evidence.extend(condition.evidence or [])
        for evidence in all_evidence:
            if evidence.source_text not in source_content:
                raise ValueError(
                    f"字段 {evidence.field_path} 的原文依据不在岗位文本中"
                )
            if evidence.end_char is not None and evidence.end_char > len(source_content):
                raise ValueError(
                    f"字段 {evidence.field_path} 的原文位置超出岗位文本范围"
                )
