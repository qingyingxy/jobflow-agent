from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Float, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database import Base

RUN_TYPE_JD_PARSE = "jd_parse"
RUN_TYPE_EVIDENCE_MATCH = "evidence_match"
RUN_TYPE_RESUME_SUGGESTION = "resume_suggestion"
RUN_TYPES = frozenset(
    {
        RUN_TYPE_JD_PARSE,
        RUN_TYPE_EVIDENCE_MATCH,
        RUN_TYPE_RESUME_SUGGESTION,
    }
)

RUN_STATUS_SUCCEEDED = "succeeded"
RUN_STATUS_FAILED = "failed"
RUN_STATUSES = frozenset({RUN_STATUS_SUCCEEDED, RUN_STATUS_FAILED})

VALIDATION_PASSED = "passed"
VALIDATION_FAILED = "failed"
VALIDATION_STATUSES = frozenset({VALIDATION_PASSED, VALIDATION_FAILED})


def generate_parse_result_id() -> str:
    return f"parse_{uuid4().hex[:20]}"


def generate_agent_run_id() -> str:
    return f"run_{uuid4().hex[:20]}"


class JobParseResult(Base):
    """Job-level parse cache; it intentionally contains no user-specific data."""

    __tablename__ = "job_parse_results"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    job_posting_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    schema_version: Mapped[str] = mapped_column(String(80), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(80), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(80), nullable=False)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    structured_jd: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class AgentRun(Base):
    """Auditable execution record shared by all future agent capabilities."""

    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    run_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(40), nullable=False)
    target_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(80), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    validation_status: Mapped[str] = mapped_column(String(24), nullable=False)
    validation_result: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
