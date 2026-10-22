"""Present current query filters for saved results and independently retried leads."""

from sqlalchemy import select

from src.domain.application import CandidateJob
from src.domain.discovery import JobLead
from src.domain.job import JobPosting
from src.services.discovery_matching import (
    apply_posting_availability,
    classify_discovery_job,
)
from src.services.discovery_sources import JobStub
from src.services.job_role_review import load_role_review


def current_run_matches(session, runs):
    if not runs:
        return {}
    from src.domain.models import UserProfile
    from src.services.job_identity import candidate_groups, representative
    from src.services.result_status import enrich_result

    aliases = {}
    for group in candidate_groups(session, runs[0].user_id).values():
        canonical = representative(group)[1]
        aliases.update({job.id: canonical for _, job in group})
    profile = session.get(UserProfile, runs[0].user_id)
    by_run = {run.id: run for run in runs}
    results = {
        run.id: {item["job_posting_id"]: item for item in run.result_matches or []}
        for run in runs
    }
    from src.services.source_understanding import ai_policy_enabled

    primary = ai_policy_enabled()
    if primary:
        # Saved JSON is an audit snapshot, never a current AI eligibility result.
        results = {run.id: {} for run in runs}
    rows = session.execute(
        select(JobLead.discovery_run_id, JobPosting)
        .join(JobPosting, JobPosting.id == JobLead.job_posting_id)
        .where(JobLead.discovery_run_id.in_(by_run), JobLead.user_id == runs[0].user_id)
    ).all()
    if primary:
        linked = {(run_id, job.id) for run_id, job in rows}
        ids = {item["job_posting_id"] for run in runs for item in run.result_matches or []}
        owned = session.scalars(select(JobPosting).join(CandidateJob, CandidateJob.job_posting_id == JobPosting.id)
            .where(CandidateJob.user_id == runs[0].user_id, JobPosting.id.in_(ids))).all()
        for run in runs:
            run_ids = {item["job_posting_id"] for item in run.result_matches or []}
            rows.extend((run.id, job) for job in owned if job.id in run_ids and (run.id, job.id) not in linked)
    for run_id, job in rows:
        job = aliases.get(job.id, job)
        stub = JobStub(
            source_id=job.source_id or "saved",
            source_job_id=job.source_job_id or job.id,
            title=job.title,
            company=job.company,
            locations=job.locations or [],
            job_type=job.job_type,
            published_at=job.published_at,
            raw_content=job.raw_content,
            recruitment_context=job.recruitment_context or {},
            detail_url=job.source_url or "",
        )
        query = by_run[run_id].search_query
        match = classify_discovery_job(
            stub,
            query=query,
            conditions=by_run[run_id].goal_conditions,
            role_review=None if primary else load_role_review(
                session, user_id=by_run[run_id].user_id, job=stub, query=query
            ),
        )
        match = apply_posting_availability(match, job).as_dict(job_posting_id=job.id)
        from src.services.discovery_matching import search_filter_conditions

        match = enrich_result(match, job, profile,
                              conditions=by_run[run_id].goal_conditions or search_filter_conditions(query))
        results[run_id][job.id] = match
    deduped = {}
    for run_id, items in results.items():
        current = {}
        for job_id, match in items.items():
            canonical_id = aliases[job_id].id if job_id in aliases else job_id
            current.setdefault(canonical_id, items.get(canonical_id, {**match, "job_posting_id": canonical_id}))
        deduped[run_id] = list(current.values())
    return deduped
