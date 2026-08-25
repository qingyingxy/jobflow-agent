from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import JSON, DateTime, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database import Base


class DiscoveryRunStatus(StrEnum):
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class DiscoveryTool(StrEnum):
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
