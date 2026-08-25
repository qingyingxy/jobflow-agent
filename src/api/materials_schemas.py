from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.domain.materials import (
    AnswerScope,
    AnswerSensitivity,
    PrivateFieldState,
    VoluntaryDisclosurePolicy,
)


class PrivateStringField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: PrivateFieldState
    value: str | None = Field(default=None, max_length=240)

    @model_validator(mode="after")
    def validate_state_and_value(self) -> PrivateStringField:
        if self.state is PrivateFieldState.PROVIDED:
            if self.value is None or not self.value.strip():
                raise ValueError("provided 状态必须提供值")
            self.value = self.value.strip()
        elif self.value is not None:
            raise ValueError("非 provided 状态不能携带值")
        return self


class PrivateEmailField(PrivateStringField):
    value: str | None = Field(default=None, max_length=254)

    @field_validator("value")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        candidate = value.strip()
        if candidate.count("@") != 1 or "." not in candidate.rsplit("@", 1)[1]:
            raise ValueError("邮箱格式无效")
        return candidate


class PrivatePhoneField(PrivateStringField):
    value: str | None = Field(default=None, max_length=40)

    @field_validator("value")
    @classmethod
    def validate_phone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        candidate = value.strip()
        digits = sum(character.isdigit() for character in candidate)
        if digits < 6:
            raise ValueError("联系电话格式无效")
        return candidate


class PrivateDateField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: PrivateFieldState
    value: date | None = None

    @model_validator(mode="after")
    def validate_state_and_value(self) -> PrivateDateField:
        if self.state is PrivateFieldState.PROVIDED and self.value is None:
            raise ValueError("provided 状态必须提供日期")
        if self.state is not PrivateFieldState.PROVIDED and self.value is not None:
            raise ValueError("非 provided 状态不能携带日期")
        return self


class PrivateBooleanField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: PrivateFieldState
    value: bool | None = None

    @model_validator(mode="after")
    def validate_state_and_value(self) -> PrivateBooleanField:
        if self.state is PrivateFieldState.PROVIDED and self.value is None:
            raise ValueError("provided 状态必须提供布尔值")
        if self.state is not PrivateFieldState.PROVIDED and self.value is not None:
            raise ValueError("非 provided 状态不能携带布尔值")
        return self


class CandidatePrivateProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contact_email: PrivateEmailField | None = None
    contact_phone: PrivatePhoneField | None = None
    current_status: PrivateStringField | None = None
    availability_date: PrivateDateField | None = None
    work_authorization: PrivateStringField | None = None
    sponsorship_required: PrivateBooleanField | None = None
    salary_strategy: PrivateStringField | None = None
    relocation_willing: PrivateBooleanField | None = None
    voluntary_disclosure_policy: VoluntaryDisclosurePolicy | None = None

    @model_validator(mode="after")
    def require_change(self) -> CandidatePrivateProfileUpdate:
        if not self.model_fields_set:
            raise ValueError("至少提供一个需要更新的字段")
        for field_name in self.model_fields_set:
            if getattr(self, field_name) is None:
                raise ValueError(f"{field_name} 不能设置为空")
        return self


class ConfirmationItem(BaseModel):
    field: str
    state: PrivateFieldState
    reason: Literal[
        "missing_high_impact_field",
        "declined_to_store_requires_runtime_confirmation",
    ]


class CandidatePrivateProfileRead(BaseModel):
    user_id: str
    revision: int
    contact_email: PrivateEmailField
    contact_phone: PrivatePhoneField
    current_status: PrivateStringField
    availability_date: PrivateDateField
    work_authorization: PrivateStringField
    sponsorship_required: PrivateBooleanField
    salary_strategy: PrivateStringField
    relocation_willing: PrivateBooleanField
    voluntary_disclosure_policy: VoluntaryDisclosurePolicy
    readiness: Literal["ready", "needs_confirmation"]
    needs_confirmation: list[ConfirmationItem]
    created_at: datetime
    updated_at: datetime


class ResumeAssetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    original_filename: str
    media_type: str
    size_bytes: int
    sha256: str
    created_at: datetime


class ResumeVersionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str = Field(min_length=1, max_length=48)
    label: str = Field(min_length=1, max_length=120)
    job_family: str | None = Field(default=None, max_length=120)
    source_version_id: str | None = Field(default=None, max_length=48)
    generation_reason: str = Field(
        default="uploaded_by_user", min_length=1, max_length=240
    )
    is_default: bool = False


class ResumeVersionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str | None = Field(default=None, min_length=1, max_length=120)
    job_family: str | None = Field(default=None, max_length=120)
    generation_reason: str | None = Field(default=None, min_length=1, max_length=240)
    is_default: bool | None = None

    @model_validator(mode="after")
    def require_change(self) -> ResumeVersionUpdate:
        if not self.model_fields_set:
            raise ValueError("至少提供一个需要更新的字段")
        for field_name in self.model_fields_set - {"job_family"}:
            if getattr(self, field_name) is None:
                raise ValueError(f"{field_name} 不能设置为空")
        return self


class ResumeVersionRead(BaseModel):
    id: str
    user_id: str
    asset_id: str
    version_number: int
    label: str
    job_family: str | None
    source_version_id: str | None
    generation_reason: str
    is_default: bool
    asset: ResumeAssetRead
    created_at: datetime
    updated_at: datetime


class AnswerBankCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_pattern: str = Field(min_length=2, max_length=500)
    answer: str = Field(min_length=1, max_length=5000)
    scope_type: AnswerScope = AnswerScope.GENERAL
    scope_value: str = Field(default="", max_length=160)
    sensitivity: AnswerSensitivity = AnswerSensitivity.STANDARD
    confirmed: Literal[True]


class AnswerBankUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_pattern: str | None = Field(default=None, min_length=2, max_length=500)
    answer: str | None = Field(default=None, min_length=1, max_length=5000)
    scope_type: AnswerScope | None = None
    scope_value: str | None = Field(default=None, max_length=160)
    sensitivity: AnswerSensitivity | None = None
    confirmed: Literal[True]

    @model_validator(mode="after")
    def require_answer_change(self) -> AnswerBankUpdate:
        changed_fields = self.model_fields_set - {"confirmed"}
        if not changed_fields:
            raise ValueError("至少提供一个需要更新的答案字段")
        for field_name in changed_fields:
            if getattr(self, field_name) is None:
                raise ValueError(f"{field_name} 不能设置为空")
        return self


class AnswerBankRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    question_pattern: str
    answer: str
    scope_type: AnswerScope
    scope_value: str
    sensitivity: AnswerSensitivity
    confirmed_at: datetime
    created_at: datetime
    updated_at: datetime
