"""Re-read selected failed official leads on an isolated database copy."""

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


async def validate(args, folder):
    from src.config import get_settings
    from src.domain.search_goal import SearchGoal
    from src.infrastructure.database import SessionLocal
    from src.services.browser_job_reader import PlaywrightBrowserJobReader
    from src.services.company_registry import enabled_company_source_hosts
    from src.services.discovery_matching import (
        apply_posting_availability,
        classify_discovery_job,
    )
    from src.services.job_lead_service import JobLeadService, LeadVerificationFailure
    from src.services.lead_retry import can_retry, parser_retry_state
    from src.services.search_goal_service import posting_stub
    from src.services.source_understanding import SourceUnderstanding

    events, results = [], []
    runtime = SourceUnderstanding(get_settings(), on_event=lambda kind, value: events.append({"kind": kind, **value}))
    with SessionLocal() as session:
        goal = session.get(SearchGoal, args.goal_id)
        if goal is None:
            raise ValueError("Saved goal not found")
        service = JobLeadService(session, understanding=runtime)
        browser = PlaywrightBrowserJobReader(timeout_seconds=20)
        hosts = enabled_company_source_hosts(session=session, user_id=goal.user_id)
        for lead_id in args.lead_id:
            lead = service.get_lead(user_id=goal.user_id, lead_id=lead_id)
            prior = {"status": lead.status, "failure_code": lead.failure_code, "retry_state": lead.retry_state}
            retry = parser_retry_state(session, lead)
            row = {"lead_id": lead_id, "url": lead.source_url, "before": prior,
                   "automatic_retry_eligible": can_retry(retry), "retry_after_upgrade": retry}
            try:
                result = await service.verify_browser(user_id=goal.user_id, lead_id=lead_id,
                    reader=browser, official_hosts=hosts, official_only=True)
                posting = result.posting
                stub = await runtime.review(posting_stub(posting), query=goal.query, conditions=goal.conditions)
                posting.recruitment_context = stub.recruitment_context
                session.commit()
                match = apply_posting_availability(classify_discovery_job(stub, query=goal.query, conditions=goal.conditions), posting)
                row.update(success=True, job_id=posting.id, title=posting.title,
                    raw_content=posting.raw_content, match=match.as_dict(job_posting_id=posting.id),
                    last_verified_at=posting.last_verified_at, status=lead.status)
            except LeadVerificationFailure as error:
                row.update(success=False, failure_code=error.code, reason=str(error))
            results.append(row)
            print(json.dumps({k: v for k, v in row.items() if k in {"url", "title", "success", "failure_code", "automatic_retry_eligible"}}, ensure_ascii=False), flush=True)
    report = {"mode": "live_failed_official_page_recovery", "query": goal.query,
        "results": results, "events": events, "model_calls": runtime.calls,
        "checks": {"both_pages_recovered": all(r["success"] for r in results),
                   "eligible_after_parser_upgrade": all(r["automatic_retry_eligible"] for r in results)},
        "limitations": ["真实重读已知失败官网页面，仅修改数据库副本。", "恢复可读不代表符合城市、届别或招聘类型。"]}
    path = folder / "report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"report": str(path), "checks": report["checks"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--goal-id", default="goal_510142e137774f3ea1f7")
    parser.add_argument("--lead-id", action="append", required=True)
    args = parser.parse_args()
    folder = ROOT / "artifacts" / ("detail-recovery-" + datetime.now(UTC).strftime("%Y%m%d-%H%M%S"))
    folder.mkdir()
    with sqlite3.connect(args.database.resolve().as_uri() + "?mode=ro", uri=True) as source, sqlite3.connect(folder / "trial.db") as target:
        source.backup(target)
    os.environ["DATABASE_URL"] = "sqlite:///" + (folder / "trial.db").as_posix()
    asyncio.run(validate(args, folder))
