from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse

from pydantic import ValidationError

from scripts.run_unified_jd_model_first_v1 import (
    DEFAULT_MANIFEST,
    DEFAULT_PREDICTIONS,
)
from src.config import get_settings
from src.domain.job import RawJobDocument
from src.domain.unified_jd_extraction import UnifiedJDExtractionV3
from src.evaluation.predict_unified import generate_unified_predictions
from src.evaluation.unified_metrics import evaluate_unified_manifest
from src.evaluation.unified_models import (
    UnifiedEvaluationManifest,
    UnifiedPredictionFile,
)
from src.infrastructure.llm_client import (
    ModelClientError,
    create_structured_model_client,
)
from src.services.unified_jd_parser import UnifiedJDParser

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT / "artifacts/evaluation"
SELECTED_CASE_ID = "campus-ai-121"
MAX_TOTAL_MODEL_CALLS = 21
EXPECTED_PRIOR_MODEL_CALLS = 20

DEFAULT_PROBE_MANIFEST = (
    ARTIFACT_DIR
    / "unified-jd-model-first-v3-surface-probe-case121-manifest-2026-09-05.json"
)
DEFAULT_REQUEST = (
    ARTIFACT_DIR
    / "unified-jd-model-first-v3-surface-probe-case121-request-2026-09-05.json"
)
DEFAULT_PREDICTION = (
    ARTIFACT_DIR
    / "unified-jd-model-first-v3-surface-probe-case121-prediction-2026-09-05.json"
)
DEFAULT_CHECKPOINT = DEFAULT_PREDICTION.with_suffix(".checkpoint.json")
DEFAULT_RAW_RESPONSE = (
    ARTIFACT_DIR
    / "unified-jd-model-first-v3-surface-probe-case121-raw-response-2026-09-05.json"
)
DEFAULT_REPORT = (
    ARTIFACT_DIR
    / "unified-jd-model-first-v3-surface-probe-case121-report-2026-09-05.json"
)
V3_LAYER_PROJECTION = (
    ARTIFACT_DIR / "unified-jd-model-first-v3-dev20-layer-projection-2026-09-05.json"
)


def _write_new_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = (
        payload.model_dump_json(indent=2)  # type: ignore[attr-defined]
        if hasattr(payload, "model_dump_json")
        else json.dumps(payload, ensure_ascii=False, indent=2)
    )
    with path.open("x", encoding="utf-8", newline="\n") as output:
        output.write(rendered + "\n")


def _payload_sha256(payload: object) -> str:
    rendered = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _build_probe_manifest(
    source: UnifiedEvaluationManifest,
) -> UnifiedEvaluationManifest:
    selected = [case for case in source.cases if case.id == SELECTED_CASE_ID]
    if len(selected) != 1:
        raise ValueError(f"expected exactly one {SELECTED_CASE_ID} case")
    payload = source.model_dump(mode="json")
    payload.update(
        {
            "manifest_version": "unified-jd-model-first-v3-surface-probe-v1",
            "dataset_version": "unified-jd-model-first-v3-surface-probe-case121",
            "purpose": (
                "One-call probe of paired semantic_item and exact surface_item output."
            ),
            "source_policy": (
                "One frozen dev-20 case selected before the call because it had the "
                "highest v1 unmapped clause-item count."
            ),
            "thresholds": {},
            "cases": [selected[0].model_dump(mode="json")],
        }
    )
    return UnifiedEvaluationManifest.model_validate(payload)


def _baseline_surface_counts() -> dict[str, int | float]:
    projection = json.loads(V3_LAYER_PROJECTION.read_text(encoding="utf-8"))
    record = next(
        item for item in projection["records"] if item["case_id"] == SELECTED_CASE_ID
    )
    items = [item for clause in record["clauses"] for item in clause["items"]]
    exact = sum(item["surface_status"] == "exact" for item in items)
    return {
        "semantic_item_count": len(items),
        "exact_surface_count": exact,
        "unmapped_surface_count": len(items) - exact,
        "exact_surface_rate": exact / len(items),
    }


def _v3_surface_counts(raw_output: object) -> dict[str, object]:
    try:
        extraction = UnifiedJDExtractionV3.model_validate(raw_output)
    except ValidationError as error:
        return {
            "schema_valid": False,
            "validation_errors": [
                {
                    "location": list(item["loc"]),
                    "message": item["msg"],
                    "type": item["type"],
                }
                for item in error.errors()
            ],
        }
    clause_items = [item for clause in extraction.clauses for item in clause.items]
    example_items = [
        item for clause in extraction.clauses for item in (clause.examples or [])
    ]
    fact_items = [
        item for mention in extraction.fact_mentions for item in mention.items
    ]
    return {
        "schema_valid": True,
        "fact_item_count": len(fact_items),
        "semantic_item_count": len(clause_items),
        "example_item_count": len(example_items),
        "semantic_equals_surface_count": sum(
            item.semantic_item == item.surface_item for item in clause_items
        ),
        "completed_semantic_item_count": sum(
            item.semantic_item != item.surface_item for item in clause_items
        ),
        "exact_surface_count": len(clause_items),
        "unmapped_surface_count": 0,
        "exact_surface_rate": 1.0 if clause_items else None,
    }


def _evaluation_summary(report: dict[str, object]) -> dict[str, object]:
    dimensions = report["dimensions"]  # type: ignore[index]
    return {
        "schema_valid_rate": report["schema_valid_rate"],
        "parse_success_rate": report["parse_success_rate"],
        "facts_macro_f1": dimensions["facts"]["macro_f1"],  # type: ignore[index]
        "category_f1": dimensions["category"]["overall"]["f1"],  # type: ignore[index]
        "level_f1": dimensions["level"]["overall"]["f1"],  # type: ignore[index]
        "relation_f1": dimensions["relation"]["overall"]["f1"],  # type: ignore[index]
        "canonical_items_f1": dimensions["canonical_items"]["overall"]["f1"],  # type: ignore[index]
        "evidence_localization_rate": report["evidence"]["localization_rate"],  # type: ignore[index]
        "prediction_failure_count": report["prediction_failure_count"],
    }


def main() -> int:
    reserved = [
        DEFAULT_PROBE_MANIFEST,
        DEFAULT_REQUEST,
        DEFAULT_PREDICTION,
        DEFAULT_CHECKPOINT,
        DEFAULT_RAW_RESPONSE,
        DEFAULT_REPORT,
    ]
    existing = [str(path) for path in reserved if path.exists()]
    if existing:
        raise SystemExit(f"refusing to repeat one-call v3 probe: {existing}")

    source_manifest = UnifiedEvaluationManifest.model_validate_json(
        DEFAULT_MANIFEST.read_text(encoding="utf-8")
    )
    prior_predictions = UnifiedPredictionFile.model_validate_json(
        DEFAULT_PREDICTIONS.read_text(encoding="utf-8")
    )
    prior_calls = sum(
        prediction.model_call_count or 0 for prediction in prior_predictions.predictions
    )
    if prior_calls != EXPECTED_PRIOR_MODEL_CALLS:
        raise SystemExit(
            "frozen prior-call count changed: "
            f"expected={EXPECTED_PRIOR_MODEL_CALLS}, actual={prior_calls}"
        )
    remaining_calls = MAX_TOTAL_MODEL_CALLS - prior_calls
    if remaining_calls != 1:
        raise SystemExit(
            f"probe requires exactly one remaining call, got {remaining_calls}"
        )

    settings = get_settings()
    hostname = urlparse(settings.llm_base_url or "").hostname
    if hostname != "api.deepseek.com":
        raise SystemExit(
            "v3 probe is authorized only for api.deepseek.com; "
            f"configured host={hostname!r}"
        )
    one_transport_attempt = settings.model_copy(update={"llm_max_retries": 0})
    try:
        client = create_structured_model_client(one_transport_attempt)
    except ModelClientError as error:
        raise SystemExit(f"cannot create DeepSeek client: {error}") from error

    probe_manifest = _build_probe_manifest(source_manifest)
    case = probe_manifest.cases[0]
    parser = UnifiedJDParser(client, mode="model_first_v3", validation_retries=0)
    request = parser.build_request(
        RawJobDocument(
            source_url=case.source.source_url,
            source_type="unified_evaluation",
            raw_content=case.raw_content,
        )
    )
    request_payload = request.model_dump(mode="json")
    request_artifact = {
        "experiment": "model-first-v3-surface-probe-case121",
        "authorization": (
            "User authorized the remaining DeepSeek call in the active task."
        ),
        "destination_host": hostname,
        "case_id": case.id,
        "input_sha256": case.source_content_sha256,
        "prior_model_calls": prior_calls,
        "maximum_total_model_calls": MAX_TOTAL_MODEL_CALLS,
        "maximum_new_model_calls": remaining_calls,
        "transport_retries": 0,
        "validation_retries": 0,
        "request_sha256": _payload_sha256(request_payload),
        "request": request_payload,
    }
    _write_new_json(DEFAULT_PROBE_MANIFEST, probe_manifest)
    _write_new_json(DEFAULT_REQUEST, request_artifact)

    predictions = asyncio.run(
        generate_unified_predictions(
            probe_manifest,
            client=client,
            concurrency=1,
            checkpoint_path=DEFAULT_CHECKPOINT,
            max_new_cases=1,
            max_model_calls=remaining_calls,
            stop_on_failure=True,
            parser_mode="model_first_v3",
            validation_retries=0,
        )
    )
    _write_new_json(DEFAULT_PREDICTION, predictions)
    new_calls = sum(
        prediction.model_call_count or 0 for prediction in predictions.predictions
    )
    if new_calls > remaining_calls or prior_calls + new_calls > MAX_TOTAL_MODEL_CALLS:
        raise RuntimeError("model-call budget invariant violated")

    prediction = predictions.predictions[0]
    attempts = prediction.diagnostics.get("model_attempts", [])
    raw_output = (
        attempts[-1].get("raw_model_output")
        if attempts and isinstance(attempts[-1], dict)
        else None
    )
    raw_artifact = {
        "experiment": "model-first-v3-surface-probe-case121",
        "case_id": case.id,
        "input_sha256": case.source_content_sha256,
        "model_call_count": new_calls,
        "attempts": attempts,
        "raw_model_output": raw_output,
    }
    _write_new_json(DEFAULT_RAW_RESPONSE, raw_artifact)

    baseline_prediction = next(
        item
        for item in prior_predictions.predictions
        if item.case_id == SELECTED_CASE_ID
    )
    baseline_evaluation = evaluate_unified_manifest(
        probe_manifest, [baseline_prediction]
    )
    probe_evaluation = evaluate_unified_manifest(
        probe_manifest, predictions.predictions
    )
    report = {
        "experiment": "model-first-v3-surface-probe-case121",
        "case_id": case.id,
        "model": predictions.model,
        "prompt_version": predictions.prompt_version,
        "parser_version": predictions.parser_version,
        "prior_model_calls": prior_calls,
        "new_model_calls": new_calls,
        "total_model_calls": prior_calls + new_calls,
        "maximum_total_model_calls": MAX_TOTAL_MODEL_CALLS,
        "transport_retries": 0,
        "validation_retries": 0,
        "failure_code": prediction.failure_code,
        "baseline_surface": _baseline_surface_counts(),
        "v3_surface": _v3_surface_counts(raw_output),
        "baseline_evaluation": _evaluation_summary(baseline_evaluation),
        "v3_evaluation": _evaluation_summary(probe_evaluation),
        "request_sha256": request_artifact["request_sha256"],
        "raw_response_sha256": _payload_sha256(raw_artifact),
    }
    _write_new_json(DEFAULT_REPORT, report)
    print(
        "model-first v3 one-call surface probe complete "
        f"case={case.id} new_calls={new_calls} "
        f"total_calls={prior_calls + new_calls}/{MAX_TOTAL_MODEL_CALLS} "
        f"failure={prediction.failure_code or 'none'}"
    )
    print(f"prediction={DEFAULT_PREDICTION}")
    print(f"raw_response={DEFAULT_RAW_RESPONSE}")
    print(f"report={DEFAULT_REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
