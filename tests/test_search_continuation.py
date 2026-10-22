"""Search continuations preserve evidence and avoid repeating completed work."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import sessionmaker

from src.config import Settings
from src.domain.discovery import DiscoveryRun
from src.domain.job import JobAvailabilityStatus, JobPosting
from src.domain.search_goal import SearchGoalConditions
from src.services.discovery_matching import search_filter_conditions
from src.services.entry_expansion_budget import EntryExpansionBudget, EntryPageCache
from src.services.job_lead_service import JobLeadService
from src.services.recruitment_entry import expand_entry
from src.services.search_goal_service import SearchGoalService, posting_stub
from src.services.source_understanding import checked_decisions, pending_review_fields
from src.services.url_reader import FetchedResponse
from tests.test_source_understanding import QUERY, decision, engine, job, paragraphs


@pytest.mark.asyncio
async def test_budget_limited_field_can_resume_but_missing_or_ambiguous_facts_do_not_loop():
    original = job(1)
    runtime = engine([])
    runtime.settings = runtime.settings.model_copy(update={"web_search_semantic_max_calls": 0})
    pending = await runtime.review(original, query=QUERY)
    attempt = pending.recruitment_context["source_review_attempt"]
    assert attempt["error_code"] == "semantic_budget" and attempt["failures"] == 0
    conditions = search_filter_conditions(QUERY)
    assert pending_review_fields(pending, query=QUERY, conditions=conditions) == ["graduation_year"]
    index = next(i for i, p in enumerate(paragraphs(original.raw_content)) if "2026/2027" in p)
    model = engine([decision("graduation_year", "matched", [index])])
    recovered = await model.review(pending, query=QUERY)
    assert checked_decisions(recovered, conditions)["graduation_year"]["status"] == "matched"
    assert not pending_review_fields(recovered, query=QUERY, conditions=conditions)
    assert "graduation_year" not in pending_review_fields(job(0), query=QUERY, conditions=conditions)
    ambiguous = await engine([decision("graduation_year", "pending", [index], diagnosis="ambiguous")]).review(original, query=QUERY)
    assert not pending_review_fields(ambiguous, query=QUERY, conditions=conditions)


@pytest.mark.asyncio
async def test_failed_semantics_cool_down_without_hiding_changed_evidence():
    invalid = await engine([decision("graduation_year", "matched", [999])]).review(job(1), query=QUERY)
    conditions = search_filter_conditions(QUERY)
    assert not pending_review_fields(invalid, query=QUERY, conditions=conditions)
    changed = replace(invalid, raw_content=invalid.raw_content + "\n补充说明：接受2027届毕业生。")
    assert pending_review_fields(changed, query=QUERY, conditions=conditions)


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_before_review", [False, True])
async def test_saved_unknown_body_resumes_through_real_pipeline_without_a_reader(db_session, monkeypatch, cancel_before_review):
    from src.infrastructure.llm_client import FakeModelClient
    from src.services import multiround_search, source_understanding, web_search_service
    from tests.test_search_execution import candidate

    conditions = SearchGoalConditions.model_validate(search_filter_conditions(QUERY))
    goals = SearchGoalService(db_session)
    goal = goals.save(user_id="u", input_text=QUERY, conditions=conditions, condition_sources={}, company_ids=[])
    first = DiscoveryRun(id="before-resume", user_id="u", source="test", source_url="https://example.com",
                         search_goal_id=goal.id, search_goal_version=goal.version,
                         search_query=QUERY, started_at=datetime.now(UTC))
    db_session.add(first)
    db_session.commit()
    service = JobLeadService(db_session)
    lead = service.capture_candidate(user_id="u", discovery_run_id=first.id, candidate=candidate(1))
    original = replace(job(1), detail_url=candidate(1).source_url)
    saved = service.verify_stub(user_id="u", lead_id=lead.id, stub=original,
                               availability_status=JobAvailabilityStatus.UNKNOWN).posting
    read_at = saved.last_verified_at
    assert goals.refresh_candidates("u", query=QUERY, conditions=conditions.model_dump())
    assert goals.cached_posting("u", saved.source_url) is saved
    assert goals.cached_posting("other", saved.source_url) is None
    index = next(i for i, p in enumerate(paragraphs(original.raw_content)) if "2026/2027" in p)
    client = FakeModelClient(output={"decisions": [decision("graduation_year", "matched", [index])]})

    class Provider:
        source_id = "test"

        async def discover(self):
            return []

    async def forbidden(*args, **kwargs):
        raise AssertionError("Saved official body must not be fetched again")

    settings = Settings(_env_file=None, web_search_understanding_mode="hybrid", structured_model_provider="openai",
        web_search_direct_sources_enabled=False, company_discovery_enabled=False,
        web_search_max_rounds=1, web_search_budget_seconds=5, web_search_verification_budget_seconds=5)
    monkeypatch.setattr(multiround_search, "get_settings", lambda: settings)
    monkeypatch.setattr(multiround_search, "SessionLocal", sessionmaker(bind=db_session.bind))
    monkeypatch.setattr(multiround_search, "enabled_company_source_hosts", lambda **_: {"example.com"})
    monkeypatch.setattr(multiround_search, "enabled_company_sources", lambda *_, **__: [])
    monkeypatch.setattr(web_search_service, "create_web_search_provider", lambda *_, **__: Provider())
    monkeypatch.setattr(source_understanding, "create_structured_model_client", lambda _: client)
    monkeypatch.setattr(JobLeadService, "verify_url", forbidden)
    monkeypatch.setattr(JobLeadService, "verify_browser", forbidden)
    run = DiscoveryRun(id="resume", user_id="u", source="test", source_url="https://example.com",
        search_goal_id=goal.id, search_goal_version=goal.version, goal_conditions=conditions.model_dump(),
        search_query=QUERY, started_at=datetime.now(UTC))
    db_session.add(run)
    db_session.commit()
    # A website read failure must not block interpretation of already saved text.
    from src.services.company_search_progress import CompanyProgressStore
    store = CompanyProgressStore(db_session, user_id="u", goal_id=goal.id, version=goal.version)
    store.save_verification("example.com", {"failures": 3, "blocks": 1,
        "last_failure_code": "browser_timeout", "next_retry_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat()})
    if cancel_before_review:
        entered = asyncio.Event()
        original_pipeline = multiround_search.run_search_pipeline

        async def hold_before_review(_job_id):
            entered.set()
            await asyncio.Event().wait()

        async def paused_pipeline(**kwargs):
            kwargs["review"] = hold_before_review
            return await original_pipeline(**kwargs)

        with monkeypatch.context() as paused:
            paused.setattr(multiround_search, "run_search_pipeline", paused_pipeline)
            task = asyncio.create_task(multiround_search.execute_multiround_search(
                run_id=run.id, user_id="u", query=QUERY, company_ids=[], analysis_limit=0))
            try:
                await asyncio.wait_for(entered.wait(), 2)
                db_session.refresh(saved)
                attempt = saved.recruitment_context["source_review_attempt"]
                assert attempt["error_code"] == "semantic_pending"
                assert attempt["fields"] == ["graduation_year"] and attempt["failures"] == 0
                assert not client.requests
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        run = DiscoveryRun(id="after-queued-cancellation", user_id="u", source="test",
            source_url="https://example.com", search_goal_id=goal.id, search_goal_version=goal.version,
            goal_conditions=conditions.model_dump(), search_query=QUERY, started_at=datetime.now(UTC))
        db_session.add(run)
        db_session.commit()
    await multiround_search.execute_multiround_search(run_id=run.id, user_id="u", query=QUERY,
                                                     company_ids=[], analysis_limit=0)
    db_session.expire_all()
    saved = db_session.get(JobPosting, saved.id)
    assert saved.last_verified_at.replace(tzinfo=UTC) == read_at.replace(tzinfo=UTC)
    assert saved.availability_status == "UNKNOWN"
    assert len(client.requests) == 1
    assert checked_decisions(posting_stub(saved), conditions.model_dump())["graduation_year"]["status"] == "matched"
    assert run.usage_metrics["read_attempts"] == 0 and run.usage_metrics["cache_hits"] == 1
    assert run.result_matches[0]["filter_status"] == "pending"
    assert run.result_matches[0]["review_status"] == "recommended"
    from src.services.discovery_results import current_run_matches
    assert current_run_matches(db_session, [run])[run.id][0]["review_status"] == "recommended"
    assert goals.library("u", goal.id)["counts"]["recommended"] == 1
    assert store.load_verification()["example.com"]["failures"] == 3
    assert not goals.refresh_candidates("u", query=QUERY, conditions=conditions.model_dump())
    # An unknown state still gets a real source refresh after one day.
    saved.last_verified_at = datetime.now(UTC) - timedelta(days=2)
    db_session.commit()
    assert goals.cached_posting("u", saved.source_url) is None
    assert goals.refresh_candidates("u", query=QUERY, conditions=conditions.model_dump())


def test_entry_budget_is_separate_and_unproductive_sources_pause_with_saved_cursors():
    clock = [0]
    saved = {}
    budget = EntryExpansionBudget(seconds=5, item_seconds=3, empty_limit=2,
        clock=lambda: clock[0], checkpoint=lambda key, state: saved.update({key: state}))
    for i in range(2):
        url = f"https://example.com/careers?channel={i}"
        assert budget.reason(url, "one") is None
        assert budget.begin(url) == 3
        clock[0] += 1
        budget.finish(url, "one", {"queue": [url], "pending_details": {}}, 0, interrupted=True)
    assert budget.reason("https://example.com/campus", "one") == "entry_no_progress"
    assert budget.reason("https://other.example/careers", "two") is None
    assert budget.begin("https://other.example/careers") == 3
    clock[0] += 3
    budget.finish("https://other.example/careers", "two", {}, 1)
    assert budget.reason("https://third.example/careers", "three") == "entry_budget"
    resumed = EntryExpansionBudget(states=saved)
    url = "https://example.com/careers?channel=0"
    assert resumed.reason(url, "one") == "entry_cooldown"
    assert resumed.cursor(url)["queue"] == [url]


@pytest.mark.asyncio
async def test_entry_continues_saved_links_and_next_page_without_rereading_first_page():
    base = "https://example.com/careers"
    pages = {base: '<a href="/jobs/1">Agent开发</a><a href="/jobs/2">AI产品经理</a><a href="?page=2">下一页</a>',
             base + "?page=2": '<a href="/jobs/3">RAG开发</a>'}
    calls, state, found = [], {}, []

    async def fetch(url):
        calls.append(url)
        return FetchedResponse(url, url, 200, "text/html", pages[url].encode())

    for _ in range(3):
        links = await expand_entry(base, reader=SimpleNamespace(fetch=fetch), browser=None,
            allowed_hosts={"example.com"}, record_snapshot=lambda *_: None,
            max_pages=1, max_details=1, state=state)
        found.extend(link.url for link in links)
    assert found == [f"https://example.com/jobs/{i}" for i in (1, 2, 3)]
    assert calls == [base, base + "?page=2"]
    assert not state["queue"] and not state["pending_details"]


@pytest.mark.asyncio
async def test_resumed_ats_scope_restores_transport_without_admitting_other_tenants():
    base = "https://official.example/careers"
    scope = ("app.mokahr.com", "/campus-recruitment/acme/1")
    page = "https://" + "".join(scope) + "?page=2"
    other = "https://app.mokahr.com/campus-recruitment/other/2?page=2"
    checker = SimpleNamespace(proxy_allowed_hosts=frozenset({"official.example"}))
    state = {"queue": [page, other], "scopes": [list(scope)]}
    calls = []

    async def fetch(url):
        assert scope[0] in checker.proxy_allowed_hosts
        calls.append(url)
        return FetchedResponse(url, url, 200, "text/html", b'<a href="#/job/1">Agent</a>')

    links = await expand_entry(base, reader=SimpleNamespace(fetch=fetch, safety_checker=checker), browser=None,
        allowed_hosts={"official.example"}, record_snapshot=lambda *_: None, state=state)
    assert calls == [page]
    assert len(links) == 1 and "acme" in links[0].url


@pytest.mark.asyncio
async def test_entry_cancellation_keeps_next_page_without_losing_emitted_jobs():
    base = "https://example.com/careers"
    second_started = asyncio.Event()
    calls, state = [], {}

    async def fetch(url):
        calls.append(url)
        if "page=2" in url:
            second_started.set()
            await asyncio.Event().wait()
        return FetchedResponse(url, url, 200, "text/html", b'<a href="/jobs/1">Agent</a><a href="?page=2">next</a>')

    task = asyncio.create_task(expand_entry(base, reader=SimpleNamespace(fetch=fetch), browser=None,
        allowed_hosts={"example.com"}, record_snapshot=lambda *_: None, state=state))
    await asyncio.wait_for(second_started.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert state["queue"] == [base + "?page=2"]
    assert state["delivered"] == ["https://example.com/jobs/1"]
    assert base in state["visited"]


def test_content_dedup_keeps_query_selectors_and_dynamic_shells_distinct():
    cache = EntryPageCache()
    html = '<a href="/jobs/1">AI产品经理</a>'
    assert not cache.duplicate_content("https://example.com/careers?ref=1", html)
    assert cache.duplicate_content("https://example.com/careers?ref=2", html)
    assert not cache.duplicate_content("https://example.com/careers?city=sh", html.replace("/1", "/2"))
    shell = '<script src="/main.js"></script><div>Loading</div>'
    assert not cache.duplicate_content("https://example.com/careers?city=bj", shell)
    assert not cache.duplicate_content("https://example.com/careers?city=sh", shell)
    # Equal titles/paths on different ATS tenants are not interchangeable.
    relative = '<a href="#/job/1">AI产品经理</a>'
    assert not cache.duplicate_content("https://app.mokahr.com/campus-recruitment/one/1", relative)
    assert not cache.duplicate_content("https://app.mokahr.com/campus-recruitment/two/2", relative)


def test_entry_cursor_persistence_is_scoped_to_goal_version(db_session):
    from src.services.company_search_progress import CompanyProgressStore
    goal = SearchGoalService(db_session).save(user_id="u", input_text=QUERY,
        conditions=SearchGoalConditions.model_validate(search_filter_conditions(QUERY)), condition_sources={})
    store = CompanyProgressStore(db_session, user_id="u", goal_id=goal.id, version=goal.version)
    store.save_entry("https://example.com/careers", {"updated_at": datetime.now(UTC).isoformat(),
                     "cursor": {"queue": ["https://example.com/careers?page=2"]}})
    assert len(store.load_entries()) == 1
    assert not CompanyProgressStore(db_session, user_id="other", goal_id=goal.id, version=goal.version).load_entries()
    assert not CompanyProgressStore(db_session, user_id="u", goal_id=goal.id, version=goal.version + 1).load_entries()


@pytest.mark.asyncio
async def test_entry_no_progress_does_not_block_concrete_jobs_in_pipeline(db_session, monkeypatch):
    from src.domain.discovery import JobLead, LeadProvider
    from src.services import multiround_search
    from src.services.lead_providers import LeadCandidate
    from tests.test_search_bottlenecks import configure_execution

    calls = []
    now = datetime.now(UTC)

    class Provider:
        source_id = "test"

        async def discover(self):
            return [LeadCandidate(provider=LeadProvider.EXTERNAL_AGENT, source_url=url, discovered_at=now)
                    for url in [*[f"https://official.example/careers?channel={i}" for i in range(3)],
                                "https://official.example/jobs/1"]]

    async def fetch(url):
        calls.append(url)
        return FetchedResponse(url, url, 200, "text/html", "<main>暂无职位</main>".encode())

    async def read(url):
        return SimpleNamespace(final_url=url, raw_html="<main>暂无职位</main>")

    async def verify(service, *, user_id, lead_id, **kwargs):
        calls.append("detail")
        return service.verify_stub(user_id=user_id, lead_id=lead_id,
            stub=replace(job(1), detail_url="https://official.example/jobs/1"),
            availability_status=JobAvailabilityStatus.UNKNOWN)

    run = configure_execution(db_session, monkeypatch, lambda *_, **__: Provider(),
        web_search_max_rounds=1, company_discovery_enabled=False)
    monkeypatch.setattr(multiround_search, "SafeHTTPReader", lambda **_: SimpleNamespace(fetch=fetch))
    monkeypatch.setattr(multiround_search, "PlaywrightBrowserJobReader", lambda **_: SimpleNamespace(read=read))
    monkeypatch.setattr(JobLeadService, "verify_url", verify)
    await multiround_search.execute_multiround_search(run_id=run.id, user_id="u", query=QUERY,
                                                     company_ids=[], analysis_limit=0)
    db_session.expire_all()
    assert calls[0] == "detail"
    assert len(calls) == 3
    leads = JobLeadService(db_session).list_leads(user_id="u", discovery_run_id=run.id)
    skipped = [lead for lead in leads if lead.failure_code == "entry_no_progress"]
    assert len(skipped) == 1
    assert db_session.get(JobLead, skipped[0].id).status == "DEFERRED"


def test_saved_entry_resumes_only_after_its_cooldown(db_session):
    from src.domain.discovery import LeadProvider
    from src.services.company_search_progress import CompanyProgressStore
    from src.services.lead_providers import LeadCandidate

    goals = SearchGoalService(db_session)
    goal = goals.save(user_id="u", input_text=QUERY,
        conditions=SearchGoalConditions.model_validate(search_filter_conditions(QUERY)), condition_sources={})
    now = datetime.now(UTC)
    run = DiscoveryRun(id="entry-before", user_id="u", source="test", source_url="https://example.com",
        search_goal_id=goal.id, search_goal_version=goal.version, search_query=QUERY, started_at=now)
    db_session.add(run)
    db_session.commit()
    url = "https://example.com/careers"
    lead = JobLeadService(db_session).capture_candidate(user_id="u", discovery_run_id=run.id,
        candidate=LeadCandidate(provider=LeadProvider.EXTERNAL_AGENT, source_url=url, discovered_at=now))
    lead.status, lead.failure_code = "DEFERRED", "entry_budget"
    db_session.commit()
    store = CompanyProgressStore(db_session, user_id="u", goal_id=goal.id, version=goal.version)
    store.save_entry(url, {"updated_at": now.isoformat(), "next_retry_at": (now + timedelta(seconds=60)).isoformat(),
                          "cursor": {"queue": [url + "?page=2"]}})
    args = {"goal_id": goal.id, "version": goal.version, "current_run_id": "next"}
    assert not goals.resume_candidates("u", **args, now=now)
    assert [c.source_url for c in goals.resume_candidates("u", **args, now=now + timedelta(seconds=61))] == [url]
    lead.selection_status = "IGNORED"
    db_session.commit()
    assert not goals.resume_candidates("u", **args, now=now + timedelta(seconds=61))
