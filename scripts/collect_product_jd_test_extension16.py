from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import get_settings
from src.services.discovery_sources import ByteDanceAdapter
from src.services.url_reader import SafeHTTPReader

CATALOG_PATH = ROOT / "datasets" / "ai_campus_job_catalog_2026_08_31.json"
STRICT_MANIFEST_PATH = (
    ROOT
    / "artifacts"
    / "evaluation"
    / "m11-ai-campus-manifest-full-v4-strict-2026-08-31.json"
)
PRODUCT_SPLIT_PATH = (
    ROOT / "datasets" / "product_jd_eval_split_v2_2026_09_06.json"
)
DEFAULT_EXTENSION_SOURCE_PATH = (
    ROOT
    / "artifacts"
    / "evaluation"
    / "product-jd-test-extension16-sources-v1-2026-09-08.json"
)
DEFAULT_TEST_SOURCE_PATH = (
    ROOT
    / "artifacts"
    / "evaluation"
    / "product-jd-test100-sources-v1-2026-09-08.json"
)
DEFAULT_PREREGISTRATION_PATH = (
    ROOT
    / "datasets"
    / "product_jd_test100_preregistration_v1_2026_09_08.json"
)

DATASET_VERSION = "product-jd-test100-v1-2026-09-08"
VERIFIED_AT = "2026-09-08"
EXPECTED_BASE_STRICT_COUNT = 154
EXPECTED_DEVELOPMENT_COUNT = 70
EXPECTED_BASE_HOLDOUT_COUNT = 84
EXPECTED_EXTENSION_COUNT = 16
EXPECTED_TEST_COUNT = 100

# Fixed after official-listing review and before Product JD parsing or annotation.
EXTENSION_SELECTION = (
    ("7673509678010108213", "大模型算法研究员 - 火山方舟"),
    ("7668633107578997045", "AIGC视频生成算法工程师 - 火山方舟"),
    ("7669752384818055477", "算法研究员（搜广推大模型） - Data AML"),
    ("7668630538194471221", "豆包大模型多模态算法工程师 - 火山方舟"),
    ("7667949032820492597", "广告算法工程师 - Data AML"),
    ("7667950451392874805", "大模型应用算法工程师 - Data AML"),
    ("7668634222367312133", "AIGC图像生成算法工程师 - 火山方舟"),
    ("7675611979327490357", "大模型算法工程师（语音） - 火山方舟"),
    ("7669781552199436549", "增长算法工程师 - 财经业务"),
    ("7667144702417750277", "代码智能大模型算法研究员 - TRAE"),
    ("7665173792972556597", "广告AIGC算法工程师 - 中国交易与广告"),
    ("7667099804536948997", "大模型算法工程师（业务风控） - TikTok研发"),
    ("7665593225248819461", "AI应用算法工程师 - 小荷健康"),
    ("7670457476447684869", "豆包AI大模型评测算法工程师 - 火山方舟"),
    ("7672293900385257733", "豆包大模型算法工程师（AIGC Agent方向） - 火山方舟"),
    (
        "7667048582088870197",
        "大模型内容安全算法工程师（业务风控） - TikTok研发",
    ),
)


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


def _source_ref(path: Path) -> dict[str, str]:
    return {"path": _display_path(path), "sha256": _sha256_file(path)}


async def _fetch_extension_cases() -> list[dict[str, Any]]:
    settings = get_settings()
    reader = SafeHTTPReader(
        proxy=settings.url_fetch_proxy,
        proxy_allowed_hosts={"jobs.bytedance.com"},
        proxy_allow_unlisted_hosts=settings.url_fetch_proxy_allow_unlisted_hosts,
        timeout_seconds=15,
        max_retries=1,
    )
    adapter = ByteDanceAdapter(
        query="2027届 AI 大模型 Agent 算法校招",
        reader=reader,
        max_jobs=20,
    )
    semaphore = asyncio.Semaphore(4)

    async def fetch_one(
        index: int,
        source_job_id: str,
        expected_title: str,
    ) -> dict[str, Any]:
        async with semaphore:
            stub = await adapter.fetch_job(source_job_id)
        if stub.source_job_id != source_job_id:
            raise ValueError(f"Official ID mismatch for {source_job_id}")
        if stub.title != expected_title:
            raise ValueError(
                f"Official title changed for {source_job_id}: {stub.title!r}"
            )
        if stub.job_type != "campus":
            raise ValueError(f"Job is no longer a campus role: {source_job_id}")
        if not stub.locations:
            raise ValueError(f"Job has no official location: {source_job_id}")
        if "岗位职责" not in stub.raw_content or "任职要求" not in stub.raw_content:
            raise ValueError(f"Job detail is incomplete: {source_job_id}")

        return {
            "id": f"campus-ai-{166 + index:03d}",
            "company": "字节跳动",
            "title": stub.title,
            "source_url": (
                "https://jobs.bytedance.com/campus/position/"
                f"{source_job_id}/detail"
            ),
            "raw_content": stub.raw_content,
            "recruitment_type": "应届生",
            "cohort": "2027届校园招聘",
            "graduation_window": "2027届（以官网项目口径为准）",
            "locations": "/".join(stub.locations),
            "official_source": True,
            "quality_grade": "A",
            "application_status": "官网列表在招，官方详情 API 可读",
            "page_status": "open_or_readable",
            "published_at": (
                stub.published_at.isoformat() if stub.published_at else None
            ),
            "verified_at": VERIFIED_AT,
            "enabled_for_parser_eval": True,
            "selection_origin": "new_official_extension16",
            "source_job_id": source_job_id,
        }

    cases = await asyncio.gather(
        *(
            fetch_one(index, source_job_id, expected_title)
            for index, (source_job_id, expected_title) in enumerate(
                EXTENSION_SELECTION
            )
        )
    )
    if len(cases) != EXPECTED_EXTENSION_COUNT:
        raise ValueError("Extension did not produce exactly 16 cases")
    return cases


def _build_base_holdout_cases(
    strict_manifest: dict[str, Any],
    product_split: dict[str, Any],
    catalog: dict[str, Any],
) -> list[dict[str, Any]]:
    strict_cases = strict_manifest["cases"]
    development_ids = {
        item["id"] for item in product_split["development"]["cases"]
    }
    sealed_ids = {
        item["id"] for item in product_split["sealed_test"]["cases"]
    }
    if len(strict_cases) != EXPECTED_BASE_STRICT_COUNT:
        raise ValueError("Expected the frozen 154-case strict manifest")
    if len(development_ids) != EXPECTED_DEVELOPMENT_COUNT:
        raise ValueError("Expected the frozen 70-case Product development set")

    catalog_by_id = {item["id"]: item for item in catalog["records"]}
    holdout: list[dict[str, Any]] = []
    for case in strict_cases:
        if case["id"] in development_ids:
            continue
        metadata = catalog_by_id[case["id"]]
        raw_content = case["input"]["raw_content"]
        holdout.append(
            {
                "id": case["id"],
                "company": metadata["company"],
                "title": metadata["title"],
                "source_url": case["input"]["source_url"],
                "raw_content": raw_content,
                "recruitment_type": metadata["recruitment_type"],
                "verified_at": metadata["verified_at"],
                "selection_origin": (
                    "prior_product_sealed30"
                    if case["id"] in sealed_ids
                    else "original_strict_unused54"
                ),
                "source_content_sha256": _sha256_text(raw_content),
                "source_content_length": len(raw_content),
            }
        )

    if len(holdout) != EXPECTED_BASE_HOLDOUT_COUNT:
        raise ValueError("Expected 84 strict cases outside Product development")
    origins = Counter(item["selection_origin"] for item in holdout)
    if origins != {
        "prior_product_sealed30": 30,
        "original_strict_unused54": 54,
    }:
        raise ValueError(f"Unexpected base holdout composition: {origins}")
    return holdout


def _metadata(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": case["id"],
        "company": case["company"],
        "title": case["title"],
        "source_url": case["source_url"],
        "recruitment_type": case["recruitment_type"],
        "verified_at": case["verified_at"],
        "source_content_sha256": case["source_content_sha256"],
        "source_content_length": case["source_content_length"],
        "selection_origin": case["selection_origin"],
        "annotation_status": "unlabeled_source_frozen",
    }


async def collect_and_freeze(
    *,
    extension_source_path: Path = DEFAULT_EXTENSION_SOURCE_PATH,
    test_source_path: Path = DEFAULT_TEST_SOURCE_PATH,
    preregistration_path: Path = DEFAULT_PREREGISTRATION_PATH,
) -> dict[str, Any]:
    catalog = _load_json(CATALOG_PATH)
    strict_manifest = _load_json(STRICT_MANIFEST_PATH)
    product_split = _load_json(PRODUCT_SPLIT_PATH)
    base_holdout = _build_base_holdout_cases(
        strict_manifest,
        product_split,
        catalog,
    )
    existing_urls = {item["source_url"] for item in catalog["records"]}
    existing_ids = {item["id"] for item in catalog["records"]}

    extension = await _fetch_extension_cases()
    for case in extension:
        if case["id"] in existing_ids:
            raise ValueError(f"Extension ID already exists: {case['id']}")
        if case["source_url"] in existing_urls:
            raise ValueError(f"Extension URL already exists: {case['source_url']}")
        raw_content = case["raw_content"]
        case["source_content_sha256"] = _sha256_text(raw_content)
        case["source_content_length"] = len(raw_content)

    extension_payload = {
        "dataset_version": DATASET_VERSION,
        "created_at": VERIFIED_AT,
        "status": "official_sources_frozen_unlabeled",
        "case_count": len(extension),
        "source_policy": (
            "Full public JD text is stored only in this gitignored local artifact."
        ),
        "selection_policy": (
            "Fixed current 2027 ByteDance campus roles across distinct AI topics "
            "before Product JD parsing, annotation, or metric calculation."
        ),
        "cases": extension,
    }
    _write_json(extension_source_path, extension_payload)

    test_cases = [*base_holdout, *extension]
    all_ids = [item["id"] for item in test_cases]
    all_urls = [item["source_url"] for item in test_cases]
    if len(test_cases) != EXPECTED_TEST_COUNT:
        raise ValueError("Expected exactly 100 test cases")
    if len(set(all_ids)) != EXPECTED_TEST_COUNT:
        raise ValueError("Test IDs are not unique")
    if len(set(all_urls)) != EXPECTED_TEST_COUNT:
        raise ValueError("Test source URLs are not unique")

    test_payload = {
        "dataset_version": DATASET_VERSION,
        "created_at": VERIFIED_AT,
        "status": "source_selection_frozen_unlabeled",
        "case_count": len(test_cases),
        "composition": {
            "prior_product_sealed30": 30,
            "original_strict_unused54": 54,
            "new_official_extension16": 16,
        },
        "independence_policy": (
            "The 70 Product JD development cases are excluded. New sources were "
            "frozen before Product JD parsing, annotation, or metric calculation."
        ),
        "cases": test_cases,
    }
    _write_json(test_source_path, test_payload)

    settings = get_settings()
    metadata_cases = [_metadata(case) for case in test_cases]
    preregistration = {
        "dataset_version": DATASET_VERSION,
        "created_at": VERIFIED_AT,
        "status": "source_selection_frozen_unlabeled",
        "expanded_source_record_count": 181,
        "expanded_strict_case_count": 170,
        "development_case_count": 70,
        "test_case_count": len(metadata_cases),
        "composition": test_payload["composition"],
        "selection_policy": {
            "base_holdout": (
                "All 84 cases from the frozen 154-case strict corpus that are not "
                "in Product JD development-70."
            ),
            "extension": (
                "Sixteen current official 2027 campus roles selected for AI-topic "
                "diversity and frozen before Product JD parsing or annotation."
            ),
            "development_exclusion": (
                "No case from Product JD development-70 may enter test-100."
            ),
        },
        "evaluation_protocol": [
            "Freeze source selection and content hashes.",
            "Create and human-review Product JD labels without changing parser code or prompts.",
            "Freeze labels and evaluation code.",
            "Run the frozen parser once across all 100 cases.",
            "Report failures and metric denominators with the aggregate scores.",
        ],
        "frozen_runtime": {
            "provider": settings.structured_model_provider,
            "model": settings.llm_model,
            "reasoning_effort": settings.llm_reasoning_effort,
            "product_prompt_version": settings.product_prompt_version,
            "product_parser_version": settings.product_parser_version,
            "parser_implementation": _source_ref(
                ROOT / "src" / "services" / "product_jd_parser.py"
            ),
            "output_contract": _source_ref(
                ROOT / "src" / "domain" / "product_jd.py"
            ),
            "evaluation_metrics": _source_ref(
                ROOT / "src" / "evaluation" / "product_metrics.py"
            ),
        },
        "source_files": {
            "original_catalog": _source_ref(CATALOG_PATH),
            "original_strict_manifest": _source_ref(STRICT_MANIFEST_PATH),
            "product_development_split": _source_ref(PRODUCT_SPLIT_PATH),
        },
        "local_artifacts": {
            "extension16_sources": _source_ref(extension_source_path),
            "test100_sources": _source_ref(test_source_path),
        },
        "test": {
            "case_count": len(metadata_cases),
            "annotation_status_counts": {"unlabeled_source_frozen": 100},
            "cases": metadata_cases,
        },
    }
    _write_json(preregistration_path, preregistration)
    return preregistration


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Collect 16 official jobs and freeze Product JD test-100"
    )
    parser.add_argument(
        "--extension-sources",
        type=Path,
        default=DEFAULT_EXTENSION_SOURCE_PATH,
    )
    parser.add_argument(
        "--test-sources",
        type=Path,
        default=DEFAULT_TEST_SOURCE_PATH,
    )
    parser.add_argument(
        "--preregistration",
        type=Path,
        default=DEFAULT_PREREGISTRATION_PATH,
    )
    args = parser.parse_args()
    preregistration = asyncio.run(
        collect_and_freeze(
            extension_source_path=args.extension_sources,
            test_source_path=args.test_sources,
            preregistration_path=args.preregistration,
        )
    )
    print(
        json.dumps(
            {
                "dataset_version": preregistration["dataset_version"],
                "expanded_strict_case_count": preregistration[
                    "expanded_strict_case_count"
                ],
                "development_case_count": preregistration[
                    "development_case_count"
                ],
                "test_case_count": preregistration["test_case_count"],
                "composition": preregistration["composition"],
                "status": preregistration["status"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
