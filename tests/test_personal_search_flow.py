"""Personal search: useful history first, observed entries survive cursor resets."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from src.services.company_coverage import CompanyCoverage
from src.services.company_registry import CompanySource
from src.services.company_search_progress import fresh_cursor
from src.services.direct_recruitment_search import DirectRecruitmentSearch
from src.services.lead_providers import LeadCandidate, LeadProviderKind
from src.services.official_hiring_resolver import OfficialHiringResolver
from src.services.search_goal_service import SearchGoalService
from src.services.url_reader import FetchedResponse
from src.services.verified_recruitment_entry import (
    current_progress,
    fresh_entry,
    remember_entry,
)
from tests.test_direct_recruitment_search import QUERY, SOURCE, PortalQueryBrowser
from tests.test_search_goals import add_posting


def entry(source=SOURCE, url=None):
    url = url or source.career_url
    return remember_entry(source, {"url": url, "scope_url": url,
        "proof_url": source.career_url, "official_html": "<a href='" + url + "'>招聘</a>"})


def test_history_orders_by_body_rotates_companies_and_keeps_an_exploration_slot(db_session):
    for i in range(3):
        job = add_posting(db_session, identifier=f"old-{i}", age=2)
        job.company, job.title, job.raw_content = "旧公司", "芯片控制工程师", "岗位职责：负责芯片设计、硬件调试，参与设计评审与测试验收工作。任职要求：本科毕业，校招2027届。"
    for company, count in [("目标一", 3), ("目标二", 1)]:
        for i in range(count):
            job = add_posting(db_session, identifier=f"{company}-{i}")
            job.company, job.title = company, "软件工程师"
            job.raw_content = "2027届校招，上海。岗位职责：负责Agent应用研发、RAG检索系统开发，参与工具调用和任务规划。任职要求：本科毕业。"
    db_session.commit()
    queue = SearchGoalService(db_session).refresh_candidates("owner", query=QUERY,
        conditions={"roles": ["ai agent", "rag"], "job_types": ["校招"], "locations": ["上海"]},
        primary=True, limit=4)
    assert len(queue) == 4
    assert {c.company_hint for c in queue[:2]} == {"目标一", "目标二"}
    assert queue[2].company_hint == "目标一"
    assert queue[3].company_hint == "旧公司"  # bounded, explicit exploration


def test_entry_reset_discards_filters_and_results_but_keeps_observed_proof():
    saved = {"version": 1, "sources": {SOURCE.id: {"verified_entry": entry(),
        "filters": {"location": "old"}, "buffer": [{"id": "old"}], "page_number": 9,
        "checked_urls": ["old"], "matched_urls": ["old"], "status": "completed"}}}
    reset = current_progress(saved, 2)
    assert set(reset["sources"][SOURCE.id]) == {"verified_entry"}
    coverage = CompanyCoverage(sources=[SOURCE], store=SimpleNamespace(load=lambda: reset["sources"]),
        query=QUERY, batch_size=1)
    assert coverage.direct_states()[SOURCE.id] == {"verified_entry": entry_record(saved)}
    assert fresh_entry(reset["sources"][SOURCE.id], replace(SOURCE, career_url="https://moved.example/")) is None
    assert saved["sources"][SOURCE.id]["page_number"] == 9


def entry_record(saved):
    return saved["sources"][SOURCE.id]["verified_entry"]


@pytest.mark.parametrize("age", [-1, 31])
def test_future_or_expired_entry_is_not_reused(age):
    record = entry()
    record["checked_at"] = (datetime.now(UTC) - timedelta(days=age)).isoformat()
    assert fresh_entry({"verified_entry": record}, SOURCE) is None
    assert not fresh_cursor({"started_at": record["checked_at"]})


def test_revisiting_destination_cannot_extend_original_official_link_ttl():
    record = entry()
    record["checked_at"] = (datetime.now(UTC) - timedelta(days=29)).isoformat()
    refreshed = remember_entry(SOURCE, {**record, "cached_entry": True})
    assert refreshed["checked_at"] == record["checked_at"]


@pytest.mark.parametrize("url,company", [
    ("https://talent.baidu.com/jobs/detail/GRADUATE/123", "百度"),
    ("https://unknown.example/jobs/123", None),
    ("https://wecruit.hotjob.cn/SUunknown/pb/posDetail.html?postId=1", None),
])
def test_missing_company_uses_unique_verified_source_not_title_guess(db_session, url, company):
    from src.services.job_lead_service import JobLeadService
    from tests.test_search_goals import BASE

    result = JobLeadService(db_session)._official_company(
        SimpleNamespace(id="no-lead", user_id="owner", source_url=url), replace(BASE, company=None))
    assert result.company == company


@pytest.mark.asyncio
async def test_failed_cached_entry_falls_back_to_official_homepage():
    from src.services.browser_job_reader import BrowserReadError

    calls, events = [], []
    bad = "https://moved.example/campus/"

    class Browser(PortalQueryBrowser):
        async def read_search_listing(self, url):
            calls.append(url)
            if url == bad:
                raise BrowserReadError("moved")
            return await super().read_search_listing(url)

    search = DirectRecruitmentSearch(sources=[SOURCE], query=QUERY, reader=None, browser=Browser(),
        states={SOURCE.id: {"verified_entry": entry(url=bad)}},
        on_event=lambda kind, data: events.append(kind))
    found = []
    await search.discover(found.extend)
    assert calls[:2] == [bad, SOURCE.career_url]
    assert found and "recruitment_entry_fallback" in events
    assert search.states[SOURCE.id]["verified_entry"]["url"] == SOURCE.career_url


@pytest.mark.asyncio
async def test_changed_cached_api_reloads_entry_filters_and_preserves_checked_urls():
    from src.services.discovery_sources import SourcePayloadError

    class ChangedAPI(DirectRecruitmentSearch):
        async def _pages(self, source, state):
            if state.get("filters") == {"location": "obsolete"}:
                raise SourcePayloadError("API changed")
            async for candidate in super()._pages(source, state):
                yield candidate

    search = ChangedAPI(sources=[SOURCE], query=QUERY, reader=None, browser=PortalQueryBrowser(),
        states={SOURCE.id: {"base": SOURCE.career_url, "reader_kind": "feishu",
            "filters": {"location": "obsolete"}, "verified_entry": entry(),
            "checked_urls": ["https://example.com/previous"]}}, on_event=lambda *_: None)
    found = []
    await search.discover(found.extend)
    assert found
    assert search.states[SOURCE.id]["filters"]["location"] == "sh"
    assert "https://example.com/previous" in search.states[SOURCE.id]["checked_urls"]


@pytest.mark.asyncio
@pytest.mark.parametrize("brand", ["Acme招聘", "Unrelated招聘"])
async def test_custom_hiring_domain_needs_official_link_and_destination_identity(brand):
    source = CompanySource("acme", "Acme", "A", "https://acme.example/careers", "official")
    hiring = "https://jobs.acme.example/edu/"
    calls, saved = [], []

    async def fetch(url):
        calls.append(url)
        html = f'<a href="{hiring}">应届生招聘 立即投递</a>' if url == source.career_url else f"<title>{brand}</title>"
        return FetchedResponse(url, url, 200, "text/html", html.encode())

    resolver = OfficialHiringResolver(sources=[source], reader=SimpleNamespace(fetch=fetch), browser=None)
    resolver.on_entry = lambda source, entry: saved.append(entry)
    candidate = LeadCandidate(provider=LeadProviderKind.EXTERNAL_AGENT, source_url=hiring + "position/123/detail",
        company_hint="Acme", discovered_at=datetime.now(UTC))
    proof = await resolver.resolve(candidate, record_snapshot=lambda *args: "snapshot")
    assert bool(proof) == (brand == "Acme招聘")
    if proof:
        assert saved and calls == [source.career_url, hiring]
        second = OfficialHiringResolver(sources=[source], reader=None, browser=None)
        second.entry_states = lambda: {source.id: {"verified_entry": saved[0]}}
        assert await second.resolve(replace(candidate, company_hint=None), record_snapshot=lambda *args: "saved")
        from src.services.official_hiring_resolver import covers
        assert not covers("https://jobs.acme.example/other/position/1", proof.scope_url)
