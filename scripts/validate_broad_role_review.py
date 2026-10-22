"""Replay audited public job bodies through the current model, without database writes."""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from time import monotonic

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from src.config import get_settings
from src.domain.job import JobPosting
from src.domain.search_goal import SearchGoal
from src.services.discovery_matching import classify_discovery_job
from src.services.search_goal_service import posting_stub
from src.services.source_understanding import (
    PREVIOUS_VERSION,
    VERSION,
    SourceUnderstanding,
    checked_decisions,
    pending_review_fields,
)

# Previously inspected development cases, not an independent accuracy benchmark.
CASES = {
    "job_6b32768fe41640e5b7de": "retain_adjacent",
    "job_8972c1f3ee734c5fb462": "direct",
    "job_71afa14b6db94b899a17": "direct",
    "job_572bf85b163b483ea0e9": "cohort_conflict",
    "job_8997bc68439a4fa894c2": "unrelated",
    "job_143704412edb4f3090dd": "unrelated",
    "job_491178895f31464fbee8": "unrelated",
    "job_422ea98cf1854920af19": "retain_adjacent",
}


async def main(args):
    args.output.mkdir(parents=True, exist_ok=False)
    engine = create_engine(f"sqlite:///file:{args.source.resolve().as_posix()}?mode=ro&uri=true")
    with Session(engine) as session:
        goal = session.scalar(select(SearchGoal).where(SearchGoal.user_id == "local-user")
                              .order_by(SearchGoal.updated_at.desc()))
        query, conditions = goal.query, goal.conditions
        samples = [(job.id, posting_stub(job)) for job in session.scalars(
            select(JobPosting).where(JobPosting.id.in_(CASES)))]
    engine.dispose()
    assert len(samples) == len(CASES), "All recorded regression cases must exist"
    settings = get_settings().model_copy(update={"web_search_semantic_max_calls": 30,
        "web_search_semantic_timeout_seconds": get_settings().web_search_semantic_retry_timeout_seconds})
    events = []
    runtime = SourceUnderstanding(settings, query=query, conditions=conditions,
        on_event=lambda kind, data: events.append({"kind": kind, **data}))
    assert runtime.primary, "A configured real model is required"
    slots = asyncio.Semaphore(settings.web_search_semantic_concurrency)
    results = []
    started = monotonic()

    async def check(identifier, original):
        async with slots:
            before = checked_decisions(original, conditions, version=PREVIOUS_VERSION)
            current = original
            passes = []
            for _ in range(2):
                if not pending_review_fields(current, query=query, conditions=conditions, primary=True):
                    break
                current = await runtime.review(current, query=query, conditions=conditions)
                passes.append(checked_decisions(current, conditions))
            after = checked_decisions(current, conditions)
            role = after.get("role", {})
            expected = CASES[identifier]
            passed = (role.get("status") == "matched" if expected == "direct" else
                      role.get("status") == "excluded" if expected == "unrelated" else
                      after.get("graduation_year", {}).get("status") == "excluded" if expected == "cohort_conflict" else
                      role.get("status") in {"matched", "pending"} and not role.get("review_required"))
            result = {"id": identifier, "title": current.title, "url": current.detail_url,
                "expected": expected, "passed": passed, "before": before, "after": after, "passes": passes,
                "final_status": classify_discovery_job(current, query=query, conditions=conditions, primary=True).filter_status,
                "source_unchanged": current.raw_content == original.raw_content,
                "attempt": current.recruitment_context.get("source_review_attempt"),
                "record": current.recruitment_context.get("source_understanding")}
            results.append(result)
            (args.output / "progress.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({key: result[key] for key in ("id", "title", "expected", "passed", "final_status")}, ensure_ascii=False), flush=True)

    await asyncio.gather(*(check(identifier, stub) for identifier, stub in samples))
    report = {"version": VERSION, "elapsed_seconds": round(monotonic() - started, 2),
        "model_calls": runtime.calls, "samples": len(results), "passed": sum(r["passed"] for r in results),
        "scope": "Real model, saved public bodies, development regressions; no website reads or database writes.",
        "results": results, "events": events}
    (args.output / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("samples", "passed", "model_calls", "elapsed_seconds")}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(main(parser.parse_args()))
