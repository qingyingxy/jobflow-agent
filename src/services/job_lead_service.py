from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from src.domain.application import CandidateStatus
from src.domain.discovery import (
    DiscoveryRun,
    JobLead,
    JobLeadStatus,
    LeadProvider,
    LeadVerification,
    generate_job_lead_id,
    generate_lead_verification_id,
)
from src.domain.job import (
    JobAvailabilityStatus,
    JobPosting,
    JobVerificationStatus,
    normalize_job_text,
)
from src.services.application_service import ApplicationService
from src.services.browser_job_reader import BrowserJobReader, BrowserReadError
from src.services.discovery_sources import (
    JobStub,
    looks_like_dynamic_shell,
    looks_like_job_page,
)
from src.services.jd_analysis_service import invalidate_analyses_for_job
from src.services.job_fact_verifier import verified_stub_evidence, verify_page_facts
from src.services.job_service import JobImportService
from src.services.lead_providers import (
    LeadCandidate,
    ManualImportProvider,
)
from src.services.lead_providers import (
    LeadProvider as LeadProviderContract,
)
from src.services.url_reader import SafeHTTPReader, URLReaderError, parse_html_document


class JobLeadNotFoundError(LookupError):
    pass


class JobLeadStateError(RuntimeError):
    pass


class LeadVerificationFailure(RuntimeError):
    def __init__(self, *, code: str, message: str, lead_id: str) -> None:
        super().__init__(message)
        self.code = code
        self.lead_id = lead_id


@dataclass(frozen=True)
class VerifiedLeadResult:
    lead: JobLead
    posting: JobPosting
    posting_created: bool


class JobLeadService:
    """Own the boundary between untrusted discovery leads and formal jobs."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create_lead(
        self,
        *,
        user_id: str,
        provider: LeadProvider,
        source_url: str,
        discovery_run_id: str | None = None,
        source_id: str | None = None,
        source_job_id: str | None = None,
        company_hint: str | None = None,
        title_hint: str | None = None,
        search_snippet: str | None = None,
        discovered_at: datetime | None = None,
    ) -> JobLead:
        normalized_url = normalize_lead_url(source_url)
        if discovery_run_id is not None:
            run = self.session.get(DiscoveryRun, discovery_run_id)
            if run is None or run.user_id != user_id:
                raise ValueError("发现运行不存在或不属于当前用户")

        statement = select(JobLead).where(
            JobLead.user_id == user_id,
            JobLead.provider == provider.value,
        )
        if discovery_run_id is not None and source_id and source_job_id:
            statement = statement.where(
                JobLead.discovery_run_id == discovery_run_id,
                JobLead.source_id == source_id,
                JobLead.source_job_id == source_job_id,
            )
        elif discovery_run_id is not None:
            statement = statement.where(
                JobLead.discovery_run_id == discovery_run_id,
                JobLead.normalized_url == normalized_url,
            )
        else:
            statement = statement.where(
                JobLead.discovery_run_id.is_(None),
                JobLead.normalized_url == normalized_url,
            )
        existing = self.session.scalar(statement.limit(1))
        if existing is not None:
            return existing

        lead = JobLead(
            id=generate_job_lead_id(),
            discovery_run_id=discovery_run_id,
            user_id=user_id,
            provider=provider.value,
            source_id=source_id,
            source_job_id=source_job_id,
            source_url=source_url,
            normalized_url=normalized_url,
            company_hint=_clean_hint(company_hint),
            title_hint=_clean_hint(title_hint),
            search_snippet=_clean_snippet(search_snippet),
            status=JobLeadStatus.NEW.value,
            discovered_at=_normalize_discovered_at(discovered_at),
        )
        self.session.add(lead)
        self.session.commit()
        self.session.refresh(lead)
        return lead

    async def ingest_provider(
        self,
        *,
        user_id: str,
        provider: LeadProviderContract,
        discovery_run_id: str | None = None,
    ) -> list[JobLead]:
        """Persist provider output as leads without promoting any provider facts."""

        return [
            self.capture_candidate(
                user_id=user_id,
                discovery_run_id=discovery_run_id,
                candidate=candidate,
            )
            for candidate in await provider.discover()
        ]

    def capture_candidate(
        self,
        *,
        user_id: str,
        candidate: LeadCandidate,
        discovery_run_id: str | None = None,
    ) -> JobLead:
        return self.create_lead(
            user_id=user_id,
            provider=candidate.provider,
            source_url=candidate.source_url,
            discovery_run_id=discovery_run_id,
            source_id=candidate.source_id,
            source_job_id=candidate.source_job_id,
            company_hint=candidate.company_hint,
            title_hint=candidate.title_hint,
            search_snippet=candidate.search_snippet,
            discovered_at=candidate.discovered_at,
        )

    def capture_stub(
        self,
        *,
        user_id: str,
        discovery_run_id: str,
        stub: JobStub,
    ) -> JobLead:
        return self.create_lead(
            user_id=user_id,
            provider=LeadProvider.OFFICIAL_ADAPTER,
            discovery_run_id=discovery_run_id,
            source_id=stub.source_id,
            source_job_id=stub.source_job_id,
            source_url=stub.detail_url,
            company_hint=stub.company,
            title_hint=stub.title,
        )

    def list_leads(
        self,
        *,
        user_id: str,
        status: JobLeadStatus | None = None,
    ) -> list[JobLead]:
        statement = (
            select(JobLead)
            .where(JobLead.user_id == user_id)
            .order_by(JobLead.created_at.desc(), JobLead.id.desc())
        )
        if status is not None:
            statement = statement.where(JobLead.status == status.value)
        return list(self.session.scalars(statement).all())

    def get_lead(self, *, user_id: str, lead_id: str) -> JobLead:
        lead = self.session.scalar(
            select(JobLead).where(
                JobLead.id == lead_id,
                JobLead.user_id == user_id,
            )
        )
        if lead is None:
            raise JobLeadNotFoundError(lead_id)
        return lead

    def list_verifications(
        self,
        *,
        user_id: str,
        lead_id: str,
    ) -> list[LeadVerification]:
        self.get_lead(user_id=user_id, lead_id=lead_id)
        return list(
            self.session.scalars(
                select(LeadVerification)
                .where(
                    LeadVerification.lead_id == lead_id,
                    LeadVerification.user_id == user_id,
                )
                .order_by(
                    LeadVerification.checked_at.desc(),
                    LeadVerification.id.desc(),
                )
            ).all()
        )

    def verify_stub(
        self,
        *,
        user_id: str,
        lead_id: str,
        stub: JobStub,
        verification_status: JobVerificationStatus = (
            JobVerificationStatus.VERIFIED_OFFICIAL
        ),
        source_type: str = "company_adapter",
        availability_status: JobAvailabilityStatus = JobAvailabilityStatus.ACTIVE,
        verification_started: bool = False,
        field_evidence: dict[str, object] | None = None,
    ) -> VerifiedLeadResult:
        if verification_started:
            lead = self.get_lead(user_id=user_id, lead_id=lead_id)
            if lead.status != JobLeadStatus.VERIFYING.value:
                raise JobLeadStateError("岗位线索没有处于验证中状态")
        else:
            existing = self._existing_verified_result(
                user_id=user_id,
                lead_id=lead_id,
            )
            if existing is not None:
                return existing
            lead = self._start_verification(user_id=user_id, lead_id=lead_id)
        try:
            posting, created = self._upsert_posting(
                stub,
                source_type=source_type,
                verification_status=verification_status,
                availability_status=availability_status,
            )
            checked_at = datetime.now(UTC)
            lead = self.get_lead(user_id=user_id, lead_id=lead.id)
            lead.status = (
                JobLeadStatus.VERIFIED.value
                if created
                else JobLeadStatus.DUPLICATE.value
            )
            lead.job_posting_id = posting.id
            lead.verified_at = checked_at
            lead.failure_code = None
            lead.failure_reason = None
            if field_evidence is None:
                metadata_kind = (
                    "official_payload"
                    if verification_status
                    in {
                        JobVerificationStatus.VERIFIED_OFFICIAL,
                        JobVerificationStatus.VERIFIED_SOURCE,
                    }
                    else "user_input"
                )
                field_evidence = verified_stub_evidence(
                    raw_content=stub.raw_content,
                    company=stub.company,
                    title=stub.title,
                    locations=stub.locations,
                    job_type=stub.job_type,
                    metadata_kind=metadata_kind,
                )
            self.session.add(
                LeadVerification(
                    id=generate_lead_verification_id(),
                    lead_id=lead.id,
                    user_id=user_id,
                    result=JobLeadStatus.VERIFIED.value,
                    source_url=posting.source_url or lead.normalized_url,
                    source_type=source_type,
                    content_hash=posting.content_hash,
                    field_evidence={
                        **field_evidence,
                        "verification_status": posting.verification_status,
                    },
                    checked_at=checked_at,
                )
            )
            ApplicationService(self.session).create_candidate(
                user_id=user_id,
                job_posting_id=posting.id,
                initial_status=CandidateStatus.DISCOVERED,
                commit=False,
            )
            self.session.commit()
            self.session.refresh(lead)
        except Exception as error:
            self.session.rollback()
            self._record_failure(
                user_id=user_id,
                lead_id=lead.id,
                status=JobLeadStatus.FAILED,
                code=getattr(error, "code", "lead_verification_failed"),
                reason=str(error),
            )
            raise

        return VerifiedLeadResult(
            lead=lead,
            posting=posting,
            posting_created=created,
        )

    async def verify_url(
        self,
        *,
        user_id: str,
        lead_id: str,
        reader: SafeHTTPReader,
        official_hosts: set[str],
    ) -> VerifiedLeadResult:
        existing = self._existing_verified_result(user_id=user_id, lead_id=lead_id)
        if existing is not None:
            return existing
        lead = self._start_verification(user_id=user_id, lead_id=lead_id)
        try:
            response = await reader.fetch(lead.normalized_url)
        except URLReaderError as error:
            self._record_failure(
                user_id=user_id,
                lead_id=lead.id,
                status=JobLeadStatus.FAILED,
                code=error.code,
                reason=str(error),
            )
            raise LeadVerificationFailure(
                code=error.code,
                message=str(error),
                lead_id=lead.id,
            ) from error

        raw_html = response.body.decode("utf-8", errors="replace")
        document = parse_html_document(raw_html)
        if not looks_like_job_page(document, url=response.final_url):
            if looks_like_dynamic_shell(raw_html):
                lead_status = JobLeadStatus.NEEDS_BROWSER
                code = "lead_requires_browser"
                message = "页面依赖 JavaScript，静态读取无法验证具体岗位"
            else:
                lead_status = JobLeadStatus.REJECTED_NON_JOB
                code = "lead_not_job_page"
                message = "页面不是可验证的具体岗位详情页"
            self._record_failure(
                user_id=user_id,
                lead_id=lead.id,
                status=lead_status,
                code=code,
                reason=message,
                source_url=response.final_url,
            )
            raise LeadVerificationFailure(
                code=code,
                message=message,
                lead_id=lead.id,
            )

        final_url = normalize_lead_url(response.final_url)
        host = (urlsplit(final_url).hostname or "").rstrip(".").casefold()
        verification_status = (
            JobVerificationStatus.VERIFIED_OFFICIAL
            if host in official_hosts
            else JobVerificationStatus.VERIFIED_SOURCE
        )
        source_id = lead.source_id or f"{lead.provider}:{host}"
        source_job_id = lead.source_job_id or hashlib.sha256(
            final_url.encode("utf-8")
        ).hexdigest()[:24]
        facts = verify_page_facts(document)
        stub = JobStub(
            source_id=source_id,
            source_job_id=source_job_id,
            company=facts.company,
            title=facts.title,
            locations=facts.locations,
            job_type=facts.job_type,
            published_at=document.published_at,
            detail_url=final_url,
            raw_content=document.text,
        )
        return self.verify_stub(
            user_id=user_id,
            lead_id=lead.id,
            stub=stub,
            verification_status=verification_status,
            source_type="verified_html",
            verification_started=True,
            field_evidence=facts.evidence,
        )

    async def verify_browser(
        self,
        *,
        user_id: str,
        lead_id: str,
        reader: BrowserJobReader,
        official_hosts: set[str],
    ) -> VerifiedLeadResult:
        existing = self._existing_verified_result(user_id=user_id, lead_id=lead_id)
        if existing is not None:
            return existing
        lead = self._start_verification(user_id=user_id, lead_id=lead_id)
        try:
            snapshot = await reader.read(lead.normalized_url)
        except BrowserReadError as error:
            needs_user_codes = {
                "browser_login_required",
                "browser_captcha_required",
                "browser_2fa_required",
                "browser_security_challenge",
            }
            lead_status = (
                JobLeadStatus.NEEDS_USER
                if error.code in needs_user_codes
                else JobLeadStatus.FAILED
            )
            self._record_failure(
                user_id=user_id,
                lead_id=lead.id,
                status=lead_status,
                code=error.code,
                reason=str(error),
            )
            raise LeadVerificationFailure(
                code=error.code,
                message=str(error),
                lead_id=lead.id,
            ) from error

        document = parse_html_document(snapshot.raw_html)
        if not looks_like_job_page(document, url=snapshot.final_url):
            message = "浏览器已读取页面，但仍无法确认这是具体岗位详情页"
            self._record_failure(
                user_id=user_id,
                lead_id=lead.id,
                status=JobLeadStatus.NEEDS_USER,
                code="browser_job_page_unverified",
                reason=message,
                source_url=snapshot.final_url,
            )
            raise LeadVerificationFailure(
                code="browser_job_page_unverified",
                message=message,
                lead_id=lead.id,
            )

        final_url = normalize_lead_url(snapshot.final_url)
        host = (urlsplit(final_url).hostname or "").rstrip(".").casefold()
        verification_status = (
            JobVerificationStatus.VERIFIED_OFFICIAL
            if host in official_hosts
            else JobVerificationStatus.VERIFIED_SOURCE
        )
        facts = verify_page_facts(document)
        stub = JobStub(
            source_id=lead.source_id or f"{lead.provider}:{host}",
            source_job_id=lead.source_job_id
            or hashlib.sha256(final_url.encode("utf-8")).hexdigest()[:24],
            company=facts.company,
            title=facts.title,
            locations=facts.locations,
            job_type=facts.job_type,
            published_at=document.published_at,
            detail_url=final_url,
            raw_content=document.text or snapshot.visible_text,
        )
        return self.verify_stub(
            user_id=user_id,
            lead_id=lead.id,
            stub=stub,
            verification_status=verification_status,
            source_type="verified_browser",
            verification_started=True,
            field_evidence={
                **facts.evidence,
                "browser": {
                    "mode": "read_only",
                    "final_url": final_url,
                    "page_title": snapshot.title,
                },
            },
        )

    def complete_manual_handoff(
        self,
        *,
        user_id: str,
        lead_id: str,
        raw_content: str,
        company: str | None = None,
        title: str | None = None,
        locations: list[str] | None = None,
        job_type: str | None = None,
    ) -> VerifiedLeadResult:
        existing = self._existing_verified_result(user_id=user_id, lead_id=lead_id)
        if existing is not None:
            return existing
        lead = self.get_lead(user_id=user_id, lead_id=lead_id)
        host = (urlsplit(lead.normalized_url).hostname or "unknown").casefold()
        source_id = lead.source_id or f"user_handoff:{host}"
        source_job_id = lead.source_job_id or hashlib.sha256(
            lead.normalized_url.encode("utf-8")
        ).hexdigest()[:24]
        stub = ManualImportProvider.build_handoff_stub(
            source_id=source_id,
            source_job_id=source_job_id,
            source_url=lead.normalized_url,
            raw_content=raw_content,
            company=company or lead.company_hint,
            title=title or lead.title_hint,
            locations=locations or [],
            job_type=job_type,
        )
        return self.verify_stub(
            user_id=user_id,
            lead_id=lead.id,
            stub=stub,
            verification_status=JobVerificationStatus.USER_PROVIDED,
            availability_status=JobAvailabilityStatus.UNKNOWN,
            source_type="manual_handoff",
        )

    def _start_verification(self, *, user_id: str, lead_id: str) -> JobLead:
        allowed = {
            JobLeadStatus.NEW.value,
            JobLeadStatus.NEEDS_BROWSER.value,
            JobLeadStatus.NEEDS_USER.value,
            JobLeadStatus.REJECTED_NON_JOB.value,
            JobLeadStatus.FAILED.value,
        }
        result = self.session.execute(
            update(JobLead)
            .where(
                JobLead.id == lead_id,
                JobLead.user_id == user_id,
                JobLead.status.in_(allowed),
            )
            .values(
                status=JobLeadStatus.VERIFYING.value,
                failure_code=None,
                failure_reason=None,
            )
        )
        if result.rowcount != 1:
            lead = self.get_lead(user_id=user_id, lead_id=lead_id)
            raise JobLeadStateError(f"线索状态 {lead.status} 不允许重新验证")
        self.session.commit()
        lead = self.get_lead(user_id=user_id, lead_id=lead_id)
        self.session.refresh(lead)
        return lead

    def _existing_verified_result(
        self,
        *,
        user_id: str,
        lead_id: str,
    ) -> VerifiedLeadResult | None:
        lead = self.get_lead(user_id=user_id, lead_id=lead_id)
        if lead.status not in {
            JobLeadStatus.VERIFIED.value,
            JobLeadStatus.DUPLICATE.value,
        } or not lead.job_posting_id:
            return None
        posting = self.session.get(JobPosting, lead.job_posting_id)
        if posting is None:
            raise JobLeadStateError("已验证线索关联的岗位不存在")
        return VerifiedLeadResult(
            lead=lead,
            posting=posting,
            posting_created=False,
        )

    def _upsert_posting(
        self,
        stub: JobStub,
        *,
        source_type: str,
        verification_status: JobVerificationStatus,
        availability_status: JobAvailabilityStatus,
    ) -> tuple[JobPosting, bool]:
        normalized_url = normalize_lead_url(stub.detail_url)
        raw_content = normalize_job_text(stub.raw_content)
        content_hash = hashlib.sha256(raw_content.encode("utf-8")).hexdigest()
        now = datetime.now(UTC)

        posting = self.session.scalar(
            select(JobPosting).where(
                JobPosting.source_id == stub.source_id,
                JobPosting.source_job_id == stub.source_job_id,
            )
        )
        if posting is None:
            posting = self.session.scalar(
                select(JobPosting).where(
                    or_(
                        JobPosting.source_url == normalized_url,
                        JobPosting.content_hash == content_hash,
                    )
                )
            )
        if posting is None:
            posting = JobImportService(self.session).import_text(
                raw_content=raw_content,
                source_url=normalized_url,
                source_type=source_type,
                company=stub.company,
                title=stub.title,
                source_id=stub.source_id,
                source_job_id=stub.source_job_id,
                locations=stub.locations,
                job_type=stub.job_type,
                published_at=stub.published_at,
                first_seen_at=now,
                last_seen_at=now,
                last_verified_at=now,
                verification_status=verification_status,
                availability_status=availability_status,
                commit=False,
            )
            return posting, True

        content_changed = posting.content_hash != content_hash
        current_verification = JobVerificationStatus(posting.verification_status)
        incoming_is_stronger = _verification_rank(verification_status) >= _verification_rank(
            current_verification
        )
        if incoming_is_stronger:
            posting.source_url = normalized_url
            posting.source_type = source_type
            posting.source_id = stub.source_id
            posting.source_job_id = stub.source_job_id
            posting.company = stub.company or posting.company
            posting.title = stub.title or posting.title
            posting.locations = stub.locations or posting.locations or []
            posting.job_type = stub.job_type or posting.job_type
            posting.published_at = stub.published_at or posting.published_at
        else:
            posting.source_url = posting.source_url or normalized_url
            posting.company = posting.company or stub.company
            posting.title = posting.title or stub.title
            posting.locations = posting.locations or stub.locations or []
            posting.job_type = posting.job_type or stub.job_type
            posting.published_at = posting.published_at or stub.published_at
        if incoming_is_stronger:
            posting.verification_status = verification_status.value
        if availability_status is not JobAvailabilityStatus.UNKNOWN:
            posting.availability_status = availability_status.value
        posting.first_seen_at = posting.first_seen_at or posting.last_seen_at or now
        posting.last_seen_at = now
        if incoming_is_stronger:
            posting.last_verified_at = now
        if content_changed and incoming_is_stronger:
            posting.raw_content = raw_content
            posting.content_hash = content_hash
            posting.retrieved_at = now
            invalidate_analyses_for_job(self.session, job_id=posting.id)
        self.session.flush()
        self.session.refresh(posting)
        return posting, False

    def _record_failure(
        self,
        *,
        user_id: str,
        lead_id: str,
        status: JobLeadStatus,
        code: str,
        reason: str,
        source_url: str | None = None,
    ) -> JobLead:
        self.session.rollback()
        lead = self.get_lead(user_id=user_id, lead_id=lead_id)
        checked_at = datetime.now(UTC)
        lead.status = status.value
        lead.failure_code = code[:80]
        lead.failure_reason = reason[:2000]
        self.session.add(
            LeadVerification(
                id=generate_lead_verification_id(),
                lead_id=lead.id,
                user_id=user_id,
                result=status.value,
                source_url=source_url or lead.normalized_url,
                source_type=None,
                content_hash=None,
                field_evidence={},
                error_code=code[:80],
                error_reason=reason[:2000],
                checked_at=checked_at,
            )
        )
        self.session.commit()
        self.session.refresh(lead)
        return lead


def normalize_lead_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("岗位线索 URL 必须是有效的 HTTP/HTTPS 地址")
    return urlunsplit(
        (
            parsed.scheme.casefold(),
            parsed.netloc.casefold(),
            parsed.path or "/",
            parsed.query,
            "",
        )
    )


def _verification_rank(status: JobVerificationStatus) -> int:
    return {
        JobVerificationStatus.LEGACY_UNVERIFIED: 0,
        JobVerificationStatus.USER_PROVIDED: 1,
        JobVerificationStatus.VERIFIED_SOURCE: 2,
        JobVerificationStatus.VERIFIED_OFFICIAL: 3,
    }[status]


def _clean_hint(value: str | None) -> str | None:
    normalized = " ".join((value or "").split()).strip()
    return normalized[:160] or None


def _clean_snippet(value: str | None) -> str | None:
    normalized = " ".join((value or "").split()).strip()
    return normalized[:2000] or None


def _normalize_discovered_at(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
