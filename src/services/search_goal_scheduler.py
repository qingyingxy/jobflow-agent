"""Persisted opt-in schedules, one bounded search at a time per local server."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from fastapi import BackgroundTasks
from sqlalchemy import select, update

from src.domain.search_goal import SearchGoal
from src.infrastructure.database import SessionLocal

logger = logging.getLogger("jobflow.scheduler")


async def run_due_goals(session_factory=SessionLocal, *, now=None, dispatch=None):
    now = now or datetime.now(UTC)
    with session_factory() as session:
        goal = session.scalar(select(SearchGoal).where(
            SearchGoal.update_interval_minutes.in_([30, 60]), SearchGoal.next_update_at <= now,
        ).order_by(SearchGoal.next_update_at, SearchGoal.id).limit(1))
        if goal is None:
            return False
        goal_id = goal.id
        # Atomic claim also prevents duplicate work across a reload or two workers.
        claimed = session.execute(update(SearchGoal).where(
            SearchGoal.id == goal.id, SearchGoal.version == goal.version,
            SearchGoal.next_update_at == goal.next_update_at,
            SearchGoal.update_interval_minutes == goal.update_interval_minutes,
        ).values(next_update_at=now + timedelta(minutes=goal.update_interval_minutes))).rowcount
        session.commit()
        if not claimed:
            return False
        try:
            if dispatch:
                await dispatch(goal, session)
            else:
                from src.api.discovery import create_official_search
                from src.api.schemas import DiscoverySearchRequest

                tasks = BackgroundTasks()
                run = await create_official_search(DiscoverySearchRequest(
                    query=goal.input_text, source_mode="web", search_goal_id=goal.id,
                    search_goal_version=goal.version,
                ), tasks, goal.user_id, session)
                await tasks()
                from src.domain.discovery import DiscoveryRun

                session.expire_all()
                completed = session.get(DiscoveryRun, run.id)
                if completed and completed.status == "FAILED":
                    raise RuntimeError("scheduled search failed")
            session.expire_all()
            current = session.get(SearchGoal, goal_id)
            if current:
                current.schedule_error = None
                session.commit()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - failure is persisted; never kill the scheduler
            session.rollback()
            session.expire_all()
            current = session.get(SearchGoal, goal_id)
            if current:
                current.schedule_error = "自动更新失败，请检查搜索配置或手动重试。"
                session.commit()
            logger.warning("scheduled_search_failed")
        return True


async def scheduler_loop():
    while True:
        try:
            await run_due_goals()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - database may await its initial migration
            logger.warning("search_scheduler_unavailable")
        await asyncio.sleep(30)
