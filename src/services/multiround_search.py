from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager, nullcontext
from dataclasses import asdict, replace
from datetime import UTC, datetime
from time import monotonic
from urllib.parse import urlsplit
from uuid import uuid4

from src.config import get_settings
from src.domain.discovery import DiscoveryRun, SearchEvidence
from src.infrastructure.database import SessionLocal
from src.infrastructure.llm_client import create_structured_model_client
from src.services.browser_job_reader import PlaywrightBrowserJobReader
from src.services.company_registry import (
    enabled_company_source_hosts,
    enabled_company_sources,
    provider_source_options,
)
from src.services.discovery_matching import (
    apply_posting_availability,
    classify_discovery_job,
)
from src.services.discovery_sources import JobStub
from src.services.job_lead_service import JobLeadService, LeadVerificationFailure
from src.services.job_url import canonical_job_url
from src.services.lead_presentation import (
    discovery_kind,
    lead_discovery_kind,
    reference_link_reason,
)
from src.services.official_hiring_resolver import OfficialHiringResolver
from src.services.official_search_service import analyze_discovery_jobs
from src.services.recruitment_entry import expand_entry
from src.services.recruitment_trust import hiring_scope, within_scope
from src.services.search_decision import SearchDecisionPlanner
from src.services.search_pipeline import (
    SearchSnapshot,
    VerificationFailure,
    WaitForVerification,
    run_search_pipeline,
)
from src.services.search_planner import (
    build_agent_search_tasks,
    build_search_tasks,
    next_search_task,
)
from src.services.search_scheduling import candidate_priority, candidate_source
from src.services.url_reader import SafeHTTPReader


class SearchRequestTimeout(RuntimeError):
    """One request timed out; the workflow may still have search budget."""


def _transient_search_failure(error, evidence):
    if isinstance(error, (SearchRequestTimeout, TimeoutError)):
        return True
    if evidence.get("http_status") in {408, 429, 500, 502, 503, 504, 524}:
        return True
    return evidence.get("error_code") in {
        "ReadTimeout",
        "ConnectTimeout",
        "WriteTimeout",
        "PoolTimeout",
        "ConnectError",
        "ReadError",
        "RemoteProtocolError",
    }


def canonical_search_url(url: str) -> str:
    return canonical_job_url(url)


def is_recruitment_entry(url: str) -> bool:
    return discovery_kind(url) == "entry"


async def search_rounds(
    *, search, verify, report, max_rounds=6, seconds=300, target=15, clock=monotonic
):
    """Budget search and verification together; only distinct useful jobs count."""
    deadline = clock() + seconds
    seen_urls = set()
    useful_ids = set()
    known_ids = set()
    stop = "达到搜索轮数上限"
    for round_number in range(1, max_rounds + 1):
        remaining = deadline - clock()
        if remaining <= 0:
            stop = "达到搜索时间预算"
            break
        report(round_number, len(seen_urls), len(useful_ids), "正在搜索", None)
        try:
            candidates = await asyncio.wait_for(
                search(round_number, seen_urls), remaining
            )
        except TimeoutError:
            stop = "达到搜索时间预算"
            break
        except Exception:  # noqa: BLE001 - preserve previous rounds on provider failure
            report(
                round_number,
                len(seen_urls),
                len(useful_ids),
                "本轮搜索失败，继续下一轮",
                None,
            )
            continue
        for candidate in candidates:
            key = canonical_search_url(candidate.source_url)
            if key in seen_urls:
                continue
            remaining = deadline - clock()
            if remaining <= 0:
                stop = "达到搜索时间预算"
                break
            seen_urls.add(key)
            candidate = replace(candidate, source_url=key)
            try:
                result = await asyncio.wait_for(verify(candidate), remaining)
            except TimeoutError:
                stop = "达到搜索时间预算"
                break
            if result:
                job_id, useful = result
                known_ids.add(job_id)
                if useful:
                    useful_ids.add(job_id)
            report(round_number, len(seen_urls), len(useful_ids), "正在核验", None)
            if len(useful_ids) >= target:
                stop = "达到有效岗位目标"
                break
            if len(known_ids) >= 20:
                stop = "达到候选展示上限"
                break
        if stop != "达到搜索轮数上限":
            break
        report(
            round_number,
            len(seen_urls),
            len(useful_ids),
            "本轮完成，结果不足继续补搜",
            None,
        )
    report(round_number, len(seen_urls), len(useful_ids), "搜索结束", stop)
    return stop


async def execute_multiround_search(
    *,
    run_id,
    user_id,
    query,
    company_ids,
    query_tasks=None,
    analysis_limit=0,
    feedback_wait_seconds=None,
):
    from src.services.web_search_service import create_web_search_provider

    settings = get_settings()
    with SessionLocal() as session:
        run = session.get(DiscoveryRun, run_id)
        if run is None or run.user_id != user_id:
            return
        rounds = max(1, min(10, settings.web_search_max_rounds))
        seconds = max(1, min(900, settings.web_search_budget_seconds))
        target = max(1, min(20, settings.web_search_target_jobs))
        sources = enabled_company_sources(company_ids or None, session=session, user_id=user_id)
        from src.services.company_scope import in_company_scope

        scoped_sources = sources if company_ids else None
        other_sources = ([s for s in enabled_company_sources(session=session, user_id=user_id)
                          if s.id not in company_ids] if company_ids else [])

        def outside_selected_companies(candidate):
            return (scoped_sources is not None and not in_company_scope(candidate, scoped_sources)
                    and in_company_scope(candidate, other_sources))

        retrieval_query = query + ("；限定公司：" + "、".join(s.company for s in sources) if company_ids else "")
        provider = create_web_search_provider(retrieval_query, company_ids, **provider_source_options(company_ids, sources))
        service = JobLeadService(session)
        hosts = enabled_company_source_hosts(session=session, user_id=user_id)
        reader = SafeHTTPReader(
            timeout_seconds=8,
            max_retries=0,
            proxy=settings.url_fetch_proxy,
            proxy_allowed_hosts=hosts,
            proxy_allow_unlisted_hosts=settings.url_fetch_proxy_allow_unlisted_hosts,
        )
        browser = PlaywrightBrowserJobReader(timeout_seconds=15)
        matched = {}
        analysis_ids = []
        failures = []
        followup_links = []
        agent_enabled = settings.web_search_decision_mode == "agent"
        # Internal callers may supply the same code-owned candidates in controlled
        # comparisons; the public API keeps the normal mode-specific defaults.
        tasks = (
            list(query_tasks)
            if query_tasks is not None
            else (
                build_agent_search_tasks(retrieval_query, sources)
                if agent_enabled
                else build_search_tasks(retrieval_query, sources)
            )
        )
        completed_queries = set()
        duplicate_streak = 0
        search_history = []
        pending_retry = None
        retries_used = 0
        search_unavailable = False
        verification_errors = {}
        verified_summaries = []
        role_jobs = {}
        summary_indices = {}
        snapshot = SearchSnapshot(0, 0, 0, 0, seconds)
        search_stop_reason = None
        resuming_after_verification = False
        enqueue_discovered = None
        from src.services.search_goal_service import SearchGoalService
        from src.services.search_run_metrics import SearchRunMetrics

        metrics = SearchRunMetrics(run.started_at, run.library_baseline if run.library_baseline is not None
                                   else SearchGoalService(session).snapshot(user_id, query=query))
        run.usage_metrics = metrics.snapshot()

        def queue_ready(enqueue):
            nonlocal enqueue_discovered
            enqueue_discovered = enqueue

        def update_snapshot(value):
            nonlocal snapshot
            snapshot = value

        coverage = None

        def trace_event(kind, details):
            metrics.observe(kind, details)
            if coverage and kind in {"direct_search", "search_query"}:
                coverage.observe(details.get("source_id"), kind, details)
            if kind == "direct_search" and details.get("source_read_attempted"):
                metrics.source_read(details["source_id"], success=details.get("source_read_success", False),
                                    retry=details.get("source_retry", False))
            if kind == "queue_budget":
                failures.append("正文核验预算已用尽，剩余链接已保留待核验")
            if kind == "verification_deferred":
                from sqlalchemy import select

                from src.domain.discovery import JobLead

                pending = session.scalar(select(JobLead).where(
                    JobLead.user_id == user_id, JobLead.discovery_run_id == run_id,
                    JobLead.normalized_url == details["url"],
                ))
                if pending and not pending.job_posting_id:
                    pending.status = "DEFERRED"
                    pending.failure_code = details["error_code"]
                    pending.failure_reason = details["summary"]
                    from src.services.lead_retry import failed_state

                    pending.retry_state = failed_state(pending.retry_state, pending.failure_code)
                    if details.get("next_retry_at") and pending.retry_state.get("mode") not in {
                        "manual", "needs_adapter", "exhausted", "stopped",
                    }:
                        from src.services.lead_retry import utc_time

                        due = max(filter(None, (utc_time(details["next_retry_at"]),
                            utc_time(pending.retry_state.get("next_retry_at")))))
                        pending.retry_state = {**pending.retry_state, "mode": "cooldown",
                                               "next_retry_at": due.isoformat()}
                if details.get("error_code") not in {"company_target", "company_read_limit", "company_paused", "search_reference_deferred"}:
                    failures.append("部分来源暂缓核验，链接已保留，将在目标更新时继续处理")
            trace = list(run.agent_trace or [])
            error = details.get("error_code")
            if error in {"company_target", "company_read_limit", "company_paused", "search_reference_deferred"}:
                error = None  # An intentional company pause is not a source failure.
            if error and kind in {"verification", "page_verification", "entry_timeout"}:
                verification_errors[error] = verification_errors.get(error, 0) + 1
            is_decision = kind.startswith("search_decision")
            trace.append(
                {
                    "phase": (
                        "fallback"
                        if kind == "search_decision_fallback"
                        else "plan"
                        if is_decision
                        else "observe"
                    ),
                    "tool": kind,
                    "outcome": "failed" if error else "completed",
                    "observation": details.get("summary")
                    or f"{kind}：{details.get('url', '')}",
                    "decision": (details.get("reason") or "")
                    if is_decision
                    else (
                        "已保留证据；失败不删除已发现链接"
                        if error
                        else "继续独立查询与正文核验"
                    ),
                    "duration_ms": details.get("duration_ms"),
                    "error_code": error,
                    "occurred_at": datetime.now(UTC).isoformat(),
                    "details": details,
                }
            )
            run.agent_trace = trace
            run.usage_metrics = metrics.snapshot()
            session.commit()

        @contextmanager
        def verification_stage(stage, url):
            started = monotonic()
            error_code = None
            try:
                yield
            except BaseException as error:
                error_code = getattr(error, "code", type(error).__name__)
                raise
            finally:
                trace_event(
                    "verification_stage",
                    {
                        "url": url,
                        "stage": stage,
                        "duration_ms": int((monotonic() - started) * 1000),
                        "error_code": error_code,
                    },
                )

        def decision_client():
            # One counted decision attempt must mean one HTTP request. Repairs
            # are budgeted explicitly by SearchDecisionPlanner, never hidden in
            # the shared client's transport retry loop.
            return create_structured_model_client(
                settings.model_copy(
                    update={
                        "llm_max_retries": 0,
                        "llm_timeout_seconds": min(
                            settings.llm_timeout_seconds,
                            settings.web_search_decision_timeout_seconds,
                        ),
                    }
                )
            )

        from src.services.direct_recruitment_search import DirectRecruitmentSearch
        from src.services.job_role_review import JobRoleReviewer, load_role_review
        from src.services.search_resources import BoundedReader

        reader = BoundedReader(reader, limit=settings.web_search_http_concurrency,
                               stage="http", on_event=trace_event)
        browser = BoundedReader(browser, limit=settings.web_search_browser_concurrency,
                                stage="browser", on_event=trace_event)
        hiring_resolver = OfficialHiringResolver(sources=sources, reader=reader, browser=browser)
        role_reviewer = JobRoleReviewer(settings, on_event=trace_event)
        from src.services.search_goal_service import SearchGoalService
        from src.services.source_understanding import (
            SourceUnderstanding,
            pending_review_fields,
            queue_review,
        )
        known_job_urls = {canonical_search_url(job.source_url) for job in SearchGoalService(session).postings(user_id)
                          if job.source_url}
        understanding = SourceUnderstanding(settings, on_event=trace_event, query=query, conditions=run.goal_conditions,
                                              known_urls=known_job_urls, include_qualifications=False)
        service.understanding = understanding
        if hasattr(browser, "read_dynamic_listing"):
            browser.search_understanding = understanding
        from src.services.company_coverage import CompanyCoverage
        from src.services.company_search_progress import CompanyProgressStore

        progress_store = CompanyProgressStore(session, user_id=user_id,
            goal_id=run.search_goal_id, version=run.search_goal_version)
        from src.services.entry_expansion_budget import EntryExpansionBudget

        entry_budget = EntryExpansionBudget(
            seconds=min(settings.web_search_entry_budget_seconds, seconds / 3),
            item_seconds=settings.web_search_entry_item_seconds,
            limit=max(1, min(20, settings.web_search_entry_limit)),
            empty_limit=settings.web_search_entry_empty_limit,
            states=progress_store.load_entries(), checkpoint=progress_store.save_entry,
        )
        continued_company = run.continued_company_id
        coverage = CompanyCoverage(
            sources=sources, store=progress_store, query=query,
            batch_size=min(settings.web_search_company_batch_size, rounds),
            continued_company=continued_company,
        ) if run.search_goal_id and query_tasks is None else None
        prior_states = coverage.direct_states() if coverage else progress_store.load() if continued_company else {}
        candidate_waiters = {}
        candidate_outcomes = {}
        bootstrap_started = asyncio.Event()
        source_active, reservations, matched_sources = {}, {}, {}
        source_reads = {}
        historical_candidates = set()
        cached_reviews = {}

        def source_group(url, company=None):
            host = urlsplit(url).hostname
            for source in sources:
                state = direct.states.get(source.id, {})
                scope = hiring_scope(source.career_url)
                if scope:
                    if within_scope(url, scope):
                        return source.id
                    continue
                if (company and company == source.company) or host in {
                    urlsplit(source.career_url).hostname,
                    urlsplit(state.get("base", "")).hostname,
                }:
                    return source.id
                listing_url = state.get("listing_url", "")
                listing_scope = hiring_scope(listing_url)
                if listing_scope and within_scope(url, listing_scope):
                    return source.id
            return "".join(hiring_scope(url) or ()) or host or url

        def candidate_done(candidate, result, error):
            if error == "verification_timeout":
                from sqlalchemy import select

                from src.domain.discovery import JobLead, JobLeadStatus

                with SessionLocal() as retry_session:
                    pending = retry_session.scalar(select(JobLead).where(
                        JobLead.user_id == user_id, JobLead.discovery_run_id == run_id,
                        JobLead.normalized_url == candidate.source_url,
                    ))
                    if pending and not pending.job_posting_id:
                        JobLeadService(retry_session)._record_failure(
                            user_id=user_id, lead_id=pending.id, status=JobLeadStatus.FAILED,
                            code=error, reason="本次页面读取超时",
                        )
            group = reservations.pop(candidate.source_url, None)
            if group is not None:
                source_active[group] -= 1
            key = canonical_search_url(candidate.source_url)
            if result:
                candidate_outcomes[key] = result
                posting = role_jobs[result[0]][1] if result[0] in role_jobs else None
                url = posting.source_url if posting else candidate.source_url
                company = posting.company if posting else candidate.company_hint
                group = source_group(url or '', company)
                if result[1]:
                    matched_sources[result[0]] = group
                else:
                    matched_sources.pop(result[0], None)
                if coverage:
                    coverage.record_match(group, url, bool(result[1]))
            waiter = candidate_waiters.get(key)
            if waiter is not None and not waiter.done():
                waiter.set_result(bool(result[1]) if result else None)
            direct.record_result(candidate, bool(result[1]) if result else None)

        async def await_candidate(candidate):
            # Stopping a producer must not cancel a consumer's acknowledgement.
            return await asyncio.shield(candidate_waiters[canonical_search_url(candidate.source_url)])

        direct = DirectRecruitmentSearch(
            sources=coverage.sources if coverage else sources,
            query=query,
            reader=reader,
            browser=browser,
            on_event=trace_event,
            max_jobs=settings.web_search_entry_max_details,
            target_per_company=settings.web_search_company_target,
            company_seconds=settings.web_search_company_seconds,
            company_concurrency=settings.web_search_company_concurrency,
            verification_seconds=settings.web_search_verification_budget_seconds,
            understanding=understanding,
            known_urls=known_job_urls,
            states=prior_states,
            checkpoint=coverage.save_direct if coverage else progress_store.save,
            company_done=lambda company: source_reads.get(company, 0) >= settings.web_search_company_target,
        )
        concurrent_direct = bool(coverage and settings.web_search_direct_sources_enabled and direct.supported)
        from math import ceil

        from src.services.search_scheduling import CompanyCandidateGate
        shortlist_sources = {source.id for source in direct.sources} if settings.web_search_direct_sources_enabled and direct.supported else set()
        shortlist_gate = CompanyCandidateGate(quota=settings.web_search_company_target,
            wait_seconds=min(120, settings.web_search_company_seconds * ceil(max(1, len(shortlist_sources)) / settings.web_search_company_concurrency) + 5))
        shortlist_finished = False
        hiring_resolver.entry_states = lambda: {**progress_store.load(), **direct.states}

        def remember_resolved_entry(source, entry):
            state = direct.states.setdefault(source.id, {})
            state["verified_entry"] = entry
            if coverage:
                coverage.save_direct(source.id, state)
            else:
                progress_store.save(source.id, state)

        hiring_resolver.on_entry = remember_resolved_entry
        if coverage and not (settings.web_search_direct_sources_enabled and direct.supported):
            direct.states = {}
        if coverage:
            trace_event("company_batch", {
                "source_ids": [source.id for source in coverage.sources],
                "summary": "本批查询：" + "、".join(source.company for source in coverage.sources),
                "strategy": "saved_company_rotation",
            })

        async def bootstrap(enqueue):
            bootstrap_started.set()
            def publish(candidates):
                for candidate in candidates:
                    service.capture_candidate(
                        user_id=user_id, discovery_run_id=run_id, candidate=candidate
                    )
                enqueue(candidates)

            if run.search_goal_id and (not continued_company or coverage):
                from src.services.search_goal_service import SearchGoalService

                goals = SearchGoalService(session)
                resumed = goals.resume_candidates(
                    user_id, goal_id=run.search_goal_id, version=run.search_goal_version,
                    current_run_id=run_id,
                    company_id=continued_company, source_group=source_group,
                    company_sources=scoped_sources,
                )
                refreshed = goals.refresh_candidates(user_id, query=run.search_query,
                    conditions=run.goal_conditions, company_id=continued_company,
                    limit=settings.web_search_semantic_history_max_calls if understanding.primary else 8,
                    source_group=source_group, primary=understanding.primary,
                    company_sources=scoped_sources,
                    include_body_reviews=not understanding.primary)
                for candidate in refreshed:
                    if goals.cached_posting(user_id, candidate.source_url):
                        cached_reviews[canonical_search_url(candidate.source_url)] = len(cached_reviews)
                # Direct recovery already owns these saved candidates and their
                # original listing evidence. Do not race it with a fresh read.
                direct_pending = ({url for state in direct.states.values()
                                   for url in state.get('pending_candidates', {})}
                                  if settings.web_search_direct_sources_enabled and direct.supported else set())
                history = [c for c in [*refreshed, *resumed]
                           if in_company_scope(c, scoped_sources) and (
                               canonical_search_url(c.source_url) not in direct_pending
                               or canonical_search_url(c.source_url) in cached_reviews)]
                historical_candidates.update(canonical_search_url(c.source_url) for c in history)
                publish(history)

            if settings.web_search_direct_sources_enabled and direct.supported:
                def publish_direct(candidates):
                    pending = []
                    for candidate in candidates:
                        key = canonical_search_url(candidate.source_url)
                        waiter = candidate_waiters.setdefault(key, asyncio.get_running_loop().create_future())
                        if key in candidate_outcomes:
                            if not waiter.done():
                                waiter.set_result(bool(candidate_outcomes[key][1]))
                        else:
                            pending.append(candidate)
                    publish(pending)
                await direct.discover(publish_direct, await_result=await_candidate)

        planner = (
            SearchDecisionPlanner(
                decision_client,
                max_calls=settings.web_search_decision_max_calls,
                timeout_seconds=settings.web_search_decision_timeout_seconds,
                on_event=trace_event,
            )
            if agent_enabled
            else None
        )

        diversity_probe_done = False
        useful_companies = {}

        def target_reached(useful_ids):
            if concurrent_direct and direct.running:
                return False
            if coverage and coverage.next_task(direct) is not None:
                return False
            if len(useful_ids & matched_sources.keys()) < target:
                return False
            companies = {useful_companies.get(job_id) for job_id in useful_ids} - {None, ""}
            needed_companies = min(len(sources), max(1, (target + settings.web_search_company_target - 1) // settings.web_search_company_target))
            return len(companies) >= needed_companies

        async def search(number, seen):
            nonlocal duplicate_streak, search_stop_reason, resuming_after_verification
            nonlocal pending_retry, retries_used, search_unavailable
            nonlocal diversity_probe_done
            if concurrent_direct:
                await bootstrap_started.wait()
            if continued_company and not coverage:
                search_stop_reason = "本次公司查询已结束，进度已保存"
                return None
            # Supplemental searches progress independently of historical reviews.
            if search_unavailable:
                return None
            if (not coverage and settings.web_search_direct_sources_enabled and snapshot.useful_jobs > 0
                    and len(search_history) >= 2
                    and snapshot.useful_jobs <= search_history[-2].get("useful_jobs_before", -1)):
                search_stop_reason = "连续两轮补搜未增加符合岗位，停止新增搜索；保留未完成进度"
                return None
            coverage_task = coverage.next_task(direct) if coverage else None
            while concurrent_direct and coverage_task is None and direct.running:
                direct.changed.clear()
                coverage_task = coverage.next_task(direct)
                if coverage_task is not None or not direct.running:
                    break
                try:
                    await asyncio.wait_for(direct.changed.wait(), timeout=min(1, max(0.001, search_deadline - monotonic())))
                except TimeoutError:
                    pass
                if monotonic() >= search_deadline:
                    raise TimeoutError
                coverage_task = coverage.next_task(direct)
            if coverage and coverage_task is None and pending_retry is None:
                search_stop_reason = "本批公司已查询，进度已保存；下次搜索优先覆盖其他公司"
                return None
            is_retry = pending_retry is not None and coverage_task is None
            poor_results = bool(search_history) and (
                bool(search_history[-1]["error_code"])
                or search_history[-1]["new_details"] == 0
                or (snapshot.completed_verifications >= 2 and snapshot.useful_jobs == 0)
            )
            task = (coverage_task or pending_retry) if coverage else pending_retry or next_search_task(
                tasks,
                completed_queries,
                duplicate_streak,
                poor_results=poor_results,
                last_strategy=search_history[-1]["strategy"]
                if search_history
                else None,
            )
            if not coverage and settings.web_search_direct_sources_enabled and direct.states and not is_retry:
                from src.services.search_planner import diversity_task

                # Spend the small supplemental budget on employers whose official
                # listings were not already scanned, instead of rediscovering them.
                covered = [source.company for source in sources
                           if source.id in direct.fresh_sources or source.id in direct.published_sources]
                task = diversity_task(query, sources, [*covered, *useful_companies.values()], completed_queries) or task
            if not coverage or is_retry:
                pending_retry = None
            if planner is not None and (number > 1 or coverage) and not is_retry:
                decision_tasks = tasks
                if coverage and task is not None:
                    from src.services.search_planner import build_agent_search_tasks

                    # Company rotation owns coverage; AI chooses a query inside
                    # that employer's search; official ownership is checked later.
                    decision_tasks = [replace(option, company_id=task.company_id)
                                      for option in build_agent_search_tasks(task.query)]
                observation = {
                    **asdict(snapshot),
                    "round": number,
                    "target_jobs": target,
                    "remaining_search_calls": rounds - len(search_history),
                    "remaining_seconds": max(0, search_deadline - monotonic()),
                    "completed_queries": sorted(completed_queries),
                    "search_history": list(search_history),
                    "verification_failures": dict(verification_errors),
                    "verified_summaries": list(verified_summaries[:10]),
                    "must_search": resuming_after_verification or bool(coverage),
                    "resume_reason": (
                        "核验反馈后岗位数量仍不足；请选择新的查询，不能再次仅等待或结束"
                        if resuming_after_verification
                        else None
                    ),
                }
                decision = await planner.choose(
                    original_query=query,
                    company_ids=company_ids or [],
                    tasks=decision_tasks,
                    observation=observation,
                )
                # Verification progresses during the model request. Never
                # dispatch an obsolete decision after the target/budget changes.
                if monotonic() >= search_deadline:
                    raise TimeoutError
                if snapshot.useful_jobs >= target and (not sources or target_reached(set(useful_companies))):
                    search_stop_reason = "达到有效岗位目标"
                    return None
                if decision.action == "finish":
                    if (
                        snapshot.pending_verification
                        or observation["pending_verification"]
                    ):
                        resuming_after_verification = True
                        return WaitForVerification(decision.reason)
                    search_stop_reason = "搜索 Agent 建议结束新增搜索；继续核验已有线索"
                    return None
                if decision.action == "search_web":
                    task = decision.task
            if not coverage and not is_retry and snapshot.useful_jobs >= target and not diversity_probe_done:
                from src.services.search_planner import diversity_task

                probe = diversity_task(query, sources, useful_companies.values(), completed_queries)
                diversity_probe_done = True
                if probe:
                    task = probe
            if task is None:
                return None
            resuming_after_verification = False
            completed_queries.add(task.query)
            current_provider = create_web_search_provider(
                task.query, [task.company_id] if task.company_id else company_ids,
                **provider_source_options([task.company_id] if task.company_id else company_ids, sources))
            current_provider.search_context = (
                "原始用户条件：" + query + "。本次只执行上述独立查询。"
                "结果不足可保留相邻岗位并说明差异。已见链接："
                + " ".join(sorted(seen)[-40:])
                + " 待追溯官网线索："
                + " ".join(followup_links[-10:])
            )
            started = monotonic()
            useful_before_search = snapshot.useful_jobs
            evidence_id = "search_" + uuid4().hex[:24]
            evidence = SearchEvidence(
                id=evidence_id,
                user_id=user_id,
                discovery_run_id=run_id,
                query=task.query,
                provider=current_provider.source_id,
                status="RUNNING",
                details={"strategy": task.strategy, "round": number},
            )
            session.add(evidence)
            session.commit()
            candidates = []
            failure = None
            failure_reason = None
            retry_scheduled = False
            if coverage and task.company_id:
                coverage.start_search(task.company_id, keep_listing=task.company_id in direct.states)
            try:
                try:
                    candidates = list(
                        await asyncio.wait_for(
                            current_provider.discover(),
                            settings.web_search_request_timeout_seconds,
                        )
                    )
                except TimeoutError:
                    raise SearchRequestTimeout(
                        "单次搜索请求超时，继续在剩余预算内补搜"
                    ) from None
                unrelated = [c for c in candidates if outside_selected_companies(c)]
                if unrelated:
                    trace_event("company_scope", {"ignored_count": len(unrelated),
                        "summary": "搜索返回的其他公司线索保留在搜索证据中，不进入本次岗位队列"})
                    candidates = [c for c in candidates if not outside_selected_companies(c)]
                # Persist before any slow fetch or parser. Evidence contains all
                # occurrences even when multiple queries return the same URL.
                for candidate in candidates:
                    service.capture_candidate(
                        user_id=user_id, discovery_run_id=run_id, candidate=candidate
                    )
                return candidates
            except BaseException as error:
                failure = type(error).__name__
                failure_reason = (
                    str(error)
                    if type(error).__name__
                    in {
                        "WebSearchPayloadError",
                        "WebSearchConfigurationError",
                        "SearchRequestTimeout",
                    }
                    else failure
                )
                provider_failure = getattr(current_provider, "last_evidence", {})
                if provider_failure.get("http_status") in {401, 403}:
                    search_unavailable = True
                    search_stop_reason = "搜索服务认证或访问权限失败，已停止新增搜索"
                    failures.append(search_stop_reason)
                if (
                    not search_unavailable
                    and _transient_search_failure(error, provider_failure)
                    and retries_used < settings.web_search_transient_retries
                    and number < rounds
                    and monotonic() < search_deadline
                ):
                    # Retries are explicit rounds, not a hidden transport loop.
                    retries_used += 1
                    pending_retry = task
                    retry_scheduled = True
                raise
            finally:
                provider_evidence = dict(getattr(current_provider, "last_evidence", {}))
                if provider_evidence.get("partial"):
                    failures.append("部分搜索响应未整体完成，已保留可用链接与完整证据")
                evidence.raw_response = provider_evidence.pop("raw_response", None)
                new_urls = {
                    canonical_search_url(c.source_url) for c in candidates
                } - seen
                new_jobs = sum(
                    lead_discovery_kind(c) == "job"
                    for c in candidates
                    if canonical_search_url(c.source_url) in new_urls
                )
                duplicate_streak = duplicate_streak + 1 if not new_urls else 0
                details = {
                    **provider_evidence,
                    "source_id": task.company_id,
                    "query": task.query,
                    "strategy": task.strategy,
                    "round": number,
                    "output_count": len(candidates),
                    "new_links": len(new_urls),
                    "new_details": new_jobs,
                    "detail_count": sum(lead_discovery_kind(c) == "job" for c in candidates),
                    "duplicate_count": len(candidates) - len(new_urls),
                    "duration_ms": int((monotonic() - started) * 1000),
                    "useful_jobs_before": useful_before_search,
                    "error_code": failure,
                    "failure_reason": failure_reason,
                    "is_retry": is_retry,
                    "retry_scheduled": retry_scheduled,
                    "request_timeout_seconds": settings.web_search_request_timeout_seconds,
                    "evidence_id": evidence_id,
                    "summary": f"查询：{task.query}；返回 {len(candidates)}，新增链接 {len(new_urls)}，新增具体岗位 {new_jobs}",
                }
                evidence.details = details
                search_history.append(
                    {
                        key: details[key]
                        for key in (
                            "query",
                            "strategy",
                            "round",
                            "output_count",
                            "new_links",
                            "new_details",
                            "duplicate_count",
                            "duration_ms",
                            "error_code",
                            "useful_jobs_before",
                        )
                    }
                )
                evidence.status = (
                    "FAILED"
                    if failure
                    else (
                        "PARTIAL" if provider_evidence.get("partial") else "COMPLETED"
                    )
                )
                session.commit()
                if coverage and task.company_id:
                    coverage.finish_search(task.company_id, failed=bool(failure),
                                           partial=bool(provider_evidence.get("partial")))
                trace_event("search_query", details)

        def can_verify(candidate):
            group = source_group(candidate.source_url)
            if group not in shortlist_sources:
                return True
            return shortlist_gate.allows(used=source_reads.get(group, 0),
                priority=candidate_priority(candidate, query=query, official_hosts=hosts),
                producer_finished=shortlist_finished or group in direct.finished_sources,
                direct=candidate.source_url in direct.evidence,
                cached=canonical_search_url(candidate.source_url) in cached_reviews)

        def finish_shortlist():
            nonlocal shortlist_finished
            shortlist_finished = True

        def reserve_candidate(candidate):
            if candidate.search_context.get("deferred") and not candidate.search_context.get("resumed"):
                return
            if canonical_search_url(candidate.source_url) in cached_reviews:
                return
            group = source_group(candidate.source_url)
            from src.services.lead_presentation import lead_discovery_kind

            if lead_discovery_kind(candidate) != "job":
                return
            if (group in {source.id for source in sources}
                    and source_reads.get(group, 0) < settings.web_search_company_target):
                source_reads[group] = source_reads.get(group, 0) + 1
                source_active[group] = source_active.get(group, 0) + 1
                reservations[candidate.source_url] = group
                if coverage:
                    coverage.record_match(group, candidate.source_url, False)

        async def verify(candidate):
            if outside_selected_companies(candidate):
                trace_event("company_scope", {"url": candidate.source_url,
                    "summary": "该线索属于其他公司，未纳入本次公司查询"})
                return None
            if candidate.search_context.get("deferred") and not candidate.search_context.get("resumed"):
                service.capture_candidate(user_id=user_id, discovery_run_id=run_id, candidate=candidate)
                trace_event("verification_deferred", {
                    "url": candidate.source_url, "error_code": "search_reference_deferred",
                    "summary": "搜索参考来源或本轮候选额度外的链接已保存，优先处理明确相关岗位，可继续查询",
                })
                return None
            group = source_group(candidate.source_url)
            waiting = candidate_waiters.get(canonical_search_url(candidate.source_url))
            fallback_active = coverage and group in coverage.web_attempted
            if (direct.states.get(group, {}).get("status") == "paused" and not fallback_active
                    and (waiting is None or waiting.done())
                    and canonical_search_url(candidate.source_url) not in historical_candidates):
                service.capture_candidate(user_id=user_id, discovery_run_id=run_id, candidate=candidate)
                trace_event("verification_deferred", {
                    "url": candidate.source_url, "error_code": "company_paused",
                    "summary": "本轮已暂停这家公司，剩余链接保留供按需续查",
                })
                return None
            # A shared job-board host is not a company identity. Apply quotas
            # only after it resolves to a configured official company.
            if (group in {source.id for source in sources}
                    and source_reads.get(group, 0) >= settings.web_search_company_target
                    and candidate.source_url not in reservations
                    and canonical_search_url(candidate.source_url) not in cached_reviews):
                service.capture_candidate(user_id=user_id, discovery_run_id=run_id, candidate=candidate)
                trace_event("verification_deferred", {
                    "url": candidate.source_url, "error_code": "company_read_limit",
                    "summary": f"这家公司本轮已检查{settings.web_search_company_target}个岗位，未查完的链接已保留",
                })
                return None
            # No SQLAlchemy session is shared across concurrently awaiting tasks.
            with SessionLocal() as verification_session:
                result = await verify_in_session(
                    candidate,
                    verification_session,
                    JobLeadService(verification_session, understanding=understanding),
                )
                from sqlalchemy import select

                from src.domain.discovery import JobLead

                lead = verification_session.scalar(
                    select(JobLead).where(
                        JobLead.user_id == user_id,
                        JobLead.discovery_run_id == run_id,
                        JobLead.normalized_url == candidate.source_url,
                    )
                )
                if lead and lead.failure_code:
                    trace_event(
                        "page_verification",
                        {
                            "url": lead.source_url,
                            "error_code": lead.failure_code,
                            "summary": lead.failure_reason,
                            "lead_id": lead.id,
                            "status": lead.status,
                        },
                    )
                    if not result and (
                        lead.status in {"FAILED", "NEEDS_BROWSER"}
                        or lead.failure_code in {
                            "browser_job_page_unverified", "visual_extraction_unverified",
                            "job_detail_unconfirmed", "browser_login_required",
                            "browser_captcha_required", "browser_security_challenge",
                        }
                    ):
                        return VerificationFailure(lead.failure_code)
                return result

        async def verify_in_session(candidate, session, service):
            lead = service.capture_candidate(
                user_id=user_id,
                discovery_run_id=run_id,
                candidate=candidate,
            )
            if lead.selection_status == "IGNORED":
                return None
            reference_reason = reference_link_reason(candidate.source_url)
            if reference_reason and not lead.job_posting_id:
                from src.domain.discovery import JobLeadStatus

                service._record_failure(
                    user_id=user_id, lead_id=lead.id, status=JobLeadStatus.REJECTED_NON_JOB,
                    code="lead_not_job_page",
                    reason="该链接为资讯、社区、操作或帮助页面，保留来源记录，不进入岗位正文核验",
                    field_evidence={"routing_reason": reference_reason},
                )
                return None
            direct_evidence = direct.evidence.get(candidate.source_url)
            if not direct_evidence or canonical_search_url(candidate.source_url) in cached_reviews:
                from src.services.search_goal_service import SearchGoalService

                cached = SearchGoalService(session).cached_posting(user_id, candidate.source_url)
                if cached:
                    metrics.cache_hit(candidate.source_url)
                    lead.job_posting_id = cached.id
                    lead.status = "VERIFIED"
                    # Do not reset freshness: no new page was read.
                    lead.verified_at = cached.last_verified_at
                    lead.failure_code = lead.failure_reason = None
                    session.commit()
                    trace_event("verified_cache", {
                        "url": candidate.source_url, "job_id": cached.id,
                        "summary": "复用有效期内的官网正文证据，按当前条件重新筛选",
                    })
                    return publish_verified(cached, lead, session=session)
            from src.services.lead_retry import can_retry, lead_state, retry_message

            retry = lead_state(lead)
            new_official_proof = candidate.official_entry_url and retry.get("last_failure_code") in {
                "official_source_unconfirmed", "entry_source_unconfirmed",
            }
            if lead.selection_status == "IGNORED" or (
                not can_retry(retry) and not new_official_proof
                and not (direct_evidence and direct_evidence.full_body)
            ):
                lead.retry_state = retry
                lead.status = {"cooldown": "DEFERRED", "exhausted": "FAILED"}.get(retry.get("mode"), "NEEDS_USER")
                lead.failure_code = retry.get("last_failure_code")
                lead.failure_reason = retry_message(retry)
                session.commit()
                return VerificationFailure("retry_paused")
            if direct_evidence:
                if direct_evidence.official_redirects:
                    service._save_page_snapshot(
                        user_id=user_id, lead_id=lead.id,
                        url=direct_evidence.official_proof_url or direct_evidence.official_url,
                        raw_html="", raw_text=json.dumps({"redirect_chain": direct_evidence.official_redirects}, ensure_ascii=False),
                    )
                if direct_evidence.official_html:
                    service._save_page_snapshot(
                        user_id=user_id,
                        lead_id=lead.id,
                        url=direct_evidence.official_proof_url
                        or direct_evidence.official_url,
                        raw_html=direct_evidence.official_html,
                        raw_text=json.dumps({"observed_navigation": direct_evidence.official_navigation}, ensure_ascii=False)
                        if direct_evidence.official_navigation else None,
                    )
                if direct_evidence.listing_html is not None:
                    snapshot_id = service._save_page_snapshot(
                        user_id=user_id, lead_id=lead.id,
                        url=direct_evidence.listing_url,
                        raw_html=direct_evidence.listing_html,
                        raw_text=json.dumps(direct_evidence.api_record, ensure_ascii=False) if direct_evidence.api_record else None,
                    )
                else:
                    snapshot_id = service._save_page_snapshot(
                        user_id=user_id,
                        lead_id=lead.id,
                        url=direct_evidence.api_record["url"],
                        raw_html="",
                        raw_text=json.dumps(direct_evidence.api_record, ensure_ascii=False),
                        raw_bytes=json.dumps(
                            direct_evidence.api_record, ensure_ascii=False
                        ).encode(),
                    )
                service.record_official_link(
                    user_id=user_id,
                    lead_id=lead.id,
                    source_url=candidate.source_url,
                    entry_url=direct_evidence.official_url,
                    from_url=direct_evidence.listing_url,
                    company=direct_evidence.stub.company,
                )
            host = (urlsplit(candidate.source_url).hostname or "").lower()
            if host not in hosts and not candidate.official_entry_url:
                with verification_stage("official_ownership", candidate.source_url):
                    evidence = await hiring_resolver.resolve(
                        candidate,
                        record_snapshot=lambda url, html: service._save_page_snapshot(
                            user_id=user_id,
                            lead_id=lead.id,
                            url=url,
                            raw_html=html,
                            raw_text=None,
                        ),
                    )
                if evidence:
                    service.record_official_link(
                        user_id=user_id,
                        lead_id=lead.id,
                        source_url=candidate.source_url,
                        entry_url=evidence.entry_url,
                        from_url=evidence.from_url,
                        scope_url=evidence.scope_url,
                        snapshot_id=evidence.snapshot_id,
                        company=evidence.company,
                    )
                    candidate = replace(
                        candidate, official_entry_url=evidence.entry_url
                    )
                    trace_event(
                        "official_ownership",
                        {
                            "url": candidate.source_url,
                            "summary": f"已从{evidence.company}官网确认企业招聘页面归属",
                            "entry_url": evidence.entry_url,
                            "scope_url": evidence.scope_url,
                            "snapshot_id": evidence.snapshot_id,
                        },
                    )
            if (
                host not in hosts
                and not candidate.official_entry_url
                and lead_discovery_kind(candidate) == "job"
            ):
                lead.status = "NEEDS_USER"
                lead.failure_code = "official_source_unconfirmed"
                lead.failure_reason = "官网归属尚未核实，保留线索并继续追溯官方岗位链接"
                followup_links.append(candidate.source_url)
                session.commit()
                return None
            if not direct_evidence and lead_discovery_kind(candidate) == "entry":
                lead.status = "DEFERRED"
                lead.failure_code = "recruitment_entry_page"
                lead.failure_reason = "招聘入口或列表页，保留为线索；补搜具体职位链接"
                followup_links.append(candidate.source_url)
                session.commit()
                found = []
                if host not in hosts and not candidate.official_entry_url:
                    lead.failure_code = "entry_source_unconfirmed"
                    lead.failure_reason = (
                        "入口官网归属未确认，已保留线索供补搜追溯，未批量展开"
                    )
                    session.commit()
                    trace_event(
                        "entry_expansion",
                        {
                            "url": candidate.source_url,
                            "output_count": 0,
                            "reason": "entry_source_unconfirmed",
                            "summary": lead.failure_reason,
                        },
                    )
                    return found
                entry_source = source_group(candidate.source_url, candidate.company_hint)
                reason = entry_budget.reason(candidate.source_url, entry_source)
                if reason:
                    lead.failure_code = reason
                    lead.failure_reason = {
                        "entry_duplicate": "本轮已处理该入口，保留已发现的岗位和续查进度",
                        "entry_budget": "本轮入口探索预算已用尽，剩余页面已保留供续查",
                        "entry_no_progress": "该来源连续展开未发现新岗位，本轮暂停入口探索",
                        "entry_cooldown": "该入口近期已探索，冷却结束后继续，已发现的岗位仍可核验",
                    }[reason]
                    session.commit()
                    trace_event("entry_expansion", {"url": candidate.source_url, "output_count": 0,
                                "reason": reason, "summary": lead.failure_reason})
                    return found
                if not reason:
                    timeout = entry_budget.begin(candidate.source_url)
                    cursor = entry_budget.cursor(candidate.source_url)
                    interrupted = False

                    def record_snapshot(url, html):
                        service._save_page_snapshot(
                            user_id=user_id,
                            lead_id=lead.id,
                            url=url,
                            raw_html=html,
                            raw_text=None,
                        )

                    def capture_detail(link, from_url):
                        detail = replace(
                            candidate,
                            source_url=link.url,
                            title_hint=link.text or None,
                            observed_title=True,
                            source_job_id=None,
                            search_snippet=link.text or None,
                            official_entry_url=candidate.source_url
                            if host in hosts
                            else candidate.official_entry_url,
                        )
                        detail_lead = service.capture_candidate(
                            user_id=user_id, discovery_run_id=run_id, candidate=detail
                        )
                        if detail.official_entry_url:
                            service.record_official_link(
                                user_id=user_id,
                                lead_id=detail_lead.id,
                                source_url=link.url,
                                entry_url=detail.official_entry_url,
                                from_url=from_url,
                            )
                        found.append(detail)
                        if enqueue_discovered:
                            enqueue_discovered([detail])

                    try:
                        with verification_stage(
                            "entry_expansion", candidate.source_url
                        ):
                            await asyncio.wait_for(
                                expand_entry(
                                    candidate.source_url,
                                    reader=reader,
                                    browser=browser,
                                    allowed_hosts=hosts,
                                    initial_scope=hiring_scope(candidate.source_url)
                                    if candidate.official_entry_url
                                    else None,
                                    record_snapshot=record_snapshot,
                                    query=query,
                                    max_pages=max(
                                        2, min(12, settings.web_search_entry_max_pages)
                                    ),
                                    official_hosts=hosts,
                                    max_details=settings.web_search_entry_max_details,
                                    on_detail=capture_detail,
                                    on_event=trace_event,
                                    state=cursor,
                                    page_cache=entry_budget.pages,
                                    on_checkpoint=lambda value: entry_budget.save_cursor(
                                        candidate.source_url, entry_source, value),
                                ),
                                timeout=timeout,
                            )
                    except TimeoutError:
                        interrupted = True
                        trace_event(
                            "entry_timeout",
                            {
                                "url": candidate.source_url,
                                "error_code": "entry_timeout",
                                "detail_count": len(found),
                            },
                        )
                    except asyncio.CancelledError:
                        interrupted = True
                        raise
                    except Exception:
                        interrupted = True
                        raise
                    finally:
                        entry_budget.finish(candidate.source_url, entry_source, cursor,
                                            len(found), interrupted=interrupted)
                    lead.failure_code = "entry_budget" if cursor.get("queue") or cursor.get("pending_details") else "recruitment_entry_page"
                    lead.failure_reason = (
                        f"本次从入口发现 {len(found)} 个具体职位链接；"
                        + ("尚未查完，剩余页面和链接已保存" if lead.failure_code == "entry_budget" else "已保存入口探索记录")
                    )
                    session.commit()
                    trace_event(
                        "entry_expansion",
                        {
                            "url": candidate.source_url,
                            "output_count": len(found),
                            "exploration_spent_ms": int(entry_budget.spent * 1000),
                            "remaining_pages": len(cursor.get("queue", [])),
                            "remaining_details": len(cursor.get("pending_details", {})),
                            "summary": f"招聘入口展开：发现 {len(found)} 个具体职位链接",
                        },
                    )
                return found
            try:
                try:
                    # Count distinct concrete job URLs only after actually starting
                    # their reader. List expansion, quotas and cache hits are separate.
                    fresh_payload = direct_evidence and (
                        not direct_evidence.observed_at
                        or direct_evidence.observed_at >= metrics.started_at
                    )
                    if not direct_evidence or not direct_evidence.full_body or fresh_payload:
                        metrics.start_read(candidate.source_url, previous=retry)
                    else:
                        metrics.cache_hit(candidate.source_url)
                    if direct_evidence and direct_evidence.full_body:
                        from src.services.job_fact_verifier import (
                            verified_stub_evidence,
                        )

                        stub = direct_evidence.stub
                        fields = verified_stub_evidence(
                            raw_content=stub.raw_content,
                            company=stub.company,
                            title=stub.title,
                            locations=stub.locations,
                            job_type=stub.job_type,
                            metadata_kind="official_payload",
                        )
                        with verification_stage(
                            "official_payload", candidate.source_url
                        ):
                            verified = service.verify_stub(
                                user_id=user_id,
                                lead_id=lead.id,
                                stub=direct_evidence.stub,
                                source_type="official_ats_search_payload",
                                field_evidence={
                                    **fields,
                                    "snapshot_id": snapshot_id,
                                    "listing_url": direct_evidence.listing_url,
                                    "api_url": direct_evidence.api_record["url"],
                                    "source_job_id": direct_evidence.stub.source_job_id,
                                },
                            )
                            if direct_evidence.observed_at:
                                # Consuming a saved page is not a new visit to the
                                # official site. Preserve the evidence's actual age.
                                verified.posting.last_verified_at = direct_evidence.observed_at
                                lead.verified_at = direct_evidence.observed_at
                                session.commit()
                    elif retry.get("next_method") == "browser":
                        with verification_stage("browser_verification", candidate.source_url):
                            verified = await service.verify_browser(
                                user_id=user_id, lead_id=lead.id, reader=browser,
                                official_hosts=hosts, official_only=True,
                            )
                    else:
                        with verification_stage(
                            "http_verification", candidate.source_url
                        ):
                            verified = await service.verify_url(
                                user_id=user_id,
                                lead_id=lead.id,
                                reader=reader,
                                official_hosts=hosts,
                                official_only=True,
                            )
                except LeadVerificationFailure as error:
                    if retry.get("next_method") == "browser" or error.code not in {
                        "lead_requires_browser",
                        "job_detail_unconfirmed",
                        "page_body_incomplete",
                    }:
                        return None
                    with verification_stage(
                        "browser_verification", candidate.source_url
                    ):
                        verified = await service.verify_browser(
                            user_id=user_id,
                            lead_id=lead.id,
                            reader=browser,
                            official_hosts=hosts,
                            official_only=True,
                        )
            except LeadVerificationFailure:
                return None
            except asyncio.CancelledError:
                session.rollback()
                pending = service.get_lead(user_id=user_id, lead_id=lead.id)
                pending.status = "DEFERRED"
                pending.failure_code = "verification_budget_exhausted"
                pending.failure_reason = "正文核验预算已用尽，链接已保留，可继续核验"
                from src.services.lead_retry import failed_state

                pending.retry_state = failed_state(pending.retry_state, pending.failure_code)
                session.commit()
                raise
            except Exception:  # noqa: BLE001 - isolate individual page failures
                session.rollback()
                from src.domain.discovery import JobLeadStatus

                service._record_failure(
                    user_id=user_id, lead_id=lead.id, status=JobLeadStatus.FAILED,
                    code="unexpected_verification_error", reason="本次页面处理异常，需检查读取方式",
                )
                failures.append("个别页面读取失败，线索已保留")
                return None
            metrics.finish_read(candidate.source_url, success=True)
            return publish_verified(verified.posting, lead, session=session,
                                    created=verified.posting_created)

        def publish_verified(posting, lead, *, session, created=False):
            if not in_company_scope(posting, scoped_sources):
                trace_event("company_scope", {"url": posting.source_url,
                    "summary": "正文已确认属于其他公司，未计入本次公司查询结果"})
                return None
            stub = JobStub(
                source_id=posting.source_id or provider.source_id,
                source_job_id=posting.source_job_id or posting.id,
                company=posting.company,
                title=posting.title,
                locations=posting.locations or [],
                job_type=posting.job_type,
                published_at=posting.published_at,
                detail_url=posting.source_url,
                raw_content=posting.raw_content,
                recruitment_context=posting.recruitment_context or {},
            )
            # Publish verified public facts before any remote direction review.
            role_review = load_role_review(
                session, user_id=user_id, job=stub, query=query
            )
            if settings.web_search_semantic_enabled and (
                settings.structured_model_provider != "fake" or understanding.client is not None
            ):
                from src.services.discovery_matching import search_filter_conditions

                conditions = run.goal_conditions or search_filter_conditions(query)
                if understanding.primary:
                    stub = replace(stub, recruitment_context={**stub.recruitment_context, "understanding_policy": "ai"})
                    posting.recruitment_context = stub.recruitment_context
                    session.commit()
                fields = pending_review_fields(stub, query=query, conditions=conditions, role_review=role_review,
                                               primary=understanding.primary)
                if fields:
                    # Persist before the async consumer starts: cancellation can
                    # leave a job waiting in the queue without any model call.
                    stub = queue_review(stub, conditions=conditions, fields=fields, primary=understanding.primary)
                    posting.recruitment_context = stub.recruitment_context
                    session.commit()
            role_jobs[posting.id] = (stub, posting, lead.id)
            match = classify_discovery_job(stub, query=query, role_review=role_review, conditions=run.goal_conditions)
            return posting.id, publish_match(
                posting, match, created=created
            )

        def publish_match(posting, match, *, created=False):
            if not in_company_scope(posting, scoped_sources):
                return False
            match = apply_posting_availability(match, posting)
            useful = match.filter_status == "matched"
            from src.domain.discovery import JobLead

            evidence_lead = session.get(JobLead, role_jobs[posting.id][2]) if posting.id in role_jobs else None
            evidence_url = evidence_lead.source_url if evidence_lead else posting.source_url
            metrics.publish(posting.id, useful, fresh=metrics.reads.get(evidence_url, {}).get("success", False),
                            recommended=match.review_status == "recommended")
            if useful:
                useful_companies[posting.id] = posting.company
            else:
                useful_companies.pop(posting.id, None)
            if posting.id not in matched:
                summary_indices[posting.id] = len(verified_summaries)
                verified_summaries.append(
                    {
                        "company": (posting.company or "")[:160],
                        "title": (posting.title or "")[:160],
                        "match_tier": match.match_tier,
                        "mismatch_labels": list(match.mismatch_labels),
                        "useful": useful,
                    }
                )
                if created:
                    run.new_count += 1
                else:
                    run.duplicate_count += 1
            matched[posting.id] = match.as_dict(job_posting_id=posting.id)
            verified_summaries[summary_indices[posting.id]].update(
                match_tier=match.match_tier,
                mismatch_labels=list(match.mismatch_labels),
                useful=useful,
            )
            if useful and posting.id not in analysis_ids:
                analysis_ids.append(posting.id)
            elif not useful and posting.id in analysis_ids:
                analysis_ids.remove(posting.id)
            return useful

        async def review_direction(job_id):
            while True:
                inputs = role_jobs[job_id]
                stub, posting, lead_id = inputs
                def checkpoint(updated, inputs=inputs, posting=posting):
                    if role_jobs[job_id] is not inputs:
                        return
                    posting.recruitment_context = updated.recruitment_context
                    stored = session.get(type(posting), posting.id)
                    stored.recruitment_context = updated.recruitment_context
                    session.commit()

                interpreted = await understanding.review(
                    stub, query=query, conditions=run.goal_conditions,
                    role_review=load_role_review(session, user_id=user_id, job=stub, query=query),
                    on_checkpoint=checkpoint,
                    historical=canonical_search_url(stub.detail_url) in known_job_urls,
                )
                if role_jobs[job_id] is not inputs:
                    continue
                if interpreted is not stub:
                    stub = interpreted
                role_review = None
                if not understanding.primary:
                    with verification_stage("role_review", stub.detail_url):
                        role_review = await role_reviewer.review(
                            stub, query=query, session=session, user_id=user_id, lead_id=lead_id,
                        )
                # A newer official body can arrive while the model is waiting.
                if role_jobs[job_id] is inputs:
                    match = classify_discovery_job(
                        stub, query=query, role_review=role_review, conditions=run.goal_conditions
                    )
                    return job_id, publish_match(posting, match)

        def report(number, seen, useful, message, stop):
            if "搜索失败" in message:
                failures.append("部分搜索轮次失败，已保留其他轮次结果")
            run_leads = service.list_leads(user_id=user_id, discovery_run_id=run_id)
            pending_count = sum(
                not lead.job_posting_id
                and lead.status != "CLOSED"
                and lead_discovery_kind(lead) == "job"
                for lead in run_leads
            )
            entry_count = sum(
                not lead.job_posting_id
                and lead_discovery_kind(lead) == "entry"
                for lead in run_leads
            )
            run.discovered_count = len(run_leads)
            run.result_matches = list(matched.values())
            run.usage_metrics = metrics.snapshot()
            details = {
                "round": number,
                "max_rounds": rounds,
                "target_jobs": target,
                "budget_seconds": seconds,
                "unique_leads": len(run_leads),
                "pending_jobs": pending_count,
                "recruitment_entries": entry_count,
                "verified_jobs": len(matched),
                "useful_jobs": useful,
                "stop_reason": stop,
            }
            step = {
                "phase": "stop" if stop else "observe",
                "tool": "multiround_search",
                "outcome": "completed" if stop else "running",
                "observation": f"第 {number}/{rounds} 轮：{message}；具体岗位 {len(matched) + pending_count}（正文已核验 {len(matched)}，待核验 {pending_count}），招聘入口 {entry_count}",
                "decision": stop or "结果不足时继续补搜；信息不足不等于不匹配。",
                "source_id": provider.source_id,
                "company": None,
                "url": None,
                "occurred_at": datetime.now(UTC).isoformat(),
                "duration_ms": None,
                "error_code": None,
                "details": details,
            }
            trace = list(run.agent_trace or [])
            if (
                trace
                and trace[-1].get("tool") == "multiround_search"
                and trace[-1].get("details", {}).get("round") == number
                and not stop
            ):
                trace[-1] = step
            else:
                trace.append(step)
            run.agent_trace = trace
            session.commit()

        trace_event(
            "query_plan",
            {
                "summary": f"已拆分 {len(tasks)} 条备选查询，本次预算最多执行 {rounds} 条；相关具体岗位优先，来源轮流核验",
                "planned_queries": [
                    {"query": t.query, "strategy": t.strategy} for t in tasks
                ],
                "query_budget": rounds,
                "decision_mode": settings.web_search_decision_mode,
                "original_query": query,
                "company_ids": company_ids or [],
                "decision_call_budget": settings.web_search_decision_max_calls,
                "decision_timeout_seconds": settings.web_search_decision_timeout_seconds,
                "search_budget_seconds": seconds,
                "request_timeout_seconds": settings.web_search_request_timeout_seconds,
                "transient_retry_limit": settings.web_search_transient_retries,
                "entry_max_details": settings.web_search_entry_max_details,
                "verification_scheduler": "relevance-source-fair-v1",
                "source_batch_size": 3,
                "max_active_entries": 1,
                "direct_sources_enabled": settings.web_search_direct_sources_enabled,
                "company_concurrency": settings.web_search_company_concurrency,
                "verification_budget_seconds": settings.web_search_verification_budget_seconds,
            },
        )
        if (settings.company_discovery_enabled and settings.structured_model_provider != "fake"
                and run.search_goal_id and not company_ids and not continued_company and query_tasks is None):
            from src.domain.search_goal import SearchGoal
            from src.services.company_discovery_queue import enqueue_company_discovery

            goal = session.get(SearchGoal, run.search_goal_id)
            if goal and goal.version == run.search_goal_version:
                enqueue_company_discovery(session, goal, run_id=run_id)
                trace_event("company_discovery_queued", {"summary": "新公司发现已排队，后台分步保存搜索、提取和核验进度"})
        search_deadline = monotonic() + seconds
        from src.services.search_resources import model_capacity

        async with (browser.reuse() if hasattr(browser, "reuse") else nullcontext()), model_capacity(settings).foreground():
            try:
                await run_search_pipeline(
                    bootstrap=bootstrap
                    if run.search_goal_id or (settings.web_search_direct_sources_enabled and direct.supported)
                    else None,
                    max_concurrency=settings.web_search_verification_inflight,
                    priority=lambda candidate: (4, cached_reviews[canonical_search_url(candidate.source_url)], 0)
                    if canonical_search_url(candidate.source_url) in cached_reviews else candidate_priority(
                        candidate,
                        query=query,
                        official_hosts=hosts,
                    ),
                    # Cached interpretation needs no site request, source circuit
                    # or network slot. Keep the stored failure state untouched.
                    source_key=lambda candidate: None if canonical_search_url(candidate.source_url) in cached_reviews else candidate_source(candidate),
                    is_entry=lambda candidate: (
                        candidate.source_url not in direct.evidence and lead_discovery_kind(candidate)
                        == "entry"
                    ),
                    on_queue_ready=queue_ready,
                    canonicalize=canonical_search_url,
                    on_event=trace_event,
                    on_snapshot=update_snapshot,
                    get_stop_reason=lambda: search_stop_reason,
                    feedback_wait_seconds=(
                        feedback_wait_seconds
                        if feedback_wait_seconds is not None
                        else 1
                        if agent_enabled
                        else 0
                    ),
                    verification_seconds=max(
                        1, min(900, settings.web_search_verification_budget_seconds)
                    ),
                    item_seconds=max(
                        1, min(180, settings.web_search_verification_item_seconds)
                    ),
                    search=search,
                    verify=verify,
                    review=review_direction,
                    historical_review=lambda candidate: canonical_search_url(candidate.source_url) in known_job_urls,
                    review_concurrency=(
                        settings.web_search_role_review_batch_size
                        * settings.web_search_role_review_concurrency
                    ),
                    report=report,
                    max_rounds=rounds,
                    seconds=seconds,
                    target=target,
                    target_reached=target_reached,
                    on_candidate_done=candidate_done,
                    can_verify=can_verify,
                    on_candidate_start=reserve_candidate,
                    on_bootstrap_done=finish_shortlist,
                    bootstrap_seconds=seconds,
                    bootstrap_concurrent=concurrent_direct,
                    source_retry_states=progress_store.load_verification(),
                    on_source_state=progress_store.save_verification,
                )
            finally:
                await role_reviewer.aclose()
        for pending in service.list_leads(user_id=user_id, discovery_run_id=run_id):
            if (
                pending.discovery_run_id == run_id
                and not pending.job_posting_id
                and pending.status in {"NEW", "VERIFYING"}
            ):
                pending.status = "DEFERRED"
                pending.failure_code = "verification_budget_exhausted"
                pending.failure_reason = (
                    "本次核验未完成，原链接和已读取证据均已保留，可继续核验"
                )
                from src.services.lead_retry import failed_state

                pending.retry_state = failed_state(pending.retry_state, pending.failure_code)
        session.commit()
        if failures:
            run.failure_summary = failures[0]
            session.commit()
        await analyze_discovery_jobs(
            session,
            run_id=run_id,
            user_id=user_id,
            job_ids=analysis_ids,
            analysis_limit=max(0, min(5, analysis_limit)),
        )
