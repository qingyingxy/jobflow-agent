from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from src.domain.discovery import LeadProvider
from src.main import app
from src.services.job_lead_service import JobLeadService
from src.services.url_reader import FetchedResponse
from src.services.web_search_service import (
    BingRSSSearchProvider,
    TavilySearchProvider,
    parse_bing_rss,
)


class FakeReader:
    timeout_seconds = 8

    def __init__(self, body: bytes, *, content_type: str = "text/html") -> None:
        self.body = body
        self.content_type = content_type
        self.requested_urls: list[str] = []

    async def fetch(self, url: str) -> FetchedResponse:
        self.requested_urls.append(url)
        return FetchedResponse(
            requested_url=url,
            final_url=url,
            status_code=200,
            content_type=self.content_type,
            body=self.body,
        )


class FakeTavilyReader(FakeReader):
    def __init__(self, payload: dict[str, object]) -> None:
        super().__init__(b"{}", content_type="application/json")
        self.payload = payload
        self.posted_payload: object | None = None

    async def post_json(
        self,
        url: str,
        payload: object,
        *,
        headers: dict[str, str] | None = None,
    ) -> tuple[FetchedResponse, object]:
        self.requested_urls.append(url)
        self.posted_payload = payload
        return (
            FetchedResponse(
                requested_url=url,
                final_url=url,
                status_code=200,
                content_type=self.content_type,
                body=self.body,
            ),
            self.payload,
        )


def _rss(*items: tuple[str, str, str]) -> bytes:
    rows = "".join(
        f"<item><title>{title}</title><link>{url}</link>"
        f"<description>{description}</description></item>"
        for title, url, description in items
    )
    return f"<?xml version='1.0'?><rss><channel>{rows}</channel></rss>".encode()


@pytest.mark.asyncio
async def test_bing_rss_search_returns_deduplicated_untrusted_leads() -> None:
    reader = FakeReader(
        _rss(
            (
                "AI Agent 工程师",
                "https://careers.example.com/jobs/123#overview",
                "&lt;b&gt;搜索摘要&lt;/b&gt;，只作为提示。",
            ),
            (
                "重复结果",
                "https://careers.example.com/jobs/123",
                "重复摘要",
            ),
            ("无效结果", "javascript:alert(1)", "不应保留"),
        ),
        content_type="text/xml",
    )
    provider = BingRSSSearchProvider(
        query="上海 AI Agent 校招",
        company_names=["示例科技"],
        reader=reader,  # type: ignore[arg-type]
    )

    candidates = await provider.discover()

    assert len(candidates) == 1
    assert candidates[0].provider is LeadProvider.EXTERNAL_AGENT
    assert candidates[0].source_url == "https://careers.example.com/jobs/123"
    assert candidates[0].search_snippet == "搜索摘要，只作为提示。"
    assert candidates[0].verification_stub is None
    query = parse_qs(urlsplit(reader.requested_urls[0]).query)["q"][0]
    assert "上海 AI Agent 校招" in query
    assert '"示例科技"' in query


@pytest.mark.asyncio
async def test_tavily_search_api_returns_only_untrusted_job_leads() -> None:
    reader = FakeTavilyReader(
        {
            "results": [
                {
                    "title": "大模型算法工程师 - 校园招聘",
                    "url": "https://jobs.example.com/position/88",
                    "content": "岗位职责与任职要求摘要",
                },
                {
                    "title": "公司新闻",
                    "url": "https://example.com/news/1",
                    "content": "一条普通的公司动态新闻",
                },
            ]
        }
    )
    provider = TavilySearchProvider(
        query="上海大模型校招",
        api_key="test-key",
        reader=reader,  # type: ignore[arg-type]
    )

    candidates = await provider.discover()

    assert len(candidates) == 1
    assert candidates[0].provider is LeadProvider.EXTERNAL_AGENT
    assert candidates[0].source_id == "web-search:tavily"
    assert candidates[0].verification_stub is None
    assert isinstance(reader.posted_payload, dict)
    assert reader.posted_payload["include_raw_content"] is False


@pytest.mark.asyncio
async def test_web_search_hint_never_becomes_verified_job_fact(db_session) -> None:
    [candidate] = parse_bing_rss(
        _rss(
            (
                "错误的搜索标题",
                "https://careers.example.com/jobs/verified-1",
                "错误的搜索摘要，不得写入正式岗位正文。",
            )
        )
    )
    lead = JobLeadService(db_session).capture_candidate(
        user_id="web-search-user",
        candidate=candidate,
    )
    page = (
        "<html><head><title>页面标题</title></head><body>"
        "<h1>大模型应用工程师</h1>"
        "<p>岗位职责：负责大模型应用和智能体产品研发、评测与上线。</p>"
        "<p>任职要求：熟悉 Python、机器学习和常用工程工具，有良好沟通能力；"
        "能够独立完成需求分析、系统设计、实验验证、服务部署和效果复盘。</p>"
        "</body></html>"
    ).encode()

    result = await JobLeadService(db_session).verify_url(
        user_id="web-search-user",
        lead_id=lead.id,
        reader=FakeReader(page),  # type: ignore[arg-type]
        official_hosts=set(),
    )

    assert result.posting.title == "大模型应用工程师"
    assert "错误的搜索摘要" not in result.posting.raw_content
    assert result.lead.title_hint == "错误的搜索标题"


@pytest.mark.asyncio
async def test_web_search_api_starts_agent_without_company_selection(
    monkeypatch,
) -> None:
    observed: dict[str, object] = {}
    provider = BingRSSSearchProvider(
        query="AI Agent 校招",
        reader=FakeReader(_rss(), content_type="text/xml"),  # type: ignore[arg-type]
    )

    def fake_create_provider(
        query: str,
        company_ids: list[str] | None = None,
    ) -> BingRSSSearchProvider:
        observed.update(query=query, provider_company_ids=company_ids)
        return provider

    def fake_worker(
        *,
        run_id: str,
        user_id: str,
        query: str,
        company_ids: list[str] | None = None,
    ) -> None:
        observed.update(
            run_id=run_id,
            user_id=user_id,
            worker_query=query,
            worker_company_ids=company_ids,
        )

    monkeypatch.setattr(
        "src.api.discovery.create_web_search_provider",
        fake_create_provider,
    )
    monkeypatch.setattr(
        "src.api.discovery.execute_web_search_in_worker",
        fake_worker,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/discovery/search",
            headers={"X-User-ID": "web-search-user"},
            json={
                "query": "AI Agent 校招",
                "source_mode": "web",
                "company_ids": None,
            },
        )

    assert response.status_code == 202
    body = response.json()
    assert body["source"] == "web-search-agent:v1"
    assert body["search_plan"]["routes"][1]["tool_sequence"] == [
        "web_search",
        "static_job_page_validator",
    ]
    assert observed["provider_company_ids"] is None
    assert observed["worker_company_ids"] is None
    assert observed["worker_query"] == "AI Agent 校招"
