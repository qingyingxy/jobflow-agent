from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from src.api.dependencies import CurrentUserId, DatabaseSession
from src.services.portal_tracking import PortalRow, PortalTrackingService

router = APIRouter(prefix="/api/portal-tracking", tags=["portal-tracking"])


class Connect(BaseModel):
    url: str = Field(max_length=500)


class Report(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=1, max_length=64)
    state: Literal["READY", "LOGIN_REQUIRED", "ERROR", "PAGE_CHANGED"]
    page_url: str = Field(max_length=500)
    complete: bool = False
    rows: list[PortalRow] = Field(default_factory=list, max_length=500)


class Link(BaseModel):
    application_id: str | None = Field(default=None, max_length=40)


@router.get("")
def listing(user_id: CurrentUserId, session: DatabaseSession):
    return {"sources": PortalTrackingService(session).list(user_id)}


@router.post("", status_code=201)
def connect(payload: Connect, user_id: CurrentUserId, session: DatabaseSession):
    source = PortalTrackingService(session).create(user_id, payload.url)
    return {"id": source.id, "url": source.url}


@router.post("/{source_id}/sync")
def begin(source_id: str, user_id: CurrentUserId, session: DatabaseSession):
    return {"token": PortalTrackingService(session).begin(user_id, source_id)}


@router.post("/{source_id}/report")
def report(source_id: str, payload: Report, user_id: CurrentUserId, session: DatabaseSession):
    return PortalTrackingService(session).report(user_id, source_id, **payload.model_dump(exclude={"rows"}), rows=payload.rows)


@router.put("/records/{record_id}/application")
def link(record_id: str, payload: Link, user_id: CurrentUserId, session: DatabaseSession):
    PortalTrackingService(session).link(user_id, record_id, payload.application_id)
    return {"ok": True}
