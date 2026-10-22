"""Measure saved-body recovery on an isolated backup, using the configured model."""

import argparse
import asyncio
import json
import logging
import os
import sqlite3
import sys
import traceback
from pathlib import Path
from time import monotonic

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--source", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--seconds", type=int, default=360)
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=False)
database = (args.output / "trial.db").resolve()
with sqlite3.connect(args.source.resolve().as_uri() + "?mode=ro", uri=True) as source, sqlite3.connect(database) as target:
    source.backup(target)
os.environ["DATABASE_URL"] = "sqlite:///" + database.as_posix()
os.environ["APP_ENV"] = "testing"

from alembic import command
from alembic.config import Config
from sqlalchemy import select

from scripts.saved_body_integrity import verify_saved_body_changes
from src.domain.job import JobPosting
from src.domain.search_goal import SearchGoal
from src.infrastructure.database import SessionLocal
from src.services.body_review_queue import enqueue_body_review, run_body_review_batch
from src.services.search_goal_service import SearchGoalService

command.upgrade(Config(str(ROOT / "alembic.ini")), "head")


class QueueErrors(logging.Handler):
    def emit(self, record):
        if not record.exc_info:
            return

        def describe(error):
            return {"type": type(error).__name__, "frames": [
                {"file": frame.filename, "line": frame.lineno, "function": frame.name}
                for frame in traceback.extract_tb(error.__traceback__)],
                "children": [describe(child) for child in getattr(error, "exceptions", [])]}

        # Record error types and code locations, never provider responses/keys.
        save("queue-errors.json", describe(record.exc_info[1]))


queue_logger = logging.getLogger("jobflow.body_review")
queue_logger.disabled = False
queue_logger.addHandler(QueueErrors())


def snapshot():
    with SessionLocal() as session:
        goal = session.scalar(select(SearchGoal).where(SearchGoal.user_id == "local-user").order_by(SearchGoal.updated_at.desc()))
        return {"library": SearchGoalService(session).library(goal.user_id, goal.id),
                "sources": {job.id: [job.content_hash, job.source_url, job.raw_content, str(job.last_verified_at)] for job in session.scalars(select(JobPosting))}}


def save(name, value):
    (args.output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


async def main():
    before = snapshot()
    save("before.json", before)
    with SessionLocal() as session:
        goal = session.get(SearchGoal, before["library"]["goal_id"])
        enqueue_body_review(session, goal, retry_failed=True)
    start = monotonic()
    batches = []
    while monotonic() - start < args.seconds:
        worked = await run_body_review_batch()
        after = snapshot()
        progress = {"elapsed_seconds": round(monotonic() - start, 2), **after["library"]["review_queue"]}
        if worked:
            batches.append(progress)
            save("after.json", after)
            save("progress.json", {"batches": batches, **progress})
            print(json.dumps(progress, ensure_ascii=False), flush=True)
        if progress["status"] not in {"queued", "running"}:
            break
        if not worked:
            await asyncio.sleep(5)
    after = snapshot()
    # Interpreting a saved unparsed page may legitimately create a new job.
    unchanged = all(after["sources"].get(identifier) == source for identifier, source in before["sources"].items())
    integrity = verify_saved_body_changes(args.source, database, before["sources"], after["sources"])
    save("source-integrity.json", integrity)
    result = {"elapsed_seconds": round(monotonic() - start, 2), "batches": batches,
              "before_counts": before["library"]["counts"], "after_counts": after["library"]["counts"],
              "queue": after["library"]["review_queue"], "source_bodies_urls_and_read_times_unchanged": unchanged,
              "source_integrity_passed": integrity["passed"],
              "new_postings": len(after["sources"]) - len(before["sources"])}
    save("after.json", after)
    save("result.json", result)
    assert integrity["passed"], "Changed sources must trace exactly to preexisting newer saved snapshots"


asyncio.run(main())
