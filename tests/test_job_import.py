from hashlib import sha256

import httpx
import pytest
from pydantic import ValidationError

from src.domain.job import StructuredJobDescription
from src.main import app


@pytest.mark.asyncio
async def test_job_text_import_persists_raw_content_and_hash() -> None:
    raw_text = "\r\n  AI 应用开发实习生\r\n负责 RAG 应用开发和评测。\r\n"
    normalized_text = raw_text.replace("\r\n", "\n").strip()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/jobs/import-text",
            json={
                "source_url": "https://example.com/jobs/123",
                "company": "示例公司",
                "title": "AI 应用开发实习生",
                "raw_content": raw_text,
            },
        )
        read_response = await client.get(f"/api/jobs/{response.json()['id']}")

    assert response.status_code == 201
    assert response.json()["raw_content"] == normalized_text
    assert response.json()["content_hash"] == sha256(
        normalized_text.encode("utf-8")
    ).hexdigest()
    assert response.json()["source_type"] == "manual_text"
    assert read_response.status_code == 200
    assert read_response.json()["trace_id"].startswith("trace_")


def test_structured_jd_schema_keeps_missing_fields_as_null() -> None:
    structured = StructuredJobDescription(
        company="示例公司",
        title="AI 应用开发实习生",
    )

    assert structured.company == "示例公司"
    assert structured.job_type is None
    assert structured.locations is None
    assert structured.required_skills is None
    assert structured.qualification_conditions is None


def test_structured_jd_schema_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        StructuredJobDescription(unexpected_field="不应该出现")


@pytest.mark.asyncio
async def test_job_text_import_rejects_short_text_after_normalization() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/jobs/import-text",
            json={"raw_content": "\n\r\n  太短  \n"},
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


@pytest.mark.asyncio
async def test_manual_import_rejects_non_manual_source_type() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/jobs/import-text",
            json={
                "source_type": "company_adapter",
                "raw_content": "这是一个长度足够的岗位文本，用于测试来源边界。",
            },
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_parse_endpoint_persists_a_job_result_in_fake_mode() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        import_response = await client.post(
            "/api/jobs/import-text",
            json={
                "company": "示例公司",
                "title": "AI 应用开发实习生",
                "raw_content": "示例公司招聘 AI 应用开发实习生，熟悉 RAG。",
            },
        )
        job_id = import_response.json()["id"]
        parse_response = await client.post(f"/api/jobs/{job_id}/parse")

    assert import_response.status_code == 201
    assert parse_response.status_code == 200
    body = parse_response.json()
    assert body["job_id"] == job_id
    assert body["parse_result_id"].startswith("parse_")
    assert body["agent_run_id"].startswith("run_")
    assert body["structured_jd"]["company"] == "示例公司"
    assert body["structured_jd"]["required_skills"] == ["RAG"]
