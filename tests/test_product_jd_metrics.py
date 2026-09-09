from __future__ import annotations

from src.evaluation.product_metrics import evaluate_product_dataset

SOURCE = (
    "招聘类型：实习生\n工作地点：北京\n要求熟悉 Python 或 Go。"
    "熟悉 RAG 优先。负责 Agent 开发。"
)
OUTPUT = {
    "facts": {
        "job_type": {"value": "internship", "source_text": "招聘类型：实习生"},
        "locations": {"values": ["北京"], "source_text": "工作地点：北京"},
    },
    "requirements": [
        {
            "source_text": "要求熟悉 Python 或 Go",
            "level": "required",
            "relation": "any_of",
            "items": ["Python", "Go"],
        },
        {
            "source_text": "熟悉 RAG 优先",
            "level": "preferred",
            "relation": "all_of",
            "items": ["RAG"],
        },
    ],
    "responsibilities": ["负责 Agent 开发"],
}


def _dataset() -> dict[str, object]:
    return {
        "dataset_version": "product-test-v1",
        "schema_version": "product-job-description-v1",
        "split": "development",
        "cases": [
            {
                "id": "case-1",
                "raw_content": SOURCE,
                "expected": OUTPUT,
            }
        ],
    }


def _predictions(output: object) -> dict[str, object]:
    return {
        "predictions": [
            {
                "case_id": "case-1",
                "output": output,
                "failure_code": None,
            }
        ]
    }


def test_product_metrics_score_perfect_prediction_without_fake_deadline_score() -> None:
    report = evaluate_product_dataset(_dataset(), _predictions(OUTPUT))

    assert report["schema_valid_rate"] == 1.0
    assert report["attempted_parse_success_rate"] == 1.0
    assert report["evidence_valid_rate"] == 1.0
    assert report["primary_metrics"] == {
        "parse_success_rate": 1.0,
        "schema_valid_rate": 1.0,
        "evidence_valid_rate": 1.0,
        "facts_value_macro_f1": 1.0,
        "hard_major_presence_f1": None,
        "requirement_source_character_f1": 1.0,
        "any_of_aligned_exact_group_f1": 1.0,
        "any_of_aligned_relation_group_f1": 1.0,
        "responsibility_source_character_f1": 1.0,
    }
    assert report["facts"]["macro_f1"] == 1.0
    assert report["facts"]["fields"]["deadline"]["f1"] is None
    assert "deadline" in report["facts"]["unsupported_fields"]
    assert report["requirements"]["exact"]["f1"] == 1.0
    assert report["requirements"]["character_coverage"]["all"]["f1"] == 1.0
    assert report["responsibilities"]["f1"] == 1.0
    assert report["responsibilities"]["character_coverage"]["f1"] == 1.0


def test_product_metrics_separate_span_match_from_level_confusion() -> None:
    prediction = {
        **OUTPUT,
        "requirements": [
            {**OUTPUT["requirements"][0], "level": "preferred"},
            OUTPUT["requirements"][1],
        ],
    }

    report = evaluate_product_dataset(_dataset(), _predictions(prediction))

    assert report["requirements"]["source"]["f1"] == 1.0
    assert report["requirements"]["level"]["f1"] == 0.5
    assert report["required_preferred_confusions"]["count"] == 1


def test_product_metrics_align_any_of_across_source_boundary_noise() -> None:
    prediction = {
        **OUTPUT,
        "requirements": [
            {**OUTPUT["requirements"][0], "source_text": "要求熟悉 Python 或 Go。"},
            OUTPUT["requirements"][1],
        ],
    }

    report = evaluate_product_dataset(_dataset(), _predictions(prediction))
    any_of = report["requirements"]["any_of"]

    assert any_of["exact_groups"]["f1"] == 0.0
    assert any_of["aligned_relation_groups"]["f1"] == 1.0
    assert any_of["aligned_exact_item_groups"]["f1"] == 1.0
    assert any_of["source_character_coverage"]["recall"] == 1.0


def test_product_metrics_separate_any_of_relation_from_item_granularity() -> None:
    prediction = {
        **OUTPUT,
        "requirements": [
            {
                **OUTPUT["requirements"][0],
                "items": ["Python 或 Go", "Go"],
            },
            OUTPUT["requirements"][1],
        ],
    }

    report = evaluate_product_dataset(_dataset(), _predictions(prediction))
    any_of = report["requirements"]["any_of"]

    assert any_of["aligned_relation_groups"]["f1"] == 1.0
    assert any_of["aligned_exact_item_groups"]["f1"] == 0.0


def test_product_metrics_separate_fact_source_from_value_granularity() -> None:
    source = SOURCE + "计算机、人工智能相关专业。"
    expected = {
        **OUTPUT,
        "facts": {
            **OUTPUT["facts"],
            "major_requirements": {
                "values": ["计算机", "人工智能"],
                "source_text": "计算机、人工智能相关专业",
            },
        },
    }
    prediction = {
        **expected,
        "facts": {
            **expected["facts"],
            "major_requirements": {
                "values": ["计算机、人工智能相关专业"],
                "source_text": "计算机、人工智能相关专业",
            },
        },
    }
    dataset = _dataset()
    dataset["cases"][0]["raw_content"] = source
    dataset["cases"][0]["expected"] = expected

    report = evaluate_product_dataset(dataset, _predictions(prediction))
    major = report["facts"]["fields"]["major_requirements"]

    assert major["value_exact"]["f1"] == 0.0
    assert major["presence"]["f1"] == 1.0
    assert major["source_character_coverage"]["f1"] == 1.0


def test_product_metrics_report_schema_and_evidence_failures_separately() -> None:
    invalid_schema = {"facts": [], "requirements": [], "responsibilities": []}
    report = evaluate_product_dataset(_dataset(), _predictions(invalid_schema))
    assert report["schema_valid_rate"] == 0.0
    assert report["evidence_valid_rate"] == 0.0

    invalid_evidence = {
        **OUTPUT,
        "responsibilities": ["不存在的职责"],
    }
    report = evaluate_product_dataset(_dataset(), _predictions(invalid_evidence))
    assert report["schema_valid_rate"] == 1.0
    assert report["evidence_valid_rate"] == 0.0
    assert "case-1" in report["evidence_errors"]


def test_product_metrics_scope_quality_to_attempted_cases() -> None:
    dataset = _dataset()
    dataset["cases"].append(
        {
            "id": "case-2",
            "raw_content": SOURCE,
            "expected": OUTPUT,
        }
    )

    report = evaluate_product_dataset(dataset, _predictions(OUTPUT))

    assert report["case_count"] == 2
    assert report["attempted_case_count"] == 1
    assert report["parse_success_rate"] == 0.5
    assert report["attempted_parse_success_rate"] == 1.0
    assert report["facts"]["macro_f1"] == 1.0
