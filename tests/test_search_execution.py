import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from src.domain.discovery import DiscoveryRun, LeadProvider, SearchEvidence
from src.main import app
from src.services.job_lead_service import JobLeadService, normalize_lead_url
from src.services.lead_providers import LeadCandidate
from src.services.multiround_search import canonical_search_url
from src.services.recruitment_entry import expand_entry
from src.services.responses_search import ResponsesSearchProvider
from src.services.search_pipeline import run_search_pipeline
from src.services.search_planner import build_search_tasks, next_search_task
from src.services.url_reader import FetchedResponse, extract_html_links


def candidate(number):
    return LeadCandidate(
        provider=LeadProvider.EXTERNAL_AGENT,
        source_url=f"https://example.com/jobs/{number}",
        discovered_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_slow_verification_does_not_block_next_query_and_details_are_drained():
    second_search = asyncio.Event()
    verified = []

    async def search(number, seen):
        if number == 2:
            second_search.set()
        return [candidate(1), candidate(number)]

    async def verify(lead):
        await asyncio.wait_for(second_search.wait(), 0.5)
        verified.append(lead.source_url)
        if lead.source_url.endswith("/1"):
            return [candidate(3)]
        return lead.source_url, True

    await run_search_pipeline(
        search=search,
        verify=verify,
        report=lambda *args: None,
        canonicalize=canonical_search_url,
        max_rounds=2,
        verification_seconds=1,
    )
    assert verified == [candidate(i).source_url for i in (1, 2, 3)]


@pytest.mark.asyncio
async def test_timeout_isolated_and_cancelled_worker_does_not_leak():
    cancelled = asyncio.Event()
    events = []

    async def search(number, seen):
        return [candidate(1), candidate(2)]

    async def verify(lead):
        if lead.source_url.endswith("/1"):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        return lead.source_url, True

    await run_search_pipeline(
        search=search,
        verify=verify,
        report=lambda *args: None,
        canonicalize=canonical_search_url,
        max_rounds=1,
        item_seconds=0.02,
        verification_seconds=1,
        on_event=lambda kind, details: events.append(details),
    )
    assert cancelled.is_set()
    assert events[0]["error_code"] == "verification_timeout"
    assert events[1]["url"].endswith("/2")


@pytest.mark.asyncio
async def test_finish_drains_pending_verification_and_snapshot_counts_inflight_work():
    finishing = asyncio.Event()
    snapshots = []
    verified = []

    async def search(number, seen):
        if number == 1:
            return [candidate(1)]
        assert snapshots[-1].pending_verification == 1
        assert snapshots[-1].verified_jobs == 0
        finishing.set()
        return None

    async def verify(lead):
        await finishing.wait()
        verified.append(lead.source_url)
        return lead.source_url, True

    stop = await run_search_pipeline(
        search=search, verify=verify, report=lambda *args: None,
        canonicalize=canonical_search_url, on_snapshot=snapshots.append,
        get_stop_reason=lambda: "agent finished", verification_seconds=1,
    )
    assert stop == "agent finished"
    assert verified == [candidate(1).source_url]
    assert snapshots[-1].pending_verification == 0
    assert snapshots[-1].verified_jobs == snapshots[-1].useful_jobs == 1


@pytest.mark.asyncio
async def test_feedback_wait_stops_before_decision_when_verification_reaches_target():
    calls = []

    async def search(number, seen):
        calls.append(number)
        return [candidate(1)]

    async def verify(lead):
        return lead.source_url, True

    stop = await run_search_pipeline(
        search=search, verify=verify, report=lambda *args: None,
        canonicalize=canonical_search_url, target=1, feedback_wait_seconds=0.1,
    )
    assert calls == [1]
    assert stop == "达到有效岗位目标"


@pytest.mark.asyncio
async def test_decision_time_is_included_in_search_deadline_and_cancelled():
    cancelled = asyncio.Event()

    async def search(number, seen):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    async def verify(lead):
        raise AssertionError("no provider was executed")

    stop = await run_search_pipeline(
        search=search, verify=verify, report=lambda *args: None,
        canonicalize=canonical_search_url, seconds=0.02,
    )
    assert stop == "达到搜索时间预算"
    assert cancelled.is_set()


def test_queries_are_distinct_and_preserve_non_ai_intent():
    sources = [
        SimpleNamespace(company="示例公司", career_url="https://example.com/careers")
    ]
    tasks = build_search_tasks("2027校招 前端 后端 北京 上海", sources)
    assert any("前端 北京" in t.query and "后端" not in t.query for t in tasks)
    assert any("后端 上海" in t.query and "前端" not in t.query for t in tasks)
    assert all("2027" in t.query and "校招" in t.query for t in tasks)
    assert all("Agent" not in t.query for t in tasks)
    assert next_search_task(tasks, {tasks[0].query}, 1).strategy == "公司官网"


@pytest.mark.asyncio
async def test_incomplete_response_keeps_sources_and_full_snippet():
    text = "[研发工程师](https://example.com/jobs/1) " + "详细要求" * 900
    payload = {
        "status": "incomplete",
        "output": [
            {
                "type": "web_search_call",
                "status": "completed",
                "action": {
                    "type": "search",
                    "queries": ["研发 校招 上海"],
                    "sources": [
                        {"url": "https://example.com/jobs/2", "title": "其他职位"}
                    ],
                },
            },
            {"type": "message", "content": [{"type": "output_text", "text": text}]},
        ],
    }
    provider = ResponsesSearchProvider(
        query="校招",
        base_url="https://api.example/v1",
        api_key="test",
        model="test",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
    )
    results = await provider.discover()
    assert len(results) == 2
    assert results[0].search_snippet == text
    assert provider.last_evidence["actual_queries"] == ["研发 校招 上海"]
    assert provider.last_evidence["partial"] is True
    assert json.loads(provider.last_evidence["raw_response"]) == payload


@pytest.mark.asyncio
async def test_official_entry_follows_only_observed_ats_tenant_and_pagination():
    pages = {
        "https://example.com/careers": '<a href="https://app.mokahr.com/social-recruitment/acme/1">社会招聘</a>',
        "https://app.mokahr.com/social-recruitment/acme/1": '<a href="https://app.mokahr.com/social-recruitment/acme/1#/job/1">研发工程师</a><a href="https://app.mokahr.com/social-recruitment/other/2#/job/2">其他企业工程师</a><a href="?page=2">下一页</a>',
        "https://app.mokahr.com/social-recruitment/acme/1?page=2": '<a href="https://app.mokahr.com/social-recruitment/acme/1#/job/3">后端工程师</a>',
    }

    async def fetch(url):
        return FetchedResponse(url, url, 200, "text/html", pages[url].encode())

    from src.services.browser_job_reader import BrowserReadError

    async def read(url):
        raise BrowserReadError("unavailable")

    evidence = []
    results = await expand_entry(
        "https://example.com/careers",
        reader=SimpleNamespace(fetch=fetch),
        browser=SimpleNamespace(read=read),
        allowed_hosts={"example.com"},
        official_hosts={"example.com"},
        record_snapshot=lambda *args: None,
        on_event=lambda kind, d: evidence.append((kind, d)),
    )
    assert {r.url.split("#/job/")[-1] for r in results} == {"1", "3"}
    assert any(kind == "official_link" for kind, _ in evidence)


def test_spa_routes_survive_all_link_boundaries():
    url = "https://example.com/careers#/job/123"
    assert normalize_lead_url(url) == canonical_search_url(url) == url
    assert (
        extract_html_links(
            '<a href="#/job/123">工程师</a>', base_url="https://example.com/careers"
        )[0].url
        == url
    )


def test_search_evidence_is_owned_and_long_snippets_are_not_truncated(db_session):
    run = DiscoveryRun(
        id="run-test",
        user_id="owner",
        source="test",
        source_url="https://example.com",
        started_at=datetime.now(UTC),
    )
    db_session.add(run)
    db_session.add(
        SearchEvidence(
            id="evidence-test",
            user_id="owner",
            discovery_run_id=run.id,
            query="校招",
            provider="test",
            status="PARTIAL",
            raw_response="full response",
            details={},
        )
    )
    db_session.commit()
    client = TestClient(app)
    url = f"/api/discovery/runs/{run.id}/search-evidence"
    assert (
        client.get(url, headers={"X-User-ID": "owner"}).json()[0]["raw_response"]
        == "full response"
    )
    assert client.get(url, headers={"X-User-ID": "other"}).status_code == 404
    service = JobLeadService(db_session)
    lead = service.create_lead(
        user_id="owner",
        provider=LeadProvider.EXTERNAL_AGENT,
        source_url="https://example.com/jobs/1",
        search_snippet="完整信息" * 1000,
    )
    again = service.create_lead(
        user_id="owner",
        provider=LeadProvider.EXTERNAL_AGENT,
        source_url=lead.source_url,
        search_snippet="新增说明",
    )
    assert (
        "完整信息" * 1000 in again.search_snippet and "新增说明" in again.search_snippet
    )
    service.record_official_link(
        user_id="owner",
        lead_id=lead.id,
        source_url=lead.source_url,
        entry_url="https://official.example/careers",
        from_url="https://official.example/careers",
    )
    assert service._official_target(lead, lead.source_url, {"official.example"})
    assert not service._official_target(
        lead, "https://example.com/jobs/2", {"official.example"}
    )


@pytest.mark.asyncio
async def test_execution_persists_queries_and_page_failures_with_separate_sessions(
    db_session, monkeypatch
):
    from sqlalchemy import select
    from sqlalchemy.orm import sessionmaker

    from src.config import Settings
    from src.services import multiround_search as execution
    from src.services import web_search_service
    from src.services.job_lead_service import LeadVerificationFailure

    second_query = asyncio.Event()
    calls = []

    class Provider:
        source_id = "test-provider"

        async def discover(self):
            calls.append(self.query)
            self.last_evidence = {
                "raw_response": "original-response",
                "actual_queries": [self.query],
            }
            if len(calls) == 2:
                second_query.set()
            return [candidate(1)]

    def factory(query, company_ids):
        provider = Provider()
        provider.query = query
        return provider

    async def fail_verify(service, *, user_id, lead_id, **kwargs):
        await asyncio.wait_for(second_query.wait(), 0.5)
        lead = service.get_lead(user_id=user_id, lead_id=lead_id)
        lead.failure_code = "lead_not_job_page"
        lead.failure_reason = "页面暂时无法核验"
        lead.status = "NEEDS_USER"
        service.session.commit()
        raise LeadVerificationFailure(
            code=lead.failure_code, message=lead.failure_reason, lead_id=lead_id
        )

    settings = Settings(
        _env_file=None,
        web_search_max_rounds=2,
        web_search_budget_seconds=2,
        web_search_verification_budget_seconds=2,
    )
    monkeypatch.setattr(execution, "get_settings", lambda: settings)
    monkeypatch.setattr(execution, "SessionLocal", sessionmaker(bind=db_session.bind))
    monkeypatch.setattr(
        execution, "enabled_company_source_hosts", lambda **kwargs: {"example.com"}
    )
    monkeypatch.setattr(execution, "enabled_company_sources", lambda *args, **kwargs: [])
    monkeypatch.setattr(web_search_service, "create_web_search_provider", factory)
    monkeypatch.setattr(JobLeadService, "verify_url", fail_verify)
    run = DiscoveryRun(
        id="execution-test",
        user_id="owner",
        source="test",
        source_url="https://example.com",
        started_at=datetime.now(UTC),
    )
    db_session.add(run)
    db_session.commit()
    await execution.execute_multiround_search(
        run_id=run.id, user_id="owner", query="北京 后端 校招", company_ids=[]
    )
    db_session.expire_all()
    records = list(
        db_session.scalars(
            select(SearchEvidence).where(SearchEvidence.discovery_run_id == run.id)
        )
    )
    assert len(records) == 2 and len(set(calls)) == 2
    assert all(r.raw_response == "original-response" for r in records)
    assert sorted(r.details["new_links"] for r in records) == [0, 1]
    assert any(s.get("error_code") == "lead_not_job_page" for s in run.agent_trace)
    stages = [s["details"] for s in run.agent_trace if s["tool"] == "verification_stage"]
    assert any(
        s["stage"] == "http_verification" and s["duration_ms"] >= 0
        and s["error_code"] == "lead_not_job_page" for s in stages
    )


@pytest.mark.asyncio
async def test_include_compatibility_fallback_preserves_rejected_response():
    calls = []

    def respond(request):
        calls.append(json.loads(request.content))
        if "include" in calls[-1]:
            return httpx.Response(400, json={"error": "unsupported parameter include"})
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
                                "text": "[工程师](https://example.com/jobs/1)",
                            }
                        ],
                    },
                ],
            },
        )

    provider = ResponsesSearchProvider(
        query="校招",
        base_url="https://api.example/v1",
        api_key="test",
        model="test",
        transport=httpx.MockTransport(respond),
    )
    assert len(await provider.discover()) == 1
    assert len(calls) == 2
    assert "unsupported" in provider.last_evidence["compatibility_response"]


@pytest.mark.asyncio
async def test_listing_partial_pages_are_kept_when_browser_fails():
    from src.services.browser_job_reader import BrowserReadError

    saved, captured = [], []

    async def fetch(url):
        return FetchedResponse(url, url, 200, "text/html", b"<div>loading</div>")

    async def read_listing(url, *, max_pages, record_snapshot):
        assert max_pages == 2
        record_snapshot(url, '<a href="/jobs/first">工程师</a>')
        record_snapshot(url, '<a href="/jobs/second">工程师</a>')
        raise BrowserReadError("later page failed")

    results = await expand_entry(
        "https://example.com/careers",
        reader=SimpleNamespace(fetch=fetch),
        browser=SimpleNamespace(read_listing=read_listing),
        allowed_hosts={"example.com"},
        max_pages=2,
        record_snapshot=lambda u, h: saved.append(h),
        on_detail=lambda link, u: captured.append(link.url),
    )
    assert len(results) == len(captured) == 2
    assert len(saved) == 3


@pytest.mark.asyncio
async def test_parenthesized_url_is_not_truncated():
    url = "https://example.com/jobs?id=1&name=Engineer(J111)"
    provider = ResponsesSearchProvider(
        query="校招",
        base_url="https://api.example/v1",
        api_key="test",
        model="test",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "status": "completed",
                    "output": [
                        {"type": "web_search_call", "status": "completed"},
                        {
                            "type": "message",
                            "content": [
                                {"type": "output_text", "text": f"[工程师]({url})"}
                            ],
                        },
                    ],
                },
            )
        ),
    )
    results = await provider.discover()
    assert [r.source_url for r in results] == [url]


@pytest.mark.asyncio
async def test_official_details_jump_ahead_and_new_trust_requeues_old_lead():
    from dataclasses import replace

    verified = []

    async def search(number, seen):
        return [candidate(1), candidate(2), candidate(3)]

    async def verify(lead):
        verified.append((lead.source_url, lead.official_entry_url))
        if lead.source_url.endswith("/2"):
            return [
                replace(candidate(1), official_entry_url="https://example.com/careers")
            ]
        return None

    await run_search_pipeline(
        search=search,
        verify=verify,
        report=lambda *args: None,
        canonicalize=canonical_search_url,
        max_rounds=1,
        priority=lambda c: 0 if c.official_entry_url else int(c.source_url[-1]),
    )
    assert [url[-1] for url, _ in verified] == ["1", "2", "1", "3"]
    assert verified[2][1] == "https://example.com/careers"
