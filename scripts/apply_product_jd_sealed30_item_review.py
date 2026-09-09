from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_product_jd_eval_dataset_v1 import (
    _display_path,
    _label_summary,
    _load_json,
    _sha256_file,
    _write_json,
)
from src.domain.product_jd import ProductJDModelOutput, validate_product_jd_output

SOURCE_LABELS = (
    ROOT
    / "artifacts"
    / "evaluation"
    / "product-jd-sealed30-relation-reviewed-v1-2026-09-08.json"
)
SOURCE_DECISIONS = (
    ROOT
    / "datasets"
    / "product_jd_sealed30_item_boundary_adjudication_round2_decisions_v1_2026_09_08.json"
)
DEFAULT_LABELS = (
    ROOT
    / "artifacts"
    / "evaluation"
    / "product-jd-sealed30-relation-items-reviewed-v2-2026-09-08.json"
)

DATASET_VERSION = "product-jd-sealed30-relation-items-reviewed-v2-2026-09-08"
LABEL_REVISION = "sealed30_relation_and_items_adjudication_v2"
LABEL_STATUS = "human_reviewed_relation_and_items_scope_not_full_field_review"
SOURCE_LABEL_STATUS = "human_reviewed_relation_scope_not_full_field_review"
EXPECTED_CASE_COUNT = 30
EXPECTED_DECISION_COUNT = 11


def _find_requirement(
    requirements: list[dict[str, Any]],
    *,
    source_text: str,
    case_id: str,
) -> dict[str, Any]:
    matches = [
        requirement
        for requirement in requirements
        if requirement["source_text"] == source_text
    ]
    if len(matches) != 1:
        raise ValueError(
            f"Expected exactly one requirement in {case_id!r} for "
            f"{source_text!r}, found {len(matches)}"
        )
    return matches[0]


def build_relation_items_reviewed_labels(
    *,
    source_labels_path: Path = SOURCE_LABELS,
    decisions_path: Path = SOURCE_DECISIONS,
    labels_path: Path = DEFAULT_LABELS,
) -> dict[str, Any]:
    """Apply completed item-boundary decisions without reading predictions."""

    source = _load_json(source_labels_path)
    review = _load_json(decisions_path)

    if source.get("split") != "sealed_test":
        raise ValueError("Expected the fixed sealed_test split")
    if source.get("case_count") != EXPECTED_CASE_COUNT:
        raise ValueError(f"Expected {EXPECTED_CASE_COUNT} sealed cases")
    if source.get("label_status") != SOURCE_LABEL_STATUS:
        raise ValueError("Expected the relation-reviewed sealed labels")
    if review.get("status") != "complete":
        raise ValueError("Item-boundary adjudication is not complete")
    if review.get("confirmed_count") != EXPECTED_DECISION_COUNT:
        raise ValueError("Item-boundary confirmed_count is incomplete")
    if review.get("pending_count") != 0:
        raise ValueError("Item-boundary adjudication still contains pending decisions")
    if review.get("selection_summary") != {"api": 10, "draft": 1}:
        raise ValueError("Unexpected item-boundary selection summary")

    declared_source = review.get("source_relation_reviewed_labels", {})
    if declared_source.get("path") != _display_path(source_labels_path):
        raise ValueError("Item review references a different source label file")
    if declared_source.get("sha256") != _sha256_file(source_labels_path):
        raise ValueError("Relation-reviewed label hash does not match the item review")

    decisions = review.get("decisions")
    if not isinstance(decisions, list) or len(decisions) != EXPECTED_DECISION_COUNT:
        raise ValueError(f"Expected exactly {EXPECTED_DECISION_COUNT} decisions")
    review_indices = [decision.get("review_index") for decision in decisions]
    if set(review_indices) != set(range(1, EXPECTED_DECISION_COUNT + 1)):
        raise ValueError("Item-boundary review indices are incomplete or duplicated")

    revised = deepcopy(source)
    cases_by_id = {case["id"]: case for case in revised["cases"]}
    if len(cases_by_id) != len(revised["cases"]):
        raise ValueError("Sealed dataset contains duplicate case IDs")

    touched_targets: set[tuple[str, str]] = set()
    changed_count = 0
    kept_count = 0
    for decision in sorted(decisions, key=lambda item: item["review_index"]):
        if decision.get("status") != "confirmed":
            raise ValueError(
                f"Item decision {decision.get('review_index')!r} is not confirmed"
            )
        if decision.get("choice") not in {"api", "draft"}:
            raise ValueError(f"Unsupported item choice: {decision.get('choice')!r}")
        case_id = decision["case_id"]
        source_text = decision["source_text"]
        target = (case_id, source_text)
        if target in touched_targets:
            raise ValueError(f"Requirement target reviewed twice: {target!r}")
        touched_targets.add(target)

        case = cases_by_id.get(case_id)
        if case is None:
            raise ValueError(f"Reviewed case is absent from sealed labels: {case_id!r}")
        requirement = _find_requirement(
            case["expected"]["requirements"],
            source_text=source_text,
            case_id=case_id,
        )
        if requirement["relation"] != "any_of":
            raise ValueError(f"Item-boundary target is not any_of: {target!r}")
        if requirement["items"] != decision.get("draft_items"):
            raise ValueError(f"Draft items do not match the source labels: {target!r}")
        final_items = decision.get("final_items")
        if not isinstance(final_items, list) or len(final_items) < 2:
            raise ValueError(f"Final any_of items are invalid: {target!r}")

        if requirement["items"] == final_items:
            kept_count += 1
        else:
            requirement["items"] = deepcopy(final_items)
            changed_count += 1

    revised["dataset_version"] = DATASET_VERSION
    revised["label_status"] = LABEL_STATUS
    revised["evaluation_policy"] = (
        "The project owner reviewed all 10 relation disagreements and all 11 "
        "aligned any_of item-boundary differences after predictions were visible. "
        "This freezes relation and any_of item semantics only; facts, ordinary "
        "all_of requirements, and responsibilities did not receive a complete "
        "independent human review."
    )

    for case in revised["cases"]:
        prior_revision = case.get("label_revision", {})
        case["annotation_status"] = LABEL_STATUS
        case["label_revision"] = {
            "annotation_version": LABEL_REVISION,
            "base_annotation_version": prior_revision.get("annotation_version"),
            "predictions_read_before_base_annotation": False,
            "post_prediction_relation_and_items_review": True,
            "human_reviewed_relation_and_items_scope": True,
            "fully_human_reviewed": False,
        }
        output = ProductJDModelOutput.model_validate(case["expected"])
        validate_product_jd_output(output, case["raw_content"])

    revised["label_revision"] = {
        "name": LABEL_REVISION,
        "method": "complete_project_owner_review_of_relation_and_item_disagreements",
        "human_reviewed_relation_and_items_scope": True,
        "fully_human_reviewed": False,
        "review_scope": (
            "10 relation disagreements and 11 aligned any_of item-boundary differences"
        ),
        "predictions_were_visible_during_review": True,
        "source_relation_reviewed_labels": {
            "path": _display_path(source_labels_path),
            "sha256": _sha256_file(source_labels_path),
        },
        "decision_file": {
            "path": _display_path(decisions_path),
            "sha256": _sha256_file(decisions_path),
        },
        "application_summary": {
            "decision_count": len(decisions),
            "changed_item_group_count": changed_count,
            "kept_item_group_count": kept_count,
        },
        "label_summary": _label_summary(revised["cases"]),
    }
    _write_json(labels_path, revised)
    return revised


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Apply completed sealed-30 Product JD item-boundary adjudication"
    )
    parser.add_argument("--source-labels", type=Path, default=SOURCE_LABELS)
    parser.add_argument("--decisions", type=Path, default=SOURCE_DECISIONS)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    args = parser.parse_args()
    result = build_relation_items_reviewed_labels(
        source_labels_path=args.source_labels,
        decisions_path=args.decisions,
        labels_path=args.labels,
    )
    print(
        json.dumps(
            {
                "dataset_version": result["dataset_version"],
                "label_status": result["label_status"],
                "case_count": result["case_count"],
                "application_summary": result["label_revision"][
                    "application_summary"
                ],
                "label_summary": result["label_revision"]["label_summary"],
                "model_calls": 0,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
