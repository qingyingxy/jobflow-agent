from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import draft_product_jd_test100_labels as label_draft
from src.infrastructure.llm_client import FakeModelClient


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _output(requirement: str = "熟悉 Python 或 Java") -> dict[str, object]:
    return {
        "facts": {
            "job_type": {"value": "campus", "source_text": "招聘类型：校招"},
            "locations": {"values": ["北京"], "source_text": "工作地点：北京"},
            "graduation_years": None,
            "education_requirements": None,
            "major_requirements": None,
            "deadline": None,
        },
        "requirements": [
            {
                "source_text": requirement,
                "level": "required",
                "relation": "any_of",
                "items": ["Python", "Java"],
                "relation_reason": "两门语言任选其一。",
            }
        ],
        "responsibilities": ["负责接口开发"],
    }


def _source_case(case_id: str, origin: str) -> dict[str, object]:
    raw_content = (
        "招聘类型：校招\n工作地点：北京\n任职要求：熟悉 Python 或 Java\n"
        "岗位职责：负责接口开发"
    )
    return {
        "id": case_id,
        "company": "示例公司",
        "title": "开发工程师",
        "source_url": f"https://example.com/{case_id}",
        "raw_content": raw_content,
        "verified_at": "2026-09-08",
        "selection_origin": origin,
        "source_content_sha256": _hash(raw_content),
        "source_content_length": len(raw_content),
    }


def _datasets() -> tuple[dict[str, object], dict[str, object]]:
    sealed_cases = [
        _source_case(f"sealed-{index:02d}", "prior_product_sealed30")
        for index in range(30)
    ]
    api_cases = [
        _source_case(f"api-{index:02d}", "original_strict_unused54")
        for index in range(70)
    ]
    source = {
        "dataset_version": "source-v1",
        "cases": sealed_cases + api_cases,
    }
    sealed = {
        "dataset_version": "sealed-v1",
        "cases": [
            {
                "id": case["id"],
                "source_content_sha256": case["source_content_sha256"],
                "annotation_status": "human_reviewed",
                "expected": _output(),
            }
            for case in sealed_cases
        ],
    }
    return source, sealed


def test_annotation_request_is_independent_and_source_backed() -> None:
    case = _source_case("api-00", "original_strict_unused54")

    request = label_draft.build_annotation_request(case)

    assert request.prompt_version == label_draft.ANNOTATION_PROMPT_VERSION
    assert request.schema_name == "independent_product_jd_annotation"
    assert case["raw_content"] in request.messages[-1].content
    assert "标准答案草案" in request.messages[0].content
    assert "ProductJDParser" not in " ".join(
        message.content for message in request.messages
    )


def test_annotation_granularity_rejects_compound_major_values() -> None:
    output = _output()
    output["facts"]["major_requirements"] = {
        "values": ["计算机、人工智能等相关专业"],
        "source_text": "计算机、人工智能等相关专业",
    }

    with pytest.raises(ValueError, match="逐字原子值"):
        label_draft.validate_annotation_granularity(
            label_draft.ProductJDModelOutput.model_validate(output)
        )


@pytest.mark.asyncio
async def test_label_draft_reuses_30_and_calls_api_only_for_new_cases(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source, sealed = _datasets()
    client = FakeModelClient(outputs=[_output()])
    monkeypatch.setattr(label_draft, "get_settings", object)
    monkeypatch.setattr(
        label_draft,
        "create_structured_model_client",
        lambda _settings: client,
    )

    result = await label_draft.generate_label_draft(
        source,
        sealed,
        output_path=tmp_path / "draft.json",
        max_new_cases=1,
        max_model_calls=1,
        concurrency=1,
        validation_retries=0,
        resume=False,
    )

    assert len(client.requests) == 1
    assert result["reused_case_count"] == 30
    assert result["api_success_count"] == 1
    assert result["api_failure_count"] == 0
    assert len(result["cases"]) == 31
    assert result["cases"][0]["annotation_status"] == "reused_human_reviewed"
    assert result["cases"][30]["annotation_status"] == "api_draft"
    assert "ProductJDParser" in result["independence_statement"]
    assert json.loads((tmp_path / "draft.json").read_text(encoding="utf-8")) == result


def test_review_queue_flags_semantics_without_changing_api_label() -> None:
    source_case = _source_case("api-00", "original_strict_unused54")
    proposal = _output()
    draft = {
        "dataset_version": "draft-v1",
        "status": "annotation_in_progress",
        "cases": [
            {
                "id": "api-00",
                "source": {
                    "company": source_case["company"],
                    "title": source_case["title"],
                    "source_url": source_case["source_url"],
                },
                "selection_origin": source_case["selection_origin"],
                "expected": proposal,
            }
        ],
    }
    old_core = {
        "cases": [
            {
                "id": "api-00",
                "expected": {
                    "fields": {
                        "job_type": "internship",
                        "locations": ["上海"],
                    }
                },
            }
        ]
    }

    queue = label_draft.build_review_queue(
        draft,
        {"cases": [source_case]},
        old_core,
    )

    assert queue["review_case_count"] == 1
    assert queue["cases"][0]["api_proposal"] == proposal
    codes = {issue["code"] for issue in queue["cases"][0]["issues"]}
    assert "old_core_job_type_conflict" in codes
    assert "old_core_locations_conflict" in codes
    assert queue["api_relation_counts"]["any_of"] == 1
    rendered = label_draft.render_review_markdown(queue)
    assert "任选其一" in rendered
    assert "any_of" not in rendered
