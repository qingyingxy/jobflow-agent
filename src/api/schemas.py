from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.domain.analysis import AnalysisRisk
from src.domain.application import (
    ApplicationStatus,
    CandidateStatus,
)
from src.domain.eligibility import EligibilityResult, SearchPreferences
from src.domain.job import StructuredJobDescription, normalize_job_text
from src.domain.matching import MatchScore, RequirementMatch
from src.domain.suggestion import (
    SuggestionDecision,
    SuggestionStatus,
    SuggestionTargetInput,
)


class ProfileUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=100)
    graduation_year: int | None = Field(default=None, ge=2000, le=2100)
    degree: str | None = Field(default=None, max_length=100)
    major: str | None = Field(default=None, max_length=100)
    search_preferences: SearchPreferences = Field(default_factory=SearchPreferences)


class ProfileRead(ProfileUpdate):
    model_config = ConfigDict(from_attributes=True)

    user_id: str
    search_preferences: SearchPreferences = Field(default_factory=SearchPreferences)
    created_at: datetime
    updated_at: datetime


class EvidenceCreate(BaseModel):
    type: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=1, max_length=160)
    claim: str = Field(min_length=1)
    skills: list[str] = Field(default_factory=list)
    source: str = Field(default="manual", min_length=1, max_length=160)


class EvidenceUpdate(BaseModel):
    type: str | None = Field(default=None, min_length=1, max_length=40)
    title: str | None = Field(default=None, min_length=1, max_length=160)
    claim: str | None = Field(default=None, min_length=1)
    skills: list[str] | None = None
    source: str | None = Field(default=None, min_length=1, max_length=160)


class EvidenceRead(EvidenceCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    created_at: datetime
    updated_at: datetime


class JobTextImportRequest(BaseModel):
    source_url: str | None = Field(default=None, max_length=2048)
    source_type: Literal["manual_text"] = "manual_text"
    company: str | None = Field(default=None, max_length=160)
    title: str | None = Field(default=None, max_length=160)
    raw_content: str = Field(min_length=20)

    @field_validator("raw_content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        return normalize_job_text(value)


class JobURLImportRequest(BaseModel):
    source_url: str = Field(min_length=1, max_length=2048)
    company: str | None = Field(default=None, max_length=160)
    title: str | None = Field(default=None, max_length=160)


class DiscoveryRunCreateRequest(BaseModel):
    source_url: str = Field(min_length=1, max_length=2048)
    company: str | None = Field(default=None, max_length=160)


class JobPostingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_url: str | None
    source_type: str
    source_id: str | None = None
    source_job_id: str | None = None
    company: str | None
    title: str | None
    locations: list[str] = Field(default_factory=list)
    job_type: str | None = None
    published_at: datetime | None = None
    last_seen_at: datetime | None = None
    raw_content: str
    content_hash: str
    retrieved_at: datetime
    trace_id: str
    created_at: datetime
    updated_at: datetime


class JobSummary(BaseModel):
    id: str
    company: str | None
    title: str | None
    source_url: str | None
    source_id: str | None = None
    locations: list[str] = Field(default_factory=list)
    job_type: str | None = None
    published_at: datetime | None = None
    last_seen_at: datetime | None = None


class CandidateCreateRequest(BaseModel):
    job_posting_id: str = Field(min_length=1, max_length=40)


class CandidateStatusUpdate(BaseModel):
    status: CandidateStatus


class CandidateRead(BaseModel):
    id: str
    user_id: str
    job_posting_id: str
    status: CandidateStatus
    available_transitions: list[CandidateStatus]
    job: JobSummary
    created_at: datetime
    updated_at: datetime


class DiscoveryRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    source: str
    source_url: str
    status: str
    discovered_count: int
    new_count: int
    duplicate_count: int
    failure_summary: str | None
    started_at: datetime
    finished_at: datetime | None
    created_at: datetime


class DomainEventRead(BaseModel):
    id: str
    entity_type: str
    entity_id: str
    event_type: str
    payload: dict[str, object]
    created_at: datetime


class ApplicationStatusUpdate(BaseModel):
    status: ApplicationStatus
    next_action: str | None = Field(default=None, max_length=240)


class ApplicationRead(BaseModel):
    id: str
    candidate_job_id: str
    job_posting_id: str
    status: ApplicationStatus
    candidate_status: CandidateStatus
    next_action: str | None
    available_transitions: list[ApplicationStatus]
    job: JobSummary
    events: list[DomainEventRead]
    created_at: datetime
    updated_at: datetime


class SuggestionCreateRequest(SuggestionTargetInput):
    """The latest valid analysis is resolved from the application."""


class SuggestionDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: SuggestionDecision
    final_text: str | None = Field(default=None, max_length=12000)

    @field_validator("final_text")
    @classmethod
    def normalize_final_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_decision_text(self) -> SuggestionDecisionRequest:
        if self.decision is SuggestionDecision.EDIT and not self.final_text:
            raise ValueError("编辑后接受必须提供 final_text")
        if self.decision is not SuggestionDecision.EDIT and self.final_text is not None:
            raise ValueError("accept 或 reject 决策不能携带 final_text")
        return self


class SuggestionRead(BaseModel):
    id: str
    user_id: str
    application_id: str
    job_analysis_id: str
    target_type: str
    target_label: str | None
    original_text: str
    suggestion_text: str
    evidence_ids: list[str]
    status: SuggestionStatus
    final_text: str | None
    agent_run_id: str
    created_at: datetime
    updated_at: datetime


class JobParseResponse(BaseModel):
    job_id: str
    parse_result_id: str
    agent_run_id: str
    model: str
    schema_version: str
    parser_version: str
    prompt_version: str
    structured_jd: StructuredJobDescription


class JobAnalysisResponse(BaseModel):
    analysis_id: str
    job: JobPostingRead
    parse_result_id: str
    analysis_version: str
    agent_run_ids: list[str]
    structured_jd: StructuredJobDescription
    eligibility: EligibilityResult
    matches: list[RequirementMatch]
    score: MatchScore
    risks: list[AnalysisRisk]
    missing_information: list[str]
    created_at: datetime
    invalidated_at: datetime | None
