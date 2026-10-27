"""Review saved bodies without fetching websites or borrowing search call quotas."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from time import monotonic
from uuid import uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError

from src import config
from src.domain.application import CandidateJob
from src.domain.discovery import DiscoveryRun, JobLead, LeadVerification
from src.domain.job import JobPosting
from src.domain.search_goal import BodyReviewTask, SearchGoal
from src.domain.source_review_cache import REVIEW_KEYS, merge_context, put_record
from src.infrastructure.database import SessionLocal
from src.services.job_identity import unique_candidates
from src.services.search_goal_service import posting_stub, utc_time
from src.services.source_understanding import (
    PREVIOUS_VERSION,
    VERSION,
    SourceUnderstanding,
    ai_policy_enabled,
    checked_decisions,
    fingerprint,
    pending_review_fields,
    requested_fields,
    review_attempt,
    source_record,
)

logger = logging.getLogger("jobflow.body_review")
BATCH_SIZE = 6


def review_items(session, goal, *, now=None, settings=None):
    from src.services.company_scope import goal_company_sources, in_company_scope

    company_sources = goal_company_sources(session, goal)
    now = now or datetime.now(UTC)
    items = []
    for candidate, job in unique_candidates(session, goal.user_id):
        if not in_company_scope(job, company_sources):
            continue
        from src.services.body_quality import readable_body

        if not readable_body(job.raw_content, title=job.title):
            continue  # Reading defects need transport recovery, not another AI call.
        if candidate.status == "IGNORED" or job.availability_status == "CLOSED":
            continue
        if job.verification_status not in {"VERIFIED_OFFICIAL", "VERIFIED_SOURCE"}:
            continue
        stub = posting_stub(job)
        fields = pending_review_fields(stub, query=goal.query, conditions=goal.conditions,
                                       primary=True, ignore_retry_limits=True)
        if not fields:
            from src.services.qualification_understanding import (
                cached_qualifications,
                qualification_attempt,
            )
            if (not ai_policy_enabled(settings) or cached_qualifications(stub) is not None
                    or any(c["status"] == "excluded" for c in checked_decisions(stub, goal.conditions).values())):
                continue
            attempt = {**qualification_attempt(stub), "qualification_only": True}
        else:
            attempt = {"fingerprint": fingerprint(stub, goal.conditions), **review_attempt(stub, goal.conditions)}
        due = utc_time(attempt.get("next_retry_at"))
        state = "blocked" if attempt.get("failures", 0) >= 3 else "cooldown" if due and due > now else "waiting"
        items.append((job, state, attempt))
    from src.services.job_lead_service import JobLeadService
    from src.services.saved_page_review import page_attempt

    service = JobLeadService(session)
    seen = set()
    leads = list(session.scalars(select(JobLead).join(DiscoveryRun, DiscoveryRun.id == JobLead.discovery_run_id).where(
        JobLead.user_id == goal.user_id, DiscoveryRun.user_id == goal.user_id,
        DiscoveryRun.search_goal_id == goal.id, DiscoveryRun.search_goal_version == goal.version,
        JobLead.selection_status != "IGNORED", JobLead.job_posting_id.is_(None),
        JobLead.status.in_(["DEFERRED", "VERIFYING"]))))
    snapshots = service.pending_page_snapshots(goal.user_id, [lead.normalized_url for lead in leads], now=now)
    for lead in leads:
        if not in_company_scope(lead, company_sources):
            continue
        snapshot = snapshots.get(lead.normalized_url)
        if snapshot is None or lead.normalized_url in seen:
            continue
        seen.add(lead.normalized_url)
        attempt = page_attempt(snapshot, goal.conditions)
        due = utc_time(attempt.get("next_retry_at"))
        if lead.status == "VERIFYING":
            started = (utc_time(attempt.get("attempted_at"))
                       or utc_time(snapshot.field_evidence.get("page_review_attempt", {}).get("attempted_at"))
                       or utc_time(snapshot.checked_at))
            due = max(due or started, started + timedelta(minutes=2))
            attempt = {**attempt, "next_retry_at": due.isoformat()}
        state = "blocked" if attempt.get("failures", 0) >= 3 else "cooldown" if due and due > now else "waiting"
        items.append((lead, state, {**attempt, "snapshot_id": snapshot.id}))
    return items


def review_queue_summary(session, goal):
    items = review_items(session, goal)
    task = session.get(BodyReviewTask, goal.id)
    current = task is not None and task.goal_version == goal.version
    return {"status": task.status if current else "idle", "enabled": ai_policy_enabled(),
            "remaining": len(items),
            **{key: sum(state == key for _, state, _ in items) for key in ("waiting", "cooldown", "blocked")},
            "lanes": {name: {"remaining": sum(bool(a.get("qualification_only")) == qualification for _, _, a in items),
                **{state: sum(s == state and bool(a.get("qualification_only")) == qualification for _, s, a in items)
                   for state in ("waiting", "cooldown", "blocked")}}
                for name, qualification in (("source", False), ("qualifications", True))},
            "processed": task.processed if current else 0, "completed": task.completed if current else 0,
            "error": task.error if current else None}


def enqueue_body_review(session, goal, *, retry_failed=False):
    now = datetime.now(UTC)
    task = session.get(BodyReviewTask, goal.id)
    if retry_failed:
        for job, state, attempt in review_items(session, goal):
            if state == "blocked":
                reset = {**attempt, "failures": 0, "next_retry_at": None}
                if isinstance(job, JobLead):
                    snapshot = session.get(LeadVerification, attempt["snapshot_id"])
                    snapshot.field_evidence = {**snapshot.field_evidence, "page_review_attempt": reset}
                else:
                    key = "qualification_review_attempt" if attempt.get("qualification_only") else "source_review_attempt"
                    job.recruitment_context = (put_record(job.recruitment_context, key, reset)
                        if key == "source_review_attempt" else {**(job.recruitment_context or {}), key: reset})
        session.commit()
    if task and task.goal_version == goal.version and task.status in {"queued", "running"}:
        if task.status == "queued" and any(state == "waiting" for _, state, _ in review_items(session, goal)):
            # Newly saved bodies/prompt upgrades must not inherit an unrelated
            # failed item's long cooldown at the task level.
            task.next_run_at = now
            session.commit()
        return task
    if task is None:
        task = BodyReviewTask(goal_id=goal.id, user_id=goal.user_id)
        session.add(task)
    task.goal_version = goal.version
    task.status = "queued"
    task.processed = task.completed = 0
    task.lease_token = task.lease_until = task.error = None
    task.next_run_at = task.updated_at = now
    try:
        session.commit()
    except IntegrityError:
        session.rollback()  # Another request has already created this goal's task.
    return session.get(BodyReviewTask, goal.id)


def enqueue_run_reviews(run_id, user_id, session_factory=SessionLocal):
    from src.domain.discovery import DiscoveryRun

    if not ai_policy_enabled():
        return
    with session_factory() as session:
        run = session.get(DiscoveryRun, run_id)
        goal = session.get(SearchGoal, run.search_goal_id) if run and run.search_goal_id else None
        if goal and goal.user_id == user_id and goal.version == run.search_goal_version:
            enqueue_body_review(session, goal)


def select_review_batch(items, goal):
    """Prioritize unfinished decisions; qualifications use one or idle slots."""
    from src.services.search_scheduling import listing_priority, title_role_status

    def age(item):
        job, _, attempt = item
        return (attempt.get("queued_at") or attempt.get("attempted_at")
                or str(job.created_at or ""), job.id)

    def priority(item):
        job, _, attempt = item
        title = getattr(job, "title", None) or getattr(job, "title_hint", "") or ""
        text = f"{title}\n{getattr(job, 'raw_content', '')}"
        checks = {}
        previously_completed = False
        if isinstance(job, JobPosting):
            stub = posting_stub(job)
            # Archived semantic facts affect reading order only. They never
            # become current display decisions, and the oldest slot still runs.
            checks = checked_decisions(stub, goal.conditions)
            if not checks:
                checks = checked_decisions(stub, goal.conditions, primary=True, version=PREVIOUS_VERSION)
                previously_completed = bool(checks) and set(requested_fields(goal.conditions)) <= checks.keys()
            # A provisional exclusion in the current policy is unfinished work,
            # not a completed old result waiting for a policy upgrade.
            if source_record(stub, goal.conditions).get("version") == VERSION:
                previously_completed = False
        hard_conflict = any(c["status"] == "excluded" for field, c in checks.items()
                            if field in {"location", "job_type", "graduation_year"})
        return (hard_conflict, previously_completed,
                listing_priority(text, goal.query, goal.conditions.get("job_types", [])),
                title_role_status(title, goal.query) != "matched",
                attempt.get("attempted_at") or "", age(item))

    def take(ready, limit):
        ordered = sorted(ready, key=priority)
        if len(ordered) <= limit:
            return ordered
        oldest = min(ready, key=age)
        retries = [item for item in ordered if item is not oldest and item[2].get("failures", 0) > 0][:2]
        fresh = [item for item in ordered if item is not oldest and not item[2].get("failures", 0)][:1]
        selected = fresh + retries
        selected += [item for item in ordered if item is not oldest and item not in selected][:limit - 1 - len(selected)]
        return sorted(selected, key=priority) + [oldest]

    ready = [item for item in items if item[1] == "waiting"]
    sources = [item for item in ready if not item[2].get("qualification_only")]
    qualifications = [item for item in ready if item[2].get("qualification_only")]
    selected = take(sources, BATCH_SIZE - bool(qualifications))
    # Once runnable source work is exhausted, qualifications can use idle slots.
    selected += sorted(qualifications, key=priority)[:BATCH_SIZE - len(selected)]
    return [(job.id, isinstance(job, JobLead), attempt) for job, _, attempt in selected]


async def run_body_review_batch(session_factory=SessionLocal, *, settings=None, client=None, now=None, goal_id=None, on_event=None):
    settings = settings or config.get_settings()
    if not ai_policy_enabled(settings) and client is None:
        return False
    now = now or datetime.now(UTC)
    on_event = on_event or (lambda *_: None)
    token = uuid4().hex
    with session_factory() as session:
        due = or_(BodyReviewTask.next_run_at.is_(None), BodyReviewTask.next_run_at <= now)
        available = or_(BodyReviewTask.status == "queued",
                        (BodyReviewTask.status == "running") & (BodyReviewTask.lease_until <= now))
        task = session.scalar(select(BodyReviewTask).where(due, available,
                              BodyReviewTask.goal_id == goal_id if goal_id else True)
                              .order_by(BodyReviewTask.updated_at, BodyReviewTask.goal_id).limit(1))
        if task is None:
            return False
        goal_id, version = task.goal_id, task.goal_version
        claimed = session.execute(update(BodyReviewTask).where(
            BodyReviewTask.goal_id == goal_id, BodyReviewTask.goal_version == version, due, available,
        ).values(status="running", lease_token=token, lease_until=now + timedelta(minutes=2), updated_at=now),
            execution_options={"synchronize_session": False}).rowcount
        session.commit()
        if not claimed:
            return False
        session.refresh(task)
        goal = session.get(SearchGoal, goal_id)
        if goal is None or goal.version != version:
            task.status = "superseded"
            session.commit()
            return True
        selected_ids = select_review_batch(review_items(session, goal, now=now, settings=settings), goal)
        from src.services.search_resources import model_capacity

        if model_capacity(settings, client).foreground_runs:
            selected_ids = [item for item in selected_ids if not item[2].get("qualification_only")]
            if not selected_ids:
                task.status, task.next_run_at = "queued", now + timedelta(seconds=30)
                task.lease_token = task.lease_until = None
                session.commit()
                return True
        qualification_count = sum(bool(item[2].get("qualification_only")) for item in selected_ids)
        # Separate call budgets prevent optional qualification extraction from
        # consuming the calls needed to decide unfinished jobs. Source requests
        # ask only for search decisions; qualification work has its own schema.
        runtimes = {qualification: SourceUnderstanding(settings.model_copy(update={
            "web_search_semantic_max_calls": count,
            "web_search_semantic_timeout_seconds": settings.web_search_semantic_retry_timeout_seconds,
        }), client=client, query=goal.query, conditions=goal.conditions,
            include_qualifications=False, background=True, on_event=on_event)
            for qualification, count in ((False, BATCH_SIZE - qualification_count), (True, qualification_count))}
        on_event("body_review_batch", {"goal_id": goal_id, "selected": [
            {"id": item[0], "lane": "qualifications" if item[2].get("qualification_only") else "source",
             "previous_failures": item[2].get("failures", 0)} for item in selected_ids]})
        # Never share a SQLAlchemy session across asynchronous model calls.
        # Bound the entire item, including saved-page recovery and checkpoints.
        session.commit()
        slots = asyncio.Semaphore(settings.web_search_semantic_concurrency)

        async def process(item):
            async with slots:
                started = monotonic()
                lane = "qualifications" if item[2].get("qualification_only") else "source"
                on_event("body_review_item", {"id": item[0], "lane": lane, "stage": "started"})
                try:
                    await review_item(session_factory, runtimes[lane == "qualifications"], goal_id, version, token, item)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("saved_body_item_failed")
                    record_item_failure(session_factory, goal_id, version, token, item)
                finally:
                    on_event("body_review_item", {"id": item[0], "lane": lane, "stage": "finished",
                        "duration_ms": int((monotonic() - started) * 1000)})

        try:
            async with asyncio.TaskGroup() as group:
                for item in selected_ids:
                    group.create_task(process(item))
        except asyncio.CancelledError:
            # A graceful shutdown releases only this worker's claim. A crash
            # still recovers through lease expiry; unfinished bodies are saved.
            session.rollback()
            session.execute(update(BodyReviewTask).where(
                BodyReviewTask.goal_id == goal_id, BodyReviewTask.lease_token == token,
            ).values(status="queued", next_run_at=datetime.now(UTC), lease_token=None, lease_until=None))
            session.commit()
            raise
        except Exception:
            session.rollback()
            task = session.get(BodyReviewTask, goal_id)
            if task and task.lease_token == token:
                task.status, task.error = "failed", "正文复核暂停，请重试；已完成的结果已保存。"
                session.commit()
            logger.exception("saved_body_review_failed")
            return True
        session.expire_all()
        task, goal = session.get(BodyReviewTask, goal_id), session.get(SearchGoal, goal_id)
        if not task or task.lease_token != token:
            return True
        if not goal or goal.version != version:
            task.status = "superseded"
        else:
            remaining = review_items(session, goal, settings=settings)
            ready = any(state == "waiting" for _, state, _ in remaining)
            cooldowns = [utc_time(attempt["next_retry_at"]) for _, state, attempt in remaining if state == "cooldown"]
            task.status = "queued" if ready or cooldowns else "blocked" if remaining else "completed"
            task.next_run_at = datetime.now(UTC) if ready else min(cooldowns) if cooldowns else None
        task.lease_token = task.lease_until = None
        task.updated_at = datetime.now(UTC)
        session.commit()
        return True


async def review_item(session_factory, runtime, goal_id, version, token, item):
    job_id, is_page, attempt = item
    with session_factory() as session:
        goal, task = session.get(SearchGoal, goal_id), session.get(BodyReviewTask, goal_id)
        if not goal or goal.version != version or not task or task.lease_token != token:
            return
        if is_page:
            await review_saved_lead(session, runtime, goal, task, job_id, attempt, token)
            return
        job = session.get(JobPosting, job_id)
        candidate = session.scalar(select(CandidateJob).where(
            CandidateJob.user_id == goal.user_id, CandidateJob.job_posting_id == job_id))
        if not job or not candidate or candidate.status == "IGNORED" or job.availability_status == "CLOSED":
            return
        original = posting_stub(job)
        original_key = fingerprint(original, goal.conditions)
        candidate_id = candidate.id
        query, conditions = goal.query, goal.conditions

        def checkpoint(updated):
            session.expire_all()
            current = session.get(JobPosting, job_id)
            live_goal, active = session.get(SearchGoal, goal_id), session.get(BodyReviewTask, goal_id)
            current_candidate = session.get(CandidateJob, candidate_id)
            if (not active or active.lease_token != token or not live_goal or live_goal.version != version
                    or not current or not current_candidate or current_candidate.status == "IGNORED"
                    or current.availability_status == "CLOSED"
                    or fingerprint(posting_stub(current), live_goal.conditions) != original_key):
                session.rollback()
                return
            current.recruitment_context = merge_context(current.recruitment_context,
                {**(current.recruitment_context or {}),
                 **{key: updated.recruitment_context[key] for key in REVIEW_KEYS if key in updated.recruitment_context}},
                original.recruitment_context)
            active.lease_until = datetime.now(UTC) + timedelta(minutes=2)
            active.updated_at = datetime.now(UTC)
            session.commit()

        if attempt.get("qualification_only"):
            from src.services.qualification_understanding import review_qualifications
            await review_qualifications(runtime, original, on_checkpoint=checkpoint)
        else:
            await runtime.review(original, query=query, conditions=conditions, on_checkpoint=checkpoint)
        session.expire_all()
        task, goal = session.get(BodyReviewTask, goal_id), session.get(SearchGoal, goal_id)
        if not task or task.lease_token != token or not goal or goal.version != version:
            return
        task.processed += 1
        current = session.get(JobPosting, job_id)
        from src.services.qualification_understanding import cached_qualifications
        task.completed += int(bool(current) and fingerprint(posting_stub(current), conditions) == original_key
            and (cached_qualifications(posting_stub(current)) is not None if attempt.get("qualification_only") else
                 not pending_review_fields(posting_stub(current), query=query, conditions=conditions,
                                           primary=True, ignore_retry_limits=True)))
        session.commit()


def record_item_failure(session_factory, goal_id, version, token, item):
    """A bad body gets bounded backoff; it cannot cancel the other saved bodies."""
    job_id, is_page, previous = item
    now = datetime.now(UTC)
    with session_factory() as session:
        goal, task = session.get(SearchGoal, goal_id), session.get(BodyReviewTask, goal_id)
        if not goal or goal.version != version or not task or task.lease_token != token:
            return
        if is_page:
            from src.services.saved_page_review import (
                page_fingerprint,
                save_page_attempt,
            )
            lead = session.get(JobLead, job_id)
            snapshot = session.get(LeadVerification, previous["snapshot_id"])
            if (not lead or lead.selection_status == "IGNORED" or lead.job_posting_id or not snapshot
                    or page_fingerprint(snapshot, goal.conditions) != previous["fingerprint"]):
                return
            # Page extraction may have succeeded before persistence failed.
            # Restore its queue marker and prior failure count, not its body.
            snapshot.field_evidence = {**snapshot.field_evidence, "page_review_attempt": previous}
            save_page_attempt(snapshot, goal.conditions, error="semantic_internal_error")
            lead.status, lead.failure_code = "DEFERRED", "semantic_page_pending"
        else:
            job = session.get(JobPosting, job_id)
            from src.services.qualification_understanding import body_key
            key = body_key(posting_stub(job)) if job and previous.get("qualification_only") else fingerprint(posting_stub(job), goal.conditions) if job else None
            if not job or key != previous["fingerprint"]:
                return
            failures = previous.get("failures", 0) + 1
            attempt_key = "qualification_review_attempt" if previous.get("qualification_only") else "source_review_attempt"
            failed = {
                **previous, "attempted_at": now.isoformat(), "error_code": "semantic_internal_error",
                "failures": failures, "next_retry_at": (now + timedelta(seconds=60 if failures == 1 else 300)).isoformat()}
            job.recruitment_context = (put_record(job.recruitment_context, attempt_key, failed)
                if attempt_key == "source_review_attempt" else {**(job.recruitment_context or {}), attempt_key: failed})
        task.processed += 1
        task.lease_until = now + timedelta(minutes=2)
        session.commit()


async def review_saved_lead(session, runtime, goal, task, lead_id, attempt, token):
    from src.services.company_registry import enabled_company_source_hosts
    from src.services.job_lead_service import JobLeadService, LeadVerificationFailure
    from src.services.saved_page_review import page_fingerprint

    goal_id, version = goal.id, goal.version
    lead = session.get(JobLead, lead_id)
    if not lead or lead.selection_status == "IGNORED" or lead.job_posting_id:
        return
    if lead.status == "VERIFYING":
        # Only expired attempts enter this queue; the task lease owns recovery.
        lead.status = "DEFERRED"
        session.commit()

    def guard():
        session.expire_all()
        current_goal = session.get(SearchGoal, goal_id)
        current_task = session.get(BodyReviewTask, goal_id)
        current_lead = session.get(JobLead, lead_id)
        if not current_goal or not current_task or not current_lead:
            return False
        snapshot = JobLeadService(session)._pending_page_snapshot(current_lead)
        return bool(current_goal and current_goal.version == version and current_task.lease_token == token
            and current_lead.selection_status != "IGNORED" and not current_lead.job_posting_id
            and snapshot and snapshot.id == attempt["snapshot_id"]
            and page_fingerprint(snapshot, current_goal.conditions) == attempt["fingerprint"])

    service = JobLeadService(session, understanding=runtime, review_guard=guard)
    try:
        await service.verify_url(user_id=goal.user_id, lead_id=lead_id, reader=None, saved_only=True,
            official_hosts=enabled_company_source_hosts(session=session, user_id=goal.user_id), official_only=True)
    except LeadVerificationFailure as error:
        if error.code == "semantic_review_superseded":
            return
    session.expire_all()
    active = session.get(BodyReviewTask, goal_id)
    current_goal = session.get(SearchGoal, goal_id)
    if not active or not current_goal or active.lease_token != token or current_goal.version != version:
        return
    active.processed += 1
    active.completed += int(bool(session.get(JobLead, lead_id).job_posting_id))
    active.lease_until = datetime.now(UTC) + timedelta(minutes=2)
    active.updated_at = datetime.now(UTC)
    session.commit()


def resume_stored_body_reviews(session_factory=SessionLocal):
    """Wake prior queues after a policy upgrade, without resetting retry limits."""
    if not ai_policy_enabled():
        return
    with session_factory() as session:
        goals = list(session.scalars(select(SearchGoal).join(BodyReviewTask, BodyReviewTask.goal_id == SearchGoal.id)
            .where(BodyReviewTask.goal_version == SearchGoal.version,
                   BodyReviewTask.status.in_(["completed", "blocked"])) ))
        for goal in goals:
            if any(state == "waiting" for _, state, _ in review_items(session, goal)):
                enqueue_body_review(session, goal)


async def body_review_loop():
    initialized = False
    while True:
        try:
            if not initialized:
                resume_stored_body_reviews()
                initialized = True
            worked = await run_body_review_batch()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - migrations may not yet have run
            logger.warning("body_review_queue_unavailable")
            worked = False
        await asyncio.sleep(1 if worked else 5)
