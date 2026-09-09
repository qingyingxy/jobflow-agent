from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.apply_product_jd_any_of_human_review as review_script
from scripts.apply_product_jd_any_of_human_review import (
    DATASET_VERSION,
    EXPECTED_CANDIDATE_COUNT,
    LABEL_REVISION,
    SOURCE_CANDIDATES,
    SOURCE_DECISIONS,
    SOURCE_DEVELOPMENT,
    _index_candidates,
    _resolve_decision_key,
    build_human_reviewed_development,
)
from src.domain.product_jd import ProductJDModelOutput, validate_product_jd_output

LOCAL_INPUTS_AVAILABLE = (
    SOURCE_DEVELOPMENT.exists()
    and SOURCE_CANDIDATES.exists()
    and SOURCE_DECISIONS.exists()
)


@pytest.mark.skipif(not LOCAL_INPUTS_AVAILABLE, reason="local review artifacts missing")
def test_any_of_human_review_is_complete_and_reproducible(tmp_path: Path) -> None:
    first_path = tmp_path / "development-first.json"
    second_path = tmp_path / "development-second.json"

    first = build_human_reviewed_development(development_path=first_path)
    second = build_human_reviewed_development(development_path=second_path)

    assert first == second
    assert first_path.read_bytes() == second_path.read_bytes()
    assert first["dataset_version"] == DATASET_VERSION
    assert first["case_count"] == len(first["cases"]) == 70
    assert first["label_revision"]["name"] == LABEL_REVISION
    assert first["label_revision"]["human_reviewed"] is True
    assert first["label_revision"]["sealed_test_read"] is False
    assert first["label_revision"]["candidate_count"] == EXPECTED_CANDIDATE_COUNT
    assert first["label_revision"]["decision_count"] == EXPECTED_CANDIDATE_COUNT
    assert first["label_revision"]["decision_summary"] == {
        "selected": {"api": 69, "gold": 3, "custom": 5},
        "final_relation": {"any_of": 73, "all_of": 4},
    }
    assert first["label_revision"]["application_summary"] == {
        "replaced_requirement_count": 73,
        "added_requirement_count": 4,
        "changed_requirement_count": 73,
    }

    for case in first["cases"]:
        assert case["label_revision"] == LABEL_REVISION
        output = ProductJDModelOutput.model_validate(case["expected"])
        validate_product_jd_output(output, case["raw_content"])


@pytest.mark.skipif(not LOCAL_INPUTS_AVAILABLE, reason="local review artifacts missing")
def test_any_of_human_review_reads_only_declared_development_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loaded_paths: list[Path] = []
    original_load_json = review_script._load_json

    def tracking_load_json(path: Path) -> object:
        loaded_paths.append(path.resolve())
        return original_load_json(path)

    monkeypatch.setattr(review_script, "_load_json", tracking_load_json)
    build_human_reviewed_development(
        development_path=tmp_path / "development.json"
    )

    assert loaded_paths == [
        SOURCE_DEVELOPMENT.resolve(),
        SOURCE_CANDIDATES.resolve(),
        SOURCE_DECISIONS.resolve(),
    ]


@pytest.mark.skipif(not LOCAL_INPUTS_AVAILABLE, reason="local review artifacts missing")
def test_any_of_human_review_covers_each_candidate_exactly_once() -> None:
    candidates = json.loads(SOURCE_CANDIDATES.read_text(encoding="utf-8"))
    review = json.loads(SOURCE_DECISIONS.read_text(encoding="utf-8"))

    candidate_index = _index_candidates(candidates)
    candidate_keys = set(candidate_index)
    decision_keys = [
        _resolve_decision_key(decision, candidate_index)
        for decision in review["decisions"]
    ]

    assert len(candidate_keys) == EXPECTED_CANDIDATE_COUNT
    assert len(decision_keys) == len(set(decision_keys)) == EXPECTED_CANDIDATE_COUNT
    assert set(decision_keys) == candidate_keys
