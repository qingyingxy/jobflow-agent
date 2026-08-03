from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import JSON, DateTime, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database import Base


class SuggestionStatus(StrEnum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class SuggestionDecision(StrEnum):
    ACCEPT = "accept"
    EDIT = "edit"
    REJECT = "reject"


class SuggestionTargetInput(BaseModel):
    """User-provided text that explicitly bounds a suggestion request."""

    model_config = ConfigDict(extra="forbid")

    original_text: str = Field(min_length=1, max_length=12000)
    target_type: str = Field(min_length=1, max_length=80)
    target_label: str | None = Field(default=None, max_length=160)

    @field_validator("original_text", "target_type", "target_label")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("文本不能为空")
        return normalized


class ResumeSuggestionModelOutput(BaseModel):
    """The only model-generated shape for a resume suggestion."""

    model_config = ConfigDict(extra="forbid")

    suggestion_text: str = Field(min_length=1, max_length=12000)
    evidence_ids: list[str] = Field(min_length=1, max_length=20)
    claims: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("suggestion_text")
    @classmethod
    def normalize_suggestion_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("建议文本不能为空")
        return normalized

    @field_validator("evidence_ids", "claims")
    @classmethod
    def normalize_items(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if any(not item for item in normalized):
            raise ValueError("列表不能包含空字符串")
        if len(set(normalized)) != len(normalized):
            raise ValueError("列表不能包含重复项")
        return normalized


def generate_suggestion_id() -> str:
    return f"suggestion_{uuid4().hex[:20]}"


class ResumeSuggestion(Base):
    """A user-scoped, human-gated suggestion; final_text is never model-owned."""

    __tablename__ = "resume_suggestions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    application_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    job_analysis_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(80), nullable=False)
    target_label: Mapped[str | None] = mapped_column(String(160), nullable=True)
    original_text: Mapped[str] = mapped_column(Text, nullable=False)
    suggestion_text: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_ids: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        server_default=text("'[]'"),
    )
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=SuggestionStatus.PENDING.value,
        server_default=SuggestionStatus.PENDING.value,
    )
    final_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    agent_run_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
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
