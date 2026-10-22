from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts import evaluate_unified_structured_span_v5_gates as v5_gate
from scripts import evaluate_unified_structured_span_v6_gates as v6_gate
from scripts import evaluate_unified_structured_span_v7_gates as v7_gate
from scripts import evaluate_unified_structured_span_v8_gates as v8_gate
from scripts.evaluate_unified_structured_span_v4_development import (
    evaluate_predictions,
)

ROOT = Path(__file__).resolve().parents[1]
DATE = "2026-09-05"
POSTMORTEM_PATH = (
    ROOT
    / "artifacts/evaluation"
    / f"unified-jd-structured-span-v8-one-time-execution-postmortem-v1-{DATE}.json"
)
OFFLINE_REPORT_PATH = (
    ROOT
    / "artifacts/evaluation"
    / f"unified-jd-structured-span-v8-frozen-raw-offline-gates-v1-{DATE}.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _write_new(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as output:
        json.dump(value, output, ensure_ascii=False, indent=2)
        output.write("\n")


def _reference(path: Path) -> dict[str, str]:
    return {"path": _relative(path), "sha256": _sha256(path)}


def _summarize_development_gates(gates: dict[str, Any]) -> dict[str, Any]:
    if "passed" in gates:
        return gates
    return {
        "passed": all(value["passed"] for value in gates.values()),
        "components": gates,
    }


def main() -> int:
    existing = [
        _relative(path)
        for path in (POSTMORTEM_PATH, OFFLINE_REPORT_PATH)
        if path.exists()
    ]
    if existing:
        raise FileExistsError(f"offline v8 postmortem already exists: {existing}")

    preregistration = v8_gate._validate_preregistration()
    v8_gate._validate_source_freeze()
    development = v8_gate._load(v8_gate.DEVELOPMENT_RAW_PATH)
    regression = v8_gate._load(v8_gate.REGRESSION_RAW_PATH)

    source_freeze = v8_gate._load(v8_gate.SOURCE_FREEZE_PATH)
    frozen_parser_hash = source_freeze["artifacts"]["v8_parser"]["sha256"]
    if development["parser_sha256"] != frozen_parser_hash:
        raise ValueError("development raw parser hash differs from source freeze")
    if regression["parser_sha256"] != frozen_parser_hash:
        raise ValueError("regression raw parser hash differs from source freeze")

    labels = v8_gate._load(v7_gate.LABELS_PATH)
    development_gold = v5_gate._normalize_mechanism_gold(labels)
    development_report = evaluate_predictions(development_gold, development)

    v6_preregistration = v8_gate._load(v7_gate.V6_PREREGISTRATION_PATH)
    legacy_gold = v6_gate._adjudicated_legacy_gold(
        v6_preregistration, v8_gate._load(v7_gate.LEGACY_GOLD_PATH)
    )
    external_gold = v5_gate._normalize_external_gold(
        v8_gate._load(v7_gate.EXTERNAL_DEVELOPMENT_PATH)
    )
    legacy = regression["legacy_development"]
    external = regression["revealed_external"]
    projection = regression["projection_60"]
    tests = regression["structured_span_tests"]

    original_development = v8_gate._safe_gate(
        "original-v5-development",
        lambda: v5_gate._build_development_gates(
            v8_gate._load(v7_gate.V5_PREREGISTRATION_PATH),
            development_gold,
            development,
            development_report,
        ),
    )
    original_development_summary = _summarize_development_gates(original_development)
    original_regression = v8_gate._safe_gate(
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
    g0 = v8_gate._safe_gate(
        "G0-validity",
        lambda: v8_gate._validity_gate(preregistration, development, regression),
    )
    g3 = v8_gate._safe_gate(
        "G3-v5-mechanism-preservation",
        lambda: v7_gate._mechanism_preservation(
            development, v8_gate._load(v8_gate.V5_REFERENCE_PATH)
        ),
    )
    g4 = v8_gate._safe_gate(
        "G4-E9-residual-preservation", lambda: v8_gate._e9_gate(regression)
    )
    g5 = v8_gate._safe_gate(
        "G5-control-preservation", lambda: v7_gate._control_gate(regression)
    )
    g6 = v8_gate._safe_gate(
        "G6-legacy-effective-exact",
        lambda: v7_gate._legacy_exact_gate(regression),
    )
    g7 = v8_gate._safe_gate(
        "G7-projection-regression-exact",
        lambda: v7_gate._projection_gate(regression),
    )
    g8 = v8_gate._safe_gate(
        "G8-revealed-external-non-regression",
        lambda: v7_gate._external_non_regression_gate(external_gold, regression),
    )
    prior_gates = {
        "G0-frozen-input-and-validity": g0,
        "G1-original-v5-G0-G6-unchanged": {
            "passed": original_development_summary["passed"]
            and original_regression["passed"],
            "components": {
                "development": original_development_summary,
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
    classification = v8_gate._load(v8_gate.CLASSIFICATION_PATH)
    gates = {
        "G0-frozen-input-validity-and-zero-calls": g0,
        "G1-v7-behavioral-gates-not-weakened": g1,
        "G2-three-class-resolution": v8_gate._safe_gate(
            "G2-three-class-resolution",
            lambda: v8_gate._three_class_gate(classification, development, regression),
        ),
        "G3-v5-mechanism-preservation": g3,
        "G4-E9-residual-preservation": g4,
        "G5-control-preservation": g5,
        "G6-legacy-effective-exact": g6,
        "G7-projection-regression-exact": g7,
        "G8-revealed-external-non-regression": g8,
        "G9-selector-and-test-audit": v8_gate._safe_gate(
            "G9-selector-and-test-audit",
            lambda: v8_gate._audit_gate(tests, development, regression),
        ),
    }

    generated_at = datetime.now(UTC).isoformat()
    offline_report = {
        "report_version": "unified-jd-structured-span-v8-frozen-raw-offline-gates-v1",
        "generated_at": generated_at,
        "status": "non_authoritative_offline_reconstruction_after_frozen_evaluator_aggregation_failure",
        "method": {
            "parser_executed": False,
            "predictions_regenerated": False,
            "frozen_raw_only": True,
            "gate_functions": "frozen v5-v8 evaluator helpers",
            "aggregation_correction": (
                "Summarize the mapping returned by _build_development_gates with "
                "all(component.passed) before combining it with the regression gate."
            ),
            "threshold_or_operator_changes": False,
        },
        "inputs": {
            "preregistration": _reference(v8_gate.PREREGISTRATION_PATH),
            "source_freeze": _reference(v8_gate.SOURCE_FREEZE_PATH),
            "development_raw": _reference(v8_gate.DEVELOPMENT_RAW_PATH),
            "regression_raw": _reference(v8_gate.REGRESSION_RAW_PATH),
        },
        "development_metrics": v5_gate._metric_snapshot(development_report),
        "gates": gates,
        "gate_passed": all(value["passed"] for value in gates.values()),
        "canonicalizer_allowed": False,
    }
    _write_new(OFFLINE_REPORT_PATH, offline_report)

    official_outputs = {
        _relative(path): path.exists()
        for path in (
            v8_gate.REPORT_PATH,
            v8_gate.FINDINGS_PATH,
            v8_gate.RECEIPT_PATH,
        )
    }
    postmortem = {
        "postmortem_version": "unified-jd-structured-span-v8-one-time-execution-postmortem-v1",
        "generated_at": generated_at,
        "status": "one_time_execution_failed_after_raw_write_before_report_write",
        "exception": {
            "type": "KeyError",
            "message": "'passed'",
            "location": ("scripts/evaluate_unified_structured_span_v8_gates.py:898"),
            "cause": (
                "_build_development_gates returns a mapping of five gates without "
                "a top-level passed field, but main indexed original_development['passed']."
            ),
        },
        "immutability": {
            "v8_parser_modified_after_freeze": False,
            "v8_tests_modified_after_freeze": False,
            "v8_evaluator_modified_after_freeze": False,
            "v8_rerun_performed": False,
        },
        "preserved_raw": {
            "development": _reference(v8_gate.DEVELOPMENT_RAW_PATH),
            "regression": _reference(v8_gate.REGRESSION_RAW_PATH),
        },
        "official_outputs_present": official_outputs,
        "offline_gate_reconstruction": _reference(OFFLINE_REPORT_PATH),
        "offline_gate_passed": offline_report["gate_passed"],
        "canonicalizer_allowed": False,
    }
    _write_new(POSTMORTEM_PATH, postmortem)

    print(
        json.dumps(
            {
                "postmortem": _reference(POSTMORTEM_PATH),
                "offline_report": _reference(OFFLINE_REPORT_PATH),
                "gates": {name: result["passed"] for name, result in gates.items()},
                "gate_passed": offline_report["gate_passed"],
                "canonicalizer_allowed": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
