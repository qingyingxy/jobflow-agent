from __future__ import annotations

from collections import Counter
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.domain.unified_jd import (
    ClauseLevel,
    ClauseRelation,
    NonEmptyText,
    UnifiedJDModelOutput,
)
from src.domain.unified_jd_canonicalizer import (
    canonicalize_item,
    canonicalize_unified_output,
)
from src.domain.unified_jd_extraction import SemanticClauseCategory
from src.evaluation.model_first import json_payload_sha256
from src.evaluation.unified_metrics import evaluate_unified_manifest
from src.evaluation.unified_models import (
    UnifiedEvaluationManifest,
    UnifiedPredictionFile,
    UnifiedPredictionRecord,
)
from src.services.unified_jd_extraction import (
    MODEL_FIRST_FACT_COMPILER_VERSION,
    compile_model_first_extraction_v2,
)

MODEL_FIRST_V2_REPLAY_VERSION = "unified-jd-model-first-offline-replay-v2"
MODEL_FIRST_V2_PROJECTION_VERSION = "unified-jd-model-first-surface-projection-v2"
MODEL_FIRST_V2_EVALUATOR_VERSION = "unified-jd-model-first-evaluator-v2"

SurfaceStatus = Literal["exact", "unmapped"]
CanonicalStatus = Literal["identity", "normalized", "unmapped_surface"]


class ModelFirstV2ItemProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_item: NonEmptyText
    surface_status: SurfaceStatus
    surface_item: NonEmptyText | None = None
    surface_start_char: int | None = Field(default=None, ge=0)
    surface_end_char: int | None = Field(default=None, ge=0)
    canonical_status: CanonicalStatus
    canonical_item: NonEmptyText | None = None
    canonical_rule_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_status_payload(self) -> ModelFirstV2ItemProjection:
        if self.surface_status == "exact":
            if (
                self.surface_item is None
                or self.surface_start_char is None
                or self.surface_end_char is None
                or self.canonical_item is None
                or self.canonical_status == "unmapped_surface"
            ):
                raise ValueError(
                    "exact surface item requires spans and a canonical item"
                )
            if self.surface_end_char <= self.surface_start_char:
                raise ValueError("surface item span must be non-empty")
        elif (
            any(
                value is not None
                for value in (
                    self.surface_item,
                    self.surface_start_char,
                    self.surface_end_char,
                    self.canonical_item,
                )
            )
            or self.canonical_status != "unmapped_surface"
        ):
            raise ValueError(
                "unmapped surface item cannot carry spans or canonical data"
            )
        return self


class ModelFirstV2ClauseProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw_clause_index: int = Field(ge=0)
    category: SemanticClauseCategory
    level: ClauseLevel
    relation: ClauseRelation
    source_text: NonEmptyText
    source_start_char: int = Field(ge=0)
    source_end_char: int = Field(ge=0)
    source_occurrence_count: int = Field(ge=1)
    items: list[ModelFirstV2ItemProjection] = Field(min_length=1)
    examples: list[str] = Field(default_factory=list)


class ModelFirstV2ProjectionDiagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    path: str
    message: str


class ModelFirstV2CaseProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1, max_length=80)
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    clauses: list[ModelFirstV2ClauseProjection] = Field(default_factory=list)
    diagnostics: list[ModelFirstV2ProjectionDiagnostic] = Field(default_factory=list)


class ModelFirstV2ProjectionFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    projection_version: str = MODEL_FIRST_V2_PROJECTION_VERSION
    dataset_version: str
    source_prediction_version: str
    source_prediction_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    records: list[ModelFirstV2CaseProjection]


def build_model_first_v2_replay(
    manifest: UnifiedEvaluationManifest,
    source_predictions: UnifiedPredictionFile,
) -> tuple[UnifiedPredictionFile, ModelFirstV2ProjectionFile]:
    _validate_source_predictions(manifest, source_predictions)
    source_payload_sha256 = json_payload_sha256(
        source_predictions.model_dump(mode="json")
    )
    cases_by_id = {case.id: case for case in manifest.cases}
    replay_records: list[UnifiedPredictionRecord] = []
    projection_records: list[ModelFirstV2CaseProjection] = []

    for source_prediction in source_predictions.predictions:
        case = cases_by_id[source_prediction.case_id]
        raw_output = _last_raw_model_output(source_prediction)
        compilation = compile_model_first_extraction_v2(raw_output, case.raw_content)
        replay_records.append(
            UnifiedPredictionRecord(
                case_id=case.id,
                output=compilation.output.model_dump(mode="json"),
                model_call_count=0,
                diagnostics={
                    "model_api_called": False,
                    "source_model_call_count": source_prediction.model_call_count,
                    "source_prediction_payload_sha256": source_payload_sha256,
                    "input_sha256": case.source_content_sha256,
                    "fact_compiler_version": MODEL_FIRST_FACT_COMPILER_VERSION,
                    "compilation_diagnostics": [
                        item.as_dict() for item in compilation.diagnostics
                    ],
                },
            )
        )
        projection_records.append(
            _project_case(
                case_id=case.id,
                input_sha256=case.source_content_sha256,
                raw_content=case.raw_content,
                raw_output=raw_output,
            )
        )

    replay = UnifiedPredictionFile(
        prediction_version=f"offline-v2-{manifest.dataset_version}",
        schema_version=source_predictions.schema_version,
        parser_version=MODEL_FIRST_V2_REPLAY_VERSION,
        prompt_version=source_predictions.prompt_version,
        model=source_predictions.model,
        generated_at=source_predictions.generated_at,
        predictions=replay_records,
    )
    projection = ModelFirstV2ProjectionFile(
        dataset_version=manifest.dataset_version,
        source_prediction_version=source_predictions.prediction_version,
        source_prediction_payload_sha256=source_payload_sha256,
        records=projection_records,
    )
    return replay, projection


def evaluate_model_first_v2(
    manifest: UnifiedEvaluationManifest,
    source_predictions: UnifiedPredictionFile,
    replay: UnifiedPredictionFile,
    projection: ModelFirstV2ProjectionFile,
) -> dict[str, Any]:
    _validate_v2_artifacts(manifest, source_predictions, replay, projection)
    report = evaluate_unified_manifest(manifest, replay.predictions)
    canonicalized_predictions = []
    for prediction in replay.predictions:
        if prediction.output is None or prediction.failure_code is not None:
            canonicalized_predictions.append(prediction)
            continue
        canonicalized, _ = canonicalize_unified_output(prediction.output)
        canonicalized_predictions.append(
            prediction.model_copy(
                update={"output": canonicalized.model_dump(mode="json")}
            )
        )
    canonical_report = evaluate_unified_manifest(manifest, canonicalized_predictions)

    disagreement_items = report["unsupported_critical_facts"]["items"]
    source_unsupported = [
        item
        for item in disagreement_items
        if "missing_localized_evidence" in item["reasons"]
    ]
    label_disagreements = [
        item
        for item in disagreement_items
        if "value_not_in_human_label" in item["reasons"]
    ]
    surface_metrics = _surface_metrics(projection)
    hard_checks = {
        "schema_valid_for_every_case": report["schema_valid_rate"] == 1.0,
        "parse_success_for_every_case": report["parse_success_rate"] == 1.0,
        "all_evidence_located": report["evidence"]["localization_rate"] == 1.0,
        "no_source_unsupported_critical_facts": not source_unsupported,
    }
    return {
        "evaluation_version": MODEL_FIRST_V2_EVALUATOR_VERSION,
        "dataset_version": manifest.dataset_version,
        "case_count": len(manifest.cases),
        "model_api_called": False,
        "source_prediction_payload_sha256": (
            projection.source_prediction_payload_sha256
        ),
        "hard_gate": {
            "passed": all(hard_checks.values()),
            "checks": hard_checks,
        },
        "facts": {
            "metrics": report["dimensions"]["facts"],
            "source_unsupported_critical_facts": {
                "count": len(source_unsupported),
                "items": source_unsupported,
            },
            "human_label_disagreements": {
                "count": len(label_disagreements),
                "items": label_disagreements,
            },
        },
        "evidence": {
            "localization": report["evidence"],
            "spans": report["dimensions"]["evidence_spans"],
        },
        "clause_semantics": {
            "category": report["dimensions"]["category"],
            "level": report["dimensions"]["level"],
            "relation": report["dimensions"]["relation"],
        },
        "surface_items": surface_metrics,
        "canonical_items": {
            "gold_exact_metrics": canonical_report["dimensions"]["canonical_items"],
            "mapped_count": surface_metrics["exact_count"],
            "normalized_count": surface_metrics["canonical_normalized_count"],
            "identity_count": surface_metrics["canonical_identity_count"],
            "unmapped_surface_count": surface_metrics["unmapped_count"],
        },
        "diagnostics": {
            "prediction_failure_count": report["prediction_failure_count"],
            "failure_codes": report["failure_codes"],
            "legacy_label_disagreement_metric": report["unsupported_critical_facts"],
        },
    }


def _validate_source_predictions(
    manifest: UnifiedEvaluationManifest,
    source_predictions: UnifiedPredictionFile,
) -> None:
    expected_ids = [case.id for case in manifest.cases]
    actual_ids = [prediction.case_id for prediction in source_predictions.predictions]
    if actual_ids != expected_ids:
        raise ValueError("source predictions must cover manifest cases in order")
    cases_by_id = {case.id: case for case in manifest.cases}
    for prediction in source_predictions.predictions:
        if prediction.failure_code is not None:
            raise ValueError(f"source prediction failed: {prediction.case_id}")
        if (
            prediction.diagnostics.get("input_sha256")
            != cases_by_id[prediction.case_id].source_content_sha256
        ):
            raise ValueError(f"source input hash mismatch: {prediction.case_id}")


def _last_raw_model_output(prediction: UnifiedPredictionRecord) -> dict[str, Any]:
    attempts = prediction.diagnostics.get("model_attempts")
    if not isinstance(attempts, list):
        raise TypeError(f"missing model attempts: {prediction.case_id}")
    raw_outputs = [
        attempt.get("raw_model_output")
        for attempt in attempts
        if isinstance(attempt, dict)
        and isinstance(attempt.get("raw_model_output"), dict)
    ]
    if not raw_outputs:
        raise ValueError(f"missing raw model output: {prediction.case_id}")
    return raw_outputs[-1]


def _project_case(
    *,
    case_id: str,
    input_sha256: str,
    raw_content: str,
    raw_output: dict[str, Any],
) -> ModelFirstV2CaseProjection:
    clauses: list[ModelFirstV2ClauseProjection] = []
    diagnostics: list[ModelFirstV2ProjectionDiagnostic] = []
    raw_clauses = raw_output.get("clauses")
    if not isinstance(raw_clauses, list):
        raise TypeError(f"raw clauses are not a list: {case_id}")

    for index, raw_clause in enumerate(raw_clauses):
        parsed = _projection_clause_payload(raw_clause)
        if isinstance(parsed, str):
            diagnostics.append(
                ModelFirstV2ProjectionDiagnostic(
                    code="invalid_projection_clause",
                    path=f"clauses[{index}]",
                    message=parsed,
                )
            )
            continue
        source_text = parsed["source_text"]
        source_start = raw_content.find(source_text)
        if source_start < 0:
            diagnostics.append(
                ModelFirstV2ProjectionDiagnostic(
                    code="unlocated_clause_source",
                    path=f"clauses[{index}].source_text",
                    message="clause source_text is not an exact JD substring",
                )
            )
            continue
        clauses.append(
            ModelFirstV2ClauseProjection(
                raw_clause_index=index,
                category=parsed["category"],
                level=parsed["level"],
                relation=parsed["relation"],
                source_text=source_text,
                source_start_char=source_start,
                source_end_char=source_start + len(source_text),
                source_occurrence_count=raw_content.count(source_text),
                items=[
                    _project_item(item, source_text, source_start)
                    for item in parsed["items"]
                ],
                examples=parsed["examples"],
            )
        )
    return ModelFirstV2CaseProjection(
        case_id=case_id,
        input_sha256=input_sha256,
        raw_output_sha256=json_payload_sha256(raw_output),
        clauses=clauses,
        diagnostics=diagnostics,
    )


def _projection_clause_payload(raw_clause: Any) -> dict[str, Any] | str:
    if not isinstance(raw_clause, dict):
        return "clause is not an object"
    category = raw_clause.get("category")
    level = raw_clause.get("level")
    relation = raw_clause.get("relation", "all_of")
    source_text = raw_clause.get("source_text")
    items = raw_clause.get("items")
    examples = raw_clause.get("examples") or []
    if category not in {"skill", "capability", "experience", "responsibility"}:
        return "clause category is invalid"
    if level not in {"required", "preferred", "mention"}:
        return "clause level is invalid"
    if relation not in {"all_of", "any_of"}:
        return "clause relation is invalid"
    if not isinstance(source_text, str) or not source_text.strip():
        return "clause source_text is invalid"
    if (
        not isinstance(items, list)
        or not items
        or not all(isinstance(item, str) and item.strip() for item in items)
    ):
        return "clause items are invalid"
    if not isinstance(examples, list) or not all(
        isinstance(item, str) for item in examples
    ):
        return "clause examples are invalid"
    return {
        "category": category,
        "level": "mention" if category == "responsibility" else level,
        "relation": relation,
        "source_text": source_text,
        "items": items,
        "examples": examples,
    }


def _project_item(
    model_item: str,
    source_text: str,
    source_start: int,
) -> ModelFirstV2ItemProjection:
    local_start = source_text.find(model_item)
    if local_start < 0:
        return ModelFirstV2ItemProjection(
            model_item=model_item,
            surface_status="unmapped",
            canonical_status="unmapped_surface",
            canonical_rule_ids=["surface.not-exact"],
        )
    mapping = canonicalize_item(model_item)
    canonical_status: CanonicalStatus = (
        "identity" if mapping.rule_ids == ["canonical.identity"] else "normalized"
    )
    return ModelFirstV2ItemProjection(
        model_item=model_item,
        surface_status="exact",
        surface_item=model_item,
        surface_start_char=source_start + local_start,
        surface_end_char=source_start + local_start + len(model_item),
        canonical_status=canonical_status,
        canonical_item=mapping.canonical_item,
        canonical_rule_ids=mapping.rule_ids,
    )


def _surface_metrics(projection: ModelFirstV2ProjectionFile) -> dict[str, Any]:
    items = [
        item
        for record in projection.records
        for clause in record.clauses
        for item in clause.items
    ]
    by_category: dict[str, Counter[str]] = {}
    for record in projection.records:
        for clause in record.clauses:
            counts = by_category.setdefault(clause.category, Counter())
            counts.update(item.surface_status for item in clause.items)
    exact_count = sum(item.surface_status == "exact" for item in items)
    normalized_count = sum(item.canonical_status == "normalized" for item in items)
    identity_count = sum(item.canonical_status == "identity" for item in items)
    return {
        "model_item_count": len(items),
        "exact_count": exact_count,
        "unmapped_count": len(items) - exact_count,
        "exact_rate": exact_count / len(items) if items else None,
        "canonical_normalized_count": normalized_count,
        "canonical_identity_count": identity_count,
        "by_category": {
            category: {
                "model_item_count": sum(counts.values()),
                "exact_count": counts["exact"],
                "unmapped_count": counts["unmapped"],
                "exact_rate": counts["exact"] / sum(counts.values()),
            }
            for category, counts in sorted(by_category.items())
        },
    }


def _validate_v2_artifacts(
    manifest: UnifiedEvaluationManifest,
    source_predictions: UnifiedPredictionFile,
    replay: UnifiedPredictionFile,
    projection: ModelFirstV2ProjectionFile,
) -> None:
    _validate_source_predictions(manifest, source_predictions)
    source_hash = json_payload_sha256(source_predictions.model_dump(mode="json"))
    if projection.dataset_version != manifest.dataset_version:
        raise ValueError("projection dataset version mismatch")
    if projection.source_prediction_version != source_predictions.prediction_version:
        raise ValueError("projection source prediction version mismatch")
    if projection.source_prediction_payload_sha256 != source_hash:
        raise ValueError("projection source prediction payload changed")
    expected_replay, expected_projection = build_model_first_v2_replay(
        manifest, source_predictions
    )
    if replay != expected_replay:
        raise ValueError("offline replay does not match deterministic rebuild")
    if projection != expected_projection:
        raise ValueError("surface projection does not match deterministic rebuild")
    for prediction in replay.predictions:
        if prediction.model_call_count != 0:
            raise ValueError("offline replay must record zero model calls")
        output = UnifiedJDModelOutput.model_validate(prediction.output)
        if output is None:
            raise ValueError("offline replay output is missing")
