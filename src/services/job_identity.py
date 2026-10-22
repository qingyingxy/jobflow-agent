"""Non-destructive identity grouping; applications and audit records stay intact."""

from datetime import UTC, datetime
from types import SimpleNamespace

from sqlalchemy import select

from src.domain.application import CandidateJob
from src.domain.job import JobPosting
from src.services.job_url import canonical_job_url


def posting_identity(job):
    # Never collapse equal titles or identical bodies with distinct job selectors.
    return canonical_job_url(job.source_url) if job.source_url else f"id:{job.id}"


def candidate_groups(session, user_id):
    groups = {}
    for candidate, job in session.execute(select(CandidateJob, JobPosting).join(
        JobPosting, JobPosting.id == CandidateJob.job_posting_id,
    ).where(CandidateJob.user_id == user_id)):
        groups.setdefault(posting_identity(job), []).append((candidate, job))
    return groups


def representative(rows):
    def order(row):
        candidate, job = row
        timestamp = candidate.updated_at or candidate.created_at or datetime(1970, 1, 1, tzinfo=UTC)
        timestamp = timestamp.replace(tzinfo=timestamp.tzinfo or UTC).timestamp()
        # A prior application always wins; otherwise preserve the latest explicit
        # save/ignore action instead of a later automatic discovery.
        return (candidate.status == "CONVERTED", candidate.status != "DISCOVERED",
                timestamp, job.id)
    latest, _ = max(rows, key=order)
    # Keep the displayed ID stable when save/ignore changes. A read-only proxy
    # carries the effective state; GET requests never mutate persisted records.
    def created(row):
        date = row[1].created_at or datetime(1970, 1, 1, tzinfo=UTC)
        return date.replace(tzinfo=date.tzinfo or UTC).timestamp()

    candidate, job = min(rows, key=lambda row: (row[0].status != "CONVERTED", created(row), row[1].id))
    view = SimpleNamespace(id=candidate.id, user_id=candidate.user_id, job_posting_id=job.id,
        status=latest.status, created_at=candidate.created_at, updated_at=latest.updated_at)
    return view, job


def unique_candidates(session, user_id):
    return [representative(rows) for rows in candidate_groups(session, user_id).values()]
