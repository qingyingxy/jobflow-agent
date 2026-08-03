from __future__ import annotations

import hashlib

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
    ) -> JobPosting:
        document = RawJobDocument(
            source_url=source_url,
            source_type=source_type,
            raw_content=raw_content,
        )
        content_hash = hashlib.sha256(document.raw_content.encode("utf-8")).hexdigest()
        posting = JobPosting(
            id=generate_job_id(),
            source_url=document.source_url,
            source_type=document.source_type,
            company=company,
            title=title,
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
