from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Index, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database import Base


class AtsProvider(StrEnum):
    GREENHOUSE = "GREENHOUSE"
    LEVER = "LEVER"


class AtsSessionStatus(StrEnum):
    INSPECTED = "INSPECTED"
    NEEDS_USER = "NEEDS_USER"
    READY_FOR_APPROVAL = "READY_FOR_APPROVAL"
    AUTHORIZED = "AUTHORIZED"
    SUBMITTING = "SUBMITTING"
    SUBMITTED = "SUBMITTED"
    FAILED = "FAILED"


class AtsFieldRisk(StrEnum):
    LOW = "LOW"
    PERSONAL = "PERSONAL"
    HIGH_IMPACT = "HIGH_IMPACT"
    LEGAL = "LEGAL"


class AtsFieldAction(StrEnum):
    FILL = "FILL"
    NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"
    NEEDS_VALUE = "NEEDS_VALUE"
    NEEDS_USER = "NEEDS_USER"
    SKIP = "SKIP"


def _generate_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:20]}"


def generate_ats_session_id() -> str:
    return _generate_id("ats_session")


def generate_ats_authorization_id() -> str:
    return _generate_id("ats_auth")


class AtsAssistanceSession(Base):
    __tablename__ = "ats_assistance_sessions"
    __table_args__ = (
        Index("ix_ats_sessions_user_updated", "user_id", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    attempt_id: Mapped[str] = mapped_column(
        String(48), nullable=False, unique=True, index=True
    )
    application_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    job_posting_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    packet_revision_id: Mapped[str] = mapped_column(
        String(48), nullable=False, index=True
    )
    application_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    provider: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=AtsSessionStatus.INSPECTED.value,
        server_default=AtsSessionStatus.INSPECTED.value,
    )
    page_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    plan_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    field_plan: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list, server_default=text("'[]'")
    )
    field_confirmations: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list, server_default=text("'[]'")
    )
    handoff_reasons: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list, server_default=text("'[]'")
    )
    final_summary: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, server_default=text("'{}'")
    )
    current_authorization_id: Mapped[str | None] = mapped_column(
        String(48), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    inspected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    prepared_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    authorized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    failed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AtsSubmissionAuthorization(Base):
    __tablename__ = "ats_submission_authorizations"
    __table_args__ = (
        Index("ix_ats_authorizations_session_created", "session_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    session_id: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    attempt_id: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    job_posting_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    packet_revision_id: Mapped[str] = mapped_column(
        String(48), nullable=False, index=True
    )
    application_url_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    page_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    plan_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    binding_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    token_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
