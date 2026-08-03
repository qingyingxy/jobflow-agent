from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.domain.job import StructuredJobDescription, normalize_job_text


class ProfileUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=100)
    graduation_year: int | None = Field(default=None, ge=2000, le=2100)
    degree: str | None = Field(default=None, max_length=100)
    major: str | None = Field(default=None, max_length=100)
    search_preferences: dict[str, Any] | None = None


class ProfileRead(ProfileUpdate):
    model_config = ConfigDict(from_attributes=True)

    user_id: str
    search_preferences: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class EvidenceCreate(BaseModel):
    type: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=1, max_length=160)
    claim: str = Field(min_length=1)
    skills: list[str] = Field(default_factory=list)
    source: str = Field(default="manual", min_length=1, max_length=160)


class EvidenceUpdate(BaseModel):
    type: str | None = Field(default=None, min_length=1, max_length=40)
    title: str | None = Field(default=None, min_length=1, max_length=160)
    claim: str | None = Field(default=None, min_length=1)
    skills: list[str] | None = None
    source: str | None = Field(default=None, min_length=1, max_length=160)


class EvidenceRead(EvidenceCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    created_at: datetime
    updated_at: datetime


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


class JobPostingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_url: str | None
    source_type: str
    company: str | None
    title: str | None
    raw_content: str
    content_hash: str
    retrieved_at: datetime
    trace_id: str
    created_at: datetime
    updated_at: datetime


class JobParseResponse(BaseModel):
    job_id: str
    parse_result_id: str
    agent_run_id: str
    model: str
    schema_version: str
    parser_version: str
    prompt_version: str
    structured_jd: StructuredJobDescription
