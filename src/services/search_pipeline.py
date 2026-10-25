"""Independent search producer and bounded verification consumer."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from time import monotonic

from src.services.lead_retry import PAGE_FAILURES, SOURCE_FAILURES, utc_time
from src.services.search_scheduling import VerificationQueue


@dataclass(frozen=True)
class SearchSnapshot:
    verified_jobs: int
    useful_jobs: int
    pending_verification: int
    completed_verifications: int
    remaining_seconds: float


@dataclass(frozen=True)
class WaitForVerification:
    """Pause producing searches, then recheck facts within the search budget."""

    reason: str


@dataclass(frozen=True)
class VerificationFailure:
    """An operational source failure, distinct from an irrelevant/closed job."""

    code: str


async def run_search_pipeline(
    *,
    search,
    verify,
    report,
    canonicalize,
    max_rounds=6,
    seconds=300,
    verification_seconds=180,
    item_seconds=45,
    target=15,
    on_event=None,
    priority=None,
    on_snapshot=None,
    get_stop_reason=None,
    feedback_wait_seconds=0,
    max_concurrency=1,
    source_key=None,
    is_entry=None,
    on_queue_ready=None,
    bootstrap=None,
    review=None,
    review_concurrency=1,
    historical_review=None,
    source_failure_limit=3,
    max_pending=120,
    target_reached=None,
    target_drain_seconds=20,
    on_candidate_done=None,
    bootstrap_seconds=45,
    bootstrap_concurrent=False,
    drain_grace_seconds=None,
    source_retry_states=None,
    on_source_state=None,
    can_verify=None,
    on_candidate_start=None,
    on_bootstrap_done=None,
):
    queue = VerificationQueue(
        priority=priority, source_key=source_key, is_entry=is_entry,
        max_pending=max_pending,
        can_start=can_verify,
    )
    official_evidence_seen = set()
    discovered_candidates = {}
    verified_by_url, reviewing_urls = {}, set()
    seen, useful, known = set(), set(), set()
    round_number = 0
    stop = "达到搜索轮数上限"
    active = 0
    active_reviews = 0
    review_queue = asyncio.Queue()
    history_queue = asyncio.Queue()
    queued_reviews = set()
    completed_verifications = 0
    last_decision_verifications = 0
    verification_changed = asyncio.Event()
    pipeline_started = monotonic()
    deadline = pipeline_started + seconds
    source_states = {key: dict(value) for key, value in (source_retry_states or {}).items()}
    source_failures = {key: value.get("failures", 0) for key, value in source_states.items()}
    queue.probe_sources = {key for key, value in source_states.items() if value.get("next_retry_at")}
    deferred_urls = set()
    terminal_outcomes = {}

    def save_source(source, state):
        if state:
            source_states[source] = state
        else:
            source_states.pop(source, None)
        if on_source_state:
            on_source_state(source, state)

    def enough():
        return target_reached(set(useful)) if target_reached else len(useful) >= target

    def defer(candidate, code):
        deferred_urls.add(candidate.source_url)
        terminal_outcomes[canonicalize(candidate.source_url)] = (None, code)
        source = source_key(candidate) if source_key else None
        due = source_states.get(source, {}).get("next_retry_at") if code == "source_circuit_open" else None
        event("verification_deferred", url=candidate.source_url, error_code=code,
              next_retry_at=due,
              summary="来源暂缓读取，冷却结束后随下一次搜索继续" if due
              else "本轮暂缓核验，链接已保留，将在目标更新时继续处理")
        if on_candidate_done:
            on_candidate_done(candidate, None, code)

    def pending_count():
        return queue.qsize() + active + review_queue.qsize() + history_queue.qsize() + active_reviews

    def accept_result(result):
        job_id, is_useful = result
        known.add(job_id)
        if is_useful:
            useful.add(job_id)
        else:
            useful.discard(job_id)

    def publish_snapshot():
        if on_snapshot:
            on_snapshot(
                SearchSnapshot(
                    verified_jobs=len(known),
                    useful_jobs=len(useful),
                    pending_verification=pending_count(),
                    completed_verifications=completed_verifications,
                    remaining_seconds=max(0, deadline - monotonic()),
                )
            )

    def event(kind, **details):
        if on_event:
            on_event(kind, details)

    def enqueue(candidates):
        for candidate in candidates:
            key = canonicalize(candidate.source_url)
            item = replace(candidate, source_url=key)
            previous = discovered_candidates.get(key)
            if previous:
                preferred = item if priority and priority(item) < priority(previous) else previous
                item = replace(
                    preferred,
                    official_entry_url=previous.official_entry_url or item.official_entry_url,
                )
            discovered_candidates[key] = item
            promoted = (
                item.official_entry_url and key not in official_evidence_seen
            )
            if key in seen and not promoted:
                queue.promote_pending(item)
                if key in terminal_outcomes and on_candidate_done:
                    on_candidate_done(item, *terminal_outcomes[key])
                continue
            if key not in seen or promoted:
                seen.add(key)
                if item.official_entry_url:
                    official_evidence_seen.add(key)
                if key in verified_by_url:
                    if key not in reviewing_urls and on_candidate_done:
                        on_candidate_done(item, verified_by_url[key], None)
                    continue
                terminal_outcomes.pop(key, None)
                source = source_key(item) if source_key else None
                due = utc_time(source_states.get(source, {}).get("next_retry_at"))
                if due and due > datetime.now(UTC):
                    defer(item, "source_circuit_open")
                    continue
                if not queue.put_nowait(item):
                    source = source_key(item) if source_key else None
                    defer(item, "source_circuit_open" if source in queue.deferred_sources
                          else "verification_queue_full")
        publish_snapshot()

    if on_queue_ready:
        on_queue_ready(enqueue)

    async def worker():
        nonlocal active, completed_verifications
        while True:
            item = await queue.get()
            candidate = item.candidate
            active += 1
            started = monotonic()
            timing = {
                "queue_wait_ms": int((started - item.queued_at) * 1000),
                "enqueued_elapsed_ms": int((item.queued_at - pipeline_started) * 1000),
                "started_elapsed_ms": int((started - pipeline_started) * 1000),
                "queue_depth_at_start": queue.qsize(),
                "source_group": item.source,
                "priority": item.priority,
            }
            publish_snapshot()
            error_code = None
            review_queued = False
            result = None
            try:
                # Reserve capacity synchronously before another worker can
                # dispatch a candidate from the same company.
                if on_candidate_start:
                    on_candidate_start(candidate)
                result = await asyncio.wait_for(
                    verify(candidate), min(item_seconds, max(0, deadline - monotonic()))
                )
                if isinstance(result, VerificationFailure):
                    error_code = result.code
                elif isinstance(result, list):
                    enqueue(result)
                elif result:
                    verified_by_url[candidate.source_url] = result
                    queue.discard_url(candidate.source_url)
                    accept_result(result)
                    if review and result[0] not in queued_reviews:
                        queued_reviews.add(result[0])
                        destination = history_queue if historical_review and historical_review(candidate) else review_queue
                        destination.put_nowait((result[0], monotonic(), candidate))
                        reviewing_urls.add(candidate.source_url)
                        review_queued = True
            except TimeoutError:
                error_code = "verification_budget_exhausted" if monotonic() >= deadline else "verification_timeout"
            except asyncio.CancelledError:
                error_code = "verification_cancelled"
                raise
            except Exception as error:  # noqa: BLE001 - a broken page must not kill discovery
                error_code = type(error).__name__
            finally:
                if item.source is not None:
                    if error_code in SOURCE_FAILURES:
                        source_failures[item.source] = source_failures.get(item.source, 0) + 1
                        state = {**source_states.get(item.source, {}), "failures": source_failures[item.source],
                                 "last_failure_code": error_code}
                        if source_failures[item.source] >= source_failure_limit or item.source in queue.probe_sources:
                            blocks = state.get("blocks", 0) + 1
                            state.update(blocks=blocks, next_retry_at=(datetime.now(UTC) + timedelta(
                                seconds=min(1800, 60 * 5 ** min(blocks - 1, 3)))).isoformat())
                            save_source(item.source, state)
                            for waiting in queue.defer_source(item.source):
                                defer(waiting, "source_circuit_open")
                        else:
                            save_source(item.source, state)
                    elif error_code in PAGE_FAILURES or (not error_code and result is not None):
                        source_failures[item.source] = 0
                        queue.probe_sources.discard(item.source)
                        save_source(item.source, {})
                active -= 1
                if not review_queued:
                    completed_verifications += 1
                    terminal_outcomes[candidate.source_url] = (
                        result if isinstance(result, tuple) else None, error_code)
                    if on_candidate_done:
                        on_candidate_done(candidate, result if isinstance(result, tuple) else None, error_code)
                queue.task_done(item)
                event(
                    "verification",
                    url=candidate.source_url,
                    duration_ms=int((monotonic() - started) * 1000),
                    error_code=error_code,
                    **timing,
                )
                publish_snapshot()
                verification_changed.set()
            report(round_number, len(seen), len(useful), "搜索与核验并行进行", None)

    async def review_worker(pending_reviews):
        nonlocal active_reviews, completed_verifications
        while True:
            job_id, queued_at, candidate = await pending_reviews.get()
            active_reviews += 1
            started = monotonic()
            error_code = None
            result = None
            publish_snapshot()
            try:
                result = await asyncio.wait_for(
                    review(job_id), min(item_seconds, max(0, deadline - monotonic()))
                )
                if result:
                    verified_by_url[candidate.source_url] = result
                    accept_result(result)
            except TimeoutError:
                error_code = "role_review_queue_timeout"
            except asyncio.CancelledError:
                error_code = "role_review_cancelled"
                raise
            except Exception as error:  # noqa: BLE001 - keep the public, verified job
                error_code = type(error).__name__
            finally:
                active_reviews -= 1
                reviewing_urls.discard(candidate.source_url)
                completed_verifications += 1
                if on_candidate_done:
                    on_candidate_done(candidate, result, error_code)
                terminal_outcomes[candidate.source_url] = (result, error_code)
                queue.changed.set()
                pending_reviews.task_done()
                queued_reviews.discard(job_id)
                event(
                    "role_review_queue",
                    job_id=job_id,
                    queue_wait_ms=int((started - queued_at) * 1000),
                    duration_ms=int((monotonic() - started) * 1000),
                    error_code=error_code,
                )
                publish_snapshot()
                verification_changed.set()
            report(
                round_number,
                len(seen),
                len(useful),
                "正文已保存，岗位条件理解独立进行",
                None,
            )

    consumers = [
        asyncio.create_task(worker()) for _ in range(max(1, min(24, max_concurrency)))
    ]
    review_consumers = (
        [
            asyncio.create_task(review_worker(review_queue))
            for _ in range(max(1, min(9, review_concurrency)))
        ]
        if review
        else []
    )
    if review and historical_review:
        review_consumers.append(asyncio.create_task(review_worker(history_queue)))
    bootstrap_task = None

    async def produce_initial():
        try:
            await asyncio.wait_for(bootstrap(enqueue), min(bootstrap_seconds, max(0, deadline - monotonic())))
        except TimeoutError:
            event("direct_search", error_code="direct_search_timeout")
        except Exception as error:  # noqa: BLE001 - preserve emitted candidates
            event("direct_search", error_code=type(error).__name__)
        finally:
            if on_bootstrap_done:
                on_bootstrap_done()
            queue.changed.set()

    try:
        if bootstrap:
            if bootstrap_concurrent:
                bootstrap_task = asyncio.create_task(produce_initial())
            else:
                await produce_initial()
        attempted_rounds = 0
        paused_for_round = False
        while attempted_rounds < max_rounds:
            number = attempted_rounds + 1
            round_number = number
            if (
                number > 1
                and feedback_wait_seconds > 0
                and pending_count() > 0
                and completed_verifications == last_decision_verifications
            ):
                verification_changed.clear()
                wait = min(feedback_wait_seconds, max(0, deadline - monotonic()))
                if wait > 0:
                    try:
                        await asyncio.wait_for(verification_changed.wait(), wait)
                    except TimeoutError:
                        pass  # Snapshot still exposes pending work, never a false zero.
            remaining = deadline - monotonic()
            if remaining <= 0:
                stop = "达到搜索时间预算"
                break
            if enough():
                stop = "达到有效岗位目标"
                break
            last_decision_verifications = completed_verifications
            publish_snapshot()
            report(number, len(seen), len(useful), "正在搜索，正文核验独立进行", None)
            try:
                candidates = await asyncio.wait_for(
                    search(number, set(seen)), remaining
                )
            except TimeoutError:
                stop = "达到搜索时间预算"
                break
            except Exception:  # noqa: BLE001 - search records preserve failure details
                attempted_rounds += 1
                paused_for_round = False
                report(number, len(seen), len(useful), "本轮搜索失败，继续下一轮", None)
                continue
            if isinstance(candidates, WaitForVerification):
                # A checkpoint is not a dispatched search and must not consume a
                # round. The caller must advance after this one bounded pause.
                if paused_for_round:
                    stop = "核验反馈后的搜索决策未推进"
                    break
                paused_for_round = True
                pause_seconds = min(
                    15, item_seconds, max(0, deadline - monotonic()) / 2
                )
                pause_deadline = monotonic() + pause_seconds
                event(
                    "search_pause",
                    summary="暂缓新增搜索，等待正文核验反馈后重新判断",
                    reason=candidates.reason,
                    pending_verification=pending_count(),
                    useful_jobs=len(useful),
                    timeout_seconds=pause_seconds,
                )
                while pending_count() > 0 and not enough():
                    verification_changed.clear()
                    wait = pause_deadline - monotonic()
                    if wait <= 0:
                        break
                    try:
                        await asyncio.wait_for(verification_changed.wait(), wait)
                    except TimeoutError:
                        break
                publish_snapshot()
                if enough():
                    stop = "达到有效岗位目标"
                    break
                if monotonic() >= deadline:
                    stop = "达到搜索时间预算"
                    break
                event(
                    "search_resume",
                    summary="核验后有效岗位仍不足，恢复补搜",
                    pending_verification=pending_count(),
                    completed_verifications=completed_verifications,
                    useful_jobs=len(useful),
                )
                # The next decision already receives the latest checkpoint.
                last_decision_verifications = -1
                continue
            if candidates is None:
                stop = (
                    get_stop_reason() if get_stop_reason else None
                ) or "独立查询计划已完成"
                break
            attempted_rounds += 1
            paused_for_round = False
            enqueue(candidates)
        if bootstrap_task and not bootstrap_task.done() and not enough():
            # Exhausting web rounds must not abandon an active official reader.
            await bootstrap_task
        report(round_number, len(seen), len(useful), "搜索已结束，继续处理核验队列", None)
        try:

            async def drain():
                drain_budget = min(verification_seconds, drain_grace_seconds) if drain_grace_seconds is not None else verification_seconds
                drain_deadline = min(deadline, monotonic() + drain_budget)
                target_deadline = None
                while pending_count():
                    verification_changed.clear()
                    if enough() and target_deadline is None:
                        target_deadline = monotonic() + target_drain_seconds
                    remaining = min(drain_deadline, target_deadline or drain_deadline) - monotonic()
                    if remaining <= 0:
                        raise TimeoutError
                    await asyncio.wait_for(verification_changed.wait(), remaining)

            # Draining does not create a second wall-clock budget.
            if pending_count():
                await drain()
        except TimeoutError:
            event(
                "queue_budget",
                pending_count=pending_count(),
                error_code="verification_budget_exhausted",
            )
            stop += "；剩余岗位保留待核验"
    finally:
        if bootstrap_task:
            if not bootstrap_task.done():
                bootstrap_task.cancel()
            await asyncio.gather(bootstrap_task, return_exceptions=True)
        for consumer in [*consumers, *review_consumers]:
            consumer.cancel()
        await asyncio.gather(*consumers, *review_consumers, return_exceptions=True)
    if deferred_urls:
        stop += f"；{len(deferred_urls)}条线索暂缓核验，已保留供下次更新"
    report(round_number, len(seen), len(useful), "搜索结束", stop)
    return stop
