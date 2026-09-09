from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.domain.product_jd import ProductJDModelOutput, validate_product_jd_output

CATALOG_PATH = ROOT / "datasets" / "ai_campus_job_catalog_2026_08_31.json"
SOURCE_PATH = (
    ROOT / "artifacts" / "evaluation" / "m11-ai-campus-source-full-2026-08-31.json"
)
PRIOR_SPLIT_PATH = ROOT / "datasets" / "unified_jd_eval_split_v1_2026_09_03.json"
DEV50_PATH = (
    ROOT
    / "artifacts"
    / "evaluation"
    / "unified-jd-dev50-frozen-v2-2026-09-04.json"
)
DEFAULT_MANIFEST_PATH = (
    ROOT / "datasets" / "product_jd_eval_split_v1_2026_09_06.json"
)
DEFAULT_DEV_PATH = (
    ROOT
    / "artifacts"
    / "evaluation"
    / "product-jd-development70-v1-2026-09-06.json"
)
DEFAULT_SEALED_PATH = (
    ROOT
    / "artifacts"
    / "evaluation"
    / "product-jd-sealed30-sources-v1-2026-09-06.json"
)
EXTENSION20_LABELS_PATH = (
    ROOT
    / "artifacts"
    / "evaluation"
    / "product-jd-extension20-labels-v1-2026-09-06.json"
)

DATASET_VERSION = "product-jd-eval-v1-2026-09-06"
SELECTION_SEED = "product-jd-extra20-v1"
PRODUCT_FACT_FIELDS = (
    "job_type",
    "locations",
    "graduation_years",
    "education_requirements",
    "major_requirements",
    "deadline",
)
EXPLICIT_ANY_OF_PATTERN = re.compile(
    r"(?:\b(?:or|one\s+of|at\s+least\s+one)\b|或者|或|任选|任一|任意|"
    r"至少.{0,24}(?:一种|一项|一门|一类|1\s*种|1\s*项|1\s*门|1\s*类))",
    re.IGNORECASE,
)
NON_HARD_MAJOR_PATTERN = re.compile(
    r"(?:优先|加分|preferred|\bplus\b|专业不限)",
    re.IGNORECASE,
)
FACT_VALUE_OVERRIDES = {
    ("education_requirements", "优秀的本科或硕士"): "优秀的本科及硕士",
    ("education_requirements", "国内外著名高校硕士及以上学历"): "硕士及以上学历",
    ("major_requirements", "AI相关专业"): "AI 相关专业",
}


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _display_path(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _rank(case_id: str) -> str:
    return _sha256_text(f"{SELECTION_SEED}:{case_id}")


def _comparable(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold().strip()


def _preferred_major_source(source_text: str) -> str | None:
    if not re.search(
        r"(?:优先|加分|preferred|\bplus\b)",
        source_text,
        re.IGNORECASE,
    ):
        return None
    if "专业不限" not in source_text:
        return source_text
    parenthetical = re.search(r"[（(]([^（）()]*(?:优先|加分))[^（）()]*[）)]", source_text)
    return parenthetical.group(1) if parenthetical else None


def align_product_label_contract(
    payload: dict[str, Any],
    raw_content: str,
) -> dict[str, Any]:
    """Apply objective Product-label rules without inferring semantic relations."""

    aligned = deepcopy(payload)
    facts = aligned.setdefault("facts", {})
    requirements = aligned.setdefault("requirements", [])
    major = facts.get("major_requirements")
    if isinstance(major, dict) and NON_HARD_MAJOR_PATTERN.search(
        major["source_text"]
    ):
        preferred_source = _preferred_major_source(major["source_text"])
        facts["major_requirements"] = None
        if preferred_source and not any(
            item.get("source_text") == preferred_source for item in requirements
        ):
            requirements.append(
                {
                    "source_text": preferred_source,
                    "level": "preferred",
                    "relation": "all_of",
                    "items": [preferred_source],
                }
            )

    for field in (
        "locations",
        "education_requirements",
        "major_requirements",
    ):
        fact = facts.get(field)
        if not isinstance(fact, dict):
            continue
        source_key = _comparable(fact["source_text"])
        values: list[str] = []
        for original in fact.get("values", []):
            if field == "major_requirements" and _comparable(original) == "相关专业":
                continue
            value = FACT_VALUE_OVERRIDES.get((field, original), original)
            if _comparable(value) not in source_key:
                raise ValueError(
                    f"Unsupported {field} label value {value!r} in source "
                    f"{fact['source_text']!r}"
                )
            if value not in values:
                values.append(value)
        facts[field] = {**fact, "values": values} if values else None

    output = ProductJDModelOutput.model_validate(aligned)
    validate_product_jd_output(output, raw_content)
    return output.model_dump(mode="json")


def _select_extra_development_cases(
    *,
    catalog: list[dict[str, Any]],
    existing_dev: list[dict[str, Any]],
    excluded_ids: set[str],
    count: int,
) -> list[dict[str, Any]]:
    """Greedily add cases from the least represented available company."""

    candidates = [
        record
        for record in catalog
        if record.get("enabled_for_parser_eval") is True
        and record.get("official_source") is True
        and record["id"] not in excluded_ids
    ]
    company_counts = Counter(case["company"] for case in existing_dev)
    selected: list[dict[str, Any]] = []

    for _ in range(count):
        if not candidates:
            raise ValueError("Not enough eligible records to build development-70")
        minimum_count = min(company_counts[item["company"]] for item in candidates)
        least_represented = [
            item
            for item in candidates
            if company_counts[item["company"]] == minimum_count
        ]
        chosen = min(least_represented, key=lambda item: _rank(item["id"]))
        candidates.remove(chosen)
        selected.append(chosen)
        company_counts[chosen["company"]] += 1

    return selected


def _fact_evidence(expected: dict[str, Any]) -> dict[str, str]:
    return {
        item["field"]: item["source_text"]
        for item in expected["facts"].get("evidence", [])
        if item.get("field") in PRODUCT_FACT_FIELDS
    }


def _convert_fact(
    field: str,
    value: Any,
    evidence_by_field: dict[str, str],
) -> dict[str, Any] | None:
    if value is None or field not in evidence_by_field:
        return None
    key = "value" if field in {"job_type", "deadline"} else "values"
    return {key: value, "source_text": evidence_by_field[field]}


def _source_backed_items(clause: dict[str, Any]) -> tuple[str, list[str]]:
    source_text = clause["source_text"]
    source_key = _comparable(source_text)
    items = clause.get("items") or []
    all_verbatim = (
        0 < len(items) <= 12
        and all(_comparable(item) in source_key for item in items)
    )
    relation = clause.get("relation", "all_of")
    explicit_any_of = relation != "any_of" or bool(
        EXPLICIT_ANY_OF_PATTERN.search(source_text)
    )
    if (
        not all_verbatim
        or not explicit_any_of
        or (relation == "any_of" and len(items) < 2)
    ):
        return "all_of", [source_text]
    return relation, items


def convert_unified_case(case: dict[str, Any]) -> dict[str, Any]:
    """Create a conservative Product JD review candidate from reviewed Unified gold."""

    expected = case["expected"]
    evidence_by_field = _fact_evidence(expected)
    facts = {
        field: _convert_fact(
            field,
            expected["facts"].get(field),
            evidence_by_field,
        )
        for field in PRODUCT_FACT_FIELDS
    }

    requirements: list[dict[str, Any]] = []
    responsibilities: list[str] = []
    for clause in expected["clauses"]:
        source_text = clause["source_text"]
        if clause["category"] == "responsibility":
            if source_text not in responsibilities:
                responsibilities.append(source_text)
            continue
        if clause["category"] == "fact" or clause["level"] not in {
            "required",
            "preferred",
        }:
            continue
        relation, items = _source_backed_items(clause)
        requirements.append(
            {
                "source_text": source_text,
                "level": clause["level"],
                "relation": relation,
                "items": items,
            }
        )

    return align_product_label_contract(
        {
            "facts": facts,
            "requirements": requirements,
            "responsibilities": responsibilities,
        },
        case["raw_content"],
    )


def convert_extension_annotation(
    annotation: dict[str, Any],
    raw_content: str,
) -> dict[str, Any]:
    requirements = [
        {
            "source_text": source_text,
            "level": level,
            "relation": "all_of",
            "items": [source_text],
        }
        for level in ("required", "preferred")
        for source_text in annotation.get(level, [])
    ]
    requirements.extend(
        {
            "source_text": item["source_text"],
            "level": item["level"],
            "relation": "any_of",
            "items": item["items"],
        }
        for item in annotation.get("any_of", [])
    )
    return align_product_label_contract(
        {
            "facts": annotation.get("facts", {}),
            "requirements": requirements,
            "responsibilities": annotation.get("responsibilities", []),
        },
        raw_content,
    )


def _public_case(
    *,
    record: dict[str, Any],
    raw_content: str,
    selection_origin: str,
    annotation_status: str,
) -> dict[str, Any]:
    return {
        "id": record["id"],
        "company": record["company"],
        "title": record["title"],
        "source_url": record["source_url"],
        "recruitment_type": record.get("recruitment_type"),
        "verified_at": record.get("verified_at"),
        "source_content_sha256": _sha256_text(raw_content),
        "source_content_length": len(raw_content),
        "selection_origin": selection_origin,
        "annotation_status": annotation_status,
    }


def _local_source_case(
    *,
    record: dict[str, Any],
    raw_content: str,
    split: str,
    annotation_status: str,
    expected: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "id": record["id"],
        "split": split,
        "source": {
            "company": record["company"],
            "title": record["title"],
            "source_url": record["source_url"],
            "verified_at": record.get("verified_at"),
        },
        "raw_content": raw_content,
        "source_content_sha256": _sha256_text(raw_content),
        "annotation_status": annotation_status,
        "expected": expected,
    }


def _label_summary(cases: list[dict[str, Any]]) -> dict[str, Any]:
    fact_positive_counts = {
        field: sum(case["expected"]["facts"].get(field) is not None for case in cases)
        for field in PRODUCT_FACT_FIELDS
    }
    requirements = [
        requirement
        for case in cases
        for requirement in case["expected"]["requirements"]
    ]
    return {
        "labeled_case_count": len(cases),
        "fact_positive_counts": fact_positive_counts,
        "requirement_count": len(requirements),
        "required_requirement_count": sum(
            item["level"] == "required" for item in requirements
        ),
        "preferred_requirement_count": sum(
            item["level"] == "preferred" for item in requirements
        ),
        "any_of_requirement_count": sum(
            item["relation"] == "any_of" for item in requirements
        ),
        "responsibility_count": sum(
            len(case["expected"]["responsibilities"]) for case in cases
        ),
        "empty_requirement_case_count": sum(
            not case["expected"]["requirements"] for case in cases
        ),
        "empty_responsibility_case_count": sum(
            not case["expected"]["responsibilities"] for case in cases
        ),
        "unsupported_metric_fields": [
            field for field, count in fact_positive_counts.items() if count == 0
        ],
    }


def build_dataset(
    *,
    catalog_path: Path = CATALOG_PATH,
    source_path: Path = SOURCE_PATH,
    prior_split_path: Path = PRIOR_SPLIT_PATH,
    dev50_path: Path = DEV50_PATH,
    extension20_labels_path: Path = EXTENSION20_LABELS_PATH,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    development_path: Path = DEFAULT_DEV_PATH,
    sealed_path: Path = DEFAULT_SEALED_PATH,
) -> dict[str, Any]:
    catalog_payload = _load_json(catalog_path)
    catalog = catalog_payload["records"]
    records_by_id = {record["id"]: record for record in catalog}
    source_records = _load_json(source_path)
    raw_by_id = {record["id"]: record["raw_content"] for record in source_records}
    prior_split = _load_json(prior_split_path)
    dev50 = _load_json(dev50_path)
    extension20_labels = _load_json(extension20_labels_path)

    base_dev_ids = [case["id"] for case in prior_split["dev"]["cases"]]
    sealed_ids = [case["id"] for case in prior_split["sealed_blind"]["cases"]]
    converted_by_id = {
        case["id"]: convert_unified_case(case) for case in dev50["cases"]
    }
    if set(base_dev_ids) != set(converted_by_id):
        raise ValueError("The reviewed dev-50 labels do not match the prior dev split")

    excluded_ids = set(base_dev_ids) | set(sealed_ids)
    extra_records = _select_extra_development_cases(
        catalog=catalog,
        existing_dev=[records_by_id[case_id] for case_id in base_dev_ids],
        excluded_ids=excluded_ids,
        count=20,
    )
    extra_ids = [record["id"] for record in extra_records]
    if extra_ids != extension20_labels["case_ids"]:
        raise ValueError("The extension-20 labels do not match the fixed selection")
    extension_expected_by_id = {
        case_id: convert_extension_annotation(
            extension20_labels["cases"][case_id],
            raw_by_id[case_id],
        )
        for case_id in extra_ids
    }
    development_ids = [*base_dev_ids, *extra_ids]

    all_ids = development_ids + sealed_ids
    if len(all_ids) != len(set(all_ids)) or len(all_ids) != 100:
        raise ValueError("Product JD selection must contain 100 unique cases")
    missing_sources = sorted(set(all_ids) - set(raw_by_id))
    if missing_sources:
        raise ValueError(f"Missing local source content for: {missing_sources}")

    development_cases = []
    public_development_cases = []
    for case_id in development_ids:
        record = records_by_id[case_id]
        is_base = case_id in converted_by_id
        status = (
            "reviewed_unified_gold_migration_verified"
            if is_base
            else "agent_reviewed_product_native_v1"
        )
        expected = (
            converted_by_id[case_id]
            if is_base
            else extension_expected_by_id[case_id]
        )
        development_cases.append(
            _local_source_case(
                record=record,
                raw_content=raw_by_id[case_id],
                split="development",
                annotation_status=status,
                expected=expected,
            )
        )
        public_development_cases.append(
            _public_case(
                record=record,
                raw_content=raw_by_id[case_id],
                selection_origin=(
                    "reviewed_unified_dev50" if is_base else "balanced_extension20"
                ),
                annotation_status=status,
            )
        )

    sealed_cases = [
        _local_source_case(
            record=records_by_id[case_id],
            raw_content=raw_by_id[case_id],
            split="sealed_test",
            annotation_status="sealed_unannotated",
            expected=None,
        )
        for case_id in sealed_ids
    ]
    public_sealed_cases = [
        _public_case(
            record=records_by_id[case_id],
            raw_content=raw_by_id[case_id],
            selection_origin="prior_sealed_blind30",
            annotation_status="sealed_unannotated",
        )
        for case_id in sealed_ids
    ]

    development_payload = {
        "dataset_version": DATASET_VERSION,
        "schema_version": "product-job-description-v1",
        "split": "development",
        "case_count": 70,
        "label_status": {
            "reviewed_unified_gold_migration_verified": 50,
            "agent_reviewed_product_native_v1": 20,
            "human_reviewed_frozen": 0,
        },
        "cases": development_cases,
    }
    sealed_payload = {
        "dataset_version": DATASET_VERSION,
        "schema_version": "product-job-description-v1",
        "split": "sealed_test",
        "case_count": 30,
        "label_status": "sealed_unannotated",
        "cases": sealed_cases,
    }
    _write_json(development_path, development_payload)
    _write_json(sealed_path, sealed_payload)

    manifest = {
        "dataset_version": DATASET_VERSION,
        "created_at": "2026-09-06",
        "schema_version": "product-job-description-v1",
        "status": "selection_frozen_annotation_in_progress",
        "case_count": 100,
        "source_policy": (
            "The tracked manifest contains metadata and content hashes only. "
            "Full public JD text remains in gitignored local evaluation artifacts."
        ),
        "selection_policy": {
            "development": (
                "Reuse reviewed Unified dev-50, then add 20 eligible official jobs "
                "by least-represented company with a fixed SHA-256 tie-break."
            ),
            "sealed_test": (
                "Reuse the fixed 30-case sealed split. Do not include Product JD "
                "labels or use predictions for prompt tuning."
            ),
            "extension_seed": SELECTION_SEED,
        },
        "source_files": {
            "catalog": {
                "path": _display_path(catalog_path),
                "sha256": _sha256_file(catalog_path),
            },
            "prior_split": {
                "path": _display_path(prior_split_path),
                "sha256": _sha256_file(prior_split_path),
            },
            "reviewed_dev50": {
                "path": _display_path(dev50_path),
                "sha256": _sha256_file(dev50_path),
            },
            "extension20_labels": {
                "path": _display_path(extension20_labels_path),
                "sha256": _sha256_file(extension20_labels_path),
            },
        },
        "local_artifacts": {
            "development": {
                "path": _display_path(development_path),
                "sha256": _sha256_file(development_path),
            },
            "sealed_sources": {
                "path": _display_path(sealed_path),
                "sha256": _sha256_file(sealed_path),
            },
        },
        "development": {
            "case_count": 70,
            "annotation_status_counts": {
                "reviewed_unified_gold_migration_verified": 50,
                "agent_reviewed_product_native_v1": 20,
            },
            "label_summary": _label_summary(development_cases),
            "cases": public_development_cases,
        },
        "sealed_test": {
            "case_count": 30,
            "annotation_status_counts": {"sealed_unannotated": 30},
            "cases": public_sealed_cases,
        },
    }
    _write_json(manifest_path, manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Product JD evaluation dataset v1")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--development", type=Path, default=DEFAULT_DEV_PATH)
    parser.add_argument("--sealed", type=Path, default=DEFAULT_SEALED_PATH)
    args = parser.parse_args()
    manifest = build_dataset(
        manifest_path=args.manifest,
        development_path=args.development,
        sealed_path=args.sealed,
    )
    print(
        json.dumps(
            {
                "dataset_version": manifest["dataset_version"],
                "case_count": manifest["case_count"],
                "development": manifest["development"]["case_count"],
                "sealed_test": manifest["sealed_test"]["case_count"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
