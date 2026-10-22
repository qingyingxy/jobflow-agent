from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database import Base


class JobCorrection(Base):
    """Append-only, user-owned interpretations of an immutable JD body."""

    __tablename__ = "job_corrections"
    __table_args__ = (UniqueConstraint("user_id", "job_posting_id", "revision"),)

    id: Mapped[str] = mapped_column(String(48), primary_key=True, default=lambda: f"correction_{uuid4().hex[:20]}")
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    job_posting_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    parse_result_id: Mapped[str] = mapped_column(String(40), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    requirements: Mapped[list | None] = mapped_column(JSON, nullable=True)
    structured_jd: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
