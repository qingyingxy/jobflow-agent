"""Independent search producer and bounded verification consumer."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from time import monotonic

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
):
    queue = VerificationQueue(
        priority=priority, source_key=source_key, is_entry=is_entry
    )
    official_evidence_seen = set()
    seen, useful, known = set(), set(), set()
    round_number = 0
    stop = "达到搜索轮数上限"
    active = 0
    active_reviews = 0
    review_queue = asyncio.Queue()
    queued_reviews = set()
    completed_verifications = 0
    last_decision_verifications = 0
    verification_changed = asyncio.Event()
    pipeline_started = monotonic()
    deadline = pipeline_started + seconds

    def pending_count():
        return queue.qsize() + active + review_queue.qsize() + active_reviews

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
            promoted = (
                candidate.official_entry_url and key not in official_evidence_seen
            )
            if key not in seen or promoted:
                seen.add(key)
                if candidate.official_entry_url:
                    official_evidence_seen.add(key)
                item = replace(candidate, source_url=key)
                queue.put_nowait(item)
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
            try:
                result = await asyncio.wait_for(verify(candidate), item_seconds)
                if isinstance(result, list):
                    enqueue(result)
                elif result:
                    accept_result(result)
                    if review and result[0] not in queued_reviews:
                        queued_reviews.add(result[0])
                        review_queue.put_nowait((result[0], monotonic()))
                        review_queued = True
            except TimeoutError:
                error_code = "verification_timeout"
            except asyncio.CancelledError:
                error_code = "verification_cancelled"
                raise
            except Exception as error:  # noqa: BLE001 - a broken page must not kill discovery
                error_code = type(error).__name__
            finally:
                active -= 1
                if not review_queued:
                    completed_verifications += 1
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

    async def review_worker():
        nonlocal active_reviews, completed_verifications
        while True:
            job_id, queued_at = await review_queue.get()
            active_reviews += 1
            started = monotonic()
            error_code = None
            publish_snapshot()
            try:
                result = await asyncio.wait_for(review(job_id), item_seconds)
                if result:
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
                completed_verifications += 1
                review_queue.task_done()
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
                "正文已核验，方向复核独立进行",
                None,
            )

    consumers = [
        asyncio.create_task(worker()) for _ in range(max(1, min(3, max_concurrency)))
    ]
    review_consumers = (
        [
            asyncio.create_task(review_worker())
            for _ in range(max(1, min(9, review_concurrency)))
        ]
        if review
        else []
    )
    try:
        if bootstrap:
            try:
                await asyncio.wait_for(
                    bootstrap(enqueue), min(45, max(0, deadline - monotonic()))
                )
            except TimeoutError:
                event("direct_search", error_code="direct_search_timeout")
            except Exception as error:  # noqa: BLE001 - preserve normal search fallback
                event("direct_search", error_code=type(error).__name__)
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
            if len(useful) >= target:
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
                while pending_count() > 0 and len(useful) < target:
                    verification_changed.clear()
                    wait = pause_deadline - monotonic()
                    if wait <= 0:
                        break
                    try:
                        await asyncio.wait_for(verification_changed.wait(), wait)
                    except TimeoutError:
                        break
                publish_snapshot()
                if len(useful) >= target:
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
        report(
            round_number, len(seen), len(useful), "搜索已结束，继续处理核验队列", None
        )
        try:

            async def drain():
                await queue.join()
                await review_queue.join()

            await asyncio.wait_for(drain(), verification_seconds)
        except TimeoutError:
            event(
                "queue_budget",
                pending_count=pending_count(),
                error_code="verification_budget_exhausted",
            )
            stop += "；剩余岗位保留待核验"
    finally:
        for consumer in [*consumers, *review_consumers]:
            consumer.cancel()
        await asyncio.gather(*consumers, *review_consumers, return_exceptions=True)
    report(round_number, len(seen), len(useful), "搜索结束", stop)
    return stop
