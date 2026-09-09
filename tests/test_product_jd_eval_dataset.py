from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.build_product_jd_eval_dataset_v1 import (
    NON_HARD_MAJOR_PATTERN,
    PRIOR_SPLIT_PATH,
)
from scripts.revise_product_jd_development_v2 import (
    LABEL_REVISION,
    SOURCE_DEVELOPMENT,
    SOURCE_MANIFEST,
    build_development_revision,
)
from src.domain.product_jd import ProductJDModelOutput, validate_product_jd_output

MANIFEST_PATH = Path("datasets/product_jd_eval_split_v2_2026_09_06.json")
LOCAL_INPUTS_AVAILABLE = all(
    path.exists()
    for path in (PRIOR_SPLIT_PATH, SOURCE_MANIFEST, SOURCE_DEVELOPMENT)
)


def test_product_jd_manifest_freezes_100_unique_cases_without_content() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    development = manifest["development"]["cases"]
    sealed = manifest["sealed_test"]["cases"]
    all_cases = development + sealed
    all_ids = [case["id"] for case in all_cases]

    assert manifest["case_count"] == len(all_ids) == len(set(all_ids)) == 100
    assert len(development) == manifest["development"]["case_count"] == 70
    assert len(sealed) == manifest["sealed_test"]["case_count"] == 30
    assert not {case["id"] for case in development} & {
        case["id"] for case in sealed
    }
    assert all("raw_content" not in case for case in all_cases)
    assert all("expected" not in case for case in all_cases)
    assert all(len(case["source_content_sha256"]) == 64 for case in all_cases)
    summary = manifest["development"]["label_summary"]
    assert summary["labeled_case_count"] == 70
    assert summary["requirement_count"] == 498
    assert summary["fact_positive_counts"]["major_requirements"] == 35
    assert summary["any_of_requirement_count"] == 43
    assert summary["responsibility_count"] == 304
    assert summary["empty_requirement_case_count"] == 0
    assert summary["empty_responsibility_case_count"] == 0
    assert summary["unsupported_metric_fields"] == ["deadline"]


@pytest.mark.skipif(not LOCAL_INPUTS_AVAILABLE, reason="local source artifacts missing")
def test_product_jd_manifest_preserves_prior_dev50_and_sealed30() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    prior = json.loads(PRIOR_SPLIT_PATH.read_text(encoding="utf-8"))

    development_ids = [case["id"] for case in manifest["development"]["cases"]]
    sealed_ids = [case["id"] for case in manifest["sealed_test"]["cases"]]
    prior_dev_ids = [case["id"] for case in prior["dev"]["cases"]]
    prior_sealed_ids = [case["id"] for case in prior["sealed_blind"]["cases"]]

    assert development_ids[:50] == prior_dev_ids
    assert sealed_ids == prior_sealed_ids
    assert all(
        case["selection_origin"] == "balanced_extension20"
        for case in manifest["development"]["cases"][50:]
    )


@pytest.mark.skipif(not LOCAL_INPUTS_AVAILABLE, reason="local source artifacts missing")
def test_product_jd_dataset_builder_is_reproducible_and_source_backed(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "manifest.json"
    development_path = tmp_path / "development.json"
    regenerated = build_development_revision(
        manifest_path=manifest_path,
        development_path=development_path,
    )
    frozen = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    development = json.loads(development_path.read_text(encoding="utf-8"))
    source_manifest = json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))

    assert regenerated["development"]["cases"] == frozen["development"]["cases"]
    assert regenerated["sealed_test"]["cases"] == frozen["sealed_test"]["cases"]
    assert regenerated["sealed_test"] == source_manifest["sealed_test"]
    assert development["label_revision"]["name"] == LABEL_REVISION
    assert development["label_revision"]["human_reviewed"] is False
    assert all(case["expected"] is not None for case in development["cases"][50:])

    for case in development["cases"]:
        output = ProductJDModelOutput.model_validate(case["expected"])
        validate_product_jd_output(output, case["raw_content"])
        major = output.facts.major_requirements
        if major is not None:
            assert not NON_HARD_MAJOR_PATTERN.search(major.source_text)
            assert "相关专业" not in major.values
