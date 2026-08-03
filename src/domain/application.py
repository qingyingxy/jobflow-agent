from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, String, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database import Base


class CandidateStatus(StrEnum):
    DISCOVERED = "DISCOVERED"
    SAVED = "SAVED"
    IGNORED = "IGNORED"
    CONVERTED = "CONVERTED"


class ApplicationStatus(StrEnum):
    PREPARING = "PREPARING"
    SUBMITTED = "SUBMITTED"
    ASSESSMENT = "ASSESSMENT"
    INTERVIEW = "INTERVIEW"
    OFFER = "OFFER"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


CANDIDATE_TRANSITIONS: dict[CandidateStatus, frozenset[CandidateStatus]] = {
    CandidateStatus.DISCOVERED: frozenset(
        {CandidateStatus.SAVED, CandidateStatus.IGNORED, CandidateStatus.CONVERTED}
    ),
    CandidateStatus.SAVED: frozenset(
        {CandidateStatus.IGNORED, CandidateStatus.CONVERTED}
    ),
    CandidateStatus.IGNORED: frozenset({CandidateStatus.SAVED}),
    CandidateStatus.CONVERTED: frozenset(),
}


APPLICATION_TRANSITIONS: dict[ApplicationStatus, frozenset[ApplicationStatus]] = {
    ApplicationStatus.PREPARING: frozenset(
        {ApplicationStatus.SUBMITTED, ApplicationStatus.WITHDRAWN}
    ),
    ApplicationStatus.SUBMITTED: frozenset(
        {
            ApplicationStatus.ASSESSMENT,
            ApplicationStatus.INTERVIEW,
            ApplicationStatus.REJECTED,
            ApplicationStatus.WITHDRAWN,
        }
    ),
    ApplicationStatus.ASSESSMENT: frozenset(
        {
            ApplicationStatus.INTERVIEW,
            ApplicationStatus.REJECTED,
            ApplicationStatus.WITHDRAWN,
        }
    ),
    ApplicationStatus.INTERVIEW: frozenset(
        {
            ApplicationStatus.INTERVIEW,
            ApplicationStatus.OFFER,
            ApplicationStatus.REJECTED,
            ApplicationStatus.WITHDRAWN,
        }
    ),
    ApplicationStatus.OFFER: frozenset(),
    ApplicationStatus.REJECTED: frozenset(),
    ApplicationStatus.WITHDRAWN: frozenset(),
}


def generate_candidate_id() -> str:
    return f"candidate_{uuid4().hex[:20]}"


def generate_application_id() -> str:
    return f"application_{uuid4().hex[:20]}"


def generate_domain_event_id() -> str:
    return f"event_{uuid4().hex[:20]}"


class CandidateJob(Base):
    __tablename__ = "candidate_jobs"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "job_posting_id",
            name="uq_candidate_jobs_user_job_posting",
        ),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    job_posting_id: Mapped[str] = mapped_column(
        String(40), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=CandidateStatus.SAVED.value,
        server_default=CandidateStatus.SAVED.value,
    )
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


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    candidate_job_id: Mapped[str] = mapped_column(
        String(40), nullable=False, unique=True, index=True
    )
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=ApplicationStatus.PREPARING.value,
        server_default=ApplicationStatus.PREPARING.value,
    )
    next_action: Mapped[str | None] = mapped_column(String(240), nullable=True)
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


class DomainEvent(Base):
    __tablename__ = "domain_events"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        server_default=text("'{}'"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
