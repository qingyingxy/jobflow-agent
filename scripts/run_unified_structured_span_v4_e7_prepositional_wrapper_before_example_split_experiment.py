from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import (
    run_unified_structured_span_v4_e5_example_attachment_three_toggle_experiment as e5,
)

PARSER_PATH = PROJECT_ROOT / "src/domain/unified_jd_structured_spans_v4.py"
RULES_FREEZE_PATH = (
    PROJECT_ROOT
    / "datasets/unified_jd_structured_span_rules_freeze_v4_2026-09-04.json"
)
DATASET_PATH = (
    PROJECT_ROOT
    / "datasets/unified_jd_structured_span_v4_corpus_external_revealed_development_v1_2026-09-04.json"
)
PREREGISTRATION_PATH = (
    PROJECT_ROOT
    / "datasets/unified_jd_structured_span_v4_residual_experiments_preregistration_v1-2026-09-04.json"
)
E5_RAW_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-e5-example-attachment-three-toggle-raw-v1-2026-09-04.json"
)
E5_REPORT_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-e5-example-attachment-three-toggle-report-v1-2026-09-04.json"
)
BASELINE_RAW_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-corpus-external-raw-v1-2026-09-04.json"
)
RAW_OUTPUT_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-e7-prepositional-wrapper-before-example-split-raw-v1-2026-09-04.json"
)
REPORT_OUTPUT_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-e7-prepositional-wrapper-before-example-split-report-v1-2026-09-04.json"
)
FINDINGS_OUTPUT_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-e7-prepositional-wrapper-before-example-split-findings-v1-2026-09-04.md"
)

EXPECTED_HASHES = {
    PARSER_PATH: "e09e056cab75e651937391ce5410e6df7c94477c85565abb1425bbe85cfcb094",
    RULES_FREEZE_PATH: (
        "6a8a1d9ccce7c1069a483c7cc387221164de52800a133308922d57ff75ad6a12"
    ),
    DATASET_PATH: "965263881ff85bca636aa6ab87adaca24d74183fa13400709133323a3a6d5b73",
    PREREGISTRATION_PATH: (
        "7acfbed9a61ec39c16136604d58b19c8b562dfe43ff256cc789e4e8ff2fb708e"
    ),
    E5_RAW_PATH: "8d38a34ee72aa969f2f04efdc139dc3d0c8c22b262286eb49902cc2ab7bec592",
    E5_REPORT_PATH: (
        "bd12b18f1d6e8e0299e5efb5cb91ec7705f6c6c3c12d687f9ee02a3da13683c8"
    ),
    BASELINE_RAW_PATH: (
        "36b65c1df79d856c7507ae1357ed24c10b7a3e383bad79b9471b124f4999e058"
    ),
}

TARGET_IDS = ("structured-corpus-external-v1-019",)
CONTROL_IDS = (
    "structured-corpus-external-v1-002",
    "structured-corpus-external-v1-005",
    "structured-corpus-external-v1-006",
    "structured-corpus-external-v1-009",
    "structured-corpus-external-v1-018",
)
ARMS = (
    "e5_final_baseline",
    "prepositional_wrapper_before_example_split",
)
LEADING_PREPOSITIONAL_MARKERS = ("对",)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_bytes(
        (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    )


def _relative(path: Path) -> str:
    return path.relative_to(PROJECT_ROOT).as_posix()


def _input(path: Path) -> dict[str, str]:
    return {"path": _relative(path), "sha256": _sha256(path)}


def _span_key(span: dict[str, Any]) -> tuple[int, int, str]:
    return span["start"], span["end"], span["text"]


def _apply_prepositional_boundary_before_split(
    source: str, baseline: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    treatment = copy.deepcopy(baseline)
    events: list[dict[str, Any]] = []
    replacements: dict[tuple[int, int, str], dict[str, Any]] = {}

    for attachment in treatment["attachments"]:
        if not attachment["example_spans"]:
            continue
        first = attachment["example_spans"][0]
        for marker in LEADING_PREPOSITIONAL_MARKERS:
            if not first["text"].startswith(marker):
                continue
            boundary_end = first["start"] + len(marker)
            if source[first["start"] : boundary_end] != marker:
                continue
            updated = {
                "text": source[boundary_end : first["end"]],
                "start": boundary_end,
                "end": first["end"],
            }
            replacements[_span_key(first)] = updated
            attachment["example_spans"][0] = copy.deepcopy(updated)
            events.append(
                {
                    "wrapper_marker_span": {
                        "text": marker,
                        "start": first["start"],
                        "end": boundary_end,
                    },
                    "before_split_span": copy.deepcopy(first),
                    "after_split_span": copy.deepcopy(updated),
                }
            )
            break

    treatment["example_members"] = [
        copy.deepcopy(replacements.get(_span_key(span), span))
        for span in treatment["example_members"]
    ]
    treatment["example_items"] = [
        span["text"] for span in treatment["example_members"]
    ]
    return treatment, events


def _source_record(
    fixture_id: str,
    e5_by_id: dict[str, dict[str, Any]],
    baseline_by_id: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], str]:
    if fixture_id in e5_by_id:
        return copy.deepcopy(e5_by_id[fixture_id]), "stored_e5_final"
    reconstructed = e5._record(baseline_by_id[fixture_id])
    return reconstructed, "reconstructed_e5_final_from_frozen_baseline"


def _record(source_record: dict[str, Any], baseline_origin: str) -> dict[str, Any]:
    baseline = copy.deepcopy(source_record["toggle3_parent_ranked"])
    treatment, events = _apply_prepositional_boundary_before_split(
        source_record["source_text"], baseline
    )
    return {
        "id": source_record["id"],
        "job_id": source_record["job_id"],
        "category": source_record["category"],
        "role": "target" if source_record["id"] in TARGET_IDS else "control",
        "source_text": source_record["source_text"],
        "held_fixed": copy.deepcopy(source_record["held_fixed"]),
        "baseline_origin": baseline_origin,
        "e5_final_baseline_sha256": _json_sha256(baseline),
        "e5_final_baseline": baseline,
        "prepositional_wrapper_before_example_split": treatment,
        "wrapper_boundary_events": events,
    }


def _arm_bytes(arm: dict[str, Any]) -> bytes:
    return json.dumps(arm, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _expected_target_treatment(
    baseline: dict[str, Any], plan: dict[str, Any]
) -> dict[str, Any]:
    expected = copy.deepcopy(baseline)
    observation = plan["baseline"]["target_observation"]
    before = observation["first_example_before"]
    after = observation["first_example_expected"]
    expected["attachments"][0]["example_spans"][0] = copy.deepcopy(after)
    expected["example_members"] = [
        copy.deepcopy(after) if item == before else item
        for item in expected["example_members"]
    ]
    expected["example_items"] = [item["text"] for item in expected["example_members"]]
    return expected


def _build_report(
    plan: dict[str, Any], dataset: dict[str, Any], raw: dict[str, Any]
) -> dict[str, Any]:
    gold_by_id = {item["id"]: item["gold"] for item in dataset["fixtures"]}
    records_by_id = {item["id"]: item for item in raw["records"]}
    target = records_by_id[TARGET_IDS[0]]
    baseline = target["e5_final_baseline"]
    treatment = target["prepositional_wrapper_before_example_split"]
    expected = _expected_target_treatment(baseline, plan)
    target_change_exact = treatment == expected

    target_counts = e5._fixture_counts(gold_by_id[TARGET_IDS[0]], treatment)
    target_layers_exact = all(
        target_counts[layer] == 0
        for layer in (
            "example_members",
            "attachment_edges",
            "example_projection",
        )
    )
    baseline_attachment = baseline["attachments"][0]
    treatment_attachment = treatment["attachments"][0]
    cue_parent_unchanged = (
        treatment_attachment["cue_span"] == baseline_attachment["cue_span"]
        and treatment_attachment["parent_span"] == baseline_attachment["parent_span"]
    )
    control_byte_equality = {
        fixture_id: _arm_bytes(records_by_id[fixture_id]["e5_final_baseline"])
        == _arm_bytes(
            records_by_id[fixture_id][
                "prepositional_wrapper_before_example_split"
            ]
        )
        for fixture_id in CONTROL_IDS
    }
    control_attachment_count_unchanged = {
        fixture_id: len(records_by_id[fixture_id]["e5_final_baseline"]["attachments"])
        == len(
            records_by_id[fixture_id][
                "prepositional_wrapper_before_example_split"
            ]["attachments"]
        )
        for fixture_id in CONTROL_IDS
    }
    controls_unchanged = all(control_byte_equality.values()) and all(
        control_attachment_count_unchanged.values()
    )
    accepted = (
        target_change_exact
        and target_layers_exact
        and cue_parent_unchanged
        and controls_unchanged
    )

    records = []
    for fixture_id in (*TARGET_IDS, *CONTROL_IDS):
        record = records_by_id[fixture_id]
        records.append(
            {
                "id": fixture_id,
                "role": record["role"],
                "baseline_origin": record["baseline_origin"],
                "differences_by_arm": {
                    arm: e5._fixture_counts(gold_by_id[fixture_id], record[arm])
                    for arm in ARMS
                },
                "attachment_count_by_arm": {
                    arm: len(record[arm]["attachments"]) for arm in ARMS
                },
                "whole_arm_byte_identical": _arm_bytes(
                    record["e5_final_baseline"]
                )
                == _arm_bytes(
                    record["prepositional_wrapper_before_example_split"]
                ),
                "wrapper_boundary_events": record["wrapper_boundary_events"],
            }
        )

    return {
        "report_version": (
            "unified-jd-structured-span-v4-e7-prepositional-wrapper-before-"
            "example-split-report-v1"
        ),
        "created_at": "2026-09-04",
        "scope": {
            "status": "revealed_development_causal_experiment",
            "experiment_id": plan["id"],
            "one_time_frozen_gate_decision": True,
            "generalization_claim": False,
            "production_rule_claim": False,
            "threshold_selection_allowed": False,
            "frozen_v4_modified": False,
            "v5_implemented": False,
            "cumulative_treatment": False,
            "e6_treatment_included": False,
            "model_call_count": 0,
            "network_call_count": 0,
        },
        "inputs": {
            "preregistration": _input(PREREGISTRATION_PATH),
            "revealed_development": _input(DATASET_PATH),
            "e5_final_raw": _input(E5_RAW_PATH),
            "e5_report": _input(E5_REPORT_PATH),
            "corpus_external_baseline_raw": _input(BASELINE_RAW_PATH),
            "frozen_v4_source": _input(PARSER_PATH),
            "rules_freeze": _input(RULES_FREEZE_PATH),
            "experiment_raw": _input(RAW_OUTPUT_PATH),
        },
        "independence": {
            "baseline": "E5 toggle3_parent_ranked",
            "e6_output_loaded": False,
            "e6_treatment_included": False,
            "control_006_false_attachment_remains_in_both_arms": (
                len(
                    records_by_id["structured-corpus-external-v1-006"][
                        "e5_final_baseline"
                    ]["attachments"]
                )
                == 1
                and len(
                    records_by_id["structured-corpus-external-v1-006"][
                        "prepositional_wrapper_before_example_split"
                    ]["attachments"]
                )
                == 1
            ),
        },
        "registered_hypothesis": plan["hypothesis"],
        "registered_intervention": plan["intervention"],
        "single_changed_variable": plan["single_changed_variable"],
        "held_fixed": plan["held_fixed"],
        "target_fixture_ids": list(TARGET_IDS),
        "control_fixture_ids": list(CONTROL_IDS),
        "aggregate": {
            "targets": {
                arm: e5._aggregate(TARGET_IDS, gold_by_id, records_by_id, arm)
                for arm in ARMS
            },
            "controls": {
                arm: e5._aggregate(CONTROL_IDS, gold_by_id, records_by_id, arm)
                for arm in ARMS
            },
        },
        "records": records,
        "decision": {
            "accepted": accepted,
            "criterion_1_exact_17_23_to_18_23_only": target_change_exact,
            "criterion_2_target_members_projection_edges_exact": target_layers_exact,
            "criterion_3_cue_and_parent_unchanged": cue_parent_unchanged,
            "criterion_4_all_controls_and_counts_unchanged": controls_unchanged,
            "control_byte_equality": control_byte_equality,
            "control_attachment_count_unchanged": (
                control_attachment_count_unchanged
            ),
            "gate": plan["acceptance_gate"],
            "conclusion": (
                "Prepositional-wrapper normalization before example splitting passed its frozen single-case revealed-development gate."
                if accepted
                else "Prepositional-wrapper ordering failed its frozen gate."
            ),
            "interpretation_limit": plan["interpretation_limit"],
            "next_action": (
                "Record E7 as supported diagnostic causality only; do not implement v5 "
                "or combine E6 and E7 in this experiment cycle."
            ),
        },
    }


def _render_findings(report: dict[str, Any]) -> str:
    decision = report["decision"]
    target = report["aggregate"]["targets"]
    treatment = "prepositional_wrapper_before_example_split"
    return "\n".join(
        [
            "# E7 prepositional wrapper before example split experiment",
            "",
            "## Scope",
            "",
            "- One-time decision against the frozen E7 preregistration.",
            "- E7 starts independently from E5 final; E6 output was not loaded.",
            "- Control 006 retains its E5 false attachment in both arms, proving no accumulation.",
            "- Frozen v4 was not modified; v5 was not implemented.",
            "",
            "## Frozen gate",
            "",
            f"- Change exactly 019 first example 17:23 to 18:23: {'pass' if decision['criterion_1_exact_17_23_to_18_23_only'] else 'fail'}.",
            f"- Make 019 members, projection, and edges exact: {'pass' if decision['criterion_2_target_members_projection_edges_exact'] else 'fail'}.",
            f"- Keep 019 cue and parent unchanged: {'pass' if decision['criterion_3_cue_and_parent_unchanged'] else 'fail'}.",
            f"- Keep all controls and attachment counts unchanged: {'pass' if decision['criterion_4_all_controls_and_counts_unchanged'] else 'fail'}.",
            f"Decision: **{'accepted' if decision['accepted'] else 'rejected'}**.",
            "",
            "## Target change",
            "",
            "| Metric | E5 final -> E7 |",
            "|---|---:|",
            f"| Example member F1 | {target['e5_final_baseline']['example_members']['f1']:.4f} -> {target[treatment]['example_members']['f1']:.4f} |",
            f"| Attachment edge F1 | {target['e5_final_baseline']['attachment_edges']['f1']:.4f} -> {target[treatment]['attachment_edges']['f1']:.4f} |",
            f"| Example projection F1 | {target['e5_final_baseline']['example_projection']['f1']:.4f} -> {target[treatment]['example_projection']['f1']:.4f} |",
            "",
            "## Interpretation",
            "",
            decision["conclusion"],
            decision["interpretation_limit"],
            "This result does not authorize v5 implementation or a combined E6+E7 rule.",
            "",
        ]
    )


def main() -> int:
    for path, expected in EXPECTED_HASHES.items():
        actual = _sha256(path)
        if actual != expected:
            raise ValueError(f"frozen input hash mismatch for {path}: {actual} != {expected}")

    preregistration = _load(PREREGISTRATION_PATH)
    if preregistration["status"] != "frozen_before_execution":
        raise ValueError("E6/E7 preregistration is not frozen")
    plan = next(
        item
        for item in preregistration["experiments"]
        if item["id"] == "E7-prepositional-wrapper-before-example-split"
    )
    if tuple(plan["target_fixture_ids"]) != TARGET_IDS:
        raise ValueError("registered E7 targets changed")
    if tuple(plan["control_fixture_ids"]) != CONTROL_IDS:
        raise ValueError("registered E7 controls changed")

    e5_raw = _load(E5_RAW_PATH)
    e5_by_id = {item["id"]: item for item in e5_raw["records"]}
    baseline_raw = _load(BASELINE_RAW_PATH)
    baseline_by_id = {item["id"]: item for item in baseline_raw["records"]}
    anchors = preregistration["baseline_anchors"]
    for fixture_id, expected in anchors[
        "e5_final_arm_sha256_by_fixture"
    ].items():
        observed = _json_sha256(e5_by_id[fixture_id]["toggle3_parent_ranked"])
        if observed != expected:
            raise ValueError(f"E7 E5 baseline anchor drift for {fixture_id}")
    case_009_hash = _json_sha256(
        baseline_by_id["structured-corpus-external-v1-009"]
    )
    if case_009_hash != anchors["additional_e7_control_009_record_sha256"]:
        raise ValueError("E7 control 009 baseline anchor drift")

    selected_ids = (*TARGET_IDS, *CONTROL_IDS)
    parser_hash_before = _sha256(PARSER_PATH)
    source_records = [
        _source_record(fixture_id, e5_by_id, baseline_by_id)
        for fixture_id in selected_ids
    ]
    records = [_record(record, origin) for record, origin in source_records]
    parser_hash_after = _sha256(PARSER_PATH)
    raw = {
        "raw_version": (
            "unified-jd-structured-span-v4-e7-prepositional-wrapper-before-"
            "example-split-raw-v1"
        ),
        "created_at": "2026-09-04",
        "status": "revealed_development_causal_experiment",
        "experiment_id": plan["id"],
        "arms": list(ARMS),
        "preregistration_frozen_before_execution": True,
        "baseline_source": "independent E5 toggle3_parent_ranked reconstruction",
        "cumulative_treatment": False,
        "e6_output_loaded": False,
        "e6_treatment_included": False,
        "v4_full_parser_executed": False,
        "frozen_e5_detection_helper_reused_for_009": True,
        "v5_implemented": False,
        "frozen_v4_source": {
            "path": _relative(PARSER_PATH),
            "sha256_before": parser_hash_before,
            "sha256_after": parser_hash_after,
            "modified": parser_hash_before != parser_hash_after,
        },
        "fixture_count": len(records),
        "model_call_count": 0,
        "network_call_count": 0,
        "records": records,
    }
    if raw["frozen_v4_source"]["modified"]:
        raise ValueError("frozen v4 changed during E7")

    RAW_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _write_json(RAW_OUTPUT_PATH, raw)
    report = _build_report(plan, _load(DATASET_PATH), raw)
    _write_json(REPORT_OUTPUT_PATH, report)
    FINDINGS_OUTPUT_PATH.write_bytes(_render_findings(report).encode("utf-8"))
    print(
        f"E7 accepted={report['decision']['accepted']} "
        f"target_exact={report['decision']['criterion_2_target_members_projection_edges_exact']} "
        f"controls_exact={report['decision']['criterion_4_all_controls_and_counts_unchanged']} "
        f"e6_included={report['scope']['e6_treatment_included']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
