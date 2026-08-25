from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status

from src.api.attempt_schemas import (
    ApplicationAttemptRead,
    ApplicationBlockerRead,
    AttemptChecklistRead,
    AttemptCreateRequest,
    AttemptStatusUpdate,
    BlockerCreateRequest,
    ReceiptCreateRequest,
    SubmissionReceiptRead,
)
from src.api.dependencies import CurrentUserId, DatabaseSession
from src.domain.application_attempt import ATTEMPT_TRANSITIONS, AttemptStatus
from src.services.application_attempt_service import (
    ApplicationAttemptError,
    ApplicationAttemptNotFoundError,
    ApplicationAttemptService,
    ApplicationAttemptView,
)
from src.services.application_service import ApplicationNotFoundError

router = APIRouter(prefix="/api", tags=["application-attempts"])


def _attempt_response(view: ApplicationAttemptView) -> ApplicationAttemptRead:
    attempt = view.attempt
    current_status = AttemptStatus(attempt.status)
    transitions = ATTEMPT_TRANSITIONS[current_status]
    receipt = view.receipt
    return ApplicationAttemptRead(
        id=attempt.id,
        user_id=attempt.user_id,
        application_id=attempt.application_id,
        job_posting_id=attempt.job_posting_id,
        packet_revision_id=attempt.packet_revision_id,
        application_url=attempt.application_url,
        status=current_status,
        available_transitions=sorted(
            (
                item
                for item in transitions
                if item is not AttemptStatus.SUBMITTED
            ),
            key=lambda item: item.value,
        ),
        checklist=[
            AttemptChecklistRead(
                code=item.code,
                label=item.label,
                complete=item.complete,
                blocking=item.blocking,
            )
            for item in view.checklist
        ],
        blockers=[
            ApplicationBlockerRead.model_validate(item) for item in view.blockers
        ],
        receipt=(
            SubmissionReceiptRead(
                id=receipt.id,
                attempt_id=receipt.attempt_id,
                application_id=receipt.application_id,
                packet_revision_id=receipt.packet_revision_id,
                confirmation_text=receipt.confirmation_text,
                confirmation_url=receipt.confirmation_url,
                application_number=receipt.application_number,
                screenshot_metadata=receipt.screenshot_metadata,
                user_confirmed=receipt.user_confirmed,
                is_valid=receipt.is_valid,
                validation_codes=receipt.validation_codes,
                receipt_hash=receipt.receipt_hash,
                captured_at=receipt.captured_at,
                created_at=receipt.created_at,
            )
            if receipt
            else None
        ),
        created_at=attempt.created_at,
        updated_at=attempt.updated_at,
        form_opened_at=attempt.form_opened_at,
        ready_at=attempt.ready_at,
        submitted_at=attempt.submitted_at,
        failed_at=attempt.failed_at,
        abandoned_at=attempt.abandoned_at,
    )


def _raise_attempt_error(error: ApplicationAttemptError) -> None:
    if error.code in {
        "invalid_application_url",
        "official_application_url_missing",
        "invalid_confirmation_url",
        "invalid_submission_receipt",
    }:
        response_status = status.HTTP_422_UNPROCESSABLE_CONTENT
    elif error.code == "packet_revision_not_found":
        response_status = status.HTTP_404_NOT_FOUND
    else:
        response_status = status.HTTP_409_CONFLICT
    raise HTTPException(
        status_code=response_status,
        detail={"code": error.code, "message": str(error), **error.details},
    ) from error


@router.post(
    "/packet-revisions/{revision_id}/attempts",
    response_model=ApplicationAttemptRead,
)
def create_attempt(
    revision_id: str,
    payload: AttemptCreateRequest,
    response: Response,
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> ApplicationAttemptRead:
    try:
        result = ApplicationAttemptService(session).create(
            user_id=user_id,
            packet_revision_id=revision_id,
            application_url=payload.application_url,
            idempotency_key=payload.idempotency_key,
        )
    except ApplicationNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "application_not_found", "message": "申请记录不存在"},
        ) from error
    except ApplicationAttemptError as error:
        _raise_attempt_error(error)
    response.status_code = (
        status.HTTP_201_CREATED if result.created else status.HTTP_200_OK
    )
    return _attempt_response(result.view)


@router.get("/application-attempts", response_model=list[ApplicationAttemptRead])
def list_attempts(
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> list[ApplicationAttemptRead]:
    return [
        _attempt_response(item)
        for item in ApplicationAttemptService(session).list(user_id=user_id)
    ]


@router.get(
    "/application-attempts/{attempt_id}", response_model=ApplicationAttemptRead
)
def read_attempt(
    attempt_id: str,
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> ApplicationAttemptRead:
    try:
        view = ApplicationAttemptService(session).get(
            user_id=user_id, attempt_id=attempt_id
        )
    except ApplicationAttemptNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "attempt_not_found", "message": "投递尝试不存在"},
        ) from error
    return _attempt_response(view)


@router.patch(
    "/application-attempts/{attempt_id}/status",
    response_model=ApplicationAttemptRead,
)
def transition_attempt(
    attempt_id: str,
    payload: AttemptStatusUpdate,
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> ApplicationAttemptRead:
    try:
        view = ApplicationAttemptService(session).transition(
            user_id=user_id,
            attempt_id=attempt_id,
            target_status=payload.status,
        )
    except ApplicationAttemptNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "attempt_not_found", "message": "投递尝试不存在"},
        ) from error
    except ApplicationAttemptError as error:
        _raise_attempt_error(error)
    return _attempt_response(view)


@router.post(
    "/application-attempts/{attempt_id}/blockers",
    response_model=ApplicationAttemptRead,
)
def add_blocker(
    attempt_id: str,
    payload: BlockerCreateRequest,
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> ApplicationAttemptRead:
    try:
        view = ApplicationAttemptService(session).add_blocker(
            user_id=user_id,
            attempt_id=attempt_id,
            category=payload.category,
            observation=payload.observation,
            stop_reason=payload.stop_reason,
            retryable=payload.retryable,
            next_strategy=payload.next_strategy,
            required_user_action=payload.required_user_action,
            idempotency_key=payload.idempotency_key,
        )
    except ApplicationAttemptNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "attempt_not_found", "message": "投递尝试不存在"},
        ) from error
    except ApplicationAttemptError as error:
        _raise_attempt_error(error)
    return _attempt_response(view)


@router.post(
    "/application-attempts/{attempt_id}/blockers/{blocker_id}/resolve",
    response_model=ApplicationAttemptRead,
)
def resolve_blocker(
    attempt_id: str,
    blocker_id: str,
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> ApplicationAttemptRead:
    try:
        view = ApplicationAttemptService(session).resolve_blocker(
            user_id=user_id,
            attempt_id=attempt_id,
            blocker_id=blocker_id,
        )
    except ApplicationAttemptNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "blocker_not_found", "message": "投递阻塞不存在"},
        ) from error
    return _attempt_response(view)


@router.post(
    "/application-attempts/{attempt_id}/receipt",
    response_model=ApplicationAttemptRead,
)
def record_receipt(
    attempt_id: str,
    payload: ReceiptCreateRequest,
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> ApplicationAttemptRead:
    try:
        view = ApplicationAttemptService(session).record_receipt(
            user_id=user_id,
            attempt_id=attempt_id,
            confirmation_text=payload.confirmation_text,
            confirmation_url=payload.confirmation_url,
            application_number=payload.application_number,
            screenshot_metadata=(
                payload.screenshot_metadata.model_dump(mode="json")
                if payload.screenshot_metadata
                else None
            ),
            user_confirmed=payload.user_confirmed,
            captured_at=payload.captured_at,
        )
    except ApplicationAttemptNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "attempt_not_found", "message": "投递尝试不存在"},
        ) from error
    except ApplicationAttemptError as error:
        _raise_attempt_error(error)
    return _attempt_response(view)


@router.post(
    "/application-attempts/{attempt_id}/finalize",
    response_model=ApplicationAttemptRead,
)
def finalize_submission(
    attempt_id: str,
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> ApplicationAttemptRead:
    try:
        view = ApplicationAttemptService(session).finalize_submission(
            user_id=user_id,
            attempt_id=attempt_id,
        )
    except ApplicationAttemptNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "attempt_not_found", "message": "投递尝试不存在"},
        ) from error
    except ApplicationAttemptError as error:
        _raise_attempt_error(error)
    return _attempt_response(view)

