from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.domain.application_attempt import (
    AttemptStatus,
    BlockerStatus,
)


class AttemptCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    application_url: str | None = Field(default=None, max_length=2048)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=80)


class AttemptStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: AttemptStatus


class BlockerCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str = Field(min_length=1, max_length=64)
    observation: str = Field(min_length=1, max_length=2000)
    stop_reason: str = Field(min_length=1, max_length=1000)
    retryable: bool = False
    next_strategy: str | None = Field(default=None, max_length=1000)
    required_user_action: str | None = Field(default=None, max_length=1000)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=80)


class RedactedScreenshotMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_name: str | None = Field(default=None, max_length=240)
    content_type: Literal["image/png", "image/jpeg", "image/webp"]
    size_bytes: int = Field(gt=0, le=10 * 1024 * 1024)
    sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-fA-F]{64}$")
    redacted: Literal[True]


class ReceiptCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation_text: str | None = Field(default=None, max_length=4000)
    confirmation_url: str | None = Field(default=None, max_length=2048)
    application_number: str | None = Field(default=None, max_length=240)
    screenshot_metadata: RedactedScreenshotMetadata | None = None
    user_confirmed: Literal[True]
    captured_at: datetime | None = None


class AttemptChecklistRead(BaseModel):
    code: str
    label: str
    complete: bool
    blocking: bool


class ApplicationBlockerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    attempt_id: str
    application_id: str
    category: str
    observation: str
    stop_reason: str
    retryable: bool
    next_strategy: str | None
    required_user_action: str | None
    status: BlockerStatus
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None


class SubmissionReceiptRead(BaseModel):
    id: str
    attempt_id: str
    application_id: str
    packet_revision_id: str
    confirmation_text: str | None
    confirmation_url: str | None
    application_number: str | None
    screenshot_metadata: dict[str, object]
    user_confirmed: bool
    is_valid: bool
    validation_codes: list[str]
    receipt_hash: str
    captured_at: datetime
    created_at: datetime


class ApplicationAttemptRead(BaseModel):
    id: str
    user_id: str
    application_id: str
    job_posting_id: str
    packet_revision_id: str
    application_url: str
    status: AttemptStatus
    available_transitions: list[AttemptStatus]
    checklist: list[AttemptChecklistRead]
    blockers: list[ApplicationBlockerRead]
    receipt: SubmissionReceiptRead | None
    created_at: datetime
    updated_at: datetime
    form_opened_at: datetime | None
    ready_at: datetime | None
    submitted_at: datetime | None
    failed_at: datetime | None
    abandoned_at: datetime | None

