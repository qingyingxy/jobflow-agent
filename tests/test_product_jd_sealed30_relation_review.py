from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.apply_product_jd_sealed30_relation_review as review_script
from scripts.apply_product_jd_sealed30_relation_review import (
    DATASET_VERSION,
    EXPECTED_CASE_COUNT,
    EXPECTED_DECISION_COUNT,
    LABEL_REVISION,
    LABEL_STATUS,
    SOURCE_DECISIONS,
    SOURCE_LABELS,
    build_relation_reviewed_labels,
)
from src.domain.product_jd import ProductJDModelOutput, validate_product_jd_output

LOCAL_INPUTS_AVAILABLE = SOURCE_LABELS.exists() and SOURCE_DECISIONS.exists()


def _requirements_by_case(payload: dict) -> dict[str, list[dict]]:
    return {
        case["id"]: case["expected"]["requirements"]
        for case in payload["cases"]
    }


@pytest.mark.skipif(not LOCAL_INPUTS_AVAILABLE, reason="local sealed review inputs missing")
def test_sealed_relation_review_is_complete_and_reproducible(tmp_path: Path) -> None:
    first_path = tmp_path / "labels-first.json"
    second_path = tmp_path / "labels-second.json"

    first = build_relation_reviewed_labels(labels_path=first_path)
    second = build_relation_reviewed_labels(labels_path=second_path)

    assert first == second
    assert first_path.read_bytes() == second_path.read_bytes()
    assert first["dataset_version"] == DATASET_VERSION
    assert first["label_status"] == LABEL_STATUS
    assert first["case_count"] == len(first["cases"]) == EXPECTED_CASE_COUNT
    assert first["label_revision"]["name"] == LABEL_REVISION
    assert first["label_revision"]["human_reviewed_relation_scope"] is True
    assert first["label_revision"]["fully_human_reviewed"] is False
    assert first["label_revision"]["application_summary"] == {
        "decision_count": EXPECTED_DECISION_COUNT,
        "kept_decision_count": 4,
        "modified_decision_count": 6,
        "removed_requirement_count": 7,
        "inserted_requirement_count": 9,
    }

    requirements = _requirements_by_case(first)
    assert next(
        item
        for item in requirements["campus-ai-034"]
        if item["source_text"].startswith("扎实的Web前端基础")
    )["relation"] == "all_of"
    assert next(
        item
        for item in requirements["campus-ai-038"]
        if item["source_text"] == "熟悉SQL/HQL及数据分析工具"
    )["items"] == ["SQL", "HQL"]
    assert next(
        item
        for item in requirements["campus-ai-095"]
        if item["source_text"].startswith("扎实的 Python/Java")
    )["relation"] == "all_of"

    for case in first["cases"]:
        assert case["annotation_status"] == LABEL_STATUS
        output = ProductJDModelOutput.model_validate(case["expected"])
        validate_product_jd_output(output, case["raw_content"])


@pytest.mark.skipif(not LOCAL_INPUTS_AVAILABLE, reason="local sealed review inputs missing")
def test_sealed_relation_review_reads_only_declared_label_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loaded_paths: list[Path] = []
    original_load_json = review_script._load_json

    def tracking_load_json(path: Path) -> object:
        loaded_paths.append(path.resolve())
        return original_load_json(path)

    monkeypatch.setattr(review_script, "_load_json", tracking_load_json)
    build_relation_reviewed_labels(labels_path=tmp_path / "labels.json")

    assert loaded_paths == [SOURCE_LABELS.resolve(), SOURCE_DECISIONS.resolve()]


@pytest.mark.skipif(not LOCAL_INPUTS_AVAILABLE, reason="local sealed review inputs missing")
def test_sealed_relation_review_rejects_pending_decision(tmp_path: Path) -> None:
    review = json.loads(SOURCE_DECISIONS.read_text(encoding="utf-8"))
    review["status"] = "in_progress_one_pending"
    review["confirmed_count"] = 9
    review["pending_count"] = 1
    review["decisions"][1]["status"] = "pending"
    decisions_path = tmp_path / "pending-decisions.json"
    decisions_path.write_text(
        json.dumps(review, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="not complete"):
        build_relation_reviewed_labels(
            decisions_path=decisions_path,
            labels_path=tmp_path / "labels.json",
        )
