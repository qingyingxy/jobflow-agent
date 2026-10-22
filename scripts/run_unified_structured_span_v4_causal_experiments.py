from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.evaluate_unified_structured_span_v4_development import (
    _attachment_example_edge_keys,
    _attachment_parent_keys,
    _coordination_member_keys,
    _metric,
    evaluate_predictions,
    run_predictions,
)
from src.domain.unified_jd_structured_spans_v4 import scan_connector_tokens

PROJECT_ROOT = Path(__file__).resolve().parents[1]
GOLD_PATH = (
    PROJECT_ROOT
    / "datasets"
    / "unified_jd_structured_span_v4_development_gold_v1_2026-09-04.json"
)
REPORT_PATH = (
    PROJECT_ROOT
    / "artifacts"
    / "evaluation"
    / "unified-jd-structured-span-v4-causal-experiments-v1-2026-09-04.json"
)
FINDINGS_PATH = (
    PROJECT_ROOT
    / "artifacts"
    / "evaluation"
    / "unified-jd-structured-span-v4-causal-experiments-v1-2026-09-04.md"
)


def _metric_for_records(
    gold_records: list[dict[str, Any]],
    predictions: dict[str, dict[str, Any]],
    gold_values: Any,
    predicted_values: Any,
) -> dict[str, Any]:
    return _metric(
        (gold_values(item), predicted_values(predictions[item["id"]]))
        for item in gold_records
    )


def _connector_accuracy(
    gold_records: list[dict[str, Any]], *, protect_quantifiers: bool
) -> dict[str, Any]:
    confusion: Counter[tuple[str, str]] = Counter()
    for fixture in gold_records:
        expected = {
            (item["span"]["start"], item["span"]["end"], item["span"]["text"]): item[
                "role"
            ]
            for item in fixture["connector_labels"]
        }
        predicted = {
            (token.span.start, token.span.end, token.span.text): (
                "quantifier" if token.role == "quantifier" else "surface"
            )
            for token in scan_connector_tokens(
                fixture["source_text"],
                protect_quantifiers=protect_quantifiers,
            )
        }
        for location in set(expected) | set(predicted):
            confusion[
                (expected.get(location, "none"), predicted.get(location, "none"))
            ] += 1
    correct = sum(
        count
        for (expected_role, predicted_role), count in confusion.items()
        if expected_role == predicted_role
    )
    total = sum(confusion.values())
    return {
        "correct": correct,
        "count": total,
        "accuracy": correct / total if total else 1.0,
        "confusion": {
            f"{expected}->{predicted}": count
            for (expected, predicted), count in sorted(confusion.items())
        },
    }


def _projected_pairs(
    fixtures: Iterable[dict[str, Any]],
    predictions: dict[str, dict[str, Any]],
    key: str,
) -> dict[str, Any]:
    expected_key = "surface_items" if key == "items" else "examples"
    return _metric(
        (fixture["projection"][expected_key], predictions[fixture["id"]][key])
        for fixture in fixtures
    )


def build_report(gold: dict[str, Any]) -> dict[str, Any]:
    v3_raw = run_predictions(gold, "v3")
    v4_raw = run_predictions(gold, "v4")
    v3 = {item["id"]: item for item in v3_raw["records"]}
    v4 = {item["id"]: item for item in v4_raw["records"]}

    quantifier_fixtures = [
        fixture
        for fixture in gold["fixtures"]
        if any(item["role"] == "quantifier" for item in fixture["connector_labels"])
    ]
    coordination_fixtures = [
        fixture
        for fixture in gold["fixtures"]
        if any(group["role"] == "surface" for group in fixture["coordinations"])
        and not fixture["example_attachments"]
    ]
    attachment_fixtures = [
        fixture for fixture in gold["fixtures"] if fixture["example_attachments"]
    ]

    quantifier_control = _connector_accuracy(
        quantifier_fixtures, protect_quantifiers=False
    )
    quantifier_treatment = _connector_accuracy(
        quantifier_fixtures, protect_quantifiers=True
    )
    coordination_control = _metric_for_records(
        coordination_fixtures,
        v3,
        lambda item: _coordination_member_keys(item, gold=True),
        lambda item: _coordination_member_keys(item, gold=False),
    )
    coordination_treatment = _metric_for_records(
        coordination_fixtures,
        v4,
        lambda item: _coordination_member_keys(item, gold=True),
        lambda item: _coordination_member_keys(item, gold=False),
    )
    attachment_parent_control = _metric_for_records(
        attachment_fixtures,
        v3,
        lambda item: _attachment_parent_keys(item, gold=True),
        lambda item: _attachment_parent_keys(item, gold=False),
    )
    attachment_parent_treatment = _metric_for_records(
        attachment_fixtures,
        v4,
        lambda item: _attachment_parent_keys(item, gold=True),
        lambda item: _attachment_parent_keys(item, gold=False),
    )
    attachment_edge_control = _metric_for_records(
        attachment_fixtures,
        v3,
        lambda item: _attachment_example_edge_keys(item, gold=True),
        lambda item: _attachment_example_edge_keys(item, gold=False),
    )
    attachment_edge_treatment = _metric_for_records(
        attachment_fixtures,
        v4,
        lambda item: _attachment_example_edge_keys(item, gold=True),
        lambda item: _attachment_example_edge_keys(item, gold=False),
    )

    return {
        "report_version": "unified-jd-structured-span-v4-causal-experiments-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": {
            "status": "revealed_same_corpus_development_only",
            "generalization_claim": False,
            "model_call_count": 0,
            "gold_version": gold["gold_version"],
        },
        "experiments": {
            "quantifier_context_protection": {
                "fixture_ids": [item["id"] for item in quantifier_fixtures],
                "intervention": (
                    "Classify 或 in compositional quantifier contexts before "
                    "coordination splitting; all other scanner behavior is fixed."
                ),
                "control": quantifier_control,
                "treatment": quantifier_treatment,
                "accuracy_delta": (
                    quantifier_treatment["accuracy"] - quantifier_control["accuracy"]
                ),
            },
            "category_neutral_coordination": {
                "fixture_ids": [item["id"] for item in coordination_fixtures],
                "intervention": (
                    "Replace category-template-bound grouping with the shared local "
                    "sequence scanner and keep example fixtures out of this comparison."
                ),
                "control_coordination_members": coordination_control,
                "treatment_coordination_members": coordination_treatment,
                "member_f1_delta": (
                    coordination_treatment["f1"] - coordination_control["f1"]
                ),
                "control_projection": _projected_pairs(
                    coordination_fixtures, v3, "items"
                ),
                "treatment_projection": _projected_pairs(
                    coordination_fixtures, v4, "items"
                ),
            },
            "topology_example_attachment": {
                "fixture_ids": [item["id"] for item in attachment_fixtures],
                "intervention": (
                    "Attach left-hand enumerations through local examples + 等 + parent "
                    "order; no parent-name vocabulary is used."
                ),
                "control_parent": attachment_parent_control,
                "treatment_parent": attachment_parent_treatment,
                "control_edges": attachment_edge_control,
                "treatment_edges": attachment_edge_treatment,
                "edge_f1_delta": (
                    attachment_edge_treatment["f1"] - attachment_edge_control["f1"]
                ),
                "control_example_projection": _projected_pairs(
                    attachment_fixtures, v3, "examples"
                ),
                "treatment_example_projection": _projected_pairs(
                    attachment_fixtures, v4, "examples"
                ),
            },
        },
        "full_v3": evaluate_predictions(gold, v3_raw),
        "full_v4": evaluate_predictions(gold, v4_raw),
        "interpretation": {
            "supported": all(
                (
                    quantifier_treatment["accuracy"] > quantifier_control["accuracy"],
                    coordination_treatment["f1"] > coordination_control["f1"],
                    attachment_edge_treatment["f1"] > attachment_edge_control["f1"],
                )
            ),
            "limitation": (
                "These interventions use revealed failures from one source corpus. "
                "They support mechanism selection, not external generalization."
            ),
        },
    }


def render_findings(report: dict[str, Any]) -> str:
    experiments = report["experiments"]
    quantifier = experiments["quantifier_context_protection"]
    coordination = experiments["category_neutral_coordination"]
    attachment = experiments["topology_example_attachment"]
    v3 = report["full_v3"]
    v4 = report["full_v4"]
    return "\n".join(
        [
            "# Structured span v4 causal experiments",
            "",
            "## Scope",
            "",
            "- Revealed same-corpus development data only; no generalization claim.",
            "- Zero model/API calls.",
            "- Frozen v3 is the control and was not modified.",
            "",
            "## Interventions",
            "",
            (
                "- Quantifier context protection: connector accuracy "
                f"{quantifier['control']['accuracy']:.4f} -> "
                f"{quantifier['treatment']['accuracy']:.4f}."
            ),
            (
                "- Category-neutral coordination: member F1 "
                f"{coordination['control_coordination_members']['f1']:.4f} -> "
                f"{coordination['treatment_coordination_members']['f1']:.4f}; "
                "surface projection F1 "
                f"{coordination['control_projection']['f1']:.4f} -> "
                f"{coordination['treatment_projection']['f1']:.4f}."
            ),
            (
                "- Topology example attachment: edge F1 "
                f"{attachment['control_edges']['f1']:.4f} -> "
                f"{attachment['treatment_edges']['f1']:.4f}; example projection F1 "
                f"{attachment['control_example_projection']['f1']:.4f} -> "
                f"{attachment['treatment_example_projection']['f1']:.4f}."
            ),
            "",
            "## Full development comparison",
            "",
            (
                "- Connector classification accuracy: "
                f"{v3['connector_classification']['accuracy']:.4f} -> "
                f"{v4['connector_classification']['accuracy']:.4f}."
            ),
            (
                "- Coordination member F1: "
                f"{v3['coordination_members']['f1']:.4f} -> "
                f"{v4['coordination_members']['f1']:.4f}."
            ),
            (
                "- Shared-scope edge F1: "
                f"{v3['shared_scope_edges']['f1']:.4f} -> "
                f"{v4['shared_scope_edges']['f1']:.4f}."
            ),
            (
                "- Example attachment edge F1: "
                f"{v3['example_attachment_edges']['f1']:.4f} -> "
                f"{v4['example_attachment_edges']['f1']:.4f}."
            ),
            (
                "- Surface projection F1: "
                f"{v3['projection']['surface_items']['f1']:.4f} -> "
                f"{v4['projection']['surface_items']['f1']:.4f}."
            ),
            "",
            "## Decision",
            "",
            (
                "All three mechanisms are supported on development evidence. Freeze "
                "v4 before evaluating a new corpus-external holdout. Canonicalizer "
                "work remains blocked until that gate passes."
            ),
            "",
        ]
    )


def main() -> int:
    gold = json.loads(GOLD_PATH.read_text(encoding="utf-8"))
    report = build_report(gold)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    FINDINGS_PATH.write_text(render_findings(report), encoding="utf-8")
    print(
        "causal experiments complete "
        f"supported={report['interpretation']['supported']} "
        f"v4_surface_f1={report['full_v4']['projection']['surface_items']['f1']:.4f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
