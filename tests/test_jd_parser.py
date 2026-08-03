from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest

from src.config import Settings
from src.domain.job import RawJobDocument
from src.infrastructure.llm_client import (
    FakeModelClient,
    ModelResponseError,
    ModelTimeoutError,
    OpenAICompatibleModelClient,
    StructuredModelRequest,
    create_structured_model_client,
)
from src.services.jd_parser import JDParser, JDParserError

JOB_TEXT = "示例公司招聘 AI 应用开发实习生，熟悉 RAG，工作地点为北京。"


def document() -> RawJobDocument:
    return RawJobDocument(
        source_url="https://example.com/job/1",
        raw_content=JOB_TEXT,
        retrieved_at=datetime.now(UTC),
    )


def valid_output() -> dict[str, object]:
    return {
        "company": "示例公司",
        "title": "AI 应用开发实习生",
        "locations": ["北京"],
        "required_skills": ["RAG"],
        "requirements": [
            {
                "category": "required_skill",
                "name": "RAG",
                "description": "熟悉 RAG",
                "mandatory": True,
                "evidence": [
                    {
                        "field_path": "requirements[0]",
                        "source_text": "熟悉 RAG",
                    }
                ],
            }
        ],
        "field_evidence": [
            {"field_path": "company", "source_text": "示例公司"},
            {"field_path": "title", "source_text": "AI 应用开发实习生"},
            {"field_path": "locations", "source_text": "北京"},
            {"field_path": "required_skills", "source_text": "熟悉 RAG"},
            {"field_path": "requirements[0]", "source_text": "熟悉 RAG"},
        ],
    }


@pytest.mark.asyncio
async def test_parser_returns_valid_structured_result_and_request() -> None:
    client = FakeModelClient(output=valid_output())
    parser = JDParser(client)

    result = await parser.parse(document())

    assert result.structured_jd.company == "示例公司"
    assert result.structured_jd.required_skills == ["RAG"]
    assert result.input_hash
    assert client.last_request is not None
    assert client.last_request.prompt_version == "jd-parser-prompt-v2"
    assert "岗位文本" in client.last_request.messages[1].content


@pytest.mark.asyncio
async def test_parser_keeps_missing_fields_as_null() -> None:
    result = await JDParser(FakeModelClient(output={"field_evidence": []})).parse(
        document()
    )

    assert result.structured_jd.company is None
    assert result.structured_jd.requirements is None
    assert result.structured_jd.field_evidence == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("output", "code"),
    [
        ({"field_evidence": [], "unexpected": "x"}, "structured_output_invalid"),
        ({"title": 123, "field_evidence": []}, "structured_output_invalid"),
        (
            {
                "qualification_conditions": [
                    {
                        "field": "学历",
                        "operator": "gte",
                        "value": None,
                        "evidence": [
                            {
                                "field_path": "qualification_conditions[0]",
                                "source_text": "本科以上",
                            }
                        ],
                    }
                ],
                "field_evidence": [
                    {
                        "field_path": "qualification_conditions[0]",
                        "source_text": "本科以上",
                    }
                ],
            },
            "structured_output_invalid",
        ),
        (
            {"title": "示例岗位", "field_evidence": []},
            "structured_output_invalid",
        ),
    ],
)
async def test_parser_rejects_invalid_structured_output(
    output: dict[str, object],
    code: str,
) -> None:
    with pytest.raises(JDParserError) as error:
        await JDParser(FakeModelClient(output=output)).parse(document())

    assert error.value.code == code


@pytest.mark.asyncio
async def test_parser_preserves_model_timeout_as_retryable_error() -> None:
    client = FakeModelClient(error=ModelTimeoutError("timeout"))

    with pytest.raises(JDParserError) as error:
        await JDParser(client).parse(document())

    assert error.value.code == "model_timeout"


@pytest.mark.asyncio
async def test_parser_translates_unexpected_model_exception() -> None:
    client = FakeModelClient(error=RuntimeError("model crashed"))

    with pytest.raises(JDParserError) as error:
        await JDParser(client).parse(document())

    assert error.value.code == "model_error"


@pytest.mark.asyncio
async def test_parser_prefers_campus_for_explicit_campus_recruiting() -> None:
    text = "示例公司招聘 2027 届后端开发工程师，校招全职，工作地点上海。"
    output = {
        "company": "示例公司",
        "title": "后端开发工程师",
        "job_type": "full_time",
        "recruitment_batch": "校招",
        "locations": ["上海"],
        "field_evidence": [
            {"field_path": "company", "source_text": "示例公司"},
            {"field_path": "title", "source_text": "后端开发工程师"},
            {"field_path": "job_type", "source_text": "校招全职"},
            {"field_path": "recruitment_batch", "source_text": "校招"},
            {"field_path": "locations", "source_text": "上海"},
        ],
    }

    result = await JDParser(FakeModelClient(output=output)).parse(
        RawJobDocument(raw_content=text)
    )

    assert result.structured_jd.job_type == "campus"


@pytest.mark.asyncio
async def test_parser_accepts_nested_qualification_evidence() -> None:
    text = "示例公司招聘后端开发工程师，要求 2027 届毕业生，工作地点上海。"
    output = {
        "title": "后端开发工程师",
        "qualification_conditions": [
            {
                "field": "graduation_year",
                "operator": "in",
                "value": [2027],
                "source_text": "2027 届毕业生",
                "evidence": [
                    {
                        "field_path": "qualification_conditions[0]",
                        "source_text": "2027 届毕业生",
                    }
                ],
            }
        ],
        "field_evidence": [
            {"field_path": "title", "source_text": "后端开发工程师"},
        ],
    }

    result = await JDParser(FakeModelClient(output=output)).parse(
        RawJobDocument(raw_content=text)
    )

    assert result.structured_jd.qualification_conditions is not None


@pytest.mark.asyncio
async def test_openai_compatible_client_parses_json_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(
            200,
            json={
                "id": "resp_1",
                "model": "test-model",
                "choices": [{"message": {"content": '{"field_evidence": []}'}}],
            },
        )

    client = OpenAICompatibleModelClient(
        base_url="https://model.example/v1",
        api_key="test-key",
        model="test-model",
        transport=httpx.MockTransport(handler),
    )
    request = StructuredModelRequest(
        schema_name="job_description",
        json_schema={"type": "object"},
        messages=[{"role": "user", "content": "parse"}],
        prompt_version="test-v1",
    )

    response = await client.generate(request)

    assert response.output == {"field_evidence": []}
    assert response.response_id == "resp_1"


@pytest.mark.asyncio
async def test_openai_compatible_client_supports_json_object_mode() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["response_format"] == {"type": "json_object"}
        return httpx.Response(
            200,
            json={
                "model": "deepseek-v4-flash",
                "choices": [
                    {"message": {"content": "```json\n{\"field_evidence\": []}\n```"}}
                ],
            },
        )

    client = OpenAICompatibleModelClient(
        base_url="https://api.deepseek.com",
        api_key="test-key",
        model="deepseek-v4-flash",
        response_format="json_object",
        transport=httpx.MockTransport(handler),
    )
    request = StructuredModelRequest(
        schema_name="job_description",
        json_schema={"type": "object"},
        messages=[{"role": "user", "content": "parse"}],
        prompt_version="test-v2",
    )

    response = await client.generate(request)

    assert response.output == {"field_evidence": []}


def test_factory_auto_selects_json_object_for_deepseek() -> None:
    settings = Settings(
        structured_model_provider="openai_compatible",
        llm_base_url="https://api.deepseek.com",
        llm_api_key="test-key",
        llm_model="deepseek-v4-flash",
    )

    client = create_structured_model_client(settings)

    assert isinstance(client, OpenAICompatibleModelClient)
    assert client._response_format == "json_object"


@pytest.mark.asyncio
async def test_openai_compatible_client_rejects_missing_model_content() -> None:
    client = OpenAICompatibleModelClient(
        base_url="https://model.example/v1",
        api_key=None,
        model="test-model",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"choices": []})
        ),
    )
    request = StructuredModelRequest(
        schema_name="job_description",
        json_schema={"type": "object"},
        messages=[{"role": "user", "content": "parse"}],
        prompt_version="test-v1",
    )

    with pytest.raises(ModelResponseError):
        await client.generate(request)
