import json

import httpx
import pytest

from src.services.responses_search import ResponsesSearchProvider
from src.services.web_search_service import WebSearchPayloadError


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["supported", "unsupported", "ignored"])
async def test_company_search_tool_budget_is_sent_and_actual_support_is_reported(mode):
    calls = []

    def handle(request):
        body = json.loads(request.content)
        calls.append(body)
        if mode == "unsupported" and "max_tool_calls" in body:
            return httpx.Response(400, text="unsupported parameter: max_tool_calls")
        return httpx.Response(200, json={"status": "completed", "output": [
            {"type": "web_search_call", "status": "completed", "action": {"query": "one", "sources": []}}
            for _ in range(2 if mode == "ignored" else 1)]})

    provider = ResponsesSearchProvider(query="agent 公司官网", base_url="https://api.example.com/v1",
        api_key="test", model="test", transport=httpx.MockTransport(handle))
    provider.search_purpose = "companies"
    provider.max_tool_calls = 1
    await provider.discover()
    assert calls[0]["max_tool_calls"] == 1
    assert provider.last_evidence["tool_limit_status"] == {
        "supported": "within_limit", "unsupported": "unsupported", "ignored": "exceeded"}[mode]
    if mode == "unsupported":
        assert len(calls) == 2 and "max_tool_calls" not in calls[1]


@pytest.mark.asyncio
async def test_search_links_remain_untrusted_and_are_deduplicated():
    def handle(request):
        body = json.loads(request.content)
        assert request.url.path == "/v1/responses"
        assert body["tools"] == [{"type": "web_search"}]
        assert body["tool_choice"] == "required"
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {"type": "web_search_call", "status": "completed"},
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "https://jobs.example.com/123#details",
                                "annotations": [
                                    {
                                        "type": "url_citation",
                                        "url": "https://jobs.example.com/123",
                                        "title": "AI 工程师",
                                    },
                        {
                            "type": "url_citation",
                            "url": "javascript:alert(1)",
                        },
                        {
                            "type": "url_citation",
                            "url": "https://news.example.com/article/1",
                        },
                                ],
                            }
                        ],
                    },
                ],
            },
        )

    provider = ResponsesSearchProvider(
        query="国内校招",
        base_url="https://api.example.com/v1/chat/completions",
        api_key="test",
        model="test",
        transport=httpx.MockTransport(handle),
        allowed_hosts={"jobs.example.com"},
    )
    leads = await provider.discover()
    plan = provider.build_search_plan()
    assert plan.allowed_source_ids == [provider.source_id]
    assert plan.budget.request_timeout_seconds == 120
    assert len(leads) == 1
    assert leads[0].source_url == "https://jobs.example.com/123"
    assert leads[0].verification_stub is None
    assert leads[0].source_id == "web-search:responses"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {"status": "completed", "output": []},
        {"status": "incomplete", "output": []},
        {
            "status": "completed",
            "output": [{"type": "web_search_call", "status": "failed"}],
        },
    ],
)
async def test_unexecuted_search_cannot_return_model_guessed_links(body):
    provider = ResponsesSearchProvider(
        query="校招",
        base_url="https://api.example.com/v1",
        api_key="test",
        model="test",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body)),
    )
    with pytest.raises(WebSearchPayloadError):
        await provider.discover()
