"""Read-only tracking overview; polling never starts a search or changes a stage."""
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request
from sqlalchemy import select

from src.api.dependencies import CurrentUserId, DatabaseSession
from src.api.search_goals import GoalRead
from src.domain.application import Application, CandidateJob
from src.domain.discovery import DiscoveryRun
from src.domain.follow_up import FollowUpTask
from src.domain.job import JobPosting
from src.domain.search_goal import SearchGoal
from src.services.follow_up_service import FollowUpService

router = APIRouter(prefix="/api/tracking", tags=["tracking"])


def utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def tracking_snapshot(session, user_id, *, now=None, scheduler_running=False):
    now = now or datetime.now(UTC)
    goals = list(session.scalars(select(SearchGoal).where(SearchGoal.user_id == user_id)
                                .order_by(SearchGoal.updated_at.desc(), SearchGoal.id)))
    runs = session.scalars(select(DiscoveryRun).where(
        DiscoveryRun.user_id == user_id,
        DiscoveryRun.search_goal_id.in_([goal.id for goal in goals]),
    ).order_by(DiscoveryRun.started_at.desc(), DiscoveryRun.id.desc())) if goals else []
    versions = {goal.id: goal.version for goal in goals}
    latest = {}
    for run in runs:
        if run.search_goal_version == versions.get(run.search_goal_id):
            latest.setdefault(run.search_goal_id, run)
    searches = []
    for goal in goals:
        run = latest.get(goal.id)
        searches.append({
            "goal": GoalRead.model_validate(goal).model_dump(mode="json"),
            "latest_run": None if run is None else {
                "id": run.id, "status": run.status,
                "started_at": utc(run.started_at).isoformat(),
                "finished_at": utc(run.finished_at).isoformat() if run.finished_at else None,
                "new_count": run.new_count,
            },
        })
    # Terminal applications retain their history without issuing new reminders.
    rows = session.execute(select(FollowUpTask, JobPosting).join(
        Application, Application.id == FollowUpTask.application_id,
    ).join(CandidateJob, CandidateJob.id == Application.candidate_job_id).join(
        JobPosting, JobPosting.id == CandidateJob.job_posting_id,
    ).where(
        FollowUpTask.user_id == user_id, CandidateJob.user_id == user_id,
        FollowUpTask.status == "PENDING",
        Application.status.in_(["SUBMITTED", "ASSESSMENT", "INTERVIEW", "OFFER"]),
    ).order_by(FollowUpTask.scheduled_at, FollowUpTask.id)).all()
    tasks = []
    service = FollowUpService(session)
    for task, job in rows:
        view = service._view(task, now=now)
        scheduled = utc(task.scheduled_at)
        reminder = scheduled - timedelta(minutes=30)
        if task.all_day:
            reminder = datetime.combine(view.local_scheduled_at.date(), time(9),
                                        tzinfo=ZoneInfo(task.timezone)).astimezone(UTC)
        tasks.append({
            "id": task.id, "application_id": task.application_id, "title": task.title,
            "company": job.company, "job_title": job.title,
            "scheduled_at": scheduled.isoformat(), "local_scheduled_at": view.local_scheduled_at.isoformat(),
            "reminder_at": reminder.isoformat(), "all_day": task.all_day,
            "is_overdue": view.is_overdue, "next_action": task.next_action,
        })
    today = now.astimezone(ZoneInfo("Asia/Shanghai")).date()
    return {
        "checked_at": now.isoformat(), "scheduler_running": scheduler_running,
        "searches": searches, "tasks": tasks,
        "counts": {
            "scheduled_goals": sum(goal.update_interval_minutes > 0 for goal in goals),
            "overdue": sum(task["is_overdue"] for task in tasks),
            "today": sum(datetime.fromisoformat(task["scheduled_at"]).astimezone(
                ZoneInfo("Asia/Shanghai")).date() == today for task in tasks),
            "attention": sum(task["is_overdue"] or datetime.fromisoformat(task["scheduled_at"]).astimezone(
                ZoneInfo("Asia/Shanghai")).date() == today for task in tasks),
        },
    }


@router.get("/summary")
def read_tracking(request: Request, user_id: CurrentUserId, session: DatabaseSession):
    return tracking_snapshot(session, user_id,
                             scheduler_running=bool(getattr(request.app.state, "scheduler_running", False)))
