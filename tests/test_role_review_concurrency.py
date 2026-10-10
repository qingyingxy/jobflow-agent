import asyncio
import json

import pytest

from src.config import Settings
from src.infrastructure.llm_client import StructuredModelResponse
from src.services.job_role_review import JobRoleReviewer
from tests.test_role_review_batching import jobs, review_jobs


class ControlledClient:
    def __init__(self):
        self.requests = []
        self.active = self.peak = 0
        self.two_started = asyncio.Event()
        self.release = asyncio.Event()

    async def generate(self, request):
        self.requests.append(request)
        self.active += 1
        self.peak = max(self.active, self.peak)
        if self.active == 2:
            self.two_started.set()
        try:
            await self.release.wait()
            data = json.loads(request.messages[-1].content)
            decision = {
                "status": "excluded",
                "reason": "具体职责不属于查询方向",
                "evidence_ids": [0],
            }
            output = (
                {
                    "decisions": [
                        {"job_id": i, **decision} for i in range(len(data["jobs"]))
                    ]
                }
                if "jobs" in data
                else decision
            )
            return StructuredModelResponse(
                output=output, model="controlled", provider="fake"
            )
        finally:
            self.active -= 1


@pytest.mark.asyncio
async def test_two_batches_run_concurrently_and_each_keeps_its_own_evidence(db_session):
    client = ControlledClient()
    reviewer = JobRoleReviewer(
        Settings(_env_file=None, web_search_role_review_concurrency=2), client=client
    )
    task = asyncio.create_task(review_jobs(reviewer, db_session, jobs(6)))
    await asyncio.wait_for(client.two_started.wait(), 1)
    assert reviewer.calls == len(client.requests) == 2
    assert not task.done()
    client.release.set()
    results = await task
    assert all(result["decision"]["status"] == "excluded" for result in results)
    assert reviewer.calls == 3 and client.peak == 2 and client.active == 0
    await reviewer.aclose()
    assert not reviewer._active and not reviewer._waiting


@pytest.mark.asyncio
async def test_cancelling_one_batch_does_not_cancel_the_other(db_session):
    client = ControlledClient()
    reviewer = JobRoleReviewer(
        Settings(_env_file=None, web_search_role_review_concurrency=2), client=client
    )
    inputs = jobs(4)
    tasks = [
        asyncio.create_task(
            reviewer.review(
                j,
                query="上海Agent或RAG校招",
                session=db_session,
                user_id="u",
                lead_id=j.source_job_id,
            )
        )
        for j in inputs
    ]
    await asyncio.wait_for(client.two_started.wait(), 1)
    tasks[0].cancel()
    tasks[1].cancel()
    await asyncio.gather(*tasks[:2], return_exceptions=True)
    client.release.set()
    assert all(await asyncio.gather(*tasks[2:]))
    await reviewer.aclose()
    assert client.active == 0 and reviewer.calls == 2


@pytest.mark.asyncio
async def test_queue_wait_is_not_charged_against_the_next_request_timeout(db_session):
    class Client(ControlledClient):
        async def generate(self, request):
            # Each individual request fits; the second waits longer than the
            # per-request timeout before its own dispatch.
            await asyncio.sleep(0.035)
            self.release.set()
            return await super().generate(request)

    reviewer = JobRoleReviewer(
        Settings(
            _env_file=None,
            web_search_role_review_concurrency=1,
            web_search_role_review_timeout_seconds=0.08,
        ),
        client=Client(),
    )
    assert all(await review_jobs(reviewer, db_session, jobs(8)))
    assert reviewer.calls == 4
    await reviewer.aclose()


@pytest.mark.asyncio
async def test_cancelling_one_job_keeps_its_batch_partner_alive(db_session):
    client = ControlledClient()
    reviewer = JobRoleReviewer(Settings(_env_file=None), client=client)
    tasks = [
        asyncio.create_task(
            reviewer.review(
                job,
                query="上海Agent或RAG校招",
                session=db_session,
                user_id="u",
                lead_id=job.source_job_id,
            )
        )
        for job in jobs(2)
    ]

    async def dispatched():
        while not client.requests:
            await asyncio.sleep(0)

    await asyncio.wait_for(dispatched(), 1)
    tasks[0].cancel()
    await asyncio.gather(tasks[0], return_exceptions=True)
    assert client.active == 1
    client.release.set()
    result = await tasks[1]
    assert result["decision"]["status"] == "excluded" and reviewer.calls == 1
    await reviewer.aclose()
