from __future__ import annotations

import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.domain.eligibility import EligibilityStatus
from src.domain.job import JobRequirement

SupportLevel = Literal["supported", "partial", "unsupported"]
ValidationStatus = Literal["passed", "failed"]
ScoreGroupName = Literal["required_skill", "preferred_skill", "preferences"]
ScoreGroupStatus = Literal["applicable", "not_applicable", "insufficient_data"]
Recommendation = Literal[
    "recommended",
    "not_recommended",
    "needs_confirmation",
    "insufficient_data",
]


class EvidenceRecord(BaseModel):
    """The minimal evidence view exposed to recall and matching."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=40)
    user_id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=160)
    claim: str = Field(min_length=1)
    skills: list[str] = Field(default_factory=list)
    source: str = Field(default="manual", min_length=1, max_length=160)
    retrieval_score: float | None = None

    @field_validator("skills")
    @classmethod
    def normalize_skills(cls, value: list[str]) -> list[str]:
        return [skill.strip() for skill in value if skill.strip()]


class EvidenceMatchModelOutput(BaseModel):
    """The only model-generated part of one requirement match."""

    model_config = ConfigDict(extra="forbid")

    support_level: SupportLevel
    evidence_ids: list[str] = Field(default_factory=list)
    explanation: str = Field(min_length=1)
    claims: list[str] = Field(default_factory=list)

    @field_validator("evidence_ids", "claims")
    @classmethod
    def reject_empty_items(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value):
            raise ValueError("列表不能包含空字符串")
        return [item.strip() for item in value]


class RequirementMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirement: JobRequirement
    support_level: SupportLevel
    evidence_ids: list[str] = Field(default_factory=list)
    explanation: str = Field(min_length=1)
    validation_status: ValidationStatus = "passed"
    validation_issues: list[str] = Field(default_factory=list)


class ScoreGroupResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group: ScoreGroupName
    status: ScoreGroupStatus
    original_weight: float = Field(ge=0, le=1)
    effective_weight: float = Field(ge=0, le=1)
    score: float | None = Field(default=None, ge=0, le=1)
    numerator: float | None = Field(default=None, ge=0)
    denominator: int | None = Field(default=None, ge=0)
    reason: str = Field(min_length=1)


class MatchScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: float | None = Field(default=None, ge=0, le=100)
    eligibility: EligibilityStatus
    recommendation: Recommendation
    groups: list[ScoreGroupResult] = Field(min_length=1)
    missing_information: list[str] = Field(default_factory=list)


def requirement_key(requirement: JobRequirement) -> str:
    normalized = unicodedata.normalize("NFKC", requirement.name).casefold()
    normalized = re.sub(r"[\s\-_、,，/|()（）]+", "", normalized)
    normalized = {
        "retrievalaugmentedgeneration": "rag",
        "检索增强生成": "rag",
        "vectorretrieval": "vectorsearch",
        "向量检索": "vectorsearch",
        "rerank": "reranker",
        "重排": "reranker",
        "py": "python",
        "ts": "typescript",
    }.get(normalized, normalized)
    return f"{requirement.category.casefold()}:{normalized}"
