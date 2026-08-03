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
