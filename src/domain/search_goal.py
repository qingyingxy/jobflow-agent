"""Saved intent, independent of resume qualifications and search execution."""

from datetime import datetime
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import JSON, DateTime, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database import Base


class SearchGoalConditions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    locations: list[str] = Field(default_factory=list, max_length=20)
    preferred_locations: list[str] = Field(default_factory=list, max_length=20)
    excluded_locations: list[str] = Field(default_factory=list, max_length=20)
    roles: list[str] = Field(default_factory=list, max_length=20)
    preferred_roles: list[str] = Field(default_factory=list, max_length=20)
    excluded_roles: list[str] = Field(default_factory=list, max_length=20)
    job_types: list[str] = Field(default_factory=list, max_length=3)
    excluded_job_types: list[str] = Field(default_factory=list, max_length=3)
    graduation_years: list[int] = Field(default_factory=list, max_length=10)
    keywords: list[str] = Field(default_factory=list, max_length=20)
    preferred_keywords: list[str] = Field(default_factory=list, max_length=20)
    pending_conditions: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("*", mode="before")
    @classmethod
    def clean_lists(cls, values):
        if not isinstance(values, list):
            return values
        result = []
        for value in values:
            if isinstance(value, str):
                value = " ".join(value.split())
                if not value or len(value) > 160:
                    raise ValueError("条件不能为空，单项不能超过160个字符")
            if value not in result:
                result.append(value)
        return result

    @model_validator(mode="after")
    def validate_scope(self):
        from src.services.search_vocabulary import canonical_location, canonical_role

        for name in ("locations", "preferred_locations", "excluded_locations"):
            setattr(
                self,
                name,
                list(dict.fromkeys(canonical_location(v) for v in getattr(self, name))),
            )
        for name in ("roles", "preferred_roles", "excluded_roles"):
            setattr(
                self,
                name,
                list(dict.fromkeys(canonical_role(v) for v in getattr(self, name))),
            )
        type_aliases = {"campus": "校招", "internship": "实习", "full_time": "社招"}
        for name in ("job_types", "excluded_job_types"):
            values = list(
                dict.fromkeys(type_aliases.get(v, v) for v in getattr(self, name))
            )
            if any(v not in {"校招", "实习", "社招"} for v in values):
                raise ValueError("招聘类型仅支持校招、实习和社招")
            setattr(self, name, values)
        for positive, negative, label in (
            ("locations", "excluded_locations", "地点"),
            ("roles", "excluded_roles", "岗位方向"),
            ("job_types", "excluded_job_types", "招聘类型"),
        ):
            if set(getattr(self, positive)) & set(getattr(self, negative)):
                raise ValueError(f"{label}同时要求和排除，请修改冲突条件")
        if set(self.preferred_locations) & set(self.excluded_locations):
            raise ValueError("优先地点与排除地点冲突")
        if set(self.preferred_roles) & set(self.excluded_roles):
            raise ValueError("优先方向与排除方向冲突")
        if any(year < 2000 or year > 2200 for year in self.graduation_years):
            raise ValueError("届别应在2000至2200年之间")
        return self


class SearchGoal(Base):
    __tablename__ = "search_goals"
    __table_args__ = (Index("ix_search_goals_user_updated", "user_id", "updated_at"),)

    id: Mapped[str] = mapped_column(
        String(40), primary_key=True, default=lambda: f"goal_{uuid4().hex[:20]}"
    )
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    input_text: Mapped[str] = mapped_column(Text, nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    conditions: Mapped[dict] = mapped_column(JSON, nullable=False)
    condition_sources: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    version: Mapped[int] = mapped_column(nullable=False, default=1)
    company_ids: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    company_search_state: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    update_interval_minutes: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    next_update_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    schedule_error: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class BodyReviewTask(Base):
    """One durable review queue per goal; source evidence remains on each job."""

    __tablename__ = "body_review_tasks"
    goal_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    goal_version: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    processed: Mapped[int] = mapped_column(nullable=False, default=0)
    completed: Mapped[int] = mapped_column(nullable=False, default=0)
    lease_token: Mapped[str | None] = mapped_column(String(40), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(String(200), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
