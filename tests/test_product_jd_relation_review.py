from __future__ import annotations

from scripts.analyze_product_jd_relation_disagreements import analyze_disagreements


def test_relation_review_separates_matches_extras_and_sanitizer_downgrades() -> None:
    any_of = {
        "source_text": "熟悉 Python 或 Java",
        "level": "required",
        "relation": "any_of",
        "items": ["Python", "Java"],
    }
    all_of = {
        "source_text": "具备沟通能力",
        "level": "required",
        "relation": "all_of",
        "items": ["具备沟通能力"],
    }
    predicted_extra = {
        **all_of,
        "relation": "any_of",
        "items": ["沟通", "能力"],
    }
    raw_downgrade = {
        "source_text": "熟悉 SQL 和 Linux",
        "level": "required",
        "relation": "any_of",
        "items": ["SQL", "Linux"],
    }
    dataset = {
        "dataset_version": "test-v1",
        "cases": [
            {
                "id": "case-1",
                "annotation_status": "agent_reviewed",
                "raw_content": (
                    "熟悉 Python 或 Java；具备沟通能力；熟悉 SQL 和 Linux"
                ),
                "expected": {"requirements": [any_of, all_of]},
            }
        ],
    }
    predictions = {
        "prediction_version": "prediction-v1",
        "predictions": [
            {
                "case_id": "case-1",
                "output": {"requirements": [any_of, predicted_extra]},
                "raw_output": {
                    "requirements": [any_of, predicted_extra, raw_downgrade]
                },
            }
        ],
    }

    result = analyze_disagreements(dataset, predictions)

    assert result["sealed_test_read"] is False
    assert result["summary"] == {
        "gold_any_of_count": 1,
        "predicted_any_of_count": 2,
        "gold_any_of_disagreement_count": 0,
        "predicted_any_of_disagreement_count": 1,
        "sanitizer_downgrade_count": 1,
    }
    assert result["predicted_any_of_disagreements"][0]["best_gold"] == all_of
    assert result["sanitizer_downgrades"][0]["raw_requirement"] == raw_downgrade


def test_relation_review_skips_missing_and_failed_predictions() -> None:
    dataset = {
        "dataset_version": "test-v1",
        "cases": [
            {
                "id": "missing",
                "annotation_status": "reviewed",
                "raw_content": "熟悉 Python 或 Java",
                "expected": {"requirements": []},
            },
            {
                "id": "failed",
                "annotation_status": "reviewed",
                "raw_content": "熟悉 Python 或 Java",
                "expected": {"requirements": []},
            },
        ],
    }
    predictions = {
        "prediction_version": "prediction-v1",
        "predictions": [
            {"case_id": "failed", "output": None},
        ],
    }

    result = analyze_disagreements(dataset, predictions)

    assert result["missing_prediction_case_ids"] == ["missing"]
    assert result["failed_prediction_case_ids"] == ["failed"]
    assert result["summary"]["gold_any_of_count"] == 0
