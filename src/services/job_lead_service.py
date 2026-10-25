from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from urllib.parse import urlsplit

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
from src.services.job_detail_scope import (
    EXTRACTOR_VERSION,
    DetailScopeError,
    closed_page_notice,
    scope_job_document,
)
from src.services.job_fact_verifier import verified_stub_evidence, verify_page_facts
from src.services.job_service import JobImportService
from src.services.job_url import canonical_job_url
from src.services.lead_providers import (
    LeadCandidate,
    ManualImportProvider,
)
from src.services.lead_providers import (
    LeadProvider as LeadProviderContract,
)
from src.services.recruitment_context import (
    availability_status as evidence_availability_status,
)
from src.services.recruitment_context import (
    collect_recruitment_context,
    resolve_availability,
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

    def __init__(self, session: Session, *, understanding=None, review_guard=None) -> None:
        self.session = session
        self.understanding = understanding
        self.review_guard = review_guard

    async def _readable_document(self, raw_html, url, *, lead, snapshot_id, method="http", allow_visual=False):
        document, scoped = _readable_page_document(raw_html, url)
        if scoped is not None and closed_page_notice(raw_html, url=url):
            # A closed page with a complete JD can still be saved as CLOSED,
            # without spending any interpretation/vision budget.
            return scoped[0], (scoped[0], True), False
        from src.services.lead_presentation import explicit_listing_url

        if explicit_listing_url(url):
            return document, None, False
        from src.services.body_quality import assess_body
        from src.services.job_detail_scope import readable_page_text

        quality = assess_body(scoped[0].text if scoped else readable_page_text(raw_html),
                              title=scoped[0].title if scoped else document.title)
        snapshot = self.session.get(LeadVerification, snapshot_id)
        snapshot.field_evidence = {**snapshot.field_evidence, "body_quality": quality}
        self.session.commit()
        if quality["status"] != "readable":
            if quality["status"] == "empty" and allow_visual:
                return document, None, False
            code = "browser_body_incomplete" if method == "browser" else "page_body_incomplete"
            snapshot.field_evidence = {**snapshot.field_evidence, "ai_reading_pending": False}
            self.session.commit()
            self._record_failure(user_id=lead.user_id, lead_id=lead.id,
                status=JobLeadStatus.FAILED if method == "browser" else JobLeadStatus.NEEDS_BROWSER,
                code=code, reason=quality["reason"], source_url=url)
            raise LeadVerificationFailure(code=code, message=quality["reason"], lead_id=lead.id)
        from src.config import get_settings
        from src.services.source_understanding import SourceUnderstanding

        if self.understanding is None:
            self.understanding = SourceUnderstanding(get_settings())
        # The deterministic scope retains the complete current JD, including
        # metadata, qualifications and exceptions. Avoid making the model
        # re-read site navigation or recommendations when that scope is known.
        recovery_input = scoped[0] if scoped is not None else replace(document, text=readable_page_text(raw_html))
        if self.understanding.primary:
            from src.services.saved_page_review import page_attempt, save_page_attempt

            snapshot = self.session.get(LeadVerification, snapshot_id)
            conditions = self.understanding.conditions
            attempt = page_attempt(snapshot, conditions)
            timeout = (self.understanding.settings.web_search_semantic_retry_timeout_seconds
                       if attempt.get("failures", 0) else None)
            save_page_attempt(snapshot, conditions, started=True)
            self.session.commit()
            analyzed = await self.understanding.analyze_page(recovery_input, url=url,
                title_hint=lead.title_hint, timeout=timeout)
            if self.review_guard and not self.review_guard():
                raise LeadVerificationFailure(code="semantic_review_superseded",
                    message="目标或原文已变化，保留新状态", lead_id=lead.id)
            snapshot = self.session.get(LeadVerification, snapshot_id)
            if analyzed is not None:
                interpreted, evidence = analyzed
                save_page_attempt(snapshot, conditions)
                snapshot.field_evidence = {**snapshot.field_evidence, "page_understanding": evidence,
                                           "ai_reading_pending": False}
                self.session.commit()
                if interpreted is None:
                    code = "job_detail_unconfirmed" if evidence["page_type"] == "uncertain" else "lead_not_job_page"
                    message = "原文理解尚未确认唯一岗位" if code == "job_detail_unconfirmed" else "原文为列表或其他页面，保留来源"
                    self._record_failure(user_id=lead.user_id, lead_id=lead.id,
                        status=JobLeadStatus.NEEDS_USER, code=code, reason=message, source_url=url)
                    raise LeadVerificationFailure(code=code, message=message, lead_id=lead.id)
                return interpreted, (interpreted, False), evidence["sections"]
            # A model failure is not a browser failure. Preserve the already
            # fetched page for another interpretation attempt without refetching.
            if scoped is None and len(recovery_input.text) >= 100:
                snapshot = self.session.get(LeadVerification, snapshot_id)
                save_page_attempt(snapshot, conditions,
                    error=self.understanding.page_failures.get(url, "semantic_unavailable"))
                self.session.commit()
                message = "官网正文已保存，AI理解暂未完成，可继续处理原文"
                self._record_failure(user_id=lead.user_id, lead_id=lead.id,
                    status=JobLeadStatus.DEFERRED, code="semantic_page_pending", reason=message, source_url=url)
                raise LeadVerificationFailure(code="semantic_page_pending", message=message, lead_id=lead.id)
            # A local job scope can still be persisted for the field-review lane.
            snapshot.field_evidence = {**snapshot.field_evidence, "ai_reading_pending": False}
            self.session.commit()
            return document, scoped, False
        if scoped is not None and looks_like_job_page(document, url=url):
            return document, scoped, False
        recovered = await self.understanding.recover_detail(recovery_input, url=url, title_hint=lead.title_hint)
        if recovered is None:
            return document, scoped, False
        document, evidence = recovered
        snapshot = self.session.get(LeadVerification, snapshot_id)
        snapshot.field_evidence = {**snapshot.field_evidence, "semantic_scope": evidence}
        self.session.commit()
        return document, (document, False), evidence["sections"]

    def record_official_link(self, *, user_id, lead_id, source_url, entry_url, from_url,
                             scope_url=None, snapshot_id=None, company=None):
        from src.services.company_registry import (
            enabled_company_sources,
            within_company_source,
        )

        manual = any(source.verification_method == "manual" and within_company_source(source_url, source)
                     for source in enabled_company_sources(session=self.session, user_id=user_id))
        self.session.add(LeadVerification(
            id=generate_lead_verification_id(), lead_id=lead_id, user_id=user_id,
            result="OFFICIAL_LINK", source_url=normalize_lead_url(source_url),
            source_type="user_confirmed_company" if manual else "official_outbound_link", checked_at=datetime.now(UTC),
            field_evidence={"entry_url": entry_url, "from_url": from_url,
                            "scope_url": scope_url, "snapshot_id": snapshot_id, "company": company,
                            "verification_method": "manual" if manual else "automatic"},
        ))
        self.session.commit()

    def _official_target(self, lead, url, official_hosts):
        from src.services.recruitment_trust import hiring_scope, within_scope
        if (urlsplit(url).hostname or "").lower() in official_hosts:
            return True
        # Trust an observed detail URL or enterprise scope, never a shared ATS host.
        records = self.session.scalars(select(LeadVerification).where(
            LeadVerification.lead_id == lead.id, LeadVerification.user_id == lead.user_id,
            LeadVerification.result == "OFFICIAL_LINK",
        ))
        return any(
            urlsplit(r.field_evidence.get("entry_url", "")).hostname in official_hosts
            and (r.source_url == normalize_lead_url(url) or (
                hiring_scope(r.field_evidence.get("scope_url") or "")
                and within_scope(url, hiring_scope(r.field_evidence["scope_url"]))
            )) for r in records
        )

    def _official_company(self, lead, document):
        if document.company:
            return document
        records = self.session.scalars(select(LeadVerification).where(
            LeadVerification.lead_id == lead.id, LeadVerification.user_id == lead.user_id,
            LeadVerification.result == "OFFICIAL_LINK",
        ))
        companies = {r.field_evidence.get("company") for r in records if r.field_evidence.get("company")}
        if not companies:
            from src.services.company_registry import (
                enabled_company_sources,
                within_company_source,
            )

            companies = {source.company for source in enabled_company_sources(
                session=self.session, user_id=lead.user_id)
                if within_company_source(lead.source_url, source)}
        return replace(document, company=companies.pop()) if len(companies) == 1 else document

    def _prepare_official_transport(self, lead, reader, official_hosts):
        from src.services.company_registry import (
            company_source_hosts,
            enabled_company_sources,
            within_company_source,
        )

        sources = enabled_company_sources(session=self.session, user_id=lead.user_id)
        for source in sources:
            if source.official_homepage_url and within_company_source(lead.normalized_url, source):
                official_hosts.update(company_source_hosts([source]))
                existing = self.session.scalar(select(LeadVerification.id).where(
                    LeadVerification.lead_id == lead.id, LeadVerification.user_id == lead.user_id,
                    LeadVerification.result == "OFFICIAL_LINK",
                ).limit(1))
                if not existing:
                    self.record_official_link(user_id=lead.user_id, lead_id=lead.id,
                        source_url=lead.normalized_url, entry_url=source.official_homepage_url,
                        from_url=source.hiring_evidence_url or source.official_homepage_url,
                        scope_url=source.career_url, company=source.company)
                break
        if self._official_target(lead, lead.normalized_url, official_hosts):
            checker = getattr(reader, "safety_checker", None)
            if checker is not None and hasattr(checker, "proxy_allowed_hosts"):
                checker.proxy_allowed_hosts = checker.proxy_allowed_hosts | {urlsplit(lead.normalized_url).hostname}

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
                or_(JobLead.normalized_url == normalized_url,
                    (JobLead.source_id == source_id) & (JobLead.source_job_id == source_job_id)),
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
            # Rediscovery can add evidence; never replace or truncate old snippets.
            if search_snippet and search_snippet.strip() not in (existing.search_snippet or ""):
                existing.search_snippet = "\n\n".join(filter(None, [existing.search_snippet, search_snippet.strip()]))
            if not existing.title_hint and title_hint:
                existing.title_hint = _clean_hint(title_hint)
            if not existing.company_hint and company_hint:
                existing.company_hint = _clean_hint(company_hint)
            from src.services.lead_extraction import extract_lead_preview
            preview = extract_lead_preview(source_url, title=existing.title_hint, snippet=existing.search_snippet)
            existing.extracted_fields = {**preview, **{k: v for k, v in (existing.extracted_fields or {}).items() if v is not None and v != [] and v != ""}}
            self.session.commit()
            return existing

        previous_selection = self.session.scalar(
            select(JobLead.selection_status).where(JobLead.user_id == user_id, JobLead.normalized_url == normalized_url)
            .order_by(JobLead.updated_at.desc(), JobLead.id.desc()).limit(1)
        )
        from src.services.lead_extraction import extract_lead_preview
        from src.services.lead_retry import prior_retry_state

        lead = JobLead(
            retry_state=prior_retry_state(self.session, run=run, normalized_url=normalized_url)
            if discovery_run_id is not None else {},
            extracted_fields=extract_lead_preview(source_url, title=title_hint, snippet=search_snippet),
            selection_status=previous_selection or "DISCOVERED",
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
        lead = self.create_lead(
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
        if candidate.observed_title:
            lead.extracted_fields = {**(lead.extracted_fields or {}), "page_type_basis": "observed_listing"}
            self.session.commit()
        if candidate.search_context:
            lead.extracted_fields = {**(lead.extracted_fields or {}), "search_context": candidate.search_context}
            self.session.commit()
        return lead

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
        discovery_run_id: str | None = None,
    ) -> list[JobLead]:
        statement = (
            select(JobLead)
            .where(JobLead.user_id == user_id)
            .order_by(JobLead.created_at.desc(), JobLead.id.desc())
        )
        if status is not None:
            statement = statement.where(JobLead.status == status.value)
        if discovery_run_id:
            statement = statement.where(JobLead.discovery_run_id == discovery_run_id)
        # Historical runs may predate canonical identity. Coalesce their display
        # without deleting records, verification evidence or user selections.
        grouped = {}
        for lead in self.session.scalars(statement).all():
            key = (lead.discovery_run_id, lead.provider, canonical_job_url(lead.source_url))
            rank = (lead.selection_status in {"SAVED", "IGNORED"}, bool(lead.job_posting_id), lead.status == "CLOSED", bool(lead.title_hint))
            if key not in grouped or rank > grouped[key][0]:
                grouped[key] = (rank, lead)
        return [lead for _, lead in grouped.values()]

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
            from src.services.lead_retry import mark_method

            mark_method(lead, "official_payload" if source_type != "manual_handoff" else "manual")
        try:
            from src.services.body_quality import assess_body

            quality = assess_body(stub.raw_content, title=stub.title)
            if quality["status"] != "readable" and availability_status != JobAvailabilityStatus.CLOSED:
                code = "browser_body_incomplete" if source_type == "verified_browser" else "page_body_incomplete"
                raise LeadVerificationFailure(code=code, message=quality["reason"], lead_id=lead.id)
            posting, created = self._upsert_posting(
                stub,
                source_type=source_type,
                verification_status=verification_status,
                availability_status=availability_status,
            )
            if source_type in {"verified_html", "verified_browser"}:
                # Re-reading a page cannot refresh an old ACTIVE observation.
                if posting.availability_status != "CLOSED" or availability_status != JobAvailabilityStatus.UNKNOWN:
                    posting.availability_status = availability_status.value
                posting.last_availability_checked_at = datetime.now(UTC)
                if availability_status == JobAvailabilityStatus.CLOSED:
                    posting.closed_at = posting.closed_at or datetime.now(UTC)
                elif availability_status == JobAvailabilityStatus.ACTIVE:
                    posting.closed_at = None
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
            from src.services.lead_retry import mark_success

            mark_success(lead)
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
                initial_status=CandidateStatus(lead.selection_status or "DISCOVERED"),
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
        official_only: bool = False,
        saved_only: bool = False,
    ) -> VerifiedLeadResult:
        existing = self._existing_verified_result(user_id=user_id, lead_id=lead_id)
        if existing is not None:
            return existing
        lead = self.get_lead(user_id=user_id, lead_id=lead_id)
        cached_page = self._pending_page_snapshot(lead)
        if saved_only and cached_page is None:
            raise LeadVerificationFailure(code="saved_body_unavailable", message="已保存正文已过期或变化，需重新读取", lead_id=lead.id)
        lead = self._start_verification(user_id=user_id, lead_id=lead_id)
        from src.services.lead_retry import mark_method

        mark_method(lead, "http")
        self.session.commit()
        self._prepare_official_transport(lead, reader, official_hosts)
        try:
            if cached_page is not None:
                from src.services.url_reader import FetchedResponse

                response = FetchedResponse(requested_url=lead.normalized_url, final_url=cached_page.source_url,
                    status_code=200, content_type="text/html", body=cached_page.field_evidence["raw_html"].encode())
            else:
                response = await reader.fetch(lead.normalized_url)
        except URLReaderError as error:
            code = {404: "source_not_found", 410: "source_not_found", 429: "source_rate_limited",
                    401: "source_forbidden", 403: "source_forbidden"}.get(getattr(error, "status_code", None), error.code)
            self._record_failure(
                user_id=user_id,
                lead_id=lead.id,
                status=JobLeadStatus.FAILED,
                code=code,
                reason=str(error),
            )
            raise LeadVerificationFailure(
                code=code,
                message=str(error),
                lead_id=lead.id,
            ) from error

        raw_html = response.body.decode("utf-8", errors="replace")
        snapshot_id = cached_page.id if cached_page is not None else self._save_page_snapshot(
            user_id=user_id, lead_id=lead.id, url=response.final_url,
            raw_html=raw_html, raw_text=None, raw_bytes=response.body,
        )
        self._record_closed_notice(lead, raw_html, response.final_url, snapshot_id,
                                   official_hosts=official_hosts, official_only=official_only, keep_readable=True)
        document, scoped_document, semantic_scope = await self._readable_document(
            raw_html, response.final_url, lead=lead, snapshot_id=snapshot_id)
        if not semantic_scope and not (scoped_document and scoped_document[1]) and not looks_like_job_page(document, url=response.final_url):
            self._record_closed_notice(lead, raw_html, response.final_url, snapshot_id,
                                       official_hosts=official_hosts, official_only=official_only)
            if looks_like_dynamic_shell(raw_html) or (
                any(tag in raw_html.lower() for tag in ("<img", "<canvas", "<svg"))
                and len(document.text.strip()) < 200
            ):
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
        is_official = self._official_target(lead, final_url, official_hosts)
        if official_only and not is_official:
            self._record_failure(
                user_id=user_id, lead_id=lead.id, status=JobLeadStatus.NEEDS_USER,
                code="official_source_unconfirmed",
                reason="跳转后的页面尚未确认官网归属，保留为待核验线索",
                source_url=final_url,
            )
            raise LeadVerificationFailure(
                code="official_source_unconfirmed", message="最终页面并非已确认官网", lead_id=lead.id,
            )
        verification_status = (
            JobVerificationStatus.VERIFIED_OFFICIAL
            if is_official
            else JobVerificationStatus.VERIFIED_SOURCE
        )
        source_id = lead.source_id or f"{lead.provider}:{host}"
        source_job_id = lead.source_job_id or hashlib.sha256(
            final_url.encode("utf-8")
        ).hexdigest()[:24]
        try:
            document, closed = scoped_document or scope_job_document(raw_html, document, url=final_url)
            if not document.title or document.title.strip().endswith(("招聘", "招聘官网", "Careers")):
                raise DetailScopeError("未提取到具体岗位名称，不能将招聘网站标题作为职位")
        except DetailScopeError as error:
            self._record_closed_notice(lead, raw_html, final_url, snapshot_id,
                                       official_hosts=official_hosts, official_only=official_only)
            self._record_failure(
                user_id=user_id, lead_id=lead.id, status=JobLeadStatus.NEEDS_USER,
                code="job_detail_unconfirmed", reason=str(error), source_url=final_url,
            )
            raise LeadVerificationFailure(
                code="job_detail_unconfirmed", message=str(error), lead_id=lead.id,
            ) from error
        document = self._official_company(lead, document)
        context = await self._recruitment_context(
            lead, document, raw_html, final_url, None if saved_only else reader, official_hosts,
            checked_at=cached_page.checked_at if saved_only else None,
        )
        if semantic_scope:
            context = {**context, "text_sections": semantic_scope}
        availability = resolve_availability(raw_html, url=final_url, context=context)
        if closed:
            availability = {"value": "CLOSED", "source_text": "已结束", "source_url": final_url}
        facts = verify_page_facts(document)
        facts.evidence["recruitment_context"] = context
        facts.evidence["availability"] = {**availability, "snapshot_id": availability.get("snapshot_id") or snapshot_id}
        if not document.json_ld:
            for key in ("company", "job_type"):
                item = facts.evidence.get(key)
                if item and item.get("source_kind") == "json_ld":
                    item["source_kind"] = "company_registry" if key == "company" else "page_scope_or_url"
            for item in facts.evidence.get("locations", []):
                if item and item.get("source_kind") == "json_ld":
                    item["source_kind"] = "page_scope"
        facts.evidence["page_scope"] = {
            "source_url": final_url,
            "closed": closed,
            "status_source_text": "已结束" if closed else None,
            "extractor": EXTRACTOR_VERSION,
            "snapshot_id": snapshot_id,
        }
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
            recruitment_context=context,
        )
        from src.services.source_understanding import attach_page_understanding

        stub = attach_page_understanding(stub)
        facts.evidence["recruitment_context"] = stub.recruitment_context
        result = self.verify_stub(
            user_id=user_id,
            lead_id=lead.id,
            stub=stub,
            verification_status=verification_status,
            source_type="verified_html",
            availability_status=evidence_availability_status(availability),
            verification_started=True,
            field_evidence=facts.evidence,
        )
        if cached_page is not None:
            result.posting.last_verified_at = cached_page.checked_at
            result.posting.last_availability_checked_at = cached_page.checked_at
            self.session.commit()
        return result

    def _pending_page_snapshot(self, lead):
        return self.pending_page_snapshots(lead.user_id, [lead.normalized_url]).get(lead.normalized_url)

    def pending_page_snapshots(self, user_id, urls, *, now=None):
        """Select the latest observation per URL in one query, including aliases.

        A newer non-pending snapshot supersedes an older pending one. Filtering
        pending flags before selecting the latest would resurrect stale bodies.
        """
        from datetime import timedelta

        if not urls:
            return {}
        now = now or datetime.now(UTC)
        rows = self.session.execute(select(JobLead.normalized_url, LeadVerification).join(
            JobLead, JobLead.id == LeadVerification.lead_id).where(
            JobLead.user_id == user_id, JobLead.normalized_url.in_(set(urls)),
            LeadVerification.result == "SNAPSHOT",
        ).order_by(LeadVerification.checked_at.desc(), LeadVerification.id.desc()))
        seen, pending = set(), {}
        for url, record in rows:
            if url in seen:
                continue
            seen.add(url)
            checked = record.checked_at.replace(tzinfo=record.checked_at.tzinfo or UTC)
            if (record.field_evidence.get("ai_reading_pending") and record.field_evidence.get("raw_html")
                    and timedelta(0) <= now - checked < timedelta(days=1)):
                pending[url] = record
        return pending

    async def verify_browser(
        self,
        *,
        user_id: str,
        lead_id: str,
        reader: BrowserJobReader,
        official_hosts: set[str],
        official_only: bool = False,
    ) -> VerifiedLeadResult:
        existing = self._existing_verified_result(user_id=user_id, lead_id=lead_id)
        if existing is not None:
            return existing
        lead = self._start_verification(user_id=user_id, lead_id=lead_id)
        from src.services.lead_retry import mark_method

        mark_method(lead, "browser")
        self.session.commit()
        self._prepare_official_transport(lead, reader, official_hosts)
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

        snapshot_id = self._save_page_snapshot(
            user_id=user_id, lead_id=lead.id, url=snapshot.final_url,
            raw_html=snapshot.raw_html, raw_text=snapshot.visible_text,
        )
        self._record_closed_notice(lead, snapshot.raw_html, snapshot.final_url, snapshot_id,
                                   official_hosts=official_hosts, official_only=official_only, keep_readable=True)
        if snapshot.html_compacted:
            evidence = self.session.get(LeadVerification, snapshot_id)
            evidence.field_evidence = {**evidence.field_evidence, "html_compacted": True,
                                      "snapshot_format": "dom_without_bundles_styles_or_svg"}
            self.session.commit()
        document, scoped_document, semantic_scope = await self._readable_document(
            snapshot.raw_html, snapshot.final_url, lead=lead, snapshot_id=snapshot_id, method="browser",
            allow_visual=bool(snapshot.screenshots))
        readable_dom = scoped_document is not None and (semantic_scope or scoped_document[1] or looks_like_job_page(document, url=snapshot.final_url))
        if snapshot.screenshots or snapshot.screenshot_error:
            from src.config import get_settings
            from src.services.vision_job_extraction import extract_visual_job

            evidence = self.session.get(LeadVerification, snapshot_id)
            evidence.field_evidence = {
                **evidence.field_evidence,
                "screenshots": list(snapshot.screenshots),
                "screenshot_error": snapshot.screenshot_error,
                "vision": {"status": "not_needed_readable_dom" if readable_dom else "started" if snapshot.screenshots else "capture_failed"},
            }
            # Store image evidence before a model timeout or queue cancellation.
            self.session.commit()
            if snapshot.screenshots and not readable_dom:
                result = await extract_visual_job(snapshot.screenshots, settings=get_settings())
                evidence.field_evidence = {**evidence.field_evidence, "vision": result}
                if result["status"] == "extracted":
                    fields = result["fields"]
                    lead.extracted_fields = {
                        **(lead.extracted_fields or {}),
                        **{k: v for k, v in fields.items() if v is not None and v != [] and v != ""},
                        "basis": "screenshot", "verified": False,
                        "snapshot_id": snapshot_id, "source_url": snapshot.final_url,
                        "coverage_limited": any(i.get("coverage_limited") for i in snapshot.screenshots),
                    }
                self.session.commit()
                if result["status"] == "extracted":
                    message = "已从截图提取岗位信息；截图可能不完整，官网及投递条件仍待核验"
                    self._record_failure(user_id=user_id, lead_id=lead.id, status=JobLeadStatus.NEEDS_USER,
                                         code="visual_extraction_unverified", reason=message, source_url=snapshot.final_url)
                    raise LeadVerificationFailure(code="visual_extraction_unverified", message=message, lead_id=lead.id)
        if not semantic_scope and not (scoped_document and scoped_document[1]) and not looks_like_job_page(document, url=snapshot.final_url):
            self._record_closed_notice(lead, snapshot.raw_html, snapshot.final_url, snapshot_id,
                                       official_hosts=official_hosts, official_only=official_only)
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
        is_official = self._official_target(lead, final_url, official_hosts)
        if official_only and not is_official:
            self._record_failure(
                user_id=user_id, lead_id=lead.id, status=JobLeadStatus.NEEDS_USER,
                code="official_source_unconfirmed",
                reason="跳转后的页面尚未确认官网归属，保留为待核验线索",
                source_url=final_url,
            )
            raise LeadVerificationFailure(
                code="official_source_unconfirmed", message="最终页面并非已确认官网", lead_id=lead.id,
            )
        verification_status = (
            JobVerificationStatus.VERIFIED_OFFICIAL
            if is_official
            else JobVerificationStatus.VERIFIED_SOURCE
        )
        try:
            document, closed = scoped_document or scope_job_document(snapshot.raw_html, document, url=final_url)
            if not document.title or document.title.strip().endswith(("招聘", "招聘官网", "Careers")):
                raise DetailScopeError("未提取到具体岗位名称，不能将招聘网站标题作为职位")
        except DetailScopeError as error:
            self._record_closed_notice(lead, snapshot.raw_html, final_url, snapshot_id,
                                       official_hosts=official_hosts, official_only=official_only)
            self._record_failure(
                user_id=user_id, lead_id=lead.id, status=JobLeadStatus.NEEDS_USER,
                code="job_detail_unconfirmed", reason=str(error), source_url=final_url,
            )
            raise LeadVerificationFailure(
                code="job_detail_unconfirmed", message=str(error), lead_id=lead.id,
            ) from error
        document = self._official_company(lead, document)
        from src.config import get_settings

        context = await self._recruitment_context(
            lead, document, snapshot.raw_html, final_url,
            SafeHTTPReader(proxy=get_settings().url_fetch_proxy, proxy_allowed_hosts=official_hosts,
                           timeout_seconds=4, max_retries=0),
            official_hosts, api_records=snapshot.recruitment_api,
        )
        if semantic_scope:
            context = {**context, "text_sections": semantic_scope}
        availability = resolve_availability(snapshot.raw_html, url=final_url, context=context)
        if closed:
            availability = {"value": "CLOSED", "source_text": "已结束", "source_url": final_url}
        facts = verify_page_facts(document)
        facts.evidence["recruitment_context"] = context
        facts.evidence["availability"] = {**availability, "snapshot_id": availability.get("snapshot_id") or snapshot_id}
        if not document.json_ld:
            for key in ("company", "job_type"):
                item = facts.evidence.get(key)
                if item and item.get("source_kind") == "json_ld":
                    item["source_kind"] = "company_registry" if key == "company" else "page_scope_or_url"
            for item in facts.evidence.get("locations", []):
                if item and item.get("source_kind") == "json_ld":
                    item["source_kind"] = "page_scope"
        facts.evidence["page_scope"] = {
            "source_url": final_url,
            "closed": closed,
            "status_source_text": "已结束" if closed else None,
            "extractor": EXTRACTOR_VERSION,
            "snapshot_id": snapshot_id,
        }
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
            recruitment_context=context,
        )
        from src.services.source_understanding import attach_page_understanding

        stub = attach_page_understanding(stub)
        facts.evidence["recruitment_context"] = stub.recruitment_context
        return self.verify_stub(
            user_id=user_id,
            lead_id=lead.id,
            stub=stub,
            verification_status=verification_status,
            source_type="verified_browser",
            availability_status=evidence_availability_status(availability),
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
            JobLeadStatus.DEFERRED.value,
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
        from src.services.body_quality import readable_body

        if posting.availability_status != "CLOSED" and not readable_body(posting.raw_content, title=posting.title):
            lead.status = JobLeadStatus.DEFERRED.value
            self.session.commit()
            return None
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
            # Legacy rows may still contain tracking parameters. Reuse their
            # identity without deleting analyses, saved state or applications.
            posting = next((row for row in self.session.scalars(select(JobPosting).where(
                JobPosting.source_url.is_not(None)))
                if normalize_lead_url(row.source_url) == normalized_url), None)
        if posting is None:
            posting = self.session.scalar(
                select(JobPosting).where(
                    or_(
                        JobPosting.source_url == normalized_url,
                        JobPosting.source_url.is_(None) & (JobPosting.content_hash == content_hash),
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
            if source_type in {"verified_html", "verified_browser"}:
                posting.recruitment_context = stub.recruitment_context
            return posting, True

        content_changed = posting.content_hash != content_hash
        current_verification = JobVerificationStatus(posting.verification_status)
        incoming_is_stronger = _verification_rank(verification_status) >= _verification_rank(
            current_verification
        )
        if incoming_is_stronger and source_type in {"verified_html", "verified_browser"}:
            from src.services.search_goal_service import posting_stub
            from src.services.source_understanding import preserve_review_context

            posting.recruitment_context = preserve_review_context(posting_stub(posting), stub)
        if incoming_is_stronger:
            posting.source_url = normalized_url
            posting.source_type = source_type
            posting.source_id = stub.source_id
            posting.source_job_id = stub.source_job_id
            posting.company = stub.company or posting.company
            posting.title = stub.title or posting.title
            posting.locations = stub.locations or posting.locations or []
            # A fresh scoped page can retract an earlier footer-derived type.
            posting.job_type = (
                stub.job_type if source_type in {"verified_html", "verified_browser"}
                else stub.job_type or posting.job_type
            )
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

    async def _recruitment_context(self, lead, document, raw_html, url, fetcher, official_hosts, *, api_records=(), checked_at=None):
        def save_snapshot(source_url, raw):
            snapshot_id = generate_lead_verification_id()
            self.session.add(LeadVerification(
                id=snapshot_id, lead_id=lead.id, user_id=lead.user_id,
                result="SNAPSHOT", source_url=source_url, source_type="recruitment_context_snapshot",
                content_hash=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
                field_evidence={"raw_content": raw, "job_url": url}, checked_at=checked_at or datetime.now(UTC),
            ))
            self.session.commit()
            return snapshot_id

        return await collect_recruitment_context(
            raw_html=raw_html, document=document, url=url, fetcher=fetcher,
            is_official=lambda target: self._official_target(lead, target, official_hosts),
            save_snapshot=save_snapshot, api_records=api_records, now=checked_at,
        )

    def _save_page_snapshot(
        self, *, user_id: str, lead_id: str, url: str,
        raw_html: str, raw_text: str | None, raw_bytes: bytes | None = None,
    ) -> str:
        """Commit the fetched source before any lossy extraction or validation."""
        snapshot_id = generate_lead_verification_id()
        self.session.add(LeadVerification(
            id=snapshot_id, lead_id=lead_id, user_id=user_id,
            result="SNAPSHOT", source_url=url,
            source_type="browser_snapshot" if raw_bytes is None else "http_snapshot",
            content_hash=hashlib.sha256(raw_bytes if raw_bytes is not None else raw_html.encode("utf-8")).hexdigest(),
            field_evidence={
                "raw_html": raw_html,
                "raw_text": raw_text,
                "raw_bytes_base64": base64.b64encode(raw_bytes).decode("ascii") if raw_bytes is not None else None,
                "extractor": EXTRACTOR_VERSION,
            },
            checked_at=datetime.now(UTC),
        ))
        self.session.commit()
        from src.services.lead_extraction import extract_lead_preview
        lead = self.get_lead(user_id=user_id, lead_id=lead_id)
        if normalize_lead_url(url) == lead.normalized_url:
            preview = extract_lead_preview(url, raw_html=raw_html, snapshot_id=snapshot_id)
            if preview.get("title"):
                lead.extracted_fields = {**(lead.extracted_fields or {}), **{k:v for k,v in preview.items() if v is not None and v != []}}
                self.session.commit()
        return snapshot_id

    def _record_closed_notice(self, lead, raw_html, url, snapshot_id, *, official_hosts, official_only, keep_readable=False):
        if official_only and not self._official_target(lead, url, official_hosts):
            return
        quote = closed_page_notice(raw_html, url=url)
        if not quote:
            return
        if keep_readable and _readable_page_document(raw_html, url)[1] is not None:
            return
        message = f"原始岗位页面明确显示：{quote}"
        self._record_failure(
            user_id=lead.user_id, lead_id=lead.id, status=JobLeadStatus.CLOSED,
            code="job_closed", reason=message, source_url=url,
            field_evidence={"availability": {"value": "CLOSED", "source_text": quote,
                "source_url": url, "snapshot_id": snapshot_id, "source_kind": "visible_dom"}},
        )
        raise LeadVerificationFailure(code="job_closed", message=message, lead_id=lead.id)

    def _record_failure(
        self,
        *,
        user_id: str,
        lead_id: str,
        status: JobLeadStatus,
        code: str,
        reason: str,
        source_url: str | None = None,
        field_evidence: dict | None = None,
    ) -> JobLead:
        self.session.rollback()
        lead = self.get_lead(user_id=user_id, lead_id=lead_id)
        checked_at = datetime.now(UTC)
        lead.status = status.value
        lead.failure_code = code[:80]
        lead.failure_reason = reason[:2000]
        from src.services.lead_retry import failed_state, retry_message

        lead.retry_state = failed_state(lead.retry_state, code, now=checked_at)
        if lead.retry_state.get("mode") in {"cooldown", "exhausted", "manual", "needs_adapter"}:
            lead.failure_reason = f"{lead.failure_reason}；{retry_message(lead.retry_state)}"
        if status == JobLeadStatus.CLOSED:
            lead.verified_at = checked_at
        self.session.add(
            LeadVerification(
                id=generate_lead_verification_id(),
                lead_id=lead.id,
                user_id=user_id,
                result=status.value,
                source_url=source_url or lead.normalized_url,
                source_type=None,
                content_hash=None,
                field_evidence=field_evidence or {},
                error_code=code[:80],
                error_reason=reason[:2000],
                checked_at=checked_at,
            )
        )
        self.session.commit()
        self.session.refresh(lead)
        return lead


def _readable_page_document(raw_html, url):
    """A unique scoped heading outranks the site's generic browser-tab title."""
    from src.services.lead_presentation import discovery_kind

    document = parse_html_document(raw_html)
    try:
        scoped = scope_job_document(raw_html, document, url=url)
    except DetailScopeError:
        return document, None
    if discovery_kind(url, scoped[0].title, observed_title=True) == "job":
        return scoped[0] if looks_like_job_page(scoped[0], url=url) else document, scoped
    return document, None


def normalize_lead_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("岗位线索 URL 必须是有效的 HTTP/HTTPS 地址")
    return canonical_job_url(value)


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
    return (value or "").strip() or None


def _normalize_discovered_at(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
