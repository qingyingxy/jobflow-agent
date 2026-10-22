"""Opt-in real-model continuation on a DB copy; no recruiting pages are fetched."""

import argparse
import asyncio
import json
import os
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def main(args, folder):
    from src.config import get_settings
    from src.domain.search_goal import SearchGoal
    from src.infrastructure.database import SessionLocal
    from src.services.discovery_matching import classify_discovery_job
    from src.services.job_role_review import load_role_review
    from src.services.search_goal_service import SearchGoalService, posting_stub
    from src.services.source_understanding import (
        SourceUnderstanding,
        pending_review_fields,
    )

    events = []
    settings = get_settings().model_copy(update={"web_search_semantic_max_calls": args.limit})
    runtime = SourceUnderstanding(settings, on_event=lambda kind, details: events.append({"kind": kind, **details}))
    started = monotonic()
    with SessionLocal() as session:
        goal = session.get(SearchGoal, args.goal_id)
        if goal is None:
            raise ValueError("Goal is not present in the supplied database")
        goals = SearchGoalService(session)
        candidates = goals.refresh_candidates(goal.user_id, query=goal.query, conditions=goal.conditions, limit=32)
        records = []
        for candidate in candidates:
            posting = goals.cached_posting(goal.user_id, candidate.source_url)
            if not posting:
                continue
            stub = posting_stub(posting)
            role = load_role_review(session, user_id=goal.user_id, job=stub, query=goal.query)
            needed = pending_review_fields(stub, query=goal.query, conditions=goal.conditions, role_review=role)
            if needed:
                records.append((posting, stub, role, needed, posting.last_verified_at, posting.availability_status))
            if len(records) >= args.limit:
                break
        outputs = await asyncio.gather(*(runtime.review(stub, query=goal.query,
            conditions=goal.conditions, role_review=role) for _, stub, role, *_ in records))
        results = []
        for (posting, stub, role, needed, verified_at, availability), output in zip(records, outputs, strict=True):
            before = classify_discovery_job(stub, query=goal.query, conditions=goal.conditions, role_review=role)
            after = classify_discovery_job(output, query=goal.query, conditions=goal.conditions, role_review=role)
            posting.recruitment_context = output.recruitment_context
            assert posting.last_verified_at == verified_at and posting.availability_status == availability
            results.append({"job_id": posting.id, "url": posting.source_url, "title": posting.title,
                "fields_requested": needed, "before": before.checks, "after": after.checks,
                "eligible_fields_next_update": pending_review_fields(output, query=goal.query,
                    conditions=goal.conditions, role_review=role),
                "semantic_attempt": output.recruitment_context.get("source_review_attempt", {}),
                "availability": availability, "verified_at": verified_at.isoformat() if verified_at else None})
        session.commit()
    resolved = sum(c["status"] != "pending" and c["field"] in r["fields_requested"]
                   for r in results for c in r["after"])
    report = {"mode": "real_model_cached_field_continuation", "input_database": str(args.database),
        "selected_jobs": len(records), "model_calls": runtime.calls,
        "page_reads": 0, "resolved_fields": resolved,
        "elapsed_seconds": round(monotonic() - started, 2), "results": results, "events": events,
        "limitations": ["复用已捕获正文的受控续查；不包含新岗位检索或官网重读。",
                        "字段变化由当前规则和模型产生，未经独立人工标注，不代表准确率。",
                        "仅修改数据库副本；开放状态与原核验时间保持不变。"]}
    path = folder / "report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(path), **{k:report[k] for k in
        ("selected_jobs", "model_calls", "page_reads", "resolved_fields", "elapsed_seconds")}}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--goal-id", default="goal_510142e137774f3ea1f7")
    parser.add_argument("--limit", type=int, choices=range(1, 17), default=8)
    args = parser.parse_args()
    args.database = args.database.resolve(strict=True)
    folder = ROOT / "artifacts" / ("saved-continuation-" + datetime.now(UTC).strftime("%Y%m%d-%H%M%S"))
    folder.mkdir()
    with sqlite3.connect(args.database.as_uri() + "?mode=ro", uri=True) as source, sqlite3.connect(folder / "trial.db") as target:
        source.backup(target)
    os.environ["DATABASE_URL"] = "sqlite:///" + (folder / "trial.db").as_posix()
    asyncio.run(main(args, folder))
