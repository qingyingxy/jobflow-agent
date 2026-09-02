from __future__ import annotations

import pytest

from src.domain.job import RawJobDocument
from src.infrastructure.llm_client import (
    StructuredModelRequest,
    StructuredModelResponse,
)
from src.services.staged_jd_parser import StagedJDParser

RAW_CONTENT = (
    "示例公司招聘 AI 应用开发实习生，工作地点为北京。"
    "任职要求：本科及以上学历，计算机相关专业，熟悉 RAG。"
)


class SequenceModelClient:
    model_name = "staged-test-model"
    provider = "test"

    def __init__(self, outputs: list[dict[str, object]]) -> None:
        self.outputs = outputs
        self.requests: list[StructuredModelRequest] = []

    async def generate(self, request: StructuredModelRequest) -> StructuredModelResponse:
        self.requests.append(request)
        return StructuredModelResponse(
            output=self.outputs.pop(0),
            model=self.model_name,
            provider=self.provider,
        )


@pytest.mark.asyncio
async def test_staged_parser_assembles_full_contract_from_two_small_outputs() -> None:
    client = SequenceModelClient(
        [
            {
                "job_type": "internship",
                "locations": ["北京"],
                "required_skills": ["RAG"],
            },
            {
                "company": "示例公司",
                "title": "AI 应用开发实习生",
                "requirements": {
                    "education": "本科及以上学历",
                    "major": "计算机相关专业",
                },
                "qualification_conditions": ["本科及以上学历"],
            },
        ]
    )
    parser = StagedJDParser(client, validation_retries=0)

    result = await parser.parse(RawJobDocument(raw_content=RAW_CONTENT))

    structured = result.structured_jd
    assert structured.job_type == "internship"
    assert structured.locations == ["北京"]
    assert structured.required_skills == ["RAG"]
    assert structured.education_requirements == ["本科及以上学历"]
    assert structured.major_requirements == ["计算机相关专业"]
    assert structured.qualification_conditions is not None
    assert [item.category for item in structured.requirements or []] == [
        "required_skill",
        "education",
        "major",
    ]
    assert all(
        item.evidence and item.evidence[0].source_text in RAW_CONTENT
        for item in structured.requirements or []
    )
    assert [request.schema_name for request in client.requests] == [
        "core_job_fields",
        "detail_job_fields",
    ]
    assert "field_evidence" not in client.requests[1].json_schema["properties"]
    assert "required_skills" not in client.requests[1].json_schema["properties"]


@pytest.mark.asyncio
async def test_staged_parser_can_finish_with_core_fields_when_detail_is_empty() -> None:
    client = SequenceModelClient(
        [
            {
                "job_type": "internship",
                "locations": ["北京"],
                "required_skills": ["RAG"],
            },
            {},
        ]
    )

    result = await StagedJDParser(client, validation_retries=0).parse(
        RawJobDocument(raw_content="示例公司招聘实习生，熟悉 RAG，工作地点北京。")
    )

    assert result.structured_jd.required_skills == ["RAG"]
    assert result.structured_jd.requirements is not None
    assert result.structured_jd.company is None


@pytest.mark.asyncio
async def test_staged_parser_preserves_skill_groups_and_merges_preferred_skills() -> None:
    raw_content = (
        "示例公司 2027 校园招聘，工作地点上海。"
        "任职要求：掌握 Python；熟悉 Go 或 Java 中任一种；"
        "CUDA 使用经验优先；了解 RAG。"
    )
    client = SequenceModelClient(
        [
            {
                "job_type": "campus",
                "locations": ["上海"],
                "required_skills": ["Python"],
                "required_skill_groups": [
                    {
                        "name": "后端编程语言",
                        "any_of": ["Go", "Java"],
                        "allow_other": False,
                    }
                ],
                "preferred_skills": ["CUDA"],
                "skill_mentions": ["RAG"],
            },
            {
                "preferred_skills": ["CUDA"],
                "requirements": [
                    {
                        "category": "preferred_skill",
                        "name": "CUDA",
                        "description": "CUDA 使用经验优先",
                        "mandatory": False,
                    }
                ],
            },
        ]
    )

    result = await StagedJDParser(client, validation_retries=0).parse(
        RawJobDocument(raw_content=raw_content)
    )
    structured = result.structured_jd

    assert structured.required_skills == ["Python"]
    assert [group.model_dump() for group in structured.required_skill_groups or []] == [
        {
            "name": "编程语言",
            "any_of": ["Go", "Java"],
            "allow_other": False,
        }
    ]
    assert structured.preferred_skills == ["CUDA"]
    assert structured.skill_mentions == ["RAG", "Go", "Java"]
    assert [item.category for item in structured.requirements or []] == [
        "required_skill",
        "preferred_skill",
    ]


@pytest.mark.asyncio
async def test_staged_parser_preserves_core_warnings() -> None:
    client = SequenceModelClient(
        [
            {
                "job_type": "internship",
                "locations": ["北京"],
                "required_skills": ["RAG", "GhostSkill"],
            },
            {},
        ]
    )

    result = await StagedJDParser(client, validation_retries=0).parse(
        RawJobDocument(raw_content="示例公司招聘实习生，要求熟悉 RAG，工作地点北京。")
    )

    assert result.structured_jd.required_skills == ["RAG"]
    assert len(result.warnings) == 1
    assert result.warnings[0].field_path == "required_skills[1]"
    assert result.warnings[0].value == "GhostSkill"
