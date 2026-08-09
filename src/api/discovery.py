from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException, status

from src.api.dependencies import CurrentUserId, DatabaseSession
from src.api.schemas import (
    DiscoveryRunCreateRequest,
    DiscoveryRunRead,
    DiscoverySearchRequest,
    DiscoverySourceRead,
)
from src.config import get_settings
from src.services.company_registry import (
    company_source_hosts,
    enabled_company_sources,
)
from src.services.discovery_service import DiscoveryFailure, DiscoveryService
from src.services.discovery_sources import (
    GreenhouseAdapter,
    OfficialCompanyRegistryAdapter,
    SourceNotSupportedError,
)
from src.services.official_search_service import execute_official_search_in_worker
from src.services.url_reader import SafeHTTPReader, URLFetchTimeout

router = APIRouter(prefix="/api", tags=["discovery"])


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
    """Start one bounded official-site search; parsing runs after discovery."""

    try:
        adapter = create_official_search_adapter(payload.query, payload.company_ids)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
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
