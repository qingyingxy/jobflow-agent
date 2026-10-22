from __future__ import annotations

import argparse
import ast
import hashlib
import json
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts import evaluate_unified_structured_span_v5_gates as v5_gate
from scripts import evaluate_unified_structured_span_v6_gates as v6_gate
from scripts import unified_structured_span_v6_residual_oracle_common as e9_common
from scripts.evaluate_unified_structured_span_v4_development import evaluate_predictions

ROOT = Path(__file__).resolve().parents[1]
DATE = "2026-09-05"
PREREGISTRATION_PATH = (
    ROOT / f"datasets/unified_jd_structured_span_v7_preregistration_v1_{DATE}.json"
)
PREREGISTRATION_FREEZE_PATH = (
    ROOT
    / f"datasets/unified_jd_structured_span_v7_preregistration_freeze_v1_{DATE}.json"
)
SOURCE_FREEZE_PATH = (
    ROOT / f"datasets/unified_jd_structured_span_v7_source_freeze_v1_{DATE}.json"
)
V7_PATH = ROOT / "src/domain/unified_jd_structured_spans_v7.py"
V7_TEST_PATH = ROOT / "tests/test_unified_jd_structured_spans_v7.py"
EVALUATOR_PATH = Path(__file__).resolve()
V4_PATH = ROOT / "src/domain/unified_jd_structured_spans_v4.py"
V5_PATH = ROOT / "src/domain/unified_jd_structured_spans_v5.py"
V6_PATH = ROOT / "src/domain/unified_jd_structured_spans_v6.py"
V5_PREREGISTRATION_PATH = (
    ROOT / "datasets/unified_jd_structured_span_v5_preregistration_v1_2026-09-04.json"
)
V6_PREREGISTRATION_PATH = (
    ROOT / f"datasets/unified_jd_structured_span_v6_preregistration_v1_{DATE}.json"
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
V6_REGRESSION_RAW_PATH = (
    ROOT / f"artifacts/evaluation/unified-jd-structured-span-v6-regression-raw-v1-{DATE}.json"
)
V4_LEGACY_RAW_PATH = (
    ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-development-v4-raw-v1-2026-09-04.json"
)
V4_EXTERNAL_RAW_PATH = (
    ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-corpus-external-raw-v1-2026-09-04.json"
)
E9_RAW_PATH = (
    ROOT
    / f"artifacts/evaluation/unified-jd-structured-span-v6-e9-region-versus-node-family-merge-oracle-raw-v1-{DATE}.json"
)
E9_PREREGISTRATION_PATH = (
    ROOT
    / f"datasets/unified_jd_structured_span_v6_residual_oracles_preregistration_v1_{DATE}.json"
)
PROJECTION_FIXTURE_PATHS = v5_gate.PROJECTION_FIXTURE_PATHS
DEVELOPMENT_RAW_PATH = (
    ROOT
    / f"artifacts/evaluation/unified-jd-structured-span-v7-mechanism-development-raw-v1-{DATE}.json"
)
REGRESSION_RAW_PATH = (
    ROOT
    / f"artifacts/evaluation/unified-jd-structured-span-v7-regression-raw-v1-{DATE}.json"
)
REPORT_PATH = (
    ROOT
    / f"artifacts/evaluation/unified-jd-structured-span-v7-development-regression-report-v1-{DATE}.json"
)
FINDINGS_PATH = (
    ROOT
    / f"artifacts/evaluation/unified-jd-structured-span-v7-development-regression-findings-v1-{DATE}.md"
)
RECEIPT_PATH = (
    ROOT
    / f"artifacts/evaluation/unified-jd-structured-span-v7-development-regression-receipt-v1-{DATE}.json"
)
OUTPUT_PATHS = (
    DEVELOPMENT_RAW_PATH,
    REGRESSION_RAW_PATH,
    REPORT_PATH,
    FINDINGS_PATH,
    RECEIPT_PATH,
)
EXACT_FAMILIES = (
    "wrappers",
    "connector_labels",
    "coordination_members",
    "shared_scope_edges",
    "example_attachment_parents",
    "example_attachment_edges",
    "item_candidate_spans",
    "surface_projection",
    "example_projection",
)
FROZEN_PARSER_HASHES = {
    V4_PATH: "e09e056cab75e651937391ce5410e6df7c94477c85565abb1425bbe85cfcb094",
    V5_PATH: "8abdb1df73af8731caf565d0f0c74ad824302bf99cdae2b1c6a4e2e13ad541da",
    V6_PATH: "960d0d49f1c0b6b9fece8645ca5edc0a5874cf9ffb250e2f6c780cfcde11ccfd",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_sha256(value: Any) -> str:
    serialized = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _serialized(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


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


def _validate_preregistration() -> dict[str, Any]:
    preregistration = _load(PREREGISTRATION_PATH)
    freeze = _load(PREREGISTRATION_FREEZE_PATH)
    _validate_reference(freeze["artifacts"]["preregistration"])
    for reference in preregistration["inputs"].values():
        _validate_reference(reference)
    for path, expected in FROZEN_PARSER_HASHES.items():
        if _sha256(path) != expected:
            raise ValueError(f"frozen parser changed: {_relative(path)}")
    protocol = preregistration["evaluation_protocol"]
    if protocol["all_criteria_conjunctive"] is not True:
        raise ValueError("v7 criteria are no longer conjunctive")
    if protocol["source_freeze_before_any_v7_fixture_execution"] is not True:
        raise ValueError("v7 source-freeze requirement changed")
    if preregistration["scope"]["model_calls_allowed"] is not False:
        raise ValueError("v7 unexpectedly permits model calls")
    if preregistration["scope"]["network_calls_allowed"] is not False:
        raise ValueError("v7 unexpectedly permits network calls")
    original = _load(V5_PREREGISTRATION_PATH)["development_acceptance_gates"]
    expected = preregistration["acceptance_gates"]["G1-original-v5-G0-G6-unchanged"][
        "source"
    ]["canonical_sha256"]
    if _json_sha256(original) != expected:
        raise ValueError("original v5 G0-G6 gate contract changed")
    return preregistration


def _validate_unused_outputs() -> None:
    existing = [_relative(path) for path in OUTPUT_PATHS if path.exists()]
    if existing:
        raise FileExistsError(f"one-time v7 output already exists: {existing}")


def _freeze_source() -> dict[str, Any]:
    preregistration = _validate_preregistration()
    _validate_unused_outputs()
    if SOURCE_FREEZE_PATH.exists():
        raise FileExistsError(f"source freeze already exists: {_relative(SOURCE_FREEZE_PATH)}")
    artifacts = {
        "v7_parser": {"path": _relative(V7_PATH), "sha256": _sha256(V7_PATH)},
        "v7_synthetic_tests": {
            "path": _relative(V7_TEST_PATH),
            "sha256": _sha256(V7_TEST_PATH),
        },
        "v7_one_time_evaluator": {
            "path": _relative(EVALUATOR_PATH),
            "sha256": _sha256(EVALUATOR_PATH),
        },
        "v7_preregistration": {
            "path": _relative(PREREGISTRATION_PATH),
            "sha256": _sha256(PREREGISTRATION_PATH),
        },
    }
    freeze = {
        "freeze_version": "unified-jd-structured-span-v7-source-freeze-v1",
        "frozen_at": datetime.now(UTC).isoformat(),
        "status": "v7_source_tests_evaluator_frozen_before_one_time_gates",
        "preregistration_version": preregistration["preregistration_version"],
        "artifacts": artifacts,
        "checks": {
            "development_run_count_before_freeze": 0,
            "regression_run_count_before_freeze": 0,
            "model_call_count": 0,
            "network_call_count": 0,
            "canonicalizer_allowed": False,
        },
        "immutability": (
            "Any parser, test, evaluator, signal, veto, precedence, threshold, or "
            "input change requires a new preregistration before another execution."
        ),
    }
    _write_new(SOURCE_FREEZE_PATH, _serialized(freeze))
    return freeze


def _validate_source_freeze() -> dict[str, Any]:
    freeze = _load(SOURCE_FREEZE_PATH)
    if freeze["status"] != "v7_source_tests_evaluator_frozen_before_one_time_gates":
        raise ValueError("v7 source freeze status is invalid")
    for reference in freeze["artifacts"].values():
        _validate_reference(reference)
    return freeze


def _run_predictions(gold: dict[str, Any], scope: str) -> dict[str, Any]:
    from src.domain.unified_jd_structured_spans_v7 import (
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
                    "selector_trace": [
                        value
                        for value in extraction.rule_ids
                        if value.startswith("v7.selector:")
                    ],
                    "parsed_clause": asdict(extraction.parsed_clause),
                }
            )
        except Exception as error:  # noqa: BLE001 - frozen gate result
            records.append(
                {
                    "id": fixture["id"],
                    "category": fixture["category"],
                    "source_text": fixture["source_text"],
                    "error": f"{type(error).__name__}: {error}",
                    "items": [],
                    "examples": [],
                    "rule_ids": [],
                    "selector_trace": [],
                    "parsed_clause": None,
                }
            )
    return {
        "raw_version": f"unified-jd-structured-span-v7-{scope}-raw-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": scope,
        "parser_version": STRUCTURED_SPAN_PARSER_VERSION,
        "parser_path": _relative(V7_PATH),
        "parser_sha256": _sha256(V7_PATH),
        "model_call_count": 0,
        "network_call_count": 0,
        "records": records,
    }


def _run_projection_regression() -> dict[str, Any]:
    from src.domain.unified_jd_structured_spans_v7 import extract_surface_items

    records: list[dict[str, Any]] = []
    for path in PROJECTION_FIXTURE_PATHS:
        for fixture in _load(path)["fixtures"]:
            try:
                extraction = extract_surface_items(
                    fixture["source_text"], fixture["category"]
                )
                actual_items = list(extraction.items)
                actual_examples = list(extraction.examples)
                rule_ids = list(extraction.rule_ids)
                error = None
            except Exception as caught:  # noqa: BLE001 - frozen gate result
                actual_items = []
                actual_examples = []
                rule_ids = []
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
                    "rule_ids": rule_ids,
                    "selector_trace": [
                        value for value in rule_ids if value.startswith("v7.selector:")
                    ],
                    "exact": Counter(fixture["surface_items"])
                    == Counter(actual_items)
                    and Counter(fixture["examples"] or [])
                    == Counter(actual_examples),
                    "error": error,
                }
            )
    return {
        "fixture_count": len(records),
        "exact_count": sum(record["exact"] for record in records),
        "records": records,
    }


def _record_by_id(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {record["id"]: record for record in raw["records"]}


def _regression_record(
    regression: dict[str, Any], cohort: str, fixture_id: str
) -> dict[str, Any]:
    if cohort == "legacy-20":
        return _record_by_id(regression["legacy_development"])[fixture_id]
    if cohort == "revealed-external-20":
        return _record_by_id(regression["revealed_external"])[fixture_id]
    if cohort == "projection-60":
        return _record_by_id(regression["projection_60"])[fixture_id]
    raise ValueError(f"unsupported cohort: {cohort}")


def _snapshot(record: dict[str, Any], cohort: str) -> dict[str, Any]:
    if cohort == "projection-60":
        return e9_common.projection_snapshot(record, expected=False)
    return e9_common.full_snapshot(record)


def _mechanism_preservation(
    development: dict[str, Any], reference: dict[str, Any]
) -> dict[str, Any]:
    actual = _record_by_id(development)
    expected = _record_by_id(reference)
    fixtures: dict[str, Any] = {}
    for fixture_id in sorted(expected):
        actual_snapshot = e9_common.full_snapshot(actual[fixture_id])
        reference_snapshot = e9_common.full_snapshot(expected[fixture_id])
        checks = {
            family: actual_snapshot[family] == reference_snapshot[family]
            for family in EXACT_FAMILIES
        }
        fixtures[fixture_id] = {"passed": all(checks.values()), "families": checks}
    exact_count = sum(value["passed"] for value in fixtures.values())
    return {
        "passed": len(fixtures) == 20 and exact_count == 20,
        "actual": {"fixture_count": len(fixtures), "exact_fixture_count": exact_count},
        "requirement": {"fixture_count": 20, "exact_fixture_count": 20},
        "fixtures": fixtures,
    }


def _e9_residual_gate(regression: dict[str, Any]) -> dict[str, Any]:
    e9 = _load(E9_RAW_PATH)
    record_specs = {record["id"]: record for record in e9["records"]}
    records: dict[str, Any] = {}
    corrected = 0
    retained = 0
    exact_count = 0
    trace_allowed = True
    for fixture_id, specification in sorted(record_specs.items()):
        cohort = specification["cohort"]
        actual_record = _regression_record(regression, cohort, fixture_id)
        actual = _snapshot(actual_record, cohort)
        reference = specification["reference"]
        baseline = specification["frozen_v6_region_level"]
        mismatched = specification["baseline_mismatched_families"]
        exact_families = specification["already_exact_v6_families"]
        corrected_checks = {
            family: actual[family] == reference[family] for family in mismatched
        }
        retained_checks = {
            family: actual[family] == baseline[family] for family in exact_families
        }
        all_exact = actual == reference
        exact_count += all_exact
        corrected += sum(corrected_checks.values())
        retained += sum(retained_checks.values())
        traces = actual_record["selector_trace"]
        allowed = all(
            any(
                token in value
                for token in ("signal=S1", "signal=S2", "signal=S3", "signal=supported-v5", "signal=default-v6")
            )
            for value in traces
        )
        trace_allowed = trace_allowed and allowed
        records[fixture_id] = {
            "passed": all_exact,
            "corrected_families": corrected_checks,
            "retained_v6_families": retained_checks,
            "selector_trace_allowed": allowed,
        }
    checks = {
        "targets_exact_9_of_9": v5_gate._gate(
            exact_count == 9, actual=exact_count, requirement="== 9"
        ),
        "v4_directed_families_16_of_16": v5_gate._gate(
            corrected == 16, actual=corrected, requirement="== 16"
        ),
        "retained_v6_families_9_of_9": v5_gate._gate(
            retained == 9, actual=retained, requirement="== 9"
        ),
        "selector_trace_uses_registered_decisions": v5_gate._gate(
            trace_allowed, actual=trace_allowed, requirement=True
        ),
    }
    return {
        "passed": all(check["passed"] for check in checks.values()),
        "checks": checks,
        "records": records,
    }


def _control_gate(regression: dict[str, Any]) -> dict[str, Any]:
    population = _load(E9_PREREGISTRATION_PATH)["population"]
    baseline_regression = _load(V6_REGRESSION_RAW_PATH)
    controls: dict[str, Any] = {}
    for specification in population["control_observations"]:
        cohort = specification["cohort"]
        fixture_id = specification["id"]
        actual = _snapshot(_regression_record(regression, cohort, fixture_id), cohort)
        baseline = _snapshot(
            _regression_record(baseline_regression, cohort, fixture_id), cohort
        )
        families = {family: actual[family] == baseline[family] for family in baseline}
        controls[fixture_id] = {"passed": all(families.values()), "families": families}
    exact_count = sum(value["passed"] for value in controls.values())
    return {
        "passed": len(controls) == 22 and exact_count == 22,
        "actual": {"control_count": len(controls), "byte_identical_count": exact_count},
        "requirement": {"control_count": 22, "byte_identical_count": 22},
        "controls": controls,
    }


def _legacy_exact_gate(regression: dict[str, Any]) -> dict[str, Any]:
    actual = _record_by_id(regression["legacy_development"])
    reference = _record_by_id(_load(V4_LEGACY_RAW_PATH))
    fixtures: dict[str, Any] = {}
    for fixture_id in sorted(reference):
        left = e9_common.full_snapshot(actual[fixture_id])
        right = e9_common.full_snapshot(reference[fixture_id])
        families = {family: left[family] == right[family] for family in EXACT_FAMILIES}
        fixtures[fixture_id] = {"passed": all(families.values()), "families": families}
    exact_count = sum(value["passed"] for value in fixtures.values())
    return {
        "passed": len(fixtures) == 20 and exact_count == 20,
        "actual": {"fixture_count": len(fixtures), "exact_fixture_count": exact_count},
        "requirement": {"fixture_count": 20, "exact_fixture_count": 20},
        "fixtures": fixtures,
    }


def _projection_gate(regression: dict[str, Any]) -> dict[str, Any]:
    projection = regression["projection_60"]
    return v5_gate._gate(
        projection["fixture_count"] == 60 and projection["exact_count"] == 60,
        actual={
            "fixture_count": projection["fixture_count"],
            "exact_count": projection["exact_count"],
        },
        requirement={"fixture_count": 60, "exact_count": 60},
    )


def _external_non_regression_gate(
    external_gold: dict[str, Any], regression: dict[str, Any]
) -> dict[str, Any]:
    actual_raw = regression["revealed_external"]
    v4_raw = _load(V4_EXTERNAL_RAW_PATH)
    v6_raw = _load(V6_REGRESSION_RAW_PATH)["revealed_external"]
    actual_quality = v5_gate._quality_metrics(evaluate_predictions(external_gold, actual_raw))
    v4_quality = v5_gate._quality_metrics(evaluate_predictions(external_gold, v4_raw))
    v6_quality = v5_gate._quality_metrics(evaluate_predictions(external_gold, v6_raw))
    aggregate = {
        name: {
            "v4": v4_quality[name],
            "v6": v6_quality[name],
            "v7": actual_quality[name],
            "passed": actual_quality[name] >= v4_quality[name]
            and actual_quality[name] >= v6_quality[name],
        }
        for name in actual_quality
    }
    gold = {fixture["id"]: fixture for fixture in external_gold["fixtures"]}
    actual = _record_by_id(actual_raw)
    v4_records = _record_by_id(v4_raw)
    v6_records = _record_by_id(v6_raw)
    fixtures: dict[str, Any] = {}
    for fixture_id, fixture in gold.items():
        actual_counts = v5_gate._layer_difference_counts(fixture, actual[fixture_id])
        v4_counts = v5_gate._layer_difference_counts(fixture, v4_records[fixture_id])
        v6_counts = v5_gate._layer_difference_counts(fixture, v6_records[fixture_id])
        layer_checks = {
            layer: actual_counts[layer] <= v4_counts[layer]
            and actual_counts[layer] <= v6_counts[layer]
            for layer in v5_gate.PRIMARY_LAYERS
        }
        fixtures[fixture_id] = {
            "passed": all(layer_checks.values()),
            "v4": v4_counts,
            "v6": v6_counts,
            "v7": actual_counts,
            "layers": layer_checks,
        }
    known_id = "structured-corpus-external-v1-006"
    wrapper_difference = v5_gate._difference_count(
        gold[known_id], actual[known_id], ("wrappers",)
    )
    checks = {
        "aggregate_no_worse_than_v4_and_v6": v5_gate._gate(
            all(value["passed"] for value in aggregate.values()),
            actual=aggregate,
            requirement="every aggregate primary metric >= v4 and >= v6",
        ),
        "per_fixture_no_worse_than_v4_and_v6": v5_gate._gate(
            all(value["passed"] for value in fixtures.values()),
            actual=fixtures,
            requirement="every primary-layer difference <= v4 and <= v6",
        ),
        "known_open_list_wrapper_regression_zero": v5_gate._gate(
            wrapper_difference == 0, actual=wrapper_difference, requirement="== 0"
        ),
    }
    return {
        "passed": all(check["passed"] for check in checks.values()),
        "checks": checks,
    }


def _static_audit() -> dict[str, Any]:
    source = V7_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden_text = (
        "fixture",
        "corpus",
        "gold",
        "expected",
        "employer",
        "job_title",
        "http",
        "requests",
        "urllib",
        "socket",
        "openai",
        "deepseek",
    )
    text_hits = [value for value in forbidden_text if value in source.casefold()]
    forbidden_imports = {
        "requests",
        "urllib",
        "socket",
        "httpx",
        "openai",
    }
    imports = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    category_branches = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, (ast.If, ast.Match, ast.Compare))
        and any(
            isinstance(child, ast.Name) and child.id == "category"
            for child in ast.walk(node.test if isinstance(node, ast.If) else node)
        )
    ]
    long_source_literals = [
        value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and (value := node.value)
        and len(value) > 4
        and any("\u4e00" <= character <= "\u9fff" for character in value)
    ]
    checks = {
        "forbidden_runtime_text_absent": not text_hits,
        "forbidden_imports_absent": not (imports & forbidden_imports),
        "category_not_inspected": not category_branches,
        "long_source_literals_absent": not long_source_literals,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "detail": {
            "text_hits": text_hits,
            "forbidden_imports": sorted(imports & forbidden_imports),
            "category_branch_lines": category_branches,
            "long_source_literals": long_source_literals,
        },
    }


def _trace_audit(raw_values: tuple[dict[str, Any], ...], projection: dict[str, Any]) -> dict[str, Any]:
    records = [record for raw in raw_values for record in raw["records"]]
    records.extend(projection["records"])
    failures: list[str] = []
    for record in records:
        traces = record["selector_trace"]
        if record["error"] is not None or len(traces) != 15:
            failures.append(record["id"])
            continue
        if sum("family=predicate" in value for value in traces) != 3:
            failures.append(record["id"])
        if sum("outcome=selected" in value for value in traces) != 6:
            failures.append(record["id"])
    return {
        "passed": not failures,
        "actual_failure_count": len(failures),
        "failures": sorted(set(failures)),
        "requirement": "deterministic 3-predicate, 6-restoration, 6-selection trace",
    }


def _selector_audit_gate(
    tests: dict[str, Any],
    development: dict[str, Any],
    regression: dict[str, Any],
) -> dict[str, Any]:
    static = _static_audit()
    trace = _trace_audit(
        (
            development,
            regression["legacy_development"],
            regression["revealed_external"],
        ),
        regression["projection_60"],
    )
    checks = {
        "all_structured_span_tests": v5_gate._gate(
            tests["exit_code"] == 0,
            actual={"exit_code": tests["exit_code"], "stdout": tests["stdout"]},
            requirement="pytest exit code 0",
        ),
        "synthetic_predicate_and_veto_tests_present": v5_gate._gate(
            V7_TEST_PATH in [ROOT / path for path in tests["test_paths"]],
            actual=_relative(V7_TEST_PATH),
            requirement="v7 synthetic test file included",
        ),
        "static_runtime_audit": v5_gate._gate(
            static["passed"], actual=static, requirement=True
        ),
        "selector_trace_audit": v5_gate._gate(
            trace["passed"], actual=trace, requirement=True
        ),
    }
    return {
        "passed": all(check["passed"] for check in checks.values()),
        "checks": checks,
    }


def _validity_gate(
    development: dict[str, Any], regression: dict[str, Any]
) -> dict[str, Any]:
    raw_values = (
        development,
        regression["legacy_development"],
        regression["revealed_external"],
    )
    errors = [
        record
        for raw in raw_values
        for record in raw["records"]
        if record["error"] is not None
    ]
    projection_errors = [
        record
        for record in regression["projection_60"]["records"]
        if record["error"] is not None
    ]
    anchoring = v5_gate._anchoring_errors(list(raw_values))
    frozen = {
        _relative(path): _sha256(path) == expected
        for path, expected in FROZEN_PARSER_HASHES.items()
    }
    calls_zero = all(
        raw["model_call_count"] == raw["network_call_count"] == 0
        for raw in raw_values
    )
    checks = {
        "all_outputs_parse_and_validate": v5_gate._gate(
            not errors and not projection_errors,
            actual=len(errors) + len(projection_errors),
            requirement="== 0",
        ),
        "all_spans_and_projections_anchored": v5_gate._gate(
            not anchoring, actual=len(anchoring), requirement="== 0", detail=anchoring
        ),
        "frozen_v4_v5_v6_unchanged": v5_gate._gate(
            all(frozen.values()), actual=frozen, requirement=True
        ),
        "zero_model_and_network_calls": v5_gate._gate(
            calls_zero,
            actual={"model_call_count": 0, "network_call_count": 0},
            requirement={"model_call_count": 0, "network_call_count": 0},
        ),
    }
    return {
        "passed": all(check["passed"] for check in checks.values()),
        "checks": checks,
    }


def _render_findings(report: dict[str, Any]) -> str:
    lines = [
        "# Frozen v7 one-time development and regression gates",
        "",
        "## Outcome",
        "",
        f"- Overall gate passed: `{str(report['gate_passed']).lower()}`.",
        "- This is revealed development evidence, not a generalization claim.",
        "- Model and network call counts are both zero.",
        "",
        "## Conjunctive gates",
        "",
    ]
    lines.extend(
        f"- `{name}`: {'passed' if value['passed'] else 'failed'}."
        for name, value in report["gates"].items()
    )
    lines.extend(
        [
            "",
            "## Decision",
            "",
            (
                "All preregistered gates passed. V7 remains frozen, but canonicalizer work "
                "stays locked until a separately preregistered fresh external blind holdout passes."
                if report["gate_passed"]
                else "At least one preregistered gate failed. V7 and these results remain "
                "frozen, v4 stays the production reference, and only offline diagnosis is allowed."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _receipt(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "receipt_version": "unified-jd-structured-span-v7-development-regression-receipt-v1",
        "evaluated_at": datetime.now(UTC).isoformat(),
        "status": "one_time_frozen_v7_development_and_regression_evaluated",
        "inputs": {
            "source_freeze": {
                "path": _relative(SOURCE_FREEZE_PATH),
                "sha256": _sha256(SOURCE_FREEZE_PATH),
            },
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
        "gate_passed": report["gate_passed"],
        "development_run_count": 1,
        "regression_run_count": 1,
        "canonicalizer_allowed": False,
        "model_call_count": 0,
        "network_call_count": 0,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Freeze or execute the preregistered v7 gates exactly once"
    )
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument(
        "--freeze-source",
        action="store_true",
        help="freeze the v7 parser, synthetic tests, and evaluator without importing v7",
    )
    actions.add_argument(
        "--preflight",
        action="store_true",
        help="validate frozen inputs and unused outputs without importing or executing v7",
    )
    return parser.parse_args()


def main() -> int:
    arguments = _parse_args()
    _validate_preregistration()
    if arguments.freeze_source:
        freeze = _freeze_source()
        print(json.dumps(freeze, ensure_ascii=False, indent=2))
        return 0

    _validate_source_freeze()
    _validate_unused_outputs()
    if arguments.preflight:
        print(
            "preflight passed: preregistration, frozen sources, and unused output paths "
            "verified; v7 was not imported or executed"
        )
        return 0

    labels = _load(LABELS_PATH)
    development_gold = v5_gate._normalize_mechanism_gold(labels)
    development = _run_predictions(development_gold, "mechanism-development")
    _write_new(DEVELOPMENT_RAW_PATH, _serialized(development))

    v6_preregistration = _load(V6_PREREGISTRATION_PATH)
    legacy_gold = v6_gate._adjudicated_legacy_gold(
        v6_preregistration, _load(LEGACY_GOLD_PATH)
    )
    external_gold = v5_gate._normalize_external_gold(_load(EXTERNAL_DEVELOPMENT_PATH))
    legacy = _run_predictions(legacy_gold, "legacy-development-regression")
    external = _run_predictions(external_gold, "revealed-external-regression")
    projection = _run_projection_regression()
    tests = v5_gate._run_structured_span_tests()
    regression = {
        "raw_version": "unified-jd-structured-span-v7-regression-raw-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "parser_path": _relative(V7_PATH),
        "parser_sha256": _sha256(V7_PATH),
        "model_call_count": 0,
        "network_call_count": 0,
        "legacy_development": legacy,
        "revealed_external": external,
        "projection_60": projection,
        "structured_span_tests": tests,
    }
    _write_new(REGRESSION_RAW_PATH, _serialized(regression))

    development_report = evaluate_predictions(development_gold, development)
    original_preregistration = _load(V5_PREREGISTRATION_PATH)
    original_development = v5_gate._build_development_gates(
        original_preregistration,
        development_gold,
        development,
        development_report,
    )
    original_regression = v5_gate._build_regression_gate(
        legacy_gold,
        legacy,
        external_gold,
        external,
        projection,
        tests,
    )
    g0 = _validity_gate(development, regression)
    g1_components = {"G0-validity": g0, **original_development, "G6-regression": original_regression}
    g1 = {
        "passed": all(value["passed"] for value in g1_components.values()),
        "components": g1_components,
    }
    gates = {
        "G0-frozen-input-and-validity": g0,
        "G1-original-v5-G0-G6-unchanged": g1,
        "G2-v5-mechanism-preservation": _mechanism_preservation(
            development, _load(V5_MECHANISM_RAW_PATH)
        ),
        "G3-e9-residual-runtime-selection": _e9_residual_gate(regression),
        "G4-v6-resolved-control-preservation": _control_gate(regression),
        "G5-legacy-effective-exact": _legacy_exact_gate(regression),
        "G6-projection-regression-exact": _projection_gate(regression),
        "G7-revealed-external-non-regression": _external_non_regression_gate(
            external_gold, regression
        ),
        "G8-tests-and-selector-audit": _selector_audit_gate(
            tests, development, regression
        ),
    }
    report = {
        "report_version": "unified-jd-structured-span-v7-development-regression-report-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "frozen_one_time_development_and_regression_result",
        "scope": {
            "development_data_status": "revealed_not_holdout",
            "generalization_claim": False,
            "threshold_changes_allowed": False,
            "v7_source_changes_allowed_after_result": False,
            "canonicalizer_allowed": False,
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
        "development_metrics": v5_gate._metric_snapshot(development_report),
        "gates": gates,
        "gate_passed": all(value["passed"] for value in gates.values()),
        "canonicalizer_allowed": False,
    }
    _write_new(REPORT_PATH, _serialized(report))
    _write_new(FINDINGS_PATH, _render_findings(report))
    _write_new(RECEIPT_PATH, _serialized(_receipt(report)))
    print(
        json.dumps(
            {
                "gates": {name: value["passed"] for name, value in gates.items()},
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
