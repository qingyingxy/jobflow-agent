from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.domain.job import FieldEvidence, StructuredJobDescription

JobType = Literal["campus", "internship", "full_time", "part_time"]
EligibilityStatus = Literal["pass", "fail", "unknown"]


class SearchPreferences(BaseModel):
    """Typed preferences; schedule fields are retained for payload compatibility."""

    model_config = ConfigDict(extra="forbid")

    preferred_locations: list[str] | None = None
    job_types: list[JobType] | None = None
    # Display-only in the simplified flow. Resumes do not reliably contain
    # availability, so these values must not gate automatic eligibility.
    earliest_start_date: date | None = None
    weekly_days: int | None = Field(default=None, ge=1, le=7)
    internship_duration_months: int | None = Field(default=None, ge=0)

    # Kept for compatibility with the M02 profile payload. They are display
    # preferences, not inputs to hard qualification rules.
    target_roles: list[str] | None = None
    locations: list[str] | None = None

    @field_validator("preferred_locations", "target_roles", "locations")
    @classmethod
    def normalize_text_list(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized = [item.strip() for item in value]
        if any(not item for item in normalized):
            raise ValueError("偏好列表不能包含空字符串")
        return normalized

    @model_validator(mode="after")
    def normalize_legacy_locations(self) -> SearchPreferences:
        if (
            self.preferred_locations is not None
            and self.locations is not None
            and self.preferred_locations != self.locations
        ):
            raise ValueError("preferred_locations 与旧字段 locations 不一致")
        if self.preferred_locations is None and self.locations is not None:
            self.preferred_locations = list(self.locations)
        return self


class CandidateProfileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    graduation_year: int | None = Field(default=None, ge=1900, le=2200)
    degree: str | None = Field(default=None, max_length=100)
    major: str | None = Field(default=None, max_length=100)


class EligibilityInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: CandidateProfileInput
    preferences: SearchPreferences
    job: StructuredJobDescription


class EligibilityCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_name: str = Field(min_length=1, max_length=80)
    field: str = Field(min_length=1, max_length=80)
    result: EligibilityStatus
    reason: str = Field(min_length=1)
    jd_evidence: list[FieldEvidence] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)


class EligibilityResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    eligible: EligibilityStatus
    checks: list[EligibilityCheck] = Field(min_length=1)
