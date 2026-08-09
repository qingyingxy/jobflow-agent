from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from src.evaluation.models import EvaluationManifest

METADATA_ONLY_FLAGS = {
    "job_type": ("招聘类型来自外部元数据", "招聘类型来自采集元数据"),
    "locations": ("工作地点来自外部元数据", "官方详情页未披露工作地点"),
}


def prepare_strict_manifest(
    manifest_payload: dict[str, Any],
    review_payload: dict[str, Any],
    *,
    exclude_review_required: bool = True,
    exclude_metadata_only_fields: bool = True,
) -> tuple[EvaluationManifest, dict[str, Any]]:
    """Create a fair evaluation subset without changing source text."""

    manifest = EvaluationManifest.model_validate(manifest_payload)
    review_by_id = {
        item["id"]: item
        for item in review_payload.get("cases", [])
        if isinstance(item, dict) and item.get("id")
    }

    kept_cases = []
    excluded_cases: list[dict[str, Any]] = []
    excluded_field_counts: dict[str, int] = {}
    strict_reviews: list[dict[str, Any]] = []

    for case in manifest.cases:
        review = review_by_id.get(case.id, {})
        if exclude_review_required and review.get("review_required") is True:
            excluded_cases.append(
                {
                    "id": case.id,
                    "reason": "review_required",
                    "review_reasons": list(review.get("review_reasons", [])),
                }
            )
            continue

        excluded_fields: list[str] = []
        fields = dict(case.expected.fields)
        if exclude_metadata_only_fields:
            source_flags = [str(flag) for flag in review.get("source_flags", [])]
            for field_name, flag_fragments in METADATA_ONLY_FLAGS.items():
                if field_name not in fields:
                    continue
                if any(
                    any(fragment in flag for fragment in flag_fragments)
                    for flag in source_flags
                ):
                    fields.pop(field_name)
                    excluded_fields.append(field_name)
                    excluded_field_counts[field_name] = (
                        excluded_field_counts.get(field_name, 0) + 1
                    )

        if excluded_fields:
            expected = case.expected.model_copy(update={"fields": fields})
            case = case.model_copy(update={"expected": expected})
        kept_cases.append(case)

        strict_review = dict(review)
        strict_review["draft_fields"] = fields
        strict_review["evaluation_excluded_fields"] = excluded_fields
        strict_reviews.append(strict_review)

    strict_manifest = manifest.model_copy(
        update={
            "manifest_version": f"{manifest.manifest_version}-strict",
            "dataset_version": f"{manifest.dataset_version}-strict",
            "purpose": (
                "严格 Parser 评测子集：排除待复核样本，并排除原文不可见、"
                "仅来自外部元数据的字段；原始岗位正文保持不变。"
            ),
            "cases": kept_cases,
        }
    )

    strict_review_payload = {
        "manifest_version": strict_manifest.manifest_version,
        "dataset_version": strict_manifest.dataset_version,
        "label_status": "strict_eval_subset",
        "source_record_count": review_payload.get("source_record_count"),
        "included_case_count": len(kept_cases),
        "excluded_case_count": len(excluded_cases),
        "excluded_cases": excluded_cases,
        "excluded_field_counts": excluded_field_counts,
        "review_required_count": sum(
            item.get("review_required") is True for item in strict_reviews
        ),
        "field_labeled_case_count": {
            field: sum(field in case.expected.fields for case in kept_cases)
            for field in strict_manifest.fields
        },
        "company_counts": strict_review_payload_company_counts(
            strict_reviews
        ),
        "cases": strict_reviews,
    }
    return strict_manifest, strict_review_payload


def strict_review_payload_company_counts(
    reviews: list[dict[str, Any]],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for review in reviews:
        company = str(review.get("company") or "unknown")
        counts[company] = counts.get(company, 0) + 1
    return counts


def main() -> int:
    arguments = _parse_args()
    manifest_payload = json.loads(
        Path(arguments.manifest).read_text(encoding="utf-8")
    )
    review_payload = json.loads(
        Path(arguments.review).read_text(encoding="utf-8")
    )
    strict_manifest, strict_review = prepare_strict_manifest(
        manifest_payload,
        review_payload,
        exclude_review_required=arguments.exclude_review_required,
        exclude_metadata_only_fields=arguments.exclude_metadata_only_fields,
    )
    output_path = Path(arguments.output)
    review_output_path = Path(arguments.review_output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    review_output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        strict_manifest.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    review_output_path.write_text(
        json.dumps(strict_review, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"manifest={output_path} cases={len(strict_manifest.cases)} "
        f"review_required={strict_review['review_required_count']} "
        f"review={review_output_path}"
    )
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare a strict evaluation subset from a reviewed manifest"
    )
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--review", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--review-output", required=True)
    parser.add_argument("--exclude-review-required", action="store_true")
    parser.add_argument("--exclude-metadata-only-fields", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
