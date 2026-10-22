"""Run a timed personal-use search trial on a read-only backup of the user's DB."""

import argparse
import asyncio
import json
import os
import sqlite3
import sys
from collections import Counter
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--database", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--minutes", type=float, default=30)
parser.add_argument("--goal-id", default="goal_510142e137774f3ea1f7")
args = parser.parse_args()
folder = args.output.resolve()
if not folder.is_relative_to(ROOT / "artifacts"):
    parser.error("Trial output must stay in artifacts/")
if args.minutes <= 0:
    parser.error("Trial duration must be positive")
folder.mkdir(parents=True, exist_ok=False)
with (
    sqlite3.connect(args.database.resolve().as_uri() + "?mode=ro", uri=True) as source,
    sqlite3.connect(folder / "trial.db") as target,
):
    source.backup(target)
os.environ["DATABASE_URL"] = "sqlite:///" + (folder / "trial.db").as_posix()
os.environ["APP_ENV"] = "testing"

from fastapi import BackgroundTasks
from sqlalchemy import select

from src.api.search_goals import GoalSearchRequest, search_saved_goal
from src.config import get_settings
from src.domain.discovery import DiscoveryRun, JobLead
from src.domain.job import JobPosting
from src.domain.search_goal import SearchGoal
from src.infrastructure.database import SessionLocal
from src.services.body_review_queue import body_review_loop, enqueue_body_review
from src.services.company_discovery_queue import company_discovery_loop
from src.services.search_goal_service import SearchGoalService


def save(name, data):
    (folder / name).write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def jobs_snapshot(session):
    return [{"id": j.id, "title": j.title, "company": j.company, "source_url": j.source_url,
             "raw_content": j.raw_content, "recruitment_context": j.recruitment_context,
             "availability_status": j.availability_status, "last_verified_at": j.last_verified_at}
            for j in session.scalars(select(JobPosting)).all()]


def snapshot():
    with SessionLocal() as session:
        goal = session.get(SearchGoal, args.goal_id)
        return {"at": datetime.now(UTC).isoformat(),
                "goal": {"id": goal.id, "query": goal.query, "conditions": goal.conditions,
                         "company_ids": goal.company_ids, "version": goal.version},
                "library": SearchGoalService(session).library(goal.user_id, goal.id),
                "company_search_state": goal.company_search_state, "jobs": jobs_snapshot(session)}


async def main():
    baseline = snapshot()
    save("baseline.json", baseline)
    with SessionLocal() as session:
        enqueue_body_review(session, session.get(SearchGoal, args.goal_id))
    # Use the same independent workers as the app. Older trials only dispatched
    # foreground searches, which left saved-body and company discovery work idle.
    workers = [asyncio.create_task(body_review_loop()), asyncio.create_task(company_discovery_loop())]
    settings = get_settings()
    configuration = {name: getattr(settings, name) for name in (
        "web_search_provider", "web_search_decision_mode", "web_search_understanding_mode",
        "web_search_budget_seconds", "web_search_company_target", "web_search_semantic_max_calls")}
    configuration["background_workers"] = ["body_review", "company_discovery"]
    save("configuration.json", configuration)
    initial_ids = {j["id"] for j in baseline["jobs"]}
    started = monotonic()
    started_at = datetime.now(UTC).isoformat()
    rounds = []
    continued = Counter()
    latest = baseline
    print(json.dumps({"event": "started", "at": started_at, "minutes": args.minutes,
                      "baseline": baseline["library"]["counts"], "settings": configuration}, ensure_ascii=False), flush=True)
    while monotonic() - started < args.minutes * 60:
        index = len(rounds) + 1
        company = None
        # Follow the ordinary UI: two update rounds, then alternate updating and
        # continuing companies with remaining candidates. Never reset cursors.
        if index > 2 and index % 2:
            choices = [p for p in latest["library"]["company_progress"]
                       if p["can_continue"] and (p["remaining_count"] or p["pending_count"])]
            if choices:
                pick = min(choices, key=lambda p: (continued[p["source_id"]],
                           -p["matched_count"], -p["remaining_count"]))
                company = pick["source_id"]
                continued[company] += 1
        with SessionLocal() as session:
            goal = session.get(SearchGoal, args.goal_id)
            tasks = BackgroundTasks()
            run = await search_saved_goal(goal.id,
                GoalSearchRequest(expected_version=goal.version, continue_company_id=company),
                tasks, goal.user_id, session)
            run_id = run.id
        round_started = monotonic()
        print(json.dumps({"event": "round_started", "round": index, "run_id": run_id,
                          "continue_company": company, "elapsed": round(round_started-started, 1)}, ensure_ascii=False), flush=True)
        task = asyncio.create_task(tasks())
        while not task.done():
            await asyncio.wait([task], timeout=20)
            save("heartbeat.json", {"at": datetime.now(UTC).isoformat(), "round": index,
                "elapsed_seconds": round(monotonic()-started, 2),
                "worker_errors": [type(w.exception()).__name__ for w in workers if w.done() and not w.cancelled() and w.exception()]})
            with SessionLocal() as session:
                run = session.get(DiscoveryRun, run_id)
                print(json.dumps({"event": "progress", "round": index,
                    "elapsed": round(monotonic()-started, 1), "status": run.status,
                    "counts": dict(Counter(m["review_status"] for m in run.result_matches)),
                    "reads": (run.usage_metrics or {}).get("read_attempts")}, ensure_ascii=False), flush=True)
        task_error = None
        try:
            await task
        except Exception as exc:  # noqa: BLE001 - preserve failed live-trial evidence
            task_error = type(exc).__name__ + ": " + str(exc)[:500]
        latest = snapshot()
        with SessionLocal() as session:
            run = session.get(DiscoveryRun, run_id)
            leads = session.scalars(select(JobLead).where(JobLead.discovery_run_id == run_id)).all()
            report = {"round": index, "run_id": run_id, "continue_company": company,
                "status": run.status, "error": task_error,
                "elapsed_seconds": round(monotonic()-round_started, 2),
                "trial_elapsed_seconds": round(monotonic()-started, 2),
                "metrics": run.usage_metrics, "matches": run.result_matches, "trace": run.agent_trace,
                "library_counts": latest["library"]["counts"],
                "company_progress": latest["library"]["company_progress"],
                "company_search_state": latest["company_search_state"],
                "leads": [{"url": lead.source_url, "status": lead.status,
                           "job_posting_id": lead.job_posting_id, "failure_code": lead.failure_code,
                           "failure_reason": lead.failure_reason} for lead in leads]}
        save(f"round-{index:02d}.json", report)
        rounds.append({k: v for k, v in report.items() if k not in {"matches", "trace", "company_search_state", "leads", "company_progress"}})
        save("latest.json", latest)
        save("progress.json", {"started_at": started_at, "elapsed_seconds": round(monotonic()-started, 2),
             "rounds": rounds, "new_jobs": sum(j["id"] not in initial_ids for j in latest["jobs"]),
             "library_counts": latest["library"]["counts"]})
        print(json.dumps({"event": "round_finished", "round": index,
            "elapsed": round(monotonic()-started, 1), "library": latest["library"]["counts"],
            "new_jobs": sum(j["id"] not in initial_ids for j in latest["jobs"])}, ensure_ascii=False), flush=True)
    for worker in workers:
        worker.cancel()
    for worker in workers:
        with suppress(asyncio.CancelledError):
            await worker
    save("final.json", snapshot())
    save("complete.json", {"started_at": started_at, "finished_at": datetime.now(UTC).isoformat(),
         "elapsed_seconds": round(monotonic()-started, 2), "round_count": len(rounds)})
    print(json.dumps({"event": "complete", "elapsed": round(monotonic()-started, 1),
                      "rounds": len(rounds), "folder": str(folder)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
