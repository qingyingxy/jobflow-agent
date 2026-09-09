from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException, status

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
)
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
    )


def create_official_search_adapter(
    query: str,
    company_ids: list[str] | None = None,
) -> OfficialCompanyRegistryAdapter:
    settings = get_settings()
    sources = enabled_company_sources(company_ids)
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
) -> list[JobLeadRead]:
    return [
        JobLeadRead.model_validate(lead)
        for lead in JobLeadService(session).list_leads(
            user_id=user_id,
            status=lead_status,
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
    official_hosts = enabled_company_source_hosts()
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
    official_hosts = enabled_company_source_hosts()
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

    if payload.source_mode == "web":
        try:
            provider = create_web_search_provider(payload.query, payload.company_ids)
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
            search_query=payload.query,
            max_results=plan.budget.max_results,
            source_id=WEB_SEARCH_RUN_SOURCE_ID,
            source_url=provider.source_url,
            search_plan=plan,
        )
        background_tasks.add_task(
            execute_web_search_in_worker,
            run_id=run.id,
            user_id=user_id,
            query=payload.query,
            company_ids=payload.company_ids,
        )
        return DiscoveryRunRead.model_validate(run)

    try:
        adapter = create_official_search_adapter(payload.query, payload.company_ids)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "unknown_company_source", "message": str(error)},
        ) from error
    service = DiscoveryService(session, adapter)
    run = service.create_run(
        user_id=user_id,
        search_query=payload.query,
        max_results=20,
    )
    background_tasks.add_task(
        execute_official_search_in_worker,
        run_id=run.id,
        user_id=user_id,
        query=payload.query,
        company_ids=payload.company_ids,
    )
    return DiscoveryRunRead.model_validate(run)


@router.get("/discovery/sources", response_model=list[DiscoverySourceRead])
def list_discovery_sources() -> list[DiscoverySourceRead]:
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
        for source in enabled_company_sources()
    ]


@router.get("/discovery/runs", response_model=list[DiscoveryRunRead])
def list_discovery_runs(
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> list[DiscoveryRunRead]:
    return [
        DiscoveryRunRead.model_validate(run)
        for run in DiscoveryService(session).list_runs(user_id=user_id)
    ]


@router.get("/discovery/runs/{run_id}", response_model=DiscoveryRunRead)
def read_discovery_run(
    run_id: str,
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> DiscoveryRunRead:
    run = DiscoveryService(session).get_run(user_id=user_id, run_id=run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="发现运行不存在")
    return DiscoveryRunRead.model_validate(run)
