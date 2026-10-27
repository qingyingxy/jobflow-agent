import re
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import update

from src.api.dependencies import CurrentUserId, DatabaseSession
from src.api.schemas import DiscoveryRunRead, DiscoverySearchRequest
from src.api.timestamps import UtcTimestamp
from src.config import get_settings
from src.domain.education import EducationRecord, education_summary
from src.domain.models import UserProfile
from src.domain.search_goal import SearchGoal, SearchGoalConditions
from src.services.search_goal_service import SearchGoalService
from src.services.search_intent import interpret_intent

router = APIRouter(prefix="/api/discovery/goals", tags=["search-goals"])


class GoalWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input_text: str = Field(min_length=2, max_length=500)
    conditions: SearchGoalConditions | None = None
    name: str | None = Field(default=None, min_length=1, max_length=100)
    company_ids: list[str] | None = Field(default=None, max_length=40)
    expected_version: int | None = Field(default=None, ge=1)


class GoalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    input_text: str
    query: str
    conditions: SearchGoalConditions
    condition_sources: dict[str, str]
    version: int
    company_ids: list[str] | None
    update_interval_minutes: int = 0
    next_update_at: UtcTimestamp | None = None
    schedule_error: str | None = None
    created_at: UtcTimestamp
    updated_at: UtcTimestamp


class GoalSearchRequest(BaseModel):
    expected_version: int = Field(ge=1)
    continue_company_id: str | None = Field(default=None, max_length=100)


class GoalScheduleWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    interval_minutes: Literal[0, 30, 60]


@router.put("/{goal_id}/schedule", response_model=GoalRead)
def update_schedule(goal_id: str, payload: GoalScheduleWrite, user_id: CurrentUserId, session: DatabaseSession):
    try:
        goal = SearchGoalService(session).get(user_id, goal_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    if goal.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="目标已变化，请刷新后设置更新频率")
    changed = session.execute(update(SearchGoal).where(
        SearchGoal.id == goal_id, SearchGoal.user_id == user_id,
        SearchGoal.version == payload.expected_version,
    ).values(
        update_interval_minutes=payload.interval_minutes,
        next_update_at=datetime.now(UTC) + timedelta(minutes=payload.interval_minutes) if payload.interval_minutes else None,
        schedule_error=None,
    )).rowcount
    if not changed:
        session.rollback()
        raise HTTPException(status_code=409, detail="目标已变化，请刷新后设置更新频率")
    session.commit()
    return goal


async def resolved_conditions(payload, user_id, session):
    if payload.conditions is not None:
        return (
            payload.conditions,
            {k: "用户修改" for k, v in payload.conditions.model_dump().items() if v},
            None,
        )
    conditions, sources, notice = await interpret_intent(
        payload.input_text, settings=get_settings()
    )
    profile = session.get(UserProfile, user_id)
    # Only an unambiguous, supported education record can supply the cohort.
    if (
        not conditions.graduation_years
        and sources.get("_intent_status") != "needs_review"
        and not sources.get("graduation_years")
        and profile
        and profile.educations
        and not re.search(r"届|毕业", payload.input_text)
    ):
        _, _, year = education_summary(
            [EducationRecord.model_validate(r) for r in profile.educations]
        )
        if year is not None:
            conditions.graduation_years = [year]
            sources["graduation_years"] = "已确认的个人资料（可修改）"
    return conditions, sources, notice


@router.post("/interpret")
async def interpret_goal(
    payload: GoalWrite, user_id: CurrentUserId, session: DatabaseSession
):
    try:
        conditions, sources, notice = await resolved_conditions(
            payload, user_id, session
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {
        "conditions": conditions.model_dump(),
        "condition_sources": sources,
        "notice": notice,
    }


@router.get("", response_model=list[GoalRead])
def list_goals(user_id: CurrentUserId, session: DatabaseSession):
    return SearchGoalService(session).list(user_id)


@router.get("/overview")
def goal_overview(user_id: CurrentUserId, session: DatabaseSession):
    service = SearchGoalService(session)
    return [service.library(user_id, goal.id, include_progress=False, summary_only=True)
            for goal in service.list(user_id)]


async def save_goal(payload, user_id, session, goal_id=None):
    try:
        conditions, sources, notice = await resolved_conditions(payload, user_id, session)
        if sources.get("_intent_status") == "needs_review":
            raise ValueError(notice)
        return SearchGoalService(session).save(
            user_id=user_id,
            goal_id=goal_id,
            input_text=payload.input_text,
            conditions=conditions,
            condition_sources=sources,
            name=payload.name,
            company_ids=payload.company_ids,
            expected_version=payload.expected_version,
        )
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("", response_model=GoalRead, status_code=201)
async def create_goal(
    payload: GoalWrite, user_id: CurrentUserId, session: DatabaseSession
):
    return await save_goal(payload, user_id, session)


@router.patch("/{goal_id}", response_model=GoalRead)
async def update_goal(
    goal_id: str, payload: GoalWrite, user_id: CurrentUserId, session: DatabaseSession
):
    return await save_goal(payload, user_id, session, goal_id)


@router.get("/{goal_id}/library")
def read_goal_library(goal_id: str, user_id: CurrentUserId, session: DatabaseSession, include_progress: bool = True, compact: bool = False):
    try:
        return SearchGoalService(session).library(user_id, goal_id, include_progress=include_progress, compact=compact)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/{goal_id}/jobs/{job_id}")
def read_goal_job(goal_id: str, job_id: str, expected_version: int, user_id: CurrentUserId, session: DatabaseSession):
    service = SearchGoalService(session)
    try:
        goal = service.get(user_id, goal_id)
        if goal.version != expected_version:
            raise HTTPException(status_code=409, detail="目标条件已变化，请刷新岗位列表")
        return service.library(user_id, goal_id, include_progress=False, job_id=job_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/{goal_id}/progress")
def read_goal_progress(goal_id: str, user_id: CurrentUserId, session: DatabaseSession):
    try:
        return SearchGoalService(session).progress(user_id, goal_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/{goal_id}/review", status_code=202)
def review_saved_bodies(goal_id: str, payload: GoalSearchRequest, user_id: CurrentUserId, session: DatabaseSession):
    from src.services.body_review_queue import enqueue_body_review, review_queue_summary
    from src.services.source_understanding import ai_policy_enabled

    try:
        goal = SearchGoalService(session).get(user_id, goal_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    if goal.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="目标条件已变化，请刷新后再复核")
    if not ai_policy_enabled():
        raise HTTPException(status_code=422, detail="请先配置并启用 AI 原文理解")
    enqueue_body_review(session, goal, retry_failed=True)
    return review_queue_summary(session, goal)


@router.post("/{goal_id}/search", response_model=DiscoveryRunRead, status_code=202)
async def search_saved_goal(
    goal_id: str,
    payload: GoalSearchRequest,
    background_tasks: BackgroundTasks,
    user_id: CurrentUserId,
    session: DatabaseSession,
):
    from src.api.discovery import create_official_search

    try:
        goal = SearchGoalService(session).get(user_id, goal_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    if goal.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="目标条件已变更，请刷新后再搜索")
    return await create_official_search(
        DiscoverySearchRequest(
            query=goal.input_text,
            source_mode="web",
            search_goal_id=goal.id,
            search_goal_version=goal.version,
            continue_company_id=payload.continue_company_id,
        ),
        background_tasks,
        user_id,
        session,
    )


@router.post("/{goal_id}/discover", status_code=202)
def discover_goal_companies(goal_id: str, payload: GoalSearchRequest, user_id: CurrentUserId, session: DatabaseSession):
    from src.config import get_settings
    from src.services.company_discovery_queue import (
        discovery_queue_summary,
        enqueue_company_discovery,
    )

    try:
        goal = SearchGoalService(session).get(user_id, goal_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    if goal.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="目标条件已变更，请刷新后重试")
    settings = get_settings()
    if not settings.company_discovery_enabled or settings.structured_model_provider == "fake":
        raise HTTPException(status_code=409, detail="请先配置并启用公司发现")
    if goal.company_ids:
        raise HTTPException(status_code=409, detail="当前目标限定了公司范围，请先取消公司限定")
    enqueue_company_discovery(session, goal, retry=True)
    return discovery_queue_summary(session, goal)
