import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from src.config import Settings
from src.infrastructure.llm_client import FakeModelClient
from src.services.search_resources import BoundedReader, ModelCapacity, model_capacity
from src.services.search_run_metrics import SearchRunMetrics
from src.services.source_performance import observation, select_sources, source_score
from src.services.source_understanding import DecisionOutput, SourceUnderstanding


@pytest.mark.asyncio
async def test_slow_interpretation_does_not_hold_http_capacity():
    read = []
    model_started, release = asyncio.Event(), asyncio.Event()

    class Reader:
        async def fetch(self, url):
            read.append(url)
            return url

    reader = BoundedReader(Reader(), limit=1, stage="http", on_event=lambda *_: None)

    async def candidate(url):
        body = await reader.fetch(url)
        if url == "slow":
            model_started.set()
            await release.wait()
        return body

    task = asyncio.create_task(candidate("slow"))
    await model_started.wait()
    assert await asyncio.wait_for(candidate("fast"), .5) == "fast"
    assert read == ["slow", "fast"]
    release.set()
    await task


@pytest.mark.asyncio
async def test_pipeline_drains_fast_page_while_other_candidates_wait_for_interpretation():
    from src.services.search_pipeline import run_search_pipeline
    from tests.test_search_execution import candidate

    waiting, fast_saved, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    active_models = 0

    class Reader:
        async def fetch(self, url):
            return url

    reader = BoundedReader(Reader(), limit=1, stage="http", on_event=lambda *_: None)

    async def search(number, seen):
        return [candidate(i) for i in range(4)] if number == 1 else None

    async def verify(lead):
        nonlocal active_models
        await reader.fetch(lead.source_url)
        if not lead.source_url.endswith("/3"):
            active_models += 1
            if active_models == 3:
                waiting.set()
            await release.wait()
        else:
            fast_saved.set()
        return lead.source_url, True

    task = asyncio.create_task(run_search_pipeline(search=search, verify=verify,
        canonicalize=lambda u: u, report=lambda *_: None, max_concurrency=4,
        seconds=2, max_rounds=2, target=5))
    try:
        await asyncio.wait_for(waiting.wait(), 1)
        await asyncio.wait_for(fast_saved.wait(), .5)
        assert not task.done()
    finally:
        release.set()
        await task


@pytest.mark.asyncio
async def test_browser_and_http_have_independent_limits_and_cancel_releases_slot():
    entered, block = asyncio.Event(), asyncio.Event()

    class Reader:
        async def read(self, url):
            entered.set()
            await block.wait()
            return url

        async def fetch(self, url):
            return url

    events = []
    reader = Reader()
    browser = BoundedReader(reader, limit=1, stage="browser", on_event=lambda *e: events.append(e))
    http = BoundedReader(reader, limit=1, stage="http", on_event=lambda *e: events.append(e))
    task = asyncio.create_task(browser.read("slow"))
    await entered.wait()
    assert await asyncio.wait_for(http.fetch("fast"), .5) == "fast"
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    block.set()
    assert await asyncio.wait_for(browser.read("next"), .5) == "next"
    assert any(d["error_code"] == "CancelledError" for _, d in events)


@pytest.mark.asyncio
async def test_shared_model_limit_prioritizes_search_and_retains_cancelled_capacity():
    capacity = ModelCapacity(1)
    order = []

    async def use(label, priority):
        async with capacity.slot(priority):
            order.append(label)

    async with capacity.slot():
        background = asyncio.create_task(use("background", 2))
        cancelled = asyncio.create_task(use("cancelled", 0))
        fresh = asyncio.create_task(use("fresh", 0))
        await asyncio.sleep(0)
        cancelled.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cancelled
    await asyncio.gather(background, fresh)
    assert order == ["fresh", "background"]
    assert capacity.active == capacity.background_active == 0
    assert not capacity.waiters


@pytest.mark.asyncio
async def test_optional_qualifications_wait_until_foreground_search_finishes():
    capacity = ModelCapacity(2)
    done = asyncio.Event()

    async def qualify():
        async with capacity.slot(3):
            done.set()

    async with capacity.foreground():
        task = asyncio.create_task(qualify())
        await asyncio.sleep(0)
        assert not done.is_set()
        async with capacity.slot(0):
            assert not done.is_set()
    await asyncio.wait_for(task, .5)


@pytest.mark.asyncio
async def test_independent_understanding_instances_share_provider_limit():
    settings = Settings(_env_file=None, web_search_semantic_concurrency=1)
    client = FakeModelClient(output={"decisions": []})
    first = SourceUnderstanding(settings, client=client, include_qualifications=False)
    second = SourceUnderstanding(settings, client=client, include_qualifications=False)
    capacity = model_capacity(settings, client)
    async with capacity.slot():
        tasks = [asyncio.create_task(r.generate(DecisionOutput, {"url": str(i)}, "test",
                    kind="job_source_understanding")) for i, r in enumerate([first, second])]
        await asyncio.sleep(0)
        assert len(capacity.waiters) == 2
        assert not client.requests
    await asyncio.gather(*tasks)
    assert len(client.requests) == 2
    assert all("qualifications" not in r.json_schema["properties"] for r in client.requests)


def test_first_three_counts_current_unique_recommendations_and_separates_cache():
    now = datetime(2026, 10, 22, tzinfo=UTC)
    start = now
    metrics = SearchRunMetrics(start, {"old": {}}, clock=lambda: now)
    metrics.publish("old", True, recommended=True)
    metrics.publish("one", False, recommended=True)
    metrics.publish("one", False, recommended=True)
    metrics.publish("two", False, recommended=False)
    assert metrics.first_three_recommended_ms is None
    now += timedelta(seconds=10)
    metrics.publish("two", True, recommended=True)
    assert metrics.first_three_recommended_ms == 10000
    assert metrics.first_three_new_recommended_ms is None
    metrics.publish("one", False, recommended=False)
    metrics.publish("three", True, recommended=True)
    assert metrics.first_three_new_recommended_ms is None
    now += timedelta(seconds=25)
    metrics.publish("four", True, recommended=True)
    result = metrics.snapshot()
    assert result["first_three_new_recommended_ms"] == 35000
    assert result["result_windows"]["30"]["new_recommended"] == 2
    assert result["result_windows"]["60"]["new_recommended"] == 3
    assert result["first_three_effective_ms"] == 10000


def test_source_selection_keeps_exploration_and_does_not_penalize_unchanged_listing():
    sources = [SimpleNamespace(id=str(i)) for i in range(9)]
    state = {"performance": [observation("direct_search", {
        "source_read_attempted": True, "source_read_success": True,
        "output_count": 0, "read_duration_ms": 4000})]}
    assert source_score(state) > 0
    states = {str(i): state for i in range(4)}
    fair_key = lambda s: (s.id in states, s.id)
    selected = select_sources(sources, states, 6, fair_key)
    assert [s.id for s in selected[:4]] == ["0", "1", "2", "3"]
    assert [s.id for s in selected[4:]] == ["4", "5"]
    # Old successful observations cannot permanently dominate new exploration.
    old = {"performance": [{**state["performance"][0],
            "at": (datetime.now(UTC) - timedelta(days=8)).isoformat()}]}
    assert source_score(old) == 0
    repeated = observation("search_query", {"new_details": 0, "detail_count": 2, "duration_ms": 5000})
    assert repeated["success"]
    assert not observation("search_query", {"detail_count": 0, "duration_ms": 5000})["success"]
    assert observation("search_query", {"new_details": 0, "duplicate_count": 2}) is None


def test_source_history_is_seeded_only_from_same_user_and_goal_version(db_session):
    from src.domain.discovery import DiscoveryRun
    from tests.test_company_coverage import goal_and_store

    goal, store = goal_and_store(db_session)
    store.save("good", {"status": "paused"})
    now = datetime.now(UTC)
    for index, user, version, success in [(0, "owner", 1, True), (1, "stranger", 1, False), (2, "owner", 2, False)]:
        db_session.add(DiscoveryRun(id=f"perf-{index}", user_id=user, source="test", source_url="https://example.com",
            search_goal_id=goal.id, search_goal_version=version, started_at=now, finished_at=now,
            agent_trace=[{"tool": "direct_search", "occurred_at": now.isoformat(), "details": {
                "source_id": "good", "source_read_attempted": True, "source_read_success": success,
                "read_duration_ms": 1000, "output_count": 0}}]))
    db_session.commit()
    state = store.load()["good"]
    assert len(state["performance"]) == 1
    assert source_score(state) > 0


@pytest.mark.parametrize("scope", ["地点不限", "不限地点", "工作地点：不限", "城市不限", "不限届别"])
def test_unrestricted_scope_never_becomes_a_required_keyword(scope):
    from src.services.search_intent import parse_conditions

    result = parse_conditions(f"AI Agent 校招，{scope}")
    assert not result.locations and not result.keywords and not result.pending_conditions
    assert result.roles == ["agent"] and result.job_types == ["校招"]
