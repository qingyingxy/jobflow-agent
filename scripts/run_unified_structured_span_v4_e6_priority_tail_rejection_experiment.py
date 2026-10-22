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
RAW_OUTPUT_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-e6-priority-tail-rejection-raw-v1-2026-09-04.json"
)
REPORT_OUTPUT_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-e6-priority-tail-rejection-report-v1-2026-09-04.json"
)
FINDINGS_OUTPUT_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-e6-priority-tail-rejection-findings-v1-2026-09-04.md"
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
}

TARGET_IDS = ("structured-corpus-external-v1-006",)
CONTROL_IDS = (
    "structured-corpus-external-v1-002",
    "structured-corpus-external-v1-005",
    "structured-corpus-external-v1-019",
    "structured-corpus-external-v1-018",
)
ARMS = ("e5_final_baseline", "priority_tail_rejection")
PRIORITY_TAIL_OPERATORS = {"优先"}


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


def _complete_right_tail(
    source: str,
    segments: list[dict[str, Any]],
    attachment: dict[str, Any],
) -> dict[str, Any]:
    cue = attachment["cue_span"]
    segment = segments[attachment["segment_index"]]
    start = cue["end"]
    end = segment["end"]
    while start < end and source[start].isspace():
        start += 1
    while start < end and (source[end - 1].isspace() or source[end - 1] in "，,；;。"):
        end -= 1
    return {"text": source[start:end], "start": start, "end": end}


def _apply_priority_tail_rejection(
    record: dict[str, Any], baseline: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    treatment = copy.deepcopy(baseline)
    retained: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    for attachment in treatment["attachments"]:
        tail = _complete_right_tail(
            record["source_text"],
            record["held_fixed"]["segments"],
            attachment,
        )
        eligible = tail["text"] not in PRIORITY_TAIL_OPERATORS
        events.append(
            {
                "cue_span": copy.deepcopy(attachment["cue_span"]),
                "complete_right_tail": tail,
                "attachment_eligible": eligible,
                "reason": (
                    "right_tail_is_not_priority_operator"
                    if eligible
                    else "complete_right_tail_is_priority_operator"
                ),
            }
        )
        if eligible:
            retained.append(attachment)

    treatment["attachments"] = retained
    treatment["example_members"] = [
        copy.deepcopy(span)
        for attachment in retained
        for span in attachment["example_spans"]
    ]
    treatment["example_items"] = [
        span["text"] for span in treatment["example_members"]
    ]
    return treatment, events


def _record(e5_record: dict[str, Any]) -> dict[str, Any]:
    baseline = copy.deepcopy(e5_record["toggle3_parent_ranked"])
    treatment, events = _apply_priority_tail_rejection(e5_record, baseline)
    return {
        "id": e5_record["id"],
        "job_id": e5_record["job_id"],
        "category": e5_record["category"],
        "role": "target" if e5_record["id"] in TARGET_IDS else "control",
        "source_text": e5_record["source_text"],
        "held_fixed": copy.deepcopy(e5_record["held_fixed"]),
        "e5_final_baseline_sha256": _json_sha256(baseline),
        "e5_final_baseline": baseline,
        "priority_tail_rejection": treatment,
        "eligibility_events": events,
    }


def _arm_bytes(arm: dict[str, Any]) -> bytes:
    return json.dumps(arm, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _attachment_spans(arm: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "cue_span": item["cue_span"],
            "parent_span": item["parent_span"],
            "example_spans": item["example_spans"],
        }
        for item in arm["attachments"]
    ]


def _retained_spans_unchanged(
    baseline: dict[str, Any], treatment: dict[str, Any]
) -> bool:
    baseline_spans = _attachment_spans(baseline)
    return all(item in baseline_spans for item in _attachment_spans(treatment))


def _build_report(
    plan: dict[str, Any], dataset: dict[str, Any], raw: dict[str, Any]
) -> dict[str, Any]:
    gold_by_id = {item["id"]: item["gold"] for item in dataset["fixtures"]}
    records_by_id = {item["id"]: item for item in raw["records"]}
    target = records_by_id[TARGET_IDS[0]]
    target_treatment = target["priority_tail_rejection"]

    target_cleared = (
        target_treatment["attachments"] == []
        and target_treatment["example_members"] == []
        and target_treatment["example_items"] == []
        and e5._edge_keys_arm(target_treatment) == []
    )
    control_byte_equality = {
        fixture_id: _arm_bytes(records_by_id[fixture_id]["e5_final_baseline"])
        == _arm_bytes(records_by_id[fixture_id]["priority_tail_rejection"])
        for fixture_id in CONTROL_IDS
    }
    case_019 = records_by_id["structured-corpus-external-v1-019"]
    discovery_019_preserved = (
        len(case_019["priority_tail_rejection"]["attachments"]) == 1
        and _arm_bytes(case_019["e5_final_baseline"])
        == _arm_bytes(case_019["priority_tail_rejection"])
    )
    retained_spans_unchanged = all(
        _retained_spans_unchanged(
            item["e5_final_baseline"], item["priority_tail_rejection"]
        )
        for item in raw["records"]
    )
    accepted = (
        target_cleared
        and discovery_019_preserved
        and all(control_byte_equality.values())
        and retained_spans_unchanged
    )

    records = []
    for fixture_id in (*TARGET_IDS, *CONTROL_IDS):
        record = records_by_id[fixture_id]
        records.append(
            {
                "id": fixture_id,
                "role": record["role"],
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
                == _arm_bytes(record["priority_tail_rejection"]),
                "retained_attachment_spans_unchanged": _retained_spans_unchanged(
                    record["e5_final_baseline"],
                    record["priority_tail_rejection"],
                ),
                "eligibility_events": record["eligibility_events"],
            }
        )

    return {
        "report_version": (
            "unified-jd-structured-span-v4-e6-priority-tail-rejection-report-v1"
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
            "model_call_count": 0,
            "network_call_count": 0,
        },
        "inputs": {
            "preregistration": _input(PREREGISTRATION_PATH),
            "revealed_development": _input(DATASET_PATH),
            "e5_final_raw": _input(E5_RAW_PATH),
            "e5_report": _input(E5_REPORT_PATH),
            "frozen_v4_source": _input(PARSER_PATH),
            "rules_freeze": _input(RULES_FREEZE_PATH),
            "experiment_raw": _input(RAW_OUTPUT_PATH),
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
            "criterion_1_006_false_outputs_removed": target_cleared,
            "criterion_2_019_discovery_preserved": discovery_019_preserved,
            "criterion_3_all_controls_byte_identical": all(
                control_byte_equality.values()
            ),
            "control_byte_equality": control_byte_equality,
            "criterion_4_retained_attachment_spans_unchanged": (
                retained_spans_unchanged
            ),
            "gate": plan["acceptance_gate"],
            "conclusion": (
                "Priority-tail rejection passed its frozen single-case revealed-development gate."
                if accepted
                else "Priority-tail rejection failed its frozen gate."
            ),
            "interpretation_limit": plan["interpretation_limit"],
            "next_action": (
                "Record E6 as supported diagnostic causality only; do not implement v5. "
                "Execute E7 from its independent E5 baseline."
            ),
        },
    }


def _render_findings(report: dict[str, Any]) -> str:
    decision = report["decision"]
    target = report["aggregate"]["targets"]
    return "\n".join(
        [
            "# E6 priority-tail rejection experiment",
            "",
            "## Scope",
            "",
            "- One-time decision against the frozen E6 preregistration.",
            "- Revealed development only; no generalization or production-rule claim.",
            "- E5 final is the baseline; no E7 or cumulative treatment is present.",
            "- Frozen v4 was neither executed nor modified; v5 was not implemented.",
            "",
            "## Frozen gate",
            "",
            f"- Remove all false 006 attachment outputs: {'pass' if decision['criterion_1_006_false_outputs_removed'] else 'fail'}.",
            f"- Preserve the E5-discovered 019 attachment: {'pass' if decision['criterion_2_019_discovery_preserved'] else 'fail'}.",
            f"- Keep all four controls byte-identical: {'pass' if decision['criterion_3_all_controls_byte_identical'] else 'fail'}.",
            f"- Preserve all retained attachment spans: {'pass' if decision['criterion_4_retained_attachment_spans_unchanged'] else 'fail'}.",
            f"Decision: **{'accepted' if decision['accepted'] else 'rejected'}**.",
            "",
            "## Target change",
            "",
            "| Metric | E5 final -> E6 |",
            "|---|---:|",
            f"| Example member F1 | {target['e5_final_baseline']['example_members']['f1']:.4f} -> {target['priority_tail_rejection']['example_members']['f1']:.4f} |",
            f"| Attachment edge F1 | {target['e5_final_baseline']['attachment_edges']['f1']:.4f} -> {target['priority_tail_rejection']['attachment_edges']['f1']:.4f} |",
            f"| Example projection F1 | {target['e5_final_baseline']['example_projection']['f1']:.4f} -> {target['priority_tail_rejection']['example_projection']['f1']:.4f} |",
            "",
            "## Interpretation",
            "",
            decision["conclusion"],
            decision["interpretation_limit"],
            "This result is not a production lexical blacklist and does not authorize v5 implementation.",
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
        if item["id"] == "E6-priority-tail-rejection"
    )
    if tuple(plan["target_fixture_ids"]) != TARGET_IDS:
        raise ValueError("registered E6 targets changed")
    if tuple(plan["control_fixture_ids"]) != CONTROL_IDS:
        raise ValueError("registered E6 controls changed")

    e5_raw = _load(E5_RAW_PATH)
    e5_by_id = {item["id"]: item for item in e5_raw["records"]}
    anchors = preregistration["baseline_anchors"][
        "e5_final_arm_sha256_by_fixture"
    ]
    selected_ids = (*TARGET_IDS, *CONTROL_IDS)
    for fixture_id in selected_ids:
        observed = _json_sha256(e5_by_id[fixture_id]["toggle3_parent_ranked"])
        if observed != anchors[fixture_id]:
            raise ValueError(f"E6 baseline anchor drift for {fixture_id}")

    parser_hash_before = _sha256(PARSER_PATH)
    records = [_record(e5_by_id[fixture_id]) for fixture_id in selected_ids]
    parser_hash_after = _sha256(PARSER_PATH)
    raw = {
        "raw_version": (
            "unified-jd-structured-span-v4-e6-priority-tail-rejection-raw-v1"
        ),
        "created_at": "2026-09-04",
        "status": "revealed_development_causal_experiment",
        "experiment_id": plan["id"],
        "arms": list(ARMS),
        "preregistration_frozen_before_execution": True,
        "baseline_source": "E5 toggle3_parent_ranked",
        "cumulative_treatment": False,
        "v4_parser_executed": False,
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
        raise ValueError("frozen v4 changed during E6")

    RAW_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _write_json(RAW_OUTPUT_PATH, raw)
    report = _build_report(plan, _load(DATASET_PATH), raw)
    _write_json(REPORT_OUTPUT_PATH, report)
    FINDINGS_OUTPUT_PATH.write_bytes(_render_findings(report).encode("utf-8"))
    print(
        f"E6 accepted={report['decision']['accepted']} "
        f"target_cleared={report['decision']['criterion_1_006_false_outputs_removed']} "
        f"controls_exact={report['decision']['criterion_3_all_controls_byte_identical']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
