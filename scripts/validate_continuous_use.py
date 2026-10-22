"""Three real-use sessions on one isolated DB, with actual worker restarts.

Wall-clock dates, source timestamps and cooldowns are never fast-forwarded.
Only the gaps between visits are compressed; this is not a multi-day soak.
"""

import argparse
import asyncio
import json
import logging
import os
import sqlite3
import subprocess
import sys
import traceback
from collections import Counter
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def backup(source, destination):
    with sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True) as src, sqlite3.connect(destination) as dst:
        src.backup(dst)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sessions", type=int, default=3)
    parser.add_argument("--search-seconds", type=int, default=360)
    parser.add_argument("--idle-seconds", type=int, default=240)
    parser.add_argument("--visit", type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument("--goal-id", default="goal_510142e137774f3ea1f7")
    args = parser.parse_args()
    folder = args.output.resolve()
    if not folder.is_relative_to(ROOT / "artifacts") or folder == ROOT / "artifacts":
        parser.error("Use a dedicated directory under artifacts/")
    if args.search_seconds < 0 or args.idle_seconds < 0 or not 1 <= args.sessions <= 10:
        parser.error("Invalid duration or session count")
    if args.visit:
        asyncio.run(visit(args, folder))
        return
    if not args.source or not args.source.is_file():
        parser.error("Supply an existing source database")
    folder.mkdir(parents=True, exist_ok=False)
    backup(args.source, folder / "trial.db")
    backup(args.source, folder / "baseline.db")
    manifest = {"source": str(args.source.resolve()), "started_at": datetime.now(UTC).isoformat(),
        "sessions": args.sessions, "search_seconds_per_session": args.search_seconds,
        "idle_seconds_per_session": args.idle_seconds, "goal_id": args.goal_id,
        "live_network_and_model": True, "clock_advanced": False,
        "limits": "Gaps between visits compressed; no claims about multi-day stability or expired caches."}
    save(folder / "manifest.json", manifest)
    started = monotonic()
    processes = []
    for number in range(1, args.sessions + 1):
        command = [sys.executable, "-X", "utf8", str(Path(__file__).resolve()),
            "--output", str(folder), "--visit", str(number), "--goal-id", args.goal_id,
            "--search-seconds", str(args.search_seconds), "--idle-seconds", str(args.idle_seconds)]
        with (folder / f"visit-{number:02d}.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
            processes.append({"visit": number, "pid": process.pid})
            save(folder / "processes.json", processes)
            result = process.wait()
        processes[-1]["returncode"] = result
        save(folder / "processes.json", processes)
        print(json.dumps({"visit": number, "returncode": result, "elapsed_seconds": round(monotonic() - started, 2)}), flush=True)
        if result:
            break
    save(folder / "complete.json", {"started_at": manifest["started_at"],
        "finished_at": datetime.now(UTC).isoformat(), "elapsed_seconds": round(monotonic() - started, 2),
        "processes": processes, "passed": len(processes) == args.sessions and all(p["returncode"] == 0 for p in processes)})


async def visit(args, folder):
    os.environ["DATABASE_URL"] = "sqlite:///" + (folder / "trial.db").as_posix()
    os.environ["APP_ENV"] = "testing"
    from fastapi import BackgroundTasks
    from sqlalchemy import select

    from src.api.search_goals import GoalSearchRequest, search_saved_goal
    from src.config import get_settings
    from src.domain.application import CandidateJob
    from src.domain.discovery import DiscoveryRun, JobLead
    from src.domain.job import JobPosting
    from src.domain.search_goal import SearchGoal
    from src.infrastructure.database import SessionLocal
    from src.services.body_review_queue import (
        body_review_loop,
        review_items,
        review_queue_summary,
    )
    from src.services.company_discovery_queue import company_discovery_loop
    from src.services.search_goal_scheduler import scheduler_loop
    from src.services.search_goal_service import SearchGoalService
    from src.services.source_understanding import VERSION

    directory = folder / f"visit-{args.visit:02d}"
    directory.mkdir(exist_ok=False)
    errors = []

    class SafeErrors(logging.Handler):
        def emit(self, record):
            if record.levelno < logging.WARNING:
                return
            row = {"at": datetime.now(UTC).isoformat(), "logger": record.name,
                "event": str(record.msg) if not record.args else "parameterized_warning"}
            if record.exc_info:
                def describe(error):
                    return {"type": type(error).__name__, "frames": [
                        {"file": Path(f.filename).name, "line": f.lineno, "function": f.name}
                        for f in traceback.extract_tb(error.__traceback__)],
                        "children": [describe(child) for child in getattr(error, "exceptions", [])]}
                row["exception"] = describe(record.exc_info[1])
            errors.append(row)
            save(directory / "worker-errors.json", errors)

    # Never log model endpoints, credentials, request bodies or provider responses.
    for name in ("jobflow.body_review", "jobflow.company_discovery", "jobflow.scheduler"):
        logger = logging.getLogger(name)
        logger.disabled = False
        logger.addHandler(SafeErrors())
        logger.propagate = False

    started = monotonic()
    events = []
    workers = []

    def event(kind, **values):
        row = {"event": kind, "visit": args.visit, "at": datetime.now(UTC).isoformat(),
            "elapsed_seconds": round(monotonic() - started, 2), **values}
        events.append(row)
        save(directory / "events.json", events)
        save(folder / "heartbeat.json", row)
        print(json.dumps(row, ensure_ascii=False, default=str), flush=True)

    def snapshot(name):
        began = monotonic()
        with SessionLocal() as session:
            goal = session.get(SearchGoal, args.goal_id)
            library = SearchGoalService(session).library(goal.user_id, goal.id)
            items = [{"id": job.id, "kind": "lead" if isinstance(job, JobLead) else "job", "state": state,
                "failures": attempt.get("failures", 0), "attempted_at": attempt.get("attempted_at")}
                for job, state, attempt in review_items(session, goal)]
            value = {"at": datetime.now(UTC).isoformat(),
                "goal": {"id": goal.id, "version": goal.version, "query": goal.query, "conditions": goal.conditions,
                    "schedule_minutes": goal.update_interval_minutes},
                "library": library, "review_items": items, "company_search_state": goal.company_search_state,
                "candidates": [{"id": c.id, "job_id": c.job_posting_id, "status": c.status}
                    for c in session.scalars(select(CandidateJob).where(CandidateJob.user_id == goal.user_id))],
                "jobs": [{"id": j.id, "title": j.title, "company": j.company, "source_url": j.source_url,
                    "raw_content": j.raw_content, "recruitment_context": j.recruitment_context,
                    "content_hash": j.content_hash, "last_verified_at": j.last_verified_at,
                    "availability_status": j.availability_status} for j in session.scalars(select(JobPosting))]}
        value["snapshot_seconds"] = round(monotonic() - began, 3)
        save(directory / name, value)
        save(folder / "latest.json", value)
        return value

    def heartbeat(stage, run_id=None):
        with SessionLocal() as session:
            goal = session.get(SearchGoal, args.goal_id)
            queue = review_queue_summary(session, goal)
            run = session.get(DiscoveryRun, run_id) if run_id else None
            worker_errors = [type(w.exception()).__name__ for w in workers
                if w.done() and not w.cancelled() and w.exception()]
            event(stage, queue=queue, run_id=run_id, run_status=run.status if run else None,
                worker_errors=worker_errors,
                counts=dict(Counter(m["review_status"] for m in (run.result_matches or []))) if run else None)
            if worker_errors:
                raise RuntimeError("A background worker exited unexpectedly")

    settings = get_settings()
    if settings.structured_model_provider == "fake" or settings.web_search_understanding_mode != "ai":
        raise RuntimeError("This trial requires real model configuration and AI understanding")
    save(directory / "configuration.json", {"understanding_version": VERSION,
        **{key: getattr(settings, key) for key in ("web_search_provider", "web_search_decision_mode",
            "web_search_understanding_mode", "web_search_budget_seconds", "web_search_company_target",
            "web_search_semantic_concurrency", "web_search_semantic_max_calls")}})
    baseline = snapshot("before.json")
    event("visit_started", counts=baseline["library"]["counts"], queue=baseline["library"]["review_queue"])
    # Match app lifespan: the persistent workers, not direct test-only batches.
    workers = [asyncio.create_task(loop()) for loop in (body_review_loop, company_discovery_loop, scheduler_loop)]
    current = baseline
    rounds = []
    continued = Counter()
    task = None
    try:
        search_start = monotonic()
        while monotonic() - search_start < args.search_seconds:
            number = len(rounds) + 1
            company = None
            if number % 2 == 0:
                choices = [p for p in current["library"]["company_progress"]
                    if p["can_continue"] and (p["remaining_count"] or p["pending_count"])]
                # The final visit also exercises the user's retry action for a
                # paused website with no readable list yet, not just good lists.
                if args.visit == 3:
                    failed_sources = [p for p in current["library"]["company_progress"]
                        if p["can_continue"] and p.get("reason") in
                        {"entry_retry_pending", "listing_not_ready", "listing_entry_only"}]
                    choices = failed_sources or choices
                if choices:
                    pick = min(choices, key=lambda p: (continued[p["source_id"]], -p["matched_count"], -p["remaining_count"]))
                    company = pick["source_id"]
                    continued[company] += 1
            began = monotonic()
            with SessionLocal() as session:
                goal = session.get(SearchGoal, args.goal_id)
                background = BackgroundTasks()
                run = await search_saved_goal(goal.id, GoalSearchRequest(expected_version=goal.version,
                    continue_company_id=company), background, goal.user_id, session)
                run_id = run.id
            event("search_started", round=number, run_id=run_id, company=company)
            task = asyncio.create_task(background())
            while not task.done():
                await asyncio.wait([task], timeout=25)
                heartbeat("search_progress", run_id)
            error = None
            try:
                await task
            except Exception as exc:  # noqa: BLE001 - retain failed real trials
                error = type(exc).__name__
            current = snapshot(f"after-round-{number:02d}.json")
            with SessionLocal() as session:
                run = session.get(DiscoveryRun, run_id)
                leads = session.scalars(select(JobLead).where(JobLead.discovery_run_id == run_id)).all()
                result = {"round": number, "visit": args.visit, "run_id": run_id, "continue_company": company,
                    "elapsed_seconds": round(monotonic() - began, 2), "status": run.status, "error": error,
                    "metrics": run.usage_metrics, "matches": run.result_matches, "trace": run.agent_trace,
                    "leads": [{"url": l.source_url, "status": l.status, "job_posting_id": l.job_posting_id,
                        "failure_code": l.failure_code} for l in leads],
                    "library_counts": current["library"]["counts"], "queue": current["library"]["review_queue"]}
            save(directory / f"round-{number:02d}.json", result)
            rounds.append(result)
            event("search_finished", round=number, seconds=result["elapsed_seconds"], status=result["status"],
                error=error, counts=result["library_counts"], queue=result["queue"])
        snapshot("idle-start.json")
        event("user_away_background_only")
        deadline = monotonic() + args.idle_seconds
        while monotonic() < deadline:
            await asyncio.sleep(min(25, max(0, deadline - monotonic())))
            heartbeat("idle_progress")
    finally:
        if task and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        for worker in workers:
            worker.cancel()
        for worker in workers:
            with suppress(asyncio.CancelledError):
                await worker
        final = snapshot("after.json")
        event("visit_stopped", counts=final["library"]["counts"], queue=final["library"]["review_queue"])
        save(directory / "complete.json", {"visit": args.visit, "elapsed_seconds": round(monotonic() - started, 2),
            "rounds": len(rounds), "worker_warning_count": len(errors), "worker_errors": errors,
            "before_counts": baseline["library"]["counts"], "after_counts": final["library"]["counts"]})


if __name__ == "__main__":
    main()
