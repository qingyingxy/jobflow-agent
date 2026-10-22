from __future__ import annotations

from collections import Counter
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.domain.unified_jd import (
    ClauseLevel,
    ClauseRelation,
    FactFieldName,
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
    MODEL_FIRST_NORMALIZED_FACT_COMPILER_VERSION,
    UNIFIED_EXTRACTION_COMPILER_VERSION,
    CompiledUnifiedExtractionV2,
    compile_model_first_extraction_v2,
    compile_model_first_normalized_extraction_v3,
    compile_unified_extraction_v2,
    normalize_model_first_fact_item_v3,
)

MODEL_FIRST_V3_REPLAY_VERSION = "unified-jd-model-first-offline-replay-v3"
MODEL_FIRST_V3_PROJECTION_VERSION = "unified-jd-model-first-layer-projection-v3"
MODEL_FIRST_V3_EVALUATOR_VERSION = "unified-jd-model-first-evaluator-v3"

FACT_FIELDS: tuple[FactFieldName, ...] = (
    "job_type",
    "locations",
    "graduation_years",
    "education_requirements",
    "major_requirements",
    "internship_duration_months",
    "weekly_days",
    "earliest_start_date",
    "deadline",
)

SurfaceStatus = Literal["exact", "unmapped"]
NormalizationStatus = Literal["identity", "normalized", "failed"]
DerivationStatus = Literal["unchanged", "transformed", "backfilled", "dropped"]
FactValue = str | int | date


class ModelFirstV3EvidenceProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_text: NonEmptyText
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)
    occurrence_count: int = Field(ge=1)


class ModelFirstV3FactItemProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw_item: NonEmptyText
    surface_status: SurfaceStatus
    surface_item: NonEmptyText | None = None
    surface_start_char: int | None = Field(default=None, ge=0)
    surface_end_char: int | None = Field(default=None, ge=0)
    normalization_status: NormalizationStatus
    normalized_values: list[FactValue] = Field(default_factory=list)
    normalization_rule_ids: list[str] = Field(default_factory=list)
    normalization_error: str | None = None

    @model_validator(mode="after")
    def validate_layers(self) -> ModelFirstV3FactItemProjection:
        if self.surface_status == "exact":
            if (
                self.surface_item is None
                or self.surface_start_char is None
                or self.surface_end_char is None
                or self.surface_end_char <= self.surface_start_char
            ):
                raise ValueError("exact surface fact item requires a non-empty span")
        elif any(
            value is not None
            for value in (
                self.surface_item,
                self.surface_start_char,
                self.surface_end_char,
            )
        ):
            raise ValueError("unmapped surface fact item cannot carry a span")

        if self.normalization_status == "failed":
            if self.normalized_values or self.normalization_rule_ids:
                raise ValueError("failed normalization cannot carry normalized values")
            if self.normalization_error is None:
                raise ValueError("failed normalization requires an error")
        elif not self.normalized_values or not self.normalization_rule_ids:
            raise ValueError("successful normalization requires values and rule ids")
        return self


class ModelFirstV3FactMentionProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw_fact_index: int = Field(ge=0)
    field: FactFieldName
    level: ClauseLevel | None = None
    evidence: ModelFirstV3EvidenceProjection
    items: list[ModelFirstV3FactItemProjection] = Field(min_length=1)


class ModelFirstV3FactFieldProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: FactFieldName
    normalized_value: Any = None
    derived_value: Any = None
    derivation_status: DerivationStatus
    derivation_rule_ids: list[str] = Field(default_factory=list)
    evidence: list[ModelFirstV3EvidenceProjection] = Field(default_factory=list)


class ModelFirstV3ClauseItemProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw_item: NonEmptyText
    surface_status: SurfaceStatus
    surface_item: NonEmptyText | None = None
    surface_start_char: int | None = Field(default=None, ge=0)
    surface_end_char: int | None = Field(default=None, ge=0)
    normalized_item: NonEmptyText
    normalization_status: Literal["identity", "normalized"]
    normalization_rule_ids: list[str] = Field(min_length=1)
    derived_items: list[NonEmptyText] = Field(default_factory=list)
    derivation_rule_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_surface(self) -> ModelFirstV3ClauseItemProjection:
        if self.surface_status == "exact":
            if (
                self.surface_item is None
                or self.surface_start_char is None
                or self.surface_end_char is None
                or self.surface_end_char <= self.surface_start_char
            ):
                raise ValueError("exact surface clause item requires a non-empty span")
        elif any(
            value is not None
            for value in (
                self.surface_item,
                self.surface_start_char,
                self.surface_end_char,
            )
        ):
            raise ValueError("unmapped surface clause item cannot carry a span")
        if bool(self.derived_items) != bool(self.derivation_rule_ids):
            raise ValueError("derived clause items require matching provenance")
        return self


class ModelFirstV3ClauseProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw_clause_index: int = Field(ge=0)
    category: SemanticClauseCategory
    level: ClauseLevel
    relation: ClauseRelation
    evidence: ModelFirstV3EvidenceProjection
    items: list[ModelFirstV3ClauseItemProjection] = Field(min_length=1)
    examples: list[ModelFirstV3ClauseItemProjection] = Field(default_factory=list)


class ModelFirstV3ProjectionDiagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    path: str
    message: str


class ModelFirstV3CaseProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1, max_length=80)
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fact_mentions: list[ModelFirstV3FactMentionProjection] = Field(default_factory=list)
    fact_fields: list[ModelFirstV3FactFieldProjection]
    clauses: list[ModelFirstV3ClauseProjection] = Field(default_factory=list)
    diagnostics: list[ModelFirstV3ProjectionDiagnostic] = Field(default_factory=list)


class ModelFirstV3ProjectionFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    projection_version: str = MODEL_FIRST_V3_PROJECTION_VERSION
    dataset_version: str
    source_prediction_version: str
    source_prediction_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    records: list[ModelFirstV3CaseProjection]


def build_model_first_v3_replay(
    manifest: UnifiedEvaluationManifest,
    source_predictions: UnifiedPredictionFile,
) -> tuple[
    UnifiedPredictionFile,
    UnifiedPredictionFile,
    UnifiedPredictionFile,
    ModelFirstV3ProjectionFile,
]:
    """Build raw, normalized, and derived views from frozen model responses."""

    _validate_source_predictions(manifest, source_predictions)
    source_payload_sha256 = json_payload_sha256(
        source_predictions.model_dump(mode="json")
    )
    cases_by_id = {case.id: case for case in manifest.cases}
    stage_records: dict[str, list[UnifiedPredictionRecord]] = {
        "raw": [],
        "normalized": [],
        "derived": [],
    }
    projection_records: list[ModelFirstV3CaseProjection] = []

    for source_prediction in source_predictions.predictions:
        case = cases_by_id[source_prediction.case_id]
        raw_output = _last_raw_model_output(source_prediction)
        raw_compilation = compile_model_first_extraction_v2(
            raw_output, case.raw_content
        )
        normalized_compilation = compile_model_first_normalized_extraction_v3(
            raw_output, case.raw_content
        )
        derived_compilation = compile_unified_extraction_v2(
            raw_output, case.raw_content
        )
        compilations = {
            "raw": (MODEL_FIRST_FACT_COMPILER_VERSION, raw_compilation),
            "normalized": (
                MODEL_FIRST_NORMALIZED_FACT_COMPILER_VERSION,
                normalized_compilation,
            ),
            "derived": (
                UNIFIED_EXTRACTION_COMPILER_VERSION,
                derived_compilation,
            ),
        }
        for stage, (compiler_version, compilation) in compilations.items():
            stage_records[stage].append(
                _replay_record(
                    stage=stage,
                    compiler_version=compiler_version,
                    compilation=compilation,
                    source_prediction=source_prediction,
                    source_payload_sha256=source_payload_sha256,
                    input_sha256=case.source_content_sha256,
                )
            )
        projection_records.append(
            _project_case(
                case_id=case.id,
                input_sha256=case.source_content_sha256,
                raw_content=case.raw_content,
                raw_output=raw_output,
                normalized_compilation=normalized_compilation,
                derived_compilation=derived_compilation,
            )
        )

    replays = tuple(
        UnifiedPredictionFile(
            prediction_version=f"offline-v3-{stage}-{manifest.dataset_version}",
            schema_version=source_predictions.schema_version,
            parser_version=f"{MODEL_FIRST_V3_REPLAY_VERSION}-{stage}",
            prompt_version=source_predictions.prompt_version,
            model=source_predictions.model,
            generated_at=source_predictions.generated_at,
            predictions=stage_records[stage],
        )
        for stage in ("raw", "normalized", "derived")
    )
    projection = ModelFirstV3ProjectionFile(
        dataset_version=manifest.dataset_version,
        source_prediction_version=source_predictions.prediction_version,
        source_prediction_payload_sha256=source_payload_sha256,
        records=projection_records,
    )
    return replays[0], replays[1], replays[2], projection


def evaluate_model_first_v3(
    manifest: UnifiedEvaluationManifest,
    source_predictions: UnifiedPredictionFile,
    raw_replay: UnifiedPredictionFile,
    normalized_replay: UnifiedPredictionFile,
    derived_replay: UnifiedPredictionFile,
    projection: ModelFirstV3ProjectionFile,
) -> dict[str, Any]:
    _validate_v3_artifacts(
        manifest,
        source_predictions,
        raw_replay,
        normalized_replay,
        derived_replay,
        projection,
    )
    replay_by_stage = {
        "raw": raw_replay,
        "normalized": normalized_replay,
        "derived": derived_replay,
    }
    reports = {
        stage: evaluate_unified_manifest(manifest, replay.predictions)
        for stage, replay in replay_by_stage.items()
    }
    stages = {stage: _stage_metrics(report) for stage, report in reports.items()}
    canonicalized_predictions = []
    for prediction in normalized_replay.predictions:
        canonicalized, _ = canonicalize_unified_output(prediction.output or {})
        canonicalized_predictions.append(
            prediction.model_copy(
                update={"output": canonicalized.model_dump(mode="json")}
            )
        )
    canonical_report = evaluate_unified_manifest(manifest, canonicalized_predictions)
    layer_metrics = _layer_metrics(projection)
    all_stage_checks = {
        f"{stage}_{check}": value
        for stage, metrics in stages.items()
        for check, value in metrics["hard_checks"].items()
    }
    raw_f1 = stages["raw"]["facts"]["macro_f1"]
    normalized_f1 = stages["normalized"]["facts"]["macro_f1"]
    derived_f1 = stages["derived"]["facts"]["macro_f1"]
    return {
        "evaluation_version": MODEL_FIRST_V3_EVALUATOR_VERSION,
        "dataset_version": manifest.dataset_version,
        "case_count": len(manifest.cases),
        "model_api_called": False,
        "source_prediction_payload_sha256": (
            projection.source_prediction_payload_sha256
        ),
        "hard_gate": {
            "passed": all(all_stage_checks.values()),
            "checks": all_stage_checks,
        },
        "stages": stages,
        "facts": {
            "normalized_minus_raw_macro_f1": normalized_f1 - raw_f1,
            "derived_minus_normalized_macro_f1": derived_f1 - normalized_f1,
            "derived_minus_raw_macro_f1": derived_f1 - raw_f1,
        },
        "layers": layer_metrics,
        "canonical_items": {
            "normalization_input": "normalized-stage semantic items",
            "gold_exact_metrics": canonical_report["dimensions"]["canonical_items"],
        },
    }


def _replay_record(
    *,
    stage: str,
    compiler_version: str,
    compilation: CompiledUnifiedExtractionV2,
    source_prediction: UnifiedPredictionRecord,
    source_payload_sha256: str,
    input_sha256: str,
) -> UnifiedPredictionRecord:
    return UnifiedPredictionRecord(
        case_id=source_prediction.case_id,
        output=compilation.output.model_dump(mode="json"),
        model_call_count=0,
        diagnostics={
            "model_api_called": False,
            "projection_stage": stage,
            "source_model_call_count": source_prediction.model_call_count,
            "source_prediction_payload_sha256": source_payload_sha256,
            "input_sha256": input_sha256,
            "fact_compiler_version": compiler_version,
            "compilation_diagnostics": [
                item.as_dict() for item in compilation.diagnostics
            ],
        },
    )


def _stage_metrics(report: dict[str, Any]) -> dict[str, Any]:
    disagreements = report["unsupported_critical_facts"]["items"]
    source_unsupported = [
        item
        for item in disagreements
        if "missing_localized_evidence" in item["reasons"]
    ]
    label_disagreements = [
        item for item in disagreements if "value_not_in_human_label" in item["reasons"]
    ]
    hard_checks = {
        "schema_valid": report["schema_valid_rate"] == 1.0,
        "parse_success": report["parse_success_rate"] == 1.0,
        "all_evidence_located": report["evidence"]["localization_rate"] == 1.0,
        "no_source_unsupported_critical_facts": not source_unsupported,
    }
    return {
        "hard_checks": hard_checks,
        "facts": report["dimensions"]["facts"],
        "source_unsupported_critical_facts": {
            "count": len(source_unsupported),
            "items": source_unsupported,
        },
        "human_label_disagreements": {
            "count": len(label_disagreements),
            "items": label_disagreements,
        },
        "evidence": report["evidence"],
        "clause_semantics": {
            "category": report["dimensions"]["category"],
            "level": report["dimensions"]["level"],
            "relation": report["dimensions"]["relation"],
        },
    }


def _project_case(
    *,
    case_id: str,
    input_sha256: str,
    raw_content: str,
    raw_output: dict[str, Any],
    normalized_compilation: CompiledUnifiedExtractionV2,
    derived_compilation: CompiledUnifiedExtractionV2,
) -> ModelFirstV3CaseProjection:
    fact_mentions: list[ModelFirstV3FactMentionProjection] = []
    clauses: list[ModelFirstV3ClauseProjection] = []
    diagnostics: list[ModelFirstV3ProjectionDiagnostic] = []
    raw_facts = raw_output.get("fact_mentions")
    raw_clauses = raw_output.get("clauses")
    if not isinstance(raw_facts, list) or not isinstance(raw_clauses, list):
        raise TypeError(f"raw model envelope is invalid: {case_id}")

    for index, raw_fact in enumerate(raw_facts):
        parsed = _fact_mention_payload(raw_fact)
        if isinstance(parsed, str):
            diagnostics.append(
                ModelFirstV3ProjectionDiagnostic(
                    code="invalid_fact_projection",
                    path=f"fact_mentions[{index}]",
                    message=parsed,
                )
            )
            continue
        evidence = _evidence_projection(raw_content, parsed["source_text"])
        if evidence is None:
            diagnostics.append(
                ModelFirstV3ProjectionDiagnostic(
                    code="unlocated_fact_source",
                    path=f"fact_mentions[{index}].source_text",
                    message="fact source_text is not an exact JD substring",
                )
            )
            continue
        fact_mentions.append(
            ModelFirstV3FactMentionProjection(
                raw_fact_index=index,
                field=parsed["field"],
                level=parsed["level"],
                evidence=evidence,
                items=[
                    _project_fact_item(
                        field=parsed["field"],
                        raw_item=item,
                        source_text=parsed["source_text"],
                        source_start=evidence.start_char,
                    )
                    for item in parsed["raw_items"]
                ],
            )
        )

    for index, raw_clause in enumerate(raw_clauses):
        parsed = _clause_payload(raw_clause)
        if isinstance(parsed, str):
            diagnostics.append(
                ModelFirstV3ProjectionDiagnostic(
                    code="invalid_clause_projection",
                    path=f"clauses[{index}]",
                    message=parsed,
                )
            )
            continue
        evidence = _evidence_projection(raw_content, parsed["source_text"])
        if evidence is None:
            diagnostics.append(
                ModelFirstV3ProjectionDiagnostic(
                    code="unlocated_clause_source",
                    path=f"clauses[{index}].source_text",
                    message="clause source_text is not an exact JD substring",
                )
            )
            continue
        clauses.append(
            ModelFirstV3ClauseProjection(
                raw_clause_index=index,
                category=parsed["category"],
                level=parsed["level"],
                relation=parsed["relation"],
                evidence=evidence,
                items=[
                    _project_clause_item(
                        item,
                        parsed["source_text"],
                        evidence.start_char,
                    )
                    for item in parsed["items"]
                ],
                examples=[
                    _project_clause_item(
                        item,
                        parsed["source_text"],
                        evidence.start_char,
                    )
                    for item in parsed["examples"]
                ],
            )
        )

    return ModelFirstV3CaseProjection(
        case_id=case_id,
        input_sha256=input_sha256,
        raw_output_sha256=json_payload_sha256(raw_output),
        fact_mentions=fact_mentions,
        fact_fields=_fact_field_projections(
            raw_content,
            normalized_compilation,
            derived_compilation,
        ),
        clauses=clauses,
        diagnostics=diagnostics,
    )


def _fact_mention_payload(raw_fact: Any) -> dict[str, Any] | str:
    if not isinstance(raw_fact, dict):
        return "fact mention is not an object"
    field = raw_fact.get("field")
    if field not in FACT_FIELDS:
        return "fact field is invalid"
    raw_items = raw_fact.get("raw_items")
    if isinstance(raw_items, (str, int)) and not isinstance(raw_items, bool):
        raw_items = [raw_items]
    if not isinstance(raw_items, list) or not raw_items:
        return "fact raw_items are invalid"
    items = [
        str(item).strip()
        for item in raw_items
        if isinstance(item, (str, int))
        and not isinstance(item, bool)
        and str(item).strip()
    ]
    if len(items) != len(raw_items):
        return "fact raw_items contain unsupported values"
    source_text = raw_fact.get("source_text")
    if not isinstance(source_text, str) or not source_text.strip():
        return "fact source_text is invalid"
    level = raw_fact.get("level")
    if level not in {None, "required", "preferred", "mention"}:
        return "fact level is invalid"
    return {
        "field": field,
        "raw_items": items,
        "level": level,
        "source_text": source_text,
    }


def _clause_payload(raw_clause: Any) -> dict[str, Any] | str:
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
        isinstance(item, str) and item.strip() for item in examples
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


def _evidence_projection(
    raw_content: str,
    source_text: str,
) -> ModelFirstV3EvidenceProjection | None:
    start = raw_content.find(source_text)
    if start < 0:
        return None
    return ModelFirstV3EvidenceProjection(
        source_text=source_text,
        start_char=start,
        end_char=start + len(source_text),
        occurrence_count=raw_content.count(source_text),
    )


def _project_fact_item(
    *,
    field: FactFieldName,
    raw_item: str,
    source_text: str,
    source_start: int,
) -> ModelFirstV3FactItemProjection:
    local_start = source_text.find(raw_item)
    normalization = normalize_model_first_fact_item_v3(field, raw_item)
    normalized_values = list(normalization.values)
    normalization_status: NormalizationStatus
    if normalization.error is not None:
        normalization_status = "failed"
    elif len(normalized_values) == 1 and normalized_values[0] == raw_item:
        normalization_status = "identity"
    else:
        normalization_status = "normalized"
    surface = {
        "surface_status": "exact",
        "surface_item": raw_item,
        "surface_start_char": source_start + local_start,
        "surface_end_char": source_start + local_start + len(raw_item),
    }
    if local_start < 0:
        surface = {
            "surface_status": "unmapped",
            "surface_item": None,
            "surface_start_char": None,
            "surface_end_char": None,
        }
    return ModelFirstV3FactItemProjection(
        raw_item=raw_item,
        **surface,
        normalization_status=normalization_status,
        normalized_values=normalized_values,
        normalization_rule_ids=list(normalization.rule_ids),
        normalization_error=normalization.error,
    )


def _project_clause_item(
    raw_item: str,
    source_text: str,
    source_start: int,
) -> ModelFirstV3ClauseItemProjection:
    local_start = source_text.find(raw_item)
    mapping = canonicalize_item(raw_item)
    status = "identity" if mapping.rule_ids == ["canonical.identity"] else "normalized"
    surface = {
        "surface_status": "exact",
        "surface_item": raw_item,
        "surface_start_char": source_start + local_start,
        "surface_end_char": source_start + local_start + len(raw_item),
    }
    if local_start < 0:
        surface = {
            "surface_status": "unmapped",
            "surface_item": None,
            "surface_start_char": None,
            "surface_end_char": None,
        }
    return ModelFirstV3ClauseItemProjection(
        raw_item=raw_item,
        **surface,
        normalized_item=mapping.canonical_item,
        normalization_status=status,
        normalization_rule_ids=mapping.rule_ids,
    )


def _fact_field_projections(
    raw_content: str,
    normalized_compilation: CompiledUnifiedExtractionV2,
    derived_compilation: CompiledUnifiedExtractionV2,
) -> list[ModelFirstV3FactFieldProjection]:
    normalized = normalized_compilation.output.facts.model_dump(mode="json")
    derived = derived_compilation.output.facts.model_dump(mode="json")
    locally_backfilled = {
        diagnostic.path.removeprefix("facts.")
        for diagnostic in derived_compilation.diagnostics
        if diagnostic.code == "locally_backfilled_fact"
    }
    result = []
    for field in FACT_FIELDS:
        normalized_value = normalized[field]
        derived_value = derived[field]
        status = _derivation_status(normalized_value, derived_value)
        evidence = [
            projection
            for item in derived["evidence"]
            if item["field"] == field
            for projection in [_evidence_projection(raw_content, item["source_text"])]
            if projection is not None
        ]
        result.append(
            ModelFirstV3FactFieldProjection(
                field=field,
                normalized_value=normalized_value,
                derived_value=derived_value,
                derivation_status=status,
                derivation_rule_ids=_derivation_rule_ids(
                    field,
                    status,
                    field in locally_backfilled,
                ),
                evidence=evidence,
            )
        )
    return result


def _derivation_status(normalized: Any, derived: Any) -> DerivationStatus:
    if normalized == derived:
        return "unchanged"
    if normalized is None and derived is not None:
        return "backfilled"
    if normalized is not None and derived is None:
        return "dropped"
    return "transformed"


def _derivation_rule_ids(
    field: FactFieldName,
    status: DerivationStatus,
    locally_backfilled: bool,
) -> list[str]:
    if status == "unchanged":
        return []
    if locally_backfilled:
        return ["fact.derive.local-source-backfill"]
    if field == "education_requirements":
        return ["fact.derive.education-source-context"]
    if field == "major_requirements":
        return ["fact.derive.major-open-scope"]
    return ["fact.derive.source-value-fallback"]


def _layer_metrics(projection: ModelFirstV3ProjectionFile) -> dict[str, Any]:
    fact_items = [
        item
        for record in projection.records
        for mention in record.fact_mentions
        for item in mention.items
    ]
    clause_items = [
        item
        for record in projection.records
        for clause in record.clauses
        for item in clause.items
    ]
    example_items = [
        item
        for record in projection.records
        for clause in record.clauses
        for item in clause.examples
    ]
    derivations = [
        field for record in projection.records for field in record.fact_fields
    ]
    fact_statuses = Counter(item.normalization_status for item in fact_items)
    clause_statuses = Counter(item.normalization_status for item in clause_items)
    derivation_statuses = Counter(item.derivation_status for item in derivations)
    return {
        "facts": {
            "raw_item_count": len(fact_items),
            "exact_surface_count": sum(
                item.surface_status == "exact" for item in fact_items
            ),
            "unmapped_surface_count": sum(
                item.surface_status == "unmapped" for item in fact_items
            ),
            "normalization_statuses": dict(sorted(fact_statuses.items())),
            "derivation_statuses": dict(sorted(derivation_statuses.items())),
        },
        "clauses": {
            "raw_item_count": len(clause_items),
            "exact_surface_count": sum(
                item.surface_status == "exact" for item in clause_items
            ),
            "unmapped_surface_count": sum(
                item.surface_status == "unmapped" for item in clause_items
            ),
            "normalization_statuses": dict(sorted(clause_statuses.items())),
            "derived_item_count": sum(len(item.derived_items) for item in clause_items),
            "example_item_count": len(example_items),
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


def _validate_v3_artifacts(
    manifest: UnifiedEvaluationManifest,
    source_predictions: UnifiedPredictionFile,
    raw_replay: UnifiedPredictionFile,
    normalized_replay: UnifiedPredictionFile,
    derived_replay: UnifiedPredictionFile,
    projection: ModelFirstV3ProjectionFile,
) -> None:
    _validate_source_predictions(manifest, source_predictions)
    expected = build_model_first_v3_replay(manifest, source_predictions)
    actual = (raw_replay, normalized_replay, derived_replay, projection)
    if actual != expected:
        raise ValueError("v3 artifacts do not match deterministic offline rebuild")
    for replay in actual[:3]:
        for prediction in replay.predictions:
            if prediction.model_call_count != 0:
                raise ValueError("offline replay must record zero model calls")
            UnifiedJDModelOutput.model_validate(prediction.output)
