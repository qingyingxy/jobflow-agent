"""Read official listings using observed HTML or supported ATS protocols.

Tenant ownership comes from the
official homepage, IDs from current filter responses, and facts from full public
job payloads. None of these facts are inferred from search-engine snippets.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from time import monotonic
from urllib.parse import quote, urlencode, urlsplit, urlunsplit

from src.domain.discovery import LeadProvider
from src.services.company_search_progress import supports_direct_listing
from src.services.discovery_matching import (
    _LOCATION_GROUPS,
    classify_discovery_job,
    search_filter_conditions,
)
from src.services.discovery_sources import ByteDanceAdapter, JobStub, SourcePayloadError
from src.services.job_url import canonical_job_url
from src.services.lead_providers import LeadCandidate
from src.services.recruitment_listing import (
    allowed_listing_url,
    entry_priority,
    feishu_filters,
    inspect_listing,
    listing_card_texts,
    listing_document_url,
    observed_ats_base,
    observed_hiring_redirect,
    recruitment_priority,
)
from src.services.recruitment_trust import hiring_scope, within_scope
from src.services.search_constraints import select_term_groups
from src.services.search_scheduling import listing_priority
from src.services.url_reader import _HTMLTextParser, extract_html_links


@dataclass(frozen=True)
class DirectJobEvidence:
    stub: JobStub
    official_url: str
    official_html: str
    listing_url: str
    api_record: dict
    full_body: bool
    official_proof_url: str | None = None
    observed_at: datetime | None = None
    listing_html: str | None = None
    official_redirects: tuple[dict, ...] = ()
    official_navigation: tuple[dict, ...] = ()


def search_keywords(query):
    from src.services.search_intent import parse_conditions

    conditions = parse_conditions(query)
    # A literal "AI Agent" misses titles written simply as "Agent". This is a
    # retrieval alias only; saved user conditions and final judgments stay intact.
    return list(dict.fromkeys(re.sub(r"^ai\s+agent$", "agent", role, flags=re.IGNORECASE)
                              for role in [*conditions.roles, *conditions.preferred_roles]))[:3]


def listing_filters(data, query):
    """Use positive location choices; leave unsupported/ambiguous filters open."""
    wanted, _ = select_term_groups(query, _LOCATION_GROUPS)
    locations = [
        item["code"] for item in data.get("city_list") or []
        if item.get("code") and any(
            str(item.get("name", "")).casefold() in group
            or str(item.get("en_name", "")).casefold() in group for group in wanted
        )
    ]
    years = search_filter_conditions(query)["graduation_years"]
    internship = search_filter_conditions(query)["job_types"] == ["实习"]
    subjects = []
    for item in data.get("job_subject_list") or []:
        name = item.get("name") or {}
        name = name.get("zh_cn") or name.get("i18n") or "" if isinstance(name, dict) else str(name)
        group = item.get("subject_group_info") or {}
        group_name = group.get("name") or ""
        if isinstance(group_name, dict):
            group_name = group_name.get("zh_cn") or group_name.get("i18n") or ""
        matches_year = not years or any(f"{year}届" in name for year in years)
        matches_type = "实习" in (name + group_name) if internship else bool(years and re.search(r"校招|校园招聘", name) and "实习" not in (name + group_name))
        if item.get("id") and matches_year and matches_type:
            subjects.append(item["id"])
    return {"location": ",".join(locations), "project": ",".join(subjects)}


def payload_stub(item, *, company, listing_url):
    # Reuse the existing payload normalizer, with the current campus detail URL.
    # A list card without full requirements must go through normal page reading.
    if not isinstance(item, dict):
        raise SourcePayloadError("官网岗位格式无效")
    stub = ByteDanceAdapter(query="", company=company)._to_stub(item)
    parsed = urlsplit(listing_url)
    prefix = "/" + parsed.path.strip("/").split("/")[0]
    detail = urlunsplit((parsed.scheme, parsed.netloc, f"{prefix}/position/{stub.source_job_id}/detail", "", ""))
    subject = (item.get("job_subject") or {}).get("name") or {}
    subject = subject.get("zh_cn") or subject.get("i18n") or "" if isinstance(subject, dict) else str(subject)
    job_type = stub.job_type
    if not item.get("recruit_type") and subject:
        # Custom-domain portals omit recruit_type. Only the job's own explicit
        # project label supplies a type; the list URL alone is insufficient.
        job_type = "internship" if "实习" in subject else "campus" if re.search(r"校招|校园招聘", subject) else job_type
    # The shared normalizer collapses whitespace for card metadata. Full ATS
    # sections need their original paragraph boundaries for duty evidence.
    header = stub.raw_content.split("岗位职责：", 1)[0].split("任职要求：", 1)[0].strip()
    if job_type != stub.job_type:
        header = re.sub(r"招聘类型：[^\n]*", "招聘类型：" + ("校园招聘" if job_type == "campus" else "实习"), header)
    sections = [header]
    category = item.get("job_category") or item.get("function_category") or {}
    if isinstance(category, dict):
        category = category.get("name") or ""
        if isinstance(category, dict):
            category = category.get("zh_cn") or category.get("i18n") or ""
    if isinstance(category, str) and category.strip():
        sections.append("官网职能分类：" + " ".join(category.split())[:100])
    for field, heading in (("description", "岗位职责"), ("requirement", "任职要求")):
        if isinstance(item.get(field), str) and item[field].strip():
            parser = _HTMLTextParser()
            parser.feed(item[field])
            parser.close()
            text = "\n".join(line.strip() for line in "".join(parser.parts).splitlines() if line.strip())
            sections.append(heading + "：\n" + text)
    return replace(
        stub, source_id=f"official-ats:{parsed.hostname}:{prefix}", detail_url=detail, job_type=job_type,
        raw_content=(subject + "\n" + "\n".join(sections)).strip(),
    )


class DirectRecruitmentSearch:
    def __init__(self, *, sources, query, reader, browser, on_event, max_jobs=20,
                 target_per_company=3, company_seconds=30, states=None, checkpoint=None,
                 company_concurrency=4, company_done=None, verification_seconds=180, understanding=None, known_urls=None):
        self.sources = [s for s in sources if supports_direct_listing(s)]
        self.query, self.reader, self.browser = query, reader, browser
        self.on_event = on_event
        self.max_jobs = max_jobs
        self.evidence = {}
        self.read_sources, self.fresh_sources = set(), set()
        self.target_per_company, self.company_seconds = target_per_company, company_seconds
        self.company_concurrency = max(1, min(4, company_concurrency))
        self.verification_seconds = verification_seconds
        self.states = states or {}
        self.checkpoint = checkpoint or (lambda *_: None)
        self.running = False
        self.pending_sources = set()
        self.finished_sources = set()
        self.active_started = {}
        self.published_sources = set()
        self.last_progress = {}
        self.changed = asyncio.Event()
        self.company_done = company_done or (lambda _: False)
        self.understanding = understanding
        self.known_urls = {canonical_job_url(url) for url in known_urls or []}
        self.read_deadlines = {}

    async def _rank_buffer(self, source, state):
        from src.services.source_understanding import VERSION

        items = state["buffer"]
        if not items:
            self._trace_pool(source, state, "local")
            return
        # One detail, one slot. Keep the richest observed card and its proof.
        unique = {}
        for item in items:
            key = self._item_url(item, state)
            if key not in unique or len(str(item)) > len(str(unique[key])):
                unique[key] = item
        items = list(unique.values())
        state["buffer"] = items
        ids = [str(item["id"]) for item in items]
        pool_key = hashlib.sha256(json.dumps(sorted(items, key=lambda i: str(i['id'])),
            sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
        known = sorted(self.known_urls.intersection(self._item_url(item, state) for item in items))
        if (state.get("ranking_query") == self.query and state.get("ranking_version") == VERSION
                and state.get("ranking_known") == known and state.get("ranking_pool") == pool_key
                and state.get("ranking_policy") == "diverse-pool-v1"):
            self._reserve_waiting_candidate(state)
            self._trace_pool(source, state, "reused")
            return
        # Retrieval hints only: final eligibility is always based on the detail.
        types = search_filter_conditions(self.query)["job_types"]
        def content(item):
            return (payload_stub(item, company=source.company, listing_url=state["base"]).raw_content
                    if state.get("reader_kind") != "html" and state.get("base")
                    else item.get("listing_text") or item.get("title", ""))

        items = sorted(items, key=lambda item: (
            listing_priority(content(item), self.query, types, title=item.get("title")),
            self._item_url(item, state) in self.known_urls))
        # Keep one bounded model call, but represent the tail as well as the
        # keyword-heavy head. Unselected candidates remain for continuation.
        sample = list(range(len(items))) if len(items) <= 30 else [*range(20),
            *(20 + i * (len(items) - 20) // 10 for i in range(10))]
        texts = [("已入库岗位\n" if self._item_url(items[i], state) in self.known_urls else "尚未入库的新岗位\n") + content(items[i])
                 for i in sample]
        state["buffer"] = items
        self._reserve_waiting_candidate(state)
        self.save(source, state)
        if not self.understanding or not self.understanding.primary:
            self._trace_pool(source, state, "local")
            return
        self._trace_pool(source, state, "before_model")
        try:
            # Leave time to publish the pool even when ranking is unavailable.
            order = await asyncio.wait_for(self.understanding.rank_listing(
                texts, url=state.get("listing_url", source.career_url)),
                timeout=max(.01, self.read_deadlines.get(source.id, monotonic() + 9) - monotonic() - .5))
        except TimeoutError:
            self._trace_pool(source, state, "ranking_timeout")
            return
        listing_url = state.get("listing_url", source.career_url)
        if getattr(self.understanding, "listing_outcomes", {}).get(listing_url) == "fallback":
            # An unavailable model has not completed a ranking. Preserve the
            # local order, and let a later continuation retry interpretation.
            state.pop("ranking_version", None)
            self.save(source, state)
            self._trace_pool(source, state, "ranking_deferred")
            return
        selected = [sample[i] for i in order]
        selected += [i for i in range(len(items)) if i not in selected]
        state.update(buffer=[items[i] for i in selected], ranking_query=self.query, ranked_ids=ids,
                     ranking_version=VERSION, ranking_known=known, ranking_pool=pool_key,
                     ranking_policy="diverse-pool-v1")
        self._reserve_waiting_candidate(state)
        self.save(source, state)
        self._trace_pool(source, state, "after_ranking")

    def _reserve_waiting_candidate(self, state):
        """One third slot for a compatible candidate waiting across rounds."""
        items = state["buffer"]
        if len(items) <= 3 or self.target_per_company < 3:
            return
        waits = state.get("candidate_wait_rounds", {})
        types = search_filter_conditions(self.query)["job_types"]
        eligible = []
        for index, item in enumerate(items[2:], 2):
            key = self._item_url(item, state)
            text = (item.get("listing_text") or item.get("title", "") if state.get("reader_kind") == "html"
                    else payload_stub(item, company="", listing_url=state["base"]).raw_content)
            if (waits.get(key, 0) >= 2 and key not in self.known_urls
                    and listing_priority(text, self.query, types, title=item.get("title"))[0] < 2):
                eligible.append((waits[key], -index, item))
        if eligible:
            chosen = max(eligible, key=lambda row: row[:2])[2]
            state["buffer"] = [*items[:2], chosen, *(item for item in items[2:] if item is not chosen)]

    def _trace_pool(self, source, state, stage):
        items = state.get("buffer", [])
        if not items:
            return
        self.on_event("listing_candidates", {
            "source_id": source.id, "company": source.company, "stage": stage,
            "url": state.get("listing_url", source.career_url),
            "candidate_count": len(items), "truncated": len(items) > 60,
            "candidates": [{"url": self._item_url(item, state), "title": item.get("title", "")[:160],
                            "rank": rank, "known": self._item_url(item, state) in self.known_urls}
                           for rank, item in enumerate(items[:60], 1)],
        })

    @staticmethod
    def _item_url(item, state):
        if state.get("reader_kind") == "html":
            return canonical_job_url(item["id"])
        return canonical_job_url(payload_stub(item, company="", listing_url=state["base"]).detail_url)

    def fallback_ready(self, source_id):
        if not self.running or source_id not in self.pending_sources:
            return True
        started = self.active_started.get(source_id)
        progress = self.last_progress.get(source_id, started)
        return progress is not None and monotonic() - progress >= min(8, self.company_seconds / 2)

    @property
    def supported(self):
        types = search_filter_conditions(self.query)["job_types"]
        return bool(self.sources and search_keywords(self.query) and types in (["校招"], ["实习"]) and hasattr(self.browser, "read_search_listing"))

    def save(self, source, state):
        state["updated_at"] = datetime.now(UTC).isoformat()
        self.checkpoint(source.id, state)

    def _remember(self, source, candidate):
        """Durably hand off a candidate before advancing its listing buffer."""
        state = self.states[source.id]
        key = canonical_job_url(candidate.source_url)
        evidence = self.evidence[candidate.source_url]
        self.evidence[key] = evidence
        packed = asdict(candidate)
        packed.update(provider=candidate.provider.value,
                      discovered_at=candidate.discovered_at.isoformat(), verification_stub=None)
        proof = asdict(evidence)
        proof['observed_at'] = evidence.observed_at.isoformat() if evidence.observed_at else None
        published = evidence.stub.published_at
        proof['stub']['published_at'] = published.isoformat() if published else None
        state['pending_candidates'][key] = {'candidate': packed, 'evidence': proof}
        self.on_event("listing_handoff", {"source_id": source.id, "company": source.company,
            "url": key, "title": candidate.title_hint, "known": key in self.known_urls})
        if candidate.source_job_id is not None:
            state['seen_ids'] = list(dict.fromkeys([*state['seen_ids'], candidate.source_job_id]))
            state['buffer'] = [item for item in state['buffer']
                               if str(item.get('id')) != candidate.source_job_id]
        self.save(source, state)

    async def _resume_source(self, source):
        state = self.states[source.id]
        for key, record in list(state['pending_candidates'].items()):
            if key not in state['pending_candidates']:
                continue
            packed, proof = dict(record['candidate']), dict(record['evidence'])
            packed['discovered_at'] = datetime.fromisoformat(packed['discovered_at'])
            packed['provider'] = LeadProvider(packed['provider'])
            stub = dict(proof['stub'])
            if stub.get('published_at'):
                stub['published_at'] = datetime.fromisoformat(stub['published_at'])
            proof['stub'] = JobStub(**stub)
            if proof.get('observed_at'):
                proof['observed_at'] = datetime.fromisoformat(proof['observed_at'])
            candidate = LeadCandidate(**packed)
            self.evidence[candidate.source_url] = DirectJobEvidence(**proof)
            yield candidate
        async for candidate in self._source(source):
            yield candidate

    def record_result(self, candidate, useful):
        """An idempotent acknowledgement, also accepted after reading has stopped."""
        if useful is None:
            return
        key = canonical_job_url(candidate.source_url)
        for source in self.sources:
            state = self.states.get(source.id, {})
            if key not in state.get('pending_candidates', {}):
                continue
            state['pending_candidates'].pop(key)
            state['checked_urls'] = list(dict.fromkeys([*state['checked_urls'], key]))
            if useful:
                state['matched_urls'] = list(dict.fromkeys([*state['matched_urls'], key]))
            self.save(source, state)
            self.changed.set()

    async def discover(self, publish, await_result=None):
        self.running = True
        self.pending_sources = {source.id for source in self.sources}
        semaphore = asyncio.Semaphore(self.company_concurrency)
        async def source_jobs(source):
            started = monotonic()
            active_started = None
            read_seconds = queue_seconds = verification_wait = 0.0
            error_code = None
            count = 0
            outstanding = {}
            iterator = None
            defaults = {
                "started_at": datetime.now(UTC).isoformat(), "checked_urls": [],
                "matched_urls": [], "seen_ids": [], "buffer": [], "exhausted": [],
                "page_number": 1, "term_index": 0, "pages_checked": 0,
                "strategy": "official_listing",
                "pending_candidates": {},
            }
            state = self.states.setdefault(source.id, {})
            for key, value in defaults.items():
                state.setdefault(key, value)
            waits = state.get("candidate_wait_rounds", {})
            state["candidate_wait_rounds"] = {self._item_url(item, state): waits.get(self._item_url(item, state), 0) + 1
                                             for item in state["buffer"]}
            prior_read_failed = state.get("status") == "failed" or state.get("reason") in {
                "dynamic_navigation_unresolved", "pagination_unresolved", "listing_scope_changed",
                "entry_retry_pending",
            }
            target = self.target_per_company
            state.update(status="running", reason=None)
            self.save(source, state)

            def acknowledge_done():
                unfinished = False
                for task, candidate in list(outstanding.items()):
                    if not task.done():
                        continue
                    del outstanding[task]
                    if task.cancelled():
                        unfinished = True
                        continue
                    try:
                        useful = task.result()
                    except Exception:  # noqa: BLE001 - a consumer failure is not a bad listing
                        useful = None
                    self.record_result(candidate, useful)
                    unfinished |= useful is None
                return unfinished

            try:
                iterator = self._resume_source(source)
                producing = True
                while True:
                    if acknowledge_done():
                        producing = False
                        state.update(status="paused", reason="verification_pending")
                    if self.company_done(source.id) or count >= target:
                        state.update(status="paused", reason="company_read_limit")
                        break
                    if count >= self.max_jobs:
                        producing = False
                        state.update(status="paused", reason="verification_budget")
                    if read_seconds >= self.company_seconds and producing:
                        producing = False
                        state.update(status='paused', reason='time_budget')
                    capacity = min(3, target)
                    if producing and len(outstanding) < capacity:
                        queued_at = monotonic()
                        async with semaphore:
                            queue_seconds += monotonic() - queued_at
                            if active_started is None:
                                active_started = monotonic()
                                self.active_started[source.id] = active_started
                                state['last_attempt_at'] = datetime.now(UTC).isoformat()
                            read_started = monotonic()
                            self.read_deadlines[source.id] = read_started + max(0, self.company_seconds - read_seconds)
                            try:
                                # Only fetching/advancing the listing spends this budget.
                                async with asyncio.timeout(max(0, self.company_seconds - read_seconds)):
                                    candidate = await anext(iterator)
                            except StopAsyncIteration:
                                producing = False
                                if state['status'] == 'running':
                                    state.update(status='paused', reason='page_budget')
                                continue
                            except TimeoutError:
                                producing = False
                                state.update(status='paused', reason='time_budget')
                                continue
                            finally:
                                read_seconds += monotonic() - read_started
                        # The quota may have filled while a page was loading.
                        if self.company_done(source.id):
                            state.update(status='paused', reason='company_read_limit')
                            break
                        self._remember(source, candidate)
                        count += 1
                        self.published_sources.add(source.id)
                        self.last_progress[source.id] = monotonic()
                        self.changed.set()
                        publish([candidate])
                        if await_result:
                            outstanding[asyncio.create_task(await_result(candidate))] = candidate
                            await asyncio.sleep(0)
                        else:
                            evidence = self.evidence[candidate.source_url]
                            self.record_result(candidate, evidence.full_body and
                                classify_discovery_job(evidence.stub, query=self.query).filter_status == 'matched')
                        continue
                    if not outstanding:
                        break
                    # Backpressure frees the reader slot for other companies.
                    wait_started = monotonic()
                    try:
                        done, _ = await asyncio.wait(outstanding, return_when=asyncio.FIRST_COMPLETED,
                            timeout=max(0, self.verification_seconds - verification_wait))
                    finally:
                        verification_wait += monotonic() - wait_started
                    if not done:
                        state.update(status='paused', reason='verification_pending')
                        break
                if (state.get('reader_kind') != 'html' and not state['buffer']
                        and not state['pending_candidates']
                        and set(search_keywords(self.query)) <= set(state['exhausted'])
                        and state.get('reason') != 'company_read_limit'):
                    state.update(status='completed', reason='query_exhausted')
            except asyncio.CancelledError:
                state.update(status="paused", reason="interrupted")
                error_code = "direct_search_cancelled"
                raise
            except Exception as error:  # noqa: BLE001 - normal web search remains available
                error_code = getattr(error, "code", type(error).__name__)
                state.update(status="failed", reason=error_code)
            finally:
                # Completed acknowledgements survive cancellation; unfinished
                # ones remain in the durable journal with their original evidence.
                acknowledge_done()
                for task in outstanding:
                    task.cancel()
                await asyncio.gather(*outstanding, return_exceptions=True)
                if iterator is not None:
                    await iterator.aclose()
                self.pending_sources.discard(source.id)
                self.finished_sources.add(source.id)
                self.changed.set()
                self.save(source, state)
                self.on_event("direct_search", {
                    "company": source.company, "error_code": error_code, "source_id": source.id,
                    "source_read_attempted": source.id in self.read_sources,
                    "source_read_success": source.id in self.fresh_sources,
                    "source_retry": prior_read_failed,
                    "output_count": count, "status": state["status"],
                    "reader_kind": state.get("reader_kind"),
                    "reason": state.get("reason"),
                    "duration_ms": int((monotonic() - started) * 1000),
                    "queue_wait_ms": int(queue_seconds * 1000),
                    "read_duration_ms": int(read_seconds * 1000),
                    "verification_wait_ms": int(verification_wait * 1000),
                    "summary": f"{source.company}官网定向检索发现 {count} 个岗位；"
                               + {"paused": "未查完，进度已保存", "completed": "当前关键词已查完",
                                  "failed": "页面读取未完成，进度已保存"}.get(state["status"], "查询结束"),
                })
        try:
            await asyncio.gather(*(source_jobs(source) for source in self.sources))
        finally:
            self.running = False
            self.changed.set()

    async def _source(self, source):
        state = self.states[source.id]
        from src.services.verified_recruitment_entry import fresh_entry

        entry = fresh_entry(state, source)
        if state.get("targeted_navigation_version") != 1:
            from src.services.url_reader import HTMLLink

            types = search_filter_conditions(self.query)["job_types"]
            if (state.get("html_seen_pages") and not entry and not state.get("base")
                    and not state.get("buffer")
                    and recruitment_priority(HTMLLink(source.career_url, ""), types) == 0):
                # Resume a previously unproductive traversal once after this
                # policy change. Keep acknowledgements and alternative entries.
                state["html_queue"] = [{"url": source.career_url, "scope_url": source.career_url,
                    "proof_url": source.career_url, "official_html": "", "priority": -1},
                    *[p for p in state.get("html_queue", []) if p["url"] != source.career_url]]
                self.on_event("recruitment_navigation_recheck", {"source_id": source.id,
                    "summary": f"{source.company}重新读取目标招聘入口的动态导航"})
            state["targeted_navigation_version"] = 1
            self.save(source, state)
        queue = state.get("html_queue", [])
        homepage_retry = (entry and entry["url"] != source.career_url and queue
                          and queue[0]["url"] == source.career_url)
        reused = bool(entry and not state.get("base") and (not queue or homepage_retry) and not state.get("buffer"))
        if reused:
            state["html_queue"] = [{**entry, "cached_entry": True}]
            self.on_event("recruitment_entry_reused", {"source_id": source.id,
                "url": entry["url"], "summary": f"{source.company}复用已核验招聘入口"})
        if state.get("base") and state.get("reader_kind") != "html":
            self._allow_transport(state["base"])
            produced = False
            try:
                async for candidate in self._pages(source, state):
                    produced = True
                    yield candidate
            except Exception:
                if produced:
                    raise
                # An old API/configuration is not a permanent capability. Open
                # the observed entry again and resolve current filters/protocol.
                for key in ("base", "filters", "html_blocked", "html_last_page"):
                    state.pop(key, None)
                state.update(reader_kind="html", buffer=[], exhausted=[], term_index=0,
                    page_number=1, html_seen_pages=[], html_queue=[])
                reused = bool(entry)
                if entry:
                    state["html_queue"] = [{**entry, "cached_entry": True}]
                self.on_event("recruitment_entry_revalidated", {"source_id": source.id,
                    "summary": f"{source.company}列表接口已变化，重新核验招聘入口"})
                self.save(source, state)
            else:
                return
        state.setdefault("reader_kind", "html")
        state.setdefault("html_queue", [{"url": source.career_url, "scope_url": source.career_url,
                                         "proof_url": source.career_url, "official_html": ""}])
        state.setdefault("html_seen_pages", [])
        if state.get("html_blocked") and not state["buffer"]:
            retry = next((p for p in state["html_queue"] if "dynamic_cursor" in p), None) or state.get("html_last_page")
            if retry and not state["html_queue"]:
                state["html_queue"] = [retry, *[p for p in state["html_queue"] if p["url"] != retry["url"]]]
            state.pop("html_blocked", None)
        if not state["html_queue"] and not state["buffer"]:
            # Revisit an unresolved page on explicit continuation, without
            # republishing already checked jobs. Web fallback can also run.
            state["html_queue"] = [state.get("html_last_page") or {
                "url": source.career_url, "scope_url": source.career_url,
                "proof_url": source.career_url, "official_html": ""}]
        produced = False
        try:
            async for candidate in self._html_pages(source, state):
                produced = True
                yield candidate
        except Exception:
            if not reused or produced:
                raise
            # A saved entry may move or change protocol. Retry the registered
            # official page once; preserve URL acknowledgements and pending jobs.
            for key in ("verified_entry", "base", "filters", "html_blocked", "html_last_page"):
                state.pop(key, None)
            state.update(reader_kind="html", buffer=[], exhausted=[], term_index=0, page_number=1,
                html_seen_pages=[], html_queue=[{"url": source.career_url, "scope_url": source.career_url,
                    "proof_url": source.career_url, "official_html": ""}])
            self.on_event("recruitment_entry_fallback", {"source_id": source.id,
                "summary": f"{source.company}已保存入口暂不可用，重新读取官网"})
            self.save(source, state)
            async for candidate in self._html_pages(source, state):
                yield candidate

    def _allow_transport(self, url):
        for transport in (self.reader, self.browser):
            checker = getattr(transport, "safety_checker", None)
            if checker is not None and hasattr(checker, "proxy_allowed_hosts"):
                checker.proxy_allowed_hosts |= {urlsplit(url).hostname}

    async def _read_listing(self, url, scope_url):
        from src.services.browser_job_reader import BrowserPageSnapshot
        from src.services.url_reader import URLReaderError

        self._allow_transport(url)
        if self.reader is not None:
            try:
                async with asyncio.timeout(min(6, self.company_seconds)):
                    response = await self.reader.fetch(url)
                redirects = getattr(response, "redirect_chain", ())
                # HTTP never sends a SPA fragment to the server. An unchanged
                # document response must retain the requested listing route.
                final_url = listing_document_url(response.final_url, url)
                if not allowed_listing_url(final_url, scope_url) and not observed_hiring_redirect(url, final_url, redirects):
                    raise SourcePayloadError("招聘入口发生越界跳转")
                if 200 <= getattr(response, "status_code", 200) < 300:
                    raw = response.body.decode("utf-8", errors="replace")
                    capabilities = inspect_listing(raw, url=final_url)
                    from src.services.job_url import canonical_job_url

                    types = search_filter_conditions(self.query)["job_types"]
                    from src.services.recruitment_search_controls import has_job_search

                    needs_search_render = has_job_search(raw, include_unlabelled=True) and not any(
                        entry_priority(link, types, self.query) == 0 for link in capabilities.entries)
                    # A targeted campus/intern portal may initially contain only
                    # global/footer routes; its real navigation arrives after
                    # hydration. Do not leave it for generic entrances before
                    # giving the browser a chance to reveal that navigation.
                    from src.services.url_reader import HTMLLink

                    targeted_portal = recruitment_priority(HTMLLink(final_url, ""), types) == 0
                    if capabilities.job_controls or capabilities.outbound_jobs or any(recruitment_priority(link, types) < 2 for link in capabilities.jobs) or any(
                        link.url.rstrip("/") != canonical_job_url(final_url).rstrip("/")
                        and entry_priority(link, types, self.query) < 2
                        and not needs_search_render
                        and (not targeted_portal or recruitment_priority(link, types) == 0)
                        for link in capabilities.entries
                    ):
                        return BrowserPageSnapshot(url, final_url, "", raw, "", redirect_chain=redirects)
            except (URLReaderError, TimeoutError):
                pass
        page = await self.browser.read_search_listing(url)
        if not allowed_listing_url(page.final_url, scope_url) and not observed_hiring_redirect(url, page.final_url, getattr(page, "redirect_chain", ())):
            raise SourcePayloadError("招聘入口发生越界跳转")
        return page

    async def _html_pages(self, source, state):
        from src.services.browser_job_reader import BrowserReadError
        from src.services.url_reader import URLReaderError

        # A failed entrance must not abort the company or pin its queue head.
        for _ in range(3):
            try:
                async for candidate in self._html_pages_pass(source, state):
                    yield candidate
                return
            except (SourcePayloadError, BrowserReadError, URLReaderError, TimeoutError) as error:
                queue = state.get("html_queue", [])
                if not queue:
                    raise
                pending = dict(queue[0])
                if pending.get("cached_entry") and not state.get("buffer"):
                    # Let _source re-resolve the registered official page once.
                    # A cached entry failure must not be swallowed as a normal
                    # alternative-entry cooldown before that fallback runs.
                    raise
                attempts = pending.get("read_failures", 0) + 1
                code = getattr(error, "code", "entry_timeout")
                pending.update(read_failures=attempts, last_error=code,
                               last_error_detail=str(error)[:300],
                               retry_at=(datetime.now(UTC) + timedelta(minutes=min(60, 2 ** attempts))).isoformat())
                state.update(html_queue=[*queue[1:], pending], status="paused", reason="entry_retry_pending")
                state.pop("html_blocked", None)
                self.save(source, state)
                self.on_event("listing_entry_failure", {"source_id": source.id, "company": source.company,
                    "url": pending["url"], "error_code": code, "error_detail": pending["last_error_detail"], "retry_at": pending["retry_at"],
                    "summary": "本入口暂不可用，已保存重试进度，继续其他招聘入口"})

    async def _dynamic_listing(self, source, url, **kwargs):
        # An unresponsive JS list must save its own failure before the outer
        # company budget expires, otherwise every continuation repeats it.
        remaining = self.read_deadlines.get(source.id, monotonic() + self.company_seconds) - monotonic()
        async with asyncio.timeout(max(.01, min(18, remaining - .2))):
            return await self.browser.read_dynamic_listing(url, **kwargs)

    async def _html_pages_pass(self, source, state):
        from src.services.job_url import canonical_job_url
        from src.services.recruitment_search_controls import (
            has_job_search,
            site_search_terms,
        )
        from src.services.search_scheduling import listing_priority

        types = search_filter_conditions(self.query)["job_types"]
        keywords = [*search_keywords(self.query), *types]
        pages_read = 0
        while True:
            await self._rank_buffer(source, state)
            for item in list(state["buffer"]):
                if item["id"] in state["seen_ids"] or canonical_job_url(item["id"]) in state["checked_urls"]:
                    continue
                stub = JobStub(f"official:{source.id}", item["id"], source.company,
                               item["title"], [], None, None, item["id"], "")
                self.evidence[stub.detail_url] = DirectJobEvidence(
                    stub, source.career_url, state["official_html"], state["listing_url"],
                    state.get("ui_navigation", {}), False, state["proof_url"],
                    datetime.fromisoformat(state["page_read_at"]), state["listing_html"],
                    tuple(state.get("official_redirects", ())), tuple(state.get("official_navigation", ())))
                yield LeadCandidate(
                    provider=LeadProvider.OFFICIAL_ADAPTER, source_url=stub.detail_url,
                    source_id=stub.source_id, source_job_id=stub.source_job_id,
                    company_hint=source.company, title_hint=stub.title,
                    discovered_at=datetime.now(UTC), official_entry_url=source.career_url, observed_title=True)
            state["buffer"] = []
            if state.get("html_blocked") and not state.get("html_queue"):
                state.update(status="paused", reason=state["html_blocked"])
                return
            state.pop("html_blocked", None)
            if not state["html_queue"]:
                state.update(status="paused", reason="listing_boundary")
                return
            if pages_read >= 3:
                return
            ready = [p for p in state["html_queue"] if not p.get("retry_at")
                     or datetime.fromisoformat(p["retry_at"]) <= datetime.now(UTC)]
            ready.sort(key=lambda pending: pending.get("priority", 1))
            if not ready:
                state.update(status="paused", reason="entry_retry_pending")
                return
            state["html_queue"] = [*ready, *[p for p in state["html_queue"] if p not in ready]]
            pending = state["html_queue"][0]
            self.read_sources.add(source.id)
            dynamic = getattr(self.browser, "read_dynamic_listing", None)
            profile = state.get("search_profiles", {}).get(pending["url"])
            if dynamic and profile and "dynamic_cursor" not in pending:
                # Reuse only observed controls, and let the browser revalidate
                # them. A recipe carries no source trust or job facts.
                pending = {**pending, "dynamic_cursor": {"search": {
                    "term": site_search_terms(keywords)[0], "recipe": profile["recipe"]}}}
            if "dynamic_cursor" in pending and dynamic:
                from src.services.browser_job_reader import BrowserReadError

                try:
                    page = await self._dynamic_listing(source, pending["url"], cursor=pending["dynamic_cursor"], keywords=[*search_keywords(self.query), *search_filter_conditions(self.query)["job_types"]], max_links=min(3, self.max_jobs))
                except BrowserReadError as error:
                    if error.code not in {"pagination_changed", "search_unconfirmed"}:
                        raise
                    if error.code == "search_unconfirmed":
                        state.get("search_profiles", {}).pop(pending["url"], None)
                        raise
                    # A live listing may re-order between runs. Re-scan from its
                    # observed entry and deduplicate checked URLs instead of
                    # skipping a changed page or permanently blocking continuation.
                    # Reset the offset, retaining the exact search term.
                    replay_search = pending["dynamic_cursor"].get("search")
                    page = await self._dynamic_listing(source, pending["url"], cursor={"search": replay_search} if replay_search else None,
                                         keywords=keywords, max_links=min(3, self.max_jobs))
            else:
                # Leave time for the original official entry if reuse fails.
                async with asyncio.timeout(min(10 if pending.get("cached_entry") else 18, self.company_seconds / 2)):
                    page = await self._read_listing(pending["url"], pending["scope_url"])
            if not allowed_listing_url(page.final_url, pending["scope_url"]):
                from src.services.entry_identity import entry_brand_matches
                from src.services.url_reader import parse_html_document

                redirects = getattr(page, "redirect_chain", ())
                if not (observed_hiring_redirect(pending["url"], page.final_url, redirects)
                        and entry_brand_matches(source.company, (page.title or "") + " " + parse_html_document(page.raw_html).text[:4000],
                                                official_url=pending.get("proof_url", source.career_url))):
                    raise SourcePayloadError("招聘跳转缺少企业身份或重定向证据")
                pending = {**pending, "url": page.final_url, "scope_url": page.final_url,
                           "official_redirects": list(redirects)}
            capabilities = inspect_listing(page.raw_html, url=page.final_url)
            if pending.get("require_brand"):
                from src.services.entry_identity import entry_brand_matches
                from src.services.url_reader import parse_html_document

                title = page.title or parse_html_document(page.raw_html).title or ""
                if not entry_brand_matches(source.company, title, official_url=pending.get("proof_url", source.career_url)):
                    raise SourcePayloadError(f"官方出链目标缺少企业身份确认（页面标题：{title[:80] or '缺失'}），保留入口待核验")
                # Once this linked origin has proved the brand, its own list
                # pages may have generic titles such as "Job Search".
                pending = {**pending, "require_brand": False,
                           "brand_evidence": {"url": page.final_url, "title": title}}
            config = feishu_filters(page, base=page.final_url)
            # Protocol-specific acceleration is selected by observed structure.
            # A root portal still needs an observed campus/internship entry.
            base = observed_ats_base(page, capabilities) if config is not None else None
            if base and not state.get("dom_fallback"):
                from src.services.verified_recruitment_entry import remember_entry

                state["verified_entry"] = remember_entry(source, pending)
                state.update(reader_kind="feishu", base=base, filters=listing_filters(config, self.query),
                             official_html=pending["official_html"], proof_url=pending["proof_url"],
                             official_redirects=pending.get("official_redirects", []),
                             official_navigation=pending.get("official_navigation", []))
                wanted, _ = select_term_groups(self.query, _LOCATION_GROUPS)
                if wanted and config.get("city_list") and not state["filters"]["location"]:
                    state["exhausted"] = search_keywords(self.query)
                    self.save(source, state)
                    return
                self.save(source, state)
                async for candidate in self._pages(source, state):
                    yield candidate
                return
            types = search_filter_conditions(self.query)["job_types"]
            usable_entries = [link for link in capabilities.entries if entry_priority(link, types, self.query) < 2
                              and link.url != page.final_url]
            if (dynamic and not getattr(page, "dynamic_listing", None)
                    and ((has_job_search(page.raw_html, include_unlabelled=True) and (capabilities.jobs or capabilities.job_controls
                          or not any(recruitment_priority(link, types) == 0 for link in usable_entries)))
                         or (capabilities.job_controls and not usable_entries) or capabilities.pagination_unresolved or capabilities.entry_controls
                         or (not capabilities.jobs and not capabilities.outbound_jobs and not usable_entries))):
                page = await self._dynamic_listing(source, pending["url"], keywords=[*search_keywords(self.query), *search_filter_conditions(self.query)["job_types"]], max_links=min(3, self.max_jobs))
                capabilities = inspect_listing(page.raw_html, url=page.final_url)
            observed_links = getattr(page, "discovered_links", ())
            job_links = {link.url: link for link in (*capabilities.jobs, *observed_links)
                         if allowed_listing_url(link.url, pending["scope_url"])}
            job_links.update({link.url: link for link in capabilities.outbound_jobs})
            if job_links:
                self.fresh_sources.add(source.id)
                from src.services.verified_recruitment_entry import remember_entry

                state["verified_entry"] = remember_entry(source, pending)
            dynamic_state = getattr(page, "dynamic_listing", None) or {}
            key = canonical_job_url(page.final_url)
            seen = set(state["html_seen_pages"]) | {key, canonical_job_url(pending["url"])}
            queue = state["html_queue"][1:]
            queued = {item["url"] for item in queue}
            next_cursor = dynamic_state.get("next_cursor")
            submitted = dynamic_state.get("search") or {}
            if submitted.get("status"):
                self.on_event("official_site_search", {
                    "source_id": source.id, "company": source.company,
                    "query": submitted.get("term"), "status": submitted["status"],
                    "recipe_reused": submitted.get("recipe_reused", False),
                    "summary": f"{source.company}站内搜索：" + (
                        "已确认列表更新" if submitted["status"] == "confirmed" else "未确认筛选，保留列表补查"),
                })
                if submitted["status"] != "confirmed":
                    state.get("search_profiles", {}).pop(pending["url"], None)
            if submitted.get("status") == "confirmed":
                state.setdefault("search_profiles", {})[pending["url"]] = {
                    "recipe": submitted["recipe"], "checked_at": datetime.now(UTC).isoformat(),
                }
                # Search alternatives are separate streams. Retain an unfiltered
                # pass for titles that omit the keyword; deduplicate by job URL.
                searched = state.setdefault("html_searches", [])
                if pending["url"] not in searched:
                    seed = {k: v for k, v in pending.items() if k != "dynamic_cursor"}
                    for term in [*site_search_terms(keywords), ""]:
                        if term != submitted["term"]:
                            queue.append({**seed, "dynamic_cursor": {"search": {
                                "term": term, "recipe": submitted["recipe"]}}})
                    searched.append(pending["url"])
            # Cursor replay owns pagination; never queue the next page twice.
            next_pages = [] if next_cursor else list(capabilities.next_urls)
            blocked = dynamic_state.get("reason") if dynamic_state else "pagination_unresolved" if capabilities.pagination_unresolved else None
            if any(target in seen for target in next_pages):
                blocked = "pagination_loop"
            for target in next_pages:
                if target not in seen and target not in queued:
                    queue.append({**{k: v for k, v in pending.items() if k != "dynamic_cursor"},
                                  "entry_url": pending.get("entry_url", pending["url"]), "url": target})
                    queued.add(target)
            if next_cursor:
                cursor_entry = {**pending, "dynamic_cursor": next_cursor}
                if job_links:
                    queue.insert(0, cursor_entry)
                else:
                    queue.append(cursor_entry)
            if not job_links or usable_entries:
                types = search_filter_conditions(self.query)["job_types"]
                for link in sorted((*getattr(page, "discovered_entries", ()), *capabilities.entries), key=lambda link: entry_priority(link, types, self.query)):
                    if entry_priority(link, types, self.query) == 2:
                        continue
                    if link.url in seen or link.url in queued:
                        continue
                    if allowed_listing_url(link.url, pending["scope_url"]):
                        entry = {**{k: v for k, v in pending.items() if k not in {"dynamic_cursor", "entry_url", "cached_entry"}}, "url": link.url}
                    elif allowed_listing_url(link.url, source.career_url):
                        # Regional portals can link back to another page on
                        # the already registered employer origin.
                        entry = {"url": link.url, "scope_url": source.career_url,
                                 "proof_url": source.career_url, "official_html": ""}
                    elif (not hiring_scope(source.career_url)
                          and allowed_listing_url(page.final_url, source.career_url)
                          and urlsplit(link.url).hostname != urlsplit(page.final_url).hostname):
                        entry = {"url": link.url, "scope_url": link.url,
                                 "proof_url": page.final_url, "official_html": page.raw_html,
                                 "official_navigation": [edge for edge in dynamic_state.get("observed_links", []) if edge["url"] == link.url],
                                 "require_brand": not bool(hiring_scope(link.url))}
                    else:
                        continue
                    entry["priority"] = entry_priority(link, types, self.query)
                    queue.append(entry)
                    queued.add(link.url)
            if blocked and queue:
                blocked = None
            if not job_links and not queue and not dynamic_state:
                raise SourcePayloadError("未发现可读取的岗位列表，保留网页补搜")
            jobs = sorted(job_links.values(), key=lambda link: listing_priority(link.text, self.query, types))
            card_texts = listing_card_texts(page.raw_html, url=page.final_url, job_urls=job_links)
            state.update(buffer=[{"id": link.url, "title": link.text, "listing_text": card_texts.get(link.url, link.text)} for link in jobs
                                 if link.url not in state["seen_ids"]],
                         html_queue=queue, html_seen_pages=sorted(seen), html_last_page=pending,
                         html_blocked=blocked, listing_url=page.final_url, listing_html=page.raw_html,
                         ui_navigation=dynamic_state,
                         official_html=pending["official_html"], proof_url=pending["proof_url"],
                         official_redirects=pending.get("official_redirects", []),
                         official_navigation=pending.get("official_navigation", []),
                         page_read_at=datetime.now(UTC).isoformat())
            state["pages_checked"] += 1
            pages_read += 1
            self.save(source, state)

    async def _pages(self, source, state):
        from src.services.job_url import canonical_job_url

        base, filters = state["base"], state["filters"]
        parsed = urlsplit(base)
        terms = search_keywords(self.query)
        pages_read = 0
        sampled_terms = set()
        while True:
            # Gather one bounded page per search term before spending the three
            # detail checks. Resume cursors and each row's original proof survive.
            primary = self.understanding and self.understanding.primary
            remaining = self.read_deadlines.get(source.id, monotonic() + self.company_seconds) - monotonic()
            rank_reserve = min(8, self.company_seconds / 3)
            fill_pool = (primary and pages_read < len(terms) and len(state["buffer"]) < 30
                         and set(terms) - set(state["exhausted"]) - sampled_terms
                         and (not state["buffer"] or remaining > rank_reserve + 1))
            if not fill_pool:
                await self._rank_buffer(source, state)
            for item in ([] if fill_pool else list(state["buffer"])):
                stub = payload_stub(item, company=source.company, listing_url=base)
                if stub.source_job_id in state["seen_ids"] or canonical_job_url(stub.detail_url) in state["checked_urls"]:
                    continue
                full_body = all(isinstance(item.get(k), str) and len(item[k].strip()) >= 8 for k in ("description", "requirement"))
                proof = item.get("_listing_evidence", state)
                self.evidence[stub.detail_url] = DirectJobEvidence(
                    stub, source.career_url, state["official_html"], proof["listing_url"],
                    proof["api_record"], full_body, state["proof_url"],
                    datetime.fromisoformat(proof["page_read_at"]) if proof.get("page_read_at") else None,
                    official_redirects=tuple(state.get("official_redirects", ())),
                    official_navigation=tuple(state.get("official_navigation", ())),
                )
                yield LeadCandidate(
                    provider=LeadProvider.OFFICIAL_ADAPTER, source_url=stub.detail_url,
                    source_id=stub.source_id, source_job_id=stub.source_job_id,
                    company_hint=source.company, title_hint=stub.title,
                    discovered_at=datetime.now(UTC), official_entry_url=source.career_url,
                )
            if not fill_pool:
                state["buffer"] = []
            if set(terms) <= set(state["exhausted"]) or pages_read >= 2 * len(terms):
                return
            current, term_index = state["page_number"], state["term_index"]
            keyword = terms[term_index]
            if keyword in state["exhausted"]:
                state["term_index"] = (term_index + 1) % len(terms)
                state["page_number"] += int(state["term_index"] == 0)
                continue
            parameters = {"keywords": keyword, "category": "", **filters, "type": "", "current": str(current), "limit": "10", "functionCategory": "", "tag": ""}
            # These portals decode URI components and keep '+' literally.
            # Encode spaces as %20 so the actual API keyword stays unchanged.
            listing_url = base + "?" + urlencode(parameters, quote_via=quote)
            self.read_sources.add(source.id)
            if fill_pool and state["buffer"]:
                try:
                    page = await asyncio.wait_for(self.browser.read_search_listing(listing_url),
                                                  max(.01, remaining - rank_reserve - .5))
                except TimeoutError:
                    # Existing rows remain usable; leave the unread term cursor
                    # untouched and emit the shortlist before the company deadline.
                    sampled_terms.update(terms)
                    continue
            else:
                page = await self.browser.read_search_listing(listing_url)
            if not same_origin(page.final_url, base) or (hiring_scope(base) and not within_scope(page.final_url, hiring_scope(base))):
                raise SourcePayloadError("招聘结果发生跨站跳转")
            observed_urls = {urlsplit(link.url).path for link in extract_html_links(page.raw_html, base_url=page.final_url) if urlsplit(link.url).hostname == parsed.hostname}
            accepted = False
            for record in page.recruitment_api:
                if not same_origin(record["url"], base) or urlsplit(record["url"]).path != "/api/v1/search/job/posts" or record["payload"].get("code") != 0:
                    continue
                # Ignore startup/unfiltered responses and retain the actual query.
                request = record["request"]
                if request.get("keyword", "").casefold() != keyword.casefold():
                    continue
                if request.get("offset") != (current - 1) * 10 or request.get("limit") != 10:
                    continue
                expected_cities = set(filter(None, filters["location"].split(",")))
                expected_subjects = set(filter(None, filters["project"].split(",")))
                if set(request.get("location_code_list") or []) != expected_cities or set(request.get("subject_id_list") or []) != expected_subjects:
                    continue
                data = record["payload"].get("data") or {}
                items = data.get("job_post_list") or []
                if not isinstance(items, list):
                    raise SourcePayloadError("官网岗位列表格式变化")
                accepted = True
                pending = []
                invalid_items = False
                for item in items:
                    try:
                        stub = payload_stub(item, company=source.company, listing_url=base)
                    except SourcePayloadError:
                        invalid_items = True
                        continue
                    if stub.source_job_id in state["seen_ids"]:
                        continue
                    if urlsplit(stub.detail_url).path not in observed_urls:
                        invalid_items = True
                        continue
                    pending.append({**item, "_listing_evidence": {"api_record": record,
                        "listing_url": listing_url, "page_read_at": datetime.now(UTC).isoformat()}})
                def priority(item):
                    stub = payload_stub(item, company=source.company, listing_url=base)
                    match = classify_discovery_job(stub, query=self.query, primary=False)
                    return ({"matched": 0, "pending": 1, "excluded": 2}[match.filter_status], -match.preference_score)
                pending.sort(key=priority)
                pooled = {str(item["id"]): item for item in [*state["buffer"], *pending]}
                state.update(buffer=list(pooled.values()), api_record=record, listing_url=listing_url,
                             page_read_at=datetime.now(UTC).isoformat())
                if invalid_items:
                    # Keep the page cursor in place until the site can provide
                    # verifiable rows; never claim complete coverage for skipped rows.
                    self.save(source, state)
                    if self._use_dom_listing(source, state, page):
                        async for candidate in self._html_pages(source, state):
                            yield candidate
                        return
                    raise SourcePayloadError("官网部分岗位未能核验，当前页进度已保留")
                total = data.get("count", data.get("total"))
                # Duplicates or unobserved links are not evidence of exhaustion.
                if not items or (type(total) is int and total <= (current - 1) * 10 + len(items)):
                    state["exhausted"] = list(set(state["exhausted"]) | {keyword})
                break
            if not accepted:
                if self._use_dom_listing(source, state, page):
                    async for candidate in self._html_pages(source, state):
                        yield candidate
                    return
                raise SourcePayloadError("未读取到与当前筛选和页码一致的官网响应")
            self.fresh_sources.add(source.id)
            state["term_index"] = (term_index + 1) % len(terms)
            state["page_number"] += int(state["term_index"] == 0)
            state["pages_checked"] += 1
            pages_read += 1
            sampled_terms.add(keyword)
            self.save(source, state)


    def _use_dom_listing(self, source, state, page):
        """An unusable API must not discard readable official DOM candidates."""
        capabilities = inspect_listing(page.raw_html, url=page.final_url)
        links = [link for link in capabilities.jobs if allowed_listing_url(link.url, state["base"])]
        if not links:
            return False
        cards = listing_card_texts(page.raw_html, url=page.final_url, job_urls=[link.url for link in links])
        state["protocol_checkpoint"] = {key: state.get(key) for key in
            ("reader_kind", "base", "filters", "page_number", "term_index", "exhausted", "buffer")}
        seed = {"scope_url": state["base"], "proof_url": state["proof_url"], "official_html": state["official_html"],
                "official_redirects": state.get("official_redirects", []), "official_navigation": state.get("official_navigation", [])}
        state.update(reader_kind="html", dom_fallback=True,
            buffer=[{"id": link.url, "title": link.text, "listing_text": cards.get(link.url, link.text)} for link in links
                    if canonical_job_url(link.url) not in state["checked_urls"]],
            listing_url=page.final_url, listing_html=page.raw_html, page_read_at=datetime.now(UTC).isoformat(),
            html_queue=[{**seed, "url": url} for url in capabilities.next_urls if allowed_listing_url(url, state["base"])],
            html_last_page={**seed, "url": page.final_url}, html_seen_pages=[page.final_url],
            html_blocked="pagination_unresolved" if capabilities.pagination_unresolved else "listing_boundary")
        self.fresh_sources.add(source.id)
        self.save(source, state)
        self.on_event("listing_reader_fallback", {"source_id": source.id, "candidate_count": len(state["buffer"]),
            "summary": "列表接口未能解析，改用同页已观察到的官方岗位链接，分页进度保留"})
        return True


def same_origin(url, expected):
    left, right = urlsplit(url), urlsplit(expected)
    return (left.scheme, left.netloc) == (right.scheme, right.netloc)
