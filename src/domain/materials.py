from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database import Base


class PrivateFieldState(StrEnum):
    MISSING = "missing"
    PROVIDED = "provided"
    NOT_APPLICABLE = "not_applicable"
    DECLINED_TO_STORE = "declined_to_store"


class VoluntaryDisclosurePolicy(StrEnum):
    ASK_EACH_TIME = "ask_each_time"
    PREFER_NOT_TO_ANSWER = "prefer_not_to_answer"
    ALLOW_USER_ENTRY = "allow_user_entry"


class AnswerScope(StrEnum):
    GENERAL = "general"
    JOB_FAMILY = "job_family"
    COMPANY = "company"
    ROLE = "role"


class AnswerSensitivity(StrEnum):
    STANDARD = "standard"
    PERSONAL = "personal"
    HIGH_IMPACT = "high_impact"


def _generate_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:20]}"


def generate_resume_asset_id() -> str:
    return _generate_id("resume_asset")


def generate_resume_version_id() -> str:
    return _generate_id("resume_version")


def generate_answer_bank_id() -> str:
    return _generate_id("answer")


class CandidatePrivateProfile(Base):
    __tablename__ = "candidate_private_profiles"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    revision: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    contact_email_state: Mapped[str] = mapped_column(
        String(32), nullable=False, default=PrivateFieldState.MISSING.value
    )
    contact_email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    contact_phone_state: Mapped[str] = mapped_column(
        String(32), nullable=False, default=PrivateFieldState.MISSING.value
    )
    contact_phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    current_status_state: Mapped[str] = mapped_column(
        String(32), nullable=False, default=PrivateFieldState.MISSING.value
    )
    current_status: Mapped[str | None] = mapped_column(String(160), nullable=True)
    availability_date_state: Mapped[str] = mapped_column(
        String(32), nullable=False, default=PrivateFieldState.MISSING.value
    )
    availability_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    work_authorization_state: Mapped[str] = mapped_column(
        String(32), nullable=False, default=PrivateFieldState.MISSING.value
    )
    work_authorization: Mapped[str | None] = mapped_column(
        String(240), nullable=True
    )
    sponsorship_required_state: Mapped[str] = mapped_column(
        String(32), nullable=False, default=PrivateFieldState.MISSING.value
    )
    sponsorship_required: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    salary_strategy_state: Mapped[str] = mapped_column(
        String(32), nullable=False, default=PrivateFieldState.MISSING.value
    )
    salary_strategy: Mapped[str | None] = mapped_column(String(240), nullable=True)
    relocation_willing_state: Mapped[str] = mapped_column(
        String(32), nullable=False, default=PrivateFieldState.MISSING.value
    )
    relocation_willing: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    voluntary_disclosure_policy: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default=VoluntaryDisclosurePolicy.ASK_EACH_TIME.value,
        server_default=VoluntaryDisclosurePolicy.ASK_EACH_TIME.value,
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


class ResumeAsset(Base):
    __tablename__ = "resume_assets"
    __table_args__ = (
        UniqueConstraint("user_id", "sha256", name="uq_resume_assets_user_hash"),
    )

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    original_filename: Mapped[str] = mapped_column(String(180), nullable=False)
    media_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(240), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ResumeVersion(Base):
    __tablename__ = "resume_versions"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "version_number", name="uq_resume_versions_user_number"
        ),
    )

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    asset_id: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    job_family: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source_version_id: Mapped[str | None] = mapped_column(
        String(48), nullable=True, index=True
    )
    generation_reason: Mapped[str] = mapped_column(String(240), nullable=False)
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
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


class AnswerBankEntry(Base):
    __tablename__ = "answer_bank_entries"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "normalized_question_pattern",
            "scope_type",
            "scope_value",
            name="uq_answer_bank_user_question_scope",
        ),
    )

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    question_pattern: Mapped[str] = mapped_column(String(500), nullable=False)
    normalized_question_pattern: Mapped[str] = mapped_column(
        String(500), nullable=False
    )
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    scope_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=AnswerScope.GENERAL.value,
        server_default=AnswerScope.GENERAL.value,
    )
    scope_value: Mapped[str] = mapped_column(
        String(160), nullable=False, default="", server_default=""
    )
    sensitivity: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=AnswerSensitivity.STANDARD.value,
        server_default=AnswerSensitivity.STANDARD.value,
    )
    confirmed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
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
