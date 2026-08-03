from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import DateTime, String, Text, func
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
