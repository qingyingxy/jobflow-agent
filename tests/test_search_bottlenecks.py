"""Regressions for source fan-out, request recovery, and role-scope caching."""
import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from src.config import Settings
from src.domain.discovery import DiscoveryRun, JobLead, LeadProvider, SearchEvidence
from src.services import multiround_search as execution
from src.services import web_search_service
from src.services.lead_providers import LeadCandidate
from src.services.recruitment_entry import expand_entry
from src.services.recruitment_trust import hiring_scope
from src.services.search_planner import build_search_tasks, next_search_task
from src.services.url_reader import FetchedResponse


@pytest.mark.asyncio
async def test_large_entry_ranks_before_callback_and_enforces_cap_across_pages():
    pages = {
        "https://official.example/careers": "".join(
            f'<a href="/jobs/{i}">市场营销专员</a>' for i in range(499)
        ) + '<a href="/jobs/499">后端研发工程师</a><a href="?page=2">下一页</a>',
    }
    callbacks, snapshots, events = [], [], []

    async def fetch(url):
        return FetchedResponse(url, url, 200, "text/html", pages[url].encode())

    async def browser_read(url):
        raise AssertionError("The capped page needs no browser or next page")

    links = await expand_entry(
        "https://official.example/careers", reader=SimpleNamespace(fetch=fetch),
        browser=SimpleNamespace(read=browser_read), allowed_hosts={"official.example"},
        official_hosts={"official.example"}, max_details=20, query="上海后端校招",
        record_snapshot=lambda url, html: snapshots.append(html),
        on_detail=lambda link, url: callbacks.append(link.url),
        on_event=lambda kind, details: events.append((kind, details)),
    )
    assert len(callbacks) == len(links) == 20
    assert callbacks[0].endswith("/499")
    assert '/jobs/498' in snapshots[0]  # Unadmitted links remain in source evidence.
    event = next(d for k, d in events if k == "entry_page")
    assert event["observed_details"] == 500 and event["deferred_by_limit"] == 480


@pytest.mark.asyncio
async def test_streamed_browser_pages_share_one_admission_limit():
    captured = []

    async def fetch(url):
        return FetchedResponse(url, url, 200, "text/html", b"<main>Loading</main>")

    async def listing(url, *, max_pages, record_snapshot):
        from src.services.browser_job_reader import BrowserReadError
        for start in (0, 15, 30):
            record_snapshot(url, "".join(f'<a href="/jobs/{i}">后端开发</a>' for i in range(start, start + 15)))
        raise BrowserReadError("Last page disconnected")

    links = await expand_entry(
        "https://official.example/careers", reader=SimpleNamespace(fetch=fetch),
        browser=SimpleNamespace(read_listing=listing), allowed_hosts={"official.example"},
        record_snapshot=lambda *args: None, max_details=20,
        on_detail=lambda link, url: captured.append(link.url),
    )
    assert len(links) == len(set(captured)) == 20


@pytest.mark.asyncio
async def test_proven_ats_entry_does_not_admit_other_tenants():
    url = "https://app.mokahr.com/social-recruitment/acme/1"
    html = f'<a href="{url}#/job/1">后端</a><a href="https://app.mokahr.com/social-recruitment/other/2#/job/2">后端</a>'

    async def fetch(target):
        return FetchedResponse(target, target, 200, "text/html", html.encode())

    links = await expand_entry(
        url, reader=SimpleNamespace(fetch=fetch), browser=None,
        allowed_hosts={"official.example"}, initial_scope=hiring_scope(url),
        record_snapshot=lambda *args: None,
    )
    assert [link.url for link in links] == [url + "#/job/1"]


def configure_execution(db_session, monkeypatch, factory, **overrides):
    settings = Settings(_env_file=None, **{
        "web_search_max_rounds": 3, "web_search_budget_seconds": 2,
        "web_search_request_timeout_seconds": 0.02,
        "web_search_verification_budget_seconds": 1,
        **overrides,
    })
    monkeypatch.setattr(execution, "get_settings", lambda: settings)
    monkeypatch.setattr(execution, "SessionLocal", sessionmaker(bind=db_session.bind))
    monkeypatch.setattr(execution, "enabled_company_source_hosts", lambda: {"official.example"})
    monkeypatch.setattr(execution, "enabled_company_sources", lambda *args: [SimpleNamespace(company="Example", career_url="https://official.example/careers")])
    monkeypatch.setattr(web_search_service, "create_web_search_provider", factory)
    run = DiscoveryRun(id="bottleneck", user_id="u", source="test", source_url="https://official.example", started_at=datetime.now(UTC))
    db_session.add(run)
    db_session.commit()
    return run


QUERY = "2027届上海后端校招，不考虑北京，不考虑社招"


async def execute():
    await execution.execute_multiround_search(run_id="bottleneck", user_id="u", query=QUERY, company_ids=[])


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "524", "401"])
async def test_request_failure_is_bounded_and_falls_back_without_losing_query(db_session, monkeypatch, failure):
    calls, cancelled = [], []

    class Provider:
        source_id = "test"

        def __init__(self, query):
            self.query, self.last_evidence = query, {}

        async def discover(self):
            calls.append(self.query)
            if len(calls) <= 2:
                if failure == "timeout":
                    try:
                        await asyncio.Event().wait()
                    finally:
                        cancelled.append(self.query)
                else:
                    self.last_evidence = {"http_status": int(failure), "raw_response": "upstream failure"}
                    raise web_search_service.WebSearchPayloadError(f"HTTP {failure}")
            return []

    run = configure_execution(db_session, monkeypatch, lambda query, _: Provider(query))
    await execute()
    db_session.expire_all()
    records = list(db_session.scalars(select(SearchEvidence).order_by(SearchEvidence.created_at)))
    assert len(calls) == len(records) == (1 if failure == "401" else 3)
    assert all(QUERY in call for call in calls)
    traces = [t["details"] for t in run.agent_trace if t["tool"] == "search_query"]
    if failure != "401":
        assert calls[:2] == [QUERY, QUERY]
        assert traces[0]["retry_scheduled"] and traces[1]["is_retry"]
        assert "site:" not in calls[2]  # Recover across companies, not a fixed company list.
    else:
        assert len(calls) == 1
        assert not any(t["is_retry"] for t in traces)
        assert "认证或访问权限" in run.failure_summary
    assert sum(t["retry_scheduled"] for t in traces) <= 1
    if failure == "timeout":
        assert len(cancelled) == 2 and traces[0]["error_code"] == "SearchRequestTimeout"
    assert run.status != "RUNNING"


@pytest.mark.asyncio
async def test_unconfirmed_aggregate_is_preserved_without_expansion_or_user_handoff(db_session, monkeypatch):
    url = "https://aggregator.example/companies/acme.html"

    class Provider:
        source_id = "test"

        async def discover(self):
            return [LeadCandidate(provider=LeadProvider.EXTERNAL_AGENT, source_url=url, title_hint="招聘职位汇总", discovered_at=datetime.now(UTC))]

    run = configure_execution(db_session, monkeypatch, lambda *_: Provider(), web_search_max_rounds=1)

    async def forbidden(*args, **kwargs):
        raise AssertionError("Unconfirmed aggregator must not be expanded")

    monkeypatch.setattr(execution, "expand_entry", forbidden)
    await execute()
    db_session.expire_all()
    leads = list(db_session.scalars(select(JobLead)))
    assert len(leads) == 1
    assert leads[0].status == "DEFERRED" and leads[0].failure_code == "entry_source_unconfirmed"
    assert any(t["tool"] == "entry_expansion" and t["details"]["output_count"] == 0 for t in run.agent_trace)


@pytest.mark.asyncio
async def test_total_budget_cancels_request_without_dispatching_retry(db_session, monkeypatch):
    cancelled, calls = [], []

    class Provider:
        source_id = "test"

        async def discover(self):
            calls.append(True)
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.append(True)

    run = configure_execution(
        db_session, monkeypatch, lambda *_: Provider(),
        web_search_budget_seconds=1, web_search_request_timeout_seconds=20,
    )
    await execute()
    db_session.expire_all()
    assert len(calls) == len(cancelled) == 1
    records = list(db_session.scalars(select(SearchEvidence)))
    assert len(records) == 1 and records[0].status == "FAILED"
    assert not records[0].details["retry_scheduled"]
    assert "时间预算" in run.agent_trace[-1]["decision"]


def test_poor_feedback_prefers_broad_recovery_with_original_exclusions():
    sources = [SimpleNamespace(company="Example", career_url="https://official.example/careers")]
    tasks = build_search_tasks(QUERY, sources)
    task = next_search_task(tasks, {QUERY}, poor_results=True)
    assert task.strategy == "条件补搜" and QUERY in task.query
    next_task = next_search_task(tasks, {QUERY, task.query}, poor_results=True)
    assert next_task.strategy == "同义岗位" and QUERY in next_task.query
    focused = next_search_task(tasks, {QUERY, task.query}, poor_results=True, last_strategy=task.strategy)
    assert focused.strategy == "公司官网" and QUERY in focused.query
    recovered = next_search_task(tasks, {QUERY, task.query, focused.query}, poor_results=True, last_strategy=focused.strategy)
    assert recovered.strategy == "同义岗位" and QUERY in recovered.query


@pytest.mark.parametrize("header, expected", [
    ("上海、北京 校招", ["上海", "北京"]),
    ("深圳市 / 上海市 社会招聘", ["深圳市", "上海市"]),
    ("上海、多伦多 校招", []),
    ("上海、北京大学 校招", []),
    ("上海 校招，仅限本地", []),
])
def test_compact_city_and_type_header_preserves_unknown_locations(header, expected):
    from src.services.job_header_facts import header_location_evidence

    text = f"工程师\n{header}\n岗位职责\n负责软件开发。"
    evidence = header_location_evidence(text, "工程师")
    assert [item["value"] for item in evidence] == expected
    assert all(text[item["start_char"]:item["end_char"]] == item["source_text"] for item in evidence)
