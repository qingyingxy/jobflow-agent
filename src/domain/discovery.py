from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import JSON, DateTime, Index, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database import Base


class DiscoveryRunStatus(StrEnum):
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class JobLeadStatus(StrEnum):
    NEW = "NEW"
    VERIFYING = "VERIFYING"
    VERIFIED = "VERIFIED"
    NEEDS_BROWSER = "NEEDS_BROWSER"
    NEEDS_USER = "NEEDS_USER"
    DUPLICATE = "DUPLICATE"
    REJECTED_NON_JOB = "REJECTED_NON_JOB"
    FAILED = "FAILED"


class LeadProvider(StrEnum):
    OFFICIAL_ADAPTER = "official_adapter"
    EXTERNAL_AGENT = "external_agent"
    MANUAL_URL = "manual_url"
    THIRD_PARTY = "third_party"


class LeadNextAction(StrEnum):
    VERIFY_URL = "verify_url"
    WAIT_FOR_VERIFICATION = "wait_for_verification"
    OPEN_IN_BROWSER = "open_in_browser"
    PROVIDE_MANUAL_JD = "provide_manual_jd"
    RETRY_VERIFICATION = "retry_verification"
    OPEN_JOB = "open_job"


class DiscoveryTool(StrEnum):
    WEB_SEARCH = "web_search"
    SOURCE_ADAPTER = "source_adapter"
    GREENHOUSE_PUBLIC_JOB_API = "greenhouse_public_job_api"
    BYTEDANCE_PUBLIC_JOB_ADAPTER = "bytedance_public_job_adapter"
    TENCENT_PUBLIC_JOB_ADAPTER = "tencent_public_job_adapter"
    JSON_LD_JOB_PARSER = "json_ld_job_parser"
    STATIC_JOB_PAGE_VALIDATOR = "static_job_page_validator"
    VISIBLE_JOB_LINK_READER = "visible_job_link_reader"


class DiscoveryStopCondition(StrEnum):
    MAX_RESULTS_REACHED = "max_results_reached"
    SOURCE_ROUTE_EXHAUSTED = "source_route_exhausted"
    NO_VERIFIED_JOBS_REQUIRES_HUMAN_INPUT = (
        "no_verified_jobs_requires_human_input"
    )


class DiscoveryPlanRoute(BaseModel):
    """Allowed tool sequence for one user-selected official source."""

    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1, max_length=100)
    company: str | None = Field(default=None, max_length=160)
    source_url: str = Field(min_length=1, max_length=2048)
    tool_sequence: list[DiscoveryTool] = Field(min_length=1, max_length=8)


class DiscoveryPlanBudget(BaseModel):
    """Hard limits enforced by deterministic discovery code."""

    model_config = ConfigDict(extra="forbid")

    max_results: int = Field(ge=1, le=20)
    max_analysis: int = Field(ge=0, le=5)
    max_detail_links_per_source: int | None = Field(default=None, ge=1, le=20)
    max_concurrency: int | None = Field(default=None, ge=1, le=20)
    request_timeout_seconds: float | None = Field(default=None, gt=0, le=60)


class DiscoverySearchPlan(BaseModel):
    """Replayable plan contract created before any official source is read."""

    model_config = ConfigDict(extra="forbid")

    version: str = Field(default="bounded-discovery-v1", min_length=1, max_length=80)
    planner: str = Field(default="deterministic_policy", min_length=1, max_length=80)
    query: str | None = Field(default=None, max_length=500)
    allowed_source_ids: list[str] = Field(min_length=1, max_length=40)
    routes: list[DiscoveryPlanRoute] = Field(min_length=1, max_length=40)
    budget: DiscoveryPlanBudget
    stop_conditions: list[DiscoveryStopCondition] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def validate_source_scope(self) -> DiscoverySearchPlan:
        if len(self.allowed_source_ids) != len(set(self.allowed_source_ids)):
            raise ValueError("发现计划包含重复来源")
        route_source_ids = [route.source_id for route in self.routes]
        if len(route_source_ids) != len(set(route_source_ids)):
            raise ValueError("发现计划包含重复来源路线")
        if route_source_ids != self.allowed_source_ids:
            raise ValueError("来源白名单必须与工具路线一一对应")
        return self


def generate_discovery_run_id() -> str:
    return f"discovery_{uuid4().hex[:20]}"


def generate_job_lead_id() -> str:
    return f"lead_{uuid4().hex[:20]}"


def generate_lead_verification_id() -> str:
    return f"leadcheck_{uuid4().hex[:20]}"


class JobLead(Base):
    """A discovered URL or adapter result that must be verified before use."""

    __tablename__ = "job_leads"
    __table_args__ = (
        UniqueConstraint(
            "discovery_run_id",
            "source_id",
            "source_job_id",
            name="uq_job_leads_run_source_job",
        ),
        Index("ix_job_leads_user_status", "user_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    discovery_run_id: Mapped[str | None] = mapped_column(
        String(40), nullable=True, index=True
    )
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    source_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_job_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    normalized_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    company_hint: Mapped[str | None] = mapped_column(String(160), nullable=True)
    title_hint: Mapped[str | None] = mapped_column(String(160), nullable=True)
    search_snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=JobLeadStatus.NEW.value,
        server_default=JobLeadStatus.NEW.value,
    )
    job_posting_id: Mapped[str | None] = mapped_column(
        String(40), nullable=True, index=True
    )
    failure_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
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

    @property
    def next_action(self) -> str:
        return {
            JobLeadStatus.NEW.value: LeadNextAction.VERIFY_URL.value,
            JobLeadStatus.VERIFYING.value: LeadNextAction.WAIT_FOR_VERIFICATION.value,
            JobLeadStatus.NEEDS_BROWSER.value: LeadNextAction.OPEN_IN_BROWSER.value,
            JobLeadStatus.NEEDS_USER.value: LeadNextAction.PROVIDE_MANUAL_JD.value,
            JobLeadStatus.REJECTED_NON_JOB.value: LeadNextAction.PROVIDE_MANUAL_JD.value,
            JobLeadStatus.FAILED.value: LeadNextAction.RETRY_VERIFICATION.value,
            JobLeadStatus.VERIFIED.value: LeadNextAction.OPEN_JOB.value,
            JobLeadStatus.DUPLICATE.value: LeadNextAction.OPEN_JOB.value,
        }[self.status]


class LeadVerification(Base):
    """One immutable verification observation for a job lead."""

    __tablename__ = "lead_verifications"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    lead_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    result: Mapped[str] = mapped_column(String(32), nullable=False)
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    source_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    field_evidence: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        server_default=text("'{}'"),
    )
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class DiscoveryRun(Base):
    """One user-triggered synchronization with a configured public source."""

    __tablename__ = "discovery_runs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    search_query: Mapped[str | None] = mapped_column(String(500), nullable=True)
    max_results: Mapped[int] = mapped_column(nullable=False, default=20, server_default="20")
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=DiscoveryRunStatus.RUNNING.value,
        server_default=DiscoveryRunStatus.RUNNING.value,
    )
    discovered_count: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    new_count: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    duplicate_count: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
        server_default="0",
    )
    analysis_target_count: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
        server_default="0",
    )
    analysis_completed_count: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
        server_default="0",
    )
    analysis_failure_count: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
        server_default="0",
    )
    analysis_status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="NOT_REQUESTED",
        server_default="NOT_REQUESTED",
    )
    agent_trace: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        server_default=text("'[]'"),
    )
    search_plan: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    result_matches: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        server_default=text("'[]'"),
    )
    failure_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
