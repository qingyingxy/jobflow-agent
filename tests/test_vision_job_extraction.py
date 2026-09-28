import json

import httpx
import pytest
from sqlalchemy import select

from src.config import Settings
from src.domain.discovery import LeadProvider, LeadVerification
from src.domain.job import JobPosting
from src.services.browser_job_reader import BrowserPageSnapshot
from src.services.job_lead_service import JobLeadService, LeadVerificationFailure
from src.services.vision_job_extraction import extract_visual_job, needs_visual_fallback


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,status", [("job", "extracted"), ("listing", "inconclusive"), ("login", "inconclusive")])
async def test_vision_payload_and_page_classification(kind, status):
    def handler(request):
        body = json.loads(request.content)
        assert body["messages"][0]["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({"page_kind": kind, "title": "Agent工程师", "raw_content": "工作职责：负责智能体开发与评测。任职要求：掌握Python，熟悉模型调用、数据库和服务部署。"})}}]})
    result = await extract_visual_job([{"base64": "abc"}], settings=Settings(llm_api_key="test", llm_base_url="https://example.com/v1/responses"), transport=httpx.MockTransport(handler))
    assert result["status"] == status


@pytest.mark.asyncio
async def test_unsupported_model_is_recorded_without_credentials():
    result = await extract_visual_job([{"base64": "abc"}], settings=Settings(llm_api_key="secret"), transport=httpx.MockTransport(lambda r: httpx.Response(400, text="secret")))
    assert result["status"] == "failed"
    assert "secret" not in json.dumps(result)


def test_image_only_requires_fallback():
    assert needs_visual_fallback('<body><img src="poster.jpg"></body>', "https://example.com/job/1")


def test_readable_jd_does_not_require_vision():
    html = '<h1>智能体工程师</h1><p>岗位职责：' + '负责Python开发与模型评测。' * 12 + '</p><p>任职要求：熟悉数据库。</p>'
    assert not needs_visual_fallback(html, "https://example.com/job/1")


@pytest.mark.asyncio
async def test_disabled_vision_never_calls_provider():
    def unexpected(request):
        raise AssertionError("disabled fallback must not call provider")
    result = await extract_visual_job([{"base64": "abc"}], settings=Settings(vision_fallback_enabled=False), transport=httpx.MockTransport(unexpected))
    assert result["status"] == "unavailable"


@pytest.mark.asyncio
async def test_visual_preview_preserves_snapshot_without_promoting_job(db_session, monkeypatch):
    from src.services import vision_job_extraction

    async def extract(images, **kwargs):
        assert images[0]["base64"] == "evidence"
        return {"status": "extracted", "fields": {"title": "智能体工程师", "raw_content": "截图岗位正文", "locations": ["上海"]}}

    monkeypatch.setattr(vision_job_extraction, "extract_visual_job", extract)
    url = "https://example.com/job/1"
    class Reader:
        async def read(self, url):
            return BrowserPageSnapshot(url, url, "招聘", "<body><img></body>", "", screenshots=({"base64": "evidence"},))

    service = JobLeadService(db_session)
    lead = service.create_lead(user_id="visual-user", provider=LeadProvider.MANUAL_URL, source_url=url, search_snippet="原始摘要")
    with pytest.raises(LeadVerificationFailure, match="截图"):
        await service.verify_browser(user_id="visual-user", lead_id=lead.id, reader=Reader(), official_hosts={"example.com"})
    db_session.refresh(lead)
    assert lead.extracted_fields["basis"] == "screenshot"
    assert lead.extracted_fields["verified"] is False
    assert lead.search_snippet == "原始摘要"
    assert db_session.scalar(select(JobPosting)) is None
    saved = db_session.scalar(select(LeadVerification).where(LeadVerification.result == "SNAPSHOT"))
    assert saved.field_evidence["screenshots"][0]["base64"] == "evidence"
    assert saved.field_evidence["raw_html"] == "<body><img></body>"
