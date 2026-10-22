from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.api.timestamps import UtcTimestamp
from src.domain.ats_assistance import (
    AtsFieldAction,
    AtsFieldRisk,
    AtsProvider,
    AtsSessionStatus,
)


class AtsRetryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_completed_handoff: Literal[True]


class AtsFieldConfirmationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_keys: list[str] = Field(min_length=1, max_length=100)
    confirmed: Literal[True]


class AtsAuthorizationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmed: Literal[True]


class AtsSubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    authorization_token: str = Field(min_length=32, max_length=200)


class AtsFieldPlanRead(BaseModel):
    field_key: str
    label: str
    name: str
    input_type: str
    required: bool
    canonical_name: str
    risk: AtsFieldRisk
    action: AtsFieldAction
    source: str | None
    value: str | None
    reason: str
    options: list[str]


class AtsSessionRead(BaseModel):
    id: str
    user_id: str
    attempt_id: str
    application_id: str
    job_posting_id: str
    packet_revision_id: str
    application_url: str
    provider: AtsProvider
    status: AtsSessionStatus
    page_fingerprint: str
    plan_hash: str
    field_plan: list[AtsFieldPlanRead]
    handoff_reasons: list[dict[str, object]]
    final_summary: dict[str, object]
    authorization_expires_at: UtcTimestamp | None
    authorization_used: bool
    created_at: UtcTimestamp
    updated_at: UtcTimestamp
    inspected_at: UtcTimestamp
    prepared_at: UtcTimestamp | None
    authorized_at: UtcTimestamp | None
    submitted_at: UtcTimestamp | None
    failed_at: UtcTimestamp | None


class AtsAuthorizationGrantRead(BaseModel):
    session: AtsSessionRead
    authorization_token: str
    expires_at: UtcTimestamp
