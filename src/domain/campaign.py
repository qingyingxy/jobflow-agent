"""Private company recruitment batches and durable, opt-in source watches."""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database import Base


def identifier():
    return "camp_" + uuid4().hex[:24]


class CampaignWatch(Base):
    __tablename__ = "campaign_watches"
    __table_args__ = (UniqueConstraint("user_id", "company_id", "year"),
                      Index("ix_campaign_watch_due", "status", "next_check_at"))

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=identifier)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    company_id: Mapped[str] = mapped_column(String(100))
    year: Mapped[int]
    followed: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    succeeded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[str | None] = mapped_column(String(40))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(String(300))
    # Parser results keyed by source body hash; each refresh still reads the page.
    cache: Mapped[dict] = mapped_column(JSON, default=dict)


class CampaignDiscoveryTask(Base):
    """Company discovery for one cohort, independent of personal job goals."""

    __tablename__ = "campaign_discovery_tasks"
    __table_args__ = (UniqueConstraint("user_id", "year"),
                     Index("ix_campaign_discovery_due", "status", "next_run_at"))

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=identifier)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    year: Mapped[int]
    run_id: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(24), default="queued")
    stage: Mapped[str] = mapped_column(String(24), default="search")
    state: Mapped[dict] = mapped_column(JSON, default=dict)
    lease_token: Mapped[str | None] = mapped_column(String(40))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(String(200))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RecruitmentCampaign(Base):
    __tablename__ = "recruitment_campaigns"
    __table_args__ = (UniqueConstraint("user_id", "company_id", "identity"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=identifier)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    company_id: Mapped[str] = mapped_column(String(100))
    company: Mapped[str] = mapped_column(String(160))
    identity: Mapped[str] = mapped_column(String(64))
    year: Mapped[int]
    title: Mapped[str] = mapped_column(String(300))
    batch: Mapped[str] = mapped_column(String(30))
    source_url: Mapped[str] = mapped_column(Text)
    facts: Mapped[dict] = mapped_column(JSON)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CampaignEvent(Base):
    __tablename__ = "campaign_events"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=identifier)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    campaign_id: Mapped[str] = mapped_column(String(40), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    evidence: Mapped[dict] = mapped_column(JSON)
