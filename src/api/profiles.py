from fastapi import APIRouter, HTTPException

from src.api.dependencies import CurrentUserId, DatabaseSession
from src.api.schemas import ProfileRead, ProfileUpdate
from src.services.profile_service import ProfileService

router = APIRouter(prefix="/api", tags=["profile"])


@router.get("/profile", response_model=ProfileRead)
def read_profile(user_id: CurrentUserId, session: DatabaseSession) -> ProfileRead:
    profile = ProfileService(session).get(user_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="用户画像不存在")
    return profile


@router.put("/profile", response_model=ProfileRead)
def upsert_profile(
    payload: ProfileUpdate,
    user_id: CurrentUserId,
    session: DatabaseSession,
) -> ProfileRead:
    changes = payload.model_dump(mode="json", exclude_unset=True)
    return ProfileService(session).upsert(user_id, changes)
