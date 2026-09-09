from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_product_jd_eval_dataset_v1 import _label_summary
from src.domain.product_jd import ProductJDModelOutput, validate_product_jd_output

SOURCE_DATASET = (
    ROOT
    / "artifacts"
    / "evaluation"
    / "product-jd-test100-sources-v1-2026-09-08.json"
)
SOURCE_DRAFT = (
    ROOT
    / "artifacts"
    / "evaluation"
    / "product-jd-test100-api-label-draft-v2-2026-09-08.json"
)
SOURCE_REVIEW_QUEUE = (
    ROOT / "datasets" / "product_jd_test100_review_queue_v2_2026_09_08.json"
)
SOURCE_BOUNDARIES = (
    ROOT
    / "artifacts"
    / "evaluation"
    / "product-jd-test100-confirmed-any-of-items-terra-medium-v1-2026-09-09.json"
)
SOURCE_PREREGISTRATION = (
    ROOT / "datasets" / "product_jd_test100_preregistration_v1_2026_09_08.json"
)
DEFAULT_LABELS = (
    ROOT
    / "artifacts"
    / "evaluation"
    / "product-jd-test100-human-reviewed-v1-2026-09-09.json"
)
DEFAULT_FREEZE_RECEIPT = (
    ROOT / "datasets" / "product_jd_test100_label_freeze_v1_2026_09_09.json"
)

DATASET_VERSION = "product-jd-test100-human-reviewed-v1-2026-09-09"
FREEZE_VERSION = "product-jd-test100-label-freeze-v1-2026-09-09"
LABEL_STATUS = "frozen_api_labels_with_human_dispute_review"
EXPECTED_CASE_COUNT = 100
EXPECTED_REVIEW_COUNT = 28
EXPECTED_BOUNDARY_COUNT = 9
SUPPORTED_OPERATIONS = {
    "keep_api",
    "replace_requirement",
    "split_requirement",
    "replace_requirements",
    "set_all_flagged_relations_any_of",
    "set_all_flagged_relations_to_any_of",
}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _payload_sha256(payload: Any) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return _sha256_text(canonical)


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _write_immutable_json(path: Path, payload: Any) -> None:
    content = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") != content:
        raise FileExistsError(f"Refusing to overwrite changed frozen artifact: {path}")
    path.write_text(content, encoding="utf-8")


def _source_hash(source_case: dict[str, Any]) -> str:
    return _sha256_text(source_case["raw_content"])


def _find_requirement_index(
    requirements: list[dict[str, Any]],
    *,
    source_text: str,
    case_id: str,
) -> int:
    matches = [
        index
        for index, requirement in enumerate(requirements)
        if requirement.get("source_text") == source_text
    ]
    if len(matches) != 1:
        raise ValueError(
            f"Expected one requirement target in {case_id!r} for {source_text!r}, "
            f"found {len(matches)}"
        )
    return matches[0]


def _final_requirement(
    payload: dict[str, Any],
    *,
    target_source_text: str,
) -> dict[str, Any]:
    nested = payload.get("final_requirement")
    if nested is not None:
        if not isinstance(nested, dict):
            raise TypeError("final_requirement must be an object")
        result = deepcopy(nested)
    else:
        result = {
            "source_text": payload.get("source_text", target_source_text),
            "level": payload["level"],
            "relation": payload["relation"],
            "items": deepcopy(payload["items"]),
            "relation_reason": payload.get("relation_reason"),
        }
    result.setdefault("relation_reason", None)
    return result


def _replace_requirement(
    requirements: list[dict[str, Any]],
    *,
    target_source_text: str,
    replacements: list[dict[str, Any]],
    case_id: str,
) -> tuple[int, int]:
    index = _find_requirement_index(
        requirements,
        source_text=target_source_text,
        case_id=case_id,
    )
    prior = requirements[index]
    requirements[index : index + 1] = deepcopy(replacements)
    return int([prior] != replacements), len(replacements) - 1


def _boundary_index(boundaries: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    if boundaries.get("status") != "api_boundary_extraction_complete":
        raise ValueError("Confirmed any_of boundary extraction is incomplete")
    groups = boundaries.get("groups")
    if not isinstance(groups, list) or len(groups) != EXPECTED_BOUNDARY_COUNT:
        raise ValueError(f"Expected exactly {EXPECTED_BOUNDARY_COUNT} boundary groups")
    indexed: dict[tuple[str, str], dict[str, Any]] = {}
    for group in groups:
        key = (group["case_id"], group["source_text"])
        if key in indexed:
            raise ValueError(f"Duplicate boundary group: {key!r}")
        items = group.get("items")
        if not isinstance(items, list) or not 2 <= len(items) <= 12:
            raise ValueError(f"Invalid boundary items: {key!r}")
        if not all(item in group["source_text"] for item in items):
            raise ValueError(f"Boundary item lacks source support: {key!r}")
        keys = [item.strip().casefold() for item in items]
        if len(keys) != len(set(keys)):
            raise ValueError(f"Duplicate boundary items: {key!r}")
        indexed[key] = group
    return indexed


def _validate_inputs(
    source_dataset: dict[str, Any],
    draft: dict[str, Any],
    review_queue: dict[str, Any],
    boundaries: dict[str, Any],
    preregistration: dict[str, Any],
    *,
    source_dataset_path: Path,
    review_queue_path: Path,
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[tuple[str, str], dict[str, Any]],
]:
    if source_dataset.get("status") != "source_selection_frozen_unlabeled":
        raise ValueError("Expected the frozen unlabeled test-100 source dataset")
    if source_dataset.get("case_count") != EXPECTED_CASE_COUNT:
        raise ValueError(f"Expected exactly {EXPECTED_CASE_COUNT} source cases")
    if draft.get("status") != "api_draft_complete":
        raise ValueError("Expected a complete test-100 API label draft")
    if draft.get("source_case_count") != EXPECTED_CASE_COUNT:
        raise ValueError("API label draft source count is not 100")
    if draft.get("api_success_count") != 70 or draft.get("api_failure_count") != 0:
        raise ValueError("The 70 independent API labels are not complete")
    if draft.get("source_payload_sha256") != _payload_sha256(source_dataset):
        raise ValueError("API draft is not bound to the current source payload")
    if draft.get("source_dataset_version") != source_dataset.get("dataset_version"):
        raise ValueError("API draft and source dataset versions differ")

    if review_queue.get("review_status") != "human_review_complete":
        raise ValueError("Human dispute review is incomplete")
    if review_queue.get("review_case_count") != EXPECTED_REVIEW_COUNT:
        raise ValueError(f"Expected exactly {EXPECTED_REVIEW_COUNT} review cases")
    if review_queue.get("confirmed_decision_count") != EXPECTED_REVIEW_COUNT:
        raise ValueError("Not all 28 review decisions are confirmed")
    if review_queue.get("pending_review_case_count") != 0:
        raise ValueError("Human dispute review still has pending cases")

    review_cases = review_queue.get("cases")
    if not isinstance(review_cases, list) or len(review_cases) != EXPECTED_REVIEW_COUNT:
        raise ValueError("Review queue does not contain exactly 28 cases")
    review_numbers = [case.get("review_number") for case in review_cases]
    if review_numbers != list(range(1, EXPECTED_REVIEW_COUNT + 1)):
        raise ValueError("Review numbers must be complete, unique, and ordered")
    for case in review_cases:
        decision = case.get("decision")
        if not isinstance(decision, dict) or decision.get("status") != "confirmed":
            raise ValueError(f"Review case is not confirmed: {case.get('id')!r}")
        if decision.get("operation") not in SUPPORTED_OPERATIONS:
            raise ValueError(
                f"Unsupported review operation: {decision.get('operation')!r}"
            )

    declared_queue = boundaries.get("review_queue", {})
    if declared_queue.get("path") != _display_path(review_queue_path):
        raise ValueError("Boundary extraction references a different review queue")
    if declared_queue.get("sha256") != _sha256_file(review_queue_path):
        raise ValueError("Review queue changed after boundary extraction")
    if boundaries.get("model") != "gpt-5.6-terra":
        raise ValueError("Boundary extraction did not use the frozen Terra model")
    if boundaries.get("reasoning_effort") != "medium":
        raise ValueError("Boundary extraction did not use medium reasoning effort")
    boundary_by_target = _boundary_index(boundaries)
    expected_boundary_targets = {
        (case["id"], issue["source_text"])
        for case in review_cases
        if case["decision"]["operation"].startswith("set_all_flagged_relations")
        for issue in case.get("issues", [])
        if issue.get("code") == "relation_uncertain"
    }
    if set(boundary_by_target) != expected_boundary_targets:
        raise ValueError("Boundary extraction does not exactly cover flagged decisions")

    if preregistration.get("status") != "source_selection_frozen_unlabeled":
        raise ValueError("Test-100 preregistration is not frozen")
    if preregistration.get("test_case_count") != EXPECTED_CASE_COUNT:
        raise ValueError("Test-100 preregistration count is not 100")
    source_reference = preregistration["local_artifacts"]["test100_sources"]
    if source_reference.get("path") != _display_path(source_dataset_path):
        raise ValueError("Preregistration references a different test-100 source file")
    if source_reference.get("sha256") != _sha256_file(source_dataset_path):
        raise ValueError("Frozen test-100 source file hash changed")

    source_cases = source_dataset.get("cases")
    draft_cases = draft.get("cases")
    if not isinstance(source_cases, list) or not isinstance(draft_cases, list):
        raise TypeError("Source and draft cases must be lists")
    if (
        len(source_cases) != EXPECTED_CASE_COUNT
        or len(draft_cases) != EXPECTED_CASE_COUNT
    ):
        raise ValueError("Source and draft case counts differ")
    source_by_id = {case["id"]: case for case in source_cases}
    draft_by_id = {case["id"]: case for case in draft_cases}
    review_by_id = {case["id"]: case for case in review_cases}
    if len(source_by_id) != EXPECTED_CASE_COUNT or len(draft_by_id) != EXPECTED_CASE_COUNT:
        raise ValueError("Source or draft contains duplicate case IDs")
    if set(source_by_id) != set(draft_by_id):
        raise ValueError("Source and API draft case IDs differ")
    if len(review_by_id) != EXPECTED_REVIEW_COUNT:
        raise ValueError("Review queue contains duplicate case IDs")
    if not set(review_by_id) <= set(source_by_id):
        raise ValueError("Review queue contains an unknown case ID")
    return source_by_id, draft_by_id, review_by_id, boundary_by_target


def _apply_decision(
    case: dict[str, Any],
    review_case: dict[str, Any],
    boundary_by_target: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, int]:
    case_id = case["id"]
    requirements = case["expected"]["requirements"]
    decision = review_case["decision"]
    operation = decision["operation"]
    changed = 0
    inserted = 0
    target_count = 0

    if operation == "keep_api":
        confirmed_responsibilities = decision.get("confirmed_responsibilities")
        if (
            confirmed_responsibilities is not None
            and confirmed_responsibilities != case["expected"]["responsibilities"]
        ):
            raise ValueError(f"Confirmed responsibilities differ in {case_id!r}")
    elif operation == "replace_requirement":
        target = decision["target_source_text"]
        final = _final_requirement(decision, target_source_text=target)
        delta_changed, delta_inserted = _replace_requirement(
            requirements,
            target_source_text=target,
            replacements=[final],
            case_id=case_id,
        )
        changed += delta_changed
        inserted += delta_inserted
        target_count += 1
    elif operation == "split_requirement":
        target = decision["target_source_text"]
        final_requirements = [
            _final_requirement(item, target_source_text=target)
            for item in decision["final_requirements"]
        ]
        delta_changed, delta_inserted = _replace_requirement(
            requirements,
            target_source_text=target,
            replacements=final_requirements,
            case_id=case_id,
        )
        changed += delta_changed
        inserted += delta_inserted
        target_count += 1
    elif operation == "replace_requirements":
        for change in decision["requirement_changes"]:
            target = change["target_source_text"]
            final = _final_requirement(change, target_source_text=target)
            delta_changed, delta_inserted = _replace_requirement(
                requirements,
                target_source_text=target,
                replacements=[final],
                case_id=case_id,
            )
            changed += delta_changed
            inserted += delta_inserted
            target_count += 1
    elif operation.startswith("set_all_flagged_relations"):
        flagged = [
            issue["source_text"]
            for issue in review_case.get("issues", [])
            if issue.get("code") == "relation_uncertain"
        ]
        declared_count = decision.get("flagged_requirement_count")
        if declared_count is not None and declared_count != len(flagged):
            raise ValueError(f"Flagged requirement count differs in {case_id!r}")
        for target in flagged:
            index = _find_requirement_index(
                requirements,
                source_text=target,
                case_id=case_id,
            )
            boundary = boundary_by_target[(case_id, target)]
            final = {
                **requirements[index],
                "relation": "any_of",
                "items": deepcopy(boundary["items"]),
                "relation_reason": boundary["reason"],
            }
            prior = requirements[index]
            requirements[index] = final
            changed += int(prior != final)
            target_count += 1
    else:
        raise ValueError(f"Unsupported review operation: {operation!r}")

    return {
        "target_count": target_count,
        "changed_target_count": changed,
        "inserted_requirement_count": inserted,
    }


def build_reviewed_labels(
    *,
    source_dataset_path: Path = SOURCE_DATASET,
    draft_path: Path = SOURCE_DRAFT,
    review_queue_path: Path = SOURCE_REVIEW_QUEUE,
    boundaries_path: Path = SOURCE_BOUNDARIES,
    preregistration_path: Path = SOURCE_PREREGISTRATION,
    labels_path: Path = DEFAULT_LABELS,
) -> dict[str, Any]:
    source_dataset = _load_json(source_dataset_path)
    draft = _load_json(draft_path)
    review_queue = _load_json(review_queue_path)
    boundaries = _load_json(boundaries_path)
    preregistration = _load_json(preregistration_path)
    _source_by_id, draft_by_id, review_by_id, boundary_by_target = _validate_inputs(
        source_dataset,
        draft,
        review_queue,
        boundaries,
        preregistration,
        source_dataset_path=source_dataset_path,
        review_queue_path=review_queue_path,
    )

    revised_cases: list[dict[str, Any]] = []
    operation_counts: Counter[str] = Counter()
    target_count = 0
    changed_target_count = 0
    inserted_requirement_count = 0
    for source_case in source_dataset["cases"]:
        case_id = source_case["id"]
        draft_case = draft_by_id[case_id]
        if draft_case.get("source_content_sha256") != source_case[
            "source_content_sha256"
        ]:
            raise ValueError(f"Draft source hash differs in {case_id!r}")
        if source_case["source_content_sha256"] != _source_hash(source_case):
            raise ValueError(f"Raw source content hash differs in {case_id!r}")
        if source_case["source_content_length"] != len(source_case["raw_content"]):
            raise ValueError(f"Raw source content length differs in {case_id!r}")
        for field in ("company", "title", "source_url", "verified_at"):
            if draft_case["source"].get(field) != source_case.get(field):
                raise ValueError(f"Draft source metadata differs in {case_id!r}: {field}")

        case = deepcopy(draft_case)
        case["raw_content"] = source_case["raw_content"]
        case["source"]["recruitment_type"] = source_case["recruitment_type"]
        review_case = review_by_id.get(case_id)
        if review_case is not None:
            summary = _apply_decision(case, review_case, boundary_by_target)
            operation_counts[review_case["decision"]["operation"]] += 1
            target_count += summary["target_count"]
            changed_target_count += summary["changed_target_count"]
            inserted_requirement_count += summary["inserted_requirement_count"]
            case["annotation_status"] = "api_or_reused_label_human_dispute_reviewed"
            case["label_revision"] = {
                "review_number": review_case["review_number"],
                "operation": review_case["decision"]["operation"],
                "confirmed_by": review_case["decision"]["confirmed_by"],
                "confirmed_at": review_case["decision"]["confirmed_at"],
            }
        else:
            case["label_revision"] = None

        output = ProductJDModelOutput.model_validate(case["expected"])
        validate_product_jd_output(output, case["raw_content"])
        revised_cases.append(case)

    if any(
        requirement["relation"] == "uncertain"
        for case in revised_cases
        for requirement in case["expected"]["requirements"]
    ):
        raise ValueError("Reviewed test-100 labels still contain uncertain relations")
    if [case["id"] for case in revised_cases] != [
        case["id"] for case in source_dataset["cases"]
    ]:
        raise ValueError("Reviewed label case order differs from the frozen source order")

    result = {
        "dataset_version": DATASET_VERSION,
        "source_dataset_version": source_dataset["dataset_version"],
        "schema_version": draft["schema_version"],
        "split": "test",
        "label_status": LABEL_STATUS,
        "frozen_at": "2026-09-09",
        "case_count": len(revised_cases),
        "composition": deepcopy(source_dataset["composition"]),
        "fully_human_reviewed": False,
        "labeling_scope": (
            "Thirty prior labels were reused after relation/item review; seventy labels "
            "were independently drafted by Terra, with all 28 automatically flagged "
            "dispute cases confirmed by the project owner."
        ),
        "prediction_independence": (
            "No test-100 parser prediction file was read while drafting, reviewing, "
            "applying, validating, or freezing these labels."
        ),
        "label_revision": {
            "method": "api_independent_annotation_plus_complete_flagged_human_review",
            "review_case_count": EXPECTED_REVIEW_COUNT,
            "boundary_group_count": len(boundary_by_target),
            "operation_counts": dict(sorted(operation_counts.items())),
            "target_count": target_count,
            "changed_target_count": changed_target_count,
            "inserted_requirement_count": inserted_requirement_count,
            "label_summary": _label_summary(revised_cases),
            "inputs": {
                "sources": {
                    "path": _display_path(source_dataset_path),
                    "sha256": _sha256_file(source_dataset_path),
                },
                "api_draft": {
                    "path": _display_path(draft_path),
                    "sha256": _sha256_file(draft_path),
                    "version": draft["dataset_version"],
                },
                "review_queue": {
                    "path": _display_path(review_queue_path),
                    "sha256": _sha256_file(review_queue_path),
                    "version": review_queue["review_queue_version"],
                },
                "boundary_extraction": {
                    "path": _display_path(boundaries_path),
                    "sha256": _sha256_file(boundaries_path),
                    "version": boundaries["artifact_version"],
                },
                "preregistration": {
                    "path": _display_path(preregistration_path),
                    "sha256": _sha256_file(preregistration_path),
                    "version": preregistration["dataset_version"],
                },
            },
        },
        "cases": revised_cases,
    }
    _write_immutable_json(labels_path, result)
    return result


def build_freeze_receipt(
    *,
    labels_path: Path = DEFAULT_LABELS,
    preregistration_path: Path = SOURCE_PREREGISTRATION,
) -> dict[str, Any]:
    labels = _load_json(labels_path)
    preregistration = _load_json(preregistration_path)
    if labels.get("dataset_version") != DATASET_VERSION:
        raise ValueError("Unexpected reviewed test-100 label version")
    if labels.get("label_status") != LABEL_STATUS:
        raise ValueError("Reviewed test-100 labels are not frozen")
    if labels.get("case_count") != EXPECTED_CASE_COUNT:
        raise ValueError("Reviewed test-100 labels do not contain 100 cases")

    runtime = preregistration["frozen_runtime"]
    frozen_files: dict[str, dict[str, str]] = {}
    for name in ("parser_implementation", "output_contract", "evaluation_metrics"):
        reference = runtime[name]
        path = ROOT / reference["path"]
        current_hash = _sha256_file(path)
        if current_hash != reference["sha256"]:
            raise ValueError(f"Frozen runtime file changed before evaluation: {name}")
        frozen_files[name] = {
            "path": reference["path"],
            "sha256": current_hash,
        }
    runner_path = ROOT / "scripts" / "run_product_jd_baseline.py"
    frozen_files["evaluation_runner"] = {
        "path": _display_path(runner_path),
        "sha256": _sha256_file(runner_path),
    }

    return {
        "freeze_version": FREEZE_VERSION,
        "status": "frozen",
        "frozen_at": "2026-09-09",
        "prediction_status": "not_generated_or_viewed",
        "case_count": EXPECTED_CASE_COUNT,
        "model_call_count": 0,
        "labels": {
            "path": _display_path(labels_path),
            "sha256": _sha256_file(labels_path),
            "version": labels["dataset_version"],
            "status": labels["label_status"],
        },
        "preregistration": {
            "path": _display_path(preregistration_path),
            "sha256": _sha256_file(preregistration_path),
            "version": preregistration["dataset_version"],
        },
        "runtime": {
            "provider": runtime["provider"],
            "model": runtime["model"],
            "reasoning_effort": runtime["reasoning_effort"],
            "product_prompt_version": runtime["product_prompt_version"],
            "product_parser_version": runtime["product_parser_version"],
            "files": frozen_files,
        },
        "immutability_policy": (
            "Any change to labels, parser prompts or implementation, output contract, "
            "metrics, or runner requires a new versioned freeze and a new evaluation. "
            "Test predictions must not be used to revise this frozen version."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apply all confirmed Product JD test-100 reviews and freeze labels"
    )
    parser.add_argument("--sources", type=Path, default=SOURCE_DATASET)
    parser.add_argument("--draft", type=Path, default=SOURCE_DRAFT)
    parser.add_argument("--review-queue", type=Path, default=SOURCE_REVIEW_QUEUE)
    parser.add_argument("--boundaries", type=Path, default=SOURCE_BOUNDARIES)
    parser.add_argument("--preregistration", type=Path, default=SOURCE_PREREGISTRATION)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--freeze-receipt", type=Path, default=DEFAULT_FREEZE_RECEIPT)
    args = parser.parse_args()
    labels = build_reviewed_labels(
        source_dataset_path=args.sources,
        draft_path=args.draft,
        review_queue_path=args.review_queue,
        boundaries_path=args.boundaries,
        preregistration_path=args.preregistration,
        labels_path=args.labels,
    )
    receipt = build_freeze_receipt(
        labels_path=args.labels,
        preregistration_path=args.preregistration,
    )
    _write_immutable_json(args.freeze_receipt, receipt)
    print(
        "product-jd-test100-labels-frozen "
        f"cases={labels['case_count']} "
        f"reviews={labels['label_revision']['review_case_count']} "
        f"changed_targets={labels['label_revision']['changed_target_count']} "
        f"labels_sha256={receipt['labels']['sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
