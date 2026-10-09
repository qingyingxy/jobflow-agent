"""Independent search producer and bounded verification consumer."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from itertools import count
from time import monotonic


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
):
    queue = asyncio.PriorityQueue()
    sequence = count()
    official_evidence_seen = set()
    seen, useful, known = set(), set(), set()
    round_number = 0
    stop = "达到搜索轮数上限"
    active = 0
    completed_verifications = 0
    last_decision_verifications = 0
    verification_changed = asyncio.Event()
    verification_locks = {}
    deadline = monotonic() + seconds

    def publish_snapshot():
        if on_snapshot:
            on_snapshot(SearchSnapshot(
                verified_jobs=len(known),
                useful_jobs=len(useful),
                pending_verification=queue.qsize() + active,
                completed_verifications=completed_verifications,
                remaining_seconds=max(0, deadline - monotonic()),
            ))

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
                queue.put_nowait(
                    (priority(item) if priority else 0, next(sequence), item)
                )
        publish_snapshot()

    async def verify_serialized(candidate):
        # An official-link promotion may enqueue the same URL a second time.
        # Different pages can run concurrently; the same lead cannot be verified twice at once.
        key = canonicalize(candidate.source_url)
        lock = verification_locks.setdefault(key, asyncio.Lock())
        async with lock:
            return await verify(candidate)

    async def worker():
        nonlocal active, completed_verifications
        while True:
            _, _, candidate = await queue.get()
            active += 1
            publish_snapshot()
            started = monotonic()
            try:
                result = await asyncio.wait_for(verify_serialized(candidate), item_seconds)
                if isinstance(result, list):
                    enqueue(result)
                elif result:
                    job_id, is_useful = result
                    known.add(job_id)
                    if is_useful:
                        useful.add(job_id)
                event(
                    "verification",
                    url=candidate.source_url,
                    duration_ms=int((monotonic() - started) * 1000),
                    error_code=None,
                )
            except TimeoutError:
                event(
                    "verification",
                    url=candidate.source_url,
                    duration_ms=int((monotonic() - started) * 1000),
                    error_code="verification_timeout",
                )
            except Exception as error:  # noqa: BLE001 - a broken page must not kill discovery
                event(
                    "verification",
                    url=candidate.source_url,
                    duration_ms=int((monotonic() - started) * 1000),
                    error_code=type(error).__name__,
                )
            finally:
                active -= 1
                completed_verifications += 1
                queue.task_done()
                publish_snapshot()
                verification_changed.set()
            report(round_number, len(seen), len(useful), "搜索与核验并行进行", None)

    consumers = [asyncio.create_task(worker()) for _ in range(max(1, min(3, max_concurrency)))]
    try:
        attempted_rounds = 0
        paused_for_round = False
        while attempted_rounds < max_rounds:
            number = attempted_rounds + 1
            round_number = number
            if (
                number > 1
                and feedback_wait_seconds > 0
                and queue.qsize() + active > 0
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
                pause_seconds = min(15, item_seconds, max(0, deadline - monotonic()) / 2)
                pause_deadline = monotonic() + pause_seconds
                event(
                    "search_pause",
                    summary="暂缓新增搜索，等待正文核验反馈后重新判断",
                    reason=candidates.reason,
                    pending_verification=queue.qsize() + active,
                    useful_jobs=len(useful),
                    timeout_seconds=pause_seconds,
                )
                while queue.qsize() + active > 0 and len(useful) < target:
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
                    pending_verification=queue.qsize() + active,
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
            await asyncio.wait_for(queue.join(), verification_seconds)
        except TimeoutError:
            event(
                "queue_budget",
                pending_count=queue.qsize() + active,
                error_code="verification_budget_exhausted",
            )
            stop += "；剩余岗位保留待核验"
    finally:
        for consumer in consumers:
            consumer.cancel()
        await asyncio.gather(*consumers, return_exceptions=True)
    report(round_number, len(seen), len(useful), "搜索结束", stop)
    return stop
