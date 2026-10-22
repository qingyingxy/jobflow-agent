"""Opt-in live saved-goal trial on an isolated copy, never the personal DB."""

import argparse
import asyncio
import json
import os
import sqlite3
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--database", type=Path, default=ROOT / "tmp/company-discovery-validation/saved-goal-20261017-145757/before.db")
parser.add_argument("--goal-id", default="goal_510142e137774f3ea1f7")
parser.add_argument("--companies", nargs="+")
parser.add_argument("--continue-company")
parser.add_argument("--restart-listings", action="store_true", help="Acceptance only: reset completed cursors while retaining observed entry proof")
parser.add_argument("--seconds", type=int, choices=range(30, 301), default=180)
parser.add_argument("--output", type=Path, help="New directory for this isolated trial")
args = parser.parse_args()
folder = args.output or ROOT / "artifacts" / ("source-search-" + datetime.now(UTC).astimezone().strftime("%Y%m%d-%H%M%S"))
folder.mkdir(parents=True)
baseline = args.database.resolve(strict=True)
with (
    sqlite3.connect(baseline.as_uri() + "?mode=ro", uri=True) as source,
    sqlite3.connect(folder / "trial.db") as target,
):
    source.backup(target)
os.environ["DATABASE_URL"] = "sqlite:///" + (folder / "trial.db").as_posix()
os.environ["WEB_SEARCH_BUDGET_SECONDS"] = str(args.seconds)

from fastapi import BackgroundTasks
from sqlalchemy import select

from src.api.search_goals import GoalSearchRequest, search_saved_goal
from src.domain.discovery import DiscoveryRun, JobLead
from src.domain.job import JobPosting
from src.domain.search_goal import SearchGoal, SearchGoalConditions
from src.infrastructure.database import SessionLocal
from src.services.search_intent import conditions_query


async def main():
    with SessionLocal() as session:
        baseline_jobs = [{"id": j.id, "url": j.source_url} for j in session.scalars(select(JobPosting)).all()]
        goal = session.get(SearchGoal, args.goal_id)
        if goal is None:
            raise ValueError("Saved goal not found")
        roles = list(goal.conditions.get("roles", []))
        if not any(role.casefold() in {"ai产品", "ai产品经理"} for role in roles):
            roles.append("AI产品")
        conditions = SearchGoalConditions.model_validate({**goal.conditions, "roles": roles})
        changed = conditions.model_dump() != goal.conditions or (args.companies is not None and args.companies != goal.company_ids)
        goal.conditions = conditions.model_dump()
        goal.query = conditions_query(conditions)
        if changed:
            goal.version += 1
        if args.companies is not None:
            goal.company_ids = args.companies
        if args.restart_listings:
            import copy

            state = copy.deepcopy(goal.company_search_state or {})
            for source in state.get("sources", {}).values():
                source["status"] = "completed"
            goal.company_search_state = state
        session.commit()
        tasks = BackgroundTasks()
        run = await search_saved_goal(goal.id, GoalSearchRequest(expected_version=goal.version, continue_company_id=args.continue_company), tasks, goal.user_id, session)
        run_id, query = run.id, goal.query
    print(json.dumps({"folder": str(folder), "run_id": run_id, "query": query}, ensure_ascii=False), flush=True)
    started = monotonic()
    task = asyncio.create_task(tasks())
    while not task.done():
        await asyncio.wait([task], timeout=20)
        with SessionLocal() as session:
            run = session.get(DiscoveryRun, run_id)
            print(json.dumps({"elapsed": round(monotonic() - started, 1), "status": run.status,
                "counts": dict(Counter(m["review_status"] for m in run.result_matches)),
                "read_attempts": (run.usage_metrics or {}).get("read_attempts")}, ensure_ascii=False), flush=True)
    await task
    with SessionLocal() as session:
        run = session.get(DiscoveryRun, run_id)
        jobs = [session.get(JobPosting, m["job_posting_id"]) for m in run.result_matches]
        leads = session.scalars(select(JobLead).where(JobLead.discovery_run_id == run_id)).all()
        report = {"run_id": run_id, "query": query, "status": run.status,
            "scope": "isolated_saved_goal_full_live_search", "input_database": str(baseline),
            "companies": args.companies, "continue_company": args.continue_company,
            "restart_listings": args.restart_listings,
            "budget_seconds": args.seconds, "elapsed_seconds": round(monotonic() - started, 2),
            "metrics": run.usage_metrics, "matches": run.result_matches, "trace": run.agent_trace,
            "baseline_jobs": baseline_jobs,
            "company_search_state": session.get(SearchGoal, args.goal_id).company_search_state,
            "jobs": [{"id": j.id, "title": j.title, "company": j.company, "source_url": j.source_url,
                "raw_content": j.raw_content, "recruitment_context": j.recruitment_context,
                "availability_status": j.availability_status, "last_verified_at": j.last_verified_at} for j in jobs if j],
            "leads": [{"url": lead.source_url, "status": lead.status, "job_posting_id": lead.job_posting_id,
                       "failure_code": lead.failure_code, "failure_reason": lead.failure_reason} for lead in leads]}
    (folder / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"report": str(folder / "report.json"), "metrics": report["metrics"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
