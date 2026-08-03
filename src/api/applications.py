from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status

from src.api.dependencies import CurrentUserId, DatabaseSession
from src.api.schemas import (
    ApplicationRead,
    ApplicationStatusUpdate,
    CandidateCreateRequest,
    CandidateRead,
    CandidateStatusUpdate,
    DomainEventRead,
    JobSummary,
)
from src.domain.application import (
    APPLICATION_TRANSITIONS,
    CANDIDATE_TRANSITIONS,
    ApplicationStatus,
    CandidateStatus,
)
from src.services.application_service import (
    ApplicationNotFoundError,
    ApplicationService,
    CandidateNotFoundError,
    InvalidTransitionError,
    JobPostingNotFoundError,
)

router = APIRouter(prefix="/api", tags=["applications"])


def _job_summary(posting) -> JobSummary:
    return JobSummary(
        id=posting.id,
        company=posting.company,
        title=posting.title,
        source_url=posting.source_url,
    )


def _candidate_response(view) -> CandidateRead:
    status_value = CandidateStatus(view.candidate.status)
    return CandidateRead(
        id=view.candidate.id,
        user_id=view.candidate.user_id,
        job_posting_id=view.candidate.job_posting_id,
        status=status_value,
        available_transitions=sorted(
            CANDIDATE_TRANSITIONS[status_value],
            key=lambda item: item.value,
        ),
        job=_job_summary(view.posting),
        created_at=view.candidate.created_at,
        updated_at=view.candidate.updated_at,
    )


def _application_response(view) -> ApplicationRead:
    status_value = ApplicationStatus(view.application.status)
    return ApplicationRead(
        id=view.application.id,
        candidate_job_id=view.application.candidate_job_id,
        job_posting_id=view.candidate.job_posting_id,
        status=status_value,
        candidate_status=CandidateStatus(view.candidate.status),
        next_action=view.application.next_action,
        available_transitions=sorted(
            APPLICATION_TRANSITIONS[status_value],
            key=lambda item: item.value,
        ),
        job=_job_summary(view.posting),
        events=[
            DomainEventRead(
                id=event.id,
                entity_type=event.entity_type,
                entity_id=event.entity_id,
                event_type=event.event_type,
                payload=event.payload,
                created_at=event.created_at,
            )
            for event in view.events
        ],
        created_at=view.application.created_at,
        updated_at=view.application.updated_at,
    )


def _transition_error(error: InvalidTransitionError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "invalid_transition",
            "message": str(error),
            "entity": error.entity,
            "current": error.current,
            "target": error.target,
            "allowed": error.allowed,
        },
    )


@router.post("/candidates", response_model=CandidateRead, status_code=201)
def create_candidate(
    payload: CandidateCreateRequest,
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> CandidateRead:
    try:
        view = ApplicationService(session).create_candidate(
            user_id=user_id,
            job_posting_id=payload.job_posting_id,
        )
    except JobPostingNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "job_not_found", "message": "岗位不存在"},
        ) from error
    return _candidate_response(view)


@router.get("/candidates", response_model=list[CandidateRead])
def list_candidates(
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> list[CandidateRead]:
    return [
        _candidate_response(view)
        for view in ApplicationService(session).list_candidates(user_id=user_id)
    ]


@router.get("/candidates/{candidate_id}", response_model=CandidateRead)
def read_candidate(
    candidate_id: str,
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> CandidateRead:
    try:
        view = ApplicationService(session).get_candidate(
            user_id=user_id,
            candidate_id=candidate_id,
        )
    except CandidateNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "candidate_not_found", "message": "候选岗位不存在"},
        ) from error
    return _candidate_response(view)


@router.patch("/candidates/{candidate_id}/status", response_model=CandidateRead)
def transition_candidate(
    candidate_id: str,
    payload: CandidateStatusUpdate,
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> CandidateRead:
    try:
        view = ApplicationService(session).transition_candidate(
            user_id=user_id,
            candidate_id=candidate_id,
            target_status=payload.status,
        )
    except CandidateNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "candidate_not_found", "message": "候选岗位不存在"},
        ) from error
    except InvalidTransitionError as error:
        raise _transition_error(error) from error
    return _candidate_response(view)


@router.post(
    "/candidates/{candidate_id}/prepare-application",
    response_model=ApplicationRead,
)
def prepare_application(
    candidate_id: str,
    response: Response,
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> ApplicationRead:
    try:
        preparation = ApplicationService(session).prepare_application(
            user_id=user_id,
            candidate_id=candidate_id,
        )
    except CandidateNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "candidate_not_found", "message": "候选岗位不存在"},
        ) from error
    except InvalidTransitionError as error:
        raise _transition_error(error) from error
    response.status_code = (
        status.HTTP_201_CREATED if preparation.created else status.HTTP_200_OK
    )
    return _application_response(preparation.view)


@router.get("/applications", response_model=list[ApplicationRead])
def list_applications(
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> list[ApplicationRead]:
    return [
        _application_response(view)
        for view in ApplicationService(session).list_applications(user_id=user_id)
    ]


@router.get("/applications/{application_id}", response_model=ApplicationRead)
def read_application(
    application_id: str,
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> ApplicationRead:
    try:
        view = ApplicationService(session).get_application(
            user_id=user_id,
            application_id=application_id,
        )
    except ApplicationNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "application_not_found", "message": "申请记录不存在"},
        ) from error
    return _application_response(view)


@router.patch("/applications/{application_id}/status", response_model=ApplicationRead)
def transition_application(
    application_id: str,
    payload: ApplicationStatusUpdate,
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> ApplicationRead:
    try:
        view = ApplicationService(session).transition_application(
            user_id=user_id,
            application_id=application_id,
            target_status=payload.status,
            next_action=payload.next_action,
        )
    except ApplicationNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "application_not_found", "message": "申请记录不存在"},
        ) from error
    except InvalidTransitionError as error:
        raise _transition_error(error) from error
    return _application_response(view)


@router.get(
    "/applications/{application_id}/events",
    response_model=list[DomainEventRead],
)
def list_application_events(
    application_id: str,
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> list[DomainEventRead]:
    try:
        events = ApplicationService(session).list_events(
            user_id=user_id,
            application_id=application_id,
        )
    except ApplicationNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "application_not_found", "message": "申请记录不存在"},
        ) from error
    return [
        DomainEventRead(
            id=event.id,
            entity_type=event.entity_type,
            entity_id=event.entity_id,
            event_type=event.event_type,
            payload=event.payload,
            created_at=event.created_at,
        )
        for event in events
    ]
