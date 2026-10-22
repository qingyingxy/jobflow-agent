from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts import unified_structured_span_v8_residual_oracle_common as common

ROOT = Path(__file__).resolve().parents[1]
DATE = "2026-09-05"
EXPERIMENT_ID = "E12-S2-admission-control-oracle"
SOURCE_FREEZE_PATH = (
    ROOT
    / f"datasets/unified_jd_structured_span_v8_e12_s2_admission_control_oracle_source_freeze_v1_{DATE}.json"
)
RAW_PATH = (
    ROOT
    / f"artifacts/evaluation/unified-jd-structured-span-v8-e12-s2-admission-control-oracle-raw-v1-{DATE}.json"
)
REPORT_PATH = (
    ROOT
    / f"artifacts/evaluation/unified-jd-structured-span-v8-e12-s2-admission-control-oracle-report-v1-{DATE}.json"
)
FINDINGS_PATH = (
    ROOT
    / f"artifacts/evaluation/unified-jd-structured-span-v8-e12-s2-admission-control-oracle-findings-v1-{DATE}.md"
)
OUTPUT_PATHS = (RAW_PATH, REPORT_PATH, FINDINGS_PATH)
RUNNER_PATH = Path(__file__).resolve()
COMMON_PATH = Path(common.__file__).resolve()
S2_OBSERVABLE_FAMILIES = (
    "item_candidate_spans",
    "surface_projection",
    "example_projection",
)


def _preflight() -> dict[str, dict[str, Any]]:
    inputs = common.validate_frozen_inputs()
    common.validate_source_freeze(SOURCE_FREEZE_PATH, EXPERIMENT_ID)
    audit = common.static_import_audit((COMMON_PATH, RUNNER_PATH))
    if not audit["passed"]:
        raise ValueError(f"parser import audit failed: {audit}")
    plan = common.experiment_plan(inputs["preregistration"], EXPERIMENT_ID)
    if len(plan["false_admission_targets"]) != 2:
        raise ValueError("E12 false-admission target count changed")
    if len(plan["positive_admission_controls"]) != 5:
        raise ValueError("E12 positive-admission control count changed")
    existing = [common.relative(path) for path in OUTPUT_PATHS if path.exists()]
    if existing:
        raise FileExistsError(f"one-time E12 output already exists: {existing}")
    return inputs


def _snapshot(record: dict[str, Any], cohort: str) -> dict[str, Any]:
    if cohort == "projection-60":
        return common.projection_snapshot(record)
    return common.full_snapshot(record)


def _projection_exact(record: dict[str, Any]) -> bool:
    return common.projection_snapshot(record) == common.projection_snapshot(
        record, expected=True
    )


def _baseline_exact(
    inputs: dict[str, dict[str, Any]], cohort: str, record_id: str
) -> bool:
    if cohort == "projection-60":
        return bool(
            common.regression_record(inputs["v8_regression"], cohort, record_id)[
                "exact"
            ]
        )
    gate = inputs["v8_offline_report"]["gates"]["G6-legacy-effective-exact"]
    return bool(gate["fixtures"][record_id]["passed"])


def _denied_record(
    baseline: dict[str, Any], reference: dict[str, Any], cohort: str
) -> dict[str, Any]:
    if cohort == "projection-60":
        return reference
    baseline_graph = common.normalize_graph(baseline["parsed_clause"])
    reference_graph = common.normalize_graph(reference["parsed_clause"])
    denied_graph = common.replace_family(
        baseline_graph, reference_graph, "item_candidates"
    )
    return common.record_from_graph(
        baseline, denied_graph, "offline.E12.S2-denied-to-v6"
    )


def _denied_exact(
    inputs: dict[str, dict[str, Any]], cohort: str, record_id: str
) -> bool:
    v6_record = common.regression_record(inputs["v6_regression"], cohort, record_id)
    if cohort == "projection-60":
        return _projection_exact(v6_record)
    unresolved_v6_ids = {
        record["evidence_record_id"]
        for record in inputs["e9_signal"]["record_evidence"]
    }
    return record_id not in unresolved_v6_ids


def _run(inputs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    plan = common.experiment_plan(inputs["preregistration"], EXPERIMENT_ID)
    input_hashes_before = {
        "v8_development": common.json_sha256(inputs["v8_development"]),
        "v8_regression": common.json_sha256(inputs["v8_regression"]),
        "v6_regression": common.json_sha256(inputs["v6_regression"]),
        "v7_regression": common.json_sha256(inputs["v7_regression"]),
    }
    false_targets: list[dict[str, Any]] = []
    for target in plan["false_admission_targets"]:
        cohort = target["cohort"]
        record_id = target["id"]
        baseline_record = common.regression_record(
            inputs["v8_regression"], cohort, record_id
        )
        v6_record = common.regression_record(inputs["v6_regression"], cohort, record_id)
        denied_record = _denied_record(baseline_record, v6_record, cohort)
        baseline = _snapshot(baseline_record, cohort)
        v6 = _snapshot(v6_record, cohort)
        denied = _snapshot(denied_record, cohort)
        relevant = {
            family
            for family in S2_OBSERVABLE_FAMILIES
            if family in baseline and family in v6
        }
        held_fixed = sorted(set(baseline) - relevant)
        false_targets.append(
            {
                "cohort": cohort,
                "id": record_id,
                "frozen_v8_admitted": baseline,
                "frozen_v6_denied_reference": v6,
                "deny_all_S2": denied,
                "oracle_binary_admission": denied,
                "relevant_families": sorted(relevant),
                "held_fixed_families": held_fixed,
                "held_fixed_families_unchanged": all(
                    denied[family] == baseline[family] for family in held_fixed
                ),
                "restored_to_v6_on_S2_and_projection": all(
                    denied[family] == v6[family] for family in relevant
                ),
            }
        )

    positive_controls: list[dict[str, Any]] = []
    for control in plan["positive_admission_controls"]:
        cohort = control["cohort"]
        record_id = control["id"]
        baseline_record = common.regression_record(
            inputs["v8_regression"], cohort, record_id
        )
        v6_record = common.regression_record(inputs["v6_regression"], cohort, record_id)
        denied_record = _denied_record(baseline_record, v6_record, cohort)
        baseline = _snapshot(baseline_record, cohort)
        denied = _snapshot(denied_record, cohort)
        positive_controls.append(
            {
                "cohort": cohort,
                "id": record_id,
                "frozen_v8_admitted": baseline,
                "deny_all_S2": denied,
                "oracle_binary_admission": baseline,
                "baseline_exact": _baseline_exact(inputs, cohort, record_id),
                "deny_all_exact": _denied_exact(inputs, cohort, record_id),
                "oracle_binary_exact": _baseline_exact(inputs, cohort, record_id),
                "oracle_binary_byte_identical_to_v8": True,
            }
        )

    boundary = plan["boundary_case"]
    boundary_id = boundary["id"]
    boundary_cohort = boundary["cohort"]
    boundary_v8 = common.regression_record(
        inputs["v8_regression"], boundary_cohort, boundary_id
    )
    boundary_v6 = common.regression_record(
        inputs["v6_regression"], boundary_cohort, boundary_id
    )
    boundary_v7 = common.regression_record(
        inputs["v7_regression"], boundary_cohort, boundary_id
    )
    boundary_result = {
        "cohort": boundary_cohort,
        "id": boundary_id,
        "frozen_v8_admitted": common.projection_snapshot(boundary_v8),
        "frozen_v6_denied": common.projection_snapshot(boundary_v6),
        "frozen_v7_minimal_S2": common.projection_snapshot(boundary_v7),
        "reference": common.projection_snapshot(boundary_v8, expected=True),
        "frozen_v8_admitted_exact": _projection_exact(boundary_v8),
        "frozen_v6_denied_exact": _projection_exact(boundary_v6),
        "frozen_v7_minimal_S2_exact": _projection_exact(boundary_v7),
        "oracle_binary_admission_exact": _projection_exact(boundary_v8),
    }

    population = {
        (item["cohort"], item["id"])
        for item in (
            *plan["false_admission_targets"],
            *plan["positive_admission_controls"],
            plan["boundary_case"],
        )
    }
    non_s2: list[dict[str, str]] = []
    cohort_keys = {
        "legacy-20": "legacy_development",
        "revealed-external-20": "revealed_external",
        "projection-60": "projection_60",
    }
    for cohort, key in cohort_keys.items():
        for record in inputs["v8_regression"][key]["records"]:
            if (cohort, record["id"]) not in population:
                non_s2.append(
                    {
                        "cohort": cohort,
                        "id": record["id"],
                        "payload_sha256": common.json_sha256(record),
                    }
                )
    input_hashes_after = {
        "v8_development": common.json_sha256(inputs["v8_development"]),
        "v8_regression": common.json_sha256(inputs["v8_regression"]),
        "v6_regression": common.json_sha256(inputs["v6_regression"]),
        "v7_regression": common.json_sha256(inputs["v7_regression"]),
    }
    return {
        "raw_version": "unified-jd-structured-span-v8-e12-s2-admission-control-oracle-raw-v1",
        "created_at": datetime.now(UTC).isoformat(),
        "status": "revealed_frozen_raw_causal_oracle",
        "experiment_id": EXPERIMENT_ID,
        "baseline": "frozen_v8_regression_raw_independently_reloaded",
        "arms": plan["arms"],
        "parser_imported_or_executed": False,
        "other_oracle_output_loaded": False,
        "model_call_count": 0,
        "network_call_count": 0,
        "input_payload_hashes_before": input_hashes_before,
        "input_payload_hashes_after": input_hashes_after,
        "false_admission_targets": false_targets,
        "positive_admission_controls": positive_controls,
        "boundary_case": boundary_result,
        "excluded_E11_records": plan["excluded_and_held_fixed_E11_records"],
        "non_S2_regression_anchors": non_s2,
    }


def _report(inputs: dict[str, dict[str, Any]], raw: dict[str, Any]) -> dict[str, Any]:
    restored = sum(
        record["restored_to_v6_on_S2_and_projection"]
        for record in raw["false_admission_targets"]
    )
    positives = sum(
        record["oracle_binary_exact"] and record["oracle_binary_byte_identical_to_v8"]
        for record in raw["positive_admission_controls"]
    )
    deny_all_positives = sum(
        record["deny_all_exact"] for record in raw["positive_admission_controls"]
    )
    held_fixed = (
        all(
            record["held_fixed_families_unchanged"]
            for record in raw["false_admission_targets"]
        )
        and raw["input_payload_hashes_before"] == raw["input_payload_hashes_after"]
    )
    offline = (
        not raw["parser_imported_or_executed"]
        and not raw["other_oracle_output_loaded"]
        and raw["model_call_count"] == raw["network_call_count"] == 0
    )
    discrimination_checks = {
        "false_admissions_restored_2_of_2": {
            "passed": restored == 2,
            "actual": restored,
            "requirement": 2,
        },
        "positive_admissions_retained_5_of_5": {
            "passed": positives == 5,
            "actual": positives,
            "requirement": 5,
        },
        "held_fixed_payloads_unchanged": {
            "passed": held_fixed and len(raw["non_S2_regression_anchors"]) == 92,
            "actual": {
                "held_fixed_families_unchanged": held_fixed,
                "non_S2_regression_count": len(raw["non_S2_regression_anchors"]),
            },
            "requirement": {
                "held_fixed_families_unchanged": True,
                "non_S2_regression_count": 92,
            },
        },
        "execution_offline_and_independent": {
            "passed": offline,
            "actual": {
                "parser_imported_or_executed": raw["parser_imported_or_executed"],
                "other_oracle_output_loaded": raw["other_oracle_output_loaded"],
                "model_call_count": raw["model_call_count"],
                "network_call_count": raw["network_call_count"],
            },
            "requirement": "all false or zero",
        },
    }
    discrimination_accepted = all(
        check["passed"] for check in discrimination_checks.values()
    )
    boundary_exact = raw["boundary_case"]["oracle_binary_admission_exact"]
    full_sufficiency = discrimination_accepted and boundary_exact
    resolved_regressions = restored + int(boundary_exact)
    plan = common.experiment_plan(inputs["preregistration"], EXPERIMENT_ID)
    return {
        "report_version": "unified-jd-structured-span-v8-e12-s2-admission-control-oracle-report-v1",
        "created_at": datetime.now(UTC).isoformat(),
        "scope": {
            "status": "revealed_frozen_raw_causal_oracle",
            "generalization_claim": False,
            "production_rule_claim": False,
            "v8_modified_or_rerun": False,
            "parser_imported_or_executed": False,
            "model_call_count": 0,
            "network_call_count": 0,
        },
        "inputs": {
            "preregistration": {
                "path": common.relative(common.PREREGISTRATION_PATH),
                "sha256": common.sha256(common.PREREGISTRATION_PATH),
            },
            "source_freeze": {
                "path": common.relative(SOURCE_FREEZE_PATH),
                "sha256": common.sha256(SOURCE_FREEZE_PATH),
            },
            "raw": {
                "path": common.relative(RAW_PATH),
                "sha256": common.sha256(RAW_PATH),
            },
        },
        "registered_hypothesis": plan["hypothesis"],
        "registered_intervention": plan["intervention"],
        "discrimination_checks": discrimination_checks,
        "discrimination_accepted": discrimination_accepted,
        "full_sufficiency": full_sufficiency,
        "resolved_S2_associated_regression_count": resolved_regressions,
        "required_for_full_sufficiency": 3,
        "deny_all_positive_exact_count": deny_all_positives,
        "boundary_case": raw["boundary_case"],
        "conclusion": (
            "Binary S2 admission is sufficient for all three associated regressions."
            if full_sufficiency
            else (
                "S2 admission discrimination is supported for two of three associated regressions, but binary admission is not fully sufficient."
                if discrimination_accepted
                else "S2 admission discrimination is not supported under the frozen E12 gate."
            )
        ),
        "next_required_oracle": (
            None
            if full_sufficiency or not discrimination_accepted
            else "selection-envelope-versus-producer-projection-closure"
        ),
        "interpretation_limit": plan["interpretation_limit"],
    }


def _findings(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# E12 S2 admission-control oracle",
            "",
            "## Result",
            "",
            f"- Discrimination gate: **{'accepted' if report['discrimination_accepted'] else 'rejected'}**.",
            f"- Full sufficiency: **{'accepted' if report['full_sufficiency'] else 'rejected'}**.",
            f"- S2-associated regressions resolved: `{report['resolved_S2_associated_regression_count']}/3`.",
            f"- Positive S2 cases exact under deny-all: `{report['deny_all_positive_exact_count']}/5`.",
            "- Parser, model, and network calls: `0`.",
            "",
            "## Interpretation",
            "",
            report["conclusion"],
            report["interpretation_limit"],
            "",
        ]
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run frozen offline E12 once")
    parser.add_argument("--preflight", action="store_true")
    return parser.parse_args()


def main() -> int:
    arguments = _parse_args()
    inputs = _preflight()
    if arguments.preflight:
        print("E12 preflight passed; E10 and E11 outputs were not loaded")
        return 0
    raw = _run(inputs)
    common.write_new_json(RAW_PATH, raw)
    report = _report(inputs, raw)
    common.write_new_json(REPORT_PATH, report)
    common.write_new_text(FINDINGS_PATH, _findings(report))
    print(
        f"E12 discrimination={report['discrimination_accepted']} "
        f"full_sufficiency={report['full_sufficiency']} "
        f"resolved={report['resolved_S2_associated_regression_count']}/3"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
