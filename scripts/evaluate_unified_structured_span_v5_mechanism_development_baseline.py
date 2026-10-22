from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from scripts.evaluate_unified_structured_span_v4_development import (
    evaluate_predictions,
    run_predictions,
)

ROOT = Path(__file__).resolve().parents[1]
DATE = "2026-09-04"
LABELS_PATH = (
    ROOT
    / "datasets"
    / "unified_jd_structured_span_v5_mechanism_development_labels_v1_2026-09-04.json"
)
LABEL_FREEZE_PATH = (
    ROOT
    / "datasets"
    / "unified_jd_structured_span_v5_mechanism_development_label_freeze_v1_2026-09-04.json"
)
V4_PATH = ROOT / "src" / "domain" / "unified_jd_structured_spans_v4.py"
RAW_PATH = (
    ROOT
    / "artifacts"
    / "evaluation"
    / "unified-jd-structured-span-v5-mechanism-development-v4-baseline-raw-v1-2026-09-04.json"
)
REPORT_PATH = (
    ROOT
    / "artifacts"
    / "evaluation"
    / "unified-jd-structured-span-v5-mechanism-development-v4-baseline-report-v1-2026-09-04.json"
)
FINDINGS_PATH = (
    ROOT
    / "artifacts"
    / "evaluation"
    / "unified-jd-structured-span-v5-mechanism-development-v4-baseline-findings-v1-2026-09-04.md"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def normalized_gold(labels: dict[str, Any]) -> dict[str, Any]:
    gold = copy.deepcopy(labels)
    gold["gold_version"] = labels["labels_version"]
    for fixture in gold["fixtures"]:
        fixture["diagnostic_status"] = fixture["development_role"]
    return gold


def metric_snapshot(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "fixture_count": report["evaluation_scope"]["fixture_count"],
        "structure_validation_error_count": report["structure_validation_errors"],
        "wrapper_span_f1": report["wrappers"]["f1"],
        "wrapper_exact_fixture_count": report["wrappers"]["exact_fixture_count"],
        "connector_classification_accuracy": report["connector_classification"][
            "accuracy"
        ],
        "coordination_member_f1": report["coordination_members"]["f1"],
        "coordination_member_exact_fixture_count": report["coordination_members"][
            "exact_fixture_count"
        ],
        "shared_scope_edge_f1": report["shared_scope_edges"]["f1"],
        "shared_scope_exact_fixture_count": report["shared_scope_edges"][
            "exact_fixture_count"
        ],
        "example_attachment_parent_f1": report["example_attachment_parents"]["f1"],
        "example_attachment_edge_f1": report["example_attachment_edges"]["f1"],
        "example_attachment_exact_fixture_count": report[
            "example_attachment_edges"
        ]["exact_fixture_count"],
        "surface_projection_f1": report["projection"]["surface_items"]["f1"],
        "surface_projection_exact_fixture_count": report["projection"][
            "surface_items"
        ]["exact_fixture_count"],
        "example_projection_f1": report["projection"]["examples"]["f1"],
        "example_projection_exact_fixture_count": report["projection"]["examples"][
            "exact_fixture_count"
        ],
    }


def evaluate_subset(
    gold: dict[str, Any], raw: dict[str, Any], fixture_ids: set[str]
) -> dict[str, Any]:
    subset_gold = copy.deepcopy(gold)
    subset_gold["fixtures"] = [
        fixture for fixture in gold["fixtures"] if fixture["id"] in fixture_ids
    ]
    subset_raw = copy.deepcopy(raw)
    subset_raw["records"] = [
        record for record in raw["records"] if record["id"] in fixture_ids
    ]
    return evaluate_predictions(subset_gold, subset_raw)


def render_findings(report: dict[str, Any]) -> str:
    metric = report["baseline_metrics"]
    lines = [
        "# V4 baseline on v5 mechanism development gold",
        "",
        "## Scope",
        "",
        "- The 20 clauses are revealed mechanism-enriched development data, not a holdout.",
        "- Their six-layer gold was frozen before this parser run.",
        "- The run is local and deterministic; model calls and network calls are zero.",
        "- The frozen v4 source was read but not modified.",
        "",
        "## Aggregate baseline",
        "",
        "| Layer | Metric | Exact fixtures |",
        "|---|---:|---:|",
        f"| Wrapper spans | {metric['wrapper_span_f1']:.4f} | {metric['wrapper_exact_fixture_count']}/20 |",
        f"| Connector role | {metric['connector_classification_accuracy']:.4f} | n/a |",
        f"| Coordination members | {metric['coordination_member_f1']:.4f} | {metric['coordination_member_exact_fixture_count']}/20 |",
        f"| Shared-scope edges | {metric['shared_scope_edge_f1']:.4f} | {metric['shared_scope_exact_fixture_count']}/20 |",
        f"| Attachment edges | {metric['example_attachment_edge_f1']:.4f} | {metric['example_attachment_exact_fixture_count']}/20 |",
        f"| Surface projection | {metric['surface_projection_f1']:.4f} | {metric['surface_projection_exact_fixture_count']}/20 |",
        f"| Example projection | {metric['example_projection_f1']:.4f} | {metric['example_projection_exact_fixture_count']}/20 |",
        "",
        "## Interpretation boundary",
        "",
        "These values are preregistration anchors only. They do not validate v5 and must not be used as a generalization claim. V5 remains unimplemented until the combined rule and gates are frozen.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    labels = load(LABELS_PATH)
    freeze = load(LABEL_FREEZE_PATH)
    if freeze["artifacts"]["labels"]["sha256"] != sha256(LABELS_PATH):
        raise ValueError("labels changed after their freeze")
    if (
        freeze["artifacts"]["frozen_v4_parser_reference"]["sha256"]
        != sha256(V4_PATH)
    ):
        raise ValueError("frozen v4 parser changed after label freeze")
    if labels["prediction_status_at_labeling"] != (
        "no_v4_or_v5_predictions_loaded_or_run_for_these_20_fixtures"
    ):
        raise ValueError("label prediction-independence declaration is missing")

    gold = normalized_gold(labels)
    raw = run_predictions(gold, "v4")
    raw.update(
        {
            "raw_version": "unified-jd-structured-span-v5-mechanism-development-v4-baseline-raw-v1",
            "generated_at": DATE,
            "status": "post_label_freeze_revealed_development_baseline",
            "gold_path": str(LABELS_PATH.relative_to(ROOT)).replace("\\", "/"),
            "gold_sha256": sha256(LABELS_PATH),
            "label_freeze_path": str(LABEL_FREEZE_PATH.relative_to(ROOT)).replace(
                "\\", "/"
            ),
            "label_freeze_sha256": sha256(LABEL_FREEZE_PATH),
            "v4_source_sha256_before": sha256(V4_PATH),
            "model_call_count": 0,
            "network_call_count": 0,
        }
    )
    raw["v4_source_sha256_after"] = sha256(V4_PATH)
    raw["v4_modified"] = (
        raw["v4_source_sha256_before"] != raw["v4_source_sha256_after"]
    )
    write_json(RAW_PATH, raw)

    evaluated = evaluate_predictions(gold, raw)
    strata: dict[str, Any] = {}
    for stratum in sorted(
        {fixture["development_stratum"] for fixture in gold["fixtures"]}
    ):
        fixture_ids = {
            fixture["id"]
            for fixture in gold["fixtures"]
            if fixture["development_stratum"] == stratum
        }
        strata[stratum] = metric_snapshot(evaluate_subset(gold, raw, fixture_ids))

    role_subsets = {
        "E6-target": {
            fixture["id"]
            for fixture in gold["fixtures"]
            if fixture["development_stratum"] == "E6-priority-tail-rejection"
            and fixture["development_role"] == "target"
        },
        "E6-matched-control": {
            fixture["id"]
            for fixture in gold["fixtures"]
            if fixture["development_stratum"] == "E6-priority-tail-rejection"
            and fixture["development_role"] == "matched_control"
        },
    }
    role_metrics = {
        role: metric_snapshot(evaluate_subset(gold, raw, fixture_ids))
        for role, fixture_ids in role_subsets.items()
    }
    unanchored = [
        {"id": record["id"], "value": value}
        for record in raw["records"]
        for value in record["items"] + record["examples"]
        if value not in record["source_text"]
    ]
    report = {
        "report_version": "unified-jd-structured-span-v5-mechanism-development-v4-baseline-report-v1",
        "created_at": DATE,
        "status": "frozen_baseline_for_v5_preregistration",
        "scope": {
            "data_status": "revealed_mechanism_development_not_holdout",
            "fixture_count": 20,
            "generalization_claim": False,
            "threshold_selection_allowed_after_this_report": False,
            "model_call_count": 0,
            "network_call_count": 0,
            "v4_modified": raw["v4_modified"],
            "v5_implemented": False,
        },
        "inputs": {
            "labels": {
                "path": str(LABELS_PATH.relative_to(ROOT)).replace("\\", "/"),
                "sha256": sha256(LABELS_PATH),
            },
            "label_freeze": {
                "path": str(LABEL_FREEZE_PATH.relative_to(ROOT)).replace("\\", "/"),
                "sha256": sha256(LABEL_FREEZE_PATH),
            },
            "frozen_v4": {
                "path": str(V4_PATH.relative_to(ROOT)).replace("\\", "/"),
                "sha256": sha256(V4_PATH),
            },
            "raw": {
                "path": str(RAW_PATH.relative_to(ROOT)).replace("\\", "/"),
                "sha256": sha256(RAW_PATH),
            },
        },
        "baseline_metrics": metric_snapshot(evaluated),
        "strata": strata,
        "role_subsets": role_metrics,
        "unanchored_output_count": len(unanchored),
        "unanchored_outputs": unanchored,
        "records": evaluated["records"],
        "full_layer_report": {
            key: evaluated[key]
            for key in (
                "wrappers",
                "connector_classification",
                "coordination_members",
                "shared_scope_edges",
                "example_attachment_parents",
                "example_attachment_edges",
                "projection",
            )
        },
    }
    write_json(REPORT_PATH, report)
    FINDINGS_PATH.write_text(render_findings(report), encoding="utf-8")
    print(
        json.dumps(
            {
                "raw": str(RAW_PATH),
                "report": str(REPORT_PATH),
                "findings": str(FINDINGS_PATH),
                "baseline_metrics": report["baseline_metrics"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
