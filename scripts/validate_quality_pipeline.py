"""Replay the real acceptance bodies through the production background queue."""
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
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--resume", action="store_true")
parser.add_argument("--cohort", type=Path, default=ROOT / "artifacts/job-acceptance-20261019")
parser.add_argument("--output", type=Path, default=ROOT / "artifacts/quality-pipeline-20261019")
args = parser.parse_args()
BASE, OUT = args.cohort.resolve(), args.output.resolve()
if not OUT.is_relative_to(ROOT / "artifacts"):
    parser.error("Validation writes must stay in artifacts/")
OUT.mkdir(exist_ok=True)
if not args.resume:
    if (OUT / "trial.db").exists():
        raise SystemExit("Use --resume for an existing trial")
    with sqlite3.connect(BASE / "trial.db") as source, sqlite3.connect(OUT / "trial.db") as target:
        source.backup(target)
os.environ["DATABASE_URL"] = "sqlite:///" + (OUT / "trial.db").as_posix()
os.environ["APP_ENV"] = "testing"


async def main():
    from sqlalchemy import select

    from src.config import get_settings
    from src.domain.application import CandidateJob
    from src.domain.company_source import DiscoveredCompany
    from src.domain.discovery import DiscoveryRun, JobLead
    from src.domain.job import JobPosting
    from src.domain.search_goal import SearchGoal, SearchGoalConditions
    from src.infrastructure.database import SessionLocal
    from src.services.body_review_queue import (
        enqueue_body_review,
        review_queue_summary,
        run_body_review_batch,
    )
    from src.services.discovery_matching import classify_discovery_job
    from src.services.personal_requirements import personal_requirement_hints
    from src.services.search_goal_service import SearchGoalService, posting_stub
    from src.services.source_understanding import VERSION

    data = json.loads((BASE / "results.json").read_text(encoding="utf-8"))
    user = "recovered-candidate-acceptance"
    with SessionLocal() as session:
        if not args.resume:
            # Original acceptance used local-user's verified registry while
            # isolating job records under a test user. Preserve the same verified
            # company evidence under that test user for background ownership checks.
            existing_hosts = set(session.scalars(select(DiscoveredCompany.homepage_host).where(DiscoveredCompany.user_id == user)))
            for company in session.scalars(select(DiscoveredCompany).where(DiscoveredCompany.user_id == "local-user")):
                if company.homepage_host not in existing_hosts:
                    values = {c.name: getattr(company, c.name) for c in DiscoveredCompany.__table__.columns if c.name not in {"id", "user_id"}}
                    session.add(DiscoveredCompany(user_id=user, **values))
            goal = SearchGoalService(session).save(user_id=user, input_text=data["query"],
                conditions=SearchGoalConditions.model_validate(data["conditions"]), condition_sources={})
            run = DiscoveryRun(id="quality-pipeline", user_id=user, source="saved-body-validation",
                source_url="https://example.com", started_at=datetime.now(UTC),
                search_goal_id=goal.id, search_goal_version=goal.version)
            session.add(run)
            for row in data["results"]:
                session.get(JobLead, row["lead_id"]).discovery_run_id = run.id
            selected = {session.get(JobLead, row["lead_id"]).job_posting_id for row in data["results"]}
            for candidate in session.scalars(select(CandidateJob).where(CandidateJob.user_id == user)):
                if candidate.job_posting_id not in selected:
                    candidate.status = "IGNORED"  # Scope only this isolated acceptance copy.
            session.commit()
            enqueue_body_review(session, goal)
        goal = session.scalar(select(SearchGoal).where(SearchGoal.user_id == user))
        goal_id = goal.id
        if args.resume and review_queue_summary(session, goal)["waiting"]:
            enqueue_body_review(session, goal)

    def report():
        with SessionLocal() as session:
            goal = session.get(SearchGoal, goal_id)
            summary = review_queue_summary(session, goal)
            rows = []
            for original in data["results"]:
                lead = session.get(JobLead, original["lead_id"])
                job = session.get(JobPosting, lead.job_posting_id) if lead.job_posting_id else None
                row = {"index": original["index"], "url": original["url"], "title": original["title"],
                    "lead_status": lead.status, "failure_code": lead.failure_code}
                if job:
                    row.update(title=job.title, match=classify_discovery_job(posting_stub(job), query=goal.query,
                        conditions=goal.conditions, primary=True).as_dict(job_posting_id=job.id),
                        personal_requirements=personal_requirement_hints(job, None), context=job.recruitment_context)
                rows.append(row)
            (OUT / "results.json").write_text(json.dumps({"version": VERSION, "at": datetime.now(UTC).isoformat(),
                "summary": summary, "results": rows, "detail_refetches": 0}, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            print(json.dumps(summary, ensure_ascii=False), flush=True)
            return summary

    report()
    for _ in range(10):
        if not await run_body_review_batch(SessionLocal, settings=get_settings(), goal_id=goal_id):
            break
        if not report()["waiting"]:
            break


if __name__ == "__main__":
    asyncio.run(main())
