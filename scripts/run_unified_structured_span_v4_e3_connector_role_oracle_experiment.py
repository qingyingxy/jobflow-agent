from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.evaluate_unified_structured_span_v4_corpus_external_holdout import (
    _attachment_edge_keys,
    _coordination_member_keys,
    _metric,
)

PARSER_PATH = PROJECT_ROOT / "src/domain/unified_jd_structured_spans_v4.py"
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
E2_REPORT_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-e2-wrapper-oracle-report-v1-2026-09-04.json"
)
RAW_OUTPUT_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-e3-connector-role-oracle-raw-v1-2026-09-04.json"
)
REPORT_OUTPUT_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-e3-connector-role-oracle-report-v1-2026-09-04.json"
)
FINDINGS_OUTPUT_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-e3-connector-role-oracle-findings-v1-2026-09-04.md"
)

EXPECTED_HASHES = {
    PARSER_PATH: "e09e056cab75e651937391ce5410e6df7c94477c85565abb1425bbe85cfcb094",
    DATASET_PATH: "965263881ff85bca636aa6ab87adaca24d74183fa13400709133323a3a6d5b73",
    BASELINE_RAW_PATH: (
        "36b65c1df79d856c7507ae1357ed24c10b7a3e383bad79b9471b124f4999e058"
    ),
    ANALYSIS_PATH: "770d09ca956a55995609ad9f8c8e549a69b26097e6b18216e1b174f1f6c9a4b7",
    E2_REPORT_PATH: (
        "84d53a7d11556cf32f4892e42ebed7a4e40979871ace1e35195786888e69db3c"
    ),
}

GROUP_ROLES = ("surface", "embedded", "example")
PRIMARY_OUTCOMES = (
    "coordination_members",
    "example_attachment_edges",
    "surface_projection",
)

SpanKey = tuple[int, int, str]
MemberKey = tuple[str, SpanKey]
AttachmentEdgeKey = tuple[SpanKey, SpanKey, SpanKey]


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
    while start < end and (source[start].isspace() or source[start] in "，,；;:："):
        start += 1
    while start < end and (
        source[end - 1].isspace() or source[end - 1] in "，,；;:："
    ):
        end -= 1
    if start >= end:
        raise ValueError("connector-role reconstruction produced an empty span")
    return {"text": source[start:end], "start": start, "end": end}


def _role_maps(
    gold: dict[str, Any], baseline: dict[str, Any]
) -> tuple[dict[SpanKey, str], dict[SpanKey, str]]:
    expected = {
        _span_key(item["span"]): item["role"] for item in gold["connector_labels"]
    }
    predicted = {
        _span_key(item["span"]): item["role"]
        for item in baseline["parsed_clause"]["connector_labels"]
    }
    return expected, predicted


def _split_region(
    source: str,
    start: int,
    end: int,
    connectors: list[SpanKey],
) -> list[dict[str, Any]]:
    members: list[dict[str, Any]] = []
    cursor = start
    for connector_start, connector_end, _ in sorted(connectors):
        if not (start <= connector_start < connector_end <= end):
            continue
        members.append(_span(source, cursor, connector_start))
        cursor = connector_end
    members.append(_span(source, cursor, end))
    return members


def _unique_text(spans: list[dict[str, Any]]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for span in sorted(spans, key=lambda item: (item["start"], item["end"])):
        key = span["text"].casefold()
        if key not in seen:
            seen.add(key)
            result.append(span["text"])
    return result


def _candidate_spans(baseline: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        dict(item["span"])
        for item in baseline["parsed_clause"]["item_candidates"]
    ]


def _split_candidate_at(
    candidates: list[dict[str, Any]], connector: SpanKey, source: str
) -> list[dict[str, Any]]:
    connector_start, connector_end, _ = connector
    for index, candidate in enumerate(candidates):
        if candidate["start"] < connector_start < connector_end < candidate["end"]:
            replacement = [
                _span(source, candidate["start"], connector_start),
                _span(source, connector_end, candidate["end"]),
            ]
            return [*candidates[:index], *replacement, *candidates[index + 1 :]]
    raise ValueError(f"no candidate contains newly-surface connector {connector}")


def _merge_candidates_across(
    candidates: list[dict[str, Any]], connector: SpanKey, source: str
) -> list[dict[str, Any]]:
    connector_start, connector_end, _ = connector
    left_index = next(
        (
            index
            for index, candidate in enumerate(candidates)
            if candidate["end"] == connector_start
        ),
        None,
    )
    right_index = next(
        (
            index
            for index, candidate in enumerate(candidates)
            if candidate["start"] == connector_end
        ),
        None,
    )
    if left_index is None or right_index is None or right_index != left_index + 1:
        raise ValueError(f"no adjacent candidates around non-surface connector {connector}")
    merged = _span(
        source, candidates[left_index]["start"], candidates[right_index]["end"]
    )
    return [
        *candidates[:left_index],
        merged,
        *candidates[right_index + 1 :],
    ]


def _reproject_candidates(
    baseline: dict[str, Any], role_changes: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    source = baseline["source_text"]
    candidates = _candidate_spans(baseline)
    for change in sorted(role_changes, key=lambda item: item["span"]["start"]):
        connector = _span_key(change["span"])
        predicted_role = change["predicted_role"]
        expected_role = change["expected_role"]
        if predicted_role != "surface" and expected_role == "surface":
            candidates = _split_candidate_at(candidates, connector, source)
        elif predicted_role == "surface" and expected_role != "surface":
            candidates = _merge_candidates_across(candidates, connector, source)
    return candidates


def _members_from_group(
    group: dict[str, Any], roles: dict[SpanKey, str], source: str
) -> list[MemberKey]:
    connectors = [_span_key(item) for item in group["connector_spans"]]
    start = group["members"][0]["span"]["start"]
    end = group["members"][-1]["span"]["end"]
    surface_connectors = [item for item in connectors if roles.get(item) == "surface"]
    surface_chunks = _split_region(source, start, end, surface_connectors)
    members: list[MemberKey] = []

    if surface_connectors:
        members.extend(
            ("surface", _span_key(member))
            for member in _split_region(source, start, end, surface_connectors)
        )
    for role in ("embedded", "example"):
        role_connectors = [item for item in connectors if roles.get(item) == role]
        for chunk in surface_chunks:
            local = [
                item
                for item in role_connectors
                if chunk["start"] <= item[0] < item[1] <= chunk["end"]
            ]
            if local:
                members.extend(
                    (role, _span_key(member))
                    for member in _split_region(
                        source, chunk["start"], chunk["end"], local
                    )
                )
    return members


def _reconstruct_members(
    baseline: dict[str, Any], roles: dict[SpanKey, str]
) -> list[MemberKey]:
    parsed = baseline["parsed_clause"]
    source = baseline["source_text"]
    members: list[MemberKey] = []
    grouped_connectors: set[SpanKey] = set()
    for group in parsed["coordinations"]:
        grouped_connectors.update(_span_key(item) for item in group["connector_spans"])
        members.extend(_members_from_group(group, roles, source))

    for connector, role in sorted(roles.items()):
        if connector in grouped_connectors or role not in GROUP_ROLES:
            continue
        containing = next(
            (
                item
                for item in parsed["item_candidates"]
                if item["span"]["start"] < connector[0]
                and connector[1] < item["span"]["end"]
            ),
            None,
        )
        if containing is None:
            continue
        split_members = _split_region(
            source,
            containing["span"]["start"],
            containing["span"]["end"],
            [connector],
        )
        members.extend((role, _span_key(item)) for item in split_members)
    return members


def _serialize_members(members: list[MemberKey]) -> list[dict[str, Any]]:
    return [
        {
            "role": role,
            "span": {"start": span[0], "end": span[1], "text": span[2]},
        }
        for role, span in members
    ]


def _serialize_roles(roles: dict[SpanKey, str]) -> list[dict[str, Any]]:
    return [
        {
            "span": {"start": span[0], "end": span[1], "text": span[2]},
            "role": role,
        }
        for span, role in sorted(roles.items())
        if role != "none"
    ]


def _oracle_record(
    gold: dict[str, Any], baseline: dict[str, Any]
) -> dict[str, Any]:
    expected_roles, predicted_roles = _role_maps(gold, baseline)
    locations = sorted(set(expected_roles) | set(predicted_roles))
    role_changes = [
        {
            "span": {
                "start": span[0],
                "end": span[1],
                "text": span[2],
            },
            "predicted_role": predicted_roles.get(span, "none"),
            "expected_role": expected_roles.get(span, "none"),
        }
        for span in locations
        if predicted_roles.get(span, "none") != expected_roles.get(span, "none")
    ]
    treatment_roles = dict(predicted_roles)
    for change in role_changes:
        span = _span_key(change["span"])
        if change["expected_role"] == "none":
            treatment_roles.pop(span, None)
        else:
            treatment_roles[span] = change["expected_role"]

    baseline_members = _coordination_member_keys(baseline, gold=False)
    control_members = _reconstruct_members(baseline, predicted_roles)
    if Counter(control_members) != Counter(baseline_members):
        raise ValueError(f"control constructor drifted for {gold['id']}")
    baseline_candidates = _candidate_spans(baseline)
    if _unique_text(baseline_candidates) != baseline["items"]:
        raise ValueError(f"control projection drifted for {gold['id']}")
    treatment_candidates = _reproject_candidates(baseline, role_changes)

    attachment_edges = _attachment_edge_keys(baseline, gold=False)
    nuisance_state = {
        "wrappers": baseline["parsed_clause"]["wrappers"],
        "shared_scopes": baseline["parsed_clause"]["shared_scopes"],
    }
    return {
        "id": gold["id"],
        "job_id": gold["job_id"],
        "category": gold["category"],
        "source_text": gold["source_text"],
        "role_changes": role_changes,
        "nuisance_state_held_fixed": nuisance_state,
        "control": {
            "connector_labels": _serialize_roles(predicted_roles),
            "coordination_members": _serialize_members(control_members),
            "surface_items": baseline["items"],
            "example_attachment_edges": attachment_edges,
        },
        "treatment": {
            "connector_labels": _serialize_roles(treatment_roles),
            "coordination_members": _serialize_members(
                _reconstruct_members(baseline, treatment_roles)
            ),
            "surface_items": _unique_text(treatment_candidates),
            "example_attachment_edges": attachment_edges,
        },
    }


def _member_keys(arm: dict[str, Any]) -> list[MemberKey]:
    return [
        (item["role"], _span_key(item["span"]))
        for item in arm["coordination_members"]
    ]


def _role_map_from_arm(arm: dict[str, Any]) -> dict[SpanKey, str]:
    return {
        _span_key(item["span"]): item["role"] for item in arm["connector_labels"]
    }


def _attachment_keys(arm: dict[str, Any]) -> list[AttachmentEdgeKey]:
    return [
        (
            tuple(item[0]),
            tuple(item[1]),
            tuple(item[2]),
        )
        for item in arm["example_attachment_edges"]
    ]


def _gold_attachment_keys(gold: dict[str, Any]) -> list[AttachmentEdgeKey]:
    return _attachment_edge_keys(gold, gold=True)


def _difference_count(expected: list[Any], predicted: list[Any]) -> int:
    left = Counter(expected)
    right = Counter(predicted)
    return sum((left - right).values()) + sum((right - left).values())


def _fixture_counts(gold: dict[str, Any], arm: dict[str, Any]) -> dict[str, int]:
    return {
        "coordination_members": _difference_count(
            _coordination_member_keys(gold, gold=True), _member_keys(arm)
        ),
        "example_attachment_edges": _difference_count(
            _gold_attachment_keys(gold), _attachment_keys(arm)
        ),
        "surface_projection": _difference_count(
            gold["projection"]["surface_items"], arm["surface_items"]
        ),
    }


def _aggregate(
    fixture_ids: list[str],
    gold_by_id: dict[str, dict[str, Any]],
    records_by_id: dict[str, dict[str, Any]],
    arm_name: str,
) -> dict[str, Any]:
    pairs = [(gold_by_id[x], records_by_id[x][arm_name]) for x in fixture_ids]
    connector_pairs = []
    for gold, arm in pairs:
        expected = {
            _span_key(item["span"]): item["role"]
            for item in gold["connector_labels"]
        }
        predicted = _role_map_from_arm(arm)
        locations = set(expected) | set(predicted)
        connector_pairs.append(
            (
                [(span, expected.get(span, "none")) for span in locations],
                [(span, predicted.get(span, "none")) for span in locations],
            )
        )
    return {
        "connector_roles": _metric(connector_pairs),
        "coordination_members": _metric(
            (
                (_coordination_member_keys(gold, gold=True), _member_keys(arm))
                for gold, arm in pairs
            )
        ),
        "example_attachment_edges": _metric(
            (
                (_gold_attachment_keys(gold), _attachment_keys(arm))
                for gold, arm in pairs
            )
        ),
        "surface_projection": _metric(
            (
                (gold["projection"]["surface_items"], arm["surface_items"])
                for gold, arm in pairs
            )
        ),
    }


def _build_report(
    plan: dict[str, Any], dataset: dict[str, Any], raw: dict[str, Any]
) -> dict[str, Any]:
    gold_by_id = {item["id"]: item["gold"] for item in dataset["fixtures"]}
    records_by_id = {item["id"]: item for item in raw["records"]}
    target_ids = plan["target_fixture_ids"]
    control_ids = plan["control_fixture_ids"]
    per_fixture: list[dict[str, Any]] = []
    improved_target_ids: list[str] = []
    control_regressions: dict[str, list[str]] = {}

    for fixture_id in [*target_ids, *control_ids]:
        record = records_by_id[fixture_id]
        control_counts = _fixture_counts(gold_by_id[fixture_id], record["control"])
        treatment_counts = _fixture_counts(
            gold_by_id[fixture_id], record["treatment"]
        )
        improved_outcomes = [
            outcome
            for outcome in PRIMARY_OUTCOMES
            if treatment_counts[outcome] < control_counts[outcome]
        ]
        regressed_outcomes = [
            outcome
            for outcome in PRIMARY_OUTCOMES
            if treatment_counts[outcome] > control_counts[outcome]
        ]
        if fixture_id in target_ids and improved_outcomes:
            improved_target_ids.append(fixture_id)
        if fixture_id in control_ids:
            control_regressions[fixture_id] = regressed_outcomes
        per_fixture.append(
            {
                "id": fixture_id,
                "role": "target" if fixture_id in target_ids else "control",
                "source_text": record["source_text"],
                "role_changes": record["role_changes"],
                "control_difference_counts": control_counts,
                "treatment_difference_counts": treatment_counts,
                "improved_outcomes": improved_outcomes,
                "regressed_outcomes": regressed_outcomes,
                "control_surface_items": record["control"]["surface_items"],
                "treatment_surface_items": record["treatment"]["surface_items"],
            }
        )

    error_count = sum(len(item["role_changes"]) for item in raw["records"])
    no_control_regression = all(not value for value in control_regressions.values())
    accepted = len(improved_target_ids) >= 4 and no_control_regression
    target_control = _aggregate(target_ids, gold_by_id, records_by_id, "control")
    target_treatment = _aggregate(
        target_ids, gold_by_id, records_by_id, "treatment"
    )
    attachment_improved = (
        target_treatment["example_attachment_edges"]["f1"]
        > target_control["example_attachment_edges"]["f1"]
    )

    return {
        "report_version": (
            "unified-jd-structured-span-v4-e3-connector-role-oracle-report-v1"
        ),
        "created_at": "2026-09-04",
        "scope": {
            "status": "revealed_development_causal_experiment",
            "experiment_id": plan["id"],
            "generalization_claim": False,
            "threshold_selection_allowed": False,
            "frozen_v4_modified": False,
            "v4_parser_executed": False,
            "baseline_reused": True,
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
            "e2_acceptance": {
                "path": _relative(E2_REPORT_PATH),
                "sha256": EXPECTED_HASHES[E2_REPORT_PATH],
            },
            "frozen_v4_source": {
                "path": _relative(PARSER_PATH),
                "sha256": EXPECTED_HASHES[PARSER_PATH],
            },
            "oracle_raw": {
                "path": _relative(RAW_OUTPUT_PATH),
                "sha256": _sha256(RAW_OUTPUT_PATH),
            },
        },
        "registered_hypothesis": plan["hypothesis"],
        "registered_intervention": plan["intervention"],
        "operationalization": {
            "control": (
                "Reconstruct current members and projection from existing candidates "
                "using predicted connector roles. The constructor is required to "
                "reproduce stored baseline members and items."
            ),
            "treatment": (
                "Change only the nine incorrect connector token roles. Surface tokens "
                "split existing operands; embedded, example, and quantifier tokens "
                "coarsen outer surface operands. No gold member boundary is injected."
            ),
            "held_fixed": (
                "Predicted wrapper spans, predicted scope spans and target IDs, source "
                "segments, attachment edges, and all non-error connector roles."
            ),
            "limitation": (
                "The oracle cannot infer a missing wrapper, fine-grained nested-member "
                "boundary, attachment parent, or attachment edge."
            ),
        },
        "connector_role_error_count": error_count,
        "target_fixture_ids": target_ids,
        "control_fixture_ids": control_ids,
        "aggregate": {
            "targets": {
                "control": target_control,
                "treatment": target_treatment,
            },
            "controls": {
                "control": _aggregate(
                    control_ids, gold_by_id, records_by_id, "control"
                ),
                "treatment": _aggregate(
                    control_ids, gold_by_id, records_by_id, "treatment"
                ),
            },
        },
        "records": per_fixture,
        "decision": {
            "accepted": accepted,
            "improved_target_count": len(improved_target_ids),
            "required_improved_target_count": 4,
            "improved_target_ids": improved_target_ids,
            "control_regressions": control_regressions,
            "no_control_regression": no_control_regression,
            "attachment_improved": attachment_improved,
            "conclusion": (
                "Correct connector roles independently improve downstream member or "
                "surface outcomes beyond wrapper effects."
                if accepted
                else "E3 does not establish an independent connector-role contribution."
            ),
            "attachment_conclusion": (
                "Role correction alone improves attachment edges."
                if attachment_improved
                else "Role correction alone does not create missing attachment edges; attachment remains a separate mechanism."
            ),
            "next_action": (
                "Retain region-first connector classification as a v5 candidate, but "
                "run E4 scope candidate/application before combining mechanisms."
                if accepted
                else "Do not add a connector-role mechanism; proceed to E4."
            ),
        },
    }


def _metric_change(report: dict[str, Any], outcome: str) -> str:
    aggregate = report["aggregate"]["targets"]
    control = aggregate["control"][outcome]["f1"]
    treatment = aggregate["treatment"][outcome]["f1"]
    return f"{control:.4f} -> {treatment:.4f}"


def _render_findings(report: dict[str, Any]) -> str:
    decision = report["decision"]
    lines = [
        "# E3 region-first connector-role oracle experiment",
        "",
        "## Scope",
        "",
        "- Revealed development data only; no generalization claim.",
        "- Frozen v4 and the stored baseline were not executed or modified.",
        "- Predicted wrappers, scopes, and attachment edges are held fixed.",
        "- No gold member boundaries or attachment parents are injected.",
        "",
        "## Result",
        "",
        (
            f"Targets with a better downstream primary outcome: "
            f"{decision['improved_target_count']}/6 "
            f"(required: {decision['required_improved_target_count']}/6)."
        ),
        f"Corrected connector tokens: {report['connector_role_error_count']}.",
        f"Control regression: {'no' if decision['no_control_regression'] else 'yes'}.",
        f"Decision: **{'accepted' if decision['accepted'] else 'rejected'}**.",
        "",
        "## Target metrics",
        "",
        "| Metric | Predicted roles -> gold roles |",
        "|---|---:|",
        f"| Connector-role F1 | {_metric_change(report, 'connector_roles')} |",
        f"| Coordination-member F1 | {_metric_change(report, 'coordination_members')} |",
        (
            "| Example-attachment-edge F1 | "
            f"{_metric_change(report, 'example_attachment_edges')} |"
        ),
        f"| Surface projection F1 | {_metric_change(report, 'surface_projection')} |",
        "",
        "## Per-target differences",
        "",
        "| Fixture | Member | Attachment | Surface | Improved outcomes |",
        "|---|---:|---:|---:|---|",
    ]
    for record in report["records"]:
        if record["role"] != "target":
            continue
        control = record["control_difference_counts"]
        treatment = record["treatment_difference_counts"]
        improved = ", ".join(record["improved_outcomes"]) or "none"
        lines.append(
            f"| `{record['id']}` | "
            f"{control['coordination_members']} -> "
            f"{treatment['coordination_members']} | "
            f"{control['example_attachment_edges']} -> "
            f"{treatment['example_attachment_edges']} | "
            f"{control['surface_projection']} -> "
            f"{treatment['surface_projection']} | {improved} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            decision["conclusion"],
            "",
            decision["attachment_conclusion"],
            "",
            (
                "This separates two claims: region-first role assignment affects "
                "member and surface construction, while example attachment still "
                "requires its own parent-selection mechanism."
            ),
            "",
            "## Decision",
            "",
            decision["next_action"],
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    for path, expected_hash in EXPECTED_HASHES.items():
        actual_hash = _sha256(path)
        if actual_hash != expected_hash:
            raise ValueError(
                f"experiment input changed: {path}: {actual_hash} != {expected_hash}"
            )

    e2_report = _load(E2_REPORT_PATH)
    if e2_report["decision"]["accepted"] is not True:
        raise ValueError("E3 requires the recorded E2 wrapper-oracle acceptance")
    dataset = _load(DATASET_PATH)
    baseline_raw = _load(BASELINE_RAW_PATH)
    analysis = _load(ANALYSIS_PATH)
    plan = next(
        item
        for item in analysis["causal_experiment_plan"]
        if item["id"] == "E3-region-first-connector-role-oracle"
    )
    gold_by_id = {item["id"]: item["gold"] for item in dataset["fixtures"]}
    baseline_by_id = {item["id"]: item for item in baseline_raw["records"]}
    selected_ids = [*plan["target_fixture_ids"], *plan["control_fixture_ids"]]
    records = [
        _oracle_record(gold_by_id[fixture_id], baseline_by_id[fixture_id])
        for fixture_id in selected_ids
    ]
    error_count = sum(len(item["role_changes"]) for item in records)
    if error_count != 9:
        raise ValueError(f"expected nine connector role interventions, got {error_count}")

    raw = {
        "raw_version": (
            "unified-jd-structured-span-v4-e3-connector-role-oracle-raw-v1"
        ),
        "created_at": "2026-09-04",
        "status": "revealed_development_causal_experiment",
        "experiment_id": plan["id"],
        "baseline_reused": True,
        "v4_parser_executed": False,
        "frozen_v4_source": {
            "path": _relative(PARSER_PATH),
            "sha256_before": EXPECTED_HASHES[PARSER_PATH],
            "sha256_after": _sha256(PARSER_PATH),
            "modified": False,
        },
        "fixture_count": len(records),
        "connector_role_intervention_count": error_count,
        "gold_member_boundary_injection_count": 0,
        "gold_attachment_injection_count": 0,
        "model_call_count": 0,
        "network_call_count": 0,
        "records": records,
    }
    if raw["frozen_v4_source"]["sha256_after"] != EXPECTED_HASHES[PARSER_PATH]:
        raise ValueError("frozen v4 changed during E3")

    _write_json(RAW_OUTPUT_PATH, raw)
    report = _build_report(plan, dataset, raw)
    _write_json(REPORT_OUTPUT_PATH, report)
    FINDINGS_OUTPUT_PATH.write_text(_render_findings(report), encoding="utf-8")
    print(
        f"E3 accepted={report['decision']['accepted']} "
        f"improved_targets={report['decision']['improved_target_count']}/6 "
        f"attachment_improved={report['decision']['attachment_improved']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
