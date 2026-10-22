from __future__ import annotations

import argparse
import copy
import hashlib
import json
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts import evaluate_unified_structured_span_v5_gates as v5_gate
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
V6_PREREGISTRATION_PATH = (
    ROOT / f"datasets/unified_jd_structured_span_v6_preregistration_v1_{DATE}.json"
)
V6_PREREGISTRATION_FREEZE_PATH = (
    ROOT
    / f"datasets/unified_jd_structured_span_v6_preregistration_freeze_v1_{DATE}.json"
)
V6_SOURCE_FREEZE_PATH = (
    ROOT / f"datasets/unified_jd_structured_span_v6_source_freeze_v1_{DATE}.json"
)
V6_PATH = ROOT / "src/domain/unified_jd_structured_spans_v6.py"
V6_TEST_PATH = ROOT / "tests/test_unified_jd_structured_spans_v6.py"
V6_EVALUATOR_PATH = Path(__file__).resolve()
V4_PATH = ROOT / "src/domain/unified_jd_structured_spans_v4.py"
V5_PATH = ROOT / "src/domain/unified_jd_structured_spans_v5.py"
V5_PREREGISTRATION_PATH = (
    ROOT / "datasets/unified_jd_structured_span_v5_preregistration_v1_2026-09-04.json"
)
LABELS_PATH = (
    ROOT
    / "datasets/unified_jd_structured_span_v5_mechanism_development_labels_v1_2026-09-04.json"
)
LEGACY_GOLD_PATH = (
    ROOT / "datasets/unified_jd_structured_span_v4_development_gold_v1_2026-09-04.json"
)
EXTERNAL_DEVELOPMENT_PATH = (
    ROOT
    / "datasets/unified_jd_structured_span_v4_corpus_external_revealed_development_v1_2026-09-04.json"
)
V5_MECHANISM_RAW_PATH = (
    ROOT
    / f"artifacts/evaluation/unified-jd-structured-span-v5-mechanism-development-v5-raw-v1-{DATE}.json"
)
CLASSIFICATION_PATH = (
    ROOT
    / f"artifacts/evaluation/unified-jd-structured-span-v5-frozen-regression-classification-v1-{DATE}.json"
)
PROJECTION_FIXTURE_PATHS = (
    ROOT / "datasets/unified_jd_canonical_items_contract_v1.json",
    ROOT / "datasets/unified_jd_surface_holdout_labels_v1_2026-09-04.json",
    ROOT / "datasets/unified_jd_surface_holdout_labels_v2_2026-09-04.json",
)
DEVELOPMENT_RAW_PATH = (
    ROOT
    / f"artifacts/evaluation/unified-jd-structured-span-v6-mechanism-development-raw-v1-{DATE}.json"
)
REGRESSION_RAW_PATH = (
    ROOT
    / f"artifacts/evaluation/unified-jd-structured-span-v6-regression-raw-v1-{DATE}.json"
)
REPORT_PATH = (
    ROOT
    / f"artifacts/evaluation/unified-jd-structured-span-v6-development-regression-report-v1-{DATE}.json"
)
FINDINGS_PATH = (
    ROOT
    / f"artifacts/evaluation/unified-jd-structured-span-v6-development-regression-findings-v1-{DATE}.md"
)
RECEIPT_PATH = (
    ROOT
    / f"artifacts/evaluation/unified-jd-structured-span-v6-development-regression-receipt-v1-{DATE}.json"
)
OUTPUT_PATHS = (
    DEVELOPMENT_RAW_PATH,
    REGRESSION_RAW_PATH,
    REPORT_PATH,
    FINDINGS_PATH,
    RECEIPT_PATH,
)
PRIMARY_LAYERS = v5_gate.PRIMARY_LAYERS
EXACT_LAYERS = (
    "wrappers",
    "connector_labels",
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


def _validate_reference(reference: dict[str, Any]) -> None:
    path = ROOT / reference["path"]
    actual = _sha256(path)
    if actual != reference["sha256"]:
        raise ValueError(
            f"frozen hash mismatch for {reference['path']}: "
            f"expected {reference['sha256']}, got {actual}"
        )


def _validate_frozen_inputs() -> tuple[dict[str, Any], dict[str, Any]]:
    preregistration = _load(V6_PREREGISTRATION_PATH)
    preregistration_freeze = _load(V6_PREREGISTRATION_FREEZE_PATH)
    source_freeze = _load(V6_SOURCE_FREEZE_PATH)
    _validate_reference(preregistration_freeze["artifacts"]["preregistration"])
    for reference in preregistration["inputs"].values():
        _validate_reference(reference)
    for reference in source_freeze["artifacts"].values():
        _validate_reference(reference)

    if preregistration["evaluation_protocol"]["all_criteria_conjunctive"] is not True:
        raise ValueError("v6 gates are no longer conjunctive")
    if preregistration["scope"]["model_calls_allowed"] is not False:
        raise ValueError("v6 preregistration unexpectedly permits model calls")
    if preregistration["scope"]["network_calls_allowed"] is not False:
        raise ValueError("v6 preregistration unexpectedly permits network calls")
    if source_freeze["status"] != "v6_source_frozen_before_one_time_gates":
        raise ValueError("v6 source freeze status is invalid")
    existing = [_relative(path) for path in OUTPUT_PATHS if path.exists()]
    if existing:
        raise FileExistsError(f"one-time v6 output already exists: {existing}")
    return preregistration, _load(LABELS_PATH)


def _run_v6_predictions(gold: dict[str, Any], scope: str) -> dict[str, Any]:
    from src.domain.unified_jd_structured_spans_v6 import (
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
        except Exception as error:  # noqa: BLE001 - errors are frozen gate results
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
        "raw_version": f"unified-jd-structured-span-v6-{scope}-raw-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": scope,
        "parser_version": STRUCTURED_SPAN_PARSER_VERSION,
        "parser_path": _relative(V6_PATH),
        "parser_sha256": _sha256(V6_PATH),
        "model_call_count": 0,
        "network_call_count": 0,
        "records": records,
    }


def _run_projection_regression() -> dict[str, Any]:
    from src.domain.unified_jd_structured_spans_v6 import extract_surface_items

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
            exact = Counter(fixture["surface_items"]) == Counter(
                actual_items
            ) and Counter(fixture["examples"] or []) == Counter(actual_examples)
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
                    "exact": exact,
                    "error": error,
                }
            )
    return {
        "fixture_count": len(records),
        "exact_count": sum(record["exact"] for record in records),
        "records": records,
    }


def _adjudicated_legacy_gold(
    preregistration: dict[str, Any], legacy_gold: dict[str, Any]
) -> dict[str, Any]:
    result = copy.deepcopy(legacy_gold)
    adjudication = preregistration["evaluation_adjudication"]
    fixture = next(
        item for item in result["fixtures"] if item["id"] == adjudication["fixture_id"]
    )
    wrapper = fixture["wrappers"][1]
    if wrapper["marker_span"] != adjudication["frozen_value"]:
        raise ValueError("legacy gold no longer matches the preregistered R7 value")
    wrapper["marker_span"] = adjudication["source_corrected_value"]
    return result


def _prediction_layer(value: dict[str, Any], layer: str) -> Counter[Any]:
    if value["parsed_clause"] is None:
        return Counter({("parse_error",): 1})
    if layer == "wrappers":
        return Counter(_wrapper_keys(value, gold=False))
    if layer == "connector_labels":
        return Counter(_connector_role_map(value, gold=False).items())
    if layer == "coordination_members":
        return Counter(_coordination_member_keys(value, gold=False))
    if layer == "shared_scope_edges":
        return Counter(_scope_edge_keys(value, gold=False))
    if layer == "example_attachment_parents":
        return Counter(_attachment_parent_keys(value, gold=False))
    if layer == "example_attachment_edges":
        return Counter(_attachment_example_edge_keys(value, gold=False))
    if layer == "surface_projection":
        return Counter(value["items"])
    if layer == "example_projection":
        return Counter(value["examples"])
    raise ValueError(f"unsupported prediction layer: {layer}")


def _g7_mechanism_preservation(
    development_raw: dict[str, Any], reference_raw: dict[str, Any]
) -> dict[str, Any]:
    actual = v5_gate._prediction_by_id(development_raw)
    reference = v5_gate._prediction_by_id(reference_raw)
    fixtures: dict[str, Any] = {}
    for fixture_id in sorted(reference):
        layer_checks = {
            layer: _prediction_layer(actual[fixture_id], layer)
            == _prediction_layer(reference[fixture_id], layer)
            for layer in EXACT_LAYERS
        }
        fixtures[fixture_id] = {
            "passed": all(layer_checks.values()),
            "layer_checks": layer_checks,
        }
    exact_count = sum(value["passed"] for value in fixtures.values())
    return {
        "passed": len(fixtures) == 20 and exact_count == 20,
        "actual": {"fixture_count": len(fixtures), "exact_fixture_count": exact_count},
        "requirement": {"fixture_count": 20, "exact_fixture_count": 20},
        "fixtures": fixtures,
    }


def _projection_by_id(projection: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {record["id"]: record for record in projection["records"]}


def _g8_classified_resolution(
    preregistration: dict[str, Any],
    legacy_gold: dict[str, Any],
    legacy_raw: dict[str, Any],
    external_gold: dict[str, Any],
    external_raw: dict[str, Any],
    projection: dict[str, Any],
) -> dict[str, Any]:
    legacy_expected = {fixture["id"]: fixture for fixture in legacy_gold["fixtures"]}
    legacy_actual = v5_gate._prediction_by_id(legacy_raw)
    external_expected = {
        fixture["id"]: fixture for fixture in external_gold["fixtures"]
    }
    external_actual = v5_gate._prediction_by_id(external_raw)
    projection_actual = _projection_by_id(projection)
    cohorts: dict[str, Any] = {}
    total_resolved = 0
    total_observations = 0
    for name, specification in preregistration["acceptance_gates"][
        "G8-classified-regression-resolution"
    ]["cohorts"].items():
        cases: dict[str, bool] = {}
        for case in specification["cases"]:
            fixture_id = case["id"]
            if case["cohort"] == "legacy-20":
                resolved = (
                    v5_gate._difference_count(
                        legacy_expected[fixture_id],
                        legacy_actual[fixture_id],
                        PRIMARY_LAYERS,
                    )
                    == 0
                )
            elif case["cohort"] == "revealed-external-20":
                resolved = (
                    v5_gate._difference_count(
                        external_expected[fixture_id],
                        external_actual[fixture_id],
                        PRIMARY_LAYERS,
                    )
                    == 0
                )
            else:
                resolved = bool(projection_actual[fixture_id]["exact"])
            cases[fixture_id] = resolved
        resolved_count = sum(cases.values())
        observation_count = specification["observation_count"]
        cohorts[name] = {
            "passed": len(cases) == observation_count
            and resolved_count == specification["required_resolved_count"],
            "observation_count": len(cases),
            "resolved_count": resolved_count,
            "cases": cases,
        }
        total_resolved += resolved_count
        total_observations += len(cases)
    return {
        "passed": total_observations == 31
        and total_resolved == 31
        and all(value["passed"] for value in cohorts.values()),
        "actual": {
            "observation_count": total_observations,
            "resolved_count": total_resolved,
        },
        "requirement": {"observation_count": 31, "resolved_count": 31},
        "cohorts": cohorts,
    }


def _g9_no_new_regression(
    regression_gate: dict[str, Any], external_raw: dict[str, Any]
) -> dict[str, Any]:
    external_gold = v5_gate._normalize_external_gold(_load(EXTERNAL_DEVELOPMENT_PATH))
    gold = {fixture["id"]: fixture for fixture in external_gold["fixtures"]}
    actual = v5_gate._prediction_by_id(external_raw)
    wrapper_difference = v5_gate._difference_count(
        gold["structured-corpus-external-v1-006"],
        actual["structured-corpus-external-v1-006"],
        ("wrappers",),
    )
    checks = {
        **regression_gate["checks"],
        "known_open_list_wrapper_regression_zero": v5_gate._gate(
            wrapper_difference == 0,
            actual=wrapper_difference,
            requirement="== 0",
        ),
    }
    return {
        "passed": all(check["passed"] for check in checks.values()),
        "checks": checks,
        "legacy_metrics": regression_gate["legacy_metrics"],
        "revealed_external_v4_metrics": regression_gate["revealed_external_v4_metrics"],
        "revealed_external_v6_metrics": regression_gate["revealed_external_v5_metrics"],
    }


def _render_findings(report: dict[str, Any]) -> str:
    metrics = report["development_metrics"]
    lines = [
        "# Frozen v6 development and regression gates",
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
    lines.extend(
        f"- `{name}`: {'passed' if result['passed'] else 'failed'}."
        for name, result in report["gates"].items()
    )
    lines.extend(
        [
            "",
            "## Decision",
            "",
            (
                "Every frozen development and regression gate passed. V6 remains "
                "frozen; canonicalizer work stays locked until a separately frozen "
                "fresh external blind holdout also passes."
                if report["gate_passed"]
                else "At least one frozen gate failed. V6 remains frozen, v4 stays "
                "the production reference, and any new parser attempt requires a new "
                "preregistration before source changes."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _receipt(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "receipt_version": "unified-jd-structured-span-v6-development-regression-receipt-v1",
        "evaluated_at": datetime.now(UTC).isoformat(),
        "status": "one_time_frozen_v6_development_and_regression_evaluated",
        "inputs": {
            "source_freeze": {
                "path": _relative(V6_SOURCE_FREEZE_PATH),
                "sha256": _sha256(V6_SOURCE_FREEZE_PATH),
            },
            "v6_parser": {"path": _relative(V6_PATH), "sha256": _sha256(V6_PATH)},
            "preregistration": {
                "path": _relative(V6_PREREGISTRATION_PATH),
                "sha256": _sha256(V6_PREREGISTRATION_PATH),
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
        "gate_passed": report["gate_passed"],
        "canonicalizer_allowed": False,
        "model_call_count": 0,
        "network_call_count": 0,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the frozen v6 development and regression gates exactly once"
    )
    parser.add_argument(
        "--preflight",
        action="store_true",
        help="validate frozen hashes and unused outputs without importing v6",
    )
    return parser.parse_args()


def main() -> int:
    arguments = _parse_args()
    preregistration, labels = _validate_frozen_inputs()
    if arguments.preflight:
        print(
            "preflight passed: frozen hashes and unused output paths verified; "
            "v6 was not imported or executed"
        )
        return 0

    development_gold = v5_gate._normalize_mechanism_gold(labels)
    development_raw = _run_v6_predictions(development_gold, "mechanism-development")
    _write_new(DEVELOPMENT_RAW_PATH, _serialized(development_raw))

    legacy_gold = _adjudicated_legacy_gold(preregistration, _load(LEGACY_GOLD_PATH))
    legacy_raw = _run_v6_predictions(legacy_gold, "legacy-development-regression")
    external_gold = v5_gate._normalize_external_gold(_load(EXTERNAL_DEVELOPMENT_PATH))
    external_raw = _run_v6_predictions(external_gold, "revealed-external-regression")
    projection = _run_projection_regression()
    tests = v5_gate._run_structured_span_tests()
    regression_raw = {
        "raw_version": "unified-jd-structured-span-v6-regression-raw-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "parser_path": _relative(V6_PATH),
        "parser_sha256": _sha256(V6_PATH),
        "model_call_count": 0,
        "network_call_count": 0,
        "legacy_development": legacy_raw,
        "revealed_external": external_raw,
        "projection_60": projection,
        "structured_span_tests": tests,
    }
    _write_new(REGRESSION_RAW_PATH, _serialized(regression_raw))

    development_report = evaluate_predictions(development_gold, development_raw)
    development_metrics = v5_gate._metric_snapshot(development_report)
    original_preregistration = _load(V5_PREREGISTRATION_PATH)
    development_gates = v5_gate._build_development_gates(
        original_preregistration,
        development_gold,
        development_raw,
        development_report,
    )
    regression_gate = v5_gate._build_regression_gate(
        legacy_gold,
        legacy_raw,
        external_gold,
        external_raw,
        projection,
        tests,
    )
    anchoring_errors = v5_gate._anchoring_errors(
        [development_raw, legacy_raw, external_raw]
    )
    g0_checks = {
        "development_structure_validation": v5_gate._gate(
            development_metrics["structure_validation_error_count"] == 0,
            actual=development_metrics["structure_validation_error_count"],
            requirement="== 0",
        ),
        "all_regression_predictions_parse": v5_gate._gate(
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
        "anchored_outputs": v5_gate._gate(
            not anchoring_errors,
            actual=len(anchoring_errors),
            requirement="== 0",
            detail=anchoring_errors,
        ),
        "frozen_v4_sha256": v5_gate._gate(
            _sha256(V4_PATH)
            == "e09e056cab75e651937391ce5410e6df7c94477c85565abb1425bbe85cfcb094",
            actual=_sha256(V4_PATH),
            requirement=(
                "e09e056cab75e651937391ce5410e6df7c94477c85565abb1425bbe85cfcb094"
            ),
        ),
        "frozen_v5_sha256": v5_gate._gate(
            _sha256(V5_PATH)
            == "8abdb1df73af8731caf565d0f0c74ad824302bf99cdae2b1c6a4e2e13ad541da",
            actual=_sha256(V5_PATH),
            requirement=(
                "8abdb1df73af8731caf565d0f0c74ad824302bf99cdae2b1c6a4e2e13ad541da"
            ),
        ),
        "frozen_v6_sha256": v5_gate._gate(
            _sha256(V6_PATH)
            == _load(V6_SOURCE_FREEZE_PATH)["artifacts"]["v6_parser"]["sha256"],
            actual=_sha256(V6_PATH),
            requirement=_load(V6_SOURCE_FREEZE_PATH)["artifacts"]["v6_parser"][
                "sha256"
            ],
        ),
        "zero_model_and_network_calls": v5_gate._gate(
            all(
                raw["model_call_count"] == raw["network_call_count"] == 0
                for raw in (development_raw, legacy_raw, external_raw)
            ),
            actual={"model_call_count": 0, "network_call_count": 0},
            requirement={"model_call_count": 0, "network_call_count": 0},
        ),
    }
    g7 = _g7_mechanism_preservation(development_raw, _load(V5_MECHANISM_RAW_PATH))
    g8 = _g8_classified_resolution(
        preregistration,
        legacy_gold,
        legacy_raw,
        external_gold,
        external_raw,
        projection,
    )
    g9 = _g9_no_new_regression(regression_gate, external_raw)
    all_gates = {
        "G0-validity": {
            "passed": all(check["passed"] for check in g0_checks.values()),
            "checks": g0_checks,
        },
        **development_gates,
        "G6-regression": regression_gate,
        "G7-v5-mechanism-preservation": g7,
        "G8-classified-regression-resolution": g8,
        "G9-no-new-regression": g9,
    }
    report = {
        "report_version": "unified-jd-structured-span-v6-development-regression-report-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "frozen_one_time_development_and_regression_result",
        "scope": {
            "development_data_status": "revealed_not_holdout",
            "generalization_claim": False,
            "threshold_changes_allowed": False,
            "v6_source_changes_allowed_after_result": False,
            "canonicalizer_allowed": False,
            "model_call_count": 0,
            "network_call_count": 0,
        },
        "inputs": {
            "preregistration": {
                "path": _relative(V6_PREREGISTRATION_PATH),
                "sha256": _sha256(V6_PREREGISTRATION_PATH),
            },
            "source_freeze": {
                "path": _relative(V6_SOURCE_FREEZE_PATH),
                "sha256": _sha256(V6_SOURCE_FREEZE_PATH),
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
