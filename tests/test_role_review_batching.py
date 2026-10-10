"""Batch requests preserve per-job evidence, budgets, cache and failure isolation."""

import asyncio
import json
from dataclasses import replace

import pytest

from src.config import Settings
from src.infrastructure.llm_client import FakeModelClient
from src.services.discovery_matching import classify_discovery_job
from src.services.discovery_sources import JobStub
from src.services.job_role_review import JobRoleReviewer, load_role_review

QUERY = "上海Agent或RAG校招"
DUTIES = [
    "负责工业设备现场调试和可靠性实验，整理故障报告，跟进设备项目的验收与交付，持续完善操作规程。",
    "负责数据库备份恢复、容量治理和故障诊断，维护业务数据的可靠性与稳定性，持续完善值班处理流程。",
]
BASE = JobStub(
    source_id="test",
    source_job_id="0",
    company="示例",
    title="技术工程师",
    locations=["上海"],
    job_type="campus",
    published_at=None,
    detail_url="https://example.com/0",
    raw_content="岗位职责：\n" + DUTIES[0] + "\n任职要求：\n熟悉Python。",
)


def jobs(count=2):
    return [
        replace(
            BASE,
            source_job_id=str(i),
            detail_url=f"https://example.com/{i}",
            raw_content="岗位职责：\n" + DUTIES[i % 2] + "\n任职要求：\n熟悉Python。",
        )
        for i in range(count)
    ]


def decision(index):
    return {
        "job_id": index,
        "status": "excluded",
        "reason": "职责属于其他方向",
        "evidence_ids": [0],
    }


async def review_jobs(reviewer, session, inputs):
    return await asyncio.gather(
        *(
            reviewer.review(
                job,
                query=QUERY,
                session=session,
                user_id="u",
                lead_id=job.source_job_id,
            )
            for job in inputs
        )
    )


@pytest.mark.asyncio
async def test_one_call_independently_binds_two_jobs_and_reuses_each_cache(db_session):
    client = FakeModelClient(output={"decisions": [decision(0), decision(1)]})
    events = []
    reviewer = JobRoleReviewer(
        Settings(_env_file=None, web_search_role_review_max_calls=1),
        client=client,
        on_event=lambda kind, data: events.append((kind, data)),
    )
    inputs = jobs()
    reviews = await review_jobs(reviewer, db_session, inputs)
    assert reviewer.calls == len(client.requests) == 1
    assert client.requests[0].schema_name == "job_role_review_batch"
    payload = json.loads(client.requests[0].messages[-1].content)
    assert len(payload["jobs"]) == 2
    for i, (job, review) in enumerate(zip(inputs, reviews, strict=True)):
        assert review["decision"]["evidence"] == [DUTIES[i].rstrip("。")]
        assert (
            classify_discovery_job(job, query=QUERY, role_review=review).filter_status
            == "excluded"
        )
        assert load_role_review(db_session, user_id="u", job=job, query=QUERY) == review
        assert (
            load_role_review(db_session, user_id="other", job=job, query=QUERY) is None
        )
    assert await review_jobs(reviewer, db_session, inputs) == reviews
    assert len(client.requests) == 1
    assert sum(kind == "role_review_batch" for kind, _ in events) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_item",
    [None, {**decision(1), "evidence_ids": [8]}, {**decision(1), "status": "unknown"}],
)
async def test_missing_or_invalid_item_cannot_contaminate_other_job(
    db_session, bad_item
):
    client = FakeModelClient(
        output={"decisions": [decision(0), *([bad_item] if bad_item else [])]}
    )
    reviewer = JobRoleReviewer(Settings(_env_file=None), client=client)
    inputs = jobs()
    reviews = await review_jobs(reviewer, db_session, inputs)
    assert reviews[0]["decision"]["status"] == "excluded"
    assert reviews[1] is None
    assert (
        classify_discovery_job(
            inputs[1], query=QUERY, role_review=reviews[1]
        ).filter_status
        == "pending"
    )
    assert len(client.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "output",
    [
        {"decisions": [decision(9)]},
        {"decisions": [{**decision(0), "job_id": True}]},
        {"status": "excluded"},
    ],
)
async def test_unknown_job_namespace_cannot_produce_an_exclusion(db_session, output):
    reviewer = JobRoleReviewer(
        Settings(_env_file=None), client=FakeModelClient(output=output)
    )
    assert await review_jobs(reviewer, db_session, jobs()) == [None, None]
    assert reviewer.calls == 1


@pytest.mark.asyncio
async def test_four_concurrent_reviews_do_not_exceed_one_call_budget(db_session):
    client = FakeModelClient(output={"decisions": [decision(0), decision(1)]})
    reviewer = JobRoleReviewer(
        Settings(_env_file=None, web_search_role_review_max_calls=1), client=client
    )
    reviews = await review_jobs(reviewer, db_session, jobs(4))
    assert reviewer.calls == len(client.requests) == 1
    assert sum(review is not None for review in reviews) == 2


@pytest.mark.asyncio
async def test_timeout_cancels_batch_request_without_exclusion_or_background_retry(
    db_session,
):
    started, cancelled = [], []

    class Slow:
        async def generate(self, request):
            started.append(request)
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.append(True)

    reviewer = JobRoleReviewer(
        Settings(
            _env_file=None,
            web_search_role_review_timeout_seconds=0.04,
            web_search_role_review_max_calls=1,
        ),
        client=Slow(),
    )
    assert await review_jobs(reviewer, db_session, jobs()) == [None, None]
    await asyncio.sleep(0)
    assert len(started) == len(cancelled) == reviewer.calls == 1
    assert not reviewer._waiting and not reviewer._active


@pytest.mark.asyncio
async def test_setting_batch_size_one_preserves_single_job_schema(db_session):
    client = FakeModelClient(
        output={k: v for k, v in decision(0).items() if k != "job_id"}
    )
    reviewer = JobRoleReviewer(
        Settings(_env_file=None, web_search_role_review_batch_size=1), client=client
    )
    assert all(await review_jobs(reviewer, db_session, jobs()))
    assert len(client.requests) == reviewer.calls == 2
    assert all(r.schema_name == "job_role_review" for r in client.requests)


@pytest.mark.asyncio
async def test_different_queries_are_not_combined(db_session):
    output = {k: v for k, v in decision(0).items() if k != "job_id"}
    client = FakeModelClient(output=output)
    reviewer = JobRoleReviewer(Settings(_env_file=None), client=client)
    reviews = await asyncio.gather(
        *(
            reviewer.review(
                job,
                query=query,
                session=db_session,
                user_id="u",
                lead_id=job.source_job_id,
            )
            for job, query in zip(jobs(), ["上海Agent校招", "上海RAG校招"], strict=True)
        )
    )
    assert all(reviews)
    assert len(client.requests) == 2
    assert all(r.schema_name == "job_role_review" for r in client.requests)
