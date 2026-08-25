from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import (
    Boolean,
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


class FollowUpEventType(StrEnum):
    ASSESSMENT = "ASSESSMENT"
    WRITTEN_TEST = "WRITTEN_TEST"
    INTERVIEW = "INTERVIEW"
    MATERIAL_DEADLINE = "MATERIAL_DEADLINE"
    OUTREACH = "OUTREACH"
    CUSTOM = "CUSTOM"


class FollowUpStatus(StrEnum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class FollowUpEffectiveStatus(StrEnum):
    PENDING = "PENDING"
    OVERDUE = "OVERDUE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


FOLLOW_UP_TRANSITIONS: dict[FollowUpStatus, frozenset[FollowUpStatus]] = {
    FollowUpStatus.PENDING: frozenset(
        {FollowUpStatus.COMPLETED, FollowUpStatus.CANCELLED}
    ),
    FollowUpStatus.COMPLETED: frozenset(),
    FollowUpStatus.CANCELLED: frozenset(),
}


def generate_follow_up_id() -> str:
    return f"follow_up_{uuid4().hex[:20]}"


class FollowUpTask(Base):
    __tablename__ = "follow_up_tasks"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_follow_up_tasks_user_idempotency",
        ),
        UniqueConstraint(
            "user_id",
            "application_id",
            "event_type",
            "scheduled_at",
            "title",
            name="uq_follow_up_tasks_natural_identity",
        ),
        Index(
            "ix_follow_up_tasks_user_scheduled",
            "user_id",
            "scheduled_at",
        ),
        Index(
            "ix_follow_up_tasks_application_scheduled",
            "application_id",
            "scheduled_at",
        ),
        Index(
            "ix_follow_up_tasks_user_status_scheduled",
            "user_id",
            "status",
            "scheduled_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    application_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    job_posting_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, default="Asia/Shanghai", server_default="Asia/Shanghai"
    )
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    all_day: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    contact_name: Mapped[str | None] = mapped_column(String(240), nullable=True)
    contact_detail: Mapped[str | None] = mapped_column(String(500), nullable=True)
    channel: Mapped[str | None] = mapped_column(String(80), nullable=True)
    next_action: Mapped[str] = mapped_column(String(1000), nullable=False)
    notes: Mapped[str | None] = mapped_column(String(4000), nullable=True)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=FollowUpStatus.PENDING.value,
        server_default=FollowUpStatus.PENDING.value,
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
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

