from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Header, HTTPException, Response, status

from src.api.dependencies import CurrentUserId, DatabaseSession
from src.api.packet_schemas import (
    ApplicationPacketRead,
    PacketApprovalRequest,
    PacketDecisionRead,
    PacketGenerateRequest,
    PacketNewRevisionRequest,
    PacketRevisionEditRequest,
    PacketRevisionRead,
)
from src.services.application_packet_service import (
    ApplicationPacketError,
    ApplicationPacketNotFoundError,
    ApplicationPacketService,
    ApplicationPacketView,
    PacketRevisionView,
)
from src.services.application_service import ApplicationNotFoundError

router = APIRouter(prefix="/api", tags=["application-packets"])
ActorHeader = Annotated[
    Literal["user", "agent"], Header(alias="X-Actor-Type")
]


def _revision_response(view: PacketRevisionView) -> PacketRevisionRead:
    revision = view.revision
    return PacketRevisionRead(
        id=revision.id,
        packet_id=revision.packet_id,
        application_id=revision.application_id,
        job_posting_id=revision.job_posting_id,
        revision_number=revision.revision_number,
        status=revision.status,
        supersedes_revision_id=revision.supersedes_revision_id,
        job_analysis_id=revision.job_analysis_id,
        analysis_version=revision.analysis_version,
        analysis_input_hash=revision.analysis_input_hash,
        jd_content_hash=revision.jd_content_hash,
        profile_revision=revision.profile_revision,
        resume_version_id=revision.resume_version_id,
        source_fingerprint=revision.source_fingerprint,
        payload_hash=revision.payload_hash,
        job_snapshot=revision.job_snapshot,
        analysis_snapshot=revision.analysis_snapshot,
        profile_snapshot=revision.profile_snapshot,
        resume_snapshot=revision.resume_snapshot,
        evidence_snapshots=revision.evidence_snapshots,
        form_answer_snapshots=revision.form_answer_snapshots,
        open_questions=revision.open_questions,
        risk_snapshots=revision.risk_snapshots,
        confirmation_items=revision.confirmation_items,
        blockers=revision.blockers,
        created_by_actor=revision.created_by_actor,
        source_changed=view.source_changed,
        source_change_codes=view.source_change_codes,
        decisions=[
            PacketDecisionRead(
                id=decision.id,
                decision=decision.decision,
                actor_type=decision.actor_type,
                created_at=decision.created_at,
            )
            for decision in view.decisions
        ],
        created_at=revision.created_at,
        updated_at=revision.updated_at,
        submitted_for_review_at=revision.submitted_for_review_at,
        approved_at=revision.approved_at,
        superseded_at=revision.superseded_at,
    )


def _packet_response(view: ApplicationPacketView) -> ApplicationPacketRead:
    revisions = [_revision_response(item) for item in view.revisions]
    current = next(
        item for item in revisions if item.id == view.packet.current_revision_id
    )
    return ApplicationPacketRead(
        id=view.packet.id,
        user_id=view.packet.user_id,
        application_id=view.packet.application_id,
        job_posting_id=view.packet.job_posting_id,
        current_revision_id=view.packet.current_revision_id,
        status=view.packet.status,
        current_revision=current,
        revisions=revisions,
        created_at=view.packet.created_at,
        updated_at=view.packet.updated_at,
    )


def _raise_packet_error(error: ApplicationPacketError) -> None:
    if error.code == "user_approval_required":
        response_status = status.HTTP_403_FORBIDDEN
    elif error.code in {
        "resume_version_not_found",
        "evidence_not_found",
        "answer_not_found",
    }:
        response_status = status.HTTP_404_NOT_FOUND
    elif error.code in {"invalid_open_question", "agent_cannot_confirm"}:
        response_status = status.HTTP_422_UNPROCESSABLE_CONTENT
    else:
        response_status = status.HTTP_409_CONFLICT
    raise HTTPException(
        status_code=response_status,
        detail={
            "code": error.code,
            "message": str(error),
            **error.details,
        },
    ) from error


def _open_questions(payload) -> list[dict[str, object]]:
    return [item.model_dump(mode="json") for item in payload]


@router.post(
    "/applications/{application_id}/packet",
    response_model=ApplicationPacketRead,
)
def generate_packet(
    application_id: str,
    payload: PacketGenerateRequest,
    response: Response,
    user_id: CurrentUserId,
    session: DatabaseSession,
    actor_type: ActorHeader = "user",
) -> ApplicationPacketRead:
    try:
        result = ApplicationPacketService(session).generate(
            user_id=user_id,
            application_id=application_id,
            actor_type=actor_type,
            resume_version_id=payload.resume_version_id,
            evidence_ids=payload.evidence_ids,
            answer_entry_ids=payload.answer_entry_ids,
            open_questions=_open_questions(payload.open_questions),
        )
    except ApplicationNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "application_not_found", "message": "申请记录不存在"},
        ) from error
    except ApplicationPacketError as error:
        _raise_packet_error(error)
    response.status_code = (
        status.HTTP_201_CREATED if result.created else status.HTTP_200_OK
    )
    return _packet_response(result.view)


@router.get("/application-packets", response_model=list[ApplicationPacketRead])
def list_packets(
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> list[ApplicationPacketRead]:
    return [
        _packet_response(item)
        for item in ApplicationPacketService(session).list(user_id=user_id)
    ]


@router.get(
    "/application-packets/{packet_id}", response_model=ApplicationPacketRead
)
def read_packet(
    packet_id: str,
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> ApplicationPacketRead:
    try:
        view = ApplicationPacketService(session).get(
            user_id=user_id, packet_id=packet_id
        )
    except ApplicationPacketNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "packet_not_found", "message": "投递包不存在"},
        ) from error
    return _packet_response(view)


@router.get(
    "/packet-revisions/{revision_id}", response_model=PacketRevisionRead
)
def read_revision(
    revision_id: str,
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> PacketRevisionRead:
    try:
        view = ApplicationPacketService(session).get_revision(
            user_id=user_id, revision_id=revision_id
        )
    except ApplicationPacketNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "packet_revision_not_found", "message": "投递包版本不存在"},
        ) from error
    return _revision_response(view)


@router.patch(
    "/packet-revisions/{revision_id}/items",
    response_model=ApplicationPacketRead,
)
def edit_revision(
    revision_id: str,
    payload: PacketRevisionEditRequest,
    user_id: CurrentUserId,
    session: DatabaseSession,
    actor_type: ActorHeader = "user",
) -> ApplicationPacketRead:
    fields = payload.model_fields_set
    kwargs: dict[str, object] = {
        "evidence_ids": payload.evidence_ids if "evidence_ids" in fields else None,
        "answer_entry_ids": (
            payload.answer_entry_ids if "answer_entry_ids" in fields else None
        ),
        "open_questions": (
            _open_questions(payload.open_questions or [])
            if "open_questions" in fields
            else None
        ),
    }
    if "resume_version_id" in fields:
        kwargs["resume_version_id"] = payload.resume_version_id
    try:
        view = ApplicationPacketService(session).edit_revision(
            user_id=user_id,
            revision_id=revision_id,
            actor_type=actor_type,
            **kwargs,
        )
    except ApplicationPacketNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "packet_revision_not_found", "message": "投递包版本不存在"},
        ) from error
    except ApplicationPacketError as error:
        _raise_packet_error(error)
    return _packet_response(view)


@router.post(
    "/packet-revisions/{revision_id}/review",
    response_model=ApplicationPacketRead,
)
def submit_revision_for_review(
    revision_id: str,
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> ApplicationPacketRead:
    try:
        view = ApplicationPacketService(session).submit_for_review(
            user_id=user_id, revision_id=revision_id
        )
    except ApplicationPacketNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "packet_revision_not_found", "message": "投递包版本不存在"},
        ) from error
    except ApplicationPacketError as error:
        _raise_packet_error(error)
    return _packet_response(view)


@router.post(
    "/packet-revisions/{revision_id}/approve",
    response_model=ApplicationPacketRead,
)
def approve_revision(
    revision_id: str,
    payload: PacketApprovalRequest,
    user_id: CurrentUserId,
    session: DatabaseSession,
    actor_type: ActorHeader = "user",
) -> ApplicationPacketRead:
    try:
        view = ApplicationPacketService(session).approve(
            user_id=user_id,
            revision_id=revision_id,
            actor_type=actor_type,
            confirmed=payload.confirmed,
        )
    except ApplicationPacketNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "packet_revision_not_found", "message": "投递包版本不存在"},
        ) from error
    except ApplicationPacketError as error:
        _raise_packet_error(error)
    return _packet_response(view)


@router.post(
    "/application-packets/{packet_id}/revisions",
    response_model=ApplicationPacketRead,
    status_code=status.HTTP_201_CREATED,
)
def create_revision(
    packet_id: str,
    payload: PacketNewRevisionRequest,
    user_id: CurrentUserId,
    session: DatabaseSession,
    actor_type: ActorHeader = "user",
) -> ApplicationPacketRead:
    fields = payload.model_fields_set
    kwargs: dict[str, object] = {
        "evidence_ids": payload.evidence_ids if "evidence_ids" in fields else None,
        "answer_entry_ids": (
            payload.answer_entry_ids if "answer_entry_ids" in fields else None
        ),
        "open_questions": (
            _open_questions(payload.open_questions or [])
            if "open_questions" in fields
            else None
        ),
    }
    if "resume_version_id" in fields:
        kwargs["resume_version_id"] = payload.resume_version_id
    try:
        view = ApplicationPacketService(session).create_revision(
            user_id=user_id,
            packet_id=packet_id,
            actor_type=actor_type,
            **kwargs,
        )
    except ApplicationPacketNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "packet_not_found", "message": "投递包不存在"},
        ) from error
    except ApplicationPacketError as error:
        _raise_packet_error(error)
    return _packet_response(view)
