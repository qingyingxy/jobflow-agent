from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

from src.api.timestamps import UtcTimestamp
from src.domain.analysis import AnalysisRisk, JobDecision
from src.domain.application import (
    ApplicationStatus,
    CandidateStatus,
)
from src.domain.discovery import DiscoverySearchPlan, JobLeadStatus, LeadProvider
from src.domain.education import EducationRecord
from src.domain.eligibility import EligibilityResult, SearchPreferences
from src.domain.fact_provenance import FactProvenance
from src.domain.job import (
    JobAvailabilityStatus,
    JobVerificationStatus,
    StructuredJobDescription,
    normalize_job_text,
)
from src.domain.matching import MatchScore, RequirementMatch
from src.domain.suggestion import (
    SuggestionDecision,
    SuggestionStatus,
    SuggestionTargetInput,
)


class ProfileUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=100)
    graduation_year: int | None = Field(default=None, ge=1900, le=2200)
    degree: str | None = Field(default=None, max_length=100)
    major: str | None = Field(default=None, max_length=100)
    educations: list[EducationRecord] = Field(default_factory=list, max_length=20)
    education_history_complete: bool = False
    search_preferences: SearchPreferences = Field(default_factory=SearchPreferences)

    @field_validator("educations")
    @classmethod
    def unique_education_ids(cls, value: list[EducationRecord]) -> list[EducationRecord]:
        if len({item.id for item in value}) != len(value):
            raise ValueError("教育经历 ID 不能重复")
        return value


class ProfileRead(ProfileUpdate):
    model_config = ConfigDict(from_attributes=True)

    user_id: str
    search_preferences: SearchPreferences = Field(default_factory=SearchPreferences)
    created_at: UtcTimestamp
    updated_at: UtcTimestamp


class EvidenceCreate(BaseModel):
    type: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=1, max_length=160)
    claim: str = Field(min_length=1)
    skills: list[str] = Field(default_factory=list)
    source: str = Field(default="manual", min_length=1, max_length=160)


class EvidenceUpdate(BaseModel):
    keep_current: bool = False
    type: str | None = Field(default=None, min_length=1, max_length=40)
    title: str | None = Field(default=None, min_length=1, max_length=160)
    claim: str | None = Field(default=None, min_length=1)
    skills: list[str] | None = None
    source: str | None = Field(default=None, min_length=1, max_length=160)


class EvidenceRead(EvidenceCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    provenance: FactProvenance = Field(default_factory=FactProvenance)
    created_at: UtcTimestamp
    updated_at: UtcTimestamp


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


class DiscoverySearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    source_mode: Literal["official", "web"] = "official"
    search_goal_id: str | None = Field(default=None, max_length=40)
    search_goal_version: int | None = Field(default=None, ge=1)
    continue_company_id: str | None = Field(default=None, max_length=100)
    company_ids: list[str] | None = Field(default=None, min_length=1, max_length=40)

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        normalized = " ".join(value.split()).strip()
        if len(normalized) < 2:
            raise ValueError("搜索目标至少需要两个字符")
        return normalized

    @field_validator("company_ids")
    @classmethod
    def normalize_company_ids(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized: list[str] = []
        for source_id in value:
            clean_id = source_id.strip()
            if not clean_id or len(clean_id) > 50:
                raise ValueError("公司来源 ID 无效")
            if clean_id not in normalized:
                normalized.append(clean_id)
        if not normalized:
            raise ValueError("至少选择一家目标公司")
        return normalized


class JobLeadCreateRequest(BaseModel):
    provider: Literal["external_agent", "manual_url", "third_party"]
    source_url: str = Field(min_length=1, max_length=2048)
    discovery_run_id: str | None = Field(default=None, max_length=40)
    company_hint: str | None = Field(default=None, max_length=160)
    title_hint: str | None = Field(default=None, max_length=160)
    search_snippet: str | None = Field(default=None, max_length=2000)
    discovered_at: datetime | None = None


class ManualLeadHandoffRequest(BaseModel):
    raw_content: str = Field(min_length=20, max_length=200_000)
    company: str | None = Field(default=None, max_length=160)
    title: str | None = Field(default=None, max_length=160)
    locations: list[str] = Field(default_factory=list, max_length=20)
    job_type: Literal[
        "campus",
        "internship",
        "full_time",
        "part_time",
        "unknown",
    ] | None = None


class LeadVerificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    lead_id: str
    result: str
    source_url: str
    source_type: str | None
    content_hash: str | None
    field_evidence: dict[str, object] = Field(default_factory=dict)
    error_code: str | None
    error_reason: str | None
    checked_at: UtcTimestamp


class JobAvailabilityCheckRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    job_posting_id: str
    previous_status: JobAvailabilityStatus
    result_status: JobAvailabilityStatus
    evidence_type: str
    source_url: str | None
    content_hash: str | None
    failure_code: str | None
    failure_reason: str | None
    evidence: dict[str, object] = Field(default_factory=dict)
    checked_at: UtcTimestamp


class JobAvailabilityConfirmationRequest(BaseModel):
    status: Literal["ACTIVE", "CLOSED"]
    reason: str = Field(min_length=4, max_length=1000)


class JobLeadRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    discovery_run_id: str | None
    provider: LeadProvider
    source_id: str | None
    source_job_id: str | None
    source_url: str
    normalized_url: str
    company_hint: str | None
    title_hint: str | None
    search_snippet: str | None
    extracted_fields: dict[str, object] = Field(default_factory=dict)
    retry_state: dict[str, object] = Field(default_factory=dict)
    status: JobLeadStatus
    next_action: str
    job_posting_id: str | None
    failure_code: str | None
    failure_reason: str | None
    discovered_at: UtcTimestamp
    verified_at: UtcTimestamp | None
    created_at: UtcTimestamp
    updated_at: UtcTimestamp


    discovery_kind: Literal["job", "entry"] = "entry"
    source_label: str = "来源待核实"
    selection_status: Literal["DISCOVERED", "SAVED", "IGNORED"] = "DISCOVERED"

    @model_validator(mode="after")
    def describe_discovered_link(self):
        from src.services.job_url import canonical_job_url
        from src.services.lead_presentation import lead_discovery_kind, source_label
        self.normalized_url = canonical_job_url(self.source_url)
        if self.status == JobLeadStatus.NEEDS_USER and self.failure_code == "verification_budget_exhausted":
            self.status = JobLeadStatus.DEFERRED
            self.next_action = "retry_verification"
        self.discovery_kind = lead_discovery_kind(self)
        self.source_label = source_label(self.source_url)
        return self


class LeadSelectionUpdate(BaseModel):
    status: Literal["DISCOVERED", "SAVED", "IGNORED"]


class JobLeadDetailRead(JobLeadRead):
    verifications: list[LeadVerificationRead] = Field(default_factory=list)


class DiscoverySourceRead(BaseModel):
    id: str
    company: str
    priority: str
    search_mode: Literal["dedicated_adapter", "official_page"]


class JobPostingRead(BaseModel):
    recruitment_context: dict = Field(default_factory=dict)
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
    published_at: UtcTimestamp | None = None
    verification_status: JobVerificationStatus
    availability_status: JobAvailabilityStatus
    first_seen_at: UtcTimestamp | None = None
    last_seen_at: UtcTimestamp | None = None
    last_verified_at: UtcTimestamp | None = None
    availability_failure_count: int = 0
    last_availability_checked_at: UtcTimestamp | None = None
    closed_at: UtcTimestamp | None = None
    raw_content: str
    content_hash: str
    retrieved_at: UtcTimestamp
    trace_id: str
    created_at: UtcTimestamp
    updated_at: UtcTimestamp

    @model_validator(mode="after")
    def recover_saved_header_locations(self):
        from src.services.job_header_facts import effective_job_locations

        self.locations = effective_job_locations(self)
        return self


class JobSummary(BaseModel):
    id: str
    company: str | None
    title: str | None
    source_url: str | None
    source_id: str | None = None
    locations: list[str] = Field(default_factory=list)
    job_type: str | None = None
    published_at: UtcTimestamp | None = None
    verification_status: JobVerificationStatus
    availability_status: JobAvailabilityStatus
    first_seen_at: UtcTimestamp | None = None
    last_seen_at: UtcTimestamp | None = None
    last_verified_at: UtcTimestamp | None = None
    availability_failure_count: int = 0
    last_availability_checked_at: UtcTimestamp | None = None
    closed_at: UtcTimestamp | None = None


class CandidateCreateRequest(BaseModel):
    job_posting_id: str = Field(min_length=1, max_length=40)


class CandidateStatusUpdate(BaseModel):
    status: CandidateStatus


class CandidateAnalysisSummary(BaseModel):
    status: Literal["ready"] = "ready"
    score: float | None = None
    recommendation: str | None = None
    eligibility: Literal["pass", "fail", "unknown"] | None = None


class CandidateRead(BaseModel):
    id: str
    user_id: str
    job_posting_id: str
    status: CandidateStatus
    available_transitions: list[CandidateStatus]
    job: JobSummary
    analysis: CandidateAnalysisSummary | None = None
    created_at: UtcTimestamp
    updated_at: UtcTimestamp


class DiscoveryAgentTraceStep(BaseModel):
    phase: str
    tool: str
    outcome: str
    observation: str
    decision: str
    source_id: str | None = None
    company: str | None = None
    url: str | None = None
    occurred_at: UtcTimestamp | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    error_code: str | None = None
    details: dict[str, object] = Field(default_factory=dict)


class DiscoveryResultMatchRead(BaseModel):
    job_posting_id: str
    result_status: dict[str, object] = Field(default_factory=dict)
    personal_gate_conflict: bool = False
    review_caveats: list[str] = Field(default_factory=list)
    personal_requirements: list[dict[str, object]] = Field(default_factory=list)
    match_tier: Literal["strict", "expanded"]
    mismatch_reasons: list[str] = Field(default_factory=list)
    mismatch_labels: list[str] = Field(default_factory=list)
    filter_status: Literal["matched", "pending", "excluded"] = "pending"
    review_status: Literal["recommended", "pending", "excluded"] | None = None
    review_version: str | None = None
    checks: list[dict[str, object]] = Field(default_factory=list)
    filter_version: str | None = None
    decision_policy: str | None = None
    preference_score: int = 0


class DiscoveryRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    source: str
    source_url: str
    search_query: str | None = None
    search_goal_id: str | None = None
    search_goal_version: int | None = None
    continued_company_id: str | None = None
    goal_conditions: dict[str, object] | None = None
    usage_metrics: dict[str, object] | None = None
    max_results: int = 20
    status: str
    discovered_count: int
    new_count: int
    duplicate_count: int
    analysis_target_count: int = 0
    analysis_completed_count: int = 0
    analysis_failure_count: int = 0
    analysis_status: str = "NOT_REQUESTED"
    search_plan: DiscoverySearchPlan | None = None
    agent_trace: list[DiscoveryAgentTraceStep] = Field(default_factory=list)
    result_matches: list[DiscoveryResultMatchRead] = Field(default_factory=list)
    failure_summary: str | None
    started_at: UtcTimestamp
    finished_at: UtcTimestamp | None
    created_at: UtcTimestamp

    @computed_field
    @property
    def filter_conditions(self) -> dict[str, object]:
        from src.services.discovery_matching import search_filter_conditions
        return self.goal_conditions or search_filter_conditions(self.search_query)


class DomainEventRead(BaseModel):
    id: str
    entity_type: str
    entity_id: str
    event_type: str
    payload: dict[str, object]
    created_at: UtcTimestamp


class ApplicationStatusUpdate(BaseModel):
    status: ApplicationStatus
    next_action: str | None = Field(default=None, max_length=240)


class ApplicationRead(BaseModel):
    id: str
    candidate_job_id: str
    job_posting_id: str
    status: ApplicationStatus
    candidate_status: CandidateStatus
    submission_source: Literal["user_confirmed", "verified_receipt"] | None = None
    next_action: str | None
    available_transitions: list[ApplicationStatus]
    job: JobSummary
    events: list[DomainEventRead]
    created_at: UtcTimestamp
    updated_at: UtcTimestamp


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
    created_at: UtcTimestamp
    updated_at: UtcTimestamp


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
    decision: JobDecision
    score: MatchScore
    risks: list[AnalysisRisk]
    missing_information: list[str]
    created_at: UtcTimestamp
    invalidated_at: UtcTimestamp | None
