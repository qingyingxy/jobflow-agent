"""Unfinished job decisions stay responsive while optional upgrades accumulate."""

from datetime import UTC, datetime, timedelta

import pytest

from src import config
from src.domain.job import JobPosting
from src.infrastructure.llm_client import FakeModelClient
from src.services.body_review_queue import (
    review_items,
    review_queue_summary,
    run_body_review_batch,
    select_review_batch,
)
from src.services.search_goal_service import SearchGoalService, posting_stub
from src.services.source_understanding import SourceUnderstanding
from tests.test_body_review_queue import OUTPUT, SETTINGS, setup_queue


def test_qualification_backlog_cannot_take_source_slots_and_idle_slots_are_borrowed(db_session):
    goal, _ = setup_queue(db_session, 30)
    items = [(job, "waiting", {"qualification_only": i >= 8, "failures": 0})
             for i, job in enumerate(SearchGoalService(db_session).postings("owner"))]
    selected = select_review_batch(items, goal)
    assert len(selected) == 6
    assert sum(not row[2].get("qualification_only") for row in selected) == 5
    assert sum(bool(row[2].get("qualification_only")) for row in selected) == 1
    # Cooling source work does not idle the worker or bypass its cooldown.
    cooled = [(j, "cooldown" if not a["qualification_only"] else state, a) for j, state, a in items]
    assert all(row[2]["qualification_only"] for row in select_review_batch(cooled, goal))
    assert len(select_review_batch(cooled, goal)) == 6
    assert len(select_review_batch(items[:2] + items[8:], goal)) == 6
    assert sum(not row[2]["qualification_only"] for row in select_review_batch(items[:2] + items[8:], goal)) == 2


def test_direct_title_retries_precede_incidental_body_mentions_without_starving_oldest(db_session):
    goal, _ = setup_queue(db_session, 10)
    goal.query = "上海 Agent 校招"
    jobs = sorted(SearchGoalService(db_session).postings("owner"), key=lambda j: j.id)
    items = []
    for i, job in enumerate(jobs):
        job.title = "Agent平台研发工程师" if i >= 7 else "基础设施工程师"
        job.raw_content = "上海校园招聘。职责包括Agent相关平台研发。"
        items.append((job, "waiting", {"failures": 1,
            "queued_at": f"2026-10-19T00:{i:02d}:00+00:00", "attempted_at": f"2026-10-19T01:{i:02d}:00+00:00"}))
    chosen = select_review_batch(items, goal)
    assert [row[0] for row in chosen[:3]] == [j.id for j in jobs[7:]]
    assert chosen[-1][0] == jobs[0].id
    # After retrying, a job rotates behind equally relevant waiting peers.
    items[-3][2]["attempted_at"] = "2026-10-19T02:00:00+00:00"
    assert select_review_batch(items, goal)[0][0] == jobs[8].id


@pytest.mark.asyncio
async def test_source_and_qualification_calls_have_independent_budgets_and_schemas(db_session, monkeypatch):
    goal, factory = setup_queue(db_session, 8)
    settings = SETTINGS.model_copy(update={"structured_model_provider": "openai_compatible"})
    monkeypatch.setattr(config, "get_settings", lambda: settings)
    jobs = sorted(SearchGoalService(db_session).postings("owner"), key=lambda j: j.id)
    runtime = SourceUnderstanding(settings, client=FakeModelClient(output=OUTPUT))
    for job in jobs[:2]:
        job.recruitment_context = (await runtime.review(posting_stub(job), query=goal.query,
            conditions=goal.conditions)).recruitment_context
    db_session.commit()
    requests = []

    class Routed:
        async def generate(self, request):
            requests.append(request)
            output = {"qualifications": []} if request.schema_name == "job_qualifications" else OUTPUT
            return await FakeModelClient(output=output).generate(request)

    events = []
    await run_body_review_batch(factory, settings=settings, client=Routed(),
        on_event=lambda name, fields: events.append((name, fields)))
    core = [r for r in requests if r.schema_name == "job_source_understanding"]
    qualification = [r for r in requests if r.schema_name == "job_qualifications"]
    assert len(core) == 5 and len(qualification) == 1
    assert all("qualifications" not in r.json_schema["properties"] and r.max_output_tokens == 1600 for r in core)
    assert "qualifications" in qualification[0].json_schema["properties"]
    assert all('"profile"' not in r.messages[-1].content for r in requests)
    starts = [data for name, data in events if name == "body_review_item" and data["stage"] == "started"]
    assert [row["lane"] for row in starts] == ["source"] * 5 + ["qualifications"]
    db_session.expire_all()
    summary = review_queue_summary(db_session, goal)
    assert summary["lanes"]["source"]["waiting"] == 1
    assert summary["lanes"]["qualifications"]["waiting"] == 6
    assert summary["remaining"] == sum(lane["remaining"] for lane in summary["lanes"].values())
    assert summary["completed"] == 6


@pytest.mark.asyncio
async def test_qualification_cooldown_does_not_delay_ready_sources(db_session, monkeypatch):
    goal, _ = setup_queue(db_session, 8)
    settings = SETTINGS.model_copy(update={"structured_model_provider": "openai_compatible"})
    monkeypatch.setattr(config, "get_settings", lambda: settings)
    job = db_session.get(JobPosting, "body-0")
    runtime = SourceUnderstanding(settings, client=FakeModelClient(output=OUTPUT))
    updated = await runtime.review(posting_stub(job), query=goal.query, conditions=goal.conditions)
    from src.services.qualification_understanding import body_key
    job.recruitment_context = {**updated.recruitment_context, "qualification_review_attempt": {
        "fingerprint": body_key(updated), "failures": 1,
        "next_retry_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat()}}
    db_session.commit()
    items = review_items(db_session, goal)
    assert next(state for j, state, _ in items if j.id == job.id) == "cooldown"
    selected = select_review_batch(items, goal)
    assert len(selected) == 6 and all(not a.get("qualification_only") for _, _, a in selected)
    assert all(identifier != job.id for identifier, _, _ in selected)
