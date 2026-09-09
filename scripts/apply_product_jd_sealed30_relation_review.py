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
    / "product-jd-sealed30-codex-blind-draft-v1-2026-09-08.json"
)
SOURCE_DECISIONS = (
    ROOT
    / "datasets"
    / "product_jd_sealed30_relation_adjudication_round1_decisions_v1_2026_09_08.json"
)
DEFAULT_LABELS = (
    ROOT
    / "artifacts"
    / "evaluation"
    / "product-jd-sealed30-relation-reviewed-v1-2026-09-08.json"
)

DATASET_VERSION = "product-jd-sealed30-relation-reviewed-v1-2026-09-08"
LABEL_REVISION = "sealed30_relation_adjudication_v1"
LABEL_STATUS = "human_reviewed_relation_scope_not_full_field_review"
EXPECTED_CASE_COUNT = 30
EXPECTED_DECISION_COUNT = 10


def _find_requirement_indices(
    requirements: list[dict[str, Any]],
    *,
    source_texts: list[str],
    case_id: str,
) -> list[int]:
    indices: list[int] = []
    for source_text in source_texts:
        matches = [
            index
            for index, requirement in enumerate(requirements)
            if requirement["source_text"] == source_text
        ]
        if len(matches) != 1:
            raise ValueError(
                f"Expected exactly one requirement in {case_id!r} for "
                f"{source_text!r}, found {len(matches)}"
            )
        indices.append(matches[0])
    if len(indices) != len(set(indices)):
        raise ValueError(f"Duplicate requirement targets in {case_id!r}")
    return indices


def build_relation_reviewed_labels(
    *,
    source_labels_path: Path = SOURCE_LABELS,
    decisions_path: Path = SOURCE_DECISIONS,
    labels_path: Path = DEFAULT_LABELS,
) -> dict[str, Any]:
    """Apply the completed relation review without reading or changing predictions."""

    source = _load_json(source_labels_path)
    review = _load_json(decisions_path)

    if source.get("split") != "sealed_test":
        raise ValueError("Expected the fixed sealed_test split")
    if source.get("case_count") != EXPECTED_CASE_COUNT:
        raise ValueError(f"Expected {EXPECTED_CASE_COUNT} sealed cases")
    if source.get("label_status") != "codex_blind_draft_requires_human_review":
        raise ValueError("Expected the original Codex blind draft labels")
    if review.get("status") != "complete":
        raise ValueError("Relation adjudication is not complete")
    if review.get("confirmed_count") != EXPECTED_DECISION_COUNT:
        raise ValueError("Relation adjudication confirmed_count is incomplete")
    if review.get("pending_count") != 0:
        raise ValueError("Relation adjudication still contains pending decisions")

    declared_source = review.get("source_blind_draft", {})
    if declared_source.get("path") != _display_path(source_labels_path):
        raise ValueError("Relation adjudication references a different source label file")
    if declared_source.get("sha256") != _sha256_file(source_labels_path):
        raise ValueError("Source blind-label hash does not match the adjudication record")

    decisions = review.get("decisions")
    if not isinstance(decisions, list) or len(decisions) != EXPECTED_DECISION_COUNT:
        raise ValueError(f"Expected exactly {EXPECTED_DECISION_COUNT} decisions")
    review_indices = [decision.get("review_index") for decision in decisions]
    if set(review_indices) != set(range(1, EXPECTED_DECISION_COUNT + 1)):
        raise ValueError("Relation adjudication review indices are incomplete or duplicated")
    for decision in decisions:
        if decision.get("status") != "confirmed":
            raise ValueError(
                f"Relation decision {decision.get('review_index')!r} is not confirmed"
            )
        if decision.get("choice") not in {"api", "draft"}:
            raise ValueError(
                f"Unsupported relation choice: {decision.get('choice')!r}"
            )
        if decision.get("operation") not in {
            "keep_draft",
            "replace_draft_requirements",
        }:
            raise ValueError(
                f"Unsupported relation operation: {decision.get('operation')!r}"
            )

    revised = deepcopy(source)
    revised["dataset_version"] = DATASET_VERSION
    revised["label_status"] = LABEL_STATUS
    revised["evaluation_policy"] = (
        "The project owner reviewed all 10 post-prediction relation disagreements. "
        "This freezes the relation-disagreement scope only; facts, ordinary all_of "
        "requirements, responsibilities, and remaining item-boundary differences did "
        "not receive a complete independent human review."
    )

    cases_by_id = {case["id"]: case for case in revised["cases"]}
    if len(cases_by_id) != len(revised["cases"]):
        raise ValueError("Sealed dataset contains duplicate case IDs")

    touched_targets: set[tuple[str, str]] = set()
    kept_decision_count = 0
    modified_decision_count = 0
    removed_requirement_count = 0
    inserted_requirement_count = 0

    for decision in sorted(decisions, key=lambda item: item["review_index"]):
        case_id = decision["case_id"]
        case = cases_by_id.get(case_id)
        if case is None:
            raise ValueError(f"Reviewed case is absent from sealed labels: {case_id!r}")
        requirements = case["expected"]["requirements"]
        source_texts = decision.get("draft_source_texts")
        if not isinstance(source_texts, list) or not source_texts:
            raise ValueError(
                f"Decision {decision['review_index']} has no draft requirement targets"
            )
        indices = _find_requirement_indices(
            requirements,
            source_texts=source_texts,
            case_id=case_id,
        )
        for source_text in source_texts:
            target = (case_id, source_text)
            if target in touched_targets:
                raise ValueError(f"Requirement target reviewed twice: {target!r}")
            touched_targets.add(target)

        if decision["operation"] == "keep_draft":
            if "final_requirements" in decision:
                raise ValueError(
                    f"Keep decision {decision['review_index']} must not replace labels"
                )
            kept_decision_count += 1
            continue

        final_requirements = decision.get("final_requirements")
        if not isinstance(final_requirements, list) or not final_requirements:
            raise ValueError(
                f"Replace decision {decision['review_index']} has no final requirements"
            )
        insert_at = min(indices)
        for index in sorted(indices, reverse=True):
            del requirements[index]
        for offset, requirement in enumerate(deepcopy(final_requirements)):
            requirements.insert(insert_at + offset, requirement)
        modified_decision_count += 1
        removed_requirement_count += len(indices)
        inserted_requirement_count += len(final_requirements)

    for case in revised["cases"]:
        prior_revision = case.get("label_revision", {})
        case["annotation_status"] = LABEL_STATUS
        case["label_revision"] = {
            "annotation_version": LABEL_REVISION,
            "base_annotation_version": prior_revision.get("annotation_version"),
            "predictions_read_before_base_annotation": False,
            "post_prediction_relation_review": True,
            "human_reviewed_relation_scope": True,
            "fully_human_reviewed": False,
        }
        output = ProductJDModelOutput.model_validate(case["expected"])
        validate_product_jd_output(output, case["raw_content"])

    revised["label_revision"] = {
        "name": LABEL_REVISION,
        "method": "complete_project_owner_review_of_relation_disagreements",
        "human_reviewed_relation_scope": True,
        "fully_human_reviewed": False,
        "review_scope": "10 relation disagreements affecting any_of relation F1",
        "predictions_were_visible_during_review": True,
        "source_blind_draft": {
            "path": _display_path(source_labels_path),
            "sha256": _sha256_file(source_labels_path),
        },
        "decision_file": {
            "path": _display_path(decisions_path),
            "sha256": _sha256_file(decisions_path),
        },
        "application_summary": {
            "decision_count": len(decisions),
            "kept_decision_count": kept_decision_count,
            "modified_decision_count": modified_decision_count,
            "removed_requirement_count": removed_requirement_count,
            "inserted_requirement_count": inserted_requirement_count,
        },
        "label_summary": _label_summary(revised["cases"]),
    }
    _write_json(labels_path, revised)
    return revised


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Apply completed sealed-30 Product JD relation adjudication"
    )
    parser.add_argument("--source-labels", type=Path, default=SOURCE_LABELS)
    parser.add_argument("--decisions", type=Path, default=SOURCE_DECISIONS)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    args = parser.parse_args()
    result = build_relation_reviewed_labels(
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
