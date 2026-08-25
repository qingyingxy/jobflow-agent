from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from src.domain.job import (
    JobAvailabilityStatus,
    JobPosting,
    JobVerificationStatus,
    RawJobDocument,
    generate_job_id,
)
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
        verification_status: JobVerificationStatus | str | None = None,
        availability_status: JobAvailabilityStatus | str | None = None,
        first_seen_at: datetime | None = None,
        last_verified_at: datetime | None = None,
        commit: bool = True,
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
        now = datetime.now(UTC)
        if verification_status is None:
            verification_status = {
                "company_adapter": JobVerificationStatus.VERIFIED_OFFICIAL,
                "generic_html": JobVerificationStatus.VERIFIED_SOURCE,
                "manual_text": JobVerificationStatus.USER_PROVIDED,
            }.get(source_type, JobVerificationStatus.LEGACY_UNVERIFIED)
        verification_value = JobVerificationStatus(verification_status).value
        if availability_status is None:
            availability_status = (
                JobAvailabilityStatus.ACTIVE
                if verification_value
                in {
                    JobVerificationStatus.VERIFIED_OFFICIAL.value,
                    JobVerificationStatus.VERIFIED_SOURCE.value,
                }
                else JobAvailabilityStatus.UNKNOWN
            )
        availability_value = JobAvailabilityStatus(availability_status).value
        seen_at = last_seen_at or now
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
            verification_status=verification_value,
            availability_status=availability_value,
            first_seen_at=first_seen_at or seen_at,
            last_seen_at=seen_at,
            last_verified_at=last_verified_at,
            raw_content=document.raw_content,
            content_hash=content_hash,
            retrieved_at=document.retrieved_at,
            trace_id=document.trace_id,
        )
        self.session.add(posting)
        if commit:
            self.session.commit()
        else:
            self.session.flush()
        self.session.refresh(posting)
        return posting

    def get(self, job_id: str) -> JobPosting | None:
        return self.session.get(JobPosting, job_id)

    def invalidate_analyses(self, job_id: str) -> int:
        return invalidate_analyses_for_job(self.session, job_id=job_id)
