from __future__ import annotations

import asyncio
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
)
from src.services.discovery_matching import classify_discovery_job
from src.services.discovery_sources import JobStub
from src.services.job_lead_service import JobLeadService, LeadVerificationFailure
from src.services.job_url import canonical_job_url
from src.services.lead_presentation import discovery_kind
from src.services.official_hiring_resolver import OfficialHiringResolver
from src.services.official_search_service import analyze_discovery_jobs
from src.services.recruitment_entry import expand_entry
from src.services.recruitment_trust import hiring_scope
from src.services.search_decision import SearchDecisionPlanner
from src.services.search_pipeline import (
    SearchSnapshot,
    WaitForVerification,
    run_search_pipeline,
)
from src.services.search_planner import (
    build_agent_search_tasks,
    build_search_tasks,
    next_search_task,
)
from src.services.url_reader import SafeHTTPReader


class SearchRequestTimeout(RuntimeError):
    """One request timed out; the workflow may still have search budget."""


def _transient_search_failure(error, evidence):
    if isinstance(error, (SearchRequestTimeout, TimeoutError)):
        return True
    if evidence.get("http_status") in {408, 429, 500, 502, 503, 504, 524}:
        return True
    return evidence.get("error_code") in {
        "ReadTimeout", "ConnectTimeout", "WriteTimeout", "PoolTimeout",
        "ConnectError", "ReadError", "RemoteProtocolError",
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
    *, run_id, user_id, query, company_ids,
    query_tasks=None, analysis_limit=0, feedback_wait_seconds=None,
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
        provider = create_web_search_provider(query, company_ids)
        service = JobLeadService(session)
        hosts = enabled_company_source_hosts()
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
        sources = enabled_company_sources(company_ids or None)
        hiring_resolver = OfficialHiringResolver(sources=sources, reader=reader, browser=browser)
        followup_links = []
        expanded_entries = set()
        agent_enabled = settings.web_search_decision_mode == "agent"
        # Internal callers may supply the same code-owned candidates in controlled
        # comparisons; the public API keeps the normal mode-specific defaults.
        tasks = list(query_tasks) if query_tasks is not None else (
            build_agent_search_tasks(query, sources)
            if agent_enabled else build_search_tasks(query, sources)
        )
        completed_queries = set()
        duplicate_streak = 0
        search_history = []
        pending_retry = None
        retries_used = 0
        search_unavailable = False
        verification_errors = {}
        verified_summaries = []
        snapshot = SearchSnapshot(0, 0, 0, 0, seconds)
        search_stop_reason = None
        resuming_after_verification = False

        def update_snapshot(value):
            nonlocal snapshot
            snapshot = value

        def trace_event(kind, details):
            if kind == "queue_budget":
                failures.append("正文核验预算已用尽，剩余链接已保留待核验")
            trace = list(run.agent_trace or [])
            error = details.get("error_code")
            if error and kind in {"verification", "page_verification", "entry_timeout"}:
                verification_errors[error] = verification_errors.get(error, 0) + 1
            is_decision = kind.startswith("search_decision")
            trace.append(
                {
                    "phase": (
                        "fallback" if kind == "search_decision_fallback"
                        else "plan" if is_decision else "observe"
                    ),
                    "tool": kind,
                    "outcome": "failed" if error else "completed",
                    "observation": details.get("summary")
                    or f"{kind}：{details.get('url', '')}",
                    "decision": details.get("reason") if is_decision else (
                        "已保留证据；失败不删除已发现链接"
                        if error else "继续独立查询与正文核验"
                    ),
                    "duration_ms": details.get("duration_ms"),
                    "error_code": error,
                    "occurred_at": datetime.now(UTC).isoformat(),
                    "details": details,
                }
            )
            run.agent_trace = trace
            session.commit()

        def decision_client():
            # One counted decision attempt must mean one HTTP request. Repairs
            # are budgeted explicitly by SearchDecisionPlanner, never hidden in
            # the shared client's transport retry loop.
            return create_structured_model_client(settings.model_copy(update={
                "llm_max_retries": 0,
                "llm_timeout_seconds": min(
                    settings.llm_timeout_seconds,
                    settings.web_search_decision_timeout_seconds,
                ),
            }))

        from src.services.job_role_review import JobRoleReviewer
        role_reviewer = JobRoleReviewer(settings, on_event=trace_event)

        planner = SearchDecisionPlanner(
            decision_client,
            max_calls=settings.web_search_decision_max_calls,
            timeout_seconds=settings.web_search_decision_timeout_seconds,
            on_event=trace_event,
        ) if agent_enabled else None

        async def search(number, seen):
            nonlocal duplicate_streak, search_stop_reason, resuming_after_verification
            nonlocal pending_retry, retries_used, search_unavailable
            if search_unavailable:
                return None
            is_retry = pending_retry is not None
            poor_results = bool(search_history) and (
                bool(search_history[-1]["error_code"])
                or search_history[-1]["new_details"] == 0
                or (snapshot.completed_verifications >= 2 and snapshot.useful_jobs == 0)
            )
            task = pending_retry or next_search_task(
                tasks, completed_queries, duplicate_streak, poor_results=poor_results,
                last_strategy=search_history[-1]["strategy"] if search_history else None,
            )
            pending_retry = None
            if planner is not None and number > 1 and not is_retry:
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
                    "must_search": resuming_after_verification,
                    "resume_reason": (
                        "核验反馈后岗位数量仍不足；请选择新的查询，不能再次仅等待或结束"
                        if resuming_after_verification else None
                    ),
                }
                decision = await planner.choose(
                    original_query=query,
                    company_ids=company_ids or [],
                    tasks=tasks,
                    observation=observation,
                )
                # Verification progresses during the model request. Never
                # dispatch an obsolete decision after the target/budget changes.
                if monotonic() >= search_deadline:
                    raise TimeoutError
                if snapshot.useful_jobs >= target:
                    search_stop_reason = "达到有效岗位目标"
                    return None
                if decision.action == "finish":
                    if snapshot.pending_verification or observation["pending_verification"]:
                        resuming_after_verification = True
                        return WaitForVerification(decision.reason)
                    search_stop_reason = "搜索 Agent 建议结束新增搜索；继续核验已有线索"
                    return None
                if decision.action == "search_web":
                    task = decision.task
            if task is None:
                return None
            resuming_after_verification = False
            completed_queries.add(task.query)
            current_provider = create_web_search_provider(task.query, company_ids)
            current_provider.search_context = (
                "原始用户条件：" + query + "。本次只执行上述独立查询。"
                "结果不足可保留相邻岗位并说明差异。已见链接："
                + " ".join(sorted(seen)[-40:])
                + " 待追溯官网线索："
                + " ".join(followup_links[-10:])
            )
            started = monotonic()
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
            try:
                try:
                    candidates = list(await asyncio.wait_for(
                        current_provider.discover(), settings.web_search_request_timeout_seconds
                    ))
                except TimeoutError:
                    raise SearchRequestTimeout("单次搜索请求超时，继续在剩余预算内补搜") from None
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
                    in {"WebSearchPayloadError", "WebSearchConfigurationError", "SearchRequestTimeout"}
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
                    discovery_kind(c.source_url, c.title_hint) == "job"
                    for c in candidates
                    if canonical_search_url(c.source_url) in new_urls
                )
                duplicate_streak = duplicate_streak + 1 if not new_urls else 0
                details = {
                    **provider_evidence,
                    "query": task.query,
                    "strategy": task.strategy,
                    "round": number,
                    "output_count": len(candidates),
                    "new_links": len(new_urls),
                    "new_details": new_jobs,
                    "duplicate_count": len(candidates) - len(new_urls),
                    "duration_ms": int((monotonic() - started) * 1000),
                    "error_code": failure,
                    "failure_reason": failure_reason,
                    "is_retry": is_retry,
                    "retry_scheduled": retry_scheduled,
                    "request_timeout_seconds": settings.web_search_request_timeout_seconds,
                    "evidence_id": evidence_id,
                    "summary": f"查询：{task.query}；返回 {len(candidates)}，新增链接 {len(new_urls)}，新增具体岗位 {new_jobs}",
                }
                evidence.details = details
                search_history.append({
                    key: details[key] for key in (
                        "query", "strategy", "round", "output_count", "new_links",
                        "new_details", "duplicate_count", "duration_ms", "error_code",
                    )
                })
                evidence.status = (
                    "FAILED"
                    if failure
                    else (
                        "PARTIAL" if provider_evidence.get("partial") else "COMPLETED"
                    )
                )
                session.commit()
                trace_event("search_query", details)

        async def verify(candidate):
            # No SQLAlchemy session is shared across concurrently awaiting tasks.
            with SessionLocal() as verification_session:
                result = await verify_in_session(
                    candidate,
                    verification_session,
                    JobLeadService(verification_session),
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
                return result

        async def verify_in_session(candidate, session, service):
            lead = service.capture_candidate(
                user_id=user_id,
                discovery_run_id=run_id,
                candidate=candidate,
            )
            host = (urlsplit(candidate.source_url).hostname or "").lower()
            if host not in hosts and not candidate.official_entry_url:
                evidence = await hiring_resolver.resolve(
                    candidate,
                    record_snapshot=lambda url, html: service._save_page_snapshot(
                        user_id=user_id, lead_id=lead.id, url=url, raw_html=html, raw_text=None,
                    ),
                )
                if evidence:
                    service.record_official_link(
                        user_id=user_id, lead_id=lead.id, source_url=candidate.source_url,
                        entry_url=evidence.entry_url, from_url=evidence.from_url,
                        scope_url=evidence.scope_url, snapshot_id=evidence.snapshot_id, company=evidence.company,
                    )
                    candidate = replace(candidate, official_entry_url=evidence.entry_url)
                    trace_event("official_ownership", {"url": candidate.source_url,
                        "summary": f"已从{evidence.company}官网确认企业招聘页面归属",
                        "entry_url": evidence.entry_url, "scope_url": evidence.scope_url,
                        "snapshot_id": evidence.snapshot_id})
            if (
                host not in hosts
                and not candidate.official_entry_url
                and discovery_kind(candidate.source_url, candidate.title_hint) == "job"
            ):
                lead.status = "NEEDS_USER"
                lead.failure_code = "official_source_unconfirmed"
                lead.failure_reason = "官网归属尚未核实，保留线索并继续追溯官方岗位链接"
                followup_links.append(candidate.source_url)
                session.commit()
                return None
            if discovery_kind(candidate.source_url, candidate.title_hint) == "entry":
                lead.status = "DEFERRED"
                lead.failure_code = "recruitment_entry_page"
                lead.failure_reason = "招聘入口或列表页，保留为线索；补搜具体职位链接"
                followup_links.append(candidate.source_url)
                session.commit()
                found = []
                if host not in hosts and not candidate.official_entry_url:
                    lead.failure_code = "entry_source_unconfirmed"
                    lead.failure_reason = "入口官网归属未确认，已保留线索供补搜追溯，未批量展开"
                    session.commit()
                    trace_event("entry_expansion", {
                        "url": candidate.source_url, "output_count": 0,
                        "reason": "entry_source_unconfirmed", "summary": lead.failure_reason,
                    })
                    return found
                if (
                    len(expanded_entries)
                    < max(1, min(20, settings.web_search_entry_limit))
                    and candidate.source_url not in expanded_entries
                ):
                    expanded_entries.add(candidate.source_url)

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

                    try:
                        await asyncio.wait_for(
                            expand_entry(
                                candidate.source_url,
                                reader=reader,
                                browser=browser,
                                allowed_hosts=hosts,
                                initial_scope=hiring_scope(candidate.source_url)
                                if candidate.official_entry_url else None,
                                record_snapshot=record_snapshot,
                                query=query,
                                max_pages=max(
                                    2, min(12, settings.web_search_entry_max_pages)
                                ),
                                official_hosts=hosts,
                                max_details=settings.web_search_entry_max_details,
                                on_detail=capture_detail,
                                on_event=trace_event,
                            ),
                            timeout=50,
                        )
                    except TimeoutError:
                        trace_event(
                            "entry_timeout",
                            {
                                "url": candidate.source_url,
                                "error_code": "entry_timeout",
                                "detail_count": len(found),
                            },
                        )
                    lead.failure_reason = (
                        f"招聘入口已保留，本次从入口发现 {len(found)} 个具体职位链接"
                    )
                    session.commit()
                    trace_event(
                        "entry_expansion",
                        {
                            "url": candidate.source_url,
                            "output_count": len(found),
                            "summary": f"招聘入口展开：发现 {len(found)} 个具体职位链接",
                        },
                    )
                return found
            try:
                try:
                    verified = await service.verify_url(
                        user_id=user_id,
                        lead_id=lead.id,
                        reader=reader,
                        official_hosts=hosts,
                        official_only=True,
                    )
                except LeadVerificationFailure as error:
                    if error.code not in {
                        "lead_requires_browser",
                        "job_detail_unconfirmed",
                    }:
                        return None
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
                session.commit()
                raise
            except Exception:  # noqa: BLE001 - isolate individual page failures
                session.rollback()
                failures.append("个别页面读取失败，线索已保留")
                return None
            posting = verified.posting
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
            )
            role_review = await role_reviewer.review(stub, query=query, session=session, user_id=user_id, lead_id=lead.id)
            match = classify_discovery_job(stub, query=query, role_review=role_review)
            useful = match.filter_status == "matched"
            useful = useful and posting.availability_status != "CLOSED"
            if posting.id not in matched:
                matched[posting.id] = match.as_dict(job_posting_id=posting.id)
                verified_summaries.append({
                    "company": (posting.company or "")[:160],
                    "title": (posting.title or "")[:160],
                    "match_tier": match.match_tier,
                    "mismatch_labels": list(match.mismatch_labels),
                    "useful": useful,
                })
                if verified.posting_created:
                    run.new_count += 1
                else:
                    run.duplicate_count += 1
                if useful:
                    analysis_ids.append(posting.id)
            return posting.id, useful

        def report(number, seen, useful, message, stop):
            if "搜索失败" in message:
                failures.append("部分搜索轮次失败，已保留其他轮次结果")
            run_leads = [
                lead
                for lead in service.list_leads(user_id=user_id)
                if lead.discovery_run_id == run_id
            ]
            pending_count = sum(
                not lead.job_posting_id
                and lead.status != "CLOSED"
                and discovery_kind(lead.source_url, lead.title_hint) == "job"
                for lead in run_leads
            )
            entry_count = sum(
                not lead.job_posting_id
                and discovery_kind(lead.source_url, lead.title_hint) == "entry"
                for lead in run_leads
            )
            run.discovered_count = len(run_leads)
            run.result_matches = list(matched.values())
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

        def candidate_priority(candidate):
            if candidate.official_entry_url:
                return 0
            is_job = discovery_kind(candidate.source_url, candidate.title_hint) == "job"
            if urlsplit(candidate.source_url).hostname in hosts:
                return 1 if is_job else 2
            return 3 if is_job else 4

        trace_event(
            "query_plan",
            {
                "summary": f"已拆分 {len(tasks)} 条备选查询，本次预算最多执行 {rounds} 条；官网优先核验",
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
                "verification_budget_seconds": settings.web_search_verification_budget_seconds,
            },
        )
        search_deadline = monotonic() + seconds
        await run_search_pipeline(
            max_concurrency=2,
            priority=candidate_priority,
            canonicalize=canonical_search_url,
            on_event=trace_event,
            on_snapshot=update_snapshot,
            get_stop_reason=lambda: search_stop_reason,
            feedback_wait_seconds=(
                feedback_wait_seconds if feedback_wait_seconds is not None
                else 1 if agent_enabled else 0
            ),
            verification_seconds=max(
                1, min(900, settings.web_search_verification_budget_seconds)
            ),
            item_seconds=max(
                1, min(180, settings.web_search_verification_item_seconds)
            ),
            search=search,
            verify=verify,
            report=report,
            max_rounds=rounds,
            seconds=seconds,
            target=target,
        )
        for pending in service.list_leads(user_id=user_id):
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
