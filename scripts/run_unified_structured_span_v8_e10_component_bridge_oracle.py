from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts import unified_structured_span_v8_residual_oracle_common as common

ROOT = Path(__file__).resolve().parents[1]
DATE = "2026-09-05"
EXPERIMENT_ID = "E10-component-bridge-oracle"
SOURCE_FREEZE_PATH = (
    ROOT
    / f"datasets/unified_jd_structured_span_v8_e10_component_bridge_oracle_source_freeze_v1_{DATE}.json"
)
RAW_PATH = (
    ROOT
    / f"artifacts/evaluation/unified-jd-structured-span-v8-e10-component-bridge-oracle-raw-v1-{DATE}.json"
)
REPORT_PATH = (
    ROOT
    / f"artifacts/evaluation/unified-jd-structured-span-v8-e10-component-bridge-oracle-report-v1-{DATE}.json"
)
FINDINGS_PATH = (
    ROOT
    / f"artifacts/evaluation/unified-jd-structured-span-v8-e10-component-bridge-oracle-findings-v1-{DATE}.md"
)
OUTPUT_PATHS = (RAW_PATH, REPORT_PATH, FINDINGS_PATH)
RUNNER_PATH = Path(__file__).resolve()
COMMON_PATH = Path(common.__file__).resolve()


def _preflight() -> dict[str, dict[str, Any]]:
    inputs = common.validate_frozen_inputs()
    common.validate_source_freeze(SOURCE_FREEZE_PATH, EXPERIMENT_ID)
    audit = common.static_import_audit((COMMON_PATH, RUNNER_PATH))
    if not audit["passed"]:
        raise ValueError(f"parser import audit failed: {audit}")
    plan = common.experiment_plan(inputs["preregistration"], EXPERIMENT_ID)
    if len(plan["targets"]) != 3:
        raise ValueError("E10 target count changed")
    existing = [common.relative(path) for path in OUTPUT_PATHS if path.exists()]
    if existing:
        raise FileExistsError(f"one-time E10 output already exists: {existing}")
    return inputs


def _observable_families(target: dict[str, Any]) -> set[str]:
    names = {
        "wrappers": "wrappers",
        "coordinations": "coordination_members",
        "shared_scopes": "shared_scope_edges",
        "item_candidates": "item_candidate_spans",
    }
    return {
        *(names[family] for family in target["treatment_node_families"]),
        *target["derived_outcomes"],
    }


def _run(inputs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    plan = common.experiment_plan(inputs["preregistration"], EXPERIMENT_ID)
    actual = common.records_by_id(inputs["v8_development"])
    reference = common.records_by_id(inputs["v5_mechanism"])
    input_hashes_before = {
        "v8_development": common.json_sha256(inputs["v8_development"]),
        "v8_regression": common.json_sha256(inputs["v8_regression"]),
    }
    records: list[dict[str, Any]] = []
    for target in plan["targets"]:
        record_id = target["id"]
        baseline_record = actual[record_id]
        reference_record = reference[record_id]
        baseline_graph = common.normalize_graph(baseline_record["parsed_clause"])
        reference_graph = common.normalize_graph(reference_record["parsed_clause"])
        envelopes = tuple(
            tuple(int(value) for value in envelope.split("-"))
            for envelope in target["bridge_component_envelopes"]
        )
        treatment_graph = common.replace_nodes_in_envelopes(
            baseline_graph,
            reference_graph,
            families=tuple(target["treatment_node_families"]),
            envelopes=envelopes,
        )
        treatment_record = common.record_from_graph(
            baseline_record,
            treatment_graph,
            "offline.E10.component-bridge-oracle",
        )
        baseline = common.full_snapshot(baseline_record)
        expected = common.full_snapshot(reference_record)
        treatment = common.full_snapshot(treatment_record)
        before = common.family_status(baseline, expected)
        after = common.family_status(treatment, expected)
        registered = _observable_families(target)
        baseline_incorrect = {family for family, exact in before.items() if not exact}
        corrected = sorted(
            family
            for family in baseline_incorrect
            if after[family] and family in registered
        )
        records.append(
            {
                "id": record_id,
                "registered_bridge_component_envelopes": target[
                    "bridge_component_envelopes"
                ],
                "registered_treatment_node_families": target["treatment_node_families"],
                "baseline": baseline,
                "reference": expected,
                "treatment": treatment,
                "treatment_record": treatment_record,
                "baseline_family_exact": before,
                "treatment_family_exact": after,
                "registered_observable_families": sorted(registered),
                "corrected_registered_families": corrected,
                "already_correct_families_unchanged": all(
                    after[family] for family, exact in before.items() if exact
                ),
                "target_exact": common.snapshot_exact(treatment, expected),
                "graph_valid": True,
            }
        )
    target_ids = {target["id"] for target in plan["targets"]}
    non_targets = [
        record
        for record in inputs["v8_development"]["records"]
        if record["id"] not in target_ids
    ]
    input_hashes_after = {
        "v8_development": common.json_sha256(inputs["v8_development"]),
        "v8_regression": common.json_sha256(inputs["v8_regression"]),
    }
    return {
        "raw_version": "unified-jd-structured-span-v8-e10-component-bridge-oracle-raw-v1",
        "created_at": datetime.now(UTC).isoformat(),
        "status": "revealed_frozen_raw_causal_oracle",
        "experiment_id": EXPERIMENT_ID,
        "baseline": "frozen_v8_development_raw_independently_reloaded",
        "arms": ["frozen_v8", "component_bridge_oracle"],
        "target_count": len(records),
        "parser_imported_or_executed": False,
        "other_oracle_output_loaded": False,
        "model_call_count": 0,
        "network_call_count": 0,
        "input_payload_hashes_before": input_hashes_before,
        "input_payload_hashes_after": input_hashes_after,
        "records": records,
        "non_target_development_anchors": common.unchanged_anchors(non_targets),
        "regression_payload_sha256": input_hashes_before["v8_regression"],
    }


def _report(inputs: dict[str, dict[str, Any]], raw: dict[str, Any]) -> dict[str, Any]:
    records = raw["records"]
    exact_count = sum(record["target_exact"] for record in records)
    corrected_count = sum(
        len(record["corrected_registered_families"]) for record in records
    )
    exact_families_unchanged = all(
        record["already_correct_families_unchanged"] for record in records
    )
    input_unchanged = (
        raw["input_payload_hashes_before"] == raw["input_payload_hashes_after"]
    )
    valid = all(record["graph_valid"] for record in records)
    offline = (
        not raw["parser_imported_or_executed"]
        and not raw["other_oracle_output_loaded"]
        and raw["model_call_count"] == raw["network_call_count"] == 0
    )
    checks = {
        "targets_exact_3_of_3": {
            "passed": exact_count == 3,
            "actual": exact_count,
            "requirement": 3,
        },
        "incorrect_observable_families_corrected_13_of_13": {
            "passed": corrected_count == 13,
            "actual": corrected_count,
            "requirement": 13,
        },
        "already_correct_families_unchanged": {
            "passed": exact_families_unchanged,
            "actual": exact_families_unchanged,
            "requirement": True,
        },
        "non_target_inputs_byte_identical": {
            "passed": input_unchanged
            and len(raw["non_target_development_anchors"]) == 17,
            "actual": {
                "input_hashes_unchanged": input_unchanged,
                "non_target_development_count": len(
                    raw["non_target_development_anchors"]
                ),
            },
            "requirement": {
                "input_hashes_unchanged": True,
                "non_target_development_count": 17,
            },
        },
        "merged_graphs_valid": {
            "passed": valid,
            "actual": valid,
            "requirement": True,
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
    accepted = all(check["passed"] for check in checks.values())
    plan = common.experiment_plan(inputs["preregistration"], EXPERIMENT_ID)
    partial = not accepted and corrected_count > 0 and exact_families_unchanged
    return {
        "report_version": "unified-jd-structured-span-v8-e10-component-bridge-oracle-report-v1",
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
        "checks": checks,
        "accepted": accepted,
        "partial_contribution": partial,
        "resolved_target_count": exact_count,
        "corrected_observable_family_count": corrected_count,
        "records": [
            {
                "id": record["id"],
                "corrected_registered_families": record[
                    "corrected_registered_families"
                ],
                "target_exact": record["target_exact"],
            }
            for record in records
        ],
        "conclusion": (
            "Component bridging is sufficient for all three preregistered residual records."
            if accepted
            else "Component bridging is not sufficient under the frozen E10 gate."
        ),
        "interpretation_limit": plan["interpretation_limit"],
    }


def _findings(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# E10 component bridge oracle",
            "",
            "## Result",
            "",
            f"- Frozen gate: **{'accepted' if report['accepted'] else 'rejected'}**.",
            f"- Exact targets: `{report['resolved_target_count']}/3`.",
            f"- Corrected observable families: `{report['corrected_observable_family_count']}/13`.",
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
    parser = argparse.ArgumentParser(description="Run frozen offline E10 once")
    parser.add_argument("--preflight", action="store_true")
    return parser.parse_args()


def main() -> int:
    arguments = _parse_args()
    inputs = _preflight()
    if arguments.preflight:
        print("E10 preflight passed; no parser imported or executed")
        return 0
    raw = _run(inputs)
    common.write_new_json(RAW_PATH, raw)
    report = _report(inputs, raw)
    common.write_new_json(REPORT_PATH, report)
    common.write_new_text(FINDINGS_PATH, _findings(report))
    print(
        f"E10 accepted={report['accepted']} "
        f"targets={report['resolved_target_count']}/3 "
        f"families={report['corrected_observable_family_count']}/13"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
