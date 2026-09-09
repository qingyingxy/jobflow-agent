from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.apply_product_jd_test100_review as review_script
from scripts.apply_product_jd_test100_review import (
    DATASET_VERSION,
    DEFAULT_LABELS,
    EXPECTED_BOUNDARY_COUNT,
    EXPECTED_CASE_COUNT,
    EXPECTED_REVIEW_COUNT,
    LABEL_STATUS,
    SOURCE_BOUNDARIES,
    SOURCE_DATASET,
    SOURCE_DRAFT,
    SOURCE_PREREGISTRATION,
    SOURCE_REVIEW_QUEUE,
    build_freeze_receipt,
    build_reviewed_labels,
)
from scripts.extract_product_jd_confirmed_any_of_items import (
    collect_confirmed_groups,
    validate_boundary_group,
)
from src.domain.product_jd import ProductJDModelOutput, validate_product_jd_output

LOCAL_INPUTS_AVAILABLE = all(
    path.exists()
    for path in (
        SOURCE_DATASET,
        SOURCE_DRAFT,
        SOURCE_REVIEW_QUEUE,
        SOURCE_BOUNDARIES,
        SOURCE_PREREGISTRATION,
    )
)


def test_confirmed_boundary_helpers_require_verbatim_unique_items() -> None:
    queue = json.loads(SOURCE_REVIEW_QUEUE.read_text(encoding="utf-8"))
    requested = collect_confirmed_groups(queue)

    assert len(requested) == EXPECTED_BOUNDARY_COUNT
    assert {item["case_id"] for item in requested} == {
        "campus-ai-106",
        "campus-ai-136",
        "campus-ai-137",
    }

    request = {"case_id": "case-1", "source_text": "熟悉 Python 或 Java"}
    result = validate_boundary_group(
        request,
        {
            "case_id": "case-1",
            "source_text": "熟悉 Python 或 Java",
            "candidate_items": ["Python", "Java"],
        },
    )
    assert result["items"] == ["Python", "Java"]

    with pytest.raises(ValueError, match="verbatim evidence"):
        validate_boundary_group(
            request,
            {
                "case_id": "case-1",
                "source_text": "熟悉 Python 或 Java",
                "candidate_items": ["Python", "Go"],
            },
        )
    with pytest.raises(ValueError, match="duplicate"):
        validate_boundary_group(
            {"case_id": "case-1", "source_text": "熟悉 Python 或 python"},
            {
                "case_id": "case-1",
                "source_text": "熟悉 Python 或 python",
                "candidate_items": ["Python", "python"],
            },
        )


@pytest.mark.skipif(not LOCAL_INPUTS_AVAILABLE, reason="local test-100 artifacts missing")
def test_reviewed_test100_is_complete_valid_and_reproducible(tmp_path: Path) -> None:
    first_path = tmp_path / "reviewed-first.json"
    second_path = tmp_path / "reviewed-second.json"
    first = build_reviewed_labels(labels_path=first_path)
    second = build_reviewed_labels(labels_path=second_path)

    assert first == second
    assert first_path.read_bytes() == second_path.read_bytes()
    assert first["dataset_version"] == DATASET_VERSION
    assert first["label_status"] == LABEL_STATUS
    assert first["split"] == "test"
    assert first["case_count"] == len(first["cases"]) == EXPECTED_CASE_COUNT
    assert first["fully_human_reviewed"] is False
    assert first["label_revision"]["review_case_count"] == EXPECTED_REVIEW_COUNT
    assert first["label_revision"]["boundary_group_count"] == EXPECTED_BOUNDARY_COUNT
    assert first["label_revision"]["operation_counts"] == {
        "keep_api": 2,
        "replace_requirement": 15,
        "replace_requirements": 2,
        "set_all_flagged_relations_any_of": 1,
        "set_all_flagged_relations_to_any_of": 2,
        "split_requirement": 6,
    }
    assert first["label_revision"]["target_count"] == 34
    assert first["label_revision"]["changed_target_count"] == 34
    assert first["label_revision"]["inserted_requirement_count"] == 7

    for case in first["cases"]:
        output = ProductJDModelOutput.model_validate(case["expected"])
        validate_product_jd_output(output, case["raw_content"])
        assert all(
            requirement["relation"] != "uncertain"
            for requirement in case["expected"]["requirements"]
        )


@pytest.mark.skipif(not LOCAL_INPUTS_AVAILABLE, reason="local test-100 artifacts missing")
def test_reviewed_test100_applies_representative_decisions(tmp_path: Path) -> None:
    dataset = build_reviewed_labels(labels_path=tmp_path / "reviewed.json")
    cases = {case["id"]: case for case in dataset["cases"]}

    case_106 = cases["campus-ai-106"]
    reviewed_106 = {
        requirement["source_text"]: requirement
        for requirement in case_106["expected"]["requirements"]
    }
    boundaries = json.loads(SOURCE_BOUNDARIES.read_text(encoding="utf-8"))
    groups_106 = [
        group for group in boundaries["groups"] if group["case_id"] == "campus-ai-106"
    ]
    assert len(groups_106) == 4
    for group in groups_106:
        requirement = reviewed_106[group["source_text"]]
        assert requirement["relation"] == "any_of"
        assert requirement["items"] == group["items"]
    diffusion_items = groups_106[1]["items"]
    assert sum(item.casefold() == "diffusion policy" for item in diffusion_items) == 1

    case_105 = cases["campus-ai-105"]
    direction_group = next(
        requirement
        for requirement in case_105["expected"]["requirements"]
        if "以下方向满足其中一项或多项即可" in requirement["source_text"]
    )
    assert direction_group["relation"] == "any_of"
    assert len(direction_group["items"]) == 6

    assert cases["campus-ai-094"]["expected"]["responsibilities"] == []
    assert all(
        requirement["source_text"]
        != "动手能力及主动学习能力强，细致严谨，能够深入一线参与样机装配、调试和问题复盘。"
        for requirement in cases["campus-ai-132"]["expected"]["requirements"]
    )
    assert any(
        requirement["source_text"]
        == "能够深入一线参与样机装配、调试和问题复盘。"
        for requirement in cases["campus-ai-132"]["expected"]["requirements"]
    )


@pytest.mark.skipif(not LOCAL_INPUTS_AVAILABLE, reason="local test-100 artifacts missing")
def test_review_builder_reads_only_declared_label_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loaded_paths: list[Path] = []
    original_load_json = review_script._load_json

    def tracking_load_json(path: Path) -> dict[str, object]:
        loaded_paths.append(path.resolve())
        return original_load_json(path)

    monkeypatch.setattr(review_script, "_load_json", tracking_load_json)
    build_reviewed_labels(labels_path=tmp_path / "reviewed.json")

    assert loaded_paths == [
        SOURCE_DATASET.resolve(),
        SOURCE_DRAFT.resolve(),
        SOURCE_REVIEW_QUEUE.resolve(),
        SOURCE_BOUNDARIES.resolve(),
        SOURCE_PREREGISTRATION.resolve(),
    ]


@pytest.mark.skipif(not DEFAULT_LABELS.exists(), reason="frozen test-100 labels missing")
def test_test100_freeze_receipt_binds_labels_and_runtime() -> None:
    receipt = build_freeze_receipt()

    assert receipt["status"] == "frozen"
    assert receipt["prediction_status"] == "not_generated_or_viewed"
    assert receipt["case_count"] == EXPECTED_CASE_COUNT
    assert receipt["runtime"]["model"] == "gpt-5.6-terra"
    assert receipt["runtime"]["reasoning_effort"] == "medium"
    assert set(receipt["runtime"]["files"]) == {
        "parser_implementation",
        "output_contract",
        "evaluation_metrics",
        "evaluation_runner",
    }
