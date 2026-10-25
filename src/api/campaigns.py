"""Read-only browsing, explicit refresh, and opt-in hourly company tracking."""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from src.api.dependencies import CurrentUserId, DatabaseSession
from src.config import get_settings
from src.services.campaign_discovery import enqueue_discovery
from src.services.campaign_service import campaign_snapshot, queue_checks, set_followed

router = APIRouter(prefix="/api/campaigns", tags=["recruitment-campaigns"])


class RefreshCampaigns(BaseModel):
    model_config = ConfigDict(extra="forbid")
    year: int = Field(ge=2000, le=2200)
    company_ids: list[str] | None = Field(default=None, min_length=1, max_length=6)


class FollowCompany(BaseModel):
    model_config = ConfigDict(extra="forbid")
    year: int = Field(ge=2000, le=2200)
    followed: bool


class DiscoverCompanies(BaseModel):
    model_config = ConfigDict(extra="forbid")
    year: int = Field(ge=2000, le=2200)


@router.post("/discover", status_code=202)
def discover_companies(payload: DiscoverCompanies, user_id: CurrentUserId, session: DatabaseSession):
    settings = get_settings()
    if not settings.company_discovery_enabled or settings.structured_model_provider == "fake":
        raise HTTPException(status_code=422, detail="请先启用公司发现并配置真实模型服务。")
    enqueue_discovery(session, user_id, payload.year)
    return campaign_snapshot(session, user_id, payload.year)


@router.get("")
def read_campaigns(user_id: CurrentUserId, session: DatabaseSession,
                   year: int | None = Query(default=None, ge=2000, le=2200)):
    return campaign_snapshot(session, user_id, year)


@router.post("/refresh", status_code=202)
def refresh_campaigns(payload: RefreshCampaigns, user_id: CurrentUserId, session: DatabaseSession):
    try:
        queue_checks(session, user_id, payload.year, payload.company_ids)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return campaign_snapshot(session, user_id, payload.year)


@router.put("/companies/{company_id}/watch")
def follow_company(company_id: str, payload: FollowCompany, user_id: CurrentUserId, session: DatabaseSession):
    try:
        set_followed(session, user_id, payload.year, company_id, payload.followed)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return campaign_snapshot(session, user_id, payload.year)
