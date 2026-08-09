from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database import Base


class DiscoveryRunStatus(StrEnum):
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


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
