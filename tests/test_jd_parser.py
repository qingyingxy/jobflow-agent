from __future__ import annotations

import hashlib
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
    StructuredModelResponse,
    create_structured_model_client,
)
from src.services.jd_parser import JDParser, JDParserError

JOB_TEXT = "示例公司招聘 AI 应用开发实习生，熟悉 RAG，工作地点为北京。"


class SequenceModelClient:
    model_name = "sequence-model"

    def __init__(self, outputs: list[dict[str, object]]) -> None:
        self.outputs = outputs
        self.requests: list[StructuredModelRequest] = []

    async def generate(self, request: StructuredModelRequest) -> StructuredModelResponse:
        self.requests.append(request)
        return StructuredModelResponse(
            output=self.outputs.pop(0),
            model=self.model_name,
            provider="test",
        )


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
    assert client.last_request.prompt_version == "jd-parser-prompt-v4"
    assert "输出对象字段契约" in client.last_request.messages[0].content
    assert "岗位文本" in client.last_request.messages[1].content


@pytest.mark.asyncio
async def test_parser_normalizes_grouped_skill_requirements() -> None:
    text = "示例公司招聘 Agent 实习生，要求熟悉 RAG、Agent、Prompt Engineering。"
    output = {
        "title": "Agent 实习生",
        "required_skills": ["RAG、Agent、Prompt Engineering"],
        "requirements": [
            {
                "category": "required_skill",
                "name": "RAG、Agent、Prompt Engineering",
                "description": "要求熟悉 RAG、Agent、Prompt Engineering",
                "mandatory": True,
                "evidence": [
                    {
                        "field_path": "requirements[0]",
                        "source_text": "要求熟悉 RAG、Agent、Prompt Engineering",
                    }
                ],
            }
        ],
        "field_evidence": [
            {"field_path": "title", "source_text": "Agent 实习生"},
            {
                "field_path": "required_skills",
                "source_text": "要求熟悉 RAG、Agent、Prompt Engineering",
            },
        ],
    }

    result = await JDParser(FakeModelClient(output=output)).parse(
        RawJobDocument(raw_content=text)
    )

    assert result.structured_jd.required_skills == [
        "RAG",
        "Agent",
        "Prompt Engineering",
    ]
    assert [
        requirement.name for requirement in result.structured_jd.requirements or []
    ] == ["RAG", "Agent", "Prompt Engineering"]


@pytest.mark.asyncio
async def test_parser_retries_after_structured_validation_failure() -> None:
    client = SequenceModelClient(
        [
            {"title": "示例岗位", "field_evidence": []},
            valid_output(),
        ]
    )

    result = await JDParser(client).parse(document())

    assert result.structured_jd.required_skills == ["RAG"]
    assert len(client.requests) == 2
    assert "上一轮 JSON 已返回" in client.requests[1].messages[-1].content


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
        payload = json.loads(request.content)
        assert payload["reasoning_effort"] == "medium"
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
        reasoning_effort="medium",
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
        assert payload["max_tokens"] == 2048
        assert payload["thinking"] == {"type": "disabled"}
        return httpx.Response(
            200,
            json={
                "id": "resp_diagnostics",
                "model": "deepseek-v4-flash",
                "usage": {
                    "prompt_tokens": 101,
                    "completion_tokens": 23,
                    "completion_tokens_details": {"reasoning_tokens": 0},
                },
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": "```json\n{\"field_evidence\": []}\n```",
                            "reasoning_content": "",
                        },
                    }
                ],
            },
        )

    client = OpenAICompatibleModelClient(
        base_url="https://api.deepseek.com",
        api_key="test-key",
        model="deepseek-v4-flash",
        response_format="json_object",
        thinking_mode="disabled",
        transport=httpx.MockTransport(handler),
    )
    request = StructuredModelRequest(
        schema_name="job_description",
        json_schema={"type": "object"},
        messages=[{"role": "user", "content": "parse"}],
        prompt_version="test-v2",
        max_output_tokens=2048,
    )

    response = await client.generate(request)

    assert response.output == {"field_evidence": []}
    assert response.diagnostics == {
        "response_id": "resp_diagnostics",
        "finish_reason": "stop",
        "prompt_tokens": 101,
        "completion_tokens": 23,
        "reasoning_tokens": 0,
        "reasoning_content_present": True,
        "reasoning_content_length": 0,
        "max_tokens": 2048,
        "thinking_mode": "disabled",
        "content_length": len("```json\n{\"field_evidence\": []}\n```"),
        "content_sha256": hashlib.sha256(
            b"```json\n{\"field_evidence\": []}\n```"
        ).hexdigest(),
    }


@pytest.mark.asyncio
async def test_openai_compatible_client_reports_http_read_timeout_stage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow response", request=request)

    client = OpenAICompatibleModelClient(
        base_url="https://api.deepseek.com",
        api_key="test-key",
        model="deepseek-v4-flash",
        response_format="json_object",
        timeout_seconds=7,
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )
    request = StructuredModelRequest(
        schema_name="job_description",
        json_schema={"type": "object"},
        messages=[{"role": "user", "content": "parse"}],
        prompt_version="test-timeout-v1",
    )

    with pytest.raises(ModelTimeoutError) as captured:
        await client.generate(request)

    assert captured.value.details["timeout_scope"] == "http_request"
    assert captured.value.details["timeout_stage"] == "read"
    assert captured.value.details["timeout_seconds"] == 7
    assert captured.value.details["request_duration_ms"] >= 0


@pytest.mark.asyncio
async def test_openai_compatible_client_reports_truncated_json_without_content() -> None:
    truncated_content = '{"field_evidence": ['

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "resp_truncated",
                "model": "deepseek-v4-flash",
                "choices": [
                    {
                        "finish_reason": "length",
                        "message": {"content": truncated_content},
                    }
                ],
            },
        )

    client = OpenAICompatibleModelClient(
        base_url="https://api.deepseek.com",
        api_key="test-key",
        model="deepseek-v4-flash",
        response_format="json_object",
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )
    request = StructuredModelRequest(
        schema_name="job_description",
        json_schema={"type": "object"},
        messages=[{"role": "user", "content": "parse JSON"}],
        prompt_version="test-v3",
    )

    with pytest.raises(ModelResponseError) as captured:
        await client.generate(request)

    assert captured.value.details == {
        "response_id": "resp_truncated",
        "finish_reason": "length",
        "prompt_tokens": None,
        "completion_tokens": None,
        "reasoning_tokens": None,
        "reasoning_content_present": False,
        "reasoning_content_length": 0,
        "max_tokens": None,
        "thinking_mode": "provider_default",
        "content_length": len(truncated_content),
        "content_sha256": hashlib.sha256(
            truncated_content.encode("utf-8")
        ).hexdigest(),
    }
    assert truncated_content not in str(captured.value.details)


@pytest.mark.asyncio
async def test_client_reports_reasoning_budget_without_storing_reasoning_text() -> None:
    reasoning_content = "private model reasoning"

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["thinking"] == {"type": "disabled"}
        assert payload["max_tokens"] == 4096
        return httpx.Response(
            200,
            json={
                "id": "resp_reasoning_limit",
                "usage": {
                    "prompt_tokens": 512,
                    "completion_tokens": 4096,
                    "completion_tokens_details": {"reasoning_tokens": 4096},
                },
                "choices": [
                    {
                        "finish_reason": "length",
                        "message": {
                            "content": "",
                            "reasoning_content": reasoning_content,
                        },
                    }
                ],
            },
        )

    client = OpenAICompatibleModelClient(
        base_url="https://api.deepseek.com",
        api_key="test-key",
        model="deepseek-v4-flash",
        response_format="json_object",
        thinking_mode="disabled",
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )
    request = StructuredModelRequest(
        schema_name="job_description",
        json_schema={"type": "object"},
        messages=[{"role": "user", "content": "parse JSON"}],
        prompt_version="test-v4",
        max_output_tokens=4096,
    )

    with pytest.raises(ModelResponseError) as captured:
        await client.generate(request)

    assert captured.value.details == {
        "response_id": "resp_reasoning_limit",
        "finish_reason": "length",
        "prompt_tokens": 512,
        "completion_tokens": 4096,
        "reasoning_tokens": 4096,
        "reasoning_content_present": True,
        "reasoning_content_length": len(reasoning_content),
        "max_tokens": 4096,
        "thinking_mode": "disabled",
        "content_length": 0,
        "content_sha256": hashlib.sha256(b"").hexdigest(),
    }
    assert reasoning_content not in str(captured.value.details)


@pytest.mark.asyncio
async def test_openai_compatible_client_retries_transient_http_failures() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(503, json={"error": "temporarily unavailable"})
        return httpx.Response(
            200,
            json={
                "model": "test-model",
                "choices": [{"message": {"content": '{"field_evidence": []}'}}],
            },
        )

    client = OpenAICompatibleModelClient(
        base_url="https://model.example/v1",
        api_key="test-key",
        model="test-model",
        max_retries=2,
        retry_backoff_seconds=0,
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
    assert attempts == 3


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
    assert client._thinking_mode == "disabled"


def test_factory_omits_auto_thinking_for_other_compatible_providers() -> None:
    settings = Settings(
        structured_model_provider="openai_compatible",
        llm_base_url="https://model.example/v1",
        llm_api_key="test-key",
        llm_model="test-model",
        llm_response_format="auto",
        llm_reasoning_effort="medium",
    )

    client = create_structured_model_client(settings)

    assert isinstance(client, OpenAICompatibleModelClient)
    assert client._thinking_mode is None
    assert client.reasoning_effort == "medium"
    assert client.response_format == "json_schema"


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
