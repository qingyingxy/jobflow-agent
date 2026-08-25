from __future__ import annotations

from datetime import UTC

from fastapi import APIRouter, HTTPException, Query, Response, status

from src.api.dependencies import CurrentUserId, DatabaseSession
from src.api.follow_up_schemas import (
    FollowUpCreateRequest,
    FollowUpSummaryRead,
    FollowUpTaskRead,
    FollowUpUpdateRequest,
)
from src.domain.follow_up import FollowUpStatus
from src.services.application_service import ApplicationNotFoundError
from src.services.follow_up_service import (
    FollowUpError,
    FollowUpNotFoundError,
    FollowUpService,
    FollowUpTaskView,
    FollowUpViewName,
)

router = APIRouter(prefix="/api", tags=["follow-ups"])


def _task_response(view: FollowUpTaskView) -> FollowUpTaskRead:
    task = view.task
    base_status = FollowUpStatus(task.status)
    actions: list[str] = (
        ["edit", "complete", "cancel"]
        if base_status is FollowUpStatus.PENDING
        else []
    )
    return FollowUpTaskRead(
        id=task.id,
        user_id=task.user_id,
        application_id=task.application_id,
        job_posting_id=task.job_posting_id,
        event_type=task.event_type,
        title=task.title,
        scheduled_at=view.local_scheduled_at.astimezone(UTC),
        local_scheduled_at=view.local_scheduled_at,
        timezone=task.timezone,
        duration_minutes=task.duration_minutes,
        all_day=task.all_day,
        contact_name=task.contact_name,
        contact_detail=task.contact_detail,
        channel=task.channel,
        next_action=task.next_action,
        notes=task.notes,
        status=view.effective_status,
        base_status=base_status,
        is_overdue=view.is_overdue,
        available_actions=actions,
        created_at=task.created_at,
        updated_at=task.updated_at,
        completed_at=task.completed_at,
        cancelled_at=task.cancelled_at,
    )


def _raise_follow_up_error(error: FollowUpError) -> None:
    if error.code in {
        "invalid_timezone",
        "invalid_follow_up_field",
        "invalid_follow_up_update",
        "invalid_follow_up_view",
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
        detail={"code": "follow_up_not_found", "message": "跟进任务不存在"},
    )


@router.get("/follow-ups/summary", response_model=FollowUpSummaryRead)
def read_follow_up_summary(
    user_id: CurrentUserId,
    session: DatabaseSession,
    timezone: str = Query(default="Asia/Shanghai", min_length=1, max_length=64),
) -> FollowUpSummaryRead:
    try:
        summary = FollowUpService(session).summary(
            user_id=user_id,
            timezone=timezone,
        )
    except FollowUpError as error:
        _raise_follow_up_error(error)
    return FollowUpSummaryRead(
        timezone=summary.timezone,
        generated_at=summary.generated_at,
        total_pending=summary.total_pending,
        today=summary.today,
        overdue=summary.overdue,
        next_7_days=summary.next_7_days,
        next_30_days=summary.next_30_days,
    )


@router.get("/follow-ups", response_model=list[FollowUpTaskRead])
def list_follow_ups(
    user_id: CurrentUserId,
    session: DatabaseSession,
    view: FollowUpViewName = "all",
    timezone: str = Query(default="Asia/Shanghai", min_length=1, max_length=64),
) -> list[FollowUpTaskRead]:
    try:
        items = FollowUpService(session).list(
            user_id=user_id,
            view=view,
            timezone=timezone,
        )
    except FollowUpError as error:
        _raise_follow_up_error(error)
    return [_task_response(item) for item in items]


@router.get(
    "/applications/{application_id}/follow-ups",
    response_model=list[FollowUpTaskRead],
)
def list_application_follow_ups(
    application_id: str,
    user_id: CurrentUserId,
    session: DatabaseSession,
    timezone: str = Query(default="Asia/Shanghai", min_length=1, max_length=64),
) -> list[FollowUpTaskRead]:
    try:
        items = FollowUpService(session).list(
            user_id=user_id,
            view="all",
            timezone=timezone,
            application_id=application_id,
        )
    except ApplicationNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "application_not_found", "message": "申请记录不存在"},
        ) from error
    except FollowUpError as error:
        _raise_follow_up_error(error)
    return [_task_response(item) for item in items]


@router.post(
    "/applications/{application_id}/follow-ups",
    response_model=FollowUpTaskRead,
)
def create_follow_up(
    application_id: str,
    payload: FollowUpCreateRequest,
    response: Response,
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> FollowUpTaskRead:
    try:
        result = FollowUpService(session).create(
            user_id=user_id,
            application_id=application_id,
            event_type=payload.event_type,
            title=payload.title,
            scheduled_at=payload.scheduled_at,
            timezone=payload.timezone,
            duration_minutes=payload.duration_minutes,
            all_day=payload.all_day,
            contact_name=payload.contact_name,
            contact_detail=payload.contact_detail,
            channel=payload.channel,
            next_action=payload.next_action,
            notes=payload.notes,
            idempotency_key=payload.idempotency_key,
        )
    except ApplicationNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "application_not_found", "message": "申请记录不存在"},
        ) from error
    except FollowUpError as error:
        _raise_follow_up_error(error)
    response.status_code = (
        status.HTTP_201_CREATED if result.created else status.HTTP_200_OK
    )
    return _task_response(result.view)


@router.get("/follow-ups/{task_id}", response_model=FollowUpTaskRead)
def read_follow_up(
    task_id: str,
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> FollowUpTaskRead:
    try:
        view = FollowUpService(session).get(user_id=user_id, task_id=task_id)
    except FollowUpNotFoundError as error:
        raise _not_found(error) from error
    return _task_response(view)


@router.patch("/follow-ups/{task_id}", response_model=FollowUpTaskRead)
def edit_follow_up(
    task_id: str,
    payload: FollowUpUpdateRequest,
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> FollowUpTaskRead:
    try:
        view = FollowUpService(session).edit(
            user_id=user_id,
            task_id=task_id,
            updates=payload.model_dump(exclude_unset=True),
        )
    except FollowUpNotFoundError as error:
        raise _not_found(error) from error
    except FollowUpError as error:
        _raise_follow_up_error(error)
    return _task_response(view)


@router.post("/follow-ups/{task_id}/complete", response_model=FollowUpTaskRead)
def complete_follow_up(
    task_id: str,
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> FollowUpTaskRead:
    try:
        view = FollowUpService(session).complete(
            user_id=user_id,
            task_id=task_id,
        )
    except FollowUpNotFoundError as error:
        raise _not_found(error) from error
    except FollowUpError as error:
        _raise_follow_up_error(error)
    return _task_response(view)


@router.post("/follow-ups/{task_id}/cancel", response_model=FollowUpTaskRead)
def cancel_follow_up(
    task_id: str,
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> FollowUpTaskRead:
    try:
        view = FollowUpService(session).cancel(
            user_id=user_id,
            task_id=task_id,
        )
    except FollowUpNotFoundError as error:
        raise _not_found(error) from error
    except FollowUpError as error:
        _raise_follow_up_error(error)
    return _task_response(view)

