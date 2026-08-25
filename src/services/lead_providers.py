from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from src.domain.discovery import LeadProvider as LeadProviderKind
from src.services.discovery_sources import JobSourceAdapter, JobStub


@dataclass(frozen=True)
class LeadCandidate:
    """Untrusted provider output. Persisting it never creates a formal job."""

    provider: LeadProviderKind
    source_url: str
    discovered_at: datetime
    source_id: str | None = None
    source_job_id: str | None = None
    company_hint: str | None = None
    title_hint: str | None = None
    search_snippet: str | None = None
    verification_stub: JobStub | None = None


class LeadProvider(Protocol):
    """Unified discovery boundary: providers may only return lead candidates."""

    provider_type: LeadProviderKind

    async def discover(self) -> list[LeadCandidate]:
        ...


class OfficialAdapterLeadProvider:
    """Expose legacy official adapters through the lead-only provider contract."""

    provider_type = LeadProviderKind.OFFICIAL_ADAPTER

    def __init__(self, adapter: JobSourceAdapter) -> None:
        self.adapter = adapter

    async def discover(self) -> list[LeadCandidate]:
        discovered_at = datetime.now(UTC)
        return [
            LeadCandidate(
                provider=self.provider_type,
                source_url=stub.detail_url,
                source_id=stub.source_id,
                source_job_id=stub.source_job_id,
                company_hint=stub.company,
                title_hint=stub.title,
                discovered_at=discovered_at,
                verification_stub=stub,
            )
            for stub in await self.adapter.list_jobs()
        ]


class ManualImportProvider:
    provider_type = LeadProviderKind.MANUAL_URL

    def __init__(
        self,
        *,
        source_url: str,
        company_hint: str | None = None,
        title_hint: str | None = None,
        discovered_at: datetime | None = None,
    ) -> None:
        self.candidate = LeadCandidate(
            provider=self.provider_type,
            source_url=source_url,
            company_hint=company_hint,
            title_hint=title_hint,
            discovered_at=discovered_at or datetime.now(UTC),
        )

    async def discover(self) -> list[LeadCandidate]:
        return [self.candidate]

    @staticmethod
    def build_handoff_stub(
        *,
        source_id: str,
        source_job_id: str,
        source_url: str,
        raw_content: str,
        company: str | None,
        title: str | None,
        locations: list[str],
        job_type: str | None,
    ) -> JobStub:
        return JobStub(
            source_id=source_id,
            source_job_id=source_job_id,
            company=company,
            title=title,
            locations=locations,
            job_type=job_type,
            published_at=None,
            detail_url=source_url,
            raw_content=raw_content,
        )


class ExternalAgentProvider:
    """Controlled contract for URL discoveries made by an external AI agent."""

    provider_type = LeadProviderKind.EXTERNAL_AGENT

    def __init__(
        self,
        *,
        source_url: str,
        search_snippet: str | None,
        inferred_company: str | None,
        inferred_title: str | None,
        discovered_at: datetime | None,
    ) -> None:
        self.candidate = LeadCandidate(
            provider=self.provider_type,
            source_url=source_url,
            search_snippet=search_snippet,
            company_hint=inferred_company,
            title_hint=inferred_title,
            discovered_at=discovered_at or datetime.now(UTC),
        )

    async def discover(self) -> list[LeadCandidate]:
        return [self.candidate]


class ThirdPartyLeadProvider(ExternalAgentProvider):
    """Keep third-party identity explicit while preserving the same trust boundary."""

    provider_type = LeadProviderKind.THIRD_PARTY

    def __init__(
        self,
        *,
        source_url: str,
        search_snippet: str | None,
        inferred_company: str | None,
        inferred_title: str | None,
        discovered_at: datetime | None,
    ) -> None:
        super().__init__(
            source_url=source_url,
            search_snippet=search_snippet,
            inferred_company=inferred_company,
            inferred_title=inferred_title,
            discovered_at=discovered_at,
        )
        self.candidate = LeadCandidate(
            provider=self.provider_type,
            source_url=self.candidate.source_url,
            search_snippet=self.candidate.search_snippet,
            company_hint=self.candidate.company_hint,
            title_hint=self.candidate.title_hint,
            discovered_at=self.candidate.discovered_at,
        )
