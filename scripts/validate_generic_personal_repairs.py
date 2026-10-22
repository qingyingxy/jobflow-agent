"""Replay saved public bodies and one official continuation on an isolated DB."""

import argparse
import asyncio
import json
import os
import sqlite3
import sys
from pathlib import Path
from time import monotonic
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def save(folder, name, value):
    (folder / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


async def run(folder, *, live):
    from fastapi import BackgroundTasks

    from src.api.search_goals import GoalSearchRequest, search_saved_goal
    from src.config import get_settings
    from src.domain.discovery import DiscoveryRun
    from src.domain.job import JobPosting
    from src.domain.search_goal import SearchGoal
    from src.infrastructure.database import SessionLocal
    from src.services.body_review_queue import (
        enqueue_body_review,
        review_items,
        run_body_review_batch,
        select_review_batch,
    )
    from src.services.personal_requirements import personal_requirement_hints
    from src.services.qualification_understanding import (
        cached_qualifications,
        review_qualifications,
    )
    from src.services.search_goal_service import SearchGoalService, posting_stub
    from src.services.source_understanding import SourceUnderstanding

    goal_id = "goal_510142e137774f3ea1f7"
    began = monotonic()
    with SessionLocal() as session:
        goal = session.get(SearchGoal, goal_id)
        settings = get_settings()
        service = SearchGoalService(session)
        timing = {}
        for label, operation in {
            "library_without_progress": lambda: service.library(goal.user_id, goal_id, include_progress=False),
            "progress": lambda: service.progress(goal.user_id, goal_id),
            "full_library": lambda: service.library(goal.user_id, goal_id),
        }.items():
            samples = []
            for _ in range(3):
                started = monotonic()
                operation()
                samples.append(round(monotonic() - started, 3))
            timing[label] = samples
        save(folder, "latency.json", timing)
        items = review_items(session, goal)
        chosen = select_review_batch(items, goal)
        save(folder, "next-batch.json", [{"id": row[0], "title": session.get(JobPosting, row[0]).title if not row[1] else "saved page",
            "failures": row[2].get("failures"), "qualification_only": row[2].get("qualification_only", False)} for row in chosen])
        query, conditions, user_id = goal.query, goal.conditions, goal.user_id
        if not live:
            return
        enqueue_body_review(session, goal)
    for i in range(2):
        await run_body_review_batch(settings=settings, goal_id=goal_id)
        with SessionLocal() as session:
            save(folder, f"batch-{i+1}.json", SearchGoalService(session).progress(user_id, goal_id))
        print(json.dumps({"stage": "body_batch", "batch": i + 1, "elapsed": round(monotonic() - began, 1)}), flush=True)

    runtime = SourceUnderstanding(settings, query=query, conditions=conditions)
    hints = []
    for identifier in ("job_3154e59aef6b488f8afb", "job_2cb8d050aa7848ba8184"):
        with SessionLocal() as session:
            job = session.get(JobPosting, identifier)
            original = posting_stub(job)
            updated = await review_qualifications(runtime, original)
            job.recruitment_context = updated.recruitment_context
            session.commit()
            hints.append({"id": job.id, "title": job.title, "ai_extraction_saved": cached_qualifications(updated) is not None,
                "hints_for_synthetic_master": personal_requirement_hints(job, SimpleNamespace(degree="硕士", educations=[]))})
    save(folder, "qualification-results.json", hints)
    with SessionLocal() as session:
        save(folder, "after-body-library.json", SearchGoalService(session).library(user_id, goal_id))
        background = BackgroundTasks()
        goal = session.get(SearchGoal, goal_id)
        result = await search_saved_goal(goal_id, GoalSearchRequest(expected_version=goal.version, continue_company_id="xpeng"), background, user_id, session)
        run_id = result.id
    await background()
    with SessionLocal() as session:
        search_run = session.get(DiscoveryRun, run_id)
        save(folder, "official-continuation.json", {"status": search_run.status, "metrics": search_run.usage_metrics,
            "trace": search_run.agent_trace, "matches": search_run.result_matches})
        save(folder, "final-library.json", SearchGoalService(session).library(user_id, goal_id))
    save(folder, "complete.json", {"elapsed_seconds": round(monotonic() - began, 1), "live": True,
        "personal_database_changed": False, "profile_sent_to_model": False})
    print("Validation complete; observations saved.", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    folder = ROOT / "artifacts/generic-personal-repairs-20261019"
    database = folder / "trial.db"
    if not database.exists():
        with (sqlite3.connect((ROOT / "artifacts/continuous-use-20261019/trial.db").as_uri() + "?mode=ro", uri=True) as source,
              sqlite3.connect(database) as target):
            source.backup(target)
    os.environ["DATABASE_URL"] = "sqlite:///" + database.as_posix()
    os.environ["APP_ENV"] = "testing"
    asyncio.run(run(folder, live=args.live))


if __name__ == "__main__":
    main()
