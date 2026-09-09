from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.domain.product_jd import ProductJDModelOutput, validate_product_jd_output
from src.evaluation.product_metrics import evaluate_product_dataset

DEFAULT_LABELS = (
    ROOT
    / "artifacts"
    / "evaluation"
    / "product-jd-test100-human-reviewed-v1-2026-09-09.json"
)
DEFAULT_FREEZE_RECEIPT = (
    ROOT / "datasets" / "product_jd_test100_label_freeze_v1_2026_09_09.json"
)
DEFAULT_PREDICTIONS = (
    ROOT
    / "artifacts"
    / "evaluation"
    / "product-jd-test100-terra-medium-two-stage-v1-predictions.json"
)
DEFAULT_REPORT = (
    ROOT
    / "artifacts"
    / "evaluation"
    / "product-jd-test100-terra-medium-two-stage-v1-report.json"
)
DEFAULT_RECEIPT = (
    ROOT / "datasets" / "product_jd_test100_evaluation_receipt_v1_2026_09_09.json"
)

EVALUATION_RECEIPT_VERSION = "product-jd-test100-evaluation-receipt-v1-2026-09-09"
EXPECTED_DATASET_VERSION = "product-jd-test100-human-reviewed-v1-2026-09-09"
EXPECTED_PREDICTION_VERSION = "product-jd-test100-terra-medium-two-stage-v1"
EXPECTED_CASE_COUNT = 100


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _write_immutable_json(path: Path, payload: Any) -> None:
    content = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") != content:
        raise FileExistsError(f"Refusing to overwrite evaluation receipt: {path}")
    path.write_text(content, encoding="utf-8")


def build_evaluation_receipt(
    *,
    labels_path: Path = DEFAULT_LABELS,
    freeze_receipt_path: Path = DEFAULT_FREEZE_RECEIPT,
    predictions_path: Path = DEFAULT_PREDICTIONS,
    report_path: Path = DEFAULT_REPORT,
) -> dict[str, Any]:
    labels = _load_json(labels_path)
    freeze = _load_json(freeze_receipt_path)
    predictions = _load_json(predictions_path)
    report = _load_json(report_path)

    if labels.get("dataset_version") != EXPECTED_DATASET_VERSION:
        raise ValueError("Unexpected formal test-100 dataset version")
    if labels.get("case_count") != EXPECTED_CASE_COUNT:
        raise ValueError("Formal labels do not contain exactly 100 cases")
    if freeze.get("status") != "frozen":
        raise ValueError("Label freeze receipt is not frozen")
    if freeze.get("prediction_status") != "not_generated_or_viewed":
        raise ValueError("Label freeze was not recorded before predictions")
    if freeze["labels"].get("path") != _display_path(labels_path):
        raise ValueError("Freeze receipt references a different label file")
    if freeze["labels"].get("sha256") != _sha256_file(labels_path):
        raise ValueError("Frozen label hash changed after prediction")

    runtime = freeze["runtime"]
    for name, reference in runtime["files"].items():
        path = ROOT / reference["path"]
        if reference["sha256"] != _sha256_file(path):
            raise ValueError(f"Frozen runtime file changed: {name}")

    if predictions.get("prediction_version") != EXPECTED_PREDICTION_VERSION:
        raise ValueError("Unexpected formal prediction version")
    if predictions.get("dataset_version") != labels["dataset_version"]:
        raise ValueError("Predictions reference a different label dataset")
    expected_runtime = {
        "model": runtime["model"],
        "reasoning_effort": runtime["reasoning_effort"],
        "parser_version": runtime["product_parser_version"],
        "prompt_version": runtime["product_prompt_version"],
    }
    for field, expected in expected_runtime.items():
        if predictions.get(field) != expected:
            raise ValueError(f"Formal prediction runtime mismatch: {field}")

    prediction_rows = predictions.get("predictions")
    if not isinstance(prediction_rows, list) or len(prediction_rows) != EXPECTED_CASE_COUNT:
        raise ValueError("Formal prediction file does not contain exactly 100 rows")
    expected_ids = [case["id"] for case in labels["cases"]]
    prediction_ids = [row["case_id"] for row in prediction_rows]
    if prediction_ids != expected_ids or len(set(prediction_ids)) != EXPECTED_CASE_COUNT:
        raise ValueError("Formal predictions do not exactly follow frozen case order")

    labels_by_id = {case["id"]: case for case in labels["cases"]}
    failures: Counter[str] = Counter()
    for row in prediction_rows:
        output_payload = row.get("output")
        if output_payload is None:
            failures[row.get("failure_code") or "unknown"] += 1
            continue
        output = ProductJDModelOutput.model_validate(output_payload)
        validate_product_jd_output(
            output,
            labels_by_id[row["case_id"]]["raw_content"],
        )

    recomputed_report = evaluate_product_dataset(labels, predictions)
    recomputed_report["prediction_version"] = predictions["prediction_version"]
    recomputed_report["model"] = predictions["model"]
    if recomputed_report != report:
        raise ValueError("Stored report differs from deterministic metric recomputation")
    if report.get("case_count") != EXPECTED_CASE_COUNT:
        raise ValueError("Formal report case count is not 100")

    model_calls = sum(int(row.get("model_call_count") or 0) for row in prediction_rows)
    call_count_distribution = Counter(
        int(row.get("model_call_count") or 0) for row in prediction_rows
    )
    primary = report["primary_metrics"]
    any_of = report["requirements"]["any_of"]
    return {
        "receipt_version": EVALUATION_RECEIPT_VERSION,
        "status": "formal_evaluation_complete",
        "evaluated_at": "2026-09-09",
        "protocol": {
            "formal_run_count": 1,
            "labels_frozen_before_prediction": True,
            "predictions_used_to_edit_labels": False,
            "model": predictions["model"],
            "reasoning_effort": predictions["reasoning_effort"],
            "response_format": predictions["response_format"],
            "validation_retries_per_stage": 1,
        },
        "counts": {
            "case_count": report["case_count"],
            "prediction_count": report["prediction_count"],
            "parse_success_count": report["parse_success_count"],
            "parse_failure_count": len(prediction_rows) - report["parse_success_count"],
            "schema_valid_count": report["schema_valid_count"],
            "evidence_valid_count": report["evidence_valid_count"],
            "model_call_count": model_calls,
            "model_call_count_distribution": {
                str(key): value for key, value in sorted(call_count_distribution.items())
            },
            "failure_codes": dict(sorted(failures.items())),
            "expected_any_of_group_count": any_of["aligned_relation_groups"][
                "expected_count"
            ],
            "expected_any_of_item_count": any_of["item_coverage"]["expected_count"],
        },
        "primary_metrics": primary,
        "artifacts": {
            "freeze_receipt": {
                "path": _display_path(freeze_receipt_path),
                "sha256": _sha256_file(freeze_receipt_path),
                "version": freeze["freeze_version"],
            },
            "labels": {
                "path": _display_path(labels_path),
                "sha256": _sha256_file(labels_path),
                "version": labels["dataset_version"],
            },
            "predictions": {
                "path": _display_path(predictions_path),
                "sha256": _sha256_file(predictions_path),
                "version": predictions["prediction_version"],
            },
            "report": {
                "path": _display_path(report_path),
                "sha256": _sha256_file(report_path),
                "version": report["evaluation_version"],
            },
        },
        "interpretation": {
            "recommended_resume_metrics": [
                "parse_success_rate",
                "schema_valid_rate",
                "evidence_valid_rate",
                "facts_value_macro_f1",
                "requirement_source_character_f1",
                "any_of_aligned_relation_group_f1",
                "responsibility_source_character_f1",
            ],
            "strict_boundary_metric": "any_of_aligned_exact_group_f1",
            "strict_boundary_note": (
                "This lower exact-item score reflects item-boundary disagreement and "
                "must not be presented as the relation-classification score."
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate and finalize the one-time Product JD test-100 evaluation"
    )
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--freeze-receipt", type=Path, default=DEFAULT_FREEZE_RECEIPT)
    parser.add_argument("--predictions", type=Path, default=DEFAULT_PREDICTIONS)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    args = parser.parse_args()
    receipt = build_evaluation_receipt(
        labels_path=args.labels,
        freeze_receipt_path=args.freeze_receipt,
        predictions_path=args.predictions,
        report_path=args.report,
    )
    _write_immutable_json(args.receipt, receipt)
    metrics = receipt["primary_metrics"]
    print(
        "product-jd-test100-evaluation-finalized "
        f"cases={receipt['counts']['case_count']} "
        f"parse_success={metrics['parse_success_rate']:.4f} "
        f"facts_value_f1={metrics['facts_value_macro_f1']:.4f} "
        f"requirements_character_f1="
        f"{metrics['requirement_source_character_f1']:.4f} "
        f"any_of_relation_f1={metrics['any_of_aligned_relation_group_f1']:.4f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
