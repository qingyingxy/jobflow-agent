from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.domain.follow_up import (
    FollowUpEffectiveStatus,
    FollowUpEventType,
    FollowUpStatus,
)


class FollowUpCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: FollowUpEventType
    title: str = Field(min_length=1, max_length=240)
    scheduled_at: datetime
    timezone: str = Field(default="Asia/Shanghai", min_length=1, max_length=64)
    duration_minutes: int | None = Field(default=None, ge=5, le=1440)
    all_day: bool = False
    contact_name: str | None = Field(default=None, max_length=240)
    contact_detail: str | None = Field(default=None, max_length=500)
    channel: str | None = Field(default=None, max_length=80)
    next_action: str = Field(min_length=1, max_length=1000)
    notes: str | None = Field(default=None, max_length=4000)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=80)

    @model_validator(mode="after")
    def normalize_schedule(self) -> FollowUpCreateRequest:
        try:
            zone = ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError("时区必须是有效的 IANA timezone") from error
        if self.scheduled_at.tzinfo is None:
            self.scheduled_at = self.scheduled_at.replace(tzinfo=zone)
        self.scheduled_at = self.scheduled_at.astimezone(UTC)
        self.timezone = zone.key
        return self


class FollowUpUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: FollowUpEventType | None = None
    title: str | None = Field(default=None, min_length=1, max_length=240)
    scheduled_at: datetime | None = None
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    duration_minutes: int | None = Field(default=None, ge=5, le=1440)
    all_day: bool | None = None
    contact_name: str | None = Field(default=None, max_length=240)
    contact_detail: str | None = Field(default=None, max_length=500)
    channel: str | None = Field(default=None, max_length=80)
    next_action: str | None = Field(default=None, min_length=1, max_length=1000)
    notes: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def validate_update(self) -> FollowUpUpdateRequest:
        if not self.model_fields_set:
            raise ValueError("至少提供一个需要更新的字段")
        zone: ZoneInfo | None = None
        if self.timezone is not None:
            try:
                zone = ZoneInfo(self.timezone)
            except (ZoneInfoNotFoundError, ValueError) as error:
                raise ValueError("时区必须是有效的 IANA timezone") from error
            self.timezone = zone.key
        if self.scheduled_at is not None:
            if self.scheduled_at.tzinfo is None:
                if zone is None:
                    raise ValueError("无时区日期时间必须同时提供 timezone")
                self.scheduled_at = self.scheduled_at.replace(tzinfo=zone)
            self.scheduled_at = self.scheduled_at.astimezone(UTC)
        return self


class FollowUpTaskRead(BaseModel):
    id: str
    user_id: str
    application_id: str
    job_posting_id: str
    event_type: FollowUpEventType
    title: str
    scheduled_at: datetime
    local_scheduled_at: datetime
    timezone: str
    duration_minutes: int | None
    all_day: bool
    contact_name: str | None
    contact_detail: str | None
    channel: str | None
    next_action: str
    notes: str | None
    status: FollowUpEffectiveStatus
    base_status: FollowUpStatus
    is_overdue: bool
    available_actions: list[Literal["edit", "complete", "cancel"]]
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    cancelled_at: datetime | None


class FollowUpSummaryRead(BaseModel):
    timezone: str
    generated_at: datetime
    total_pending: int
    today: int
    overdue: int
    next_7_days: int
    next_30_days: int

