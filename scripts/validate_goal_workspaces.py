"""Replay real saved bodies against both targets on an isolated database."""

import argparse
import asyncio
import json
import os
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TARGETS = ("goal_510142e137774f3ea1f7", "goal_e34b3c1d59e84092ac86")
JOBS = ("job_f317df23c43e462182a8", "job_a57fba9d38b24de3b42b", "job_361d9bdbdae643cb9e0e")


async def validate(folder):
    os.environ["DATABASE_URL"] = "sqlite:///" + (folder / "trial.db").as_posix()
    os.environ["APP_ENV"] = "testing"
    from src.config import get_settings
    from src.domain.job import JobPosting
    from src.domain.search_goal import SearchGoal
    from src.infrastructure.database import SessionLocal
    from src.services.search_goal_service import SearchGoalService, posting_stub
    from src.services.search_intent import interpret_intent
    from src.services.source_understanding import (
        SourceUnderstanding,
        checked_decisions,
        pending_review_fields,
    )

    settings = get_settings().model_copy(update={"web_search_semantic_timeout_seconds": 25,
        "web_search_semantic_max_calls": 12})
    if settings.structured_model_provider == "fake" or settings.web_search_understanding_mode != "ai":
        raise RuntimeError("Real model configuration is required")
    receipt = {"started_at": datetime.now(UTC).isoformat(), "isolated": True, "model_calls": 0,
               "cases": [], "conditions": {}, "before": {}, "after": {}}
    for wording in ("杭州/深圳，2027届校招，Java后端", "杭州/深圳，2027届校招，Java后端开发"):
        conditions, _, _ = await interpret_intent(wording, settings=settings)
        receipt["conditions"][wording] = conditions.model_dump()
    assert len({json.dumps(c, sort_keys=True) for c in receipt["conditions"].values()}) == 1
    with SessionLocal() as session:
        for target in TARGETS:
            receipt["before"][target] = SearchGoalService(session).library("local-user", target, summary_only=True)
    for target in TARGETS:
        runtime = SourceUnderstanding(settings, include_qualifications=False)
        with SessionLocal() as session:
            goal = session.get(SearchGoal, target)
            query, conditions = goal.query, goal.conditions
        for identifier in JOBS:
            with SessionLocal() as session:
                original = posting_stub(session.get(JobPosting, identifier))

            def checkpoint(updated, identifier=identifier):
                with SessionLocal() as write:
                    current = write.get(JobPosting, identifier)
                    current.recruitment_context = updated.recruitment_context
                    write.commit()

            reviewed = await runtime.review(original, query=query, conditions=conditions, on_checkpoint=checkpoint)
            receipt["cases"].append({"goal_id": target, "job_id": identifier, "title": original.title,
                "checks": checked_decisions(reviewed, conditions, primary=True),
                "remaining_fields": pending_review_fields(reviewed, query=query, conditions=conditions,
                                                          primary=True, ignore_retry_limits=True)})
            (folder / "live-review.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        receipt["model_calls"] += runtime.calls
    # Reopen and alternate targets repeatedly, like page navigation after a
    # worker restart. None of the finished source decisions should be lost.
    for target in (*TARGETS, *reversed(TARGETS), *TARGETS):
        with SessionLocal() as session:
            goal = session.get(SearchGoal, target)
            for identifier in JOBS:
                current = posting_stub(session.get(JobPosting, identifier))
                assert not pending_review_fields(current, query=goal.query, conditions=goal.conditions,
                                                 primary=True, ignore_retry_limits=True), (target, identifier)
            receipt["after"][target] = SearchGoalService(session).library("local-user", target, include_progress=False)
    receipt["finished_at"] = datetime.now(UTC).isoformat()
    receipt["passed"] = True
    (folder / "live-review.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"passed": True, "jobs": len(JOBS), "targets": len(TARGETS),
                      "model_calls": receipt["model_calls"],
                      "counts": {g: r["counts"] for g, r in receipt["after"].items()}}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    folder = args.output.resolve()
    if not folder.is_relative_to(ROOT / "artifacts"):
        parser.error("Use an isolated artifact directory")
    folder.mkdir(exist_ok=False, parents=True)
    with sqlite3.connect(args.source.resolve().as_uri() + "?mode=ro", uri=True) as src, sqlite3.connect(folder / "trial.db") as dst:
        src.backup(dst)
    asyncio.run(validate(folder))


if __name__ == "__main__":
    main()
