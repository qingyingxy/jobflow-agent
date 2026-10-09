"""Present current query filters for saved results and independently retried leads."""

from sqlalchemy import select

from src.domain.discovery import JobLead
from src.domain.job import JobPosting
from src.services.discovery_matching import classify_discovery_job
from src.services.discovery_sources import JobStub
from src.services.job_role_review import load_role_review


def current_run_matches(session, runs):
    if not runs:
        return {}
    by_run = {run.id: run for run in runs}
    results = {
        run.id: {item["job_posting_id"]: item for item in run.result_matches or []}
        for run in runs
    }
    rows = session.execute(
        select(JobLead.discovery_run_id, JobPosting)
        .join(JobPosting, JobPosting.id == JobLead.job_posting_id)
        .where(JobLead.discovery_run_id.in_(by_run), JobLead.user_id == runs[0].user_id)
    ).all()
    for run_id, job in rows:
        stub = JobStub(
            source_id=job.source_id or "saved",
            source_job_id=job.source_job_id or job.id,
            title=job.title,
            company=job.company,
            locations=job.locations or [],
            job_type=job.job_type,
            published_at=job.published_at,
            raw_content=job.raw_content,
            detail_url=job.source_url or "",
        )
        query = by_run[run_id].search_query
        match = classify_discovery_job(
            stub,
            query=query,
            role_review=load_role_review(
                session, user_id=by_run[run_id].user_id, job=stub, query=query
            ),
        ).as_dict(job_posting_id=job.id)
        if job.availability_status == "CLOSED":
            match["filter_status"] = "excluded"
            match["match_tier"] = "expanded"
            match["mismatch_reasons"].append("closed")
            match["checks"].append(
                {
                    "field": "availability",
                    "status": "excluded",
                    "reason": "岗位已关闭",
                    "evidence": [],
                    "source_url": job.source_url,
                }
            )
            match["mismatch_labels"].append("岗位已关闭")
        results[run_id][job.id] = match
    return {run_id: list(items.values()) for run_id, items in results.items()}
