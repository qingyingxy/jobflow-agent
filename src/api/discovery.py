from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from src.api.dependencies import CurrentUserId, DatabaseSession
from src.api.schemas import DiscoveryRunCreateRequest, DiscoveryRunRead
from src.services.discovery_service import DiscoveryFailure, DiscoveryService
from src.services.discovery_sources import (
    GreenhouseAdapter,
    SourceNotSupportedError,
)
from src.services.url_reader import URLFetchTimeout

router = APIRouter(prefix="/api", tags=["discovery"])


def create_greenhouse_adapter(
    source_url: str,
    *,
    company: str | None = None,
) -> GreenhouseAdapter:
    return GreenhouseAdapter.from_board_url(source_url, company=company)


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
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": error.code, "message": str(error)},
        ) from error

    try:
        result = await DiscoveryService(session, adapter).run(user_id=user_id)
    except DiscoveryFailure as error:
        raise _discovery_failure_error(error) from error
    return DiscoveryRunRead.model_validate(result.run)


@router.get("/discovery/runs", response_model=list[DiscoveryRunRead])
def list_discovery_runs(
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> list[DiscoveryRunRead]:
    return [
        DiscoveryRunRead.model_validate(run)
        for run in DiscoveryService(session).list_runs(user_id=user_id)
    ]
