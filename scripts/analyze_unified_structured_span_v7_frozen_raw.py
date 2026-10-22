from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts import evaluate_unified_structured_span_v5_gates as v5_gate
from scripts import evaluate_unified_structured_span_v7_gates as v7_gate
from scripts import unified_structured_span_v6_residual_oracle_common as e9_common
from scripts.evaluate_unified_structured_span_v4_development import evaluate_predictions

ROOT = Path(__file__).resolve().parents[1]
ANALYZER_PATH = Path(__file__).resolve()
EVALUATOR_ERROR = (
    "ValueError: full graph missing for structured-v5-mechanism-dev-v1-012"
)


def _safe_gate(name: str, callback: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        return callback()
    except Exception as error:  # noqa: BLE001 - preserve an offline gate failure
        return {
            "passed": False,
            "aggregation_error": f"{type(error).__name__}: {error}",
            "gate": name,
        }


def _safe_mechanism_gate(
    development: dict[str, Any], reference: dict[str, Any]
) -> dict[str, Any]:
    actual = v7_gate._record_by_id(development)
    expected = v7_gate._record_by_id(reference)
    fixtures: dict[str, Any] = {}
    for fixture_id in sorted(expected):
        record = actual[fixture_id]
        if record["parsed_clause"] is None:
            families = {family: False for family in v7_gate.EXACT_FAMILIES}
            fixtures[fixture_id] = {
                "passed": False,
                "families": families,
                "error": record["error"],
            }
            continue
        actual_snapshot = e9_common.full_snapshot(record)
        reference_snapshot = e9_common.full_snapshot(expected[fixture_id])
        families = {
            family: actual_snapshot[family] == reference_snapshot[family]
            for family in v7_gate.EXACT_FAMILIES
        }
        fixtures[fixture_id] = {
            "passed": all(families.values()),
            "families": families,
            "error": None,
        }
    exact_count = sum(value["passed"] for value in fixtures.values())
    return {
        "passed": len(fixtures) == 20 and exact_count == 20,
        "actual": {"fixture_count": len(fixtures), "exact_fixture_count": exact_count},
        "requirement": {"fixture_count": 20, "exact_fixture_count": 20},
        "fixtures": fixtures,
    }


def _findings(report: dict[str, Any]) -> str:
    lines = [
        "# Frozen v7 one-time development and regression gates",
        "",
        "## Outcome",
        "",
        "- Overall gate passed: `false`.",
        "- The single registered parser execution completed and wrote both raw files.",
        "- The frozen evaluator then aborted during report aggregation on a null parse graph.",
        "- This report was recovered offline from the frozen raw; v7 was not imported or rerun.",
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
                "V7 and the one-time results remain frozen. V4 stays the production "
                "reference, canonicalizer work remains locked, and the only permitted "
                "next parser work is offline diagnosis followed by a new preregistration."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    for path in (v7_gate.REPORT_PATH, v7_gate.FINDINGS_PATH, v7_gate.RECEIPT_PATH):
        if path.exists():
            raise FileExistsError(f"offline recovery output already exists: {path}")
    v7_gate._validate_preregistration()
    v7_gate._validate_source_freeze()
    development = v7_gate._load(v7_gate.DEVELOPMENT_RAW_PATH)
    regression = v7_gate._load(v7_gate.REGRESSION_RAW_PATH)
    if development["parser_sha256"] != v7_gate._sha256(v7_gate.V7_PATH):
        raise ValueError("development raw parser hash does not match the source freeze")
    if regression["parser_sha256"] != v7_gate._sha256(v7_gate.V7_PATH):
        raise ValueError("regression raw parser hash does not match the source freeze")

    labels = v7_gate._load(v7_gate.LABELS_PATH)
    development_gold = v5_gate._normalize_mechanism_gold(labels)
    v6_preregistration = v7_gate._load(v7_gate.V6_PREREGISTRATION_PATH)
    legacy_gold = v7_gate.v6_gate._adjudicated_legacy_gold(
        v6_preregistration, v7_gate._load(v7_gate.LEGACY_GOLD_PATH)
    )
    external_gold = v5_gate._normalize_external_gold(
        v7_gate._load(v7_gate.EXTERNAL_DEVELOPMENT_PATH)
    )
    development_report = evaluate_predictions(development_gold, development)
    original_development = _safe_gate(
        "original-v5-development",
        lambda: v5_gate._build_development_gates(
            v7_gate._load(v7_gate.V5_PREREGISTRATION_PATH),
            development_gold,
            development,
            development_report,
        ),
    )
    original_regression = _safe_gate(
        "original-v5-regression",
        lambda: v5_gate._build_regression_gate(
            legacy_gold,
            regression["legacy_development"],
            external_gold,
            regression["revealed_external"],
            regression["projection_60"],
            regression["structured_span_tests"],
        ),
    )
    g0 = _safe_gate(
        "G0-frozen-input-and-validity",
        lambda: v7_gate._validity_gate(development, regression),
    )
    if "aggregation_error" in original_development:
        original_components = {"development": original_development}
    else:
        original_components = original_development
    g1_components = {
        "G0-validity": g0,
        **original_components,
        "G6-regression": original_regression,
    }
    g1 = {
        "passed": all(value["passed"] for value in g1_components.values()),
        "components": g1_components,
    }
    gates = {
        "G0-frozen-input-and-validity": g0,
        "G1-original-v5-G0-G6-unchanged": g1,
        "G2-v5-mechanism-preservation": _safe_mechanism_gate(
            development, v7_gate._load(v7_gate.V5_MECHANISM_RAW_PATH)
        ),
        "G3-e9-residual-runtime-selection": _safe_gate(
            "G3-e9-residual-runtime-selection",
            lambda: v7_gate._e9_residual_gate(regression),
        ),
        "G4-v6-resolved-control-preservation": _safe_gate(
            "G4-v6-resolved-control-preservation",
            lambda: v7_gate._control_gate(regression),
        ),
        "G5-legacy-effective-exact": _safe_gate(
            "G5-legacy-effective-exact",
            lambda: v7_gate._legacy_exact_gate(regression),
        ),
        "G6-projection-regression-exact": v7_gate._projection_gate(regression),
        "G7-revealed-external-non-regression": _safe_gate(
            "G7-revealed-external-non-regression",
            lambda: v7_gate._external_non_regression_gate(external_gold, regression),
        ),
        "G8-tests-and-selector-audit": _safe_gate(
            "G8-tests-and-selector-audit",
            lambda: v7_gate._selector_audit_gate(
                regression["structured_span_tests"], development, regression
            ),
        ),
    }
    report = {
        "report_version": "unified-jd-structured-span-v7-development-regression-report-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "frozen_one_time_execution_failed_report_recovered_offline",
        "execution": {
            "development_run_count": 1,
            "regression_run_count": 1,
            "v7_rerun_for_recovery": False,
            "evaluator_exit_code": 1,
            "evaluator_error": EVALUATOR_ERROR,
            "raw_written_before_abort": True,
            "offline_recovery_analyzer": {
                "path": v7_gate._relative(ANALYZER_PATH),
                "sha256": hashlib.sha256(ANALYZER_PATH.read_bytes()).hexdigest(),
            },
        },
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
                "path": v7_gate._relative(v7_gate.PREREGISTRATION_PATH),
                "sha256": v7_gate._sha256(v7_gate.PREREGISTRATION_PATH),
            },
            "source_freeze": {
                "path": v7_gate._relative(v7_gate.SOURCE_FREEZE_PATH),
                "sha256": v7_gate._sha256(v7_gate.SOURCE_FREEZE_PATH),
            },
            "development_raw": {
                "path": v7_gate._relative(v7_gate.DEVELOPMENT_RAW_PATH),
                "sha256": v7_gate._sha256(v7_gate.DEVELOPMENT_RAW_PATH),
            },
            "regression_raw": {
                "path": v7_gate._relative(v7_gate.REGRESSION_RAW_PATH),
                "sha256": v7_gate._sha256(v7_gate.REGRESSION_RAW_PATH),
            },
        },
        "development_metrics": v5_gate._metric_snapshot(development_report),
        "gates": gates,
        "gate_passed": False,
        "canonicalizer_allowed": False,
    }
    v7_gate._write_new(v7_gate.REPORT_PATH, v7_gate._serialized(report))
    v7_gate._write_new(v7_gate.FINDINGS_PATH, _findings(report))
    receipt = v7_gate._receipt(report)
    receipt.update(
        {
            "status": "one_time_frozen_v7_execution_failed_report_recovered_offline",
            "evaluator_exit_code": 1,
            "evaluator_error": EVALUATOR_ERROR,
            "v7_rerun_for_recovery": False,
            "offline_recovery_analyzer": {
                "path": v7_gate._relative(ANALYZER_PATH),
                "sha256": hashlib.sha256(ANALYZER_PATH.read_bytes()).hexdigest(),
            },
        }
    )
    v7_gate._write_new(v7_gate.RECEIPT_PATH, v7_gate._serialized(receipt))
    print(
        json.dumps(
            {
                "gates": {name: value["passed"] for name, value in gates.items()},
                "gate_passed": False,
                "v7_rerun_for_recovery": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
