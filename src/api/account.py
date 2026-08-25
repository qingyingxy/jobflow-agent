from io import BytesIO

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse

from src.api.account_schemas import (
    AccountDataSummaryRead,
    AccountDeleteRequest,
    AccountDeletionRead,
    AccountExportRequest,
)
from src.api.dependencies import CurrentUserId, DatabaseSession
from src.services.user_data_lifecycle import (
    UserDataLifecycleError,
    UserDataLifecycleService,
)

router = APIRouter(prefix="/api/account", tags=["account-data"])


def create_lifecycle_service(session: DatabaseSession) -> UserDataLifecycleService:
    return UserDataLifecycleService(session)


def _raise_lifecycle_error(error: UserDataLifecycleError) -> None:
    response_status = (
        status.HTTP_413_CONTENT_TOO_LARGE
        if error.code == "account_export_too_large"
        else status.HTTP_409_CONFLICT
    )
    raise HTTPException(
        status_code=response_status,
        detail={"code": error.code, "message": str(error)},
    ) from error


@router.get("/data-summary", response_model=AccountDataSummaryRead)
def account_data_summary(
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> AccountDataSummaryRead:
    summary = create_lifecycle_service(session).summary(user_id=user_id)
    return AccountDataSummaryRead(**summary.__dict__)


@router.post("/export")
def export_account_data(
    payload: AccountExportRequest,
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> StreamingResponse:
    try:
        result = create_lifecycle_service(session).export(user_id=user_id)
    except UserDataLifecycleError as error:
        _raise_lifecycle_error(error)
    return StreamingResponse(
        BytesIO(result.content),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{result.filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("", response_model=AccountDeletionRead)
def delete_account_data(
    payload: AccountDeleteRequest,
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> AccountDeletionRead:
    result = create_lifecycle_service(session).delete(user_id=user_id)
    return AccountDeletionRead(**result.__dict__)
