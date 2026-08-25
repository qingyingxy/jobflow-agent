from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database import Base


class AttemptStatus(StrEnum):
    CREATED = "CREATED"
    FORM_IN_PROGRESS = "FORM_IN_PROGRESS"
    NEEDS_USER = "NEEDS_USER"
    BLOCKED = "BLOCKED"
    READY_TO_SUBMIT = "READY_TO_SUBMIT"
    SUBMITTED = "SUBMITTED"
    FAILED = "FAILED"
    ABANDONED = "ABANDONED"


class BlockerStatus(StrEnum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


ATTEMPT_TRANSITIONS: dict[AttemptStatus, frozenset[AttemptStatus]] = {
    AttemptStatus.CREATED: frozenset(
        {AttemptStatus.FORM_IN_PROGRESS, AttemptStatus.ABANDONED}
    ),
    AttemptStatus.FORM_IN_PROGRESS: frozenset(
        {
            AttemptStatus.NEEDS_USER,
            AttemptStatus.BLOCKED,
            AttemptStatus.READY_TO_SUBMIT,
            AttemptStatus.FAILED,
            AttemptStatus.ABANDONED,
        }
    ),
    AttemptStatus.NEEDS_USER: frozenset(
        {
            AttemptStatus.FORM_IN_PROGRESS,
            AttemptStatus.BLOCKED,
            AttemptStatus.FAILED,
            AttemptStatus.ABANDONED,
        }
    ),
    AttemptStatus.BLOCKED: frozenset(
        {
            AttemptStatus.FORM_IN_PROGRESS,
            AttemptStatus.NEEDS_USER,
            AttemptStatus.FAILED,
            AttemptStatus.ABANDONED,
        }
    ),
    AttemptStatus.READY_TO_SUBMIT: frozenset(
        {
            AttemptStatus.FORM_IN_PROGRESS,
            AttemptStatus.NEEDS_USER,
            AttemptStatus.BLOCKED,
            AttemptStatus.SUBMITTED,
            AttemptStatus.FAILED,
            AttemptStatus.ABANDONED,
        }
    ),
    AttemptStatus.SUBMITTED: frozenset(),
    AttemptStatus.FAILED: frozenset(
        {AttemptStatus.FORM_IN_PROGRESS, AttemptStatus.ABANDONED}
    ),
    AttemptStatus.ABANDONED: frozenset(),
}


def _generate_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:20]}"


def generate_attempt_id() -> str:
    return _generate_id("attempt")


def generate_blocker_id() -> str:
    return _generate_id("attempt_blocker")


def generate_receipt_id() -> str:
    return _generate_id("submission_receipt")


class ApplicationAttempt(Base):
    __tablename__ = "application_attempts"
    __table_args__ = (
        UniqueConstraint(
            "application_id",
            "packet_revision_id",
            name="uq_application_attempts_application_revision",
        ),
        UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_application_attempts_user_idempotency",
        ),
        Index(
            "ix_application_attempts_user_updated",
            "user_id",
            "updated_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    application_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    job_posting_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    packet_revision_id: Mapped[str] = mapped_column(
        String(48), nullable=False, index=True
    )
    application_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=AttemptStatus.CREATED.value,
        server_default=AttemptStatus.CREATED.value,
    )
    idempotency_key: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    form_opened_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ready_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    failed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    abandoned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ApplicationBlocker(Base):
    __tablename__ = "application_blockers"
    __table_args__ = (
        UniqueConstraint(
            "attempt_id",
            "idempotency_key",
            name="uq_application_blockers_attempt_idempotency",
        ),
        Index(
            "ix_application_blockers_attempt_status",
            "attempt_id",
            "status",
        ),
    )

    id: Mapped[str] = mapped_column(String(56), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    attempt_id: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    application_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    observation: Mapped[str] = mapped_column(String(2000), nullable=False)
    stop_reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    retryable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    next_strategy: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    required_user_action: Mapped[str | None] = mapped_column(
        String(1000), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=BlockerStatus.OPEN.value,
        server_default=BlockerStatus.OPEN.value,
    )
    idempotency_key: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class SubmissionReceipt(Base):
    __tablename__ = "submission_receipts"
    __table_args__ = (
        UniqueConstraint("attempt_id", name="uq_submission_receipts_attempt"),
        UniqueConstraint("application_id", name="uq_submission_receipts_application"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    attempt_id: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    application_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    packet_revision_id: Mapped[str] = mapped_column(
        String(48), nullable=False, index=True
    )
    confirmation_text: Mapped[str | None] = mapped_column(
        String(4000), nullable=True
    )
    confirmation_url: Mapped[str | None] = mapped_column(
        String(2048), nullable=True
    )
    application_number: Mapped[str | None] = mapped_column(
        String(240), nullable=True
    )
    screenshot_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, server_default=text("'{}'")
    )
    user_confirmed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    is_valid: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    validation_codes: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list, server_default=text("'[]'")
    )
    receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
