from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.domain.eligibility import EligibilityStatus
from src.domain.matching import SupportLevel

EvaluationSplit = Literal["dev", "eval"]


class EvaluationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw_content: str | None = None
    source_url: str | None = Field(default=None, max_length=2048)
    scenario: str | None = Field(default=None, max_length=80)

    @field_validator("raw_content")
    @classmethod
    def validate_raw_content(cls, value: str | None) -> str | None:
        if value is not None and len(value.strip()) < 20:
            raise ValueError("评测岗位文本至少需要 20 个字符")
        return value


class SourceMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["synthetic", "fixture", "real_public_source"]
    reference: str = Field(min_length=1, max_length=240)
    authorization: str = Field(min_length=1, max_length=240)
    notes: str | None = Field(default=None, max_length=500)


class ExpectedLabels(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fields: dict[str, Any] = Field(default_factory=dict)
    # Exact technical mentions kept for traceability; not part of the main
    # metric unless explicitly added to EvaluationManifest.fields.
    skill_mentions: list[str] = Field(default_factory=list)
    eligibility: EligibilityStatus | None = None
    evidence: dict[str, list[str]] = Field(default_factory=dict)
    failure_code: str | None = Field(default=None, max_length=80)
    tags: list[str] = Field(default_factory=list)


class EvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=80)
    split: EvaluationSplit
    source: SourceMetadata
    input: EvaluationInput
    candidate_evidence_ids: list[str] = Field(default_factory=list)
    expected: ExpectedLabels


class EvaluationThresholds(BaseModel):
    model_config = ConfigDict(extra="forbid")

    macro_f1: float | None = Field(default=None, ge=0, le=1)
    eligibility_accuracy: float | None = Field(default=None, ge=0, le=1)
    false_accept_rate: float | None = Field(default=None, ge=0, le=1)
    evidence_precision: float | None = Field(default=None, ge=0, le=1)
    evidence_coverage: float | None = Field(default=None, ge=0, le=1)
    unsupported_claim_rate: float | None = Field(default=None, ge=0, le=1)
    failure_accuracy: float | None = Field(default=None, ge=0, le=1)


class EvaluationManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest_version: str = Field(min_length=1, max_length=80)
    dataset_version: str = Field(min_length=1, max_length=80)
    split: EvaluationSplit
    purpose: str = Field(min_length=1, max_length=500)
    source_policy: str = Field(min_length=1, max_length=500)
    fields: list[str] = Field(min_length=1)
    thresholds: EvaluationThresholds = Field(default_factory=EvaluationThresholds)
    cases: list[EvaluationCase] = Field(min_length=1)

    @field_validator("cases")
    @classmethod
    def validate_case_ids(cls, value: list[EvaluationCase]) -> list[EvaluationCase]:
        ids = [case.id for case in value]
        if len(ids) != len(set(ids)):
            raise ValueError("评测 case id 必须唯一")
        return value


class PredictionMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirement_key: str = Field(min_length=1, max_length=160)
    support_level: SupportLevel
    evidence_ids: list[str] = Field(default_factory=list)
    validation_issues: list[str] = Field(default_factory=list)


class PredictionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1, max_length=80)
    fields: dict[str, Any] = Field(default_factory=dict)
    eligibility: EligibilityStatus | None = None
    matches: list[PredictionMatch] = Field(default_factory=list)
    failure_code: str | None = Field(default=None, max_length=80)
    failure_details: dict[str, Any] = Field(default_factory=dict)


class PredictionFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prediction_version: str = Field(min_length=1, max_length=80)
    predictions: list[PredictionRecord] = Field(default_factory=list)
    model: str | None = Field(default=None, max_length=160)
    prompt_version: str | None = Field(default=None, max_length=80)
    generator_version: str | None = Field(default=None, max_length=80)
    generated_at: str | None = None
    generation_duration_ms: float | None = Field(default=None, ge=0)
    prediction_failure_count: int | None = Field(default=None, ge=0)

    @field_validator("predictions")
    @classmethod
    def validate_prediction_ids(
        cls,
        value: list[PredictionRecord],
    ) -> list[PredictionRecord]:
        ids = [prediction.case_id for prediction in value]
        if len(ids) != len(set(ids)):
            raise ValueError("预测文件中的 case_id 必须唯一")
        return value
