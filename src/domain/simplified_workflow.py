from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

ShortText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=160),
]
ResumeExperienceType = Literal[
    "education",
    "project",
    "internship",
    "employment",
    "research",
    "open_source",
    "competition",
    "skill",
    "other",
]
ResumeEvidenceOrigin = Literal["extracted", "manual", "user_corrected"]
TargetJobType = Literal["internship", "campus", "full_time"]


class ApplicationRecommendation(StrEnum):
    RECOMMENDED = "recommended_application"
    CONSIDER = "consider"
    NOT_RECOMMENDED = "not_recommended"
    INSUFFICIENT_INFORMATION = "insufficient_information"


class ApplicationBoardStatus(StrEnum):
    TO_DECIDE = "to_decide"
    PLANNED = "planned"
    APPLIED = "applied"
    INTERVIEWING = "interviewing"
    CLOSED = "closed"


class ApplicationOutcome(StrEnum):
    SKIPPED = "skipped"
    JOB_CLOSED = "job_closed"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    OFFERED = "offered"


class InitialJobSearchProfile(BaseModel):
    """The four structured onboarding conditions; resume is a separate asset."""

    model_config = ConfigDict(extra="forbid")

    target_direction: ShortText
    target_cities: list[ShortText] = Field(min_length=1, max_length=3)
    accepts_remote: bool = False
    graduation_year: int = Field(ge=1900, le=2200)
    target_job_type: TargetJobType

    @field_validator("target_cities")
    @classmethod
    def normalize_cities(cls, value: list[str]) -> list[str]:
        cities: list[str] = []
        seen: set[str] = set()
        for item in value:
            city = item.strip()
            key = city.casefold()
            if key not in seen:
                cities.append(city)
                seen.add(key)
        if not cities:
            raise ValueError("至少需要一个目标城市")
        return cities


class ResumeSourceLocation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page_number: int | None = Field(default=None, ge=1)
    section: ShortText | None = None
    start_char: int | None = Field(default=None, ge=0)
    end_char: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_offsets(self) -> ResumeSourceLocation:
        if (self.start_char is None) != (self.end_char is None):
            raise ValueError("start_char 和 end_char 必须同时提供")
        if (
            self.start_char is not None
            and self.end_char is not None
            and self.end_char <= self.start_char
        ):
            raise ValueError("end_char 必须大于 start_char")
        return self


class ResumeEvidenceDraft(BaseModel):
    """One source-grounded resume item before local IDs are assigned."""

    model_config = ConfigDict(extra="forbid")

    experience_type: ResumeExperienceType
    title: ShortText
    organization: ShortText | None = None
    date_text: ShortText | None = None
    source_text: str = Field(min_length=1)
    skills: list[ShortText] = Field(default_factory=list)
    location: ResumeSourceLocation
    origin: ResumeEvidenceOrigin = "extracted"

    @field_validator("source_text")
    @classmethod
    def normalize_source_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("简历证据原文不能为空")
        return normalized

    @field_validator("skills")
    @classmethod
    def normalize_skills(cls, value: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for item in value:
            skill = item.strip()
            key = skill.casefold()
            if key not in seen:
                result.append(skill)
                seen.add(key)
        return result


class ResumeEvidence(ResumeEvidenceDraft):
    evidence_id: str = Field(pattern=r"^evidence_[a-zA-Z0-9_-]{1,64}$")
    resume_version_id: str = Field(min_length=1, max_length=64)
