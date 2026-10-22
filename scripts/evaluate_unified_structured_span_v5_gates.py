from __future__ import annotations

import argparse
import copy
import hashlib
import json
import subprocess
import sys
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.evaluate_unified_structured_span_v4_development import (
    _attachment_example_edge_keys,
    _attachment_parent_keys,
    _connector_role_map,
    _coordination_member_keys,
    _scope_edge_keys,
    _wrapper_keys,
    evaluate_predictions,
)

ROOT = Path(__file__).resolve().parents[1]
DATE = "2026-09-05"
PREREGISTRATION_PATH = (
    ROOT / "datasets/unified_jd_structured_span_v5_preregistration_v1_2026-09-04.json"
)
PREREGISTRATION_FREEZE_PATH = (
    ROOT
    / "datasets/unified_jd_structured_span_v5_preregistration_freeze_v1_2026-09-04.json"
)
SOURCE_FREEZE_PATH = (
    ROOT / "datasets/unified_jd_structured_span_v5_source_freeze_v1_2026-09-05.json"
)
V5_PATH = ROOT / "src/domain/unified_jd_structured_spans_v5.py"
V4_PATH = ROOT / "src/domain/unified_jd_structured_spans_v4.py"
LABELS_PATH = (
    ROOT / "datasets/"
    "unified_jd_structured_span_v5_mechanism_development_labels_v1_2026-09-04.json"
)
V4_BASELINE_RAW_PATH = (
    ROOT / "artifacts/evaluation/"
    "unified-jd-structured-span-v5-mechanism-development-v4-baseline-raw-v1-2026-09-04.json"
)
LEGACY_GOLD_PATH = (
    ROOT / "datasets/unified_jd_structured_span_v4_development_gold_v1_2026-09-04.json"
)
EXTERNAL_DEVELOPMENT_PATH = (
    ROOT / "datasets/"
    "unified_jd_structured_span_v4_corpus_external_revealed_development_v1_2026-09-04.json"
)
EXTERNAL_V4_RAW_PATH = (
    ROOT / "artifacts/evaluation/"
    "unified-jd-structured-span-v4-corpus-external-raw-v1-2026-09-04.json"
)
PROJECTION_FIXTURE_PATHS = (
    ROOT / "datasets/unified_jd_canonical_items_contract_v1.json",
    ROOT / "datasets/unified_jd_surface_holdout_labels_v1_2026-09-04.json",
    ROOT / "datasets/unified_jd_surface_holdout_labels_v2_2026-09-04.json",
)
DEVELOPMENT_RAW_PATH = (
    ROOT / "artifacts/evaluation/"
    "unified-jd-structured-span-v5-mechanism-development-v5-raw-v1-2026-09-05.json"
)
REGRESSION_RAW_PATH = (
    ROOT / "artifacts/evaluation/"
    "unified-jd-structured-span-v5-regression-raw-v1-2026-09-05.json"
)
REPORT_PATH = (
    ROOT / "artifacts/evaluation/"
    "unified-jd-structured-span-v5-development-regression-report-v1-2026-09-05.json"
)
FINDINGS_PATH = (
    ROOT / "artifacts/evaluation/"
    "unified-jd-structured-span-v5-development-regression-findings-v1-2026-09-05.md"
)
RECEIPT_PATH = (
    ROOT / "artifacts/evaluation/"
    "unified-jd-structured-span-v5-development-regression-receipt-v1-2026-09-05.json"
)
OUTPUT_PATHS = (
    DEVELOPMENT_RAW_PATH,
    REGRESSION_RAW_PATH,
    REPORT_PATH,
    FINDINGS_PATH,
    RECEIPT_PATH,
)
PRIMARY_LAYERS = (
    "wrappers",
    "coordination_members",
    "shared_scope_edges",
    "example_attachment_parents",
    "example_attachment_edges",
    "surface_projection",
    "example_projection",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _serialized(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _write_new(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as output:
        output.write(content)


def _validate_hash_reference(reference: dict[str, Any]) -> None:
    path = ROOT / reference["path"]
    actual = _sha256(path)
    if actual != reference["sha256"]:
        raise ValueError(
            f"frozen hash mismatch for {reference['path']}: "
            f"expected {reference['sha256']}, got {actual}"
        )


def _validate_frozen_inputs() -> tuple[dict[str, Any], dict[str, Any]]:
    preregistration = _load(PREREGISTRATION_PATH)
    preregistration_freeze = _load(PREREGISTRATION_FREEZE_PATH)
    source_freeze = _load(SOURCE_FREEZE_PATH)

    _validate_hash_reference(preregistration_freeze["artifacts"]["preregistration"])
    for reference in preregistration["inputs"].values():
        _validate_hash_reference(reference)
    for reference in source_freeze["artifacts"].values():
        _validate_hash_reference(reference)

    if preregistration["evaluation_protocol"]["all_criteria_conjunctive"] is not True:
        raise ValueError("preregistration no longer requires conjunctive gates")
    if preregistration["scope"]["model_calls_allowed"] is not False:
        raise ValueError("preregistration unexpectedly permits model calls")
    if preregistration["scope"]["network_calls_allowed"] is not False:
        raise ValueError("preregistration unexpectedly permits network calls")
    if source_freeze["status"] != "v5_source_frozen_before_one_time_gates":
        raise ValueError("v5 source freeze status is invalid")
    if _sha256(V4_PATH) != (
        "e09e056cab75e651937391ce5410e6df7c94477c85565abb1425bbe85cfcb094"
    ):
        raise ValueError("frozen v4 parser changed")
    existing = [_relative(path) for path in OUTPUT_PATHS if path.exists()]
    if existing:
        raise FileExistsError(f"one-time gate output already exists: {existing}")

    labels = _load(LABELS_PATH)
    if len(labels["fixtures"]) != 20:
        raise ValueError("development labels must contain exactly 20 fixtures")
    if len({fixture["id"] for fixture in labels["fixtures"]}) != 20:
        raise ValueError("development fixture ids must be unique")
    return preregistration, labels


def _normalize_mechanism_gold(labels: dict[str, Any]) -> dict[str, Any]:
    gold = copy.deepcopy(labels)
    gold["gold_version"] = labels["labels_version"]
    gold["status"] = "revealed_mechanism_development_not_holdout"
    for fixture in gold["fixtures"]:
        fixture["diagnostic_status"] = fixture["development_role"]
    return gold


def _normalize_external_gold(dataset: dict[str, Any]) -> dict[str, Any]:
    fixtures: list[dict[str, Any]] = []
    for item in dataset["fixtures"]:
        fixture = copy.deepcopy(item["gold"])
        fixture["diagnostic_status"] = "revealed_external_development"
        fixtures.append(fixture)
    return {
        "gold_version": "revealed-corpus-external-v4-gold-v1",
        "status": "revealed_corpus_external_development_only",
        "fixtures": fixtures,
    }


def _run_v5_predictions(gold: dict[str, Any], scope: str) -> dict[str, Any]:
    from src.domain.unified_jd_structured_spans_v5 import (
        STRUCTURED_SPAN_PARSER_VERSION,
        extract_surface_items,
    )

    records: list[dict[str, Any]] = []
    for fixture in gold["fixtures"]:
        try:
            extraction = extract_surface_items(
                fixture["source_text"], fixture["category"]
            )
            records.append(
                {
                    "id": fixture["id"],
                    "category": fixture["category"],
                    "source_text": fixture["source_text"],
                    "error": None,
                    "items": list(extraction.items),
                    "examples": list(extraction.examples),
                    "rule_ids": list(extraction.rule_ids),
                    "parsed_clause": asdict(extraction.parsed_clause),
                }
            )
        except Exception as error:  # noqa: BLE001 - parser errors are gate results
            records.append(
                {
                    "id": fixture["id"],
                    "category": fixture["category"],
                    "source_text": fixture["source_text"],
                    "error": f"{type(error).__name__}: {error}",
                    "items": [],
                    "examples": [],
                    "rule_ids": [],
                    "parsed_clause": None,
                }
            )
    return {
        "raw_version": f"unified-jd-structured-span-v5-{scope}-raw-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": scope,
        "parser_version": STRUCTURED_SPAN_PARSER_VERSION,
        "parser_path": _relative(V5_PATH),
        "parser_sha256": _sha256(V5_PATH),
        "model_call_count": 0,
        "network_call_count": 0,
        "records": records,
    }


def _metric_snapshot(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "fixture_count": report["evaluation_scope"]["fixture_count"],
        "structure_validation_error_count": report["structure_validation_errors"],
        "wrapper_span_f1": report["wrappers"]["f1"],
        "wrapper_exact_fixture_count": report["wrappers"]["exact_fixture_count"],
        "connector_classification_accuracy": report["connector_classification"][
            "accuracy"
        ],
        "coordination_member_f1": report["coordination_members"]["f1"],
        "coordination_member_exact_fixture_count": report["coordination_members"][
            "exact_fixture_count"
        ],
        "shared_scope_edge_f1": report["shared_scope_edges"]["f1"],
        "shared_scope_exact_fixture_count": report["shared_scope_edges"][
            "exact_fixture_count"
        ],
        "example_attachment_parent_f1": report["example_attachment_parents"]["f1"],
        "example_attachment_edge_f1": report["example_attachment_edges"]["f1"],
        "example_attachment_exact_fixture_count": report["example_attachment_edges"][
            "exact_fixture_count"
        ],
        "surface_projection_f1": report["projection"]["surface_items"]["f1"],
        "surface_projection_exact_fixture_count": report["projection"]["surface_items"][
            "exact_fixture_count"
        ],
        "example_projection_f1": report["projection"]["examples"]["f1"],
        "example_projection_exact_fixture_count": report["projection"]["examples"][
            "exact_fixture_count"
        ],
    }


def _subset_report(
    gold: dict[str, Any], raw: dict[str, Any], fixture_ids: set[str]
) -> dict[str, Any]:
    subset_gold = copy.deepcopy(gold)
    subset_gold["fixtures"] = [
        fixture for fixture in gold["fixtures"] if fixture["id"] in fixture_ids
    ]
    subset_raw = copy.deepcopy(raw)
    subset_raw["records"] = [
        record for record in raw["records"] if record["id"] in fixture_ids
    ]
    return evaluate_predictions(subset_gold, subset_raw)


def _layer_values(fixture: dict[str, Any], *, gold: bool, layer: str) -> list[Any]:
    if layer == "wrappers":
        return list(_wrapper_keys(fixture, gold=gold))
    if layer == "coordination_members":
        return list(_coordination_member_keys(fixture, gold=gold))
    if layer == "shared_scope_edges":
        return list(_scope_edge_keys(fixture, gold=gold))
    if layer == "example_attachment_parents":
        return list(_attachment_parent_keys(fixture, gold=gold))
    if layer == "example_attachment_edges":
        return list(_attachment_example_edge_keys(fixture, gold=gold))
    if layer == "connector_labels":
        return list(_connector_role_map(fixture, gold=gold).items())
    if layer == "surface_projection":
        return list(
            fixture["projection"]["surface_items"] if gold else fixture["items"]
        )
    if layer == "example_projection":
        return list(fixture["projection"]["examples"] if gold else fixture["examples"])
    raise ValueError(f"unsupported layer: {layer}")


def _difference_count(
    gold_fixture: dict[str, Any], prediction: dict[str, Any], layers: tuple[str, ...]
) -> int:
    if prediction["parsed_clause"] is None:
        return 10**9
    total = 0
    for layer in layers:
        expected = Counter(_layer_values(gold_fixture, gold=True, layer=layer))
        actual = Counter(_layer_values(prediction, gold=False, layer=layer))
        total += sum((expected - actual).values())
        total += sum((actual - expected).values())
    return total


def _layer_difference_counts(
    gold_fixture: dict[str, Any], prediction: dict[str, Any]
) -> dict[str, int]:
    return {
        layer: _difference_count(gold_fixture, prediction, (layer,))
        for layer in PRIMARY_LAYERS
    }


def _prediction_by_id(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {record["id"]: record for record in raw["records"]}


def _all_spans(value: Any) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if {"text", "start", "end"} <= set(value):
            spans.append(value)
        for child in value.values():
            spans.extend(_all_spans(child))
    elif isinstance(value, list):
        for child in value:
            spans.extend(_all_spans(child))
    return spans


def _anchoring_errors(raw_values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    for raw in raw_values:
        for record in raw["records"]:
            source = record["source_text"]
            for value in record["items"] + record["examples"]:
                if value not in source:
                    errors.append(
                        {
                            "scope": raw["scope"],
                            "id": record["id"],
                            "kind": "projection",
                            "value": value,
                        }
                    )
            for span in _all_spans(record["parsed_clause"]):
                if source[span["start"] : span["end"]] != span["text"]:
                    errors.append(
                        {
                            "scope": raw["scope"],
                            "id": record["id"],
                            "kind": "span",
                            "value": span,
                        }
                    )
    return errors


def _run_projection_regression() -> dict[str, Any]:
    from src.domain.unified_jd_structured_spans_v5 import extract_surface_items

    records: list[dict[str, Any]] = []
    for path in PROJECTION_FIXTURE_PATHS:
        for fixture in _load(path)["fixtures"]:
            try:
                extraction = extract_surface_items(
                    fixture["source_text"], fixture["category"]
                )
                actual_items = list(extraction.items)
                actual_examples = list(extraction.examples)
                error = None
            except Exception as caught:  # noqa: BLE001 - errors are gate results
                actual_items = []
                actual_examples = []
                error = f"{type(caught).__name__}: {caught}"
            records.append(
                {
                    "fixture_path": _relative(path),
                    "id": fixture["id"],
                    "category": fixture["category"],
                    "source_text": fixture["source_text"],
                    "expected_items": fixture["surface_items"],
                    "actual_items": actual_items,
                    "expected_examples": fixture["examples"] or [],
                    "actual_examples": actual_examples,
                    "exact": Counter(fixture["surface_items"]) == Counter(actual_items)
                    and Counter(fixture["examples"] or []) == Counter(actual_examples),
                    "error": error,
                }
            )
    return {
        "fixture_count": len(records),
        "exact_count": sum(record["exact"] for record in records),
        "records": records,
    }


def _run_structured_span_tests() -> dict[str, Any]:
    test_paths = sorted(ROOT.glob("tests/test_unified_jd_structured_span*.py"))
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        *[str(path) for path in test_paths],
    ]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return {
        "test_file_count": len(test_paths),
        "test_paths": [_relative(path) for path in test_paths],
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def _quality_metrics(report: dict[str, Any]) -> dict[str, float | int]:
    values: dict[str, float | int] = {
        "connector_classification.accuracy": report["connector_classification"][
            "accuracy"
        ]
    }
    sections = {
        "wrappers": report["wrappers"],
        "coordination_members": report["coordination_members"],
        "shared_scope_edges": report["shared_scope_edges"],
        "example_attachment_parents": report["example_attachment_parents"],
        "example_attachment_edges": report["example_attachment_edges"],
        "surface_projection": report["projection"]["surface_items"],
        "example_projection": report["projection"]["examples"],
    }
    for name, metric in sections.items():
        for key in ("precision", "recall", "f1", "exact_fixture_count"):
            values[f"{name}.{key}"] = metric[key]
    return values


def _exact_values(
    gold_fixture: dict[str, Any], prediction: dict[str, Any], layer: str
) -> bool:
    return _difference_count(gold_fixture, prediction, (layer,)) == 0


def _gate(
    passed: bool, *, actual: Any = None, requirement: Any = None, detail: Any = None
) -> dict[str, Any]:
    return {
        "passed": bool(passed),
        "actual": actual,
        "requirement": requirement,
        "detail": detail,
    }


def _build_development_gates(
    preregistration: dict[str, Any],
    gold: dict[str, Any],
    raw: dict[str, Any],
    report: dict[str, Any],
) -> dict[str, Any]:
    gates = preregistration["development_acceptance_gates"]
    metrics = _metric_snapshot(report)
    baseline_raw = _load(V4_BASELINE_RAW_PATH)
    predicted = _prediction_by_id(raw)
    baseline = _prediction_by_id(baseline_raw)
    gold_by_id = {fixture["id"]: fixture for fixture in gold["fixtures"]}

    g1_checks: dict[str, Any] = {}
    for threshold_name, minimum in gates["G1-aggregate-non-regression"].items():
        metric_name = threshold_name.removesuffix("_min")
        actual = metrics[metric_name]
        g1_checks[metric_name] = _gate(
            actual >= minimum, actual=actual, requirement=f">= {minimum}"
        )

    e2 = gates["G2-E2-wrapper-boundary"]
    e2_ids = set(e2["fixture_ids"])
    e2_layers = ("wrappers", "coordination_members", "surface_projection")
    e2_improvements = {
        fixture_id: {
            "baseline": _difference_count(
                gold_by_id[fixture_id], baseline[fixture_id], e2_layers
            ),
            "v5": _difference_count(
                gold_by_id[fixture_id], predicted[fixture_id], e2_layers
            ),
        }
        for fixture_id in sorted(e2_ids)
    }
    e2_improved_count = sum(
        value["v5"] < value["baseline"] for value in e2_improvements.values()
    )
    e2_metrics = _metric_snapshot(_subset_report(gold, raw, e2_ids))
    e2_requirements = e2["aggregate_requirements"]
    e2_downstream = e2_requirements["at_least_one_downstream_strictly_improves"]
    e2_checks = {
        "improved_fixture_count": _gate(
            e2_improved_count >= e2["required_improved_fixture_count"],
            actual=e2_improved_count,
            requirement=f">= {e2['required_improved_fixture_count']}",
            detail=e2_improvements,
        ),
        "wrapper_span_f1": _gate(
            e2_metrics["wrapper_span_f1"]
            > e2_requirements["wrapper_span_f1_strictly_greater_than"],
            actual=e2_metrics["wrapper_span_f1"],
            requirement=(
                f"> {e2_requirements['wrapper_span_f1_strictly_greater_than']}"
            ),
        ),
        "downstream_improvement": _gate(
            e2_metrics["coordination_member_f1"]
            > e2_downstream["coordination_member_f1_baseline"]
            or e2_metrics["surface_projection_f1"]
            > e2_downstream["surface_projection_f1_baseline"],
            actual={
                "coordination_member_f1": e2_metrics["coordination_member_f1"],
                "surface_projection_f1": e2_metrics["surface_projection_f1"],
            },
            requirement=e2_downstream,
        ),
    }

    e3 = gates["G3-E3-region-first-connector-role"]
    e3_ids = set(e3["fixture_ids"])
    e3_layers = (
        "connector_labels",
        "coordination_members",
        "example_attachment_edges",
        "surface_projection",
        "example_projection",
    )
    e3_improvements = {
        fixture_id: {
            "baseline": _difference_count(
                gold_by_id[fixture_id], baseline[fixture_id], e3_layers
            ),
            "v5": _difference_count(
                gold_by_id[fixture_id], predicted[fixture_id], e3_layers
            ),
        }
        for fixture_id in sorted(e3_ids)
    }
    e3_improved_count = sum(
        value["v5"] < value["baseline"] for value in e3_improvements.values()
    )
    e3_metrics = _metric_snapshot(_subset_report(gold, raw, e3_ids))
    e3_requirements = e3["aggregate_requirements"]
    e3_downstream = e3_requirements[
        "at_least_one_attachment_or_projection_metric_strictly_improves"
    ]
    e3_checks = {
        "improved_fixture_count": _gate(
            e3_improved_count >= e3["required_improved_fixture_count"],
            actual=e3_improved_count,
            requirement=f">= {e3['required_improved_fixture_count']}",
            detail=e3_improvements,
        ),
        "connector_classification_accuracy": _gate(
            e3_metrics["connector_classification_accuracy"]
            > e3_requirements[
                "connector_classification_accuracy_strictly_greater_than"
            ],
            actual=e3_metrics["connector_classification_accuracy"],
            requirement=(
                "> "
                f"{e3_requirements['connector_classification_accuracy_strictly_greater_than']}"
            ),
        ),
        "coordination_member_f1": _gate(
            e3_metrics["coordination_member_f1"]
            > e3_requirements["coordination_member_f1_strictly_greater_than"],
            actual=e3_metrics["coordination_member_f1"],
            requirement=(
                f"> {e3_requirements['coordination_member_f1_strictly_greater_than']}"
            ),
        ),
        "attachment_or_projection_improvement": _gate(
            e3_metrics["example_attachment_edge_f1"]
            > e3_downstream["example_attachment_edge_f1_baseline"]
            or e3_metrics["surface_projection_f1"]
            > e3_downstream["surface_projection_f1_baseline"]
            or e3_metrics["example_projection_f1"]
            > e3_downstream["example_projection_f1_baseline"],
            actual={
                "example_attachment_edge_f1": e3_metrics["example_attachment_edge_f1"],
                "surface_projection_f1": e3_metrics["surface_projection_f1"],
                "example_projection_f1": e3_metrics["example_projection_f1"],
            },
            requirement=e3_downstream,
        ),
    }

    fixture_011 = gold_by_id["structured-v5-mechanism-dev-v1-011"]
    prediction_011 = predicted[fixture_011["id"]]
    attachments_011 = (prediction_011["parsed_clause"] or {}).get(
        "example_attachments", []
    )
    fixture_012 = gold_by_id["structured-v5-mechanism-dev-v1-012"]
    prediction_012 = predicted[fixture_012["id"]]
    controls = [
        gold_by_id[f"structured-v5-mechanism-dev-v1-{index:03d}"]
        for index in range(13, 16)
    ]
    control_results: dict[str, Any] = {}
    for fixture in controls:
        fixture_id = fixture["id"]
        baseline_differences = _layer_difference_counts(fixture, baseline[fixture_id])
        v5_differences = _layer_difference_counts(fixture, predicted[fixture_id])
        control_results[fixture_id] = {
            "passed": all(
                v5_differences[layer] <= baseline_differences[layer]
                for layer in PRIMARY_LAYERS
            )
            and _exact_values(
                fixture, predicted[fixture_id], "example_attachment_parents"
            )
            and _exact_values(
                fixture, predicted[fixture_id], "example_attachment_edges"
            ),
            "baseline_difference_counts": baseline_differences,
            "v5_difference_counts": v5_differences,
            "attachment_parents_exact": _exact_values(
                fixture, predicted[fixture_id], "example_attachment_parents"
            ),
            "attachment_edges_exact": _exact_values(
                fixture, predicted[fixture_id], "example_attachment_edges"
            ),
        }
    g4_checks = {
        "target_011_attachment": _gate(
            len(attachments_011) == 1
            and _exact_values(fixture_011, prediction_011, "example_attachment_parents")
            and _exact_values(fixture_011, prediction_011, "example_attachment_edges"),
            actual=attachments_011,
            requirement="one exact 如 attachment and no priority parent",
        ),
        "target_012_direct_surface": _gate(
            not (prediction_012["parsed_clause"] or {}).get("example_attachments", [])
            and prediction_012["examples"] == []
            and prediction_012["items"] == ["手配", "小家电", "外设产品", "摄影摄像"],
            actual={
                "attachments": (prediction_012["parsed_clause"] or {}).get(
                    "example_attachments", []
                ),
                "items": prediction_012["items"],
                "examples": prediction_012["examples"],
            },
            requirement={
                "attachment_count": 0,
                "surface_items": ["手配", "小家电", "外设产品", "摄影摄像"],
                "examples": [],
            },
        ),
        "matched_controls_013_015": _gate(
            all(result["passed"] for result in control_results.values()),
            actual=control_results,
            requirement="no primary-layer regression and exact attachment endpoints",
        ),
    }

    e7 = gates["G5-E7-prepositional-boundary"]
    e7_results: dict[str, Any] = {}
    for fixture_id in e7["fixture_ids"]:
        fixture = gold_by_id[fixture_id]
        prediction = predicted[fixture_id]
        attachments = (prediction["parsed_clause"] or {}).get("example_attachments", [])
        first_example = (
            attachments[0]["example_spans"][0]["text"]
            if attachments and attachments[0]["example_spans"]
            else None
        )
        e7_results[fixture_id] = {
            "passed": first_example == e7["first_example_spans"][fixture_id]
            and not (first_example or "").startswith("对")
            and _exact_values(fixture, prediction, "example_attachment_parents")
            and _exact_values(fixture, prediction, "example_attachment_edges")
            and _exact_values(fixture, prediction, "example_projection"),
            "first_example": first_example,
            "expected_first_example": e7["first_example_spans"][fixture_id],
            "attachment_parents_exact": _exact_values(
                fixture, prediction, "example_attachment_parents"
            ),
            "attachment_edges_exact": _exact_values(
                fixture, prediction, "example_attachment_edges"
            ),
            "example_projection_exact": _exact_values(
                fixture, prediction, "example_projection"
            ),
        }
    g5_checks = {
        "five_exact_local_prepositional_boundaries": _gate(
            all(result["passed"] for result in e7_results.values()),
            actual=e7_results,
            requirement="all five frozen first examples and attachment projections exact",
        )
    }

    return {
        "G1-aggregate-non-regression": {
            "passed": all(check["passed"] for check in g1_checks.values()),
            "checks": g1_checks,
        },
        "G2-E2-wrapper-boundary": {
            "passed": all(check["passed"] for check in e2_checks.values()),
            "metrics": e2_metrics,
            "checks": e2_checks,
        },
        "G3-E3-region-first-connector-role": {
            "passed": all(check["passed"] for check in e3_checks.values()),
            "metrics": e3_metrics,
            "checks": e3_checks,
        },
        "G4-E6-priority-tail": {
            "passed": all(check["passed"] for check in g4_checks.values()),
            "checks": g4_checks,
        },
        "G5-E7-prepositional-boundary": {
            "passed": all(check["passed"] for check in g5_checks.values()),
            "checks": g5_checks,
        },
    }


def _legacy_exact(report: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    count = report["evaluation_scope"]["fixture_count"]
    checks = {
        "structure_validation_error_count": report["structure_validation_errors"] == 0,
        "wrapper_exact_fixture_count": report["wrappers"]["exact_fixture_count"]
        == count,
        "connector_classification_exact": report["connector_classification"]["correct"]
        == report["connector_classification"]["count"],
        "coordination_member_exact_fixture_count": report["coordination_members"][
            "exact_fixture_count"
        ]
        == count,
        "shared_scope_exact_fixture_count": report["shared_scope_edges"][
            "exact_fixture_count"
        ]
        == count,
        "attachment_parent_exact_fixture_count": report["example_attachment_parents"][
            "exact_fixture_count"
        ]
        == count,
        "attachment_edge_exact_fixture_count": report["example_attachment_edges"][
            "exact_fixture_count"
        ]
        == count,
        "surface_projection_exact_fixture_count": report["projection"]["surface_items"][
            "exact_fixture_count"
        ]
        == count,
        "example_projection_exact_fixture_count": report["projection"]["examples"][
            "exact_fixture_count"
        ]
        == count,
    }
    return all(checks.values()), checks


def _build_regression_gate(
    legacy_gold: dict[str, Any],
    legacy_raw: dict[str, Any],
    external_gold: dict[str, Any],
    external_raw: dict[str, Any],
    projection: dict[str, Any],
    tests: dict[str, Any],
) -> dict[str, Any]:
    legacy_report = evaluate_predictions(legacy_gold, legacy_raw)
    legacy_passed, legacy_checks = _legacy_exact(legacy_report)

    external_v4_raw = _load(EXTERNAL_V4_RAW_PATH)
    external_v4_report = evaluate_predictions(external_gold, external_v4_raw)
    external_v5_report = evaluate_predictions(external_gold, external_raw)
    baseline_quality = _quality_metrics(external_v4_report)
    v5_quality = _quality_metrics(external_v5_report)
    aggregate_comparisons = {
        name: {
            "baseline": baseline_quality[name],
            "v5": v5_quality[name],
            "passed": v5_quality[name] >= baseline_quality[name],
        }
        for name in baseline_quality
    }

    gold_by_id = {fixture["id"]: fixture for fixture in external_gold["fixtures"]}
    v4_by_id = _prediction_by_id(external_v4_raw)
    v5_by_id = _prediction_by_id(external_raw)
    per_fixture_comparisons: dict[str, Any] = {}
    for fixture_id, fixture in gold_by_id.items():
        baseline = _layer_difference_counts(fixture, v4_by_id[fixture_id])
        v5 = _layer_difference_counts(fixture, v5_by_id[fixture_id])
        layer_checks = {layer: v5[layer] <= baseline[layer] for layer in PRIMARY_LAYERS}
        per_fixture_comparisons[fixture_id] = {
            "passed": all(layer_checks.values()),
            "baseline_difference_counts": baseline,
            "v5_difference_counts": v5,
            "layer_checks": layer_checks,
        }

    checks = {
        "legacy_v4_development_exact": _gate(
            legacy_passed,
            actual=legacy_checks,
            requirement="20/20 exact on every structural and projection layer",
        ),
        "revealed_external_aggregate_non_regression": _gate(
            all(value["passed"] for value in aggregate_comparisons.values()),
            actual=aggregate_comparisons,
            requirement="every aggregate quality metric >= frozen v4 baseline",
        ),
        "revealed_external_per_fixture_non_regression": _gate(
            all(value["passed"] for value in per_fixture_comparisons.values()),
            actual=per_fixture_comparisons,
            requirement="every fixture and primary layer difference count <= v4",
        ),
        "projection_regression_60_of_60": _gate(
            projection["fixture_count"] == 60 and projection["exact_count"] == 60,
            actual={
                "fixture_count": projection["fixture_count"],
                "exact_count": projection["exact_count"],
            },
            requirement="60/60 exact",
        ),
        "structured_span_tests": _gate(
            tests["exit_code"] == 0,
            actual={
                "exit_code": tests["exit_code"],
                "test_file_count": tests["test_file_count"],
            },
            requirement="pytest exit code 0",
        ),
    }
    return {
        "passed": all(check["passed"] for check in checks.values()),
        "checks": checks,
        "legacy_metrics": _metric_snapshot(legacy_report),
        "revealed_external_v4_metrics": _metric_snapshot(external_v4_report),
        "revealed_external_v5_metrics": _metric_snapshot(external_v5_report),
    }


def _render_findings(report: dict[str, Any]) -> str:
    metrics = report["development_metrics"]
    lines = [
        "# Frozen v5 development and regression gates",
        "",
        "## Outcome",
        "",
        f"- Overall gate passed: `{str(report['gate_passed']).lower()}`.",
        "- This is revealed development evidence, not a generalization claim.",
        "- Model and network call counts are both zero.",
        "",
        "## Development metrics",
        "",
        "| Layer | Metric |",
        "|---|---:|",
        f"| Wrapper span F1 | {metrics['wrapper_span_f1']:.4f} |",
        f"| Connector accuracy | {metrics['connector_classification_accuracy']:.4f} |",
        f"| Coordination member F1 | {metrics['coordination_member_f1']:.4f} |",
        f"| Shared-scope edge F1 | {metrics['shared_scope_edge_f1']:.4f} |",
        f"| Attachment edge F1 | {metrics['example_attachment_edge_f1']:.4f} |",
        f"| Surface projection F1 | {metrics['surface_projection_f1']:.4f} |",
        f"| Example projection F1 | {metrics['example_projection_f1']:.4f} |",
        "",
        "## Frozen gates",
        "",
    ]
    for name, result in report["gates"].items():
        lines.append(f"- `{name}`: {'passed' if result['passed'] else 'failed'}.")
    lines.extend(
        [
            "",
            "## Decision",
            "",
            (
                "The frozen development and regression gates passed. V5 remains frozen; the next allowed parser step is a fresh corpus-external blind holdout. Canonicalizer work remains locked until that holdout passes."
                if report["gate_passed"]
                else "At least one frozen gate failed. V5 remains frozen, canonicalizer work stays locked, and any new parser attempt requires a new preregistration before source changes."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _receipt(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "receipt_version": "unified-jd-structured-span-v5-development-regression-receipt-v1",
        "evaluated_at": datetime.now(UTC).isoformat(),
        "status": "one_time_frozen_v5_development_and_regression_evaluated",
        "inputs": {
            "source_freeze": {
                "path": _relative(SOURCE_FREEZE_PATH),
                "sha256": _sha256(SOURCE_FREEZE_PATH),
            },
            "v5_parser": {"path": _relative(V5_PATH), "sha256": _sha256(V5_PATH)},
            "preregistration": {
                "path": _relative(PREREGISTRATION_PATH),
                "sha256": _sha256(PREREGISTRATION_PATH),
            },
        },
        "outputs": {
            "development_raw": {
                "path": _relative(DEVELOPMENT_RAW_PATH),
                "sha256": _sha256(DEVELOPMENT_RAW_PATH),
            },
            "regression_raw": {
                "path": _relative(REGRESSION_RAW_PATH),
                "sha256": _sha256(REGRESSION_RAW_PATH),
            },
            "report": {"path": _relative(REPORT_PATH), "sha256": _sha256(REPORT_PATH)},
            "findings": {
                "path": _relative(FINDINGS_PATH),
                "sha256": _sha256(FINDINGS_PATH),
            },
        },
        "v5_development_run_count": 1,
        "v5_regression_run_count": 1,
        "gate_passed": report["gate_passed"],
        "failed_gates": [
            name for name, result in report["gates"].items() if not result["passed"]
        ],
        "canonicalizer_allowed": False,
        "canonicalizer_lock_reason": (
            "A fresh blind corpus-external holdout has not passed."
            if report["gate_passed"]
            else "The frozen v5 development or regression gate failed."
        ),
        "model_call_count": 0,
        "network_call_count": 0,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the frozen v5 development and regression gates exactly once"
    )
    parser.add_argument(
        "--preflight",
        action="store_true",
        help="validate hashes and unused output paths without importing or running v5",
    )
    return parser.parse_args()


def main() -> int:
    arguments = _parse_args()
    preregistration, labels = _validate_frozen_inputs()
    if arguments.preflight:
        print(
            "preflight passed: frozen hashes and unused output paths verified; "
            "v5 was not imported or executed"
        )
        return 0

    development_gold = _normalize_mechanism_gold(labels)
    development_raw = _run_v5_predictions(development_gold, "mechanism-development")
    _write_new(DEVELOPMENT_RAW_PATH, _serialized(development_raw))
    development_report = evaluate_predictions(development_gold, development_raw)
    development_metrics = _metric_snapshot(development_report)

    legacy_gold = _load(LEGACY_GOLD_PATH)
    legacy_raw = _run_v5_predictions(legacy_gold, "legacy-development-regression")
    external_dataset = _load(EXTERNAL_DEVELOPMENT_PATH)
    external_gold = _normalize_external_gold(external_dataset)
    external_raw = _run_v5_predictions(external_gold, "revealed-external-regression")
    projection = _run_projection_regression()
    tests = _run_structured_span_tests()
    regression_raw = {
        "raw_version": "unified-jd-structured-span-v5-regression-raw-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "parser_path": _relative(V5_PATH),
        "parser_sha256": _sha256(V5_PATH),
        "model_call_count": 0,
        "network_call_count": 0,
        "legacy_development": legacy_raw,
        "revealed_external": external_raw,
        "projection_60": projection,
        "structured_span_tests": tests,
    }
    _write_new(REGRESSION_RAW_PATH, _serialized(regression_raw))

    development_gates = _build_development_gates(
        preregistration,
        development_gold,
        development_raw,
        development_report,
    )
    regression_gate = _build_regression_gate(
        legacy_gold,
        legacy_raw,
        external_gold,
        external_raw,
        projection,
        tests,
    )
    anchoring_errors = _anchoring_errors([development_raw, legacy_raw, external_raw])
    g0_checks = {
        "development_structure_validation": _gate(
            development_metrics["structure_validation_error_count"] == 0,
            actual=development_metrics["structure_validation_error_count"],
            requirement="== 0",
        ),
        "all_regression_predictions_parse": _gate(
            all(
                record["error"] is None
                for raw in (legacy_raw, external_raw)
                for record in raw["records"]
            ),
            actual=sum(
                record["error"] is not None
                for raw in (legacy_raw, external_raw)
                for record in raw["records"]
            ),
            requirement="== 0",
        ),
        "anchored_outputs": _gate(
            not anchoring_errors,
            actual=len(anchoring_errors),
            requirement="== 0",
            detail=anchoring_errors,
        ),
        "frozen_v4_sha256": _gate(
            _sha256(V4_PATH)
            == "e09e056cab75e651937391ce5410e6df7c94477c85565abb1425bbe85cfcb094",
            actual=_sha256(V4_PATH),
            requirement=(
                "e09e056cab75e651937391ce5410e6df7c94477c85565abb1425bbe85cfcb094"
            ),
        ),
        "zero_model_and_network_calls": _gate(
            all(
                raw["model_call_count"] == raw["network_call_count"] == 0
                for raw in (development_raw, legacy_raw, external_raw)
            ),
            actual={"model_call_count": 0, "network_call_count": 0},
            requirement={"model_call_count": 0, "network_call_count": 0},
        ),
    }
    all_gates = {
        "G0-validity": {
            "passed": all(check["passed"] for check in g0_checks.values()),
            "checks": g0_checks,
        },
        **development_gates,
        "G6-regression": regression_gate,
    }
    report = {
        "report_version": "unified-jd-structured-span-v5-development-regression-report-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "frozen_one_time_development_and_regression_result",
        "scope": {
            "development_data_status": "revealed_not_holdout",
            "generalization_claim": False,
            "threshold_changes_allowed": False,
            "v5_source_changes_allowed_after_result": False,
            "model_call_count": 0,
            "network_call_count": 0,
        },
        "inputs": {
            "preregistration": {
                "path": _relative(PREREGISTRATION_PATH),
                "sha256": _sha256(PREREGISTRATION_PATH),
            },
            "source_freeze": {
                "path": _relative(SOURCE_FREEZE_PATH),
                "sha256": _sha256(SOURCE_FREEZE_PATH),
            },
            "development_raw": {
                "path": _relative(DEVELOPMENT_RAW_PATH),
                "sha256": _sha256(DEVELOPMENT_RAW_PATH),
            },
            "regression_raw": {
                "path": _relative(REGRESSION_RAW_PATH),
                "sha256": _sha256(REGRESSION_RAW_PATH),
            },
        },
        "development_metrics": development_metrics,
        "development_full_layer_report": {
            key: development_report[key]
            for key in (
                "wrappers",
                "connector_classification",
                "coordination_members",
                "shared_scope_edges",
                "example_attachment_parents",
                "example_attachment_edges",
                "projection",
                "records",
            )
        },
        "gates": all_gates,
        "gate_passed": all(result["passed"] for result in all_gates.values()),
        "canonicalizer_allowed": False,
    }
    _write_new(REPORT_PATH, _serialized(report))
    _write_new(FINDINGS_PATH, _render_findings(report))
    _write_new(RECEIPT_PATH, _serialized(_receipt(report)))
    print(
        json.dumps(
            {
                "development_metrics": development_metrics,
                "gates": {name: result["passed"] for name, result in all_gates.items()},
                "gate_passed": report["gate_passed"],
                "canonicalizer_allowed": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
