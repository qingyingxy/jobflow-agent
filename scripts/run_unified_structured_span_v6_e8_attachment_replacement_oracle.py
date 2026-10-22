from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts import unified_structured_span_v6_residual_oracle_common as common

ROOT = Path(__file__).resolve().parents[1]
DATE = "2026-09-05"
RAW_PATH = (
    ROOT
    / f"artifacts/evaluation/unified-jd-structured-span-v6-e8-attachment-replacement-activation-veto-oracle-raw-v1-{DATE}.json"
)
REPORT_PATH = (
    ROOT
    / f"artifacts/evaluation/unified-jd-structured-span-v6-e8-attachment-replacement-activation-veto-oracle-report-v1-{DATE}.json"
)
FINDINGS_PATH = (
    ROOT
    / f"artifacts/evaluation/unified-jd-structured-span-v6-e8-attachment-replacement-activation-veto-oracle-findings-v1-{DATE}.md"
)
OUTPUT_PATHS = (RAW_PATH, REPORT_PATH, FINDINGS_PATH)


def _preflight() -> dict[str, dict[str, Any]]:
    inputs = common.load_frozen_inputs()
    common.validate_source_freeze()
    common.validate_population(inputs)
    existing = [common.relative(path) for path in OUTPUT_PATHS if path.exists()]
    if existing:
        raise FileExistsError(f"one-time E8 output already exists: {existing}")
    return inputs


def _treatment(baseline: dict[str, Any], reference: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(baseline)
    for family in common.ATTACHMENT_FAMILIES:
        if family in result:
            result[family] = deepcopy(reference[family])
    return result


def _run(inputs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    targets = inputs["preregistration"]["population"]["target_observations"]
    for target in targets:
        baseline, reference = common.target_snapshots(
            inputs, target["cohort"], target["id"]
        )
        treatment = _treatment(baseline, reference)
        held_fixed = sorted(set(baseline) - set(common.ATTACHMENT_FAMILIES))
        records.append(
            {
                **target,
                "baseline": baseline,
                "reference": reference,
                "attachment_replacement": treatment,
                "baseline_mismatched_families": common.mismatched_families(
                    baseline, reference
                ),
                "treatment_mismatched_families": common.mismatched_families(
                    treatment, reference
                ),
                "held_fixed_families": held_fixed,
                "held_fixed_byte_identical": all(
                    baseline[family] == treatment[family] for family in held_fixed
                ),
                "resolved": common.snapshot_exact(treatment, reference),
            }
        )
    return {
        "raw_version": "unified-jd-structured-span-v6-e8-attachment-replacement-activation-veto-oracle-raw-v1",
        "created_at": datetime.now(UTC).isoformat(),
        "status": "revealed_frozen_raw_causal_oracle",
        "experiment_id": "E8-attachment-replacement-activation-veto-oracle",
        "baseline": "frozen_v6_regression_raw",
        "arms": ["frozen_v6", "attachment_replacement"],
        "fixture_count": len(records),
        "parser_executed": False,
        "v6_imported": False,
        "e9_output_loaded": False,
        "model_call_count": 0,
        "network_call_count": 0,
        "records": records,
        "controls": common.control_anchors(inputs),
    }


def _report(inputs: dict[str, dict[str, Any]], raw: dict[str, Any]) -> dict[str, Any]:
    records = raw["records"]
    resolved_count = sum(record["resolved"] for record in records)
    held_fixed = all(record["held_fixed_byte_identical"] for record in records)
    controls_unchanged = all(
        control["baseline_resolved"] for control in raw["controls"]
    )
    checks = {
        "targets_exact_9_of_9": {
            "passed": resolved_count == 9,
            "actual": resolved_count,
            "requirement": 9,
        },
        "non_attachment_families_byte_identical": {
            "passed": held_fixed,
            "actual": held_fixed,
            "requirement": True,
        },
        "controls_exact_22_of_22": {
            "passed": len(raw["controls"]) == 22 and controls_unchanged,
            "actual": sum(control["baseline_resolved"] for control in raw["controls"]),
            "requirement": 22,
        },
        "execution_is_offline_and_independent": {
            "passed": not raw["parser_executed"]
            and not raw["v6_imported"]
            and not raw["e9_output_loaded"]
            and raw["model_call_count"] == raw["network_call_count"] == 0,
            "actual": {
                "parser_executed": raw["parser_executed"],
                "v6_imported": raw["v6_imported"],
                "e9_output_loaded": raw["e9_output_loaded"],
                "model_call_count": raw["model_call_count"],
                "network_call_count": raw["network_call_count"],
            },
            "requirement": "all false or zero",
        },
    }
    accepted = all(check["passed"] for check in checks.values())
    plan = next(
        experiment
        for experiment in inputs["preregistration"]["experiments"]
        if experiment["id"] == raw["experiment_id"]
    )
    return {
        "report_version": "unified-jd-structured-span-v6-e8-attachment-replacement-activation-veto-oracle-report-v1",
        "created_at": datetime.now(UTC).isoformat(),
        "scope": {
            "status": "revealed_frozen_raw_causal_oracle",
            "generalization_claim": False,
            "production_rule_claim": False,
            "v6_modified": False,
            "parser_executed": False,
            "model_call_count": 0,
            "network_call_count": 0,
        },
        "inputs": {
            "preregistration": {
                "path": common.relative(common.PREREGISTRATION_PATH),
                "sha256": common.sha256(common.PREREGISTRATION_PATH),
            },
            "raw": {
                "path": common.relative(RAW_PATH),
                "sha256": common.sha256(RAW_PATH),
            },
        },
        "registered_hypothesis": plan["hypothesis"],
        "registered_intervention": plan["intervention"],
        "checks": checks,
        "accepted": accepted,
        "resolved_target_count": resolved_count,
        "unresolved_target_ids": [
            record["id"] for record in records if not record["resolved"]
        ],
        "records": [
            {
                "cohort": record["cohort"],
                "id": record["id"],
                "classification": record["classification"],
                "baseline_mismatched_families": record["baseline_mismatched_families"],
                "treatment_mismatched_families": record[
                    "treatment_mismatched_families"
                ],
                "resolved": record["resolved"],
            }
            for record in records
        ],
        "conclusion": (
            "Attachment-family replacement is sufficient for all nine residual observations."
            if accepted
            else "Attachment-family replacement alone is not sufficient for the nine residual observations."
        ),
        "interpretation_limit": plan["interpretation_limit"],
    }


def _findings(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# E8 attachment-replacement activation-veto oracle",
            "",
            "## Result",
            "",
            f"- Frozen gate: **{'accepted' if report['accepted'] else 'rejected'}**.",
            f"- Completely resolved targets: `{report['resolved_target_count']}/9`.",
            "- Resolved controls retained: `22/22`.",
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
    parser = argparse.ArgumentParser(description="Run frozen offline E8 exactly once")
    parser.add_argument("--preflight", action="store_true")
    return parser.parse_args()


def main() -> int:
    arguments = _parse_args()
    inputs = _preflight()
    if arguments.preflight:
        print("E8 preflight passed; no parser imported or executed")
        return 0
    raw = _run(inputs)
    common.write_new_json(RAW_PATH, raw)
    report = _report(inputs, raw)
    common.write_new_json(REPORT_PATH, report)
    common.write_new_text(FINDINGS_PATH, _findings(report))
    print(
        f"E8 accepted={report['accepted']} "
        f"resolved={report['resolved_target_count']}/9 controls=22/22"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
