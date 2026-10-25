from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import sessionmaker

from src.config import Settings
from src.domain.discovery import DiscoveryRun
from src.domain.search_goal import SearchGoal
from src.services import multiround_search as execution
from src.services import web_search_service
from src.services.company_coverage import CompanyCoverage
from src.services.company_registry import enabled_company_sources
from src.services.company_search_progress import (
    CompanyProgressStore,
    progress_summaries,
)

QUERY = "2027届北京上海 Agent RAG 校招"


@pytest.mark.parametrize("entry,observed,expected", [
    ("https://hr.example.com/campus", None, None),
    ("https://hr.example.com/campus", "/campus/jobs", None),
    ("https://hr.example.com/campus", "http://[invalid", None),
    ("https://hr.example.com/campus", "https://company.jobs.feishu.cn/campus", "company.jobs.feishu.cn"),
    ("https://wecruit.hotjob.cn/SU123/pb/index.html", None, "wecruit.hotjob.cn/SU123/"),
])
def test_fallback_follows_observed_hiring_scope_or_discovers_migrated_entry(db_session, entry, observed, expected):
    from types import SimpleNamespace

    from src.services.company_registry import CompanySource

    _, store = goal_and_store(db_session)
    source = CompanySource("example", "示例科技", "A", entry, "official_career_page")
    coverage = CompanyCoverage(sources=[source], store=store, query=QUERY, batch_size=1)
    state = {"status": "failed", **({"base": observed} if observed else {})}
    task = coverage.next_task(SimpleNamespace(states={source.id: state}))
    assert "agent" in task.query.lower() and source.company in task.query
    assert "2027" not in task.query and "rag" not in task.query.lower()
    if expected is None:
        assert "site:" not in task.query
    else:
        assert f"site:{expected}" in task.query



def goal_and_store(session, company_ids=None):
    goal = SearchGoal(id="coverage-goal", user_id="owner", name="覆盖测试",
                      input_text=QUERY, query=QUERY, conditions={}, condition_sources={},
                      company_ids=company_ids, version=1)
    session.add(goal)
    session.commit()
    return goal, CompanyProgressStore(session, user_id="owner", goal_id=goal.id, version=1)


def mock_runtime(monkeypatch, session, *, fail_company=None, rounds=6):
    settings = Settings(_env_file=None, web_search_direct_sources_enabled=False,
                        web_search_role_review_enabled=False, web_search_max_rounds=rounds,
                        web_search_company_batch_size=6, web_search_transient_retries=0,
                        web_search_budget_seconds=5)
    calls = []

    class Provider:
        source_id, source_url = "test", "https://search.example"

        def __init__(self, query, companies):
            self.query, self.companies = query, companies

        async def discover(self):
            calls.append((self.companies[0], self.query))
            if self.companies[0] == fail_company:
                raise RuntimeError("temporary search failure")
            return []

    monkeypatch.setattr(execution, "get_settings", lambda: settings)
    monkeypatch.setattr(execution, "SessionLocal", sessionmaker(bind=session.bind))
    monkeypatch.setattr(execution, "PlaywrightBrowserJobReader", lambda **_: object())
    monkeypatch.setattr(web_search_service, "create_web_search_provider", Provider)
    return calls


async def run_search(session, goal, number, continuation=None):
    run = DiscoveryRun(id=f"coverage-run-{number}", user_id="owner", source="test",
                       source_url="https://search.example", search_goal_id=goal.id,
                       search_goal_version=goal.version, search_query=goal.query,
                       continued_company_id=continuation, started_at=datetime.now(UTC))
    session.add(run)
    session.commit()
    await execution.execute_multiround_search(
        run_id=run.id, user_id="owner", query=goal.query,
        company_ids=[continuation] if continuation else goal.company_ids,
    )
    session.expire_all()


@pytest.mark.asyncio
async def test_all_registered_companies_rotate_across_runs_and_database_reload(db_session, monkeypatch):
    goal, _ = goal_and_store(db_session)
    calls = mock_runtime(monkeypatch, db_session)
    sources = enabled_company_sources()
    for number in range((len(sources) + 5) // 6):
        await run_search(db_session, goal, number)
    first_pass = [company for company, _ in calls[:len(sources)]]
    assert len(set(first_pass)) == len(sources)
    assert set(first_pass) == {source.id for source in sources}
    summaries = progress_summaries(goal)
    assert all(item["status"] == "paused" for item in summaries)
    assert all(item["can_continue"] and item["strategy"] == "web_search" for item in summaries)
    assert all(item["pages_checked"] == 0 and item["matched_count"] == 0 for item in summaries)


@pytest.mark.asyncio
async def test_small_budget_leaves_unattempted_companies_for_next_run(db_session, monkeypatch):
    goal, _ = goal_and_store(db_session, ["alibaba", "baidu", "meituan"])
    calls = mock_runtime(monkeypatch, db_session, rounds=1, fail_company="alibaba")
    await run_search(db_session, goal, 0)
    statuses = {item["source_id"]: item["status"] for item in progress_summaries(goal)}
    assert statuses == {"alibaba": "failed", "baidu": "not_checked", "meituan": "not_checked"}
    await run_search(db_session, goal, 1)
    await run_search(db_session, goal, 2)
    assert [company for company, _ in calls] == ["alibaba", "baidu", "meituan"]


@pytest.mark.asyncio
async def test_generic_continuation_uses_saved_query_progress_and_only_selected_company(db_session, monkeypatch):
    goal, _ = goal_and_store(db_session, ["alibaba", "baidu"])
    calls = mock_runtime(monkeypatch, db_session)
    await run_search(db_session, goal, 0)
    old_queries = dict(calls)
    calls.clear()
    await run_search(db_session, goal, 1, "alibaba")
    assert len(calls) == 1 and calls[0][0] == "alibaba"
    assert calls[0][1] != old_queries["alibaba"]
    assert "rag" in calls[0][1].lower()
    assert goal.company_search_state["sources"]["alibaba"]["search_cursor"] == 2
    assert goal.company_search_state["sources"]["baidu"]["search_cursor"] == 1


def test_changed_goal_and_other_user_cannot_reuse_old_coverage(db_session):
    goal, store = goal_and_store(db_session, ["alibaba"])
    now = datetime.now(UTC).isoformat()
    store.save("alibaba", {"strategy": "web_search", "status": "paused",
                            "started_at": now, "last_attempt_at": now, "search_cursor": 2})
    stranger = CompanyProgressStore(db_session, user_id="other", goal_id=goal.id, version=1)
    assert stranger.load() == {}
    goal.version = 2
    db_session.commit()
    store.save("baidu", {"status": "running"})
    current = CompanyProgressStore(db_session, user_id="owner", goal_id=goal.id, version=2)
    assert current.load() == {}
    assert progress_summaries(goal)[0]["status"] == "not_checked"


@pytest.mark.parametrize("status,age,resumes", [("paused", 1, True), ("completed", 1, False), ("paused", 8, False)])
def test_direct_cursor_resumes_only_when_incomplete_and_fresh(db_session, status, age, resumes):
    _, store = goal_and_store(db_session, ["bytedance"])
    store.save("bytedance", {"strategy": "official_listing", "status": status,
                            "started_at": (datetime.now(UTC) - timedelta(days=age)).isoformat(),
                            "page_number": 3})
    coverage = CompanyCoverage(sources=enabled_company_sources(["bytedance"]),
                               store=store, query=QUERY, batch_size=6)
    assert bool(coverage.direct_states()) is resumes
    if resumes:
        assert coverage.direct_states()["bytedance"]["page_number"] == 3


def test_generic_continuation_api_does_not_require_direct_listing_feature(db_session, monkeypatch):
    from fastapi.testclient import TestClient

    from src.api import discovery as api
    from src.main import app
    from src.services.url_reader import SafeHTTPReader
    from src.services.web_search_service import BingRSSSearchProvider

    goal, store = goal_and_store(db_session, ["alibaba"])
    coverage = CompanyCoverage(sources=enabled_company_sources(goal.company_ids),
                               store=store, query=QUERY, batch_size=6)
    coverage.start_search("alibaba")
    coverage.finish_search("alibaba", failed=False)
    calls = []
    monkeypatch.setattr(api, "get_settings", lambda: Settings(_env_file=None, web_search_direct_sources_enabled=False))
    monkeypatch.setattr(api, "create_web_search_provider", lambda query, companies:
                        BingRSSSearchProvider(query=query, reader=SafeHTTPReader()))
    monkeypatch.setattr(api, "execute_web_search_in_worker", lambda **kwargs: calls.append(kwargs))
    response = TestClient(app).post(f"/api/discovery/goals/{goal.id}/search",
                                   headers={"X-User-ID": "owner"},
                                   json={"expected_version": 1, "continue_company_id": "alibaba"})
    assert response.status_code == 202, response.text
    assert calls[0]["company_ids"] == ["alibaba"]


@pytest.mark.asyncio
async def test_saved_goal_uses_rotation_even_with_default_web_provider(db_session, monkeypatch):
    goal, _ = goal_and_store(db_session)
    run = DiscoveryRun(id="route-run", user_id="owner", source="test",
                       source_url="https://search.example", search_goal_id=goal.id,
                       search_goal_version=1, started_at=datetime.now(UTC))
    db_session.add(run)
    db_session.commit()
    calls = []

    async def execute(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(web_search_service, "get_settings", lambda: Settings(_env_file=None))
    monkeypatch.setattr(web_search_service, "SessionLocal", sessionmaker(bind=db_session.bind))
    monkeypatch.setattr(execution, "execute_multiround_search", execute)
    await web_search_service.execute_web_search(run_id=run.id, user_id="owner", query=QUERY)
    assert len(calls) == 1 and calls[0]["run_id"] == run.id


@pytest.mark.parametrize("keep_listing", [True, False])
def test_web_fallback_preserves_only_a_listing_used_in_this_run(db_session, keep_listing):
    _, store = goal_and_store(db_session, ["bytedance"])
    store.save("bytedance", {"strategy": "official_listing", "status": "failed",
                            "started_at": datetime.now(UTC).isoformat(), "page_number": 3})
    coverage = CompanyCoverage(sources=enabled_company_sources(["bytedance"]),
                               store=store, query=QUERY, batch_size=6)
    coverage.start_search("bytedance", keep_listing=keep_listing)
    coverage.finish_search("bytedance", failed=False)
    state = store.load()["bytedance"]
    assert state["strategy"] == ("official_listing" if keep_listing else "web_search")
    assert state["status"] == ("failed" if keep_listing else "paused")
