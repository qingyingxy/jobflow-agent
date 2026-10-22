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

from scripts.run_unified_structured_span_v4_e1_dispatch_experiment import (
    _aggregate,
    _evaluate_fixture,
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
E1_REPORT_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-e1-dispatch-only-report-v1-2026-09-04.json"
)
RAW_OUTPUT_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-e2-wrapper-oracle-raw-v1-2026-09-04.json"
)
REPORT_OUTPUT_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-e2-wrapper-oracle-report-v1-2026-09-04.json"
)
FINDINGS_OUTPUT_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-e2-wrapper-oracle-findings-v1-2026-09-04.md"
)

EXPECTED_HASHES = {
    PARSER_PATH: "e09e056cab75e651937391ce5410e6df7c94477c85565abb1425bbe85cfcb094",
    DATASET_PATH: "965263881ff85bca636aa6ab87adaca24d74183fa13400709133323a3a6d5b73",
    BASELINE_RAW_PATH: (
        "36b65c1df79d856c7507ae1357ed24c10b7a3e383bad79b9471b124f4999e058"
    ),
    ANALYSIS_PATH: "770d09ca956a55995609ad9f8c8e549a69b26097e6b18216e1b174f1f6c9a4b7",
    E1_REPORT_PATH: (
        "724209b4b81e8a88ea04518f557183b7519accb2e03c61e7eb1f06c68d6ed60f"
    ),
}

PRIMARY_LAYERS = (
    "coordination_members",
    "shared_scope_edges",
    "surface_projection",
)


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


def _clip_span(
    span: dict[str, Any], marker_spans: list[dict[str, Any]], source: str
) -> tuple[dict[str, Any], bool]:
    start = span["start"]
    end = span["end"]
    for marker in marker_spans:
        if marker["start"] <= start < marker["end"] < end:
            start = marker["end"]
        elif start < marker["start"] < end <= marker["end"]:
            end = marker["start"]
        elif marker["start"] <= start and end <= marker["end"]:
            raise ValueError(f"wrapper marker consumes complete operand: {span}")
    if start >= end:
        raise ValueError(f"wrapper clipping produced an empty operand: {span}")
    clipped = {"text": source[start:end], "start": start, "end": end}
    return clipped, clipped != span


def _project(parsed_clause: dict[str, Any]) -> tuple[list[str], list[str]]:
    candidate_spans = [item["span"] for item in parsed_clause["item_candidates"]]

    items: list[str] = []
    seen_items: set[str] = set()
    for span in candidate_spans:
        key = span["text"].casefold()
        if key not in seen_items:
            seen_items.add(key)
            items.append(span["text"])

    examples: list[str] = []
    seen_examples: set[str] = set()
    for attachment in parsed_clause["example_attachments"]:
        parent = attachment["parent_span"]
        parent_is_projected = any(
            candidate["start"] < parent["end"]
            and parent["start"] < candidate["end"]
            for candidate in candidate_spans
        )
        if not parent_is_projected:
            continue
        for example in attachment["example_spans"]:
            key = example["text"].casefold()
            if key not in seen_examples:
                seen_examples.add(key)
                examples.append(example["text"])
    return items, examples


def _metadata_only(
    baseline: dict[str, Any], gold: dict[str, Any]
) -> dict[str, Any]:
    treatment = copy.deepcopy(baseline)
    treatment["parsed_clause"]["wrappers"] = copy.deepcopy(gold["wrappers"])
    return treatment


def _boundary_enforced(
    baseline: dict[str, Any], gold: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    treatment = _metadata_only(baseline, gold)
    parsed = treatment["parsed_clause"]
    source = treatment["source_text"]
    marker_spans = [item["marker_span"] for item in gold["wrappers"]]
    changed_candidate_ids: list[str] = []
    changed_member_ids: list[str] = []

    for candidate in parsed["item_candidates"]:
        candidate["span"], changed = _clip_span(
            candidate["span"], marker_spans, source
        )
        if changed:
            changed_candidate_ids.append(candidate["id"])
    for group in parsed["coordinations"]:
        for member in group["members"]:
            member["span"], changed = _clip_span(
                member["span"], marker_spans, source
            )
            if changed:
                changed_member_ids.append(member["id"])

    treatment["items"], treatment["examples"] = _project(parsed)
    return treatment, {
        "changed_candidate_ids": changed_candidate_ids,
        "changed_coordination_member_ids": changed_member_ids,
        "changed_candidate_count": len(changed_candidate_ids),
        "changed_coordination_member_count": len(changed_member_ids),
    }


def _metadata_downstream_payload(record: dict[str, Any]) -> dict[str, Any]:
    parsed = record["parsed_clause"]
    return {
        "error": record["error"],
        "items": record["items"],
        "examples": record["examples"],
        "rule_ids": record["rule_ids"],
        "protected_spans": parsed["protected_spans"],
        "segments": parsed["segments"],
        "connector_labels": parsed["connector_labels"],
        "coordinations": parsed["coordinations"],
        "shared_scopes": parsed["shared_scopes"],
        "example_attachments": parsed["example_attachments"],
        "item_candidates": parsed["item_candidates"],
    }


def _topology_payload(record: dict[str, Any]) -> dict[str, Any]:
    parsed = record["parsed_clause"]
    return {
        "error": record["error"],
        "rule_ids": record["rule_ids"],
        "protected_spans": parsed["protected_spans"],
        "segments": parsed["segments"],
        "connector_labels": parsed["connector_labels"],
        "groups": [
            {
                "id": group["id"],
                "role": group["role"],
                "kind": group["kind"],
                "connector_spans": group["connector_spans"],
                "member_ids": [member["id"] for member in group["members"]],
            }
            for group in parsed["coordinations"]
        ],
        "shared_scopes": parsed["shared_scopes"],
        "example_attachments": parsed["example_attachments"],
        "candidate_ids": [item["id"] for item in parsed["item_candidates"]],
    }


def _difference_count(evaluation: dict[str, Any], layer: str) -> int:
    difference = evaluation[layer]
    return len(difference["missing"]) + len(difference["unexpected"])


def _build_report(
    *,
    plan: dict[str, Any],
    dataset: dict[str, Any],
    baseline_raw: dict[str, Any],
    treatment_raw: dict[str, Any],
) -> dict[str, Any]:
    gold_by_id = {item["id"]: item["gold"] for item in dataset["fixtures"]}
    baseline_by_id = {item["id"]: item for item in baseline_raw["records"]}
    metadata_by_id = {
        item["id"]: item["metadata_only"] for item in treatment_raw["records"]
    }
    enforced_by_id = {
        item["id"]: item["boundary_enforced"]
        for item in treatment_raw["records"]
    }
    target_ids = plan["target_fixture_ids"]
    control_ids = plan["control_fixture_ids"]
    selected_ids = [*target_ids, *control_ids]

    records: list[dict[str, Any]] = []
    improved_target_ids: list[str] = []
    metadata_invariant: dict[str, bool] = {}
    topology_invariant: dict[str, bool] = {}
    control_regressions: dict[str, list[str]] = {}
    raw_by_id = {item["id"]: item for item in treatment_raw["records"]}

    for fixture_id in selected_ids:
        gold = gold_by_id[fixture_id]
        baseline = baseline_by_id[fixture_id]
        metadata = metadata_by_id[fixture_id]
        enforced = enforced_by_id[fixture_id]
        baseline_evaluation = _evaluate_fixture(gold, baseline)
        metadata_evaluation = _evaluate_fixture(gold, metadata)
        enforced_evaluation = _evaluate_fixture(gold, enforced)

        metadata_invariant[fixture_id] = (
            _metadata_downstream_payload(baseline)
            == _metadata_downstream_payload(metadata)
        )
        topology_invariant[fixture_id] = (
            _topology_payload(baseline) == _topology_payload(enforced)
        )
        layer_counts = {
            layer: {
                "baseline": _difference_count(baseline_evaluation, layer),
                "metadata_only": _difference_count(metadata_evaluation, layer),
                "boundary_enforced": _difference_count(enforced_evaluation, layer),
            }
            for layer in PRIMARY_LAYERS
        }
        member_or_surface_improved = any(
            layer_counts[layer]["boundary_enforced"]
            < layer_counts[layer]["baseline"]
            for layer in ("coordination_members", "surface_projection")
        )
        if fixture_id in target_ids and member_or_surface_improved:
            improved_target_ids.append(fixture_id)

        regressions = [
            layer
            for layer in PRIMARY_LAYERS
            if layer_counts[layer]["boundary_enforced"]
            > layer_counts[layer]["baseline"]
        ]
        if fixture_id in control_ids:
            control_regressions[fixture_id] = regressions

        records.append(
            {
                "id": fixture_id,
                "role": "target" if fixture_id in target_ids else "control",
                "source_text": gold["source_text"],
                "changed_spans": raw_by_id[fixture_id]["changed_spans"],
                "metadata_only_downstream_unchanged": metadata_invariant[fixture_id],
                "boundary_enforced_topology_unchanged": topology_invariant[fixture_id],
                "member_or_surface_improved": member_or_surface_improved,
                "layer_difference_counts": layer_counts,
                "baseline_items": baseline["items"],
                "metadata_only_items": metadata["items"],
                "boundary_enforced_items": enforced["items"],
            }
        )

    no_control_regression = all(not value for value in control_regressions.values())
    invariants_passed = all(metadata_invariant.values()) and all(
        topology_invariant.values()
    )
    accepted = (
        len(improved_target_ids) >= 4
        and no_control_regression
        and invariants_passed
    )

    return {
        "report_version": (
            "unified-jd-structured-span-v4-e2-wrapper-oracle-report-v1"
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
            "e1_rejection": {
                "path": _relative(E1_REPORT_PATH),
                "sha256": EXPECTED_HASHES[E1_REPORT_PATH],
            },
            "frozen_v4_source": {
                "path": _relative(PARSER_PATH),
                "sha256": EXPECTED_HASHES[PARSER_PATH],
            },
            "treatment_raw": {
                "path": _relative(RAW_OUTPUT_PATH),
                "sha256": _sha256(RAW_OUTPUT_PATH),
            },
        },
        "registered_hypothesis": plan["hypothesis"],
        "registered_intervention": plan["intervention"],
        "operationalization": {
            "metadata_only": (
                "Replace only parsed_clause.wrappers with gold wrappers. Every "
                "downstream object and projection output remains byte-equivalent."
            ),
            "boundary_enforced": (
                "Use gold wrapper marker spans only as exclusion boundaries at the "
                "edges of existing item candidates and coordination members; preserve "
                "all topology, connector roles, scope IDs/targets, attachments, and "
                "rules, then reapply unchanged projection semantics."
            ),
            "limitation": (
                "The oracle cannot create a missing member, group, scope, or attachment, "
                "so measured downstream gains are a conservative lower bound."
            ),
        },
        "acceptance_interpretation": (
            "A target improves when its missing+unexpected count decreases in either "
            "coordination_members or surface_projection. A control regresses if that "
            "count increases in coordination_members, shared_scope_edges, or "
            "surface_projection."
        ),
        "target_fixture_ids": target_ids,
        "control_fixture_ids": control_ids,
        "aggregate": {
            "targets": {
                "baseline": _aggregate(target_ids, gold_by_id, baseline_by_id),
                "metadata_only": _aggregate(target_ids, gold_by_id, metadata_by_id),
                "boundary_enforced": _aggregate(
                    target_ids, gold_by_id, enforced_by_id
                ),
            },
            "controls": {
                "baseline": _aggregate(control_ids, gold_by_id, baseline_by_id),
                "metadata_only": _aggregate(control_ids, gold_by_id, metadata_by_id),
                "boundary_enforced": _aggregate(
                    control_ids, gold_by_id, enforced_by_id
                ),
            },
        },
        "records": records,
        "decision": {
            "accepted": accepted,
            "improved_target_count": len(improved_target_ids),
            "required_improved_target_count": 4,
            "improved_target_ids": improved_target_ids,
            "metadata_only_downstream_unchanged": all(metadata_invariant.values()),
            "boundary_enforced_topology_unchanged": all(
                topology_invariant.values()
            ),
            "control_regressions": control_regressions,
            "no_control_regression": no_control_regression,
            "conclusion": (
                "Gold wrapper metadata alone has no downstream effect, but enforcing "
                "those boundaries on existing operands causally reduces member or "
                "surface errors in enough targets to accept wrapper-boundary "
                "contamination as a v5 mechanism."
                if accepted
                else "E2 does not establish wrapper-boundary contamination as a sufficient v5 mechanism."
            ),
            "next_action": (
                "Design a production wrapper-boundary stage separately, then run E3 "
                "before combining mechanisms. Do not copy gold-derived boundaries "
                "into v5."
                if accepted
                else "Proceed to E3 without implementing a wrapper-boundary mechanism."
            ),
        },
    }


def _metric_change(report: dict[str, Any], layer: str) -> str:
    aggregate = report["aggregate"]["targets"]
    baseline = aggregate["baseline"][layer]["f1"]
    treatment = aggregate["boundary_enforced"][layer]["f1"]
    return f"{baseline:.4f} -> {treatment:.4f}"


def _render_findings(report: dict[str, Any]) -> str:
    decision = report["decision"]
    lines = [
        "# E2 wrapper-boundary oracle experiment",
        "",
        "## Scope",
        "",
        "- Revealed development data only; no generalization claim.",
        "- Frozen v4 and the stored baseline were not executed or modified.",
        "- This is a diagnostic oracle, not a production parser implementation.",
        "- Connector roles, topology, scope targets, attachments, and rules stay fixed.",
        "",
        "## Result",
        "",
        (
            f"Targets with lower member or surface difference count: "
            f"{decision['improved_target_count']}/8 "
            f"(required: {decision['required_improved_target_count']}/8)."
        ),
        (
            "Metadata-only downstream unchanged: "
            f"{'yes' if decision['metadata_only_downstream_unchanged'] else 'no'}."
        ),
        (
            "Boundary-enforced topology unchanged: "
            f"{'yes' if decision['boundary_enforced_topology_unchanged'] else 'no'}."
        ),
        f"Control regression: {'no' if decision['no_control_regression'] else 'yes'}.",
        f"Decision: **{'accepted' if decision['accepted'] else 'rejected'}**.",
        "",
        "## Target metrics",
        "",
        "| Metric | Baseline -> boundary enforced |",
        "|---|---:|",
        f"| Coordination-member F1 | {_metric_change(report, 'coordination_members')} |",
        f"| Shared-scope-edge F1 | {_metric_change(report, 'shared_scope_edges')} |",
        f"| Surface projection F1 | {_metric_change(report, 'surface_projection')} |",
        "",
        "## Per-target differences",
        "",
        "| Fixture | Member | Scope | Surface | Improved |",
        "|---|---:|---:|---:|:---:|",
    ]
    for record in report["records"]:
        if record["role"] != "target":
            continue
        counts = record["layer_difference_counts"]
        lines.append(
            f"| `{record['id']}` | "
            f"{counts['coordination_members']['baseline']} -> "
            f"{counts['coordination_members']['boundary_enforced']} | "
            f"{counts['shared_scope_edges']['baseline']} -> "
            f"{counts['shared_scope_edges']['boundary_enforced']} | "
            f"{counts['surface_projection']['baseline']} -> "
            f"{counts['surface_projection']['boundary_enforced']} | "
            f"{'yes' if record['member_or_surface_improved'] else 'no'} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            decision["conclusion"],
            "",
            (
                "Because the oracle never creates missing topology, the measured "
                "improvement is a lower bound. Metadata replacement alone changes no "
                "downstream output, proving that wrapper spans must constrain member "
                "construction rather than remain passive annotations."
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

    e1_report = _load(E1_REPORT_PATH)
    if e1_report["decision"]["accepted"] is not False:
        raise ValueError("E2 requires the recorded E1 dispatch-only rejection")
    dataset = _load(DATASET_PATH)
    baseline_raw = _load(BASELINE_RAW_PATH)
    analysis = _load(ANALYSIS_PATH)
    plan = next(
        item
        for item in analysis["causal_experiment_plan"]
        if item["id"] == "E2-wrapper-boundary-oracle"
    )
    gold_by_id = {item["id"]: item["gold"] for item in dataset["fixtures"]}
    baseline_by_id = {item["id"]: item for item in baseline_raw["records"]}
    selected_ids = [*plan["target_fixture_ids"], *plan["control_fixture_ids"]]

    treatment_records = []
    for fixture_id in selected_ids:
        baseline = baseline_by_id[fixture_id]
        gold = gold_by_id[fixture_id]
        metadata = _metadata_only(baseline, gold)
        enforced, changed_spans = _boundary_enforced(baseline, gold)
        treatment_records.append(
            {
                "id": fixture_id,
                "job_id": gold["job_id"],
                "category": gold["category"],
                "source_text": gold["source_text"],
                "changed_spans": changed_spans,
                "metadata_only": metadata,
                "boundary_enforced": enforced,
            }
        )

    treatment_raw = {
        "raw_version": (
            "unified-jd-structured-span-v4-e2-wrapper-oracle-raw-v1"
        ),
        "created_at": "2026-09-04",
        "status": "revealed_development_causal_experiment",
        "experiment_id": plan["id"],
        "arms": ["metadata_only", "boundary_enforced"],
        "baseline_reused": True,
        "v4_parser_executed": False,
        "frozen_v4_source": {
            "path": _relative(PARSER_PATH),
            "sha256_before": EXPECTED_HASHES[PARSER_PATH],
            "sha256_after": _sha256(PARSER_PATH),
            "modified": False,
        },
        "fixture_count": len(treatment_records),
        "model_call_count": 0,
        "network_call_count": 0,
        "records": treatment_records,
    }
    if treatment_raw["frozen_v4_source"]["sha256_after"] != EXPECTED_HASHES[
        PARSER_PATH
    ]:
        raise ValueError("frozen v4 changed during E2")

    _write_json(RAW_OUTPUT_PATH, treatment_raw)
    report = _build_report(
        plan=plan,
        dataset=dataset,
        baseline_raw=baseline_raw,
        treatment_raw=treatment_raw,
    )
    _write_json(REPORT_OUTPUT_PATH, report)
    FINDINGS_OUTPUT_PATH.write_text(_render_findings(report), encoding="utf-8")
    print(
        f"E2 accepted={report['decision']['accepted']} "
        f"improved_targets={report['decision']['improved_target_count']}/8 "
        f"control_regression={not report['decision']['no_control_regression']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
