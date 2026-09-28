import json

import httpx
import pytest

from src.services.responses_search import ResponsesSearchProvider
from src.services.web_search_service import WebSearchPayloadError


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
