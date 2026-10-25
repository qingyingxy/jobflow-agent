"""Bounded official announcement discovery; search snippets never become facts."""
import asyncio
import hashlib
import heapq
import json
import re
from datetime import UTC, datetime
from time import monotonic
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from src.services.campaign_entry import VERSION as ENTRY_VERSION
from src.services.campaign_entry import entry_campaign
from src.services.campaign_job_presence import check_result, job_observation
from src.services.campaign_navigation import (
    announcement_link,
    irrelevant_document,
    job_filter_url,
    navigation_candidate,
)
from src.services.campaign_parser import (
    VERSION,
    explicit_campaign_title,
)
from src.services.campaign_service import effective_status
from src.services.company_evidence_reader import CompanyEvidenceReader
from src.services.company_registry import within_company_source
from src.services.job_url import canonical_job_url
from src.services.lead_presentation import discovery_kind
from src.services.recruitment_listing import (
    allowed_listing_url,
    observed_hiring_redirect,
)
from src.services.recruitment_trust import ATS_DOMAINS, hiring_scope, within_scope


def campaign_url_key(url):
    """Deduplicate promotions without changing the URL actually read or trusted."""
    parts = urlsplit(canonical_job_url(url))
    def clean(query):
        return urlencode([(k, v) for k, v in parse_qsl(query, keep_blank_values=True)
                          if k.casefold() not in {"referral_code", "referralcode", "recommendcode"}])
    fragment = parts.fragment
    if fragment.startswith(("/", "!/")):
        prefix = "!" if fragment.startswith("!") else ""
        route = urlsplit(fragment.removeprefix("!"))
        fragment = prefix + urlunsplit(("", "", route.path, clean(route.query), ""))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, clean(parts.query), fragment))


def official_url(url, source):
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
            return False
        # Shared campus publishers are scoped to the registered employer's path.
        registered = urlsplit(source.career_url)
        if any(registered.hostname == root or (registered.hostname or "").endswith("." + root) for root in ATS_DOMAINS) and not hiring_scope(source.career_url):
            return False
        if registered.hostname in {"campus.51job.com", "special.zhaopin.com"}:
            prefix = "/" + registered.path.strip("/").split("/")[0] + "/"
            return parsed.hostname == registered.hostname and (parsed.path.rstrip("/") + "/").startswith(prefix)
        return within_company_source(url, source)
    except (ValueError, TypeError):
        return False


class CampaignReader:
    def __init__(self, reader, browser, parser, provider_factory, *, entry_parser=None, time_budget=90):
        self.pages = CompanyEvidenceReader(reader, browser=browser, on_event=lambda *_: None,
                                           text_limit=120000, collect_actions=True, max_host_failures=2)
        # Cover the announcement hubs as well as one live job, within the same total time budget.
        self.pages.browser_remaining = 8
        self.pages.browser_timeout = 18
        self.parser, self.provider_factory = parser, provider_factory
        self.entry_parser, self.time_budget = entry_parser, time_budget
        self.on_observation = None
        self.diagnostics = []

    async def check(self, source, year, cache):
        started = monotonic()
        initial_model_calls = sum(getattr(parser, "model_calls", 0) for parser in (self.parser, self.entry_parser))
        visited, queued, pending, found, errors, next_cache = set(), set(), [], {}, [], {}
        queued_metadata = {}
        discovery_keys, discovery_read = set(), set()
        scopes, exact_links, origins, searches = [], set(), set(), set()
        parsed_pages, serial, stagnant, pages_read = 0, 0, 0, 0
        metrics = {"duplicate_urls_skipped": 0, "parse_calls": 0, "parse_cache_hits": 0,
                   "parse_timeouts": 0, "first_campaign_ms": None, "first_verified_entry_ms": None,
                   "first_campus_jobs_ms": None,
                   "duplicate_content_skipped": 0, "empty_listings": 0, "parse_retries": 0,
                   "read_ms": 0, "parse_ms": 0, "search_ms": 0, "navigation_pages": 0}
        content_cache, deferred = {}, {}
        resume = {campaign_url_key(item["url"]): item for item in cache.get("pending_checks", [])[:8]
                  if isinstance(item, dict) and isinstance(item.get("url"), str)}
        stop_reason = "no_more_evidence"

        def resume_priority(item):
            if discovery_kind(item["url"]) == "job":
                return -6 if item.get("reason") != "queued" else -1
            return -3 if item.get("entry") else -2

        recovery_origins = {campaign_url_key(item["origin_url"]): item["origin_url"] for item in resume.values()
                            if item.get("origin_url") and official_url(item["origin_url"], source)}

        def allowed(url):
            try:
                parsed = urlsplit(url)
                if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
                    return False
                return official_url(url, source) or url in exact_links or any(within_scope(url, scope) for scope in scopes)
            except (ValueError, TypeError):
                return False

        def recovered_job_allowed(url):
            if allowed(url):
                return True
            # A custom-domain ATS can use a job fragment on the exact portal
            # document linked by this run's official page. Do not broaden its path.
            target = urlsplit(url)
            for anchor in exact_links:
                origin = urlsplit(anchor)
                if (target.path.rstrip('/') == origin.path.rstrip('/')
                        and allowed_listing_url(url, anchor)):
                    exact_links.add(url)
                    return True
            return False

        def accept_read(page, requested):
            if not page:
                return False
            final = page["url"]
            if allowed(final):
                return True
            if not allowed(requested):
                return False
            # Follow actual public redirects, without granting a shared ATS host or unrelated origin.
            if observed_hiring_redirect(requested, final, page.get("redirect_chain", [])):
                scopes.append(hiring_scope(final))
                origins.add(requested)
                return True
            if requested in exact_links and allowed_listing_url(final, requested):
                exact_links.add(final)
                return True
            return False

        def enqueue(url, label="", *, priority=5, entry=False, context=None):
            nonlocal serial
            if not allowed(url):
                return False
            key = campaign_url_key(url)
            if announcement_link(url, label):
                context = {**(context or {}), "announcement": True}
            if re.search(r"实习|春招|春季招聘|社会招聘|社招|登录|注册|个人中心|我的申请|我的投递|投递记录|申请记录|简历中心|/(?:intern|social|privacy|culture|life|resume|login|signin|register|personal|account)(?:[/?#.]|$)|(?:[?&])recruitType=INTERN(?:&|$)", label + " " + url, re.IGNORECASE):
                return False
            if re.search(r"帮助|常见问题|须知|招聘流程|宣讲|/(?:faq|help|process)", label + " " + url, re.IGNORECASE):
                priority = max(priority, 8)
            # Keep navigation available until a concrete campus job has been found.
            discovery = priority < 8 and not job_filter_url(url) and discovery_kind(url, label, observed_title=True) != "job"
            if discovery:
                discovery_keys.add(key)
            if key in visited:
                metrics["duplicate_urls_skipped"] += 1
                return False
            if key in queued:
                old_entry, old_context = queued_metadata[key]
                queued_metadata[key] = (entry or old_entry, context if context and not old_context else old_context)
                metrics["duplicate_urls_skipped"] += 1
                return False
            serial += 1
            heapq.heappush(pending, (priority, serial, key, url))
            queued.add(key)
            queued_metadata[key] = (entry, context or {})
            return True

        def observe(facts, url):
            key = (facts["title"], facts["batch"], url)
            def evidence_score(value):
                entry = value.get("entry") or {}
                return (8 * (entry.get("status") == "open") + 4 * bool(entry)
                        + 2 * bool(value.get("year_quote")) + bool(value.get("starts") or value.get("deadline")))
            changed = key not in found or evidence_score(facts) > evidence_score(found[key][0])
            found[key] = (facts, url)
            elapsed = round((monotonic() - started) * 1000)
            if metrics["first_campaign_ms"] is None:
                metrics["first_campaign_ms"] = elapsed
            if (facts.get("entry") or {}).get("job_presence") == "found" and metrics["first_campus_jobs_ms"] is None:
                metrics["first_campus_jobs_ms"] = elapsed
            now = datetime.now(UTC)
            if (metrics["first_verified_entry_ms"] is None and effective_status(facts, now, now) == "open"
                    and (facts.get("entry") or {}).get("status") == "open"):
                metrics["first_verified_entry_ms"] = elapsed
            if self.on_observation:
                self.on_observation(facts, url)
            return changed

        async def bounded(coro, limit, stage=None):
            phase_started = monotonic()
            try:
                return await asyncio.wait_for(coro, timeout=max(.1, min(limit, self.time_budget - (monotonic() - started))))
            finally:
                if stage:
                    metrics[stage + "_ms"] += round((monotonic() - phase_started) * 1000)

        class ParseDeferred(Exception):
            pass

        async def parse_page(parser, page, limit, is_entry):
            for attempt in range(2):
                remaining = self.time_budget - (monotonic() - started)
                if remaining < 8:
                    raise ParseDeferred()
                metrics["parse_calls"] += 1
                try:
                    return await bounded(parser.parse(page, year), limit, "parse")
                except TimeoutError as error:
                    record_error("parse", error, page["url"])
                    if attempt or not is_entry or discovery_kind(page["url"]) != "job" or self.time_budget - (monotonic() - started) < limit:
                        raise
                    metrics["parse_retries"] += 1

        def record_error(stage, error, url=None):
            self.diagnostics.append({"stage": stage, "url": url, "type": type(error).__name__,
                "code": getattr(error, "code", None), "status_code": getattr(error, "details", {}).get("status_code")})
            if stage == "parse" and isinstance(error, TimeoutError):
                metrics["parse_timeouts"] += 1

        old_pages = {campaign_url_key(url): item for url, item in cache.get("pages", {}).items()}
        known_jobs = [url for url in cache.get('urls', [])[:6]
                      if (cache.get('pages', {}).get(url, {}).get('entry_observation') or {}).get('kind') == 'job'
                      and bool((cache['pages'][url]['entry_observation'] or {}).get('job_titles'))]

        for item in resume.values():
            if official_url(item["url"], source):
                enqueue(item["url"], priority=resume_priority(item), entry=bool(item.get("entry")),
                        context={"recovery_origin": item.get("origin_url")})
        for url in recovery_origins.values():
            enqueue(url, priority=-5)
        for url in cache.get("origins", [])[:4]:
            if official_url(url, source):
                enqueue(url, priority=0)
        for url in cache.get("urls", [])[:4]:
            if official_url(url, source):
                prior_entry = cache.get("pages", {}).get(url, {}).get("entry_observation")
                # A previously observed list/job can answer the company question on its own.
                known_job = prior_entry and bool(prior_entry.get('job_titles'))
                enqueue(url, priority=-4 if known_job else 1, entry=bool(prior_entry))
        enqueue(source.career_url, priority=2, entry=bool(re.search(r"/jobs?/|/positions|/opportunities", source.career_url)))
        while monotonic() - started < self.time_budget - 1:
            now = datetime.now(UTC)
            if any((job_observation(fact) or {}).get("status") == "found" for fact, _ in found.values()):
                stop_reason = "campus_jobs_found"
                break
            verified_entry = any(effective_status(fact, now, now) == "open" and fact.get("entry", {}).get("status") == "open" for fact, _ in found.values())
            discovery_pending = [item for item in pending if item[2] in discovery_keys and item[2] not in visited]
            if verified_entry and not discovery_pending:
                stop_reason = "verified_application_entry" if discovery_keys <= discovery_read else "announcement_check_incomplete"
                break
            if (isinstance(self.pages, CompanyEvidenceReader) and self.pages.cooling(source.career_url, "http")
                    and not any(not self.pages.cooling(item[3], "http") for item in pending)):
                stop_reason = "source_unavailable"
                break
            # Search by the missing evidence instead of spending a fixed number of page reads.
            if not verified_entry and (not pending or stagnant >= 3) and self.provider_factory is not None:
                purpose = "announcement" if not found else "entry" if not exact_links else "availability"
                remaining = [p for p in (purpose, "entry", "announcement", "availability") if p not in searches]
                if remaining:
                    purpose = remaining[0]
                    searches.add(purpose)
                    suffix = {"announcement": f"{year} 校园招聘 秋招 岗位",
                              "entry": "校园招聘 应届生 职位列表 招聘入口",
                              "availability": "校园招聘 在招岗位 职位列表"}[purpose]
                    domains = [urlsplit(source.career_url).hostname]
                    if purpose == "availability":
                        domains.extend(scope[0] for scope in scopes)
                    query = f'{source.company} {suffix} (' + " OR ".join(f"site:{host}" for host in dict.fromkeys(domains)) + ")"
                    self.diagnostics.append({"stage": "search", "purpose": purpose, "query": query})
                    try:
                        provider = self.provider_factory(query, [source.id], sources=[source])
                        provider.search_purpose = "campaigns"
                        candidates = await bounded(provider.discover(), 18, "search")
                        for candidate in candidates:
                            url = candidate.source_url
                            label = getattr(candidate, "title", "") or ""
                            candidate = navigation_candidate(url, label, year, observed=False)
                            if candidate:
                                priority, entry = candidate
                                enqueue(url, label, priority=priority + 2, entry=entry)
                    except Exception as error:  # noqa: BLE001 - preserve previously checked sources
                        record_error("search", error)
                        errors.append("部分补搜未完成")
                    stagnant = 0
                elif not pending or stagnant >= 3:
                    stop_reason = "no_new_evidence"
                    break
            if not pending:
                if self.provider_factory is not None and len(searches) < 3:
                    continue
                break
            if verified_entry:
                candidate = min(discovery_pending)
                pending.remove(candidate)
                heapq.heapify(pending)
                _, _, key, url = candidate
            else:
                _, _, key, url = heapq.heappop(pending)
            is_entry, context = queued_metadata[key]
            visited.add(key)
            pages_read += 1
            if pages_read > 50:  # Circuit breaker only; normal stopping uses time and evidence.
                stop_reason = "navigation_loop_limit"
                break
            try:
                page = await bounded(self.pages.read(url), 24, "read")
                if not accept_read(page, url):
                    errors.append("部分官网页面未能读取或归属待核验")
                    deferred[key] = {"url": url, "entry": is_entry, "reason": "read_failed"}
                    stagnant += 1
                    continue
                announcement_shell = context.get('announcement') and len(page['text'].strip()) < 700
                render_entry = is_entry and (page.get("needs_render") or page.get("needs_navigation")
                                             or urlsplit(url).fragment.startswith(("/", "!/")))
                if (render_entry or announcement_shell) and isinstance(self.pages, CompanyEvidenceReader) and page.get("method") == "http":
                    # HTTP drops SPA fragments. Render the actual entry route before deduping its final URL.
                    page = await bounded(self.pages.read(url, force_browser=True), 24, "read")
                    if not accept_read(page, url):
                        errors.append("部分招聘入口未能读取或归属待核验")
                        deferred[key] = {"url": url, "entry": is_entry, "reason": "read_failed"}
                        stagnant += 1
                        continue
                    if urlsplit(url).fragment.startswith(("/", "!/")) and page.get("method") == "http":
                        deferred[key] = {"url": url, "entry": True, "reason": "content_missing"}
                        errors.append("部分招聘入口正文尚未加载")
                        stagnant += 1
                        continue
                final_key = campaign_url_key(page["url"])
                if final_key != key and final_key in visited:
                    if final_key in discovery_read:
                        discovery_read.add(key)
                    metrics["duplicate_urls_skipped"] += 1
                    stagnant += 1
                    continue
                visited.add(final_key)
                if announcement_shell and page.get('method') == 'http':
                    deferred[key] = {'url': url, 'entry': is_entry, 'reason': 'content_missing'}
                    errors.append('部分公告正文尚未加载')
                    stagnant += 1
                    continue
                if (is_entry and len(page["text"].strip()) < 100 and not page.get("links")
                        and page.get("listing_state") not in {"populated", "empty"}
                        and not re.search(r"岗位职责|职位描述|任职要求|职位要求|校园招聘|应届|校招", page["text"])):
                    # An unloaded shell cannot become job evidence, nor deserves a model call.
                    self.diagnostics.append({"stage": "read", "url": url, "code": "application_content_missing"})
                    errors.append("部分招聘入口正文尚未加载")
                    deferred[key] = {"url": url, "entry": True, "reason": "content_missing"}
                    stagnant += 1
                    continue
            except TimeoutError as error:
                record_error("read", error, url)
                errors.append("部分页面读取超时")
                deferred[key] = {"url": url, "entry": is_entry, "reason": "read_timeout"}
                stagnant += 1
                continue
            changed = False
            incomplete_navigation = (page.get('method') == 'http'
                                     and (page.get('needs_render') or page.get('needs_navigation'))
                                     and isinstance(self.pages, CompanyEvidenceReader))
            text = page.get("title", "") + "\n" + page["text"]
            # Missing link/card selectors do not prove a rendered list has no jobs.
            # Let the scoped text parser inspect custom rows such as management trainees.
            rendered_listing = page.get("method") == "browser" and page.get("listing_state") == "unloaded"
            is_entry = is_entry or rendered_listing or page.get("listing_state") in {"populated", "empty"}
            digest = hashlib.sha256((VERSION + ENTRY_VERSION + str(year) + str(is_entry) + text + json.dumps(page.get("application_actions", []))).encode()).hexdigest()
            old = old_pages.get(key)
            content_key = (urlsplit(page["url"]).hostname, digest)
            # Identical listing bodies can reuse parsing, while each URL's navigation is still inspected.
            if not old and discovery_kind(page["url"]) != "job" and content_key in content_cache:
                old = content_cache[content_key]
                metrics["duplicate_content_skipped"] += 1
            facts, observation = [], None
            partial = False
            defer_budget = False
            actionable = [navigation_candidate(link.url, link.text, year) for link in page.get("links", [])
                          if link.url in page.get("hiring_links", []) and campaign_url_key(link.url) != final_key]
            navigation_only = (not rendered_listing and page.get("listing_state") != "populated" and not context.get('announcement') and discovery_kind(page["url"]) != "job" and any(c and c[0] <= 2 for c in actionable)
                               and (key in recovery_origins or final_key in recovery_origins or (
                                   not re.search(r"公告|简章|正式启动|正式开启", page.get("title", ""))
                                   and not re.search(r"网申进行中|当前接受申请|申请状态|(?:网申|投递|报名|申请)(?:时间|截止|日期)|招聘时间.{0,40}(?:开启|开放|截止)", text))))
            empty = page.get("listing_state") in {"empty", "unloaded"}
            irrelevant = irrelevant_document(page, year)
            try:
                if irrelevant:
                    self.diagnostics.append({"stage": "filter", "url": page["url"], "code": "unrelated_recruitment_document"})
                elif navigation_only:
                    metrics["navigation_pages"] += 1
                elif empty and (page.get("listing_state") == "unloaded" and not rendered_listing or not self.entry_parser):
                    metrics["empty_listings"] += 1
                    self.diagnostics.append({"stage": "read", "url": page["url"], "code": "listing_" + page["listing_state"]})
                elif is_entry and self.entry_parser:
                    if old and old.get("hash") == digest:
                        metrics["parse_cache_hits"] += 1
                        observation = old.get("entry_observation")
                    else:
                        observation = await parse_page(self.entry_parser, page, 24, True)
                    fact = entry_campaign(observation, page, source, year, context)
                    if fact:
                        if rendered_listing and fact["entry"].get("job_presence") == "found":
                            page["listing_state"], page["needs_render"], empty = "populated", False, False
                        result_url = context.get("campaign_url", page["url"]) if context.get("campaign") else page["url"]
                        changed |= observe(fact, result_url)
                    if observation and observation["kind"] == "project" and not fact:
                        facts = await parse_page(self.parser, page, 26, False)
                else:
                    if old and old.get("hash") == digest:
                        metrics["parse_cache_hits"] += 1
                        facts = old["facts"]
                    else:
                        facts = await parse_page(self.parser, page, 26, False)
                parsed_pages += 1
            except Exception as error:  # noqa: BLE001 - model failure is pending, not closure
                if not isinstance(error, TimeoutError):
                    record_error("parse_deferred" if isinstance(error, ParseDeferred) else "parse", error, url)
                errors.append("部分内容尚未核验完成")
                deferred[key] = {"url": page["url"], "entry": is_entry,
                                 "reason": "remaining_budget" if isinstance(error, ParseDeferred) else "parse_failed"}
                defer_budget = isinstance(error, ParseDeferred)
                facts = [{**fact, "partial": True} for fact in explicit_campaign_title(page, source, year)]
                partial = True
            if not partial and not navigation_only and not empty and not irrelevant:
                next_cache[url] = {"hash": digest, "facts": facts, "entry_observation": observation}
                content_cache[content_key] = next_cache[url]
            if not partial:
                resume.pop(key, None)
                deferred.pop(key, None)
                if page.get("listing_state") != "unloaded" and not incomplete_navigation:
                    discovery_read.update((key, final_key))
                elif key in discovery_keys:
                    deferred[key] = {"url": url, "entry": is_entry, "reason": "content_missing"}
                    errors.append("部分公告入口正文尚未加载")
            for fact in facts:
                changed |= observe(fact, page["url"])
            parent = {"campaign": facts[0], "campaign_url": page["url"]} if len(facts) == 1 and not partial else context
            for link in ([] if irrelevant else page.get("links", [])):
                candidate = navigation_candidate(link.url, link.text, year)
                if not candidate:
                    continue
                priority, entry = candidate
                job_link = discovery_kind(link.url, link.text, observed_title=True) == "job"
                can_grant = (official_url(page["url"], source) or
                             (page["url"] in exact_links and allowed_listing_url(link.url, page["url"])))
                if not allowed(link.url) and can_grant:
                    # Only an observed public hiring link/control grants employer-scoped trust.
                    scope = hiring_scope(link.url)
                    if scope:
                        scopes.append(scope)
                    elif any((urlsplit(link.url).hostname or "").endswith(root) for root in ATS_DOMAINS):
                        continue
                    exact_links.add(link.url)
                    origins.add(page["url"])
                child_context = {**parent, "origin_url": page["url"], "link_text": link.text}
                if job_link and context and not facts:
                    child_context = {**context, "origin_url": context.get("origin_url", page["url"])}
                child_context["recovery_origin"] = page["url"] if official_url(page["url"], source) else context.get("recovery_origin")
                resume_item = resume.get(campaign_url_key(link.url))
                added = enqueue(link.url, link.text, priority=resume_priority(resume_item) if resume_item else priority,
                                entry=entry, context=child_context)
                changed |= added and entry
            # Cached external targets become eligible only after this run re-established their scope.
            for known_url in known_jobs:
                if recovered_job_allowed(known_url) and campaign_url_key(known_url) not in visited:
                    enqueue(known_url, priority=-4, entry=True,
                            context={'recovery_origin': page['url'] if official_url(page['url'], source)
                                     else context.get('recovery_origin')})
            for resume_key, item in list(resume.items()):
                if allowed(item["url"]) and resume_key not in visited:
                    enqueue(item["url"], priority=resume_priority(item), entry=bool(item.get("entry")),
                            context={"recovery_origin": item.get("origin_url")})
            stagnant = 0 if changed else stagnant + 1
            if defer_budget:
                stop_reason = "verification_deferred"
                break
        else:
            stop_reason = "time_budget"
        # A positive observation remains sufficient even if the budget expired just after parsing.
        if any((job_observation(fact) or {}).get("status") == "found" for fact, _ in found.values()):
            stop_reason = "campus_jobs_found"
        if stop_reason in {"time_budget", "navigation_loop_limit"}:
            errors.append("本轮检查额度已用完，已保留确认结果，可继续检查")
        useful = [url for url, item in next_cache.items() if item["facts"] or (item.get("entry_observation") or {}).get("kind") in {"job", "listing", "project"}]
        useful.sort(key=lambda url: (next_cache[url].get('entry_observation') or {}).get('kind') != 'job')
        outstanding = {key: {"url": url, "entry": queued_metadata[key][0], "reason": "queued"}
                       for _, _, key, url in pending if key not in visited
                       and (key in discovery_keys or queued_metadata[key][0] and stop_reason not in {
                           "verified_application_entry", "announcement_check_incomplete"})}
        unresolved = {**resume, **outstanding, **deferred}
        if stop_reason == "campus_jobs_found":
            unresolved = {}
        for pending_key, item in unresolved.items():
            _, context = queued_metadata.get(pending_key, (False, {}))
            if context.get("recovery_origin"):
                item["origin_url"] = context["recovery_origin"]
        pending_checks = sorted(unresolved.values(), key=resume_priority)[:8]
        metrics["deferred_checks"] = len(pending_checks)
        metrics["announcement_pages_read"] = len(discovery_keys & discovery_read)
        metrics["announcement_check_complete"] = bool(discovery_keys) and discovery_keys <= discovery_read
        job_check = check_result(list(found.values()), complete=not errors and not unresolved)
        return {"found": list(found.values()), "cache": {"pages": next_cache, "urls": useful[:6], "origins": sorted(origins)[:4],
                                                        "pending_checks": pending_checks, "job_check": job_check},
                "error": "；".join(dict.fromkeys(errors)) or None, "readable": parsed_pages > 0,
                "stats": {"pages_read": pages_read, "searches": len(searches), "stop_reason": stop_reason,
                          "model_calls": sum(getattr(parser, "model_calls", 0) for parser in (self.parser, self.entry_parser)) - initial_model_calls,
                          **metrics}}


def create_campaign_reader(settings, sources):
    from src.infrastructure.llm_client import create_structured_model_client
    from src.services.browser_job_reader import PlaywrightBrowserJobReader
    from src.services.campaign_agent import CampaignAgentReader
    from src.services.company_registry import company_source_hosts
    from src.services.url_reader import SafeHTTPReader
    from src.services.web_search_service import create_web_search_provider
    if settings.structured_model_provider == "fake":
        raise ValueError("需配置真实模型服务后更新秋招公告")
    reader = SafeHTTPReader(timeout_seconds=8, max_retries=0, proxy=settings.url_fetch_proxy,
        proxy_allowed_hosts=company_source_hosts(sources),
        proxy_allow_unlisted_hosts=settings.url_fetch_proxy_allow_unlisted_hosts)
    client = create_structured_model_client(settings.model_copy(update={"llm_timeout_seconds": 25, "llm_max_retries": 0}))
    browser = PlaywrightBrowserJobReader(timeout_seconds=10)
    class EntryBrowser:
        async def read_evidence(self, url):
            return await browser.read_agent_page(url)

        async def navigate_evidence(self, url, control):
            return await browser.read_agent_page(url, control=control)

        def diagnostics_for(self, url):
            return browser.diagnostics_for(url)
    return CampaignAgentReader(reader, EntryBrowser(), client, settings, create_web_search_provider)
