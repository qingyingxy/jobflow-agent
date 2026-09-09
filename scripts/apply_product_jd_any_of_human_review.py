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

SOURCE_DEVELOPMENT = (
    ROOT
    / "artifacts"
    / "evaluation"
    / "product-jd-development70-v2-2026-09-06.json"
)
SOURCE_CANDIDATES = (
    ROOT
    / "artifacts"
    / "evaluation"
    / "product-jd-any-of-review-candidates-terra-medium-v4-development70-v1.json"
)
SOURCE_DECISIONS = (
    ROOT
    / "artifacts"
    / "evaluation"
    / "product-jd-any-of-human-review-decisions-terra-medium-v4-v1.json"
)
DEFAULT_DEVELOPMENT = (
    ROOT
    / "artifacts"
    / "evaluation"
    / "product-jd-development70-v3-human-reviewed-2026-09-07.json"
)

DATASET_VERSION = "product-jd-eval-v3-human-reviewed-2026-09-07"
LABEL_REVISION = "any_of_human_reviewed_v3"
EXPECTED_CANDIDATE_COUNT = 77


def _candidate_key(
    case_id: str,
    candidate_side: str,
    source_text: str,
) -> tuple[str, str, str]:
    return case_id, candidate_side, source_text


def _requirement_from_decision(decision: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_text": decision["source_text"],
        "level": decision["level"],
        "relation": decision["final_relation"],
        "items": decision["final_items"],
    }


def _index_candidates(
    candidates: dict[str, Any],
) -> dict[tuple[str, str, str], dict[str, Any]]:
    indexed: dict[tuple[str, str, str], dict[str, Any]] = {}
    sides = (
        ("gold_any_of_disagreement", "gold_any_of_disagreements", "gold"),
        (
            "predicted_any_of_disagreement",
            "predicted_any_of_disagreements",
            "prediction",
        ),
    )
    for side, field, source_field in sides:
        for candidate in candidates[field]:
            key = _candidate_key(
                candidate["case_id"],
                side,
                candidate[source_field]["source_text"],
            )
            if key in indexed:
                raise ValueError(f"Duplicate review candidate: {key!r}")
            indexed[key] = candidate
    return indexed


def _resolve_decision_key(
    decision: dict[str, Any],
    candidate_index: dict[tuple[str, str, str], dict[str, Any]],
) -> tuple[str, str, str]:
    candidate_source_text = decision.get(
        "candidate_source_text",
        decision["source_text"],
    )
    exact_key = _candidate_key(
        decision["case_id"],
        decision["candidate_side"],
        candidate_source_text,
    )
    if exact_key in candidate_index:
        return exact_key

    matches: list[tuple[str, str, str]] = []
    if "candidate_source_text" not in decision:
        for key, candidate in candidate_index.items():
            if key[:2] != exact_key[:2]:
                continue
            best_prediction = candidate.get("best_prediction")
            if (
                decision["candidate_side"] == "gold_any_of_disagreement"
                and best_prediction is not None
                and best_prediction["source_text"] == decision["source_text"]
            ):
                matches.append(key)
    if len(matches) == 1:
        return matches[0]
    raise ValueError(
        f"Decision does not match exactly one review candidate: {exact_key!r}"
    )


def _find_requirement_index(
    requirements: list[dict[str, Any]],
    *,
    target_requirement: dict[str, Any],
    case_id: str,
) -> int:
    matches = [
        index
        for index, requirement in enumerate(requirements)
        if requirement == target_requirement
    ]
    if len(matches) != 1:
        raise ValueError(
            f"Expected exactly one matching requirement in {case_id!r}: "
            f"{target_requirement!r}, found {len(matches)}"
        )
    return matches[0]


def build_human_reviewed_development(
    *,
    source_development_path: Path = SOURCE_DEVELOPMENT,
    candidates_path: Path = SOURCE_CANDIDATES,
    decisions_path: Path = SOURCE_DECISIONS,
    development_path: Path = DEFAULT_DEVELOPMENT,
) -> dict[str, Any]:
    """Apply completed development-only relation review without reading sealed data."""

    source_development = _load_json(source_development_path)
    candidates = _load_json(candidates_path)
    review = _load_json(decisions_path)

    if source_development.get("split") != "development":
        raise ValueError("Only a development dataset may be revised")
    if source_development.get("case_count") != 70:
        raise ValueError("Expected the fixed 70-case development dataset")
    if candidates.get("sealed_test_read") is not False:
        raise ValueError("Candidate analysis must attest sealed_test_read=false")
    if review.get("sealed_test_read") is not False:
        raise ValueError("Human review must attest sealed_test_read=false")
    if review.get("review_status") != "complete":
        raise ValueError("Human review is not complete")
    if review.get("dataset_version") != source_development.get("dataset_version"):
        raise ValueError("Review and source development dataset versions differ")
    if candidates.get("dataset_version") != source_development.get("dataset_version"):
        raise ValueError("Candidates and source development dataset versions differ")
    if review.get("candidate_file") != candidates_path.name:
        raise ValueError("Human review references a different candidate file")

    candidate_index = _index_candidates(candidates)
    decisions = review.get("decisions")
    if not isinstance(decisions, list):
        raise TypeError("Human review decisions must be a list")
    if len(candidate_index) != EXPECTED_CANDIDATE_COUNT:
        raise ValueError(
            f"Expected {EXPECTED_CANDIDATE_COUNT} candidates, found "
            f"{len(candidate_index)}"
        )
    if review.get("candidate_count") != len(candidate_index):
        raise ValueError("Recorded candidate_count does not match candidate data")
    if review.get("decision_count") != len(decisions):
        raise ValueError("Recorded decision_count does not match decisions")

    decision_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for decision in decisions:
        key = _resolve_decision_key(decision, candidate_index)
        if key in decision_by_key:
            raise ValueError(f"Duplicate human-review decision: {key!r}")
        decision_by_key[key] = decision
    missing_decisions = set(candidate_index) - set(decision_by_key)
    extra_decisions = set(decision_by_key) - set(candidate_index)
    if missing_decisions or extra_decisions:
        raise ValueError(
            "Human-review coverage mismatch: "
            f"missing={sorted(missing_decisions)!r}, "
            f"extra={sorted(extra_decisions)!r}"
        )

    revised = deepcopy(source_development)
    revised["dataset_version"] = DATASET_VERSION
    revised["label_revision"] = {
        "name": LABEL_REVISION,
        "method": "complete_human_review_of_any_of_disagreements",
        "human_reviewed": True,
        "scope": "development-70 any_of disagreement candidates only",
        "sealed_test_read": False,
        "candidate_count": len(candidate_index),
        "decision_count": len(decisions),
        "decision_summary": deepcopy(review["summary"]),
        "source_development": {
            "path": _display_path(source_development_path),
            "sha256": _sha256_file(source_development_path),
        },
        "candidate_file": {
            "path": _display_path(candidates_path),
            "sha256": _sha256_file(candidates_path),
        },
        "decision_file": {
            "path": _display_path(decisions_path),
            "sha256": _sha256_file(decisions_path),
        },
    }

    cases_by_id = {case["id"]: case for case in revised["cases"]}
    if len(cases_by_id) != len(revised["cases"]):
        raise ValueError("Development dataset contains duplicate case IDs")

    applied_targets: set[tuple[str, str]] = set()
    replaced_count = 0
    added_count = 0
    changed_count = 0

    for key, candidate in candidate_index.items():
        decision = decision_by_key[key]
        case_id = decision["case_id"]
        if case_id not in cases_by_id:
            raise ValueError(f"Review candidate case is absent from development: {case_id}")
        case = cases_by_id[case_id]
        requirements = case["expected"]["requirements"]
        final_requirement = _requirement_from_decision(decision)

        if decision["candidate_side"] == "gold_any_of_disagreement":
            target_requirement = candidate["gold"]
        elif decision["candidate_side"] == "predicted_any_of_disagreement":
            target_requirement = candidate["best_gold"]
        else:
            raise ValueError(
                f"Unsupported candidate_side: {decision['candidate_side']!r}"
            )

        if target_requirement is None:
            if any(
                requirement["source_text"] == final_requirement["source_text"]
                for requirement in requirements
            ):
                raise ValueError(
                    f"Cannot add duplicate requirement source in {case_id!r}: "
                    f"{final_requirement['source_text']!r}"
                )
            requirements.append(final_requirement)
            added_count += 1
            changed_count += 1
            continue

        target = (
            case_id,
            json.dumps(target_requirement, ensure_ascii=False, sort_keys=True),
        )
        if target in applied_targets:
            raise ValueError(f"Multiple decisions map to the same gold requirement: {target!r}")
        applied_targets.add(target)
        requirement_index = _find_requirement_index(
            requirements,
            target_requirement=target_requirement,
            case_id=case_id,
        )
        previous = requirements[requirement_index]
        requirements[requirement_index] = final_requirement
        replaced_count += 1
        if previous != final_requirement:
            changed_count += 1

    for case in revised["cases"]:
        case["label_revision"] = LABEL_REVISION
        output = ProductJDModelOutput.model_validate(case["expected"])
        validate_product_jd_output(output, case["raw_content"])

    revised["label_revision"]["application_summary"] = {
        "replaced_requirement_count": replaced_count,
        "added_requirement_count": added_count,
        "changed_requirement_count": changed_count,
    }
    revised["label_revision"]["label_summary"] = _label_summary(revised["cases"])
    _write_json(development_path, revised)
    return revised


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Apply completed any_of human review to Product JD development labels"
    )
    parser.add_argument(
        "--source-development",
        type=Path,
        default=SOURCE_DEVELOPMENT,
    )
    parser.add_argument("--candidates", type=Path, default=SOURCE_CANDIDATES)
    parser.add_argument("--decisions", type=Path, default=SOURCE_DECISIONS)
    parser.add_argument("--development", type=Path, default=DEFAULT_DEVELOPMENT)
    args = parser.parse_args()
    result = build_human_reviewed_development(
        source_development_path=args.source_development,
        candidates_path=args.candidates,
        decisions_path=args.decisions,
        development_path=args.development,
    )
    print(
        json.dumps(
            {
                "dataset_version": result["dataset_version"],
                "development": result["case_count"],
                "candidate_count": result["label_revision"]["candidate_count"],
                "decision_count": result["label_revision"]["decision_count"],
                "application_summary": result["label_revision"][
                    "application_summary"
                ],
                "label_summary": result["label_revision"]["label_summary"],
                "sealed_source_read": False,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
