"""Durable interpretation, fair resume ordering, and identical-source refresh."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from src.config import Settings
from src.domain.application import CandidateJob
from src.domain.discovery import DiscoveryRun, LeadProvider
from src.domain.job import JobAvailabilityStatus
from src.services.discovery_matching import search_filter_conditions
from src.services.job_lead_service import JobLeadService
from src.services.search_goal_service import SearchGoalService, posting_stub
from src.services.source_understanding import (
    PREVIOUS_VERSION,
    SourceUnderstanding,
    checked_decisions,
    fingerprint,
    pending_review_fields,
    queue_review,
    review_attempt,
)
from tests.test_search_goals import add_posting
from tests.test_source_understanding import QUERY, decision, engine, job, paragraphs


def saved(session, identifier, *, age=0):
    posting = add_posting(session, identifier=identifier, age=age)
    original = job(1)
    for field in ("title", "company", "locations", "job_type", "raw_content"):
        setattr(posting, field, getattr(original, field))
    posting.availability_status = "UNKNOWN"
    session.commit()
    return posting


@pytest.mark.asyncio
async def test_cached_deferrals_precede_old_refreshes_and_rotate_without_consuming_retry_budget(db_session):
    goals = SearchGoalService(db_session)
    conditions = search_filter_conditions(QUERY)
    for i in range(8):
        saved(db_session, f"old-{i}", age=9)
    fresh = [saved(db_session, f"deferred-{i}") for i in range(4)]
    runtime = engine([], web_search_semantic_max_calls=0)
    for posting in fresh:
        output = await runtime.review(posting_stub(posting), query=QUERY)
        posting.recruitment_context = output.recruitment_context
    db_session.commit()
    selected = goals.refresh_candidates("owner", query=QUERY, conditions=conditions)
    assert [c.source_url for c in selected] == [p.source_url for p in fresh[:3]]
    first = fresh[0]
    original = posting_stub(first)
    old_queue_time = first.recruitment_context["source_review_attempt"]["queued_at"]
    deferred = await runtime.review(original, query=QUERY)
    assert deferred.recruitment_context["source_review_attempt"]["queued_at"] == old_queue_time
    assert deferred.recruitment_context["source_review_attempt"]["failures"] == 0
    idx = next(i for i, p in enumerate(paragraphs(original.raw_content)) if "2026/2027" in p)
    first.recruitment_context = (await engine([decision("graduation_year", "matched", [idx])]).review(original, query=QUERY)).recruitment_context
    db_session.commit()
    selected = goals.refresh_candidates("owner", query=QUERY, conditions=conditions)
    assert [c.source_url for c in selected] == [p.source_url for p in fresh[1:]]
    # Selection scope and user ownership apply before the small batch limit.
    row = db_session.query(CandidateJob).filter_by(user_id="owner", job_posting_id=fresh[1].id).one()
    row.status = "IGNORED"
    db_session.commit()
    assert fresh[1].source_url not in [c.source_url for c in goals.refresh_candidates("owner", query=QUERY, conditions=conditions)]
    assert not goals.refresh_candidates("other", query=QUERY, conditions=conditions)
    assert not goals.refresh_candidates("owner", query=QUERY, conditions=conditions, company_id="other", source_group=lambda *_: "this")


@pytest.mark.asyncio
async def test_cancellation_checkpoints_before_model_and_resumes_without_changing_source(db_session):
    posting = saved(db_session, "interrupted")
    original = posting_stub(posting)
    verified_at = posting.last_verified_at
    entered = asyncio.Event()

    class Slow:
        async def generate(self, request):
            entered.set()
            await asyncio.Event().wait()

    def checkpoint(updated):
        posting.recruitment_context = updated.recruitment_context
        db_session.commit()

    runtime = SourceUnderstanding(Settings(_env_file=None, web_search_understanding_mode="hybrid"), client=Slow())
    task = asyncio.create_task(runtime.review(original, query=QUERY, on_checkpoint=checkpoint))
    await asyncio.wait_for(entered.wait(), 1)
    assert posting.recruitment_context["source_review_attempt"]["error_code"] == "semantic_pending"
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    db_session.expire_all()
    attempt = posting.recruitment_context["source_review_attempt"]
    assert attempt["error_code"] == "semantic_cancelled" and attempt["failures"] == 0
    assert pending_review_fields(posting_stub(posting), query=QUERY, conditions=search_filter_conditions(QUERY)) == ["graduation_year"]
    assert posting.last_verified_at == verified_at.replace(tzinfo=None)
    assert posting.raw_content == original.raw_content and posting.availability_status == "UNKNOWN"


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", [None, "body", "type", "location"])
async def test_repeat_official_read_keeps_only_reviews_bound_to_unchanged_source(db_session, changed):
    original = replace(job(1), detail_url="https://example.com/jobs/one")
    idx = next(i for i, p in enumerate(paragraphs(original.raw_content)) if "2026/2027" in p)
    reviewed = await engine([decision("graduation_year", "matched", [idx])]).review(original, query=QUERY)
    service = JobLeadService(db_session)

    def save_read(stub, run_id):
        run = DiscoveryRun(id=run_id, user_id="owner", source="test", source_url=stub.detail_url, started_at=datetime.now(UTC))
        db_session.add(run)
        db_session.commit()
        lead = service.create_lead(user_id="owner", provider=LeadProvider.EXTERNAL_AGENT,
                                   discovery_run_id=run_id, source_url=stub.detail_url)
        return service.verify_stub(user_id="owner", lead_id=lead.id, stub=stub,
                                   source_type="verified_browser", availability_status=JobAvailabilityStatus.UNKNOWN).posting

    first = save_read(reviewed, "first")
    incoming = original
    if changed == "body":
        incoming = replace(original, raw_content=original.raw_content + "\n补充要求：仅限2026届。")
    elif changed == "type":
        incoming = replace(original, job_type=None)
    elif changed == "location":
        incoming = replace(original, locations=["北京"])
    second = save_read(incoming, "second")
    assert first.id == second.id
    decisions = checked_decisions(posting_stub(second), search_filter_conditions(QUERY))
    assert bool(decisions) == (changed is None)
    if not changed:
        assert second.recruitment_context["source_review_attempt"] == reviewed.recruitment_context["source_review_attempt"]
    assert second.availability_status == "UNKNOWN"


def test_changed_conditions_do_not_reuse_old_resume_priority(db_session):
    posting = saved(db_session, "changed-goal")
    old = search_filter_conditions(QUERY.replace("2027", "2028"))
    deferred = queue_review(posting_stub(posting), conditions=old, fields=["graduation_year"], error="semantic_budget")
    posting.recruitment_context = deferred.recruitment_context
    new = saved(db_session, "current-goal")
    new.recruitment_context = queue_review(posting_stub(new), conditions=search_filter_conditions(QUERY), fields=["graduation_year"], error="semantic_budget").recruitment_context
    db_session.commit()
    selected = SearchGoalService(db_session).refresh_candidates("owner", query=QUERY, conditions=search_filter_conditions(QUERY), limit=1)
    assert selected[0].source_url == new.source_url


def test_due_failures_resume_but_cooldowns_do_not_take_batch_slots(db_session):
    posting = saved(db_session, "cooldown")
    context = queue_review(posting_stub(posting), conditions=search_filter_conditions(QUERY), fields=["graduation_year"]).recruitment_context
    context["source_review_attempt"].update(error_code="semantic_invalid", failures=1, next_retry_at=(datetime.now(UTC) + timedelta(minutes=5)).isoformat())
    posting.recruitment_context = context
    db_session.commit()
    service = SearchGoalService(db_session)
    assert not service.refresh_candidates("owner", query=QUERY, conditions=search_filter_conditions(QUERY))
    context = {**context, "source_review_attempt": {**context["source_review_attempt"], "next_retry_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat()}}
    posting.recruitment_context = context
    db_session.commit()
    assert service.refresh_candidates("owner", query=QUERY, conditions=search_filter_conditions(QUERY))[0].source_url == posting.source_url


def test_prompt_upgrade_preserves_only_unchanged_unfinished_queue_age():
    original = job(1)
    conditions = search_filter_conditions(QUERY)
    queued = queue_review(original, conditions=conditions, fields=["graduation_year"])
    attempt = queued.recruitment_context["source_review_attempt"]
    attempt["fingerprint"] = fingerprint(original, conditions, version=PREVIOUS_VERSION)
    assert review_attempt(queued, conditions)["queued_at"] == attempt["queued_at"]
    assert review_attempt(queued, conditions)["fingerprint"] == fingerprint(original, conditions)
    assert not review_attempt(replace(queued, raw_content=queued.raw_content + "更新"), conditions)
    attempt["error_code"] = "semantic_invalid"
    assert not review_attempt(queued, conditions)
    attempt["error_code"] = None
    assert not review_attempt(queued, conditions)
