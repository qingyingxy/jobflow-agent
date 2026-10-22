"""Follow ordinary queue scheduling on an isolated copy of the prior trial."""

import argparse
import asyncio
import importlib.util
import json
import os
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TRACKED = ["job_bf7af428430c44c8862e", "job_657c90c3eba3479b837c"]
GOAL_ID = "goal_510142e137774f3ea1f7"


def save(folder, name, value):
    (folder / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


async def run(folder, *, live, max_batches, seconds):
    from src.config import get_settings
    from src.domain.discovery import JobLead
    from src.domain.job import JobPosting
    from src.domain.search_goal import SearchGoal
    from src.infrastructure.database import SessionLocal
    from src.services.body_review_queue import (
        enqueue_body_review,
        review_items,
        review_queue_summary,
        run_body_review_batch,
        select_review_batch,
    )
    from src.services.search_goal_service import SearchGoalService, posting_stub
    from src.services.source_understanding import (
        checked_decisions,
        pending_review_fields,
        review_attempt,
    )

    began = monotonic()
    events = []

    def event(name, details):
        row = {"at": datetime.now(UTC).isoformat(), "elapsed_seconds": round(monotonic() - began, 3),
               "event": name, "details": details}
        events.append(row)
        with (folder / "events.jsonl").open("a", encoding="utf-8") as output:
            output.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")

    def selected(session, rows):
        result = []
        for identifier, page, attempt in rows:
            obj = session.get(JobLead if page else JobPosting, identifier)
            result.append({"id": identifier, "title": getattr(obj, "title", None) or getattr(obj, "title_hint", None),
                "lane": "qualifications" if attempt.get("qualification_only") else "source",
                "failures": attempt.get("failures", 0), "tracked": identifier in TRACKED})
        return result

    def snapshot():
        with SessionLocal() as session:
            goal = session.get(SearchGoal, GOAL_ID)
            library = SearchGoalService(session).library(goal.user_id, goal.id, include_progress=False)
            matches = {match["job_posting_id"]: match for match in library["result_matches"]}
            jobs = []
            for identifier in TRACKED:
                job = session.get(JobPosting, identifier)
                stub = posting_stub(job)
                decisions = checked_decisions(stub, goal.conditions)
                jobs.append({"id": identifier, "title": job.title, "source_url": job.source_url,
                    "attempt": review_attempt(stub, goal.conditions), "decisions": decisions,
                    "interpreted": bool(decisions) and not pending_review_fields(stub, query=goal.query,
                        conditions=goal.conditions, primary=True, ignore_retry_limits=True),
                    "display": matches.get(identifier)})
            return {"elapsed_seconds": round(monotonic() - began, 3), "tracked": jobs,
                "queue": review_queue_summary(session, goal), "library": library}

    with SessionLocal() as session:
        goal = session.get(SearchGoal, GOAL_ID)
        items = review_items(session, goal)
        old_path = folder / "before/src/services/body_review_queue.py"
        spec = importlib.util.spec_from_file_location("queue_before_trial", old_path)
        before = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(before)
        save(folder, "selection-comparison.json", {
            "before": selected(session, before.select_review_batch(items, goal)),
            "after": selected(session, select_review_batch(items, goal)),
        })
        if live:
            enqueue_body_review(session, goal)
    initial = snapshot()
    save(folder, "initial.json", initial)
    if not live:
        return
    settings = get_settings()
    count = 0
    while count < max_batches and monotonic() - began < seconds:
        with SessionLocal() as session:
            goal = session.get(SearchGoal, GOAL_ID)
            planned = selected(session, select_review_batch(review_items(session, goal), goal))
        try:
            worked = await asyncio.wait_for(run_body_review_batch(settings=settings,
                goal_id=GOAL_ID, on_event=event), timeout=max(.1, seconds - (monotonic() - began)))
        except TimeoutError:
            event("trial_budget", {"message": "Time budget reached; durable checkpoints retained"})
            break
        if not worked:
            await asyncio.sleep(1)
            continue
        count += 1
        current = snapshot()
        save(folder, f"batch-{count}.json", {"selected": planned, **current})
        print(json.dumps({"batch": count, "elapsed_seconds": current["elapsed_seconds"],
            "tracked": [{"title": j["title"], "interpreted": j["interpreted"],
                "error": j["attempt"].get("error_code")} for j in current["tracked"]]}, ensure_ascii=False), flush=True)
        if all(job["interpreted"] for job in current["tracked"]):
            break
        await asyncio.sleep(1)
    final = snapshot()
    save(folder, "final.json", final)
    save(folder, "complete.json", {"batches": count, "elapsed_seconds": round(monotonic() - began, 3),
        "both_interpreted": all(job["interpreted"] for job in final["tracked"]),
        "personal_database_changed": False, "profile_sent_to_model": False,
        "source_calls": sum(e["event"] == "source_understanding" and e["details"].get("stage") != "job_qualifications"
                            and "duration_ms" in e["details"] for e in events),
        "qualification_calls": sum(e["event"] == "source_understanding" and e["details"].get("stage") == "job_qualifications"
                                   and "duration_ms" in e["details"] for e in events)})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--max-batches", type=int, default=6)
    parser.add_argument("--seconds", type=float, default=600)
    args = parser.parse_args()
    folder = ROOT / "artifacts/queue-recovery-20261019"
    folder.mkdir(exist_ok=True)
    database = folder / "trial.db"
    if not database.exists():
        with (sqlite3.connect((ROOT / "artifacts/generic-personal-repairs-20261019/trial.db").as_uri() + "?mode=ro", uri=True) as source,
              sqlite3.connect(database) as target):
            source.backup(target)
    os.environ["DATABASE_URL"] = "sqlite:///" + database.as_posix()
    os.environ["APP_ENV"] = "testing"
    asyncio.run(run(folder, live=args.live, max_batches=args.max_batches, seconds=args.seconds))


if __name__ == "__main__":
    main()
