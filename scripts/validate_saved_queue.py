"""Follow bounded semantic batches on a DB copy, including deferred target jobs."""

import argparse
import asyncio
import json
import os
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def validate(args, folder):
    from src.config import get_settings
    from src.domain.discovery import DiscoveryRun
    from src.domain.search_goal import SearchGoal
    from src.infrastructure.database import SessionLocal
    from src.services import multiround_search, web_search_service
    from src.services.job_lead_service import JobLeadService
    from src.services.job_role_review import load_role_review
    from src.services.search_goal_service import SearchGoalService, posting_stub
    from src.services.source_understanding import pending_review_fields
    from src.services.url_reader import SafeHTTPReader

    settings = get_settings().model_copy(update={
        "web_search_semantic_enabled": True, "web_search_semantic_max_calls": 8,
        "web_search_direct_sources_enabled": False, "company_discovery_enabled": False,
        "web_search_role_review_enabled": False, "web_search_max_rounds": 1,
        "web_search_budget_seconds": 60, "web_search_verification_budget_seconds": 60,
    })
    if settings.structured_model_provider == "fake":
        raise ValueError("A real configured model is required")
    calls = []

    async def forbid_page(*_args, **_kwargs):
        calls.append("unexpected_page_read")
        raise AssertionError("The cached queue trial must not fetch a page")

    class EmptySearch:
        source_id = "controlled-queue-search"

        async def discover(self):
            return []

    def inspect(session, goal):
        goals = SearchGoalService(session)
        rows = {}
        for posting in goals.postings(goal.user_id):
            stub = posting_stub(posting)
            role = load_role_review(session, user_id=goal.user_id, job=stub, query=goal.query)
            fields = pending_review_fields(stub, query=goal.query, conditions=goal.conditions, role_review=role)
            attempt = (posting.recruitment_context or {}).get("source_review_attempt", {})
            rows[posting.id] = {"title": posting.title, "url": posting.source_url, "fields": fields,
                "attempt": attempt, "complete": not fields and not attempt.get("error_code"),
                "cache_available": goals.cached_posting(goal.user_id, posting.source_url) is not None}
        return rows

    batches, initial = [], {}
    start = monotonic()
    with (
        patch.object(multiround_search, "get_settings", lambda: settings),
        patch.object(web_search_service, "create_web_search_provider", lambda *_a, **_k: EmptySearch()),
        patch.object(SearchGoalService, "resume_candidates", lambda *_a, **_k: []),
        patch.object(SafeHTTPReader, "fetch", forbid_page),
        patch.object(JobLeadService, "verify_url", forbid_page),
        patch.object(JobLeadService, "verify_browser", forbid_page),
    ):
        for number in range(1, args.batches + 1):
            with SessionLocal() as session:
                goal = session.get(SearchGoal, args.goal_id)
                if goal is None:
                    raise ValueError("Saved goal not found")
                goals = SearchGoalService(session)
                before = inspect(session, goal)
                if not initial:
                    initial = before
                    if not args.job_id:
                        args.job_id = [k for k, row in before.items() if row["fields"] and row["cache_available"]]
                    if not args.job_id or any(k not in before for k in args.job_id):
                        raise ValueError("Expected target jobs are not present")
                selected = goals.refresh_candidates(goal.user_id, query=goal.query, conditions=goal.conditions)
                run = DiscoveryRun(id=f"{folder.name}-{number}", user_id=goal.user_id,
                    source="web_search", source_url="https://example.com/controlled-queue-search",
                    search_query=goal.query, search_goal_id=goal.id, search_goal_version=goal.version,
                    goal_conditions=goal.conditions, library_baseline=goals.snapshot(goal.user_id, goal.query),
                    started_at=datetime.now(UTC), status="RUNNING")
                session.add(run)
                session.commit()
                run_id, user_id, query = run.id, goal.user_id, goal.query
            await multiround_search.execute_multiround_search(run_id=run_id, user_id=user_id,
                query=query, company_ids=[], analysis_limit=0)
            with SessionLocal() as session:
                goal = session.get(SearchGoal, args.goal_id)
                after = inspect(session, goal)
                run = session.get(DiscoveryRun, run_id)
                processed = [k for k in after if after[k]["attempt"] != before[k]["attempt"]]
                batch = {"number": number, "run_id": run_id, "selected": [c.source_url for c in selected],
                    "processed": [{"job_id": k, **after[k]} for k in processed],
                    "remaining_targets": [k for k in args.job_id if not after[k]["complete"]],
                    "metrics": run.usage_metrics, "matches": run.result_matches, "trace": run.agent_trace}
                batches.append(batch)
                print(json.dumps({"batch": number, "selected": len(selected), "processed": len(processed),
                    "remaining_targets": [after[k]["title"] for k in batch["remaining_targets"]]}, ensure_ascii=False), flush=True)
                if not batch["remaining_targets"] or not processed:
                    break
    with SessionLocal() as session:
        goal = session.get(SearchGoal, args.goal_id)
        matches = {r["job_posting_id"]: r for r in SearchGoalService(session).library(goal.user_id, goal.id)["result_matches"]}
    results = [{"job_id": k, "before": initial[k], "after": after[k], "match": matches[k]} for k in args.job_id]
    report = {"mode": "real_model_multiple_cached_batches", "input_database": str(args.database),
        "query": query, "page_attempts": len(calls), "elapsed_seconds": round(monotonic() - start, 2),
        "targets": results, "batches": batches,
        "checks": {"no_page_reads": not calls, "all_targets_processed": all(r["after"]["complete"] for r in results)},
        "limitations": ["数据库副本上的真实模型多批次续查；网络发现与页面读取隔离。",
            "字段理解完成包含明确不符、原文缺失和歧义，不等于所有岗位推荐。"]}
    path = folder / "report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"report": str(path), "checks": report["checks"]}, ensure_ascii=False), flush=True)
    return all(report["checks"].values())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--goal-id", default="goal_510142e137774f3ea1f7")
    parser.add_argument("--batches", type=int, choices=range(1, 6), default=4)
    parser.add_argument("--job-id", action="append", default=[])
    args = parser.parse_args()
    args.database = args.database.resolve(strict=True)
    folder = ROOT / "artifacts" / ("queue-resume-" + datetime.now(UTC).strftime("%Y%m%d-%H%M%S"))
    folder.mkdir()
    with sqlite3.connect(args.database.as_uri() + "?mode=ro", uri=True) as source, sqlite3.connect(folder / "trial.db") as target:
        source.backup(target)
    os.environ["DATABASE_URL"] = "sqlite:///" + (folder / "trial.db").as_posix()
    sys.exit(0 if asyncio.run(validate(args, folder)) else 1)
