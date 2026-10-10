import asyncio
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from src.domain.discovery import LeadProvider
from src.services.lead_providers import LeadCandidate
from src.services.search_pipeline import run_search_pipeline
from src.services.search_scheduling import (
    VerificationQueue,
    candidate_priority,
    candidate_source,
)


def lead(number, *, host="a.example", title=None, official=None, entry=False):
    return LeadCandidate(
        provider=LeadProvider.EXTERNAL_AGENT,
        source_url=f"https://{host}/{'careers' if entry else 'jobs'}/{number}",
        discovered_at=datetime.now(UTC), title_hint=title,
        official_entry_url=official,
    )


@pytest.mark.parametrize("query,title", [
    ("上海 Agent 校招", "AI Agent 开发工程师"),
    ("上海后端校招", "后端工程师"),
    ("杭州前端实习", "前端开发实习生"),
])
def test_relevant_unconfirmed_detail_precedes_unrelated_official_jobs(query, title):
    relevant = lead(1, host="tenant.jobs.feishu.cn", title=title)
    unrelated = lead(2, title="市场营销", official="https://a.example/careers")
    entry = replace(lead(3), source_url="https://a.example/careers")
    priority = lambda c: candidate_priority(c, query=query, official_hosts={"a.example"})
    assert priority(relevant) < priority(unrelated) < priority(entry)
    assert relevant.official_entry_url is None  # Ordering confers no trust.


def test_explicit_role_exclusion_and_missing_hints_remain_scheduled():
    query = "上海后端校招，不考虑前端"
    wanted, missing, denied = lead(1, title="后端开发"), lead(2), lead(3, title="前端开发")
    priority = lambda c: candidate_priority(c, query=query, official_hosts=set())
    assert priority(wanted) < priority(missing) < priority(denied)
    assert len(sorted([wanted, missing, denied], key=priority)) == 3
    assert candidate_source(lead(1, host="app.mokahr.com")) != candidate_source(
        replace(lead(1), source_url="https://app.mokahr.com/social-recruitment/other/1")
    )


@pytest.mark.asyncio
async def test_source_burst_yields_to_new_company_without_dropping_backlog():
    queue = VerificationQueue(source_key=candidate_source)
    for i in range(9):
        queue.put_nowait(lead(i))
    seen = []
    for _ in range(3):
        item = await queue.get()
        seen.append(item.candidate.source_url)
        queue.task_done(item)
    other = lead(10, host="b.example")
    queue.put_nowait(other)
    item = await queue.get()
    assert item.candidate == other
    queue.task_done(item)
    while queue.qsize():
        item = await queue.get()
        seen.append(item.candidate.source_url)
        queue.task_done(item)
    await asyncio.wait_for(queue.join(), 0.1)
    assert len(seen) == 9


@pytest.mark.asyncio
async def test_queued_promotion_replaces_work_and_preserves_wait_time():
    now = [10.0]
    queue = VerificationQueue(clock=lambda: now[0])
    original = lead(1)
    queue.put_nowait(original)
    now[0] = 20.0
    promoted = replace(original, official_entry_url="https://a.example/careers")
    queue.put_nowait(promoted)
    assert queue.qsize() == 1
    item = await queue.get()
    assert item.candidate == promoted and item.queued_at == 10
    queue.task_done(item)
    await asyncio.wait_for(queue.join(), 0.1)


@pytest.mark.asyncio
async def test_active_url_promotion_does_not_block_other_jobs_or_verify_concurrently():
    queue = VerificationQueue()
    original = lead(1)
    queue.put_nowait(original)
    active = await queue.get()
    promoted = replace(original, official_entry_url="https://a.example/careers")
    queue.put_nowait(promoted)
    queue.put_nowait(lead(2))
    other = await queue.get()
    assert other.candidate.source_url.endswith("/2")
    queue.task_done(other)
    waiting = asyncio.create_task(queue.get())
    await asyncio.sleep(0)
    assert not waiting.done()
    queue.task_done(active)
    item = await asyncio.wait_for(waiting, 0.1)
    assert item.candidate == promoted
    queue.task_done(item)
    await asyncio.wait_for(queue.join(), 0.1)


@pytest.mark.asyncio
async def test_entry_streams_detail_before_finishing_and_reserves_a_worker():
    publish = None
    detail_done = asyncio.Event()
    active_entries = 0
    observed = []

    def ready(enqueue):
        nonlocal publish
        publish = enqueue

    async def search(number, seen):
        return [lead(1, entry=True), lead(2, host="b.example", entry=True)]

    async def verify(candidate):
        nonlocal active_entries
        if "/careers/" in candidate.source_url:
            active_entries += 1
            assert active_entries == 1
            publish([lead(3, official="https://a.example/careers")])
            await asyncio.wait_for(detail_done.wait(), 0.5)
            observed.append("entry")
            active_entries -= 1
            return [lead(3, official="https://a.example/careers")]
        observed.append("detail")
        detail_done.set()
        return candidate.source_url, True

    events = []
    await run_search_pipeline(
        search=search, verify=verify, report=lambda *args: None,
        canonicalize=lambda url: url, max_rounds=1, max_concurrency=2,
        is_entry=lambda c: "/careers/" in c.source_url,
        source_key=candidate_source, on_queue_ready=ready,
        on_event=lambda kind, details: events.append((kind, details)),
        verification_seconds=1,
    )
    assert observed == ["detail", "entry", "entry"]
    completed = [d for k, d in events if k == "verification"]
    assert len(completed) == 3 and all(d["error_code"] is None for d in completed)
    assert all(d["queue_wait_ms"] >= 0 and d["duration_ms"] >= 0 for d in completed)
    assert all(d["started_elapsed_ms"] >= d["enqueued_elapsed_ms"] for d in completed)


@pytest.mark.asyncio
async def test_queue_budget_cancels_entry_and_preserves_pending_counts():
    cancelled = asyncio.Event()
    events, snapshots = [], []

    async def search(number, seen):
        return [lead(1, entry=True), lead(2, entry=True)]

    async def verify(candidate):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    await run_search_pipeline(
        search=search, verify=verify, report=lambda *args: None,
        canonicalize=lambda url: url, max_rounds=1, max_concurrency=2,
        is_entry=lambda _: True, verification_seconds=0.02,
        on_snapshot=snapshots.append,
        on_event=lambda k, d: events.append((k, d)),
    )
    assert cancelled.is_set()
    assert next(d for k, d in events if k == "queue_budget")["pending_count"] == 2
    completed = [d for k, d in events if k == "verification"]
    assert len(completed) == 1 and completed[0]["error_code"] == "verification_cancelled"
    assert snapshots[-1].pending_verification == 1
