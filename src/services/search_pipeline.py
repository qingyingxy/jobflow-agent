"""Independent search producer and bounded verification consumer."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from itertools import count
from time import monotonic


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
):
    queue = asyncio.PriorityQueue()
    sequence = count()
    official_evidence_seen = set()
    seen, useful, known = set(), set(), set()
    round_number = 0
    stop = "达到搜索轮数上限"

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

    async def worker():
        while True:
            _, _, candidate = await queue.get()
            started = monotonic()
            try:
                result = await asyncio.wait_for(verify(candidate), item_seconds)
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
                queue.task_done()
            report(round_number, len(seen), len(useful), "搜索与核验并行进行", None)

    consumer = asyncio.create_task(worker())
    deadline = monotonic() + seconds
    try:
        for number in range(1, max_rounds + 1):
            round_number = number
            remaining = deadline - monotonic()
            if remaining <= 0:
                stop = "达到搜索时间预算"
                break
            if len(useful) >= target:
                stop = "达到有效岗位目标"
                break
            report(number, len(seen), len(useful), "正在搜索，正文核验独立进行", None)
            try:
                candidates = await asyncio.wait_for(
                    search(number, set(seen)), remaining
                )
            except TimeoutError:
                stop = "达到搜索时间预算"
                break
            except Exception:  # noqa: BLE001 - search records preserve failure details
                report(number, len(seen), len(useful), "本轮搜索失败，继续下一轮", None)
                continue
            if candidates is None:
                stop = "独立查询计划已完成"
                break
            enqueue(candidates)
        report(
            round_number, len(seen), len(useful), "搜索已结束，继续处理核验队列", None
        )
        try:
            await asyncio.wait_for(queue.join(), verification_seconds)
        except TimeoutError:
            event(
                "queue_budget",
                pending_count=queue.qsize() + 1,
                error_code="verification_budget_exhausted",
            )
            stop += "；剩余岗位保留待核验"
    finally:
        consumer.cancel()
        await asyncio.gather(consumer, return_exceptions=True)
    report(round_number, len(seen), len(useful), "搜索结束", stop)
    return stop
