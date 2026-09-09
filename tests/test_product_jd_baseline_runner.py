from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import run_product_jd_baseline
from src.infrastructure.llm_client import FakeModelClient


def test_product_baseline_runner_filters_explicit_case_ids() -> None:
    dataset = {
        "case_count": 3,
        "cases": [{"id": "case-1"}, {"id": "case-2"}, {"id": "case-3"}],
    }

    selected = run_product_jd_baseline._filter_dataset(
        dataset,
        ["case-3", "case-1"],
    )

    assert selected["case_count"] == 2
    assert [case["id"] for case in selected["cases"]] == ["case-3", "case-1"]
    assert dataset["case_count"] == 3


def test_product_baseline_runner_rejects_unknown_or_duplicate_case_ids() -> None:
    dataset = {"case_count": 1, "cases": [{"id": "case-1"}]}

    with pytest.raises(ValueError, match="must be unique"):
        run_product_jd_baseline._filter_dataset(dataset, ["case-1", "case-1"])
    with pytest.raises(ValueError, match="Unknown"):
        run_product_jd_baseline._filter_dataset(dataset, ["case-2"])


@pytest.mark.asyncio
async def test_product_baseline_runner_records_both_api_stages(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_text = "要求熟悉 Python 或 Java"
    raw_content = f"某公司招聘开发实习生。{source_text}。负责接口开发。"
    extraction = {
        "facts": {},
        "requirements": [
            {"source_text": source_text, "level": "required"},
        ],
        "responsibilities": ["负责接口开发"],
    }
    judgment = {
        "decisions": [
            {
                "requirement_index": 0,
                "relation": "any_of",
                "items": ["Python", "Java"],
                "reason": "两个语言是可互相替代的选项。",
            }
        ]
    }
    client = FakeModelClient(outputs=[extraction, judgment])
    monkeypatch.setattr(run_product_jd_baseline, "get_settings", object)
    monkeypatch.setattr(
        run_product_jd_baseline,
        "create_structured_model_client",
        lambda _settings: client,
    )
    predictions_path = tmp_path / "predictions.json"
    dataset = {
        "dataset_version": "product-test-v1",
        "schema_version": "product-job-description-v1",
        "split": "development",
        "cases": [
            {
                "id": "case-1",
                "raw_content": raw_content,
                "source": {
                    "source_url": "https://example.com/jobs/1",
                    "company": "某公司",
                    "title": "开发实习生",
                },
            }
        ],
    }

    result = await run_product_jd_baseline.generate_predictions(
        dataset,
        predictions_path=predictions_path,
        max_new_cases=None,
        max_model_calls=2,
        concurrency=1,
        validation_retries=0,
        resume=False,
    )

    assert len(client.requests) == 2
    assert result["schema_version"] == "product-job-description-v2"
    assert result["prediction_version"] == "product-jd-development70-two-stage-v6"
    assert result["parser_version"] == "product-jd-parser-v3"
    assert result["prompt_version"] == "product-jd-two-stage-v6"
    assert result["extraction_prompt_version"] == "product-jd-extraction-v5"
    assert result["relation_prompt_version"] == "product-jd-relation-v5"
    assert result["reasoning_effort"] == "provider_default"
    assert result["response_format"] == "provider_default"
    prediction = result["predictions"][0]
    assert prediction["model_call_count"] == 2
    assert prediction["raw_extraction"] == extraction
    assert prediction["raw_relation_judgment"] == judgment
    assert prediction["output"]["requirements"][0]["relation"] == "any_of"
    assert json.loads(predictions_path.read_text(encoding="utf-8")) == result


@pytest.mark.asyncio
async def test_product_baseline_runner_retries_only_failed_checkpoint_cases(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    requirement_text = "要求熟悉 Python 或 Java"
    extraction = {
        "facts": {},
        "requirements": [
            {"source_text": requirement_text, "level": "required"},
        ],
        "responsibilities": ["负责接口开发"],
    }
    judgment = {
        "decisions": [
            {
                "requirement_index": 0,
                "relation": "any_of",
                "items": ["Python", "Java"],
                "reason": "两种语言满足任意一种即可。",
            }
        ]
    }
    client = FakeModelClient(outputs=[extraction, judgment])
    monkeypatch.setattr(run_product_jd_baseline, "get_settings", object)
    monkeypatch.setattr(
        run_product_jd_baseline,
        "create_structured_model_client",
        lambda _settings: client,
    )
    predictions_path = tmp_path / "predictions.json"
    dataset = {
        "dataset_version": "product-test-v1",
        "cases": [
            {
                "id": "case-1",
                "raw_content": (
                    f"某公司招聘开发实习生。{requirement_text}。负责接口开发。"
                ),
                "source": {
                    "source_url": "https://example.com/jobs/1",
                    "company": "某公司",
                    "title": "开发实习生",
                },
            }
        ],
    }
    predictions_path.write_text(
        json.dumps(
            {
                "prediction_version": "product-jd-development70-two-stage-v4",
                "dataset_version": "product-test-v1",
                "schema_version": "product-job-description-v2",
                "parser_version": "product-jd-parser-v3",
                "prompt_version": "product-jd-two-stage-v6",
                "extraction_prompt_version": "product-jd-extraction-v5",
                "relation_prompt_version": "product-jd-relation-v5",
                "model": client.model_name,
                "generated_at": "2026-09-06T00:00:00+00:00",
                "predictions": [
                    {
                        "case_id": "case-1",
                        "output": None,
                        "failure_code": "model_response_invalid",
                        "model_call_count": 1,
                        "diagnostics": {"status_code": 402},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = await run_product_jd_baseline.generate_predictions(
        dataset,
        predictions_path=predictions_path,
        max_new_cases=None,
        max_model_calls=3,
        concurrency=1,
        validation_retries=0,
        resume=True,
        retry_failures=True,
    )

    prediction = result["predictions"][0]
    assert len(client.requests) == 2
    assert prediction["output"] is not None
    assert prediction["model_call_count"] == 3
    assert prediction["diagnostics"]["previous_attempt"]["failure_code"] == (
        "model_response_invalid"
    )
