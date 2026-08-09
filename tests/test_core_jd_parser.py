from __future__ import annotations

import pytest

from src.domain.job import RawJobDocument
from src.infrastructure.llm_client import FakeModelClient
from src.services.core_jd_parser import CoreJDParser

CORE_RAW = (
    "示例公司 2027 校园招聘，岗位工作地点为深圳市。"
    "任职要求：熟悉 Python、RAG 和 Agent，具备良好的沟通能力。"
)


@pytest.mark.asyncio
async def test_core_parser_keeps_contract_small_and_builds_local_evidence() -> None:
    client = FakeModelClient(
        output={
            "job_type": "campus",
            "locations": ["深圳"],
            "required_skills": ["Python"],
            "unexpected_detail": "should be ignored by the core adapter",
        }
    )
    parser = CoreJDParser(client, validation_retries=0)

    result = await parser.parse(RawJobDocument(raw_content=CORE_RAW))

    assert result.fields.model_dump() == {
        "job_type": "campus",
        "locations": ["深圳"],
        "required_skills": ["Python", "RAG", "Agent"],
    }
    assert result.field_evidence
    assert all(item.source_text in CORE_RAW for item in result.field_evidence)
    assert {item.field_path for item in result.field_evidence} == {
        "job_type",
        "locations[0]",
        "required_skills[0]",
        "required_skills[1]",
        "required_skills[2]",
    }

    assert client.last_request is not None
    assert client.last_request.schema_name == "core_job_fields"
    assert "qualification_conditions" not in client.last_request.messages[0].content
    assert "requirements" not in client.last_request.messages[0].content


@pytest.mark.asyncio
async def test_core_parser_preserves_null_when_source_has_no_core_signal() -> None:
    raw_content = "示例公司发布岗位信息，当前页面没有明确的类型、地点或技能要求。"
    parser = CoreJDParser(
        FakeModelClient(
            output={
                "job_type": None,
                "locations": None,
                "required_skills": None,
            }
        ),
        validation_retries=0,
    )

    result = await parser.parse(RawJobDocument(raw_content=raw_content))

    assert result.fields.model_dump() == {
        "job_type": None,
        "locations": None,
        "required_skills": None,
    }
    assert result.field_evidence == []


@pytest.mark.asyncio
async def test_core_parser_discards_model_job_type_without_source_evidence() -> None:
    raw_content = "示例公司发布算法岗位，工作内容是开发和测试，招聘类型未在正文中披露。"
    parser = CoreJDParser(
        FakeModelClient(
            output={
                "job_type": "campus",
                "locations": None,
                "required_skills": None,
            }
        ),
        validation_retries=0,
    )

    result = await parser.parse(RawJobDocument(raw_content=raw_content))

    assert result.fields.job_type is None
    assert result.field_evidence == []


@pytest.mark.asyncio
async def test_core_parser_accepts_job_title_metadata_as_traceable_evidence() -> None:
    parser = CoreJDParser(
        FakeModelClient(
            output={
                "job_type": "internship",
                "locations": None,
                "required_skills": None,
            }
        ),
        validation_retries=0,
    )

    result = await parser.parse(
        RawJobDocument(
            raw_content="岗位负责 AI 应用开发与测试，具体招聘类型请以页面标题为准。",
            source_metadata={"title": "AI 应用开发实习生"},
        )
    )

    assert result.fields.job_type == "internship"
    assert result.field_evidence[0].field_path == "job_type"
    assert result.field_evidence[0].source_kind == "metadata"


@pytest.mark.asyncio
async def test_core_parser_treats_graduate_recruitment_as_campus_evidence() -> None:
    parser = CoreJDParser(
        FakeModelClient(
            output={
                "job_type": "campus",
                "locations": ["北京"],
                "required_skills": None,
            }
        ),
        validation_retries=0,
    )

    result = await parser.parse(
        RawJobDocument(
            raw_content="招聘类型：应届生\n工作地点：北京市\n岗位职责：负责 AI 应用研发与测试。"
        )
    )

    assert result.fields.job_type == "campus"
    assert result.field_evidence[0].field_path == "job_type"
    assert result.field_evidence[0].source_text == "应届生"
