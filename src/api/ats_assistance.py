from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from src.api.ats_schemas import (
    AtsAuthorizationGrantRead,
    AtsAuthorizationRequest,
    AtsFieldConfirmationRequest,
    AtsFieldPlanRead,
    AtsRetryRequest,
    AtsSessionRead,
    AtsSubmitRequest,
)
from src.api.dependencies import CurrentUserId, DatabaseSession
from src.services.application_attempt_service import (
    ApplicationAttemptNotFoundError,
)
from src.services.application_packet_service import (
    ApplicationPacketNotFoundError,
)
from src.services.ats_assistance_service import (
    AtsAssistanceError,
    AtsAssistanceNotFoundError,
    AtsAssistanceService,
    AtsSessionView,
)
from src.services.ats_browser import PlaywrightAtsBrowserExecutor

router = APIRouter(prefix="/api", tags=["ats-assistance"])


def create_ats_executor() -> PlaywrightAtsBrowserExecutor:
    return PlaywrightAtsBrowserExecutor()


def _session_response(view: AtsSessionView) -> AtsSessionRead:
    item = view.session
    authorization = view.authorization
    return AtsSessionRead(
        id=item.id,
        user_id=item.user_id,
        attempt_id=item.attempt_id,
        application_id=item.application_id,
        job_posting_id=item.job_posting_id,
        packet_revision_id=item.packet_revision_id,
        application_url=item.application_url,
        provider=item.provider,
        status=item.status,
        page_fingerprint=item.page_fingerprint,
        plan_hash=item.plan_hash,
        field_plan=[
            AtsFieldPlanRead(
                field_key=str(field.get("field_key") or ""),
                label=str(field.get("label") or ""),
                name=str(field.get("name") or ""),
                input_type=str(field.get("input_type") or "text"),
                required=bool(field.get("required")),
                canonical_name=str(field.get("canonical_name") or "custom_answer"),
                risk=str(field.get("risk") or "LOW"),
                action=str(field.get("action") or "SKIP"),
                source=(str(field["source"]) if field.get("source") else None),
                value=(str(field["value"]) if field.get("value") is not None else None),
                reason=str(field.get("reason") or ""),
                options=[str(value) for value in field.get("options") or []],
            )
            for field in item.field_plan
        ],
        handoff_reasons=item.handoff_reasons,
        final_summary=item.final_summary,
        authorization_expires_at=(authorization.expires_at if authorization else None),
        authorization_used=authorization is not None and authorization.used_at is not None,
        created_at=item.created_at,
        updated_at=item.updated_at,
        inspected_at=item.inspected_at,
        prepared_at=item.prepared_at,
        authorized_at=item.authorized_at,
        submitted_at=item.submitted_at,
        failed_at=item.failed_at,
    )


def _raise_ats_error(error: AtsAssistanceError) -> None:
    if error.code in {
        "unsupported_ats",
        "invalid_application_url",
        "invalid_ats_field_confirmation",
    }:
        response_status = status.HTTP_422_UNPROCESSABLE_CONTENT
    else:
        response_status = status.HTTP_409_CONFLICT
    raise HTTPException(
        status_code=response_status,
        detail={"code": error.code, "message": str(error), **error.details},
    ) from error


def _not_found(error: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "ats_session_not_found", "message": "ATS 辅助会话不存在"},
    )


@router.get("/ats-sessions", response_model=list[AtsSessionRead])
def list_ats_sessions(
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> list[AtsSessionRead]:
    return [
        _session_response(item)
        for item in AtsAssistanceService(session).list(user_id=user_id)
    ]


@router.get("/ats-sessions/{session_id}", response_model=AtsSessionRead)
def read_ats_session(
    session_id: str,
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> AtsSessionRead:
    try:
        view = AtsAssistanceService(session).get(
            user_id=user_id,
            session_id=session_id,
        )
    except AtsAssistanceNotFoundError as error:
        raise _not_found(error) from error
    return _session_response(view)


@router.post(
    "/application-attempts/{attempt_id}/ats-session",
    response_model=AtsSessionRead,
)
async def inspect_ats_session(
    attempt_id: str,
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> AtsSessionRead:
    try:
        view = await AtsAssistanceService(session).inspect_attempt(
            user_id=user_id,
            attempt_id=attempt_id,
            executor=create_ats_executor(),
        )
    except (ApplicationAttemptNotFoundError, ApplicationPacketNotFoundError) as error:
        raise _not_found(error) from error
    except AtsAssistanceError as error:
        _raise_ats_error(error)
    return _session_response(view)


@router.post("/ats-sessions/{session_id}/retry", response_model=AtsSessionRead)
async def retry_ats_session(
    session_id: str,
    payload: AtsRetryRequest,
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> AtsSessionRead:
    try:
        view = await AtsAssistanceService(session).retry(
            user_id=user_id,
            session_id=session_id,
            user_completed_handoff=payload.user_completed_handoff,
            executor=create_ats_executor(),
        )
    except AtsAssistanceNotFoundError as error:
        raise _not_found(error) from error
    except AtsAssistanceError as error:
        _raise_ats_error(error)
    return _session_response(view)


@router.post(
    "/ats-sessions/{session_id}/confirm-fields",
    response_model=AtsSessionRead,
)
async def confirm_ats_fields(
    session_id: str,
    payload: AtsFieldConfirmationRequest,
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> AtsSessionRead:
    try:
        view = await AtsAssistanceService(session).confirm_fields(
            user_id=user_id,
            session_id=session_id,
            field_keys=payload.field_keys,
            executor=create_ats_executor(),
        )
    except AtsAssistanceNotFoundError as error:
        raise _not_found(error) from error
    except AtsAssistanceError as error:
        _raise_ats_error(error)
    return _session_response(view)


@router.post(
    "/ats-sessions/{session_id}/authorization",
    response_model=AtsAuthorizationGrantRead,
)
def authorize_ats_submission(
    session_id: str,
    payload: AtsAuthorizationRequest,
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> AtsAuthorizationGrantRead:
    try:
        grant = AtsAssistanceService(session).authorize(
            user_id=user_id,
            session_id=session_id,
        )
    except AtsAssistanceNotFoundError as error:
        raise _not_found(error) from error
    except AtsAssistanceError as error:
        _raise_ats_error(error)
    return AtsAuthorizationGrantRead(
        session=_session_response(grant.view),
        authorization_token=grant.token,
        expires_at=grant.view.authorization.expires_at,
    )


@router.post("/ats-sessions/{session_id}/submit", response_model=AtsSessionRead)
async def submit_ats_application(
    session_id: str,
    payload: AtsSubmitRequest,
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> AtsSessionRead:
    try:
        view = await AtsAssistanceService(session).submit(
            user_id=user_id,
            session_id=session_id,
            authorization_token=payload.authorization_token,
            executor=create_ats_executor(),
        )
    except AtsAssistanceNotFoundError as error:
        raise _not_found(error) from error
    except AtsAssistanceError as error:
        _raise_ats_error(error)
    return _session_response(view)
