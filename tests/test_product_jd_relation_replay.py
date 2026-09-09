from __future__ import annotations

from pathlib import Path

import pytest

from scripts import run_product_jd_relation_replay
from src.infrastructure.llm_client import FakeModelClient


@pytest.mark.asyncio
async def test_relation_replay_reuses_saved_extraction_without_extraction_call(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_text = "要求熟悉 Python 或 Java"
    raw_content = f"开发岗位。{source_text}。负责接口开发。"
    extraction = {
        "facts": {},
        "requirements": [{"source_text": source_text, "level": "required"}],
        "responsibilities": ["负责接口开发"],
    }
    judgment = {
        "decisions": [
            {
                "requirement_index": 0,
                "relation": "any_of",
                "items": ["Python", "Java"],
                "reason": "两个语言是可替代选项。",
            }
        ]
    }
    client = FakeModelClient(outputs=[judgment])
    monkeypatch.setattr(run_product_jd_relation_replay, "get_settings", object)
    monkeypatch.setattr(
        run_product_jd_relation_replay,
        "create_structured_model_client",
        lambda _settings: client,
    )
    dataset = {
        "dataset_version": "product-test-v2",
        "cases": [
            {
                "id": "case-1",
                "raw_content": raw_content,
                "source": {
                    "source_url": "https://example.com/jobs/1",
                    "company": "Example",
                    "title": "Developer",
                },
            }
        ],
    }
    source_predictions = {
        "prediction_version": "source-v4",
        "dataset_version": "product-test-v1",
        "extraction_prompt_version": "product-jd-extraction-v4",
        "predictions": [
            {
                "case_id": "case-1",
                "raw_extraction": extraction,
            }
        ],
    }

    result = await run_product_jd_relation_replay.generate_relation_replay(
        dataset,
        source_predictions,
        predictions_path=tmp_path / "predictions.json",
        max_model_calls=2,
        concurrency=1,
        validation_retries=0,
        resume=False,
    )

    assert len(client.requests) == 1
    assert client.requests[0].schema_name == "product_requirement_relations"
    assert result["replay_mode"] == "reuse_source_raw_extraction_relation_only"
    assert result["extraction_prompt_version"] == "product-jd-extraction-v4"
    assert result["relation_prompt_version"] == "product-jd-relation-v5"
    prediction = result["predictions"][0]
    assert prediction["raw_extraction"] == extraction
    assert prediction["raw_relation_judgment"] == judgment
    assert prediction["model_call_count"] == 1
    assert prediction["output"]["requirements"][0]["relation"] == "any_of"
    assert prediction["diagnostics"]["source_extraction_reused"] is True
