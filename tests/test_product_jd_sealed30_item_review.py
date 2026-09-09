from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.apply_product_jd_sealed30_item_review as review_script
from scripts.apply_product_jd_sealed30_item_review import (
    DATASET_VERSION,
    EXPECTED_CASE_COUNT,
    EXPECTED_DECISION_COUNT,
    LABEL_REVISION,
    LABEL_STATUS,
    SOURCE_DECISIONS,
    SOURCE_LABELS,
    build_relation_items_reviewed_labels,
)
from src.domain.product_jd import ProductJDModelOutput, validate_product_jd_output

LOCAL_INPUTS_AVAILABLE = SOURCE_LABELS.exists() and SOURCE_DECISIONS.exists()


@pytest.mark.skipif(not LOCAL_INPUTS_AVAILABLE, reason="local sealed review inputs missing")
def test_sealed_item_review_is_complete_reproducible_and_items_only(
    tmp_path: Path,
) -> None:
    first_path = tmp_path / "labels-first.json"
    second_path = tmp_path / "labels-second.json"

    first = build_relation_items_reviewed_labels(labels_path=first_path)
    second = build_relation_items_reviewed_labels(labels_path=second_path)
    source = json.loads(SOURCE_LABELS.read_text(encoding="utf-8"))

    assert first == second
    assert first_path.read_bytes() == second_path.read_bytes()
    assert first["dataset_version"] == DATASET_VERSION
    assert first["label_status"] == LABEL_STATUS
    assert first["case_count"] == len(first["cases"]) == EXPECTED_CASE_COUNT
    assert first["label_revision"]["name"] == LABEL_REVISION
    assert first["label_revision"]["application_summary"] == {
        "decision_count": EXPECTED_DECISION_COUNT,
        "changed_item_group_count": 10,
        "kept_item_group_count": 1,
    }

    source_by_id = {case["id"]: case for case in source["cases"]}
    revised_by_id = {case["id"]: case for case in first["cases"]}
    for case_id, source_case in source_by_id.items():
        source_requirements = source_case["expected"]["requirements"]
        revised_requirements = revised_by_id[case_id]["expected"]["requirements"]
        assert len(source_requirements) == len(revised_requirements)
        for source_requirement, revised_requirement in zip(
            source_requirements,
            revised_requirements,
            strict=True,
        ):
            for field in ("source_text", "level", "relation", "relation_reason"):
                assert revised_requirement[field] == source_requirement[field]

    campus_005 = revised_by_id["campus-ai-005"]["expected"]["requirements"]
    assert next(
        item for item in campus_005 if item["source_text"] == "熟练C/C++或Python"
    )["items"] == ["C", "C++", "Python"]
    campus_149 = revised_by_id["campus-ai-149"]["expected"]["requirements"]
    kept = next(
        item
        for item in campus_149
        if item["source_text"].startswith("做过自己的小工具")
    )
    assert kept["items"] == [
        "小工具",
        "小程序",
        "插件",
        "AI 工作流",
        "App Demo",
        "低代码/无代码产品",
        "长期深度使用影像、剪辑、效率工具类软件",
    ]

    for case in first["cases"]:
        output = ProductJDModelOutput.model_validate(case["expected"])
        validate_product_jd_output(output, case["raw_content"])


@pytest.mark.skipif(not LOCAL_INPUTS_AVAILABLE, reason="local sealed review inputs missing")
def test_sealed_item_review_reads_only_declared_label_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loaded_paths: list[Path] = []
    original_load_json = review_script._load_json

    def tracking_load_json(path: Path) -> object:
        loaded_paths.append(path.resolve())
        return original_load_json(path)

    monkeypatch.setattr(review_script, "_load_json", tracking_load_json)
    build_relation_items_reviewed_labels(labels_path=tmp_path / "labels.json")

    assert loaded_paths == [SOURCE_LABELS.resolve(), SOURCE_DECISIONS.resolve()]


@pytest.mark.skipif(not LOCAL_INPUTS_AVAILABLE, reason="local sealed review inputs missing")
def test_sealed_item_review_rejects_pending_decision(tmp_path: Path) -> None:
    review = json.loads(SOURCE_DECISIONS.read_text(encoding="utf-8"))
    review["status"] = "in_progress_one_pending"
    review["confirmed_count"] = 10
    review["pending_count"] = 1
    review["decisions"][10]["status"] = "pending"
    decisions_path = tmp_path / "pending-decisions.json"
    decisions_path.write_text(
        json.dumps(review, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="not complete"):
        build_relation_items_reviewed_labels(
            decisions_path=decisions_path,
            labels_path=tmp_path / "labels.json",
        )
