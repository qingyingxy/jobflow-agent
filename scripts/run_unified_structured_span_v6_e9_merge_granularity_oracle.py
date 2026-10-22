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
    / f"artifacts/evaluation/unified-jd-structured-span-v6-e9-region-versus-node-family-merge-oracle-raw-v1-{DATE}.json"
)
REPORT_PATH = (
    ROOT
    / f"artifacts/evaluation/unified-jd-structured-span-v6-e9-region-versus-node-family-merge-oracle-report-v1-{DATE}.json"
)
FINDINGS_PATH = (
    ROOT
    / f"artifacts/evaluation/unified-jd-structured-span-v6-e9-region-versus-node-family-merge-oracle-findings-v1-{DATE}.md"
)
E8_OUTPUT_PATH = (
    ROOT
    / f"artifacts/evaluation/unified-jd-structured-span-v6-e8-attachment-replacement-activation-veto-oracle-raw-v1-{DATE}.json"
)
OUTPUT_PATHS = (RAW_PATH, REPORT_PATH, FINDINGS_PATH)


def _preflight() -> dict[str, dict[str, Any]]:
    inputs = common.load_frozen_inputs()
    common.validate_source_freeze()
    common.validate_population(inputs)
    existing = [common.relative(path) for path in OUTPUT_PATHS if path.exists()]
    if existing:
        raise FileExistsError(f"one-time E9 output already exists: {existing}")
    return inputs


def _node_family_arm(
    baseline: dict[str, Any], reference: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, str]]:
    result: dict[str, Any] = {}
    origins: dict[str, str] = {}
    for family in sorted(baseline):
        if baseline[family] == reference[family]:
            result[family] = deepcopy(baseline[family])
            origins[family] = "v6"
        else:
            result[family] = deepcopy(reference[family])
            origins[family] = "v4_compatible_reference"
    return result, origins


def _run(inputs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    targets = inputs["preregistration"]["population"]["target_observations"]
    for target in targets:
        baseline, reference = common.target_snapshots(
            inputs, target["cohort"], target["id"]
        )
        node_family, origins = _node_family_arm(baseline, reference)
        mismatches = common.mismatched_families(baseline, reference)
        exact_families = sorted(set(baseline) - set(mismatches))
        records.append(
            {
                **target,
                "frozen_v6_region_level": baseline,
                "v4_whole_region_fallback_oracle": deepcopy(reference),
                "node_family_selection_oracle": node_family,
                "reference": reference,
                "baseline_mismatched_families": mismatches,
                "node_family_origins": origins,
                "already_exact_v6_families": exact_families,
                "node_family_retains_every_exact_v6_family": all(
                    node_family[family] == baseline[family] and origins[family] == "v6"
                    for family in exact_families
                ),
                "region_level_resolved": common.snapshot_exact(baseline, reference),
                "whole_region_fallback_resolved": True,
                "node_family_resolved": common.snapshot_exact(node_family, reference),
                "whole_region_selected_family_count": len(reference),
                "node_family_changed_family_count": len(mismatches),
                "node_family_retained_v6_family_count": len(exact_families),
            }
        )
    return {
        "raw_version": "unified-jd-structured-span-v6-e9-region-versus-node-family-merge-oracle-raw-v1",
        "created_at": datetime.now(UTC).isoformat(),
        "status": "revealed_frozen_raw_causal_oracle",
        "experiment_id": "E9-region-versus-node-family-merge-oracle",
        "baseline": "frozen_v6_regression_raw_independently_reloaded",
        "arms": [
            "frozen_v6_region_level",
            "v4_whole_region_fallback_oracle",
            "node_family_selection_oracle",
        ],
        "fixture_count": len(records),
        "parser_executed": False,
        "v6_imported": False,
        "e8_output_path_exists_but_not_loaded": E8_OUTPUT_PATH.exists(),
        "e8_output_loaded": False,
        "model_call_count": 0,
        "network_call_count": 0,
        "records": records,
        "controls": common.control_anchors(inputs),
    }


def _report(inputs: dict[str, dict[str, Any]], raw: dict[str, Any]) -> dict[str, Any]:
    records = raw["records"]
    region_resolved = sum(record["region_level_resolved"] for record in records)
    fallback_resolved = sum(
        record["whole_region_fallback_resolved"] for record in records
    )
    family_resolved = sum(record["node_family_resolved"] for record in records)
    retains_exact = all(
        record["node_family_retains_every_exact_v6_family"] for record in records
    )
    family_count_guard = all(
        record["node_family_changed_family_count"]
        <= record["whole_region_selected_family_count"]
        for record in records
    )
    controls_unchanged = len(raw["controls"]) == 22 and all(
        control["baseline_resolved"] for control in raw["controls"]
    )
    offline = bool(
        not raw["parser_executed"]
        and not raw["v6_imported"]
        and not raw["e8_output_loaded"]
        and raw["model_call_count"] == raw["network_call_count"] == 0
    )
    checks = {
        "node_family_targets_exact_9_of_9": {
            "passed": family_resolved == 9,
            "actual": family_resolved,
            "requirement": 9,
        },
        "already_exact_v6_families_retained": {
            "passed": retains_exact,
            "actual": retains_exact,
            "requirement": True,
        },
        "node_family_changes_no_more_than_whole_region": {
            "passed": family_count_guard,
            "actual": family_count_guard,
            "requirement": True,
        },
        "controls_byte_identical_22_of_22": {
            "passed": controls_unchanged,
            "actual": len(raw["controls"]),
            "requirement": 22,
        },
        "execution_is_offline_and_independent": {
            "passed": offline,
            "actual": {
                "parser_executed": raw["parser_executed"],
                "v6_imported": raw["v6_imported"],
                "e8_output_loaded": raw["e8_output_loaded"],
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
        "report_version": "unified-jd-structured-span-v6-e9-region-versus-node-family-merge-oracle-report-v1",
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
        "resolved_target_count_by_arm": {
            "frozen_v6_region_level": region_resolved,
            "v4_whole_region_fallback_oracle": fallback_resolved,
            "node_family_selection_oracle": family_resolved,
        },
        "changed_family_count": {
            "whole_region_selected": sum(
                record["whole_region_selected_family_count"] for record in records
            ),
            "node_family_changed": sum(
                record["node_family_changed_family_count"] for record in records
            ),
            "node_family_retained_v6": sum(
                record["node_family_retained_v6_family_count"] for record in records
            ),
        },
        "records": [
            {
                "cohort": record["cohort"],
                "id": record["id"],
                "classification": record["classification"],
                "baseline_mismatched_families": record["baseline_mismatched_families"],
                "node_family_retained_v6_family_count": record[
                    "node_family_retained_v6_family_count"
                ],
                "node_family_resolved": record["node_family_resolved"],
            }
            for record in records
        ],
        "conclusion": (
            "Node-family selection is sufficient for all nine residual observations while preserving every already-exact observable v6 family."
            if accepted
            else "Node-family selection is not sufficient under the frozen E9 gate."
        ),
        "interpretation_limit": plan["interpretation_limit"],
    }


def _findings(report: dict[str, Any]) -> str:
    counts = report["resolved_target_count_by_arm"]
    families = report["changed_family_count"]
    return "\n".join(
        [
            "# E9 region versus node-family merge oracle",
            "",
            "## Result",
            "",
            f"- Frozen gate: **{'accepted' if report['accepted'] else 'rejected'}**.",
            f"- Frozen v6 region-level baseline: `{counts['frozen_v6_region_level']}/9` exact.",
            f"- Whole-region v4 fallback oracle: `{counts['v4_whole_region_fallback_oracle']}/9` exact.",
            f"- Node-family selection oracle: `{counts['node_family_selection_oracle']}/9` exact.",
            f"- Node families changed: `{families['node_family_changed']}`; already-correct v6 families retained: `{families['node_family_retained_v6']}`.",
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
    parser = argparse.ArgumentParser(description="Run frozen offline E9 exactly once")
    parser.add_argument("--preflight", action="store_true")
    return parser.parse_args()


def main() -> int:
    arguments = _parse_args()
    inputs = _preflight()
    if arguments.preflight:
        print("E9 preflight passed; E8 output was not loaded")
        return 0
    raw = _run(inputs)
    common.write_new_json(RAW_PATH, raw)
    report = _report(inputs, raw)
    common.write_new_json(REPORT_PATH, report)
    common.write_new_text(FINDINGS_PATH, _findings(report))
    print(
        f"E9 accepted={report['accepted']} "
        f"region={report['resolved_target_count_by_arm']['frozen_v6_region_level']}/9 "
        f"node_family={report['resolved_target_count_by_arm']['node_family_selection_oracle']}/9"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
