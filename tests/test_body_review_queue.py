import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import sessionmaker

from src.config import Settings
from src.domain.search_goal import BodyReviewTask, SearchGoalConditions
from src.infrastructure.llm_client import FakeModelClient
from src.services.body_review_queue import (
    enqueue_body_review,
    review_queue_summary,
    run_body_review_batch,
)
from src.services.search_goal_service import SearchGoalService, posting_stub
from src.services.source_understanding import checked_decisions, queue_review
from tests.test_search_goals import add_posting

QUERY = "上海校招"
SETTINGS = Settings(_env_file=None, web_search_understanding_mode="ai")
OUTPUT = {"decisions": [
    {"field": field, "status": "matched", "diagnosis": "supported", "reason": "原文明确", "evidence_ids": [0], "basis": "explicit"}
    for field in ("location", "job_type")
]}


def setup_queue(session, count=1):
    goal = SearchGoalService(session).save(user_id="owner", input_text=QUERY,
        conditions=SearchGoalConditions(locations=["上海"], job_types=["校招"]), condition_sources={})
    for i in range(count):
        job = add_posting(session, identifier=f"body-{i}")
        job.raw_content = "工作地点上海，校园招聘。岗位职责：负责Python后端服务和企业业务系统的设计、开发、测试与上线维护。任职要求：本科及以上。"
        session.commit()
    enqueue_body_review(session, goal)
    return goal, sessionmaker(bind=session.bind, expire_on_commit=False)


@pytest.mark.asyncio
async def test_independent_batches_finish_more_than_history_limit_and_survive_new_sessions(db_session):
    goal, factory = setup_queue(db_session, 8)
    client = FakeModelClient(output=OUTPUT)
    await run_body_review_batch(factory, settings=SETTINGS, client=client)
    db_session.expire_all()
    summary = review_queue_summary(db_session, goal)
    assert summary["completed"] == 6 and summary["waiting"] == 2 and summary["status"] == "queued"
    # A new worker instance resumes the same persisted queue, no new search.
    await run_body_review_batch(factory, settings=SETTINGS, client=client)
    db_session.expire_all()
    summary = review_queue_summary(db_session, goal)
    assert summary["completed"] == 8 and summary["remaining"] == 0 and summary["status"] == "completed"
    assert len(client.requests) == 8
    assert not await run_body_review_batch(factory, settings=SETTINGS, client=client)


@pytest.mark.asyncio
async def test_active_lease_prevents_duplicate_model_calls_and_expired_lease_recovers(db_session):
    goal, factory = setup_queue(db_session)
    task = db_session.get(BodyReviewTask, goal.id)
    task.status, task.lease_token = "running", "other-worker"
    task.lease_until = datetime.now(UTC) + timedelta(minutes=2)
    db_session.commit()
    client = FakeModelClient(output=OUTPUT)
    assert not await run_body_review_batch(factory, settings=SETTINGS, client=client)
    assert not client.requests
    task.lease_until = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()
    assert await run_body_review_batch(factory, settings=SETTINGS, client=client)
    assert len(client.requests) == 1


@pytest.mark.asyncio
async def test_cancellation_checkpoints_and_restart_keeps_completed_source_unchanged(db_session):
    goal, factory = setup_queue(db_session)
    entered = asyncio.Event()

    class Slow:
        async def generate(self, request):
            entered.set()
            await asyncio.Event().wait()

    work = asyncio.create_task(run_body_review_batch(factory, settings=SETTINGS, client=Slow()))
    await asyncio.wait_for(entered.wait(), 2)
    work.cancel()
    with pytest.raises(asyncio.CancelledError):
        await work
    db_session.expire_all()
    posting = SearchGoalService(db_session).postings("owner")[0]
    assert posting.recruitment_context["source_review_attempt"]["error_code"] == "semantic_cancelled"
    assert posting.recruitment_context["source_review_attempt"]["failures"] == 0
    task = db_session.get(BodyReviewTask, goal.id)
    task.lease_until = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()
    await run_body_review_batch(factory, settings=SETTINGS, client=FakeModelClient(output=OUTPUT))
    db_session.expire_all()
    assert len(checked_decisions(posting_stub(posting), goal.conditions, primary=True)) == 2


@pytest.mark.asyncio
async def test_changed_source_during_model_call_cannot_receive_old_result(db_session):
    goal, factory = setup_queue(db_session)
    client = FakeModelClient(output=OUTPUT)

    class Changed:
        async def generate(self, request):
            from src.domain.job import JobPosting
            with factory() as other:
                current = other.get(JobPosting, "body-0")
                current.raw_content += "\n当前工作地点改为深圳。"
                other.commit()
            return await client.generate(request)

    await run_body_review_batch(factory, settings=SETTINGS, client=Changed())
    db_session.expire_all()
    posting = SearchGoalService(db_session).postings("owner")[0]
    assert not checked_decisions(posting_stub(posting), goal.conditions, primary=True)
    assert review_queue_summary(db_session, goal)["waiting"] == 1


@pytest.mark.asyncio
async def test_cooldowns_blocked_jobs_and_explicit_retry_do_not_spin(db_session):
    goal, factory = setup_queue(db_session)
    job = SearchGoalService(db_session).postings("owner")[0]
    job.recruitment_context = queue_review(posting_stub(job), conditions=goal.conditions, fields=["location", "job_type"]).recruitment_context
    job.recruitment_context = {**job.recruitment_context, "source_review_attempt": {
        **job.recruitment_context["source_review_attempt"], "failures": 3, "error_code": "semantic_timeout"}}
    db_session.commit()
    client = FakeModelClient(output=OUTPUT)
    await run_body_review_batch(factory, settings=SETTINGS, client=client)
    db_session.expire_all()
    assert review_queue_summary(db_session, goal)["blocked"] == 1
    assert not client.requests
    enqueue_body_review(db_session, goal, retry_failed=True)
    await run_body_review_batch(factory, settings=SETTINGS, client=client)
    db_session.expire_all()
    assert review_queue_summary(db_session, goal)["remaining"] == 0


@pytest.mark.asyncio
async def test_ignored_other_users_and_superseded_goals_are_not_reviewed(db_session):
    from src.domain.application import CandidateJob
    goal, factory = setup_queue(db_session)
    add_posting(db_session, user="someone-else", identifier="private")
    db_session.get(CandidateJob, "candidate-body-0").status = "IGNORED"
    db_session.commit()
    client = FakeModelClient(output=OUTPUT)
    await run_body_review_batch(factory, settings=SETTINGS, client=client)
    assert not client.requests
    enqueue_body_review(db_session, goal)
    goal.version += 1
    db_session.commit()
    await run_body_review_batch(factory, settings=SETTINGS, client=client)
    db_session.expire_all()
    assert db_session.get(BodyReviewTask, goal.id).status == "superseded"
    assert not client.requests


@pytest.mark.asyncio
async def test_bounded_parallel_reviews_save_fast_results_without_waiting_for_slow_one(db_session):
    goal, factory = setup_queue(db_session, 6)
    slow_entered, fast_saved, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    active = peak = calls = 0
    output = FakeModelClient(output=OUTPUT)

    class Parallel:
        async def generate(self, request):
            nonlocal active, peak, calls
            calls += 1
            active += 1
            peak = max(peak, active)
            try:
                if json.loads(request.messages[-1].content)["url"].endswith("body-0"):
                    slow_entered.set()
                    await release.wait()
                else:
                    await slow_entered.wait()
                    # Each next request can see the previous fast result even
                    # while the first model request is still blocked.
                    with factory() as check:
                        if check.get(BodyReviewTask, goal.id).completed:
                            fast_saved.set()
                return await output.generate(request)
            finally:
                active -= 1

    work = asyncio.create_task(run_body_review_batch(factory, settings=SETTINGS, client=Parallel()))
    try:
        await asyncio.wait_for(fast_saved.wait(), 4)
        assert not work.done()
        assert peak == 2
    finally:
        release.set()
        await work
    db_session.expire_all()
    assert calls == 6 and active == 0
    summary = review_queue_summary(db_session, goal)
    assert summary["completed"] == 6 and summary["remaining"] == 0


@pytest.mark.asyncio
async def test_cancellation_stops_all_parallel_calls_and_keeps_queue_resumable(db_session):
    goal, factory = setup_queue(db_session, 6)
    entered = asyncio.Event()
    active = calls = 0

    class Slow:
        async def generate(self, request):
            nonlocal active, calls
            active += 1
            calls += 1
            if active == 2:
                entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                active -= 1

    work = asyncio.create_task(run_body_review_batch(factory, settings=SETTINGS, client=Slow()))
    await asyncio.wait_for(entered.wait(), 4)
    work.cancel()
    with pytest.raises(asyncio.CancelledError):
        await work
    assert active == 0 and calls == 2
    db_session.expire_all()
    assert review_queue_summary(db_session, goal)["waiting"] == 6
    task = db_session.get(BodyReviewTask, goal.id)
    task.lease_until = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()
    await run_body_review_batch(factory, settings=SETTINGS, client=FakeModelClient(output=OUTPUT))
    db_session.expire_all()
    assert review_queue_summary(db_session, goal)["completed"] == 6


def test_priority_reserves_oldest_work_but_prefers_related_duties(db_session):
    from src.services.body_review_queue import select_review_batch
    goal, _ = setup_queue(db_session, 8)
    goal.query = "上海 Agent 校招"
    jobs = SearchGoalService(db_session).postings("owner")
    items = []
    for index, job in enumerate(sorted(jobs, key=lambda job: job.id)):
        job.title = "普通运维" if index < 2 else "Agent研发工程师"
        items.append((job, "waiting", {"queued_at": f"2026-10-19T00:0{index}:00+00:00"}))
    selected = select_review_batch(items, goal)
    ids = [item[0] for item in selected]
    assert len(set(ids)) == 6 and "body-0" in ids and "body-1" not in ids
    assert ids[0] != "body-0"


def test_previous_city_conflict_lowers_priority_without_hiding_or_dropping_work(db_session):
    from src.services.body_review_queue import select_review_batch
    from src.services.source_understanding import PREVIOUS_VERSION, fingerprint
    goal, _ = setup_queue(db_session, 8)
    jobs = sorted(SearchGoalService(db_session).postings("owner"), key=lambda job: job.id)
    items = []
    for index, job in enumerate(jobs):
        if index < 2:
            job.recruitment_context = {"source_understanding": {"version": PREVIOUS_VERSION,
                "policy": "ai", "fingerprint": fingerprint(posting_stub(job), goal.conditions, version=PREVIOUS_VERSION),
                "output": {"decisions": [{**OUTPUT["decisions"][0], "status": "excluded"}]}}}
        items.append((job, "waiting", {"queued_at": f"2026-10-19T00:0{index}:00+00:00"}))
    selected = select_review_batch(items, goal)
    ids = [item[0] for item in selected]
    assert ids[0] == "body-2" and "body-0" in ids and "body-1" not in ids
    assert not checked_decisions(posting_stub(jobs[0]), goal.conditions, primary=True)


def test_unfinished_bodies_precede_policy_upgrade_backlog(db_session):
    from src.services.body_review_queue import select_review_batch
    from src.services.source_understanding import PREVIOUS_VERSION, fingerprint
    goal, _ = setup_queue(db_session, 8)
    jobs = sorted(SearchGoalService(db_session).postings("owner"), key=lambda job: job.id)
    items = []
    for index, job in enumerate(jobs):
        if index < 3:
            job.recruitment_context = {"source_understanding": {"version": PREVIOUS_VERSION,
                "policy": "ai", "fingerprint": fingerprint(posting_stub(job), goal.conditions, version=PREVIOUS_VERSION),
                "output": OUTPUT}}
        items.append((job, "waiting", {"queued_at": f"2026-10-19T00:0{index}:00+00:00"}))
    ids = [item[0] for item in select_review_batch(items, goal)]
    assert ids[:5] == ["body-3", "body-4", "body-5", "body-6", "body-7"]
    assert ids[-1] == "body-0"  # Policy migration also makes progress.


def test_explicit_retry_resets_blocked_item_even_with_task_already_queued(db_session):
    from src.services.body_review_queue import review_items
    goal, _ = setup_queue(db_session)
    job = SearchGoalService(db_session).postings("owner")[0]
    context = queue_review(posting_stub(job), conditions=goal.conditions, fields=["location"]).recruitment_context
    context["source_review_attempt"].update(failures=3, next_retry_at=None)
    job.recruitment_context = context
    db_session.commit()
    enqueue_body_review(db_session, goal, retry_failed=True)
    assert review_items(db_session, goal)[0][1] == "waiting"


def test_startup_wakes_finished_queue_for_new_policy_without_resetting_failures(db_session, monkeypatch):
    from src import config
    from src.services.body_review_queue import resume_stored_body_reviews
    goal, factory = setup_queue(db_session)
    db_session.get(BodyReviewTask, goal.id).status = "completed"
    db_session.commit()
    monkeypatch.setattr(config, "get_settings", lambda: SETTINGS.model_copy(update={"structured_model_provider": "openai_compatible"}))
    resume_stored_body_reviews(factory)
    db_session.expire_all()
    assert db_session.get(BodyReviewTask, goal.id).status == "queued"
