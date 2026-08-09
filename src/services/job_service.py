from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from src.domain.job import JobPosting, RawJobDocument, generate_job_id
from src.services.jd_analysis_service import invalidate_analyses_for_job


class JobImportService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def import_text(
        self,
        *,
        raw_content: str,
        source_url: str | None,
        source_type: str,
        company: str | None,
        title: str | None,
        source_id: str | None = None,
        source_job_id: str | None = None,
        locations: list[str] | None = None,
        job_type: str | None = None,
        published_at: datetime | None = None,
        last_seen_at: datetime | None = None,
    ) -> JobPosting:
        document = RawJobDocument(
            source_url=source_url,
            source_type=source_type,
            raw_content=raw_content,
            source_metadata={
                "company": company,
                "title": title,
                "job_type": job_type,
                "locations": locations or [],
            },
        )
        content_hash = hashlib.sha256(document.raw_content.encode("utf-8")).hexdigest()
        posting = JobPosting(
            id=generate_job_id(),
            source_url=document.source_url,
            source_type=document.source_type,
            source_id=source_id,
            source_job_id=source_job_id,
            company=company,
            title=title,
            locations=locations or [],
            job_type=job_type,
            published_at=published_at,
            last_seen_at=last_seen_at or datetime.now(UTC),
            raw_content=document.raw_content,
            content_hash=content_hash,
            retrieved_at=document.retrieved_at,
            trace_id=document.trace_id,
        )
        self.session.add(posting)
        self.session.commit()
        self.session.refresh(posting)
        return posting

    def get(self, job_id: str) -> JobPosting | None:
        return self.session.get(JobPosting, job_id)

    def invalidate_analyses(self, job_id: str) -> int:
        return invalidate_analyses_for_job(self.session, job_id=job_id)
