from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status

from src.api.dependencies import CurrentUserId, DatabaseSession
from src.api.schemas import (
    DiscoveryRunCreateRequest,
    DiscoveryRunRead,
    DiscoverySearchRequest,
    DiscoverySourceRead,
    JobAvailabilityCheckRead,
    JobAvailabilityConfirmationRequest,
    JobLeadCreateRequest,
    JobLeadDetailRead,
    JobLeadRead,
    LeadSelectionUpdate,
    LeadVerificationRead,
    ManualLeadHandoffRequest,
)
from src.config import get_settings
from src.domain.discovery import JobLeadStatus, LeadProvider
from src.domain.job import JobAvailabilityStatus
from src.services.browser_job_reader import PlaywrightBrowserJobReader
from src.services.company_registry import (
    company_source_hosts,
    enabled_company_source_hosts,
    enabled_company_sources,
    provider_source_options,
)
from src.services.discovery_results import current_run_matches
from src.services.discovery_service import DiscoveryFailure, DiscoveryService
from src.services.discovery_sources import (
    GreenhouseAdapter,
    OfficialCompanyRegistryAdapter,
    SourceNotSupportedError,
)
from src.services.job_availability_service import (
    InvalidAvailabilityConfirmationError,
    JobAvailabilityNotFoundError,
    JobAvailabilityService,
)
from src.services.job_lead_service import (
    JobLeadNotFoundError,
    JobLeadService,
    JobLeadStateError,
    LeadVerificationFailure,
)
from src.services.lead_providers import (
    ExternalAgentProvider,
    ManualImportProvider,
    ThirdPartyLeadProvider,
)
from src.services.official_search_service import execute_official_search_in_worker
from src.services.url_reader import SafeHTTPReader, URLFetchTimeout
from src.services.web_search_service import (
    WEB_SEARCH_RUN_SOURCE_ID,
    WebSearchConfigurationError,
    create_web_search_provider,
    execute_web_search_in_worker,
)

router = APIRouter(prefix="/api", tags=["discovery"])


def create_lead_reader() -> SafeHTTPReader:
    settings = get_settings()
    allowed_hosts = enabled_company_source_hosts()
    allowed_hosts.update(GreenhouseAdapter.supported_hosts)
    allowed_hosts.add(GreenhouseAdapter.api_host)
    return SafeHTTPReader(
        proxy=settings.url_fetch_proxy,
        proxy_allowed_hosts=allowed_hosts,
        proxy_allow_unlisted_hosts=settings.url_fetch_proxy_allow_unlisted_hosts,
    )


def create_browser_reader() -> PlaywrightBrowserJobReader:
    return PlaywrightBrowserJobReader()


def _lead_detail(service: JobLeadService, *, user_id: str, lead_id: str) -> JobLeadDetailRead:
    lead = service.get_lead(user_id=user_id, lead_id=lead_id)
    return JobLeadDetailRead(
        **JobLeadRead.model_validate(lead).model_dump(),
        verifications=[
            LeadVerificationRead.model_validate(item)
            for item in service.list_verifications(user_id=user_id, lead_id=lead_id)
        ],
    )


def create_greenhouse_adapter(
    source_url: str,
    *,
    company: str | None = None,
) -> GreenhouseAdapter:
    settings = get_settings()
    allowed_hosts = set(GreenhouseAdapter.supported_hosts)
    allowed_hosts.add(GreenhouseAdapter.api_host)
    return GreenhouseAdapter.from_board_url(
        source_url,
        reader=SafeHTTPReader(
            proxy=settings.url_fetch_proxy,
            proxy_allowed_hosts=allowed_hosts,
            proxy_allow_unlisted_hosts=settings.url_fetch_proxy_allow_unlisted_hosts,
        ),
        company=company,
        max_jobs=20,
    )


def create_official_search_adapter(
    query: str,
    company_ids: list[str] | None = None,
    *, sources=None,
) -> OfficialCompanyRegistryAdapter:
    settings = get_settings()
    sources = sources if sources is not None else enabled_company_sources(company_ids)
    return OfficialCompanyRegistryAdapter(
        sources=sources,
        query=query,
        reader=SafeHTTPReader(
            proxy=settings.url_fetch_proxy,
            proxy_allowed_hosts=company_source_hosts(sources),
            proxy_allow_unlisted_hosts=settings.url_fetch_proxy_allow_unlisted_hosts,
        ),
        max_jobs=20,
    )


def _discovery_failure_error(error: DiscoveryFailure) -> HTTPException:
    response_status = (
        status.HTTP_504_GATEWAY_TIMEOUT
        if error.code == URLFetchTimeout.code
        else status.HTTP_502_BAD_GATEWAY
    )
    return HTTPException(
        status_code=response_status,
        detail={
            "code": error.code,
            "message": str(error),
            "run_id": error.run_id,
            "details": error.details,
        },
    )


@router.post(
    "/discovery/leads",
    response_model=JobLeadRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_job_lead(
    payload: JobLeadCreateRequest,
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> JobLeadRead:
    try:
        provider_kind = LeadProvider(payload.provider)
        if provider_kind is LeadProvider.MANUAL_URL:
            provider = ManualImportProvider(
                source_url=payload.source_url,
                company_hint=payload.company_hint,
                title_hint=payload.title_hint,
                discovered_at=payload.discovered_at,
            )
        else:
            provider_class = (
                ExternalAgentProvider
                if provider_kind is LeadProvider.EXTERNAL_AGENT
                else ThirdPartyLeadProvider
            )
            provider = provider_class(
                source_url=payload.source_url,
                search_snippet=payload.search_snippet,
                inferred_company=payload.company_hint,
                inferred_title=payload.title_hint,
                discovered_at=payload.discovered_at,
            )
        leads = await JobLeadService(session).ingest_provider(
            user_id=user_id,
            provider=provider,
            discovery_run_id=payload.discovery_run_id,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "invalid_job_lead", "message": str(error)},
        ) from error
    return JobLeadRead.model_validate(leads[0])


@router.get("/discovery/leads", response_model=list[JobLeadRead])
def list_job_leads(
    user_id: CurrentUserId,
    session: DatabaseSession,
    lead_status: JobLeadStatus | None = None,
    discovery_run_id: str | None = None,
) -> list[JobLeadRead]:
    return [
        JobLeadRead.model_validate(lead)
        for lead in JobLeadService(session).list_leads(
            user_id=user_id,
            status=lead_status,
            discovery_run_id=discovery_run_id,
        )
    ]


@router.get("/discovery/leads/{lead_id}", response_model=JobLeadDetailRead)
def read_job_lead(
    lead_id: str,
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> JobLeadDetailRead:
    service = JobLeadService(session)
    try:
        return _lead_detail(service, user_id=user_id, lead_id=lead_id)
    except JobLeadNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="岗位线索不存在",
        ) from error


@router.post(
    "/discovery/leads/{lead_id}/verify",
    response_model=JobLeadDetailRead,
)
async def verify_job_lead(
    lead_id: str,
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> JobLeadDetailRead:
    service = JobLeadService(session)
    official_hosts = enabled_company_source_hosts(session=session, user_id=user_id)
    official_hosts.update(GreenhouseAdapter.supported_hosts)
    try:
        await service.verify_url(
            user_id=user_id,
            lead_id=lead_id,
            reader=create_lead_reader(),
            official_hosts=official_hosts,
        )
        return _lead_detail(service, user_id=user_id, lead_id=lead_id)
    except JobLeadNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="岗位线索不存在",
        ) from error
    except JobLeadStateError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "invalid_lead_state", "message": str(error)},
        ) from error
    except LeadVerificationFailure as error:
        response_status = (
            status.HTTP_422_UNPROCESSABLE_CONTENT
            if error.code
            in {
                "lead_not_job_page",
                "lead_requires_browser",
                "url_not_allowed",
                "url_host_not_allowed",
                "unsafe_url",
            }
            else status.HTTP_502_BAD_GATEWAY
        )
        raise HTTPException(
            status_code=response_status,
            detail={
                "code": error.code,
                "message": str(error),
                "lead_id": error.lead_id,
            },
        ) from error


@router.post(
    "/discovery/leads/{lead_id}/handoff/browser",
    response_model=JobLeadDetailRead,
)
async def complete_browser_lead_handoff(
    lead_id: str,
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> JobLeadDetailRead:
    service = JobLeadService(session)
    official_hosts = enabled_company_source_hosts(session=session, user_id=user_id)
    official_hosts.update(GreenhouseAdapter.supported_hosts)
    try:
        await service.verify_browser(
            user_id=user_id,
            lead_id=lead_id,
            reader=create_browser_reader(),
            official_hosts=official_hosts,
        )
        return _lead_detail(service, user_id=user_id, lead_id=lead_id)
    except JobLeadNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="岗位线索不存在",
        ) from error
    except JobLeadStateError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "invalid_lead_state", "message": str(error)},
        ) from error
    except LeadVerificationFailure as error:
        response_status = (
            status.HTTP_422_UNPROCESSABLE_CONTENT
            if error.code
            in {
                "unsafe_url",
                "browser_job_page_unverified",
                "browser_login_required",
                "browser_captcha_required",
                "browser_2fa_required",
                "browser_security_challenge",
                "browser_response_too_large",
            }
            else status.HTTP_502_BAD_GATEWAY
        )
        raise HTTPException(
            status_code=response_status,
            detail={
                "code": error.code,
                "message": str(error),
                "lead_id": error.lead_id,
            },
        ) from error


@router.post(
    "/discovery/leads/{lead_id}/handoff/manual-jd",
    response_model=JobLeadDetailRead,
)
def complete_manual_lead_handoff(
    lead_id: str,
    payload: ManualLeadHandoffRequest,
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> JobLeadDetailRead:
    service = JobLeadService(session)
    try:
        service.complete_manual_handoff(
            user_id=user_id,
            lead_id=lead_id,
            raw_content=payload.raw_content,
            company=payload.company,
            title=payload.title,
            locations=payload.locations,
            job_type=payload.job_type,
        )
        return _lead_detail(service, user_id=user_id, lead_id=lead_id)
    except JobLeadNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="岗位线索不存在",
        ) from error
    except JobLeadStateError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "invalid_lead_state", "message": str(error)},
        ) from error
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "invalid_manual_jd", "message": str(error)},
        ) from error


@router.post(
    "/jobs/{job_posting_id}/availability/check",
    response_model=JobAvailabilityCheckRead,
)
async def check_job_availability(
    job_posting_id: str,
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> JobAvailabilityCheckRead:
    try:
        check = await JobAvailabilityService(session).check_url(
            user_id=user_id,
            job_posting_id=job_posting_id,
            reader=create_lead_reader(),
        )
    except JobAvailabilityNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="岗位不存在或不属于当前用户",
        ) from error
    return JobAvailabilityCheckRead.model_validate(check)


@router.post(
    "/jobs/{job_posting_id}/availability/confirm",
    response_model=JobAvailabilityCheckRead,
)
def confirm_job_availability(
    job_posting_id: str,
    payload: JobAvailabilityConfirmationRequest,
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> JobAvailabilityCheckRead:
    try:
        check = JobAvailabilityService(session).confirm(
            user_id=user_id,
            job_posting_id=job_posting_id,
            status=JobAvailabilityStatus(payload.status),
            reason=payload.reason,
        )
    except JobAvailabilityNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="岗位不存在或不属于当前用户",
        ) from error
    except InvalidAvailabilityConfirmationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "invalid_availability_confirmation", "message": str(error)},
        ) from error
    return JobAvailabilityCheckRead.model_validate(check)


@router.get(
    "/jobs/{job_posting_id}/availability/checks",
    response_model=list[JobAvailabilityCheckRead],
)
def list_job_availability_checks(
    job_posting_id: str,
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> list[JobAvailabilityCheckRead]:
    try:
        checks = JobAvailabilityService(session).list_checks(
            user_id=user_id,
            job_posting_id=job_posting_id,
        )
    except JobAvailabilityNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="岗位不存在或不属于当前用户",
        ) from error
    return [JobAvailabilityCheckRead.model_validate(item) for item in checks]


@router.post(
    "/discovery/runs",
    response_model=DiscoveryRunRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_discovery_run(
    payload: DiscoveryRunCreateRequest,
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> DiscoveryRunRead:
    try:
        adapter = create_greenhouse_adapter(
            payload.source_url,
            company=payload.company,
        )
    except SourceNotSupportedError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": error.code, "message": str(error)},
        ) from error

    try:
        result = await DiscoveryService(session, adapter).run(user_id=user_id)
    except DiscoveryFailure as error:
        raise _discovery_failure_error(error) from error
    return DiscoveryRunRead.model_validate(result.run)


@router.post(
    "/discovery/search",
    response_model=DiscoveryRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_official_search(
    payload: DiscoverySearchRequest,
    background_tasks: BackgroundTasks,
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> DiscoveryRunRead:
    """Start one bounded search; original job pages are verified before parsing."""

    query, company_ids, goal_metadata = payload.query, payload.company_ids, {}
    if payload.continue_company_id and (not payload.search_goal_id or payload.source_mode != "web"):
        raise HTTPException(status_code=422, detail="继续公司查询需要已保存的求职目标")
    if payload.search_goal_id:
        from src.services.search_goal_service import SearchGoalService

        goals = SearchGoalService(session)
        try:
            goal = goals.get(user_id, payload.search_goal_id)
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        if goal.version != payload.search_goal_version:
            raise HTTPException(status_code=409, detail="求职目标已变更，请刷新后再搜索")
        # A retry reuses its ongoing execution instead of resetting the budget.
        existing = next((r for r in DiscoveryService(session).list_runs(user_id=user_id)
                         if r.search_goal_id == goal.id and r.search_goal_version == goal.version
                         and r.status == "RUNNING"), None)
        if existing:
            if existing.continued_company_id != payload.continue_company_id:
                raise HTTPException(status_code=409, detail="该目标正在搜索，请等待本次搜索结束")
            return DiscoveryRunRead.model_validate(existing)
        query, company_ids = goal.query, goal.company_ids
        goal_metadata = {"search_goal_id": goal.id, "search_goal_version": goal.version,
                         "goal_conditions": goal.conditions, "library_baseline": goals.snapshot(user_id, query=goal.query)}
        if payload.continue_company_id:
            from src.services.company_search_progress import progress_summaries

            progress = next((item for item in progress_summaries(goal, session)
                             if item["source_id"] == payload.continue_company_id), None)
            if not progress or not progress["can_continue"]:
                raise HTTPException(status_code=409, detail="该公司没有可续查的进度，请先更新搜索")
            if (progress.get("strategy") == "official_listing"
                    and not get_settings().web_search_direct_sources_enabled):
                raise HTTPException(status_code=409, detail="官网定向查询尚未启用")
            company_ids = [payload.continue_company_id]
            goal_metadata["continued_company_id"] = payload.continue_company_id

    try:
        sources = enabled_company_sources(company_ids or None, session=session, user_id=user_id)
    except ValueError as error:
        raise HTTPException(status_code=422, detail={"code": "unknown_company_source", "message": str(error)}) from error
    source_options = provider_source_options(company_ids, sources)
    if payload.source_mode == "web":
        try:
            provider = create_web_search_provider(query, company_ids, **source_options)
        except WebSearchConfigurationError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"code": error.code, "message": str(error)},
            ) from error
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"code": "unknown_company_source", "message": str(error)},
            ) from error
        plan = provider.build_search_plan()
        run = DiscoveryService(session).create_run(
            user_id=user_id,
            search_query=query,
            max_results=plan.budget.max_results,
            source_id=WEB_SEARCH_RUN_SOURCE_ID,
            source_url=provider.source_url,
            search_plan=plan,
            **goal_metadata,
        )
        background_tasks.add_task(
            execute_web_search_in_worker,
            run_id=run.id,
            user_id=user_id,
            query=query,
            company_ids=company_ids,
        )
        return DiscoveryRunRead.model_validate(run)

    try:
        adapter = create_official_search_adapter(query, company_ids, **source_options)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "unknown_company_source", "message": str(error)},
        ) from error
    service = DiscoveryService(session, adapter)
    run = service.create_run(
        user_id=user_id,
        search_query=query,
        max_results=20,
        **goal_metadata,
    )
    background_tasks.add_task(
        execute_official_search_in_worker,
        run_id=run.id,
        user_id=user_id,
        query=query,
        company_ids=company_ids,
    )
    return DiscoveryRunRead.model_validate(run)


@router.get("/discovery/sources", response_model=list[DiscoverySourceRead])
def list_discovery_sources(user_id: CurrentUserId, session: DatabaseSession) -> list[DiscoverySourceRead]:
    return [
        DiscoverySourceRead(
            id=source.id,
            company=source.company,
            priority=source.priority,
            search_mode=(
                "dedicated_adapter"
                if source.id in {"bytedance", "tencent"}
                else "official_page"
            ),
        )
        for source in enabled_company_sources(session=session, user_id=user_id)
    ]


@router.get("/discovery/runs", response_model=list[DiscoveryRunRead])
def list_discovery_runs(
    user_id: CurrentUserId,
    session: DatabaseSession,
    compact: bool = False,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[DiscoveryRunRead]:
    runs = DiscoveryService(session).list_runs(user_id=user_id, limit=limit, offset=offset)
    # A history summary reports the saved run outcome. Re-evaluate current jobs
    # through the goal library or full detail endpoint, not every history poll.
    if compact:
        outdated = [run for run in runs if _outdated_decisions(run)]
        matches = current_run_matches(session, outdated)
        return [_compact_run(run, summary=index > 0, matches=matches.get(run.id)) for index, run in enumerate(runs)]
    matches = current_run_matches(session, runs)
    return [DiscoveryRunRead.model_validate({
        **DiscoveryRunRead.model_validate(run).model_dump(),
        "result_matches": matches[run.id],
    }) for run in runs]


def _outdated_decisions(run):
    from src.services.source_understanding import VERSION, ai_policy_enabled

    return ai_policy_enabled() and any(
        item.get("filter_version") != VERSION or item.get("decision_policy") != "ai"
        for item in run.result_matches or []
    )


def _compact_run(run, *, summary=False, matches=None):
    data = {name: getattr(run, name) for name in DiscoveryRunRead.model_fields}
    data.update(agent_trace=(run.agent_trace or [])[-1:], search_plan=None)
    if matches is not None:
        data["result_matches"] = matches
    if summary:
        data["result_matches"] = [{**match, "checks": []} for match in data["result_matches"] or []]
    return DiscoveryRunRead.model_validate(data)


@router.get("/discovery/runs/{run_id}", response_model=DiscoveryRunRead)
def read_discovery_run(
    run_id: str,
    user_id: CurrentUserId,
    session: DatabaseSession,
    compact: bool = False,
) -> DiscoveryRunRead:
    run = DiscoveryService(session).get_run(user_id=user_id, run_id=run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="发现运行不存在")
    if compact:
        # Compact only reduces trace payload. Live personal gates and job aliases
        # must remain identical to the detail view after profile/review changes.
        matches = current_run_matches(session, [run])[run.id]
        return _compact_run(run, matches=matches)
    return DiscoveryRunRead.model_validate({
        **DiscoveryRunRead.model_validate(run).model_dump(),
        "result_matches": current_run_matches(session, [run])[run.id],
    })


@router.patch("/discovery/leads/{lead_id}/selection", response_model=JobLeadRead)
def update_lead_selection(lead_id: str, payload: LeadSelectionUpdate, user_id: CurrentUserId, session: DatabaseSession):
    service = JobLeadService(session)
    try:
        lead = service.get_lead(user_id=user_id, lead_id=lead_id)
    except JobLeadNotFoundError as error:
        raise HTTPException(status_code=404, detail="岗位线索不存在") from error
    from sqlalchemy import select

    from src.domain.discovery import JobLead
    for item in session.scalars(select(JobLead).where(JobLead.user_id == user_id, JobLead.normalized_url == lead.normalized_url)):
        item.selection_status = payload.status
    session.commit()
    session.refresh(lead)
    return JobLeadRead.model_validate(lead)


@router.get("/discovery/runs/{run_id}/search-evidence")
def read_search_evidence(run_id: str, user_id: CurrentUserId, session: DatabaseSession):
    from sqlalchemy import select

    from src.domain.discovery import SearchEvidence
    if DiscoveryService(session).get_run(user_id=user_id, run_id=run_id) is None:
        raise HTTPException(status_code=404, detail="发现运行不存在")
    records = session.scalars(select(SearchEvidence).where(
        SearchEvidence.user_id == user_id, SearchEvidence.discovery_run_id == run_id,
    ).order_by(SearchEvidence.created_at, SearchEvidence.id))
    return [{"id": r.id, "query": r.query, "provider": r.provider, "status": r.status,
             "details": r.details, "raw_response": r.raw_response} for r in records]


@router.post("/discovery/leads/{lead_id}/expand", response_model=list[JobLeadRead])
async def expand_recruitment_lead(lead_id: str, user_id: CurrentUserId, session: DatabaseSession):
    import asyncio
    from dataclasses import replace
    from datetime import UTC, datetime
    from urllib.parse import urlsplit

    from src.services.company_registry import within_company_source
    from src.services.lead_providers import LeadCandidate
    from src.services.recruitment_entry import expand_entry
    from src.services.recruitment_trust import hiring_scope
    service = JobLeadService(session)
    try:
        lead = service.get_lead(user_id=user_id, lead_id=lead_id)
    except JobLeadNotFoundError as error:
        raise HTTPException(status_code=404, detail="岗位线索不存在") from error
    hosts = enabled_company_source_hosts(session=session, user_id=user_id)
    acquired = next((source for source in enabled_company_sources(session=session, user_id=user_id)
                     if source.official_homepage_url and within_company_source(lead.source_url, source)), None)
    tenant = hiring_scope(acquired.career_url) if acquired else None
    allowed = hosts if tenant else hosts | {urlsplit(lead.source_url).hostname}
    run = DiscoveryService(session).get_run(user_id=user_id, run_id=lead.discovery_run_id) if lead.discovery_run_id else None
    captured = []
    candidate = LeadCandidate(provider=LeadProvider.EXTERNAL_AGENT, source_url=lead.source_url, discovered_at=datetime.now(UTC), source_id=lead.source_id)
    def record_snapshot(url, html):
        service._save_page_snapshot(user_id=user_id, lead_id=lead.id, url=url, raw_html=html, raw_text=None)
    def capture_detail(link, from_url):
        item = service.capture_candidate(user_id=user_id, discovery_run_id=lead.discovery_run_id,
            candidate=replace(candidate, source_url=link.url, title_hint=link.text or None, search_snippet=link.text or None))
        if acquired and within_company_source(link.url, acquired):
            service.record_official_link(user_id=user_id, lead_id=item.id, source_url=link.url,
                entry_url=acquired.official_homepage_url, from_url=from_url,
                scope_url=acquired.career_url, company=acquired.company)
        elif urlsplit(lead.source_url).hostname in hosts:
            service.record_official_link(user_id=user_id, lead_id=item.id, source_url=link.url,
                entry_url=lead.source_url, from_url=from_url)
        captured.append(JobLeadRead.model_validate(item))
    try:
        await asyncio.wait_for(expand_entry(lead.source_url, reader=create_lead_reader(),
            browser=create_browser_reader(), allowed_hosts=allowed, official_hosts=hosts,
            initial_scope=tenant,
            query=run.search_query if run else "", record_snapshot=record_snapshot, on_detail=capture_detail), timeout=50)
    except TimeoutError:
        if not captured:
            raise HTTPException(status_code=504, detail="入口读取超时，已保留原链接和读取快照，可以稍后重试") from None
    return captured
