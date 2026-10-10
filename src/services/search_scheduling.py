"""Scheduling hints never establish source trust or decide job eligibility."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from itertools import count
from time import monotonic
from urllib.parse import urlsplit

from src.services.discovery_matching import (
    _contains,
    classify_discovery_job,
    requested_role_terms,
)
from src.services.discovery_sources import JobStub
from src.services.lead_presentation import discovery_kind
from src.services.recruitment_trust import hiring_scope


def candidate_priority(candidate, *, query, official_hosts):
    trusted_hint = bool(candidate.official_entry_url) or (
        urlsplit(candidate.source_url).hostname in official_hosts
    )
    if discovery_kind(candidate.source_url, candidate.title_hint) != "job":
        return (3 if trusted_hint else 4, 0)

    def role_status(text):
        stub = JobStub(
            source_id="scheduling",
            source_job_id=candidate.source_url,
            company=None,
            title=text,
            locations=[],
            job_type=None,
            published_at=None,
            detail_url=candidate.source_url,
            raw_content="",
        )
        checks = classify_discovery_job(stub, query=query).checks
        status = next((c["status"] for c in checks if c["field"] == "role"), None)
        if status != "excluded" and any(
            _contains(text.casefold(), term)
            for group in requested_role_terms(query)
            for term in group
        ):
            return "matched"  # Scheduling hint only, never a filtering verdict.
        return status

    title_status = role_status(candidate.title_hint or "")
    if title_status == "excluded":
        rank = 5
    elif title_status in {None, "matched"}:
        rank = 0
    elif role_status(candidate.search_snippet or "") == "matched":
        rank = 1
    else:
        rank = 2
    # Hints affect order only. Every candidate still undergoes the same checks.
    return rank, 0 if trusted_hint else 1


def candidate_source(candidate):
    url = candidate.official_entry_url or candidate.source_url
    scope = hiring_scope(url)
    return "".join(scope) if scope else (urlsplit(url).hostname or url)


@dataclass(frozen=True)
class QueuedVerification:
    candidate: object
    priority: object
    sequence: int
    queued_at: float
    source: str | None
    is_entry: bool


class VerificationQueue:
    """Bound source bursts, reserve room for details, and serialize each URL.

    Selection is cheap for the bounded search queue. Waiting entries and URL
    promotions do not occupy a worker while eligible detail tasks are queued.
    """

    def __init__(
        self,
        *,
        priority=None,
        source_key=None,
        is_entry=None,
        source_batch_size=3,
        clock=monotonic,
    ):
        self.priority = priority or (lambda _: 0)
        self.source_key = source_key
        self.is_entry = is_entry or (lambda _: False)
        self.source_batch_size = max(1, source_batch_size)
        self.clock = clock
        self.sequence = count()
        self.pending = []
        self.active = {}
        self.last_source = None
        self.source_streak = 0
        self.changed = asyncio.Event()
        self.finished = asyncio.Event()
        self.finished.set()

    def put_nowait(self, candidate):
        item = QueuedVerification(
            candidate,
            self.priority(candidate),
            next(self.sequence),
            self.clock(),
            self.source_key(candidate) if self.source_key else None,
            self.is_entry(candidate),
        )
        for index, previous in enumerate(self.pending):
            if previous.candidate.source_url == candidate.source_url:
                # Upgrade a queued URL with official-link evidence in place.
                self.pending[index] = replace(
                    item,
                    queued_at=previous.queued_at,
                    sequence=previous.sequence,
                )
                break
        else:
            self.pending.append(item)
        self.finished.clear()
        self.changed.set()

    async def get(self):
        while True:
            entry_active = any(item.is_entry for item in self.active.values())
            eligible = [
                item
                for item in self.pending
                if item.candidate.source_url not in self.active
                and not (item.is_entry and entry_active)
            ]
            if eligible:
                if self.source_key and self.source_streak >= self.source_batch_size:
                    other = [i for i in eligible if i.source != self.last_source]
                    if other:
                        eligible = other
                best = min(i.priority for i in eligible)
                peers = [i for i in eligible if i.priority == best]
                active_sources = {i.source for i in self.active.values()}
                diverse = [i for i in peers if i.source not in active_sources]
                item = min(diverse or peers, key=lambda i: i.sequence)
                self.pending.remove(item)
                self.active[item.candidate.source_url] = item
                self.source_streak = (
                    self.source_streak + 1 if (item.source == self.last_source) else 1
                )
                self.last_source = item.source
                return item
            self.changed.clear()
            await self.changed.wait()

    def task_done(self, item):
        del self.active[item.candidate.source_url]
        if not self.pending and not self.active:
            self.finished.set()
        self.changed.set()

    def qsize(self):
        return len(self.pending)

    async def join(self):
        await self.finished.wait()
