"""Private discovered companies; only verified rows become search sources."""

from datetime import datetime
from urllib.parse import urlsplit
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Index, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database import Base

ACCEPTED_COMPANY_STATUSES = ("verified", "manually_confirmed")


class DiscoveredCompany(Base):
    __tablename__ = "discovered_companies"
    __table_args__ = (
        UniqueConstraint("user_id", "homepage_host", name="uq_discovered_company_home"),
        Index("ix_discovered_companies_user_status", "user_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: "company_" + uuid4().hex[:24])
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    company: Mapped[str] = mapped_column(String(100), nullable=False)
    homepage_url: Mapped[str] = mapped_column(Text, nullable=False)
    homepage_host: Mapped[str] = mapped_column(String(253), nullable=False,
        default=lambda ctx: (urlsplit(ctx.get_current_parameters()["homepage_url"]).hostname or "").lower().removeprefix("www."))
    career_url: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    reason: Mapped[str] = mapped_column(String(240), nullable=False, default="等待核验官方入口")
    discovered_query: Mapped[str] = mapped_column(Text, nullable=False)
    discovery_run_id: Mapped[str] = mapped_column(String(40), nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    attempts: Mapped[int] = mapped_column(nullable=False, default=0)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CompanyDiscoveryTask(Base):
    """Durable stages of one user's goal; links remain untrusted until verified."""

    __tablename__ = "company_discovery_tasks"
    goal_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    goal_version: Mapped[int] = mapped_column(nullable=False)
    run_id: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    stage: Mapped[str] = mapped_column(String(24), nullable=False, default="search")
    state: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    lease_token: Mapped[str | None] = mapped_column(String(40))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(String(200))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
