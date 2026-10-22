import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import sessionmaker

from src.domain.discovery import DiscoveryRun, LeadProvider
from src.domain.search_goal import SearchGoal
from src.services.company_search_progress import CompanyProgressStore
from src.services.job_lead_service import JobLeadService, LeadVerificationFailure
from src.services.lead_providers import LeadCandidate
from src.services.lead_retry import can_retry, failed_state, lead_state, utc_time
from src.services.search_goal_service import SearchGoalService
from src.services.search_pipeline import VerificationFailure, run_search_pipeline
from src.services.url_reader import URLFetchError


def run(session, identifier, *, owner="owner", version=1):
    row = DiscoveryRun(id=identifier, user_id=owner, source="test", source_url="https://test.example",
        search_goal_id="goal", search_goal_version=version, started_at=datetime.now(UTC))
    session.add(row)
    session.commit()
    return row


def candidate(number, host="test.example"):
    return LeadCandidate(provider=LeadProvider.EXTERNAL_AGENT,
        source_url=f"https://{host}/jobs/{number}", discovered_at=datetime.now(UTC),
        title_hint="RAG工程师", source_id=host)


@pytest.mark.asyncio
async def test_transient_retry_survives_new_runs_and_stops_after_two_retries(db_session):
    class Reader:
        async def fetch(self, url):
            raise URLFetchError("502", code="source_server_error", status_code=502)

    service = JobLeadService(db_session)
    queue_time = None
    for attempt in range(1, 4):
        current = run(db_session, str(attempt))
        lead = service.capture_candidate(user_id="owner", discovery_run_id=current.id, candidate=candidate(1))
        if attempt > 1:
            assert lead.retry_state["attempts"] == attempt - 1
            assert lead.retry_state["queued_at"] == queue_time
        with pytest.raises(LeadVerificationFailure):
            await service.verify_url(user_id="owner", lead_id=lead.id, reader=Reader(), official_hosts=set())
        db_session.expire_all()
        state = lead.retry_state
        queue_time = state["queued_at"]
        assert state["attempts"] == state["transient_failures"] == attempt
        assert state["methods"] == ["http"]
        assert not can_retry(state)
        if attempt < 3:
            due = utc_time(state["next_retry_at"])
            assert can_retry(state, now=due)
            assert not can_retry(state, now=due - timedelta(seconds=1))
            assert (due - utc_time(state["last_failure_at"])).total_seconds() == (60 if attempt == 1 else 300)
        else:
            assert state["mode"] == "exhausted" and state["next_retry_at"] is None
            assert not can_retry(state, now=datetime.now(UTC) + timedelta(days=20))


@pytest.mark.parametrize("code", ["verification_budget_exhausted", "verification_cancelled",
                                    "source_circuit_open", "verification_queue_full", "company_paused"])
def test_deferral_keeps_queue_position_and_does_not_consume_retry(code):
    initial = {"queued_at": "2026-10-01T00:00:00+00:00", "attempts": 2,
               "transient_failures": 1, "methods": ["http", "browser"], "next_method": "browser"}
    state = failed_state(initial, code)
    assert all(state[k] == v for k, v in initial.items())
    assert can_retry(state)


@pytest.mark.parametrize("code,mode", [
    ("browser_job_page_unverified", "needs_adapter"), ("visual_extraction_unverified", "needs_adapter"),
    ("browser_captcha_required", "manual"), ("official_source_unconfirmed", "manual"),
    ("job_closed", "stopped"), ("source_not_found", "stopped"), ("lead_not_job_page", "stopped"),
])
def test_permanent_or_manual_cases_do_not_loop(code, mode):
    state = failed_state({}, code)
    assert state["mode"] == mode and not can_retry(state)


def test_body_scope_failure_only_switches_to_browser_once():
    state = failed_state({"next_method": "http"}, "job_detail_unconfirmed")
    assert can_retry(state) and state["next_method"] == "browser"
    state = failed_state(state, "job_detail_unconfirmed")
    assert state["mode"] == "needs_adapter" and not can_retry(state)


@pytest.mark.parametrize("status,code,mode", [
    (404, "source_not_found", "stopped"), (410, "source_not_found", "stopped"),
    (429, "source_rate_limited", "cooldown"), (403, "source_forbidden", "manual"),
])
@pytest.mark.asyncio
async def test_http_status_has_specific_recovery(db_session, status, code, mode):
    class Reader:
        async def fetch(self, url):
            raise URLFetchError("unavailable", code="source_http_error", status_code=status)
    lead = JobLeadService(db_session).capture_candidate(user_id="owner", candidate=candidate(1))
    with pytest.raises(LeadVerificationFailure) as failure:
        await JobLeadService(db_session).verify_url(user_id="owner", lead_id=lead.id,
            reader=Reader(), official_hosts=set())
    assert failure.value.code == code
    assert lead.retry_state["mode"] == mode


def test_company_selection_precedes_limit_and_respects_scope_and_cooldown(db_session):
    old = run(db_session, "old")
    service = JobLeadService(db_session)
    for i in range(20):
        service.capture_candidate(user_id="owner", discovery_run_id=old.id, candidate=candidate(i, "other.example"))
    target = service.capture_candidate(user_id="owner", discovery_run_id=old.id, candidate=candidate(99))
    cooling = service.capture_candidate(user_id="owner", discovery_run_id=old.id, candidate=candidate(100))
    cooling.retry_state = failed_state({}, "source_server_error")
    db_session.commit()
    for identifier, owner, version in [("foreign", "foreign", 1), ("edited", "owner", 2)]:
        row = run(db_session, identifier, owner=owner, version=version)
        service.capture_candidate(user_id=owner, discovery_run_id=row.id, candidate=candidate(101))
    resumed = SearchGoalService(db_session).resume_candidates("owner", goal_id="goal", version=1,
        current_run_id="current", company_id="test.example", limit=1)
    assert [c.source_url for c in resumed] == [target.source_url]
    target.selection_status = "IGNORED"
    db_session.commit()
    assert not SearchGoalService(db_session).resume_candidates("owner", goal_id="goal", version=1,
        current_run_id="current", company_id="test.example")


def test_retry_state_is_private_and_goal_version_scoped(db_session):
    old = run(db_session, "old")
    service = JobLeadService(db_session)
    lead = service.capture_candidate(user_id="owner", discovery_run_id=old.id, candidate=candidate(1))
    lead.retry_state = failed_state({}, "browser_captcha_required")
    db_session.commit()
    for identifier, owner, version in [("foreign", "foreign", 1), ("edited", "owner", 2)]:
        row = run(db_session, identifier, owner=owner, version=version)
        new = service.capture_candidate(user_id=owner, discovery_run_id=row.id, candidate=candidate(1))
        assert not new.retry_state


@pytest.mark.parametrize("code", ["browser_job_page_unverified", "job_detail_unconfirmed",
                                    "source_not_found", "visual_extraction_unverified"])
@pytest.mark.asyncio
async def test_single_page_failures_do_not_suspend_other_jobs_on_source(code):
    attempted, deferred = [], []
    async def search(*_):
        return [candidate(i) for i in range(7)]
    async def verify(item):
        attempted.append(item.source_url)
        return VerificationFailure(code) if len(attempted) <= 5 else (item.source_url, True)
    await run_search_pipeline(search=search, verify=verify, report=lambda *_: None,
        canonicalize=lambda u: u, max_rounds=1, seconds=2, source_key=lambda _: "source",
        on_event=lambda k, d: deferred.append(d) if k == "verification_deferred" else None)
    assert len(attempted) == 7 and not deferred


@pytest.mark.asyncio
async def test_source_cooldown_persists_and_allows_only_one_recovery_probe(db_session):
    db_session.add(SearchGoal(id="goal", user_id="owner", version=1, name="test",
        input_text="RAG", query="RAG", conditions={}, condition_sources={}))
    db_session.commit()
    store = CompanyProgressStore(db_session, user_id="owner", goal_id="goal", version=1)
    attempted = []
    async def search(*_):
        return [candidate(i) for i in range(8)]
    async def broken(item):
        attempted.append(item.source_url)
        await asyncio.sleep(.005)
        return VerificationFailure("source_server_error")
    async def execute(verify, states, concurrency=1):
        return await run_search_pipeline(search=search, verify=verify, report=lambda *_: None,
            canonicalize=lambda u: u, max_rounds=1, seconds=2, source_key=lambda _: "source",
            max_concurrency=concurrency, source_retry_states=states, on_source_state=store.save_verification)
    await execute(broken, {})
    assert len(attempted) == 3
    store.save("company", {"status": "paused", "buffer": [1, 2]})
    with sessionmaker(bind=db_session.bind)() as fresh:
        restored = CompanyProgressStore(fresh, user_id="owner", goal_id="goal", version=1).load_verification()
    assert restored["source"]["failures"] == 3
    attempted.clear()
    await execute(broken, restored)
    assert not attempted  # A later search must respect the persisted cooldown.
    restored["source"]["next_retry_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    await execute(broken, restored, concurrency=3)
    assert len(attempted) == 1
    attempted.clear()
    recovered = store.load_verification()
    recovered["source"]["next_retry_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    async def healthy(item):
        attempted.append(item.source_url)
        await asyncio.sleep(.005)
        return item.source_url, True
    await execute(healthy, recovered, concurrency=3)
    assert len(attempted) == 8 and not store.load_verification()
    assert store.load()["company"]["buffer"] == [1, 2]


@pytest.mark.asyncio
async def test_budget_expiry_is_not_a_source_failure():
    outcomes, checkpoints = [], []
    async def search(*_):
        return [candidate(1)]
    async def verify(_):
        await asyncio.Event().wait()
    await run_search_pipeline(search=search, verify=verify, report=lambda *_: None,
        canonicalize=lambda u: u, max_rounds=1, seconds=.03, item_seconds=1,
        source_key=lambda _: "source", on_source_state=lambda *args: checkpoints.append(args),
        on_candidate_done=lambda c, r, e: outcomes.append(e))
    assert outcomes[0] in {"verification_cancelled", "verification_budget_exhausted"}
    assert not checkpoints


@pytest.mark.asyncio
@pytest.mark.parametrize("blocked", [False, True])
@pytest.mark.parametrize("source_cooling", [False, True])
async def test_rediscovery_reuses_browser_path_or_honors_manual_stop(db_session, monkeypatch, blocked, source_cooling):
    from src.config import Settings
    from src.services import multiround_search as execution
    from src.services import web_search_service
    from src.services.search_planner import SearchTask
    from tests.test_discovery_filtering import BASE, QUERY

    if source_cooling:
        db_session.add(SearchGoal(id="goal", user_id="owner", version=1, name="test",
            input_text="RAG", query="RAG", conditions={}, condition_sources={}))
        db_session.commit()
        CompanyProgressStore(db_session, user_id="owner", goal_id="goal", version=1).save_verification(
            "example.com", {"failures": 3, "next_retry_at": (datetime.now(UTC) + timedelta(minutes=1)).isoformat()})
    old = run(db_session, "old")
    item = candidate(1, "example.com")
    lead = JobLeadService(db_session).capture_candidate(user_id="owner", discovery_run_id=old.id, candidate=item)
    lead.status = "NEEDS_USER" if blocked else "NEEDS_BROWSER"
    lead.failure_code = "browser_captcha_required" if blocked else "lead_requires_browser"
    lead.retry_state = failed_state({}, lead.failure_code)
    db_session.commit()
    current = run(db_session, "current")
    current.search_query = QUERY
    db_session.commit()
    calls = []
    class Provider:
        source_id = "fixture"
        async def discover(self):
            return [item]
    async def http(*args, **kwargs):
        pytest.fail("Do not repeat the known static-page failure")
    async def browser(service, *, user_id, lead_id, **kwargs):
        calls.append("browser")
        return service.verify_stub(user_id=user_id, lead_id=lead_id, stub=BASE)
    settings = Settings(_env_file=None, web_search_max_rounds=1, web_search_budget_seconds=2,
        web_search_direct_sources_enabled=False)
    monkeypatch.setattr(execution, "get_settings", lambda: settings)
    monkeypatch.setattr(execution, "SessionLocal", sessionmaker(bind=db_session.bind))
    monkeypatch.setattr(execution, "enabled_company_sources", lambda *_, **__: [])
    monkeypatch.setattr(execution, "enabled_company_source_hosts", lambda **_: {"example.com"})
    monkeypatch.setattr(web_search_service, "create_web_search_provider", lambda *args: Provider())
    monkeypatch.setattr(JobLeadService, "verify_url", http)
    monkeypatch.setattr(JobLeadService, "verify_browser", browser)
    await execution.execute_multiround_search(run_id=current.id, user_id="owner", query=QUERY,
        company_ids=[], query_tasks=[SearchTask(QUERY, "test")])
    assert calls == ([] if blocked or source_cooling else ["browser"])
    db_session.expire_all()
    leads = JobLeadService(db_session).list_leads(user_id="owner", discovery_run_id=current.id)
    assert len(leads) == 1
    assert bool(leads[0].job_posting_id) == (not blocked and not source_cooling)
    metrics = db_session.get(DiscoveryRun, current.id).usage_metrics
    assert metrics["read_attempts"] == metrics["retry_attempts"] == int(not blocked and not source_cooling)
    assert metrics["retry_recovered"] == int(not blocked and not source_cooling)
    if blocked:
        assert lead_state(leads[0])["mode"] == "manual"
    elif source_cooling:
        assert lead_state(leads[0])["mode"] == "cooldown"
        assert not can_retry(lead_state(leads[0]))


def test_retry_migration_preserves_existing_rows(db_session):
    import importlib

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, text

    migration = importlib.import_module("migrations.versions.0029_lead_retry_state")
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE job_leads (id TEXT PRIMARY KEY, failure_code TEXT)"))
        connection.execute(text("INSERT INTO job_leads VALUES ('old', 'browser_timeout')"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            assert connection.execute(text("SELECT retry_state FROM job_leads")).scalar_one() == "{}"
            migration.downgrade()
        assert connection.execute(text("SELECT failure_code FROM job_leads")).scalar_one() == "browser_timeout"


@pytest.mark.asyncio
@pytest.mark.parametrize("budget_expires", [False, True])
async def test_worker_persists_item_timeout_but_does_not_charge_budget_expiry(db_session, monkeypatch, budget_expires):
    from src.config import Settings
    from src.services import multiround_search as execution
    from src.services import web_search_service
    from src.services.search_planner import SearchTask

    current = run(db_session, "timeout")
    item = candidate(1)
    class Provider:
        source_id = "fixture"
        async def discover(self):
            return [item]
    class Reader:
        async def fetch(self, url):
            await asyncio.Event().wait()
    settings = Settings(_env_file=None, web_search_max_rounds=1,
        web_search_budget_seconds=1 if budget_expires else 3,
        web_search_verification_budget_seconds=3, web_search_verification_item_seconds=1,
        web_search_direct_sources_enabled=False)
    monkeypatch.setattr(execution, "get_settings", lambda: settings)
    monkeypatch.setattr(execution, "SessionLocal", sessionmaker(bind=db_session.bind))
    monkeypatch.setattr(execution, "enabled_company_sources", lambda *_, **__: [])
    monkeypatch.setattr(execution, "enabled_company_source_hosts", lambda **_: {"test.example"})
    monkeypatch.setattr(execution, "SafeHTTPReader", lambda **_: Reader())
    monkeypatch.setattr(web_search_service, "create_web_search_provider", lambda *args: Provider())
    await execution.execute_multiround_search(run_id=current.id, user_id="owner", query="RAG",
        company_ids=[], query_tasks=[SearchTask("RAG", "test")])
    db_session.expire_all()
    lead = JobLeadService(db_session).list_leads(user_id="owner", discovery_run_id=current.id)[0]
    assert lead.retry_state["attempts"] == 1 and lead.retry_state["methods"] == ["http"]
    assert lead.retry_state.get("transient_failures", 0) == int(not budget_expires)
    assert lead.failure_code == ("verification_budget_exhausted" if budget_expires else "verification_timeout")
    assert can_retry(lead_state(lead)) is budget_expires
    assert db_session.get(DiscoveryRun, current.id).usage_metrics["read_successes"] == 0
