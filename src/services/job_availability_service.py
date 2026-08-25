from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.domain.application import CandidateJob
from src.domain.job import (
    JobAvailabilityCheck,
    JobAvailabilityEvidenceType,
    JobAvailabilityStatus,
    JobPosting,
    generate_availability_check_id,
)
from src.services.discovery_sources import looks_like_job_page
from src.services.url_reader import SafeHTTPReader, URLReaderError, parse_html_document

STALE_FAILURE_THRESHOLD = 3
_CLOSED_PATTERNS = (
    r"职位已关闭",
    r"岗位已关闭",
    r"职位已下线",
    r"岗位已下线",
    r"停止招聘",
    r"不再接受(?:申请|投递)",
    r"招聘已结束",
    r"position (?:has been filled|is closed)",
    r"job (?:is )?no longer available",
    r"no longer accepting applications",
    r"applications? (?:are )?closed",
)


class JobAvailabilityNotFoundError(LookupError):
    pass


class InvalidAvailabilityConfirmationError(ValueError):
    pass


class JobAvailabilityService:
    def __init__(self, session: Session) -> None:
        self.session = session

    async def check_url(
        self,
        *,
        user_id: str,
        job_posting_id: str,
        reader: SafeHTTPReader,
    ) -> JobAvailabilityCheck:
        posting = self._owned_posting(
            user_id=user_id,
            job_posting_id=job_posting_id,
        )
        if not posting.source_url:
            return self._record_read_failure(
                user_id=user_id,
                posting=posting,
                code="availability_url_missing",
                reason="岗位没有可重新读取的来源 URL",
            )
        try:
            response = await reader.fetch(posting.source_url)
        except URLReaderError as error:
            return self._record_read_failure(
                user_id=user_id,
                posting=posting,
                code=error.code,
                reason=str(error),
            )

        raw_html = response.body.decode("utf-8", errors="replace")
        document = parse_html_document(raw_html)
        closed_evidence = explicit_closed_evidence(document.text)
        if closed_evidence:
            return self._record_observation(
                user_id=user_id,
                posting=posting,
                result_status=JobAvailabilityStatus.CLOSED,
                evidence_type=JobAvailabilityEvidenceType.EXPLICIT_CLOSED,
                source_url=response.final_url,
                content_hash=hashlib.sha256(response.body).hexdigest(),
                evidence={"source_text": closed_evidence},
            )
        if looks_like_job_page(document, url=response.final_url):
            posting.availability_failure_count = 0
            posting.last_seen_at = datetime.now(UTC)
            return self._record_observation(
                user_id=user_id,
                posting=posting,
                result_status=JobAvailabilityStatus.ACTIVE,
                evidence_type=JobAvailabilityEvidenceType.PAGE_CONTENT,
                source_url=response.final_url,
                content_hash=hashlib.sha256(response.body).hexdigest(),
                evidence={
                    "title": document.title,
                    "concrete_job_page": True,
                },
            )
        return self._record_read_failure(
            user_id=user_id,
            posting=posting,
            code="availability_page_unrecognized",
            reason="页面可读取，但既没有具体岗位证据，也没有明确关闭证据",
            source_url=response.final_url,
        )

    def confirm(
        self,
        *,
        user_id: str,
        job_posting_id: str,
        status: JobAvailabilityStatus,
        reason: str,
    ) -> JobAvailabilityCheck:
        if status not in {
            JobAvailabilityStatus.ACTIVE,
            JobAvailabilityStatus.CLOSED,
        }:
            raise InvalidAvailabilityConfirmationError(
                "人工确认只允许 ACTIVE 或 CLOSED"
            )
        cleaned_reason = " ".join(reason.split()).strip()
        if len(cleaned_reason) < 4:
            raise InvalidAvailabilityConfirmationError("人工确认必须填写具体原因")
        posting = self._owned_posting(
            user_id=user_id,
            job_posting_id=job_posting_id,
        )
        posting.availability_failure_count = 0
        return self._record_observation(
            user_id=user_id,
            posting=posting,
            result_status=status,
            evidence_type=JobAvailabilityEvidenceType.HUMAN_CONFIRMATION,
            source_url=posting.source_url,
            evidence={"reason": cleaned_reason[:1000]},
        )

    def list_checks(
        self,
        *,
        user_id: str,
        job_posting_id: str,
    ) -> list[JobAvailabilityCheck]:
        self._owned_posting(user_id=user_id, job_posting_id=job_posting_id)
        return list(
            self.session.scalars(
                select(JobAvailabilityCheck)
                .where(
                    JobAvailabilityCheck.user_id == user_id,
                    JobAvailabilityCheck.job_posting_id == job_posting_id,
                )
                .order_by(
                    JobAvailabilityCheck.checked_at.desc(),
                    JobAvailabilityCheck.id.desc(),
                )
            ).all()
        )

    def _record_read_failure(
        self,
        *,
        user_id: str,
        posting: JobPosting,
        code: str,
        reason: str,
        source_url: str | None = None,
    ) -> JobAvailabilityCheck:
        posting.availability_failure_count += 1
        if posting.availability_status == JobAvailabilityStatus.CLOSED.value:
            result_status = JobAvailabilityStatus.CLOSED
        elif posting.availability_failure_count >= STALE_FAILURE_THRESHOLD:
            result_status = JobAvailabilityStatus.STALE
        else:
            result_status = JobAvailabilityStatus.UNKNOWN
        return self._record_observation(
            user_id=user_id,
            posting=posting,
            result_status=result_status,
            evidence_type=JobAvailabilityEvidenceType.READ_FAILURE,
            source_url=source_url or posting.source_url,
            failure_code=code,
            failure_reason=reason,
            evidence={"consecutive_failures": posting.availability_failure_count},
        )

    def _record_observation(
        self,
        *,
        user_id: str,
        posting: JobPosting,
        result_status: JobAvailabilityStatus,
        evidence_type: JobAvailabilityEvidenceType,
        source_url: str | None,
        evidence: dict[str, object],
        content_hash: str | None = None,
        failure_code: str | None = None,
        failure_reason: str | None = None,
    ) -> JobAvailabilityCheck:
        checked_at = datetime.now(UTC)
        previous_status = posting.availability_status
        posting.availability_status = result_status.value
        posting.last_availability_checked_at = checked_at
        if result_status is JobAvailabilityStatus.CLOSED:
            posting.closed_at = posting.closed_at or checked_at
        elif result_status is JobAvailabilityStatus.ACTIVE:
            posting.closed_at = None
        check = JobAvailabilityCheck(
            id=generate_availability_check_id(),
            job_posting_id=posting.id,
            user_id=user_id,
            previous_status=previous_status,
            result_status=result_status.value,
            evidence_type=evidence_type.value,
            source_url=source_url,
            content_hash=content_hash,
            failure_code=failure_code,
            failure_reason=(failure_reason or "")[:2000] or None,
            evidence=evidence,
            checked_at=checked_at,
        )
        self.session.add(check)
        self.session.commit()
        self.session.refresh(check)
        return check

    def _owned_posting(self, *, user_id: str, job_posting_id: str) -> JobPosting:
        posting = self.session.scalar(
            select(JobPosting)
            .join(CandidateJob, CandidateJob.job_posting_id == JobPosting.id)
            .where(
                JobPosting.id == job_posting_id,
                CandidateJob.user_id == user_id,
            )
        )
        if posting is None:
            raise JobAvailabilityNotFoundError(job_posting_id)
        return posting


def explicit_closed_evidence(text: str) -> str | None:
    for pattern in _CLOSED_PATTERNS:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(0)
    return None
