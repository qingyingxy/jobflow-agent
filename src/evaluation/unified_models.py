from __future__ import annotations

import hashlib
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.domain.unified_jd import (
    UNIFIED_JD_GRANULARITY_VERSION,
    UNIFIED_JD_SCHEMA_VERSION,
    UnifiedJDModelOutput,
    validate_unified_fact_clause_granularity,
    validate_unified_jd_evidence,
)

UnifiedEvaluationSplit = Literal["dev", "sealed_blind"]
UnifiedAnnotationStatus = Literal[
    "pending",
    "draft",
    "human_reviewed",
    "frozen",
]


class UnifiedEvaluationSource(BaseModel):
    """Verified source metadata that is not owned by the JD parser."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["real_public_source", "synthetic_fixture"]
    company: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=240)
    source_url: str = Field(min_length=1, max_length=2048)
    verified_at: date | None = None
    authorization: str = Field(min_length=1, max_length=500)


class UnifiedEvaluationCase(BaseModel):
    """One source JD and its optional, explicitly reviewed Unified label."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=80)
    split: UnifiedEvaluationSplit
    source: UnifiedEvaluationSource
    raw_content: str = Field(min_length=20)
    source_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    annotation_status: UnifiedAnnotationStatus = "pending"
    expected: UnifiedJDModelOutput | None = None
    coverage_tags: list[str] = Field(default_factory=list)
    review_notes: list[str] = Field(default_factory=list)

    @field_validator("raw_content")
    @classmethod
    def normalize_raw_content(cls, value: str) -> str:
        normalized = value.replace("\r\n", "\n").replace("\r", "\n").strip()
        if len(normalized) < 20:
            raise ValueError("评测岗位文本规范化后至少需要 20 个字符")
        return normalized

    @field_validator("coverage_tags", "review_notes")
    @classmethod
    def deduplicate_text(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip() for item in value if item.strip()))

    @model_validator(mode="after")
    def validate_annotation_and_source(self) -> UnifiedEvaluationCase:
        actual_hash = hashlib.sha256(self.raw_content.encode("utf-8")).hexdigest()
        if actual_hash != self.source_content_sha256:
            raise ValueError("source_content_sha256 与 raw_content 不一致")
        if self.annotation_status == "pending" and self.expected is not None:
            raise ValueError("pending 样本不能预填 expected，避免把旧标签当作新真值")
        if self.annotation_status != "pending" and self.expected is None:
            raise ValueError("draft、已复核或冻结的样本必须提供 expected")
        if self.expected is not None:
            validate_unified_jd_evidence(self.expected, self.raw_content)
        return self


class UnifiedEvaluationThresholds(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_valid_rate_min: float | None = Field(default=None, ge=0, le=1)
    parse_success_rate_min: float | None = Field(default=None, ge=0, le=1)
    parse_success_count_min: int | None = Field(default=None, ge=0)
    facts_macro_f1_min: float | None = Field(default=None, ge=0, le=1)
    clause_type_relation_f1_min: float | None = Field(default=None, ge=0, le=1)
    required_clause_recall_min: float | None = Field(default=None, ge=0, le=1)
    required_preferred_confusion_count_max: int | None = Field(
        default=None,
        ge=0,
    )
    unsupported_critical_fact_count_max: int | None = Field(default=None, ge=0)
    evidence_localization_rate_min: float | None = Field(default=None, ge=0, le=1)
    facts_value_macro_f1_min: float | None = Field(default=None, ge=0, le=1)
    evidence_span_character_f1_min: float | None = Field(default=None, ge=0, le=1)
    clause_category_f1_min: float | None = Field(default=None, ge=0, le=1)
    clause_level_f1_min: float | None = Field(default=None, ge=0, le=1)
    clause_relation_f1_min: float | None = Field(default=None, ge=0, le=1)
    canonical_items_f1_min: float | None = Field(default=None, ge=0, le=1)


class UnifiedEvaluationManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest_version: str = Field(min_length=1, max_length=100)
    dataset_version: str = Field(min_length=1, max_length=100)
    schema_version: str = UNIFIED_JD_SCHEMA_VERSION
    split: UnifiedEvaluationSplit
    purpose: str = Field(min_length=1, max_length=1000)
    source_policy: str = Field(min_length=1, max_length=1000)
    annotation_guide_version: str = Field(min_length=1, max_length=100)
    label_status: UnifiedAnnotationStatus
    thresholds: UnifiedEvaluationThresholds = Field(
        default_factory=UnifiedEvaluationThresholds
    )
    cases: list[UnifiedEvaluationCase] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_manifest(self) -> UnifiedEvaluationManifest:
        if self.schema_version != UNIFIED_JD_SCHEMA_VERSION:
            raise ValueError(f"schema_version 必须是 {UNIFIED_JD_SCHEMA_VERSION}")
        ids = [case.id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("评测 case id 必须唯一")
        wrong_splits = [case.id for case in self.cases if case.split != self.split]
        if wrong_splits:
            raise ValueError("case split 与 manifest split 不一致")
        if self.label_status == "pending":
            if any(case.annotation_status != "pending" for case in self.cases):
                raise ValueError("pending manifest 只能包含 pending 样本")
        elif self.label_status == "draft":
            if any(case.annotation_status != "draft" for case in self.cases):
                raise ValueError("draft manifest 只能包含 draft 样本")
        elif any(case.annotation_status in {"pending", "draft"} for case in self.cases):
            raise ValueError("可评测 manifest 不能包含 pending 或 draft 样本")
        if self.label_status == "frozen" and any(
            case.annotation_status != "frozen" for case in self.cases
        ):
            raise ValueError("frozen manifest 只能包含 frozen 样本")
        if self.annotation_guide_version == UNIFIED_JD_GRANULARITY_VERSION:
            for case in self.cases:
                if case.expected is None:
                    continue
                try:
                    validate_unified_fact_clause_granularity(case.expected)
                except ValueError as error:
                    raise ValueError(f"{case.id}: {error}") from error
        return self


class UnifiedPredictionRecord(BaseModel):
    """Raw model output is intentionally untyped so invalid Schema can be scored."""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1, max_length=80)
    output: Any | None = None
    failure_code: str | None = Field(default=None, max_length=80)
    model_call_count: int | None = Field(default=None, ge=0)
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class UnifiedPredictionFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prediction_version: str = Field(min_length=1, max_length=100)
    schema_version: str = UNIFIED_JD_SCHEMA_VERSION
    parser_version: str | None = Field(default=None, max_length=100)
    prompt_version: str | None = Field(default=None, max_length=100)
    model: str | None = Field(default=None, max_length=160)
    generated_at: str | None = None
    predictions: list[UnifiedPredictionRecord] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_prediction_file(self) -> UnifiedPredictionFile:
        if self.schema_version != UNIFIED_JD_SCHEMA_VERSION:
            raise ValueError(f"schema_version 必须是 {UNIFIED_JD_SCHEMA_VERSION}")
        ids = [prediction.case_id for prediction in self.predictions]
        if len(ids) != len(set(ids)):
            raise ValueError("预测文件中的 case_id 必须唯一")
        return self
