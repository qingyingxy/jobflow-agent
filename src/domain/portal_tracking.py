"""Website observations are separate from manually managed application stages."""
from datetime import datetime

from sqlalchemy import JSON, DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database import Base


class PortalSource(Base):
    __tablename__ = "portal_sources"
    __table_args__ = (UniqueConstraint("user_id", "url"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    url: Mapped[str] = mapped_column(String(500))
    company: Mapped[str] = mapped_column(String(100))
    state: Mapped[str] = mapped_column(String(24), default="NEW")
    error: Mapped[str | None] = mapped_column(String(300))
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    succeeded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sync_token: Mapped[str | None] = mapped_column(String(64))
    sync_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PortalRecord(Base):
    __tablename__ = "portal_records"
    __table_args__ = (UniqueConstraint("source_id", "identity"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(40), index=True)
    identity: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(300))
    recruitment_type: Mapped[str] = mapped_column(String(100))
    location: Mapped[str] = mapped_column(String(200))
    submitted_at_text: Mapped[str] = mapped_column(String(40))
    raw_status: Mapped[str] = mapped_column(String(100))
    application_id: Mapped[str | None] = mapped_column(String(40), unique=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PortalObservation(Base):
    __tablename__ = "portal_observations"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    record_id: Mapped[str] = mapped_column(String(40), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    previous_status: Mapped[str | None] = mapped_column(String(100))
    raw_status: Mapped[str] = mapped_column(String(100))
    evidence: Mapped[dict] = mapped_column(JSON)
