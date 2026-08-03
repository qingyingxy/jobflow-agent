from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import JSON, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database import Base

ANALYSIS_VERSION = "job-analysis-v1"
RiskSeverity = Literal["high", "medium", "low"]


class AnalysisRisk(BaseModel):
    """A user-visible risk generated from deterministic analysis details."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=100)
    severity: RiskSeverity
    title: str = Field(min_length=1, max_length=160)
    detail: str = Field(min_length=1)
    requirement_name: str | None = Field(default=None, max_length=120)


def generate_job_analysis_id() -> str:
    return f"analysis_{uuid4().hex[:20]}"


class JobAnalysis(Base):
    """User-scoped analysis; never reuse this row across users."""

    __tablename__ = "job_analyses"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    job_posting_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    parse_result_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    analysis_version: Mapped[str] = mapped_column(String(80), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    eligibility: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    matches: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    score: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    risks: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    missing_information: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    invalidated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
