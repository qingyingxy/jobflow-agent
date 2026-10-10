import asyncio

import pytest

from src.services.search_pipeline import run_search_pipeline
from tests.test_search_execution import candidate


@pytest.mark.asyncio
async def test_slow_review_does_not_block_next_verified_job_and_finish_waits_for_review():
    release = asyncio.Event()
    local_available = asyncio.Event()
    snapshots = []

    async def search(number, seen):
        return [candidate(1), candidate(2), candidate(3)] if number == 1 else None

    async def verify(lead):
        return lead.source_url, lead.source_url.endswith("/3")

    async def review(job_id):
        await release.wait()
        return job_id, job_id.endswith(("/1", "/3"))

    def snapshot(item):
        snapshots.append(item)
        if item.verified_jobs == 3 and item.useful_jobs == 1:
            local_available.set()

    task = asyncio.create_task(
        run_search_pipeline(
            search=search,
            verify=verify,
            review=review,
            review_concurrency=2,
            report=lambda *args: None,
            canonicalize=lambda url: url,
            on_snapshot=snapshot,
            max_rounds=2,
            target=4,
            seconds=1,
            verification_seconds=1,
        )
    )
    await asyncio.wait_for(local_available.wait(), 1)
    assert snapshots[-1].pending_verification > 0 and not task.done()
    release.set()
    await task
    assert snapshots[-1].useful_jobs == 2 and snapshots[-1].pending_verification == 0
    assert snapshots[-1].completed_verifications == 3


@pytest.mark.asyncio
async def test_budget_cancels_active_reviews_and_preserves_verified_pending_jobs():
    cancelled = asyncio.Event()
    events, snapshots = [], []

    async def search(number, seen):
        return [candidate(1)] if number == 1 else None

    async def verify(lead):
        return lead.source_url, False

    async def review(job_id):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    await run_search_pipeline(
        search=search,
        verify=verify,
        review=review,
        report=lambda *args: None,
        canonicalize=lambda url: url,
        max_rounds=2,
        seconds=1,
        verification_seconds=0.05,
        on_snapshot=snapshots.append,
        on_event=lambda kind, details: events.append((kind, details)),
    )
    assert cancelled.is_set()
    assert snapshots[-1].verified_jobs == 1 and snapshots[-1].useful_jobs == 0
    assert next(d for k, d in events if k == "queue_budget")["pending_count"] == 1
    assert (
        next(d for k, d in events if k == "role_review_queue")["error_code"]
        == "role_review_cancelled"
    )
