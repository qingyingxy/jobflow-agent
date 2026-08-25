from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database import Base


class PacketStatus(StrEnum):
    DRAFT = "DRAFT"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class PacketDecisionType(StrEnum):
    APPROVE = "APPROVE"


PACKET_TRANSITIONS: dict[PacketStatus, frozenset[PacketStatus]] = {
    PacketStatus.DRAFT: frozenset({PacketStatus.NEEDS_REVIEW}),
    PacketStatus.NEEDS_REVIEW: frozenset(
        {PacketStatus.DRAFT, PacketStatus.APPROVED}
    ),
    PacketStatus.APPROVED: frozenset({PacketStatus.SUPERSEDED}),
    PacketStatus.SUPERSEDED: frozenset(),
}


def _generate_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:20]}"


def generate_packet_id() -> str:
    return _generate_id("packet")


def generate_packet_revision_id() -> str:
    return _generate_id("packet_revision")


def generate_packet_decision_id() -> str:
    return _generate_id("packet_decision")


class ApplicationPacket(Base):
    __tablename__ = "application_packets"
    __table_args__ = (
        UniqueConstraint(
            "application_id",
            name="uq_application_packets_application",
        ),
        Index(
            "ix_application_packets_user_updated",
            "user_id",
            "updated_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    application_id: Mapped[str] = mapped_column(String(40), nullable=False)
    job_posting_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    current_revision_id: Mapped[str] = mapped_column(String(48), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=PacketStatus.DRAFT.value,
        server_default=PacketStatus.DRAFT.value,
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


class PacketRevision(Base):
    __tablename__ = "packet_revisions"
    __table_args__ = (
        UniqueConstraint(
            "packet_id",
            "revision_number",
            name="uq_packet_revisions_packet_number",
        ),
        Index(
            "ix_packet_revisions_packet_created",
            "packet_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    packet_id: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    application_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    job_posting_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=PacketStatus.DRAFT.value,
        server_default=PacketStatus.DRAFT.value,
    )
    supersedes_revision_id: Mapped[str | None] = mapped_column(
        String(48), nullable=True, index=True
    )
    job_analysis_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    analysis_version: Mapped[str] = mapped_column(String(80), nullable=False)
    analysis_input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    jd_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    profile_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    resume_version_id: Mapped[str | None] = mapped_column(
        String(48), nullable=True, index=True
    )
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    job_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    analysis_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    profile_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    resume_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    evidence_snapshots: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list, server_default=text("'[]'")
    )
    form_answer_snapshots: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list, server_default=text("'[]'")
    )
    open_questions: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list, server_default=text("'[]'")
    )
    risk_snapshots: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list, server_default=text("'[]'")
    )
    confirmation_items: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list, server_default=text("'[]'")
    )
    blockers: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list, server_default=text("'[]'")
    )
    created_by_actor: Mapped[str] = mapped_column(
        String(24), nullable=False, default="user", server_default="user"
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
    submitted_for_review_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    superseded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class PacketDecision(Base):
    __tablename__ = "packet_decisions"
    __table_args__ = (
        UniqueConstraint(
            "revision_id",
            "decision",
            name="uq_packet_decisions_revision_decision",
        ),
    )

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    packet_id: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    revision_id: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    application_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    decision: Mapped[str] = mapped_column(String(24), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
