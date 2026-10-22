from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts import evaluate_unified_structured_span_v5_gates as v5_gate
from scripts import evaluate_unified_structured_span_v6_gates as v6_gate
from scripts import evaluate_unified_structured_span_v7_gates as v7_gate
from scripts import unified_structured_span_v6_residual_oracle_common as e9_common
from scripts.evaluate_unified_structured_span_v4_development import evaluate_predictions

ROOT = Path(__file__).resolve().parents[1]
DATE = "2026-09-05"
PREREGISTRATION_PATH = (
    ROOT / f"datasets/unified_jd_structured_span_v8_preregistration_v1_{DATE}.json"
)
PREREGISTRATION_FREEZE_PATH = (
    ROOT
    / f"datasets/unified_jd_structured_span_v8_preregistration_freeze_v1_{DATE}.json"
)
SOURCE_FREEZE_PATH = (
    ROOT / f"datasets/unified_jd_structured_span_v8_source_freeze_v1_{DATE}.json"
)
V8_PATH = ROOT / "src/domain/unified_jd_structured_spans_v8.py"
V8_TEST_PATH = ROOT / "tests/test_unified_jd_structured_spans_v8.py"
EVALUATOR_PATH = Path(__file__).resolve()
DEVELOPMENT_RAW_PATH = (
    ROOT
    / f"artifacts/evaluation/unified-jd-structured-span-v8-mechanism-development-raw-v1-{DATE}.json"
)
REGRESSION_RAW_PATH = (
    ROOT
    / f"artifacts/evaluation/unified-jd-structured-span-v8-regression-raw-v1-{DATE}.json"
)
REPORT_PATH = (
    ROOT
    / f"artifacts/evaluation/unified-jd-structured-span-v8-development-regression-report-v1-{DATE}.json"
)
FINDINGS_PATH = (
    ROOT
    / f"artifacts/evaluation/unified-jd-structured-span-v8-development-regression-findings-v1-{DATE}.md"
)
RECEIPT_PATH = (
    ROOT
    / f"artifacts/evaluation/unified-jd-structured-span-v8-development-regression-receipt-v1-{DATE}.json"
)
OUTPUT_PATHS = (
    DEVELOPMENT_RAW_PATH,
    REGRESSION_RAW_PATH,
    REPORT_PATH,
    FINDINGS_PATH,
    RECEIPT_PATH,
)
CLASSIFICATION_PATH = (
    ROOT
    / f"artifacts/evaluation/unified-jd-structured-span-v7-frozen-raw-failure-classification-v1-{DATE}.json"
)
V5_REFERENCE_PATH = v7_gate.V5_MECHANISM_RAW_PATH
V6_REFERENCE_PATH = v7_gate.V6_REGRESSION_RAW_PATH
EXACT_FAMILIES = v7_gate.EXACT_FAMILIES
PROJECTION_FIXTURE_PATHS = v7_gate.PROJECTION_FIXTURE_PATHS


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


def _input_references(preregistration: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for value in preregistration["inputs"].values():
        if "path" in value:
            result.append(value)
        else:
            result.extend(value.values())
    return result


def _validate_preregistration() -> dict[str, Any]:
    preregistration = _load(PREREGISTRATION_PATH)
    freeze = _load(PREREGISTRATION_FREEZE_PATH)
    _validate_reference(freeze["artifacts"]["preregistration"])
    for reference in _input_references(preregistration):
        _validate_reference(reference)
    if preregistration["status"] != "frozen_before_v8_implementation":
        raise ValueError("v8 preregistration status is invalid")
    protocol = preregistration["evaluation_protocol"]
    if protocol["all_criteria_conjunctive"] is not True:
        raise ValueError("v8 criteria are no longer conjunctive")
    if protocol["source_freeze_before_any_v8_record_execution"] is not True:
        raise ValueError("v8 source-freeze requirement changed")
    if protocol["v8_development_run_count"] != 1:
        raise ValueError("v8 development run count changed")
    if protocol["v8_regression_run_count"] != 1:
        raise ValueError("v8 regression run count changed")
    if preregistration["scope"]["model_calls_allowed"] is not False:
        raise ValueError("v8 unexpectedly permits model calls")
    if preregistration["scope"]["network_calls_allowed"] is not False:
        raise ValueError("v8 unexpectedly permits network calls")
    prior = _load(v7_gate.PREREGISTRATION_PATH)["acceptance_gates"]
    prior_behavior = {
        name: gate for name, gate in prior.items() if not name.startswith("G8-")
    }
    expected = preregistration["acceptance_gates"][
        "G1-v7-behavioral-gates-not-weakened"
    ]["source"]["canonical_sha256"]
    if _json_sha256(prior_behavior) != expected:
        raise ValueError("v7 G0-G7 behavioral contract changed")
    return preregistration


def _validate_unused_outputs() -> None:
    existing = [_relative(path) for path in OUTPUT_PATHS if path.exists()]
    if existing:
        raise FileExistsError(f"one-time v8 output already exists: {existing}")


def _freeze_source() -> dict[str, Any]:
    preregistration = _validate_preregistration()
    _validate_unused_outputs()
    if SOURCE_FREEZE_PATH.exists():
        raise FileExistsError(
            f"source freeze already exists: {_relative(SOURCE_FREEZE_PATH)}"
        )
    artifacts = {
        "v8_parser": {"path": _relative(V8_PATH), "sha256": _sha256(V8_PATH)},
        "v8_synthetic_tests": {
            "path": _relative(V8_TEST_PATH),
            "sha256": _sha256(V8_TEST_PATH),
        },
        "v8_one_time_evaluator": {
            "path": _relative(EVALUATOR_PATH),
            "sha256": _sha256(EVALUATOR_PATH),
        },
        "v8_preregistration": {
            "path": _relative(PREREGISTRATION_PATH),
            "sha256": _sha256(PREREGISTRATION_PATH),
        },
    }
    freeze = {
        "freeze_version": "unified-jd-structured-span-v8-source-freeze-v1",
        "frozen_at": datetime.now(UTC).isoformat(),
        "status": "v8_source_tests_evaluator_frozen_before_one_time_gates",
        "preregistration_version": preregistration["preregistration_version"],
        "artifacts": artifacts,
        "checks": {
            "development_run_count_before_freeze": 0,
            "regression_run_count_before_freeze": 0,
            "v8_imported_or_executed_by_freeze": False,
            "model_call_count": 0,
            "network_call_count": 0,
            "canonicalizer_allowed": False,
        },
        "immutability": (
            "Any parser, test, evaluator, component edge, witness, veto, precedence, "
            "threshold, or input change requires a new preregistration."
        ),
    }
    _write_new(SOURCE_FREEZE_PATH, _serialized(freeze))
    return freeze


def _validate_source_freeze() -> dict[str, Any]:
    freeze = _load(SOURCE_FREEZE_PATH)
    if freeze["status"] != "v8_source_tests_evaluator_frozen_before_one_time_gates":
        raise ValueError("v8 source freeze status is invalid")
    for reference in freeze["artifacts"].values():
        _validate_reference(reference)
    return freeze


def _run_predictions(gold: dict[str, Any], scope: str) -> dict[str, Any]:
    from src.domain.unified_jd_structured_spans_v8 import (
        STRUCTURED_SPAN_PARSER_VERSION,
        extract_surface_items,
    )

    records: list[dict[str, Any]] = []
    for item in gold["fixtures"]:
        try:
            extraction = extract_surface_items(item["source_text"], item["category"])
            records.append(
                {
                    "id": item["id"],
                    "category": item["category"],
                    "source_text": item["source_text"],
                    "error": None,
                    "items": list(extraction.items),
                    "examples": list(extraction.examples),
                    "rule_ids": list(extraction.rule_ids),
                    "selector_trace": [
                        value
                        for value in extraction.rule_ids
                        if value.startswith("v8.selector:")
                    ],
                    "parsed_clause": asdict(extraction.parsed_clause),
                }
            )
        except Exception as error:  # noqa: BLE001 - frozen gate result
            records.append(
                {
                    "id": item["id"],
                    "category": item["category"],
                    "source_text": item["source_text"],
                    "error": f"{type(error).__name__}: {error}",
                    "items": [],
                    "examples": [],
                    "rule_ids": [],
                    "selector_trace": [],
                    "parsed_clause": None,
                }
            )
    return {
        "raw_version": f"unified-jd-structured-span-v8-{scope}-raw-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": scope,
        "parser_version": STRUCTURED_SPAN_PARSER_VERSION,
        "parser_path": _relative(V8_PATH),
        "parser_sha256": _sha256(V8_PATH),
        "model_call_count": 0,
        "network_call_count": 0,
        "records": records,
    }


def _run_projection_regression() -> dict[str, Any]:
    from src.domain.unified_jd_structured_spans_v8 import extract_surface_items

    records: list[dict[str, Any]] = []
    for path in PROJECTION_FIXTURE_PATHS:
        for item in _load(path)["fixtures"]:
            try:
                extraction = extract_surface_items(
                    item["source_text"], item["category"]
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
                    "id": item["id"],
                    "category": item["category"],
                    "source_text": item["source_text"],
                    "expected_items": item["surface_items"],
                    "actual_items": actual_items,
                    "expected_examples": item["examples"] or [],
                    "actual_examples": actual_examples,
                    "rule_ids": rule_ids,
                    "selector_trace": [
                        value for value in rule_ids if value.startswith("v8.selector:")
                    ],
                    "exact": Counter(item["surface_items"]) == Counter(actual_items)
                    and Counter(item["examples"] or []) == Counter(actual_examples),
                    "error": error,
                }
            )
    return {
        "fixture_count": len(records),
        "exact_count": sum(record["exact"] for record in records),
        "records": records,
    }


def _safe_gate(name: str, callback: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        return callback()
    except Exception as error:  # noqa: BLE001 - preserve one-time raw
        return {
            "passed": False,
            "aggregation_error": f"{type(error).__name__}: {error}",
            "gate": name,
        }


def _record_by_id(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {record["id"]: record for record in raw["records"]}


def _regression_record(
    regression: dict[str, Any], cohort: str, record_id: str
) -> dict[str, Any]:
    if cohort == "legacy-20":
        return _record_by_id(regression["legacy_development"])[record_id]
    if cohort == "revealed-external-20":
        return _record_by_id(regression["revealed_external"])[record_id]
    if cohort == "projection-60":
        return _record_by_id(regression["projection_60"])[record_id]
    raise ValueError(f"unsupported cohort: {cohort}")


def _snapshot(record: dict[str, Any], cohort: str) -> dict[str, Any]:
    if cohort == "projection-60":
        return e9_common.projection_snapshot(record, expected=False)
    return e9_common.full_snapshot(record)


def _validity_gate(
    preregistration: dict[str, Any],
    development: dict[str, Any],
    regression: dict[str, Any],
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
        reference["path"]: _sha256(ROOT / reference["path"]) == reference["sha256"]
        for reference in _input_references(preregistration)
    }
    calls_zero = all(
        raw["model_call_count"] == raw["network_call_count"] == 0 for raw in raw_values
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
        "all_frozen_inputs_unchanged": v5_gate._gate(
            all(frozen.values()), actual=frozen, requirement=True
        ),
        "source_freeze_unchanged": v5_gate._gate(
            bool(_validate_source_freeze()), actual=True, requirement=True
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


def _three_class_gate(
    classification: dict[str, Any],
    development: dict[str, Any],
    regression: dict[str, Any],
) -> dict[str, Any]:
    actual_development = _record_by_id(development)
    v5_reference = _record_by_id(_load(V5_REFERENCE_PATH))
    e6_id = classification["classes"]["E6-implementation-exception"]["record_id"]
    under_ids = [
        record["record_id"]
        for record in classification["classes"][
            "supported-v5-restoration-under-recall"
        ]["records"]
    ]
    restoration_ids = [e6_id, *under_ids]
    restoration: dict[str, Any] = {}
    for record_id in restoration_ids:
        record = actual_development[record_id]
        exact = record["error"] is None and e9_common.full_snapshot(
            record
        ) == e9_common.full_snapshot(v5_reference[record_id])
        restoration[record_id] = {"passed": exact, "error": record["error"]}

    controls: dict[str, Any] = {}
    v6_reference = _load(V6_REFERENCE_PATH)
    for specification in classification["classes"][
        "control-supported-v5-false-activation"
    ]["records"]:
        cohort = specification["cohort"]
        record_id = specification["record_id"]
        actual_record = _regression_record(regression, cohort, record_id)
        reference_record = _regression_record(v6_reference, cohort, record_id)
        exact = _snapshot(actual_record, cohort) == _snapshot(reference_record, cohort)
        non_v6 = any(
            "origin=v4" in trace or "origin=v5" in trace
            for trace in actual_record["selector_trace"]
        )
        controls[record_id] = {
            "passed": exact and not non_v6,
            "exact_to_v6": exact,
            "non_v6_selection": non_v6,
        }
    checks = {
        "E6_parses_and_equals_v5": v5_gate._gate(
            restoration[e6_id]["passed"],
            actual=restoration[e6_id],
            requirement={"parse_error_count": 0, "exact_to_v5_count": 1},
        ),
        "under_recall_12_equal_v5": v5_gate._gate(
            len(under_ids) == 12
            and all(restoration[record_id]["passed"] for record_id in under_ids),
            actual=sum(restoration[record_id]["passed"] for record_id in under_ids),
            requirement="== 12",
        ),
        "false_activations_15_equal_v6": v5_gate._gate(
            len(controls) == 15 and all(value["passed"] for value in controls.values()),
            actual={
                "control_count": len(controls),
                "exact_to_v6_count": sum(
                    value["exact_to_v6"] for value in controls.values()
                ),
                "non_v6_selection_count": sum(
                    value["non_v6_selection"] for value in controls.values()
                ),
            },
            requirement={
                "control_count": 15,
                "exact_to_v6_count": 15,
                "non_v6_selection_count": 0,
            },
        ),
    }
    return {
        "passed": all(check["passed"] for check in checks.values()),
        "checks": checks,
        "restoration": restoration,
        "controls": controls,
    }


def _e9_gate(regression: dict[str, Any]) -> dict[str, Any]:
    e9 = _load(v7_gate.E9_RAW_PATH)
    records: dict[str, Any] = {}
    corrected = 0
    retained = 0
    exact_count = 0
    trace_allowed = True
    for specification in e9["records"]:
        record_id = specification["id"]
        cohort = specification["cohort"]
        actual_record = _regression_record(regression, cohort, record_id)
        actual = _snapshot(actual_record, cohort)
        reference = specification["reference"]
        baseline = specification["frozen_v6_region_level"]
        corrected_checks = {
            family: actual[family] == reference[family]
            for family in specification["baseline_mismatched_families"]
        }
        retained_checks = {
            family: actual[family] == baseline[family]
            for family in specification["already_exact_v6_families"]
        }
        exact = actual == reference
        exact_count += exact
        corrected += sum(corrected_checks.values())
        retained += sum(retained_checks.values())
        traces = actual_record["selector_trace"]
        allowed = bool(traces) and all(
            any(
                token in trace
                for token in (
                    "selection=S1",
                    "selection=S2",
                    "selection=S3",
                    "selection=supported-v5",
                    "selection=compatibility-veto",
                    "selection=default-v6",
                    "selection=no-delta",
                )
            )
            for trace in traces
        )
        trace_allowed = trace_allowed and allowed
        records[record_id] = {
            "passed": exact,
            "corrected_families": corrected_checks,
            "retained_v6_families": retained_checks,
            "selector_trace_allowed": allowed,
        }
    checks = {
        "targets_exact_9_of_9": v5_gate._gate(
            exact_count == 9, actual=exact_count, requirement="== 9"
        ),
        "corrected_families_16_of_16": v5_gate._gate(
            corrected == 16, actual=corrected, requirement="== 16"
        ),
        "retained_v6_families_9_of_9": v5_gate._gate(
            retained == 9, actual=retained, requirement="== 9"
        ),
        "trace_uses_registered_decisions": v5_gate._gate(
            trace_allowed, actual=trace_allowed, requirement=True
        ),
    }
    return {
        "passed": all(check["passed"] for check in checks.values()),
        "checks": checks,
        "records": records,
    }


def _static_audit() -> dict[str, Any]:
    source = V8_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden_text = (
        "fixture",
        "corpus",
        "gold",
        "expected",
        "metadata",
        "employer",
        "job_title",
        "canonical",
        "http",
        "requests",
        "urllib",
        "socket",
        "openai",
        "deepseek",
    )
    text_hits = [value for value in forbidden_text if value in source.casefold()]
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)
    forbidden_imports = {
        value
        for value in imported_modules
        if value.split(".")[0] in {"requests", "urllib", "socket", "httpx", "openai"}
        or value.endswith("unified_jd_structured_spans_v7")
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
    record_literals = [
        value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and (value := node.value)
        and re.search(
            r"(?:structured-(?:v5|external)|surface-holdout|canonical-v1)-",
            value,
            re.IGNORECASE,
        )
    ]
    checks = {
        "forbidden_runtime_text_absent": not text_hits,
        "forbidden_imports_absent": not forbidden_imports,
        "category_not_inspected": not category_branches,
        "long_source_literals_absent": not long_source_literals,
        "record_literals_absent": not record_literals,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "detail": {
            "text_hits": text_hits,
            "forbidden_imports": sorted(forbidden_imports),
            "category_branch_lines": category_branches,
            "long_source_literals": long_source_literals,
            "record_literals": record_literals,
        },
    }


def _trace_audit(
    development: dict[str, Any], regression: dict[str, Any]
) -> dict[str, Any]:
    records = [
        *development["records"],
        *regression["legacy_development"]["records"],
        *regression["revealed_external"]["records"],
        *regression["projection_60"]["records"],
    ]
    required = (
        "component=",
        "envelope=",
        "witness=",
        "compatibility=",
        "family=",
        "origin=",
        "selection=",
    )
    failures: list[str] = []
    mechanisms: set[str] = set()
    for record in records:
        traces = record["selector_trace"]
        if record["error"] is not None or not traces:
            failures.append(record["id"])
            continue
        if any(not all(token in trace for token in required) for trace in traces):
            failures.append(record["id"])
        for mechanism in (
            "E2-wrapper-boundary",
            "E3-region-first-connector-role",
            "E6-priority-tail-rejection",
            "E7-prepositional-wrapper-before-example-split",
        ):
            if any(
                f"witness={mechanism}" in trace or f"+{mechanism}" in trace
                for trace in traces
            ):
                mechanisms.add(mechanism)
    return {
        "passed": not failures and len(mechanisms) == 4,
        "actual_failure_count": len(set(failures)),
        "failures": sorted(set(failures)),
        "observed_witnesses": sorted(mechanisms),
        "requirement": "all component traces complete and all four witnesses observable",
    }


def _audit_gate(
    tests: dict[str, Any],
    development: dict[str, Any],
    regression: dict[str, Any],
) -> dict[str, Any]:
    static = _static_audit()
    trace = _trace_audit(development, regression)
    test_paths = [ROOT / path for path in tests["test_paths"]]
    checks = {
        "all_structured_span_tests": v5_gate._gate(
            tests["exit_code"] == 0,
            actual={"exit_code": tests["exit_code"], "stdout": tests["stdout"]},
            requirement="pytest exit code 0",
        ),
        "v8_synthetic_tests_present": v5_gate._gate(
            V8_TEST_PATH in test_paths,
            actual=_relative(V8_TEST_PATH),
            requirement="v8 synthetic test file included",
        ),
        "static_runtime_audit": v5_gate._gate(
            static["passed"], actual=static, requirement=True
        ),
        "component_trace_audit": v5_gate._gate(
            trace["passed"], actual=trace, requirement=True
        ),
    }
    return {
        "passed": all(check["passed"] for check in checks.values()),
        "checks": checks,
    }


def _render_findings(report: dict[str, Any]) -> str:
    lines = [
        "# Frozen v8 one-time development and regression gates",
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
                "All frozen gates passed. V8 remains frozen; canonicalizer work stays "
                "locked until a separately preregistered fresh external blind holdout passes."
                if report["gate_passed"]
                else "At least one frozen gate failed. V8 and these raw results remain "
                "frozen; only offline diagnosis and a newly preregistered version are allowed."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _receipt(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "receipt_version": "unified-jd-structured-span-v8-development-regression-receipt-v1",
        "evaluated_at": datetime.now(UTC).isoformat(),
        "status": "one_time_frozen_v8_development_and_regression_evaluated",
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
        description="Freeze or execute the preregistered v8 gates exactly once"
    )
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument(
        "--freeze-source",
        action="store_true",
        help="freeze v8 source without importing or executing the parser",
    )
    actions.add_argument(
        "--preflight",
        action="store_true",
        help="validate frozen inputs and unused outputs without importing v8",
    )
    return parser.parse_args()


def main() -> int:
    arguments = _parse_args()
    preregistration = _validate_preregistration()
    if arguments.freeze_source:
        freeze = _freeze_source()
        print(json.dumps(freeze, ensure_ascii=False, indent=2))
        return 0

    _validate_source_freeze()
    _validate_unused_outputs()
    if arguments.preflight:
        print(
            "preflight passed: frozen inputs, source hashes, and unused output paths "
            "verified; v8 was not imported or executed"
        )
        return 0

    labels = _load(v7_gate.LABELS_PATH)
    development_gold = v5_gate._normalize_mechanism_gold(labels)
    development = _run_predictions(development_gold, "mechanism-development")
    _write_new(DEVELOPMENT_RAW_PATH, _serialized(development))

    v6_preregistration = _load(v7_gate.V6_PREREGISTRATION_PATH)
    legacy_gold = v6_gate._adjudicated_legacy_gold(
        v6_preregistration, _load(v7_gate.LEGACY_GOLD_PATH)
    )
    external_gold = v5_gate._normalize_external_gold(
        _load(v7_gate.EXTERNAL_DEVELOPMENT_PATH)
    )
    legacy = _run_predictions(legacy_gold, "legacy-development-regression")
    external = _run_predictions(external_gold, "revealed-external-regression")
    projection = _run_projection_regression()
    tests = v5_gate._run_structured_span_tests()
    regression = {
        "raw_version": "unified-jd-structured-span-v8-regression-raw-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "parser_path": _relative(V8_PATH),
        "parser_sha256": _sha256(V8_PATH),
        "model_call_count": 0,
        "network_call_count": 0,
        "legacy_development": legacy,
        "revealed_external": external,
        "projection_60": projection,
        "structured_span_tests": tests,
    }
    _write_new(REGRESSION_RAW_PATH, _serialized(regression))

    development_report = evaluate_predictions(development_gold, development)
    original_development = _safe_gate(
        "original-v5-development",
        lambda: v5_gate._build_development_gates(
            _load(v7_gate.V5_PREREGISTRATION_PATH),
            development_gold,
            development,
            development_report,
        ),
    )
    original_regression = _safe_gate(
        "original-v5-regression",
        lambda: v5_gate._build_regression_gate(
            legacy_gold,
            legacy,
            external_gold,
            external,
            projection,
            tests,
        ),
    )
    g0 = _safe_gate(
        "G0-validity", lambda: _validity_gate(preregistration, development, regression)
    )
    g3 = _safe_gate(
        "G3-v5-mechanism-preservation",
        lambda: v7_gate._mechanism_preservation(development, _load(V5_REFERENCE_PATH)),
    )
    g4 = _safe_gate("G4-E9-residual-preservation", lambda: _e9_gate(regression))
    g5 = _safe_gate(
        "G5-control-preservation", lambda: v7_gate._control_gate(regression)
    )
    g6 = _safe_gate(
        "G6-legacy-effective-exact", lambda: v7_gate._legacy_exact_gate(regression)
    )
    g7 = _safe_gate(
        "G7-projection-regression-exact", lambda: v7_gate._projection_gate(regression)
    )
    g8 = _safe_gate(
        "G8-revealed-external-non-regression",
        lambda: v7_gate._external_non_regression_gate(external_gold, regression),
    )
    prior_gates = {
        "G0-frozen-input-and-validity": g0,
        "G1-original-v5-G0-G6-unchanged": {
            "passed": original_development["passed"] and original_regression["passed"],
            "components": {
                "development": original_development,
                "regression": original_regression,
            },
        },
        "G2-v5-mechanism-preservation": g3,
        "G3-e9-residual-runtime-selection": g4,
        "G4-v6-resolved-control-preservation": g5,
        "G5-legacy-effective-exact": g6,
        "G6-projection-regression-exact": g7,
        "G7-revealed-external-non-regression": g8,
    }
    g1 = {
        "passed": all(value["passed"] for value in prior_gates.values()),
        "components": prior_gates,
    }
    classification = _load(CLASSIFICATION_PATH)
    gates = {
        "G0-frozen-input-validity-and-zero-calls": g0,
        "G1-v7-behavioral-gates-not-weakened": g1,
        "G2-three-class-resolution": _safe_gate(
            "G2-three-class-resolution",
            lambda: _three_class_gate(classification, development, regression),
        ),
        "G3-v5-mechanism-preservation": g3,
        "G4-E9-residual-preservation": g4,
        "G5-control-preservation": g5,
        "G6-legacy-effective-exact": g6,
        "G7-projection-regression-exact": g7,
        "G8-revealed-external-non-regression": g8,
        "G9-selector-and-test-audit": _safe_gate(
            "G9-selector-and-test-audit",
            lambda: _audit_gate(tests, development, regression),
        ),
    }
    report = {
        "report_version": "unified-jd-structured-span-v8-development-regression-report-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "frozen_one_time_development_and_regression_result",
        "scope": {
            "development_data_status": "revealed_not_holdout",
            "generalization_claim": False,
            "threshold_changes_allowed": False,
            "v8_source_changes_allowed_after_result": False,
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
