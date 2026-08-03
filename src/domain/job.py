from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database import Base


def generate_job_id() -> str:
    return f"job_{uuid4().hex[:20]}"


def generate_trace_id() -> str:
    return f"trace_{uuid4().hex[:20]}"


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
        normalized = value.replace("\r\n", "\n").replace("\r", "\n").strip()
        if len(normalized) < 20:
            raise ValueError("岗位文本至少需要 20 个字符")
        return normalized


class QualificationCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str = Field(min_length=1, max_length=80)
    operator: Literal["eq", "in", "contains", "gte", "lte", "unknown"]
    value: Any | None = None
    source_text: str | None = None


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
