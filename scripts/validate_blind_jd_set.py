from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from src.domain.skill_normalizer import normalize_skill_concepts


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def validate(
    *,
    raw_path: Path,
    labels_path: Path,
    catalog_path: Path,
    prior_source_path: Path,
) -> dict[str, Any]:
    raw_payload = _load(raw_path)
    labels_payload = _load(labels_path)
    raw_records = {record["id"]: record for record in raw_payload["records"]}
    label_cases = labels_payload["cases"]
    errors: list[str] = []

    if set(raw_records) != set(label_cases):
        errors.append(
            "raw/label ID mismatch: "
            f"{sorted(set(raw_records) ^ set(label_cases))}"
        )

    catalog_records = _load(catalog_path)["records"]
    prior_sources = _load(prior_source_path)
    old_urls = {record.get("source_url") for record in catalog_records}
    old_company_titles = {
        (record.get("company"), record.get("title"))
        for record in catalog_records
    }
    old_content_hashes = {
        _sha256(record.get("raw_content", "")) for record in prior_sources
    }

    current_urls: set[str] = set()
    current_company_titles: set[tuple[str, str]] = set()
    current_content_hashes: set[str] = set()
    concept_count = 0
    qualifier_count = 0
    any_of_case_count = 0

    for case_id, record in raw_records.items():
        url = record["source_url"]
        company_title = (record["company"], record["title"])
        content_hash = _sha256(record["raw_content"])
        for value, seen, label in (
            (url, current_urls, "URL"),
            (company_title, current_company_titles, "company/title"),
            (content_hash, current_content_hashes, "content hash"),
        ):
            if value in seen:
                errors.append(f"{case_id}: duplicate current {label}")
            seen.add(value)
        if url in old_urls:
            errors.append(f"{case_id}: URL already exists in the prior catalog")
        if company_title in old_company_titles:
            errors.append(
                f"{case_id}: company/title already exists in the prior catalog"
            )
        if content_hash in old_content_hashes:
            errors.append(f"{case_id}: content hash already exists in prior sources")

        case = label_cases.get(case_id)
        if not isinstance(case, dict):
            continue
        fields = case.get("fields", {})
        any_of_case_count += bool(fields.get("required_skill_groups"))
        for index, concept in enumerate(fields.get("skill_concepts", [])):
            concept_count += 1
            qualifier_count += concept.get("qualifier") is not None
            source_text = concept.get("source_text")
            if not source_text or source_text not in record["raw_content"]:
                errors.append(
                    f"{case_id}: concept {index} source_text is not verbatim"
                )
            normalized = normalize_skill_concepts(
                concept.get("canonical_name"),
                qualifier=concept.get("qualifier"),
                source_text=source_text,
            )
            normalized_ids = {item.skill_id for item in normalized}
            if concept.get("skill_id") not in normalized_ids:
                errors.append(
                    f"{case_id}: concept {index} skill_id mismatch "
                    f"({concept.get('skill_id')} not in {sorted(normalized_ids)})"
                )

    summary = {
        "raw_version": raw_payload.get("collection_version"),
        "label_version": labels_payload.get("version"),
        "case_count": len(raw_records),
        "company_count": len({record["company"] for record in raw_records.values()}),
        "concept_count": concept_count,
        "qualified_concept_count": qualifier_count,
        "any_of_case_count": any_of_case_count,
        "parser_predictions_generated": raw_payload.get(
            "parser_predictions_generated"
        ),
        "external_model_calls": raw_payload.get("external_model_calls"),
        "errors": errors,
    }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument(
        "--catalog",
        type=Path,
        default=Path("datasets/ai_campus_job_catalog_2026_08_31.json"),
    )
    parser.add_argument(
        "--prior-source",
        type=Path,
        default=Path(
            "artifacts/evaluation/m11-ai-campus-source-full-2026-08-31.json"
        ),
    )
    args = parser.parse_args()
    summary = validate(
        raw_path=args.raw,
        labels_path=args.labels,
        catalog_path=args.catalog,
        prior_source_path=args.prior_source,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return int(bool(summary["errors"]))


if __name__ == "__main__":
    raise SystemExit(main())
