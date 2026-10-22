from __future__ import annotations

import copy
import hashlib
import json
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.evaluate_unified_structured_span_v4_corpus_external_holdout import (
    _attachment_edge_keys,
    _attachment_parent_keys,
    _metric,
)
from src.domain.unified_jd_structured_spans_v4 import (
    SourceSpan,
    detect_topology_attachment,
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
BASELINE_RAW_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-corpus-external-raw-v1-2026-09-04.json"
)
ANALYSIS_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-revealed-error-analysis-v1-2026-09-04.json"
)
E4_REPORT_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-e4-scope-candidate-application-report-v1-2026-09-04.json"
)
RAW_OUTPUT_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-e5-example-attachment-three-toggle-raw-v1-2026-09-04.json"
)
REPORT_OUTPUT_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-e5-example-attachment-three-toggle-report-v1-2026-09-04.json"
)
FINDINGS_OUTPUT_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-e5-example-attachment-three-toggle-findings-v1-2026-09-04.md"
)

EXPECTED_HASHES = {
    PARSER_PATH: "e09e056cab75e651937391ce5410e6df7c94477c85565abb1425bbe85cfcb094",
    RULES_FREEZE_PATH: (
        "6a8a1d9ccce7c1069a483c7cc387221164de52800a133308922d57ff75ad6a12"
    ),
    DATASET_PATH: "965263881ff85bca636aa6ab87adaca24d74183fa13400709133323a3a6d5b73",
    BASELINE_RAW_PATH: (
        "36b65c1df79d856c7507ae1357ed24c10b7a3e383bad79b9471b124f4999e058"
    ),
    ANALYSIS_PATH: "770d09ca956a55995609ad9f8c8e549a69b26097e6b18216e1b174f1f6c9a4b7",
    E4_REPORT_PATH: (
        "e8411116af4a3b759a3a41b243027476972954b0d33b44fac58b696f6552898c"
    ),
}

TARGET_IDS = (
    "structured-corpus-external-v1-002",
    "structured-corpus-external-v1-005",
    "structured-corpus-external-v1-019",
)
CONTROL_IDS = (
    "structured-corpus-external-v1-006",
    "structured-corpus-external-v1-018",
)
ARMS = (
    "baseline",
    "toggle1_cue_stripped",
    "toggle2_category_neutral",
    "toggle3_parent_ranked",
)
INTRODUCTORY_LIST_CUES = (
    "\u5305\u62ec\u4f46\u4e0d\u9650\u4e8e",
    "\u4e3b\u8981\u5305\u62ec",
)
GENERIC_RIGHT_PARENTS = {"\u5de5\u4f5c", "\u4f18\u5148"}

SpanKey = tuple[int, int, str]
ParentKey = tuple[SpanKey, SpanKey]
EdgeKey = tuple[SpanKey, SpanKey, SpanKey]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _relative(path: Path) -> str:
    return path.relative_to(PROJECT_ROOT).as_posix()


def _span_key(span: dict[str, Any]) -> SpanKey:
    return (span["start"], span["end"], span["text"])


def _span(source: str, start: int, end: int) -> dict[str, Any]:
    while start < end and (source[start].isspace() or source[start] in "\uff0c,\uff1b;:\uff1a"):
        start += 1
    while start < end and (
        source[end - 1].isspace() or source[end - 1] in "\uff0c,\uff1b;:\uff1a"
    ):
        end -= 1
    if start >= end:
        raise ValueError("attachment experiment produced an empty span")
    return {"text": source[start:end], "start": start, "end": end}


def _baseline_arm(record: dict[str, Any]) -> dict[str, Any]:
    attachments = [
        {
            "cue_span": copy.deepcopy(item["cue_span"]),
            "parent_span": copy.deepcopy(item["parent_span"]),
            "example_spans": copy.deepcopy(item["example_spans"]),
            "segment_index": item["segment_index"],
        }
        for item in record["parsed_clause"]["example_attachments"]
    ]
    members = [
        copy.deepcopy(span)
        for attachment in attachments
        for span in attachment["example_spans"]
    ]
    return {
        "example_members": members,
        "attachments": attachments,
        "example_items": list(record["examples"]),
        "detection_events": [],
        "parent_ranking_events": [],
    }


def _strip_introductory_cue(
    source: str, span: dict[str, Any]
) -> tuple[dict[str, Any], str | None]:
    for cue in INTRODUCTORY_LIST_CUES:
        if span["text"].startswith(cue) and len(span["text"]) > len(cue):
            return _span(source, span["start"] + len(cue), span["end"]), cue
    return copy.deepcopy(span), None


def _apply_toggle1(source: str, arm: dict[str, Any]) -> dict[str, Any]:
    treatment = copy.deepcopy(arm)
    stripped_events: list[dict[str, Any]] = []
    members: list[dict[str, Any]] = []
    for attachment in treatment["attachments"]:
        transformed: list[dict[str, Any]] = []
        for position, item in enumerate(attachment["example_spans"]):
            updated, cue = _strip_introductory_cue(source, item)
            transformed.append(updated)
            if cue is not None:
                stripped_events.append(
                    {
                        "position": position,
                        "cue": cue,
                        "before": item,
                        "after": updated,
                    }
                )
        attachment["example_spans"] = transformed
        members.extend(copy.deepcopy(transformed))
    treatment["example_members"] = members
    treatment["example_items"] = [item["text"] for item in members]
    treatment["cue_strip_events"] = stripped_events
    return treatment


def _segment_body(record: dict[str, Any], segment: dict[str, Any]) -> SourceSpan:
    start = segment["start"]
    prefix_markers = [
        wrapper["marker_span"]
        for wrapper in record["parsed_clause"]["wrappers"]
        if wrapper["kind"].split(".")[-1] == "prefix"
        and wrapper["marker_span"]["start"] == segment["start"]
        and wrapper["marker_span"]["end"] < segment["end"]
    ]
    if prefix_markers:
        start = max(item["end"] for item in prefix_markers)
    return SourceSpan.from_bounds(record["source_text"], start, segment["end"])


def _detected_attachment(
    record: dict[str, Any], arm: dict[str, Any]
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if arm["attachments"]:
        return None, None
    source = record["source_text"]
    for segment_index, segment in enumerate(record["parsed_clause"]["segments"]):
        body = _segment_body(record, segment)
        # Passing an allowed category removes only the frozen category guard.
        detected = detect_topology_attachment(source, body, "responsibility")
        if detected is None:
            continue
        value = asdict(detected)
        example_spans = [
            _strip_introductory_cue(source, item)[0]
            for item in value["example_spans"]
        ]
        attachment = {
            "cue_span": value["cue_span"],
            "parent_span": value["parent_span"],
            "example_spans": example_spans,
            "segment_index": segment_index,
        }
        event = {
            "segment_index": segment_index,
            "body_span": asdict(body),
            "detected_attachment": copy.deepcopy(attachment),
        }
        return attachment, event
    return None, None


def _apply_toggle2(record: dict[str, Any], arm: dict[str, Any]) -> dict[str, Any]:
    treatment = copy.deepcopy(arm)
    attachment, event = _detected_attachment(record, treatment)
    if attachment is not None and event is not None:
        treatment["attachments"] = [attachment]
        treatment["example_members"] = copy.deepcopy(attachment["example_spans"])
        treatment["example_items"] = [
            item["text"] for item in attachment["example_spans"]
        ]
        treatment["detection_events"].append(event)
    return treatment


def _segment_for_cue(record: dict[str, Any], cue: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    return next(
        (index, segment)
        for index, segment in enumerate(record["parsed_clause"]["segments"])
        if segment["start"] <= cue["start"] < cue["end"] <= segment["end"]
    )


def _previous_segment_candidate(
    record: dict[str, Any], segment_index: int
) -> dict[str, Any] | None:
    if segment_index == 0:
        return None
    segment = record["parsed_clause"]["segments"][segment_index - 1]
    prefixes = [
        wrapper
        for wrapper in record["parsed_clause"]["wrappers"]
        if wrapper["kind"].split(".")[-1] == "prefix"
        and wrapper["marker_span"]["start"] == segment["start"]
        and wrapper["content_span"]["end"] == segment["end"]
    ]
    if prefixes:
        return copy.deepcopy(max(prefixes, key=lambda item: item["marker_span"]["end"])["content_span"])
    return _span(record["source_text"], segment["start"], segment["end"])


def _right_local_candidate(
    source: str, cue: dict[str, Any], segment: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    tail = _span(source, cue["end"], segment["end"])
    predicate_offset = tail["text"].find("\u6709")
    if predicate_offset > 0:
        core = _span(source, tail["start"], tail["start"] + predicate_offset)
        return core, tail
    return tail, tail


def _rank_parent(
    record: dict[str, Any], attachment: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    segment_index, segment = _segment_for_cue(record, attachment["cue_span"])
    right_local, right_tail = _right_local_candidate(
        record["source_text"], attachment["cue_span"], segment
    )
    previous = _previous_segment_candidate(record, segment_index)
    if right_local["text"] in GENERIC_RIGHT_PARENTS and previous is not None:
        selected = previous
        reason = "generic_right_tail_prefers_previous_segment"
    else:
        selected = right_local
        reason = "specific_right_local_parent"
    event = {
        "cue_span": copy.deepcopy(attachment["cue_span"]),
        "right_tail_candidate": right_tail,
        "right_local_candidate": right_local,
        "previous_segment_candidate": previous,
        "selected_parent": selected,
        "reason": reason,
    }
    return selected, event


def _apply_toggle3(record: dict[str, Any], arm: dict[str, Any]) -> dict[str, Any]:
    treatment = copy.deepcopy(arm)
    for attachment in treatment["attachments"]:
        parent, event = _rank_parent(record, attachment)
        attachment["parent_span"] = parent
        treatment["parent_ranking_events"].append(event)
    return treatment


def _arm_payload(arm: dict[str, Any]) -> dict[str, Any]:
    return {
        "example_members": arm["example_members"],
        "attachments": arm["attachments"],
        "example_items": arm["example_items"],
    }


def _record(baseline: dict[str, Any]) -> dict[str, Any]:
    baseline_arm = _baseline_arm(baseline)
    toggle1 = _apply_toggle1(baseline["source_text"], baseline_arm)
    toggle2 = _apply_toggle2(baseline, toggle1)
    toggle3 = _apply_toggle3(baseline, toggle2)
    return {
        "id": baseline["id"],
        "job_id": baseline["job_id"],
        "category": baseline["category"],
        "source_text": baseline["source_text"],
        "held_fixed": {
            "segments": baseline["parsed_clause"]["segments"],
            "wrappers": baseline["parsed_clause"]["wrappers"],
            "non_example_items": baseline["items"],
            "shared_scopes": baseline["parsed_clause"]["shared_scopes"],
        },
        "baseline": baseline_arm,
        "toggle1_cue_stripped": toggle1,
        "toggle2_category_neutral": toggle2,
        "toggle3_parent_ranked": toggle3,
    }


def _example_member_keys_gold(gold: dict[str, Any]) -> list[SpanKey]:
    return [
        _span_key(span)
        for group in gold["coordinations"]
        if group["role"] == "example"
        for span in group["member_spans"]
    ]


def _example_member_keys_arm(arm: dict[str, Any]) -> list[SpanKey]:
    return [_span_key(item) for item in arm["example_members"]]


def _parent_keys_arm(arm: dict[str, Any]) -> list[ParentKey]:
    return [
        (_span_key(item["cue_span"]), _span_key(item["parent_span"]))
        for item in arm["attachments"]
    ]


def _edge_keys_arm(arm: dict[str, Any]) -> list[EdgeKey]:
    return [
        (
            _span_key(item["cue_span"]),
            _span_key(item["parent_span"]),
            _span_key(example),
        )
        for item in arm["attachments"]
        for example in item["example_spans"]
    ]


def _difference_count(expected: list[Any], predicted: list[Any]) -> int:
    left = Counter(expected)
    right = Counter(predicted)
    return sum((left - right).values()) + sum((right - left).values())


def _fixture_counts(gold: dict[str, Any], arm: dict[str, Any]) -> dict[str, int]:
    return {
        "example_members": _difference_count(
            _example_member_keys_gold(gold), _example_member_keys_arm(arm)
        ),
        "attachment_parents": _difference_count(
            _attachment_parent_keys(gold, gold=True), _parent_keys_arm(arm)
        ),
        "attachment_edges": _difference_count(
            _attachment_edge_keys(gold, gold=True), _edge_keys_arm(arm)
        ),
        "example_projection": _difference_count(
            gold["projection"]["examples"], arm["example_items"]
        ),
    }


def _aggregate(
    fixture_ids: tuple[str, ...],
    gold_by_id: dict[str, dict[str, Any]],
    records_by_id: dict[str, dict[str, Any]],
    arm_name: str,
) -> dict[str, Any]:
    pairs = [(gold_by_id[item], records_by_id[item][arm_name]) for item in fixture_ids]
    return {
        "example_members": _metric(
            (
                (_example_member_keys_gold(gold), _example_member_keys_arm(arm))
                for gold, arm in pairs
            )
        ),
        "attachment_parents": _metric(
            (
                (_attachment_parent_keys(gold, gold=True), _parent_keys_arm(arm))
                for gold, arm in pairs
            )
        ),
        "attachment_edges": _metric(
            (
                (_attachment_edge_keys(gold, gold=True), _edge_keys_arm(arm))
                for gold, arm in pairs
            )
        ),
        "example_projection": _metric(
            (
                (gold["projection"]["examples"], arm["example_items"])
                for gold, arm in pairs
            )
        ),
    }


def _is_exact(gold: dict[str, Any], arm: dict[str, Any], outcome: str) -> bool:
    return _fixture_counts(gold, arm)[outcome] == 0


def _changed_ids(
    records: list[dict[str, Any]], left: str, right: str
) -> list[str]:
    return [
        item["id"]
        for item in records
        if _arm_payload(item[left]) != _arm_payload(item[right])
    ]


def _build_report(
    plan: dict[str, Any], dataset: dict[str, Any], raw: dict[str, Any]
) -> dict[str, Any]:
    gold_by_id = {item["id"]: item["gold"] for item in dataset["fixtures"]}
    records_by_id = {item["id"]: item for item in raw["records"]}
    toggle1_fixed = all(
        _is_exact(
            gold_by_id[item], records_by_id[item]["toggle1_cue_stripped"], "example_members"
        )
        for item in TARGET_IDS[:2]
    )
    toggle2_discovered_019 = (
        not records_by_id[TARGET_IDS[2]]["toggle1_cue_stripped"]["attachments"]
        and len(records_by_id[TARGET_IDS[2]]["toggle2_category_neutral"]["attachments"])
        == 1
    )
    toggle2_control_changes = {
        item: _arm_payload(records_by_id[item]["toggle1_cue_stripped"])
        != _arm_payload(records_by_id[item]["toggle2_category_neutral"])
        for item in CONTROL_IDS
    }
    toggle2_controls_unchanged = not any(toggle2_control_changes.values())
    toggle3_parents_exact = all(
        _is_exact(
            gold_by_id[item], records_by_id[item]["toggle3_parent_ranked"], "attachment_parents"
        )
        for item in TARGET_IDS
    )
    toggle3_edges_exact = all(
        _is_exact(
            gold_by_id[item], records_by_id[item]["toggle3_parent_ranked"], "attachment_edges"
        )
        for item in TARGET_IDS
    )
    accepted = (
        toggle1_fixed
        and toggle2_discovered_019
        and toggle2_controls_unchanged
        and toggle3_parents_exact
        and toggle3_edges_exact
    )

    per_fixture: list[dict[str, Any]] = []
    for fixture_id in (*TARGET_IDS, *CONTROL_IDS):
        record = records_by_id[fixture_id]
        per_fixture.append(
            {
                "id": fixture_id,
                "role": "target" if fixture_id in TARGET_IDS else "control",
                "source_text": record["source_text"],
                "differences_by_arm": {
                    arm: _fixture_counts(gold_by_id[fixture_id], record[arm])
                    for arm in ARMS
                },
                "attachment_count_by_arm": {
                    arm: len(record[arm]["attachments"]) for arm in ARMS
                },
                "final_parent_ranking_events": record[
                    "toggle3_parent_ranked"
                ]["parent_ranking_events"],
            }
        )

    return {
        "report_version": (
            "unified-jd-structured-span-v4-e5-example-attachment-three-toggle-report-v1"
        ),
        "created_at": "2026-09-04",
        "scope": {
            "status": "revealed_development_causal_experiment",
            "experiment_id": plan["id"],
            "generalization_claim": False,
            "threshold_selection_allowed": False,
            "production_rule_claim": False,
            "frozen_v4_modified": False,
            "v4_full_parser_executed": False,
            "frozen_detection_helper_reused": True,
            "model_call_count": 0,
            "network_call_count": 0,
        },
        "inputs": {
            "registered_plan": {
                "path": _relative(ANALYSIS_PATH),
                "sha256": EXPECTED_HASHES[ANALYSIS_PATH],
            },
            "revealed_development": {
                "path": _relative(DATASET_PATH),
                "sha256": EXPECTED_HASHES[DATASET_PATH],
            },
            "reused_baseline_raw": {
                "path": _relative(BASELINE_RAW_PATH),
                "sha256": EXPECTED_HASHES[BASELINE_RAW_PATH],
            },
            "e4_report": {
                "path": _relative(E4_REPORT_PATH),
                "sha256": EXPECTED_HASHES[E4_REPORT_PATH],
            },
            "frozen_v4_source": {
                "path": _relative(PARSER_PATH),
                "sha256": EXPECTED_HASHES[PARSER_PATH],
            },
            "rules_freeze": {
                "path": _relative(RULES_FREEZE_PATH),
                "sha256": EXPECTED_HASHES[RULES_FREEZE_PATH],
            },
            "experiment_raw": {
                "path": _relative(RAW_OUTPUT_PATH),
                "sha256": _sha256(RAW_OUTPUT_PATH),
            },
        },
        "registered_hypothesis": plan["hypothesis"],
        "registered_intervention": plan["intervention"],
        "operationalization": {
            "baseline": "Reconstruct attachment outputs from the stored v4 raw response.",
            "toggle1": (
                "Strip only the two observed introductory list cues from the first "
                "example span; keep cue and parent fixed."
            ),
            "toggle2": (
                "For attachment-free clauses, reuse the frozen topology detector with "
                "only its category guard bypassed; keep predicted wrappers and segments."
            ),
            "toggle3": (
                "Rank a specific right-local candidate above the previous segment, "
                "but prefer the previous segment when the right tail is generic."
            ),
            "held_fixed": (
                "Stored segments, predicted wrappers, non-example items, shared scopes, "
                "and all non-attachment structure."
            ),
            "limitation": (
                "The toggles are diagnostic revealed-data mechanisms, not a frozen "
                "production detector or evidence of generalization."
            ),
        },
        "target_fixture_ids": list(TARGET_IDS),
        "control_fixture_ids": list(CONTROL_IDS),
        "changed_fixture_ids": {
            "toggle1": _changed_ids(raw["records"], "baseline", "toggle1_cue_stripped"),
            "toggle2": _changed_ids(
                raw["records"], "toggle1_cue_stripped", "toggle2_category_neutral"
            ),
            "toggle3": _changed_ids(
                raw["records"], "toggle2_category_neutral", "toggle3_parent_ranked"
            ),
        },
        "aggregate": {
            "targets": {
                arm: _aggregate(TARGET_IDS, gold_by_id, records_by_id, arm)
                for arm in ARMS
            },
            "controls": {
                arm: _aggregate(CONTROL_IDS, gold_by_id, records_by_id, arm)
                for arm in ARMS
            },
        },
        "records": per_fixture,
        "decision": {
            "accepted": accepted,
            "toggle1_fixes_002_005_example_spans": toggle1_fixed,
            "toggle2_discovers_019": toggle2_discovered_019,
            "toggle2_controls_unchanged": toggle2_controls_unchanged,
            "toggle2_control_changes": toggle2_control_changes,
            "toggle3_all_target_parents_exact": toggle3_parents_exact,
            "toggle3_all_target_edges_exact": toggle3_edges_exact,
            "conclusion": (
                "The three separable attachment mechanisms satisfy the registered gate."
                if accepted
                else "The registered three-toggle explanation is incomplete and must not be merged into v5."
            ),
            "next_action": (
                "Retain all three mechanisms as v5 candidates."
                if accepted
                else "Add no E5 mechanism to v5; diagnose priority-tail rejection and prepositional wrapper normalization before a new pre-registered experiment."
            ),
        },
    }


def _metric_change(report: dict[str, Any], layer: str) -> str:
    target = report["aggregate"]["targets"]
    return " -> ".join(f"{target[arm][layer]['f1']:.4f}" for arm in ARMS)


def _render_findings(report: dict[str, Any]) -> str:
    decision = report["decision"]
    lines = [
        "# E5 example attachment three-toggle experiment",
        "",
        "## Scope",
        "",
        "- Revealed development data only; no generalization claim.",
        "- Frozen v4 was not modified; the stored baseline raw was reused.",
        "- Toggle 2 bypasses only the frozen detector's category guard.",
        "- No post-hoc priority-tail exception or prepositional wrapper rule was added.",
        "",
        "## Registered checks",
        "",
        (
            "- Toggle 1 fixes example spans in 002/005: "
            f"{'pass' if decision['toggle1_fixes_002_005_example_spans'] else 'fail'}."
        ),
        (
            "- Toggle 2 discovers 019: "
            f"{'pass' if decision['toggle2_discovers_019'] else 'fail'}."
        ),
        (
            "- Toggle 2 leaves controls unchanged: "
            f"{'pass' if decision['toggle2_controls_unchanged'] else 'fail'}."
        ),
        (
            "- Toggle 3 makes all target parents exact: "
            f"{'pass' if decision['toggle3_all_target_parents_exact'] else 'fail'}."
        ),
        (
            "- Toggle 3 makes all target edges exact: "
            f"{'pass' if decision['toggle3_all_target_edges_exact'] else 'fail'}."
        ),
        f"Decision: **{'accepted' if decision['accepted'] else 'rejected'}**.",
        "",
        "## Target F1 by sequential arm",
        "",
        "| Metric | baseline -> toggle 1 -> toggle 2 -> toggle 3 |",
        "|---|---:|",
        f"| Example members | {_metric_change(report, 'example_members')} |",
        f"| Attachment parents | {_metric_change(report, 'attachment_parents')} |",
        f"| Attachment edges | {_metric_change(report, 'attachment_edges')} |",
        f"| Example projection | {_metric_change(report, 'example_projection')} |",
        "",
        "## Failure attribution",
        "",
        (
            "Category-neutral detection finds 019, but also creates a false attachment "
            "for control 006 from the priority phrase ending in deng-you-xian."
        ),
        (
            "Parent ranking makes all three target parents exact. The 019 edge remains "
            "non-exact because its first example still contains the leading preposition; "
            "that boundary mechanism was not one of the registered toggles."
        ),
        "",
        "## Decision",
        "",
        decision["next_action"],
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    for path, expected in EXPECTED_HASHES.items():
        actual = _sha256(path)
        if actual != expected:
            raise ValueError(f"frozen input hash mismatch for {path}: {actual} != {expected}")

    analysis = _load(ANALYSIS_PATH)
    plan = next(
        item
        for item in analysis["causal_experiment_plan"]
        if item["id"] == "E5-example-attachment-three-toggle"
    )
    if tuple(plan["target_fixture_ids"]) != TARGET_IDS:
        raise ValueError("registered E5 targets changed")
    if tuple(plan["control_fixture_ids"]) != CONTROL_IDS:
        raise ValueError("registered E5 controls changed")

    baseline_by_id = {
        item["id"]: item for item in _load(BASELINE_RAW_PATH)["records"]
    }
    selected_ids = (*TARGET_IDS, *CONTROL_IDS)
    parser_hash_before = _sha256(PARSER_PATH)
    records = [_record(baseline_by_id[item]) for item in selected_ids]
    parser_hash_after = _sha256(PARSER_PATH)
    raw = {
        "raw_version": (
            "unified-jd-structured-span-v4-e5-example-attachment-three-toggle-raw-v1"
        ),
        "created_at": "2026-09-04",
        "status": "revealed_development_causal_experiment",
        "experiment_id": plan["id"],
        "arms": list(ARMS),
        "baseline_reused": True,
        "v4_full_parser_executed": False,
        "frozen_detection_helper_reused": True,
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
        raise ValueError("frozen v4 changed during E5")

    RAW_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _write_json(RAW_OUTPUT_PATH, raw)
    dataset = _load(DATASET_PATH)
    report = _build_report(plan, dataset, raw)
    _write_json(REPORT_OUTPUT_PATH, report)
    FINDINGS_OUTPUT_PATH.write_text(_render_findings(report), encoding="utf-8")
    print(
        f"E5 accepted={report['decision']['accepted']} "
        f"toggle2_controls={report['decision']['toggle2_controls_unchanged']} "
        f"toggle3_edges={report['decision']['toggle3_all_target_edges_exact']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
