from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.domain.application_packet import (
    PacketDecisionType,
    PacketStatus,
)
from src.domain.materials import AnswerSensitivity


class OpenQuestionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = Field(default=None, min_length=1, max_length=80)
    question: str = Field(min_length=1, max_length=1000)
    answer: str | None = Field(default=None, max_length=12000)
    sensitivity: AnswerSensitivity = AnswerSensitivity.STANDARD
    confirmed: bool = False

    @model_validator(mode="after")
    def require_answer_for_confirmation(self) -> OpenQuestionInput:
        self.question = self.question.strip()
        if self.answer is not None:
            self.answer = self.answer.strip() or None
        if self.confirmed and not self.answer:
            raise ValueError("确认开放题前必须填写答案")
        return self


class PacketGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resume_version_id: str | None = Field(default=None, max_length=48)
    evidence_ids: list[str] | None = Field(default=None, max_length=100)
    answer_entry_ids: list[str] | None = Field(default=None, max_length=100)
    open_questions: list[OpenQuestionInput] = Field(default_factory=list, max_length=50)


class PacketRevisionEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resume_version_id: str | None = Field(default=None, max_length=48)
    evidence_ids: list[str] | None = Field(default=None, max_length=100)
    answer_entry_ids: list[str] | None = Field(default=None, max_length=100)
    open_questions: list[OpenQuestionInput] | None = Field(default=None, max_length=50)

    @model_validator(mode="after")
    def require_change(self) -> PacketRevisionEditRequest:
        if not self.model_fields_set:
            raise ValueError("至少提供一个需要更新的投递包项目")
        return self


class PacketNewRevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resume_version_id: str | None = Field(default=None, max_length=48)
    evidence_ids: list[str] | None = Field(default=None, max_length=100)
    answer_entry_ids: list[str] | None = Field(default=None, max_length=100)
    open_questions: list[OpenQuestionInput] | None = Field(default=None, max_length=50)


class PacketApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmed: Literal[True]


class PacketDecisionRead(BaseModel):
    id: str
    decision: PacketDecisionType
    actor_type: Literal["user"]
    created_at: datetime


class PacketRevisionRead(BaseModel):
    id: str
    packet_id: str
    application_id: str
    job_posting_id: str
    revision_number: int
    status: PacketStatus
    supersedes_revision_id: str | None
    job_analysis_id: str
    analysis_version: str
    analysis_input_hash: str
    jd_content_hash: str
    profile_revision: int
    resume_version_id: str | None
    source_fingerprint: str
    payload_hash: str
    job_snapshot: dict[str, object]
    analysis_snapshot: dict[str, object]
    profile_snapshot: dict[str, object]
    resume_snapshot: dict[str, object]
    evidence_snapshots: list[dict[str, object]]
    form_answer_snapshots: list[dict[str, object]]
    open_questions: list[dict[str, object]]
    risk_snapshots: list[dict[str, object]]
    confirmation_items: list[dict[str, object]]
    blockers: list[dict[str, object]]
    created_by_actor: Literal["user", "agent"]
    source_changed: bool
    source_change_codes: list[str]
    decisions: list[PacketDecisionRead]
    created_at: datetime
    updated_at: datetime
    submitted_for_review_at: datetime | None
    approved_at: datetime | None
    superseded_at: datetime | None


class ApplicationPacketRead(BaseModel):
    id: str
    user_id: str
    application_id: str
    job_posting_id: str
    current_revision_id: str
    status: PacketStatus
    current_revision: PacketRevisionRead
    revisions: list[PacketRevisionRead]
    created_at: datetime
    updated_at: datetime
