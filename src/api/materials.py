from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, Response

from src.api.dependencies import CurrentUserId, DatabaseSession
from src.api.materials_schemas import (
    AnswerBankCreate,
    AnswerBankRead,
    AnswerBankUpdate,
    CandidatePrivateProfileRead,
    CandidatePrivateProfileUpdate,
    ResumeAssetRead,
    ResumeVersionCreate,
    ResumeVersionRead,
    ResumeVersionUpdate,
)
from src.domain.materials import CandidatePrivateProfile, ResumeVersion
from src.services.candidate_material_service import (
    PROFILE_FIELDS,
    CandidateMaterialConflictError,
    CandidateMaterialNotFoundError,
    CandidateMaterialService,
    CandidateMaterialValidationError,
)

router = APIRouter(prefix="/api", tags=["candidate-materials"])


def _raise_api_error(exception: Exception) -> None:
    if isinstance(exception, CandidateMaterialNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "material_not_found", "message": str(exception)},
        ) from exception
    if isinstance(exception, CandidateMaterialConflictError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "material_conflict", "message": str(exception)},
        ) from exception
    if isinstance(exception, CandidateMaterialValidationError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "material_validation_error", "message": str(exception)},
        ) from exception
    raise exception


def _profile_read(
    service: CandidateMaterialService,
    profile: CandidatePrivateProfile,
) -> CandidatePrivateProfileRead:
    payload: dict[str, object] = {
        "user_id": profile.user_id,
        "revision": profile.revision,
        "voluntary_disclosure_policy": profile.voluntary_disclosure_policy,
        "created_at": profile.created_at,
        "updated_at": profile.updated_at,
    }
    for field_name, (state_column, value_column, _) in PROFILE_FIELDS.items():
        payload[field_name] = {
            "state": getattr(profile, state_column),
            "value": getattr(profile, value_column),
        }
    confirmation_items = service.profile_confirmation_items(profile)
    payload["readiness"] = (
        "needs_confirmation" if confirmation_items else "ready"
    )
    payload["needs_confirmation"] = confirmation_items
    return CandidatePrivateProfileRead.model_validate(payload)


def _version_read(
    service: CandidateMaterialService,
    *,
    user_id: str,
    version: ResumeVersion,
) -> ResumeVersionRead:
    asset = service.get_resume_asset(user_id=user_id, asset_id=version.asset_id)
    return ResumeVersionRead(
        id=version.id,
        user_id=version.user_id,
        asset_id=version.asset_id,
        version_number=version.version_number,
        label=version.label,
        job_family=version.job_family,
        source_version_id=version.source_version_id,
        generation_reason=version.generation_reason,
        is_default=version.is_default,
        asset=ResumeAssetRead.model_validate(asset),
        created_at=version.created_at,
        updated_at=version.updated_at,
    )


@router.get("/private-profile", response_model=CandidatePrivateProfileRead)
def read_private_profile(
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> CandidatePrivateProfileRead:
    service = CandidateMaterialService(session)
    return _profile_read(service, service.get_or_create_profile(user_id))


@router.put("/private-profile", response_model=CandidatePrivateProfileRead)
def update_private_profile(
    payload: CandidatePrivateProfileUpdate,
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> CandidatePrivateProfileRead:
    changes: dict[str, object] = {}
    for field_name in payload.model_fields_set:
        value = getattr(payload, field_name)
        changes[field_name] = (
            value.value if field_name == "voluntary_disclosure_policy" else value.model_dump()
        )
    service = CandidateMaterialService(session)
    try:
        profile = service.update_profile(user_id=user_id, changes=changes)
    except Exception as exception:
        _raise_api_error(exception)
        raise
    return _profile_read(service, profile)


@router.post(
    "/resumes/assets",
    response_model=ResumeAssetRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_resume_asset(
    file: Annotated[UploadFile, File(description="PDF or DOCX resume")],
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> ResumeAssetRead:
    service = CandidateMaterialService(session)
    content = await file.read(service.resume_max_bytes + 1)
    await file.close()
    try:
        asset = service.upload_resume_asset(
            user_id=user_id,
            filename=file.filename or "",
            media_type=file.content_type or "",
            content=content,
        )
    except Exception as exception:
        _raise_api_error(exception)
        raise
    return ResumeAssetRead.model_validate(asset)


@router.get("/resumes/assets", response_model=list[ResumeAssetRead])
def list_resume_assets(
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> list[ResumeAssetRead]:
    return [
        ResumeAssetRead.model_validate(asset)
        for asset in CandidateMaterialService(session).list_resume_assets(user_id)
    ]


@router.get("/resumes/assets/{asset_id}/download", response_class=FileResponse)
def download_resume_asset(
    asset_id: str,
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> FileResponse:
    service = CandidateMaterialService(session)
    try:
        asset, path = service.get_resume_download(user_id=user_id, asset_id=asset_id)
    except Exception as exception:
        _raise_api_error(exception)
        raise
    return FileResponse(
        path=path,
        media_type=asset.media_type,
        filename=asset.original_filename,
    )


@router.post(
    "/resumes/versions",
    response_model=ResumeVersionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_resume_version(
    payload: ResumeVersionCreate,
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> ResumeVersionRead:
    service = CandidateMaterialService(session)
    try:
        version = service.create_resume_version(
            user_id=user_id,
            **payload.model_dump(),
        )
    except Exception as exception:
        _raise_api_error(exception)
        raise
    return _version_read(service, user_id=user_id, version=version)


@router.get("/resumes/versions", response_model=list[ResumeVersionRead])
def list_resume_versions(
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> list[ResumeVersionRead]:
    service = CandidateMaterialService(session)
    return [
        _version_read(service, user_id=user_id, version=version)
        for version in service.list_resume_versions(user_id)
    ]


@router.patch(
    "/resumes/versions/{version_id}", response_model=ResumeVersionRead
)
def update_resume_version(
    version_id: str,
    payload: ResumeVersionUpdate,
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> ResumeVersionRead:
    service = CandidateMaterialService(session)
    try:
        version = service.update_resume_version(
            user_id=user_id,
            version_id=version_id,
            changes=payload.model_dump(exclude_unset=True),
        )
    except Exception as exception:
        _raise_api_error(exception)
        raise
    return _version_read(service, user_id=user_id, version=version)


@router.post(
    "/answer-bank",
    response_model=AnswerBankRead,
    status_code=status.HTTP_201_CREATED,
)
def create_answer_bank_entry(
    payload: AnswerBankCreate,
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> AnswerBankRead:
    service = CandidateMaterialService(session)
    changes = payload.model_dump(mode="json", exclude={"confirmed"})
    try:
        entry = service.create_answer(user_id=user_id, **changes)
    except Exception as exception:
        _raise_api_error(exception)
        raise
    return AnswerBankRead.model_validate(entry)


@router.get("/answer-bank", response_model=list[AnswerBankRead])
def list_answer_bank_entries(
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> list[AnswerBankRead]:
    return [
        AnswerBankRead.model_validate(entry)
        for entry in CandidateMaterialService(session).list_answers(user_id)
    ]


@router.patch("/answer-bank/{answer_id}", response_model=AnswerBankRead)
def update_answer_bank_entry(
    answer_id: str,
    payload: AnswerBankUpdate,
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> AnswerBankRead:
    service = CandidateMaterialService(session)
    changes = payload.model_dump(
        mode="json", exclude={"confirmed"}, exclude_unset=True
    )
    try:
        entry = service.update_answer(
            user_id=user_id,
            answer_id=answer_id,
            changes=changes,
        )
    except Exception as exception:
        _raise_api_error(exception)
        raise
    return AnswerBankRead.model_validate(entry)


@router.delete("/answer-bank/{answer_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_answer_bank_entry(
    answer_id: str,
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> Response:
    try:
        CandidateMaterialService(session).delete_answer(
            user_id=user_id,
            answer_id=answer_id,
        )
    except Exception as exception:
        _raise_api_error(exception)
        raise
    return Response(status_code=status.HTTP_204_NO_CONTENT)
