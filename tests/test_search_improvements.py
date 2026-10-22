import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from src.services.company_coverage import CompanyCoverage
from src.services.company_search_progress import fresh_search_profiles
from src.services.direct_recruitment_search import DirectRecruitmentSearch
from src.services.lead_presentation import discovery_kind
from src.services.retrieval_quality import search_link_rejection
from src.services.search_pipeline import run_search_pipeline
from src.services.search_scheduling import listing_priority
from tests.test_direct_recruitment_search import QUERY, SOURCE
from tests.test_search_scheduling import lead


@pytest.mark.parametrize("prefix", ["https://jobs.example/campus", "https://jobs.example/#/campus"])
def test_invitation_is_not_a_job_but_referral_tracking_on_details_is_preserved(prefix):
    url = prefix + "/invite?referral_code=example"
    assert search_link_rejection(url, "Agent工程师", query=QUERY) == "recruitment_action_page"
    assert discovery_kind(url, "Agent工程师", observed_title=True) == "entry"
    detail = "https://jobs.example/position/123/detail?referral_code=example"
    assert search_link_rejection(detail, "Agent工程师", query=QUERY) is None
    assert discovery_kind(detail) == "job"


@pytest.mark.parametrize("query,titles,expected", [
    ("2027届上海 Agent RAG 校招", ["2027届校招 芯片工程师", "2027届校招 Agent开发", "RAG工程师"],
     ["2027届校招 Agent开发", "RAG工程师", "2027届校招 芯片工程师"]),
    ("上海后端校招", ["2027届校招 前端工程师", "后端工程师"], ["后端工程师", "2027届校招 前端工程师"]),
    ("上海 Agent 校招", ["Agent实习工程师", "校招后端工程师", "Agent校招工程师"],
     ["Agent校招工程师", "校招后端工程师", "Agent实习工程师"]),
])
def test_direction_precedes_recruitment_type_without_discarding_unknown_titles(query, titles, expected):
    assert sorted(titles, key=lambda title: listing_priority(title, query, ["校招"])) == expected


@pytest.mark.asyncio
async def test_concurrent_bootstrap_does_not_block_search_and_keeps_later_jobs():
    started, searched = asyncio.Event(), asyncio.Event()
    observed = []

    async def bootstrap(enqueue):
        started.set()
        await searched.wait()
        enqueue([lead(2)])

    async def search(*_):
        await started.wait()
        searched.set()
        return [lead(1)]

    async def verify(candidate):
        observed.append(candidate.source_url)
        return candidate.source_url, True

    await asyncio.wait_for(run_search_pipeline(
        bootstrap=bootstrap, bootstrap_concurrent=True, search=search, verify=verify,
        report=lambda *_: None, canonicalize=lambda u: u, max_rounds=1, seconds=1,
    ), 2)
    assert set(observed) == {lead(1).source_url, lead(2).source_url}


@pytest.mark.asyncio
async def test_promoted_link_while_reading_or_reviewing_reuses_one_read():
    started, release, reviewing, finish_review = (asyncio.Event() for _ in range(4))
    reads, reviews, results = [], [], []

    async def bootstrap(enqueue):
        enqueue([lead(1)])
        await started.wait()
        enqueue([replace(lead(1), official_entry_url="https://a.example/careers")])
        release.set()
        await reviewing.wait()
        enqueue([replace(lead(1), official_entry_url="https://a.example/careers")])
        finish_review.set()

    async def search(*_):
        await finish_review.wait()
        return []

    async def verify(candidate):
        reads.append(candidate.source_url)
        started.set()
        await release.wait()
        return candidate.source_url, False

    async def review(job):
        reviews.append(job)
        reviewing.set()
        await finish_review.wait()
        return job, True

    await asyncio.wait_for(run_search_pipeline(
        bootstrap=bootstrap, bootstrap_concurrent=True, search=search, verify=verify, review=review,
        report=lambda *_: None, canonicalize=lambda u: u, max_rounds=1, seconds=1,
        on_candidate_done=lambda c, result, error: results.append((result, error)),
    ), 2)
    assert reads == reviews == [lead(1).source_url]
    assert results == [((lead(1).source_url, True), None)]


@pytest.mark.asyncio
async def test_cancellation_stops_concurrent_producer_before_returning():
    started, stopped = asyncio.Event(), asyncio.Event()

    async def bootstrap(enqueue):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    async def search(*_):
        await started.wait()
        await asyncio.Event().wait()

    task = asyncio.create_task(run_search_pipeline(
        bootstrap=bootstrap, bootstrap_concurrent=True, search=search, verify=None,
        report=lambda *_: None, canonicalize=lambda u: u,
    ))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert stopped.is_set()


def test_fallback_waits_for_fast_source_but_not_failed_or_stalled_source():
    from time import monotonic

    other = replace(SOURCE, id="other")
    coverage = CompanyCoverage(sources=[SOURCE, other], query=QUERY, batch_size=2,
                               store=SimpleNamespace(load=dict))
    direct = DirectRecruitmentSearch(sources=[SOURCE, other], query=QUERY, reader=None,
                                    browser=object(), on_event=lambda *_: None)
    direct.running = True
    direct.pending_sources = {SOURCE.id, other.id}
    direct.active_started = {SOURCE.id: monotonic(), other.id: monotonic()}
    assert coverage.next_task(direct) is None
    direct.states[SOURCE.id] = {"status": "failed"}
    direct.pending_sources.remove(SOURCE.id)
    assert coverage.next_task(direct).company_id == SOURCE.id
    coverage.web_attempted.add(SOURCE.id)
    direct.active_started[other.id] -= 9
    assert coverage.next_task(direct).company_id == other.id
    direct.published_sources.add(other.id)
    direct.last_progress[other.id] = monotonic()
    assert coverage.next_task(direct) is None
    direct.last_progress[other.id] -= 9
    assert coverage.next_task(direct).company_id == other.id


def test_web_cursor_survives_interleaved_listing_checkpoints():
    saved = {}
    store = SimpleNamespace(load=dict, save=lambda key, state: saved.update({key: deepcopy(state)}))
    coverage = CompanyCoverage(sources=[SOURCE], query=QUERY, batch_size=1, store=store)
    listing = {"strategy": "official_listing", "status": "running", "search_cursor": 0,
               "html_queue": [{"url": SOURCE.career_url}]}
    coverage.save_direct(SOURCE.id, listing)
    coverage.start_search(SOURCE.id, keep_listing=True)
    coverage.finish_search(SOURCE.id, failed=False)
    listing["status"] = "paused"
    coverage.save_direct(SOURCE.id, listing)
    assert saved[SOURCE.id]["search_cursor"] == 1
    assert saved[SOURCE.id]["search_status"] == "succeeded"
    assert saved[SOURCE.id]["html_queue"] == listing["html_queue"]
    coverage.record_match(SOURCE.id, "https://jobs.example/123", True)
    coverage.save_direct(SOURCE.id, listing)
    assert listing["matched_urls"] == ["https://jobs.example/123"]
    coverage.record_match(SOURCE.id, "https://jobs.example/123", False)
    coverage.save_direct(SOURCE.id, listing)
    assert listing["matched_urls"] == []
    assert listing["checked_urls"] == ["https://jobs.example/123"]


def test_finished_or_expired_cursor_reuses_only_fresh_search_recipe():
    now = datetime.now(UTC)
    profile = {"recipe": {"input": "input[name=q]"}, "checked_at": now.isoformat()}
    state = {"status": "completed", "strategy": "official_listing",
             "started_at": (now-timedelta(days=8)).isoformat(), "buffer": [{"id": "old-job"}],
             "search_profiles": {SOURCE.career_url: profile}}
    coverage = CompanyCoverage(sources=[SOURCE], query=QUERY, batch_size=1,
                               store=SimpleNamespace(load=lambda: {SOURCE.id: state}))
    assert coverage.direct_states() == {SOURCE.id: {"search_profiles": {SOURCE.career_url: profile}}}
    profile["checked_at"] = (now-timedelta(days=31)).isoformat()
    assert fresh_search_profiles(state) == {}
    assert coverage.direct_states() == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("reader_kind", ["html", "ats"])
async def test_web_matches_arriving_during_listing_read_share_quota_and_survive_resume(reader_kind):
    from src.services.browser_job_reader import BrowserPageSnapshot
    from tests.test_company_search_progress import ManyJobs

    saved, matched, found = {}, set(), []
    store = SimpleNamespace(load=lambda: deepcopy(saved),
                            save=lambda key, state: saved.update({key: deepcopy(state)}))
    coverage = CompanyCoverage(sources=[SOURCE], query=QUERY, batch_size=1, store=store)
    urls = [SOURCE.career_url + f"position/{number}/detail" for number in range(6)]

    class Browser(ManyJobs):
        async def read_search_listing(self, url):
            # The web consumer finishes while the official producer owns an
            # older in-memory cursor. Its next checkpoint must merge results.
            if not matched:
                for known in urls[:2]:
                    matched.add(known)
                    coverage.record_match(SOURCE.id, known, True)
            if reader_kind == "ats":
                return await super().read_search_listing(url)
            html = "".join(f'<a href="{job}">Agent工程师 {i}</a>' for i, job in enumerate(urls))
            return BrowserPageSnapshot(url, url, "校招", html, "岗位列表")

    async def verified(candidate):
        matched.add(candidate.source_url)
        coverage.record_match(SOURCE.id, candidate.source_url, True)
        return True

    browser = Browser(count=6)
    direct = DirectRecruitmentSearch(sources=[SOURCE], query=QUERY, reader=None, browser=browser,
        on_event=lambda *_: None, checkpoint=coverage.save_direct, company_done=lambda _: len(matched) >= 3)
    await direct.discover(found.extend, await_result=verified)
    assert [candidate.source_url for candidate in found] == urls[2:3]
    assert set(saved[SOURCE.id]["matched_urls"]) == set(urls[:3])
    assert saved[SOURCE.id]["reason"] == "company_read_limit"

    resumed = DirectRecruitmentSearch(sources=[SOURCE], query=QUERY, reader=None, browser=browser,
        on_event=lambda *_: None, states=deepcopy(saved))
    continued = []
    await resumed.discover(continued.extend, await_result=verified)
    assert [candidate.source_url for candidate in continued] == urls[3:]


@pytest.mark.asyncio
async def test_saved_goal_starts_failed_company_fallback_before_other_official_reader_finishes(db_session, monkeypatch):
    from sqlalchemy.orm import sessionmaker

    from src.config import Settings
    from src.services import multiround_search as execution
    from src.services import web_search_service
    from src.services.discovery_sources import SourcePayloadError
    from tests.test_company_coverage import goal_and_store, run_search

    started_web = asyncio.Event()
    events = []
    other = replace(SOURCE, id="alibaba", company="另一个公司", career_url="https://other.example/campus")
    sources = [SOURCE, other]
    settings = Settings(_env_file=None, web_search_direct_sources_enabled=True,
        web_search_role_review_enabled=False, web_search_max_rounds=2,
        web_search_budget_seconds=2, web_search_company_seconds=1.5,
        company_discovery_enabled=False)

    async def source_jobs(self, source):
        if source.id == SOURCE.id:
            raise SourcePayloadError("Official listing failed")
        await started_web.wait()
        events.append("other_official_finished")
        if False:
            yield None

    class Provider:
        source_id, source_url = "test", "https://search.example"

        def __init__(self, query, company_ids=None, **kwargs):
            self.company = company_ids[0] if company_ids else None

        async def discover(self):
            events.append("web:" + str(self.company))
            started_web.set()
            return []

    monkeypatch.setattr(execution, "get_settings", lambda: settings)
    monkeypatch.setattr(execution, "SessionLocal", sessionmaker(bind=db_session.bind))
    monkeypatch.setattr(execution, "enabled_company_sources", lambda *_, **__: sources)
    monkeypatch.setattr(execution, "enabled_company_source_hosts", lambda **_: {"other.example", "jobs.bytedance.com"})
    monkeypatch.setattr(execution, "PlaywrightBrowserJobReader", lambda **_: SimpleNamespace(read_search_listing=None))
    monkeypatch.setattr(DirectRecruitmentSearch, "_source", source_jobs)
    monkeypatch.setattr(web_search_service, "create_web_search_provider", Provider)
    goal, _ = goal_and_store(db_session, [SOURCE.id, other.id])
    await asyncio.wait_for(run_search(db_session, goal, "parallel"), 3)
    assert events.index("web:" + SOURCE.id) < events.index("other_official_finished")
    assert goal.company_search_state["sources"][SOURCE.id]["search_cursor"] == 1
