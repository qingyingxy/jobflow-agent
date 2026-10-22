from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.domain.unified_jd_canonicalizer import (
    UNIFIED_JD_CANONICALIZER_VERSION,
    UnifiedJDCanonicalProjection,
    canonicalize_unified_output,
)
from src.evaluation.unified_metrics import evaluate_unified_manifest
from src.evaluation.unified_models import (
    UnifiedEvaluationManifest,
    UnifiedPredictionFile,
)

MODEL_FIRST_EVALUATOR_VERSION = "unified-jd-model-first-evaluator-v1"
MODEL_FIRST_PROJECTION_VERSION = "unified-jd-model-first-canonical-projection-v1"


class ModelFirstCanonicalRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1, max_length=80)
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    failure_code: str | None = None
    canonicalized_output: dict[str, Any] | None = None
    projection: UnifiedJDCanonicalProjection | None = None


class ModelFirstCanonicalFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    projection_version: str = MODEL_FIRST_PROJECTION_VERSION
    canonicalizer_version: str = UNIFIED_JD_CANONICALIZER_VERSION
    dataset_version: str
    prediction_version: str
    prediction_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    records: list[ModelFirstCanonicalRecord]

    @model_validator(mode="after")
    def require_unique_cases(self) -> ModelFirstCanonicalFile:
        ids = [record.case_id for record in self.records]
        if len(ids) != len(set(ids)):
            raise ValueError("canonical projection case ids must be unique")
        return self


def json_payload_sha256(value: Any) -> str:
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def build_canonical_projection_file(
    manifest: UnifiedEvaluationManifest,
    predictions: UnifiedPredictionFile,
) -> ModelFirstCanonicalFile:
    cases = {case.id: case for case in manifest.cases}
    records: list[ModelFirstCanonicalRecord] = []
    for prediction in predictions.predictions:
        case = cases.get(prediction.case_id)
        if case is None:
            raise ValueError(f"prediction contains unknown case: {prediction.case_id}")
        if prediction.failure_code is not None or prediction.output is None:
            records.append(
                ModelFirstCanonicalRecord(
                    case_id=prediction.case_id,
                    input_sha256=case.source_content_sha256,
                    failure_code=prediction.failure_code or "missing_output",
                )
            )
            continue
        canonicalized, projection = canonicalize_unified_output(prediction.output)
        records.append(
            ModelFirstCanonicalRecord(
                case_id=prediction.case_id,
                input_sha256=case.source_content_sha256,
                canonicalized_output=canonicalized.model_dump(mode="json"),
                projection=projection,
            )
        )
    return ModelFirstCanonicalFile(
        dataset_version=manifest.dataset_version,
        prediction_version=predictions.prediction_version,
        prediction_payload_sha256=json_payload_sha256(
            predictions.model_dump(mode="json")
        ),
        records=records,
    )


def evaluate_model_first_manifest(
    manifest: UnifiedEvaluationManifest,
    predictions: UnifiedPredictionFile,
    canonical: ModelFirstCanonicalFile,
) -> dict[str, Any]:
    _validate_canonical_file(manifest, predictions, canonical)
    base_report = evaluate_unified_manifest(manifest, predictions.predictions)
    canonical_records = {record.case_id: record for record in canonical.records}
    canonicalized_predictions = [
        prediction.model_copy(
            update={
                "output": canonical_records[prediction.case_id].canonicalized_output,
                "failure_code": canonical_records[prediction.case_id].failure_code,
                "diagnostics": {
                    **prediction.diagnostics,
                    "canonicalizer_version": canonical.canonicalizer_version,
                },
            }
        )
        for prediction in predictions.predictions
    ]
    canonical_report = evaluate_unified_manifest(manifest, canonicalized_predictions)
    hard_checks = {
        "schema_valid_for_every_case": {
            "passed": canonical_report["schema_valid_rate"] == 1.0,
            "actual": canonical_report["schema_valid_rate"],
            "requirement": 1.0,
        },
        "parse_success_for_every_case": {
            "passed": canonical_report["parse_success_rate"] == 1.0,
            "actual": canonical_report["parse_success_rate"],
            "requirement": 1.0,
        },
        "all_evidence_located": {
            "passed": canonical_report["evidence"]["localization_rate"] == 1.0,
            "actual": canonical_report["evidence"]["localization_rate"],
            "requirement": 1.0,
        },
        "no_unsupported_critical_facts": {
            "passed": canonical_report["unsupported_critical_facts"]["count"] == 0,
            "actual": canonical_report["unsupported_critical_facts"]["count"],
            "requirement": 0,
        },
    }
    return {
        "evaluation_version": MODEL_FIRST_EVALUATOR_VERSION,
        "dataset_version": manifest.dataset_version,
        "case_count": len(manifest.cases),
        "prediction_count": len(predictions.predictions),
        "parser_version": predictions.parser_version,
        "prompt_version": predictions.prompt_version,
        "model": predictions.model,
        "canonicalizer_version": canonical.canonicalizer_version,
        "hard_gate": {
            "passed": all(check["passed"] for check in hard_checks.values()),
            "checks": hard_checks,
        },
        "semantic_thresholds_applied": False,
        "primary_dimensions": {
            "facts": canonical_report["dimensions"]["facts"],
            "category": canonical_report["dimensions"]["category"],
            "level": canonical_report["dimensions"]["level"],
            "relation": canonical_report["dimensions"]["relation"],
            "canonical_items": canonical_report["dimensions"]["canonical_items"],
        },
        "diagnostics": {
            "prediction_failure_count": canonical_report["prediction_failure_count"],
            "failure_codes": canonical_report["failure_codes"],
            "evidence": canonical_report["evidence"],
            "evidence_spans": canonical_report["dimensions"]["evidence_spans"],
            "canonical_items_before_canonicalizer": base_report["dimensions"][
                "canonical_items"
            ],
            "legacy_clause_exact": canonical_report["clauses"],
            "base_manifest_gate": canonical_report["gate"],
        },
    }


def _validate_canonical_file(
    manifest: UnifiedEvaluationManifest,
    predictions: UnifiedPredictionFile,
    canonical: ModelFirstCanonicalFile,
) -> None:
    if canonical.dataset_version != manifest.dataset_version:
        raise ValueError("canonical projection dataset version mismatch")
    if canonical.prediction_version != predictions.prediction_version:
        raise ValueError("canonical projection prediction version mismatch")
    if canonical.prediction_payload_sha256 != json_payload_sha256(
        predictions.model_dump(mode="json")
    ):
        raise ValueError("canonical projection prediction payload changed")
    expected = build_canonical_projection_file(manifest, predictions)
    if canonical != expected:
        raise ValueError("canonical projection does not match deterministic rebuild")
