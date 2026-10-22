"""Scheduling hints never establish source trust or decide job eligibility."""

from __future__ import annotations

import asyncio
import re
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
from src.services.lead_presentation import lead_discovery_kind
from src.services.recruitment_trust import hiring_scope


def title_role_status(text, query):
    """A cheap ordering hint; missing title evidence never excludes a job."""
    stub = JobStub(source_id="scheduling", source_job_id="", company=None,
                   title=text, locations=[], job_type=None, published_at=None,
                   detail_url="", raw_content="")
    checks = classify_discovery_job(stub, query=query).checks
    status = next((c["status"] for c in checks if c["field"] == "role"), None)
    from src.services.recruitment_search_controls import site_search_terms

    terms = [term for group in requested_role_terms(query) for term in group]
    terms = list(dict.fromkeys([*terms, *site_search_terms(terms)]))
    if status != "excluded" and any(
        _contains(text.casefold(), term)
        for term in terms
    ):
        return "matched"
    return status


def listing_priority(text, query, job_types=(), *, title=None):
    """Order card evidence, retaining uncertain and conflicting candidates."""
    from src.services.recruitment_listing import recruitment_priority
    from src.services.url_reader import HTMLLink

    title = title or next(iter(text.splitlines()), "")
    status = title_role_status(title, query)
    if status not in {"matched", "excluded"}:
        # Mere use of an assistant is weak retrieval evidence. Keep the row,
        # but do not let an incidental tooling clause win a scarce detail slot.
        clauses = re.split(r"[。；;\n]", text)
        relevant = [clause for clause in clauses if not re.search(
            r"(?:使用|利用|借助|熟悉).{0,35}(?:AI|Agent|RAG|大模型).{0,25}(?:工具|辅助|编码助手)"
            r"|(?:AI|Agent|RAG|大模型).{0,25}(?:辅助|助力).{0,20}(?:工作|编码|提效)"
            r"|(?:use|using).{0,30}(?:AI|agent).{0,20}(?:tools?|assistants?)", clause, re.IGNORECASE)]
        status = title_role_status("\n".join(relevant), query)
    recruitment = recruitment_priority(HTMLLink("", text), list(job_types))
    from src.services.search_constraints import select_term_groups
    from src.services.search_intent import parse_conditions
    from src.services.search_vocabulary import _LOCATION_GROUPS, location_aliases

    desired = parse_conditions(query).locations
    # A city mentioned in responsibilities (e.g. serving Beijing clients) is
    # not a work location. Prefer the card header and explicit location lines.
    header = re.split(r"岗位职责|工作职责|职责描述|任职要求|Responsibilities|Requirements", text, maxsplit=1, flags=re.IGNORECASE)[0]
    location_text = header + "\n" + "\n".join(line for line in text.splitlines()
        if re.match(r"\s*(?:工作地点|工作城市|城市|Job location|Location)\s*[:：]", line, re.IGNORECASE))
    observed, _ = select_term_groups(location_text.casefold(), _LOCATION_GROUPS)
    overlap = any(set(location_aliases(wanted)) & set(group) for wanted in desired for group in observed)
    location = (0 if not desired or overlap else 2 if observed else 1)
    return (3 if recruitment == 2 or location == 2 else {"matched": 0, "excluded": 2}.get(status, 1),
            location, recruitment)


def candidate_priority(candidate, *, query, official_hosts):
    from src.services.recruitment_listing import recruitment_priority
    from src.services.search_intent import parse_conditions
    from src.services.url_reader import HTMLLink

    trusted_hint = bool(candidate.official_entry_url) or (
        urlsplit(candidate.source_url).hostname in official_hosts
    )
    purpose = candidate.search_context.get("purpose")
    if purpose in {"negative", "reference"}:
        return (7 if purpose == "negative" else 6, 0, 0 if trusted_hint else 1)
    if lead_discovery_kind(candidate) != "job":
        return (3 if trusted_hint else 4, 0, 0)

    title_status = title_role_status(candidate.title_hint or "", query)
    if title_status == "excluded":
        rank = 5
    elif title_status in {None, "matched"}:
        rank = 0
    elif title_role_status(candidate.search_snippet or "", query) == "matched":
        rank = 1
    else:
        rank = 2
    recruitment = recruitment_priority(
        HTMLLink(candidate.source_url, candidate.title_hint or ""),
        parse_conditions(query).job_types,
    )
    if recruitment == 2:
        rank = 5
    if purpose == "recommended":
        rank, recruitment = 0, 0
    elif purpose == "adjacent":
        rank, recruitment = 1, 0
    # Hints affect order only. Every candidate still undergoes the same checks.
    return rank, recruitment, 0 if trusted_hint else 1


def candidate_source(candidate):
    url = candidate.official_entry_url or candidate.source_url
    scope = hiring_scope(url)
    return "".join(scope) if scope else (urlsplit(url).hostname or url)


class CompanyCandidateGate:
    """Protect a bounded shortlist from early, weak historical arrivals."""

    def __init__(self, *, quota=3, wait_seconds=35, clock=monotonic):
        self.quota, self.clock = quota, clock
        self.deadline = clock() + wait_seconds

    def allows(self, *, used, priority, producer_finished, direct=False, cached=False):
        if cached or direct or used >= self.quota or producer_finished or self.clock() >= self.deadline:
            return True
        # Strong new/history candidates can start immediately. References wait;
        # at most one uncertain candidate may borrow the unreserved capacity.
        return priority[0] <= 1 or (priority[0] < 5 and used < max(0, self.quota - 2))


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
        max_pending=120,
        clock=monotonic,
        can_start=None,
    ):
        self.priority = priority or (lambda _: 0)
        self.source_key = source_key
        self.is_entry = is_entry or (lambda _: False)
        self.source_batch_size = max(1, source_batch_size)
        self.clock = clock
        self.can_start = can_start or (lambda _: True)
        self.sequence = count()
        self.pending = []
        self.active = {}
        self.last_source = None
        self.source_streak = 0
        self.max_pending = max(1, max_pending)
        self.deferred_sources = set()
        self.probe_sources = set()
        self.changed = asyncio.Event()
        self.finished = asyncio.Event()
        self.finished.set()

    def put_nowait(self, candidate):
        source = self.source_key(candidate) if self.source_key else None
        if source is not None and source in self.deferred_sources:
            return False
        item = QueuedVerification(
            candidate,
            self.priority(candidate),
            next(self.sequence),
            self.clock(),
            source,
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
            if len(self.pending) >= self.max_pending:
                return False
            self.pending.append(item)
        self.finished.clear()
        self.changed.set()
        return True

    def defer_source(self, source):
        """Remove runnable work for this run; the caller retains durable leads."""
        self.deferred_sources.add(source)
        deferred = [i.candidate for i in self.pending if i.source == source]
        self.pending = [i for i in self.pending if i.source != source]
        if not self.pending and not self.active:
            self.finished.set()
        self.changed.set()
        return deferred

    def promote_pending(self, candidate):
        """Better discovery hints may reorder queued work, never repeat a read."""
        previous = next((item for item in self.pending
                         if item.candidate.source_url == candidate.source_url), None)
        if previous and self.priority(candidate) < previous.priority:
            return self.put_nowait(candidate)
        return False

    def discard_url(self, url):
        """A completed read also satisfies a duplicate queued by another producer."""
        self.pending = [item for item in self.pending if item.candidate.source_url != url]
        if not self.pending and not self.active:
            self.finished.set()
        self.changed.set()

    async def get(self):
        while True:
            entry_active = any(item.is_entry for item in self.active.values())
            eligible = [
                item
                for item in self.pending
                if item.candidate.source_url not in self.active
                and self.can_start(item.candidate)
                and not (item.is_entry and entry_active)
                and not (item.source in self.probe_sources
                         and any(a.source == item.source for a in self.active.values()))
            ]
            if eligible:
                # Company rotation is a tie-breaker within the best relevance
                # tier. It must not promote background links over target jobs.
                best = min(i.priority for i in eligible)
                eligible = [i for i in eligible if i.priority == best]
                if self.source_key and self.source_streak >= self.source_batch_size:
                    other = [i for i in eligible if i.source != self.last_source]
                    if other:
                        eligible = other
                peers = eligible
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
            if self.pending:
                # Eligibility also changes when a producer finishes or its
                # bounded waiting window expires without publishing anything.
                try:
                    await asyncio.wait_for(self.changed.wait(), .25)
                except TimeoutError:
                    pass
            else:
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
