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
    _metric,
    _scope_edge_keys,
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
ANALYSIS_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-revealed-error-analysis-v1-2026-09-04.json"
)
E3_REPORT_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-e3-connector-role-oracle-report-v1-2026-09-04.json"
)
RAW_OUTPUT_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-e4-scope-candidate-application-raw-v1-2026-09-04.json"
)
REPORT_OUTPUT_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-e4-scope-candidate-application-report-v1-2026-09-04.json"
)
FINDINGS_OUTPUT_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-e4-scope-candidate-application-findings-v1-2026-09-04.md"
)

EXPECTED_HASHES = {
    PARSER_PATH: "e09e056cab75e651937391ce5410e6df7c94477c85565abb1425bbe85cfcb094",
    RULES_FREEZE_PATH: (
        "6a8a1d9ccce7c1069a483c7cc387221164de52800a133308922d57ff75ad6a12"
    ),
    DATASET_PATH: "965263881ff85bca636aa6ab87adaca24d74183fa13400709133323a3a6d5b73",
    ANALYSIS_PATH: "770d09ca956a55995609ad9f8c8e549a69b26097e6b18216e1b174f1f6c9a4b7",
    E3_REPORT_PATH: (
        "5dc74e90c81330b03a17554caff7d5e147011ff59f9e76019d5502fe0b67a28b"
    ),
}

TARGET_IDS = (
    "structured-corpus-external-v1-011",
    "structured-corpus-external-v1-012",
    "structured-corpus-external-v1-016",
    "structured-corpus-external-v1-017",
    "structured-corpus-external-v1-018",
    "structured-corpus-external-v1-020",
)
CONTROL_IDS = (
    "structured-corpus-external-v1-006",
    "structured-corpus-external-v1-013",
)
PRIMARY_OUTCOMES = (
    "shared_scope_edges",
    "false_shared_scope_edges",
    "surface_projection",
)
TERMINAL_HEADS = ("\u80fd\u529b", "\u7ecf\u9a8c", "\u57fa\u7840")

# These are the revealed semantic judgments under test. They are deliberately
# explicit so the experiment cannot be mistaken for a production heuristic.
COMPATIBILITY_JUDGMENTS = {
    ("structured-corpus-external-v1-006", 9, 11): (
        False,
        "singleton_is_a_complete_foundation_item",
    ),
    ("structured-corpus-external-v1-011", 24, 28): (
        True,
        "job_domains_share_work_experience_head",
    ),
    ("structured-corpus-external-v1-012", 9, 11): (
        False,
        "singleton_is_a_complete_capability_item",
    ),
    ("structured-corpus-external-v1-012", 23, 26): (
        True,
        "actions_share_capability_nominalizer",
    ),
    ("structured-corpus-external-v1-013", 7, 9): (
        False,
        "singleton_is_a_complete_experience_item",
    ),
    ("structured-corpus-external-v1-016", 7, 9): (
        False,
        "singleton_cannot_have_distributed_scope",
    ),
    ("structured-corpus-external-v1-017", 14, 16): (
        False,
        "left_member_is_an_independent_habit_not_an_ability",
    ),
    ("structured-corpus-external-v1-018", 4, 17): (
        True,
        "research_and_practice_share_domain_modifier",
    ),
    ("structured-corpus-external-v1-018", 22, 24): (
        True,
        "research_and_practice_share_experience_head",
    ),
    ("structured-corpus-external-v1-020", 12, 14): (
        True,
        "communication_members_share_capability_head",
    ),
}

SpanKey = tuple[int, int, str]
ScopeEdgeKey = tuple[str, SpanKey, SpanKey]


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
        raise ValueError("scope experiment produced an empty span")
    return {"text": source[start:end], "start": start, "end": end}


def _contains(container: dict[str, Any], value: dict[str, Any]) -> bool:
    return container["start"] <= value["start"] and value["end"] <= container["end"]


def _overlaps(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return left["start"] < right["end"] and right["start"] < left["end"]


def _scope_kind(text: str, *, prefix: bool = False) -> str | None:
    if prefix and text.endswith("\u7684"):
        return "prefix"
    if text.endswith("\u7ecf\u9a8c"):
        return "evidence"
    if text.endswith(("\u80fd\u529b", "\u57fa\u7840")):
        return "suffix"
    return None


def _coordination_groups(gold: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "id": f"group-{index}",
            "role": group["role"],
            "member_spans": [dict(item) for item in group["member_spans"]],
        }
        for index, group in enumerate(gold["coordinations"], start=1)
    ]


def _wrapper_contents(gold: dict[str, Any]) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    seen: set[SpanKey] = set()
    for wrapper in gold["wrappers"]:
        content = dict(wrapper["content_span"])
        key = _span_key(content)
        if key not in seen:
            seen.add(key)
            values.append(content)
    return values


def _candidate(
    *,
    kind: str,
    span: dict[str, Any],
    target_type: str,
    target_id: str,
    member_spans: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "kind": kind,
        "span": span,
        "target_type": target_type,
        "target_id": target_id,
        "member_spans": [dict(item) for item in member_spans],
    }


def _discover_candidates(gold: dict[str, Any]) -> list[dict[str, Any]]:
    source = gold["source_text"]
    groups = _coordination_groups(gold)
    contents = _wrapper_contents(gold)
    candidates: list[dict[str, Any]] = []
    all_members = [
        member for group in groups for member in group["member_spans"]
    ]

    for group in groups:
        members = group["member_spans"]
        containing = [
            item
            for item in contents
            if all(_contains(item, member) for member in members)
        ]
        if not containing:
            raise ValueError(f"no gold wrapper region for {gold['id']} {group['id']}")
        region_start = min(item["start"] for item in containing)
        region_end = max(item["end"] for item in containing)
        first_member = members[0]
        last_member = members[-1]

        if region_start < first_member["start"]:
            prefix = _span(source, region_start, first_member["start"])
            kind = _scope_kind(prefix["text"], prefix=True)
            if kind is not None:
                candidates.append(
                    _candidate(
                        kind=kind,
                        span=prefix,
                        target_type="coordination",
                        target_id=group["id"],
                        member_spans=members,
                    )
                )

        if last_member["end"] < region_end:
            suffix = _span(source, last_member["end"], region_end)
            kind = _scope_kind(suffix["text"])
            if kind is not None:
                candidates.append(
                    _candidate(
                        kind=kind,
                        span=suffix,
                        target_type="coordination",
                        target_id=group["id"],
                        member_spans=members,
                    )
                )

        candidate_ends = {item["span"]["end"] for item in candidates}
        for head in TERMINAL_HEADS:
            if last_member["text"].endswith(head) and last_member["end"] not in candidate_ends:
                head_span = _span(
                    source, last_member["end"] - len(head), last_member["end"]
                )
                candidates.append(
                    _candidate(
                        kind=_scope_kind(head) or "suffix",
                        span=head_span,
                        target_type="coordination",
                        target_id=group["id"],
                        member_spans=members,
                    )
                )
                break

    independent_contents = [
        item
        for item in contents
        if not any(_overlaps(item, member) for member in all_members)
    ]
    for index, content in enumerate(independent_contents, start=1):
        for head in TERMINAL_HEADS:
            if not content["text"].endswith(head):
                continue
            head_span = _span(source, content["end"] - len(head), content["end"])
            candidates.append(
                _candidate(
                    kind=_scope_kind(head) or "suffix",
                    span=head_span,
                    target_type="singleton",
                    target_id=f"singleton-{index}",
                    member_spans=[content],
                )
            )
            break

    unique: dict[tuple[Any, ...], dict[str, Any]] = {}
    for item in candidates:
        key = (
            item["kind"],
            _span_key(item["span"]),
            item["target_type"],
            item["target_id"],
        )
        unique.setdefault(key, item)
    return sorted(
        unique.values(),
        key=lambda item: (item["span"]["start"], item["span"]["end"], item["kind"]),
    )


def _base_surface_spans(gold: dict[str, Any]) -> list[dict[str, Any]]:
    groups = _coordination_groups(gold)
    members = [member for group in groups for member in group["member_spans"]]
    independent_contents = [
        item
        for item in _wrapper_contents(gold)
        if not any(_overlaps(item, member) for member in members)
    ]
    values = [*members, *independent_contents]
    unique = {_span_key(item): dict(item) for item in values}
    return sorted(unique.values(), key=lambda item: (item["start"], item["end"]))


def _apply_projection(
    source: str,
    base_spans: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    arm: str,
) -> list[str]:
    spans = [dict(item) for item in base_spans]
    for candidate in candidates:
        applied = (
            candidate["topology_applied"]
            if arm == "topology_only"
            else candidate["compatibility_applied"]
        )
        if not applied:
            continue
        scope = candidate["span"]
        overlap_found = False
        for index, item in enumerate(spans):
            if not _overlaps(item, scope):
                continue
            overlap_found = True
            if item["start"] < scope["start"] and scope["end"] == item["end"]:
                spans[index] = _span(source, item["start"], scope["start"])
        if (
            candidate["kind"] == "evidence"
            and not overlap_found
            and len(scope["text"]) > len("\u7ecf\u9a8c")
        ):
            spans.append(dict(scope))

    result: list[str] = []
    seen: set[str] = set()
    for item in sorted(spans, key=lambda value: (value["start"], value["end"])):
        key = item["text"].casefold()
        if key not in seen:
            seen.add(key)
            result.append(item["text"])
    return result


def _serialize_edges(candidates: list[dict[str, Any]], arm: str) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    for candidate in candidates:
        applied = (
            candidate["topology_applied"]
            if arm == "topology_only"
            else candidate["compatibility_applied"]
        )
        if not applied:
            continue
        for member in candidate["member_spans"]:
            edges.append(
                {
                    "kind": candidate["kind"],
                    "scope_span": dict(candidate["span"]),
                    "member_span": dict(member),
                }
            )
    return edges


def _record(gold: dict[str, Any]) -> dict[str, Any]:
    candidates = _discover_candidates(gold)
    for index, candidate in enumerate(candidates, start=1):
        key = (gold["id"], candidate["span"]["start"], candidate["span"]["end"])
        if key not in COMPATIBILITY_JUDGMENTS:
            raise ValueError(f"missing compatibility judgment for {key}")
        compatible, rationale = COMPATIBILITY_JUDGMENTS[key]
        candidate["id"] = f"scope-candidate-{index}"
        candidate["topology_applied"] = True
        candidate["compatibility_applied"] = compatible
        candidate["compatibility_rationale"] = rationale

    base_spans = _base_surface_spans(gold)
    return {
        "id": gold["id"],
        "job_id": gold["job_id"],
        "category": gold["category"],
        "source_text": gold["source_text"],
        "nuisance_state": {
            "gold_wrappers": gold["wrappers"],
            "gold_coordination_members": _coordination_groups(gold),
            "base_surface_spans": base_spans,
        },
        "scope_candidates": candidates,
        "topology_only": {
            "shared_scope_edges": _serialize_edges(candidates, "topology_only"),
            "surface_items": _apply_projection(
                gold["source_text"], base_spans, candidates, "topology_only"
            ),
        },
        "compatibility": {
            "shared_scope_edges": _serialize_edges(candidates, "compatibility"),
            "surface_items": _apply_projection(
                gold["source_text"], base_spans, candidates, "compatibility"
            ),
        },
    }


def _edge_keys(arm: dict[str, Any]) -> list[ScopeEdgeKey]:
    return [
        (
            item["kind"],
            _span_key(item["scope_span"]),
            _span_key(item["member_span"]),
        )
        for item in arm["shared_scope_edges"]
    ]


def _difference_count(expected: list[Any], predicted: list[Any]) -> int:
    left = Counter(expected)
    right = Counter(predicted)
    return sum((left - right).values()) + sum((right - left).values())


def _false_count(expected: list[Any], predicted: list[Any]) -> int:
    return sum((Counter(predicted) - Counter(expected)).values())


def _fixture_counts(gold: dict[str, Any], arm: dict[str, Any]) -> dict[str, int]:
    gold_edges = _scope_edge_keys(gold, gold=True)
    predicted_edges = _edge_keys(arm)
    return {
        "shared_scope_edges": _difference_count(gold_edges, predicted_edges),
        "false_shared_scope_edges": _false_count(gold_edges, predicted_edges),
        "surface_projection": _difference_count(
            gold["projection"]["surface_items"], arm["surface_items"]
        ),
    }


def _aggregate(
    fixture_ids: tuple[str, ...],
    gold_by_id: dict[str, dict[str, Any]],
    records_by_id: dict[str, dict[str, Any]],
    arm_name: str,
) -> dict[str, Any]:
    pairs = [(gold_by_id[item], records_by_id[item][arm_name]) for item in fixture_ids]
    edge_metrics = _metric(
        (
            (_scope_edge_keys(gold, gold=True), _edge_keys(arm))
            for gold, arm in pairs
        )
    )
    surface_metrics = _metric(
        (
            (gold["projection"]["surface_items"], arm["surface_items"])
            for gold, arm in pairs
        )
    )
    return {
        "shared_scope_edges": edge_metrics,
        "false_shared_scope_edge_count": sum(
            _false_count(_scope_edge_keys(gold, gold=True), _edge_keys(arm))
            for gold, arm in pairs
        ),
        "surface_projection": surface_metrics,
    }


def _find_candidate(record: dict[str, Any], start: int, end: int) -> dict[str, Any]:
    return next(
        item
        for item in record["scope_candidates"]
        if item["span"]["start"] == start and item["span"]["end"] == end
    )


def _build_report(
    plan: dict[str, Any], dataset: dict[str, Any], raw: dict[str, Any]
) -> dict[str, Any]:
    gold_by_id = {item["id"]: item["gold"] for item in dataset["fixtures"]}
    records_by_id = {item["id"]: item for item in raw["records"]}
    records: list[dict[str, Any]] = []
    improved_target_ids: list[str] = []
    control_regressions: dict[str, list[str]] = {}

    for fixture_id in (*TARGET_IDS, *CONTROL_IDS):
        gold = gold_by_id[fixture_id]
        raw_record = records_by_id[fixture_id]
        topology_counts = _fixture_counts(gold, raw_record["topology_only"])
        compatibility_counts = _fixture_counts(gold, raw_record["compatibility"])
        improved = [
            outcome
            for outcome in PRIMARY_OUTCOMES
            if compatibility_counts[outcome] < topology_counts[outcome]
        ]
        regressed = [
            outcome
            for outcome in PRIMARY_OUTCOMES
            if compatibility_counts[outcome] > topology_counts[outcome]
        ]
        if fixture_id in TARGET_IDS and improved:
            improved_target_ids.append(fixture_id)
        if fixture_id in CONTROL_IDS:
            control_regressions[fixture_id] = regressed
        records.append(
            {
                "id": fixture_id,
                "role": "target" if fixture_id in TARGET_IDS else "control",
                "source_text": gold["source_text"],
                "candidate_decisions": [
                    {
                        "kind": item["kind"],
                        "span": item["span"],
                        "target_type": item["target_type"],
                        "topology_applied": item["topology_applied"],
                        "compatibility_applied": item["compatibility_applied"],
                        "compatibility_rationale": item[
                            "compatibility_rationale"
                        ],
                    }
                    for item in raw_record["scope_candidates"]
                ],
                "topology_difference_counts": topology_counts,
                "compatibility_difference_counts": compatibility_counts,
                "improved_outcomes": improved,
                "regressed_outcomes": regressed,
                "topology_surface_items": raw_record["topology_only"][
                    "surface_items"
                ],
                "compatibility_surface_items": raw_record["compatibility"][
                    "surface_items"
                ],
            }
        )

    case_017 = records_by_id["structured-corpus-external-v1-017"]
    case_020 = records_by_id["structured-corpus-external-v1-020"]
    decision_017 = _find_candidate(case_017, 14, 16)
    decision_020 = _find_candidate(case_020, 12, 14)
    topology_treats_pair_same = (
        decision_017["topology_applied"] is True
        and decision_020["topology_applied"] is True
    )
    compatibility_distinguishes_pair = (
        decision_017["compatibility_applied"] is False
        and decision_020["compatibility_applied"] is True
    )
    case_016 = records_by_id["structured-corpus-external-v1-016"]
    singleton_016_avoided = (
        len(case_016["topology_only"]["shared_scope_edges"]) == 1
        and not case_016["compatibility"]["shared_scope_edges"]
    )
    no_control_regression = all(not value for value in control_regressions.values())
    accepted = (
        topology_treats_pair_same
        and compatibility_distinguishes_pair
        and singleton_016_avoided
        and len(improved_target_ids) >= 4
        and no_control_regression
    )

    return {
        "report_version": (
            "unified-jd-structured-span-v4-e4-scope-candidate-application-report-v1"
        ),
        "created_at": "2026-09-04",
        "scope": {
            "status": "revealed_development_causal_experiment",
            "experiment_id": plan["id"],
            "generalization_claim": False,
            "threshold_selection_allowed": False,
            "production_rule_claim": False,
            "frozen_v4_modified": False,
            "v4_parser_executed": False,
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
            "e3_report": {
                "path": _relative(E3_REPORT_PATH),
                "sha256": EXPECTED_HASHES[E3_REPORT_PATH],
            },
            "frozen_v4_source": {
                "path": _relative(PARSER_PATH),
                "sha256": EXPECTED_HASHES[PARSER_PATH],
            },
            "rules_freeze": {
                "path": _relative(RULES_FREEZE_PATH),
                "sha256": EXPECTED_HASHES[RULES_FREEZE_PATH],
            },
            "oracle_raw": {
                "path": _relative(RAW_OUTPUT_PATH),
                "sha256": _sha256(RAW_OUTPUT_PATH),
            },
        },
        "registered_hypothesis": plan["hypothesis"],
        "registered_intervention": plan["intervention"],
        "operationalization": {
            "candidate_discovery": (
                "Both arms use the same deterministic candidates from wrapper/member "
                "region residuals and terminal ability, experience, or foundation heads."
            ),
            "topology_only": (
                "Apply every discovered candidate to every member in its local "
                "coordination or singleton unit."
            ),
            "compatibility": (
                "Change only the application decision using ten explicit revealed "
                "member-head compatibility judgments."
            ),
            "held_fixed": (
                "Gold wrapper and coordination-member boundaries, candidate spans, "
                "candidate kinds, target units, and projection mechanics."
            ),
            "outcome_leakage_guard": (
                "Candidate discovery does not read gold shared scopes or projection; "
                "terminal heads are scanned even when a gold member contains the head."
            ),
            "limitation": (
                "Compatibility judgments are a diagnostic oracle on revealed data, "
                "not an implemented or generalized classifier."
            ),
        },
        "target_fixture_ids": list(TARGET_IDS),
        "control_fixture_ids": list(CONTROL_IDS),
        "aggregate": {
            "targets": {
                "topology_only": _aggregate(
                    TARGET_IDS, gold_by_id, records_by_id, "topology_only"
                ),
                "compatibility": _aggregate(
                    TARGET_IDS, gold_by_id, records_by_id, "compatibility"
                ),
            },
            "controls": {
                "topology_only": _aggregate(
                    CONTROL_IDS, gold_by_id, records_by_id, "topology_only"
                ),
                "compatibility": _aggregate(
                    CONTROL_IDS, gold_by_id, records_by_id, "compatibility"
                ),
            },
        },
        "records": records,
        "decision": {
            "accepted": accepted,
            "topology_treats_017_020_same": topology_treats_pair_same,
            "compatibility_distinguishes_017_020": compatibility_distinguishes_pair,
            "singleton_016_scope_avoided": singleton_016_avoided,
            "improved_target_count": len(improved_target_ids),
            "required_improved_target_count": 4,
            "improved_target_ids": improved_target_ids,
            "control_regressions": control_regressions,
            "no_control_regression": no_control_regression,
            "conclusion": (
                "Member-head compatibility is supported as a sufficient v5 scope mechanism."
                if accepted
                else "Compatibility changes scope application causally, but does not meet the registered breadth gate as a sufficient v5 mechanism."
            ),
            "next_action": (
                "Retain scope candidate/application separation for v5 design and run E5 before implementation."
                if accepted
                else "Do not implement the compatibility oracle as a v5 rule; run E5, then redesign candidate discovery and application before v5."
            ),
        },
    }


def _metric_change(report: dict[str, Any], layer: str) -> str:
    values = report["aggregate"]["targets"]
    left = values["topology_only"][layer]["f1"]
    right = values["compatibility"][layer]["f1"]
    return f"{left:.4f} -> {right:.4f}"


def _render_findings(report: dict[str, Any]) -> str:
    decision = report["decision"]
    targets = report["aggregate"]["targets"]
    lines = [
        "# E4 scope candidate versus application experiment",
        "",
        "## Scope",
        "",
        "- Revealed development data only; no generalization claim.",
        "- Frozen v4 was neither executed nor modified.",
        "- Both arms share gold wrapper/member nuisance boundaries and identical scope candidates.",
        "- No gold scope edge or gold projection is injected.",
        "- Compatibility decisions are a diagnostic oracle, not a production rule.",
        "",
        "## Result",
        "",
        (
            "Targets with a better downstream primary outcome: "
            f"{decision['improved_target_count']}/6 "
            f"(required: {decision['required_improved_target_count']}/6)."
        ),
        (
            "017/020 minimal pair distinguished: "
            f"{'yes' if decision['compatibility_distinguishes_017_020'] else 'no'}."
        ),
        (
            "Singleton 016 false scope avoided: "
            f"{'yes' if decision['singleton_016_scope_avoided'] else 'no'}."
        ),
        f"Control regression: {'no' if decision['no_control_regression'] else 'yes'}.",
        f"Decision: **{'accepted' if decision['accepted'] else 'rejected'}**.",
        "",
        "## Target metrics",
        "",
        "| Metric | Topology-only -> compatibility |",
        "|---|---:|",
        f"| Shared-scope-edge F1 | {_metric_change(report, 'shared_scope_edges')} |",
        (
            "| False shared-scope edges | "
            f"{targets['topology_only']['false_shared_scope_edge_count']} -> "
            f"{targets['compatibility']['false_shared_scope_edge_count']} |"
        ),
        f"| Surface projection F1 | {_metric_change(report, 'surface_projection')} |",
        "",
        "## Per-fixture differences",
        "",
        "| Fixture | Scope | False scope | Surface | Improved outcomes |",
        "|---|---:|---:|---:|---|",
    ]
    for record in report["records"]:
        if record["role"] != "target":
            continue
        left = record["topology_difference_counts"]
        right = record["compatibility_difference_counts"]
        outcomes = ", ".join(record["improved_outcomes"]) or "none"
        lines.append(
            f"| `{record['id']}` | "
            f"{left['shared_scope_edges']} -> {right['shared_scope_edges']} | "
            f"{left['false_shared_scope_edges']} -> {right['false_shared_scope_edges']} | "
            f"{left['surface_projection']} -> {right['surface_projection']} | "
            f"{outcomes} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            (
                "Compatibility is causally relevant: it separates 017 from 020, "
                "prevents the singleton error in 016, and removes false scope edges."
            ),
            (
                "However, the compatibility arm improves only "
                f"{decision['improved_target_count']}/6 targets, below the frozen 4/6 gate."
            ),
            (
                "The result does not justify encoding these revealed judgments as "
                "lexical constraints or claiming a generalized compatibility classifier."
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
    for path, expected in EXPECTED_HASHES.items():
        actual = _sha256(path)
        if actual != expected:
            raise ValueError(f"frozen input hash mismatch for {path}: {actual} != {expected}")

    analysis = _load(ANALYSIS_PATH)
    plan = next(
        item
        for item in analysis["causal_experiment_plan"]
        if item["id"] == "E4-scope-candidate-versus-application"
    )
    if tuple(plan["target_fixture_ids"]) != TARGET_IDS:
        raise ValueError("registered E4 targets changed")
    if tuple(plan["control_fixture_ids"]) != CONTROL_IDS:
        raise ValueError("registered E4 controls changed")
    if _load(E3_REPORT_PATH)["decision"]["accepted"] is not True:
        raise ValueError("E3 must be accepted before E4")

    dataset = _load(DATASET_PATH)
    gold_by_id = {item["id"]: item["gold"] for item in dataset["fixtures"]}
    selected_ids = (*TARGET_IDS, *CONTROL_IDS)
    parser_hash_before = _sha256(PARSER_PATH)
    records = [_record(gold_by_id[item]) for item in selected_ids]
    observed_judgments = {
        (record["id"], item["span"]["start"], item["span"]["end"])
        for record in records
        for item in record["scope_candidates"]
    }
    if observed_judgments != set(COMPATIBILITY_JUDGMENTS):
        raise ValueError(
            "scope candidate inventory drifted: "
            f"{observed_judgments ^ set(COMPATIBILITY_JUDGMENTS)}"
        )
    parser_hash_after = _sha256(PARSER_PATH)
    raw = {
        "raw_version": (
            "unified-jd-structured-span-v4-e4-scope-candidate-application-raw-v1"
        ),
        "created_at": "2026-09-04",
        "status": "revealed_development_causal_experiment",
        "experiment_id": plan["id"],
        "arms": ["topology_only", "compatibility"],
        "v4_parser_executed": False,
        "frozen_v4_source": {
            "path": _relative(PARSER_PATH),
            "sha256_before": parser_hash_before,
            "sha256_after": parser_hash_after,
            "modified": parser_hash_before != parser_hash_after,
        },
        "fixture_count": len(records),
        "scope_candidate_count": sum(
            len(item["scope_candidates"]) for item in records
        ),
        "compatibility_judgment_count": len(COMPATIBILITY_JUDGMENTS),
        "gold_wrapper_nuisance_count": sum(
            len(gold_by_id[item]["wrappers"]) for item in selected_ids
        ),
        "gold_member_boundary_nuisance_count": sum(
            len(group["member_spans"])
            for item in selected_ids
            for group in gold_by_id[item]["coordinations"]
        ),
        "gold_scope_edge_injection_count": 0,
        "gold_projection_injection_count": 0,
        "model_call_count": 0,
        "network_call_count": 0,
        "records": records,
    }
    if raw["frozen_v4_source"]["modified"]:
        raise ValueError("frozen v4 changed during E4")

    RAW_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _write_json(RAW_OUTPUT_PATH, raw)
    report = _build_report(plan, dataset, raw)
    _write_json(REPORT_OUTPUT_PATH, report)
    FINDINGS_OUTPUT_PATH.write_text(_render_findings(report), encoding="utf-8")
    print(
        f"E4 accepted={report['decision']['accepted']} "
        f"improved_targets={report['decision']['improved_target_count']}/6 "
        f"pair={report['decision']['compatibility_distinguishes_017_020']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
