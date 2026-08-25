from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from src.api import discovery as discovery_api
from src.domain.discovery import JobLeadStatus, LeadProvider, LeadVerification
from src.domain.job import (
    JobAvailabilityCheck,
    JobAvailabilityStatus,
    JobPosting,
)
from src.main import app
from src.services.browser_job_reader import (
    BrowserPageSnapshot,
    BrowserReadError,
    PlaywrightBrowserJobReader,
)
from src.services.discovery_service import DiscoveryService
from src.services.discovery_sources import JobStub
from src.services.job_availability_service import JobAvailabilityService
from src.services.job_lead_service import (
    JobLeadService,
    JobLeadStateError,
    LeadVerificationFailure,
)
from src.services.lead_providers import (
    ExternalAgentProvider,
    ManualImportProvider,
    OfficialAdapterLeadProvider,
)
from src.services.lead_providers import (
    LeadProvider as LeadProviderContract,
)
from src.services.url_reader import FetchedResponse, URLFetchError, URLSafetyChecker


class MappingHTMLReader:
    def __init__(self, html: str, *, final_url: str) -> None:
        self.html = html
        self.final_url = final_url

    async def fetch(self, url: str) -> FetchedResponse:
        return FetchedResponse(
            requested_url=url,
            final_url=self.final_url,
            status_code=200,
            content_type="text/html; charset=utf-8",
            body=self.html.encode("utf-8"),
        )


class FailingReader:
    async def fetch(self, url: str) -> FetchedResponse:
        raise URLFetchError("fixture source unavailable")


class BlockingReader(MappingHTMLReader):
    def __init__(self, html: str, *, final_url: str) -> None:
        super().__init__(html, final_url=final_url)
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def fetch(self, url: str) -> FetchedResponse:
        self.entered.set()
        await self.release.wait()
        return await super().fetch(url)


class FakeBrowserReader:
    def __init__(self, snapshot: BrowserPageSnapshot | Exception) -> None:
        self.snapshot = snapshot
        self.calls: list[str] = []

    async def read(self, url: str) -> BrowserPageSnapshot:
        self.calls.append(url)
        if isinstance(self.snapshot, Exception):
            raise self.snapshot
        return self.snapshot


class OneOfficialAdapter:
    source_id = "official:m13-fixture"
    source_url = "https://careers.example.com/jobs"

    def __init__(self) -> None:
        self.stub = JobStub(
            source_id=self.source_id,
            source_job_id="m13-100",
            company="示例科技",
            title="AI Agent 校招工程师",
            locations=["上海"],
            job_type="campus",
            published_at=datetime(2026, 8, 20, tzinfo=UTC),
            detail_url="https://careers.example.com/jobs/m13-100",
            raw_content=(
                "AI Agent 校招工程师。工作地点：上海。"
                "岗位职责：负责模型评测平台。任职要求：熟悉 Python 和数据库。"
            ),
        )

    async def list_jobs(self) -> list[JobStub]:
        return [self.stub]

    async def fetch_job(self, source_job_id: str) -> JobStub:
        assert source_job_id == self.stub.source_job_id
        return self.stub


def _job_page_html() -> str:
    return """
    <html><head><title>AI 平台工程师</title></head><body>
      <h1>AI 平台工程师</h1>
      <p>招聘公司：正文科技。</p>
      <p>工作地点：杭州。</p>
      <p>2027 届校园招聘，岗位职责：负责 AI Agent 平台和服务接口。</p>
      <p>任职要求：熟悉 Python、数据库和分布式系统，有工程实践经验。</p>
    </body></html>
    """


def _dynamic_job_snapshot() -> BrowserPageSnapshot:
    return BrowserPageSnapshot(
        requested_url="https://careers.example.com/jobs/dynamic-1",
        final_url="https://careers.example.com/jobs/dynamic-1",
        title="动态渲染 AI 工程师",
        raw_html="""
        <html><head><title>动态渲染 AI 工程师</title></head><body>
          <h1>动态渲染 AI 工程师</h1>
          <p>招聘公司：浏览器科技。</p><p>工作地点：北京。</p>
          <p>岗位职责：负责 AI Agent 产品研发和模型评测。</p>
          <p>任职要求：熟悉 Python、LLM 和软件工程。</p>
        </body></html>
        """,
        visible_text=(
            "动态渲染 AI 工程师 招聘公司：浏览器科技。工作地点：北京。"
            "岗位职责：负责 AI Agent 产品研发和模型评测。"
            "任职要求：熟悉 Python、LLM 和软件工程。"
        ),
    )


@pytest.mark.asyncio
async def test_all_provider_types_implement_lead_only_contract() -> None:
    providers: list[LeadProviderContract] = [
        OfficialAdapterLeadProvider(OneOfficialAdapter()),
        ExternalAgentProvider(
            source_url="https://careers.example.com/jobs/agent-1",
            search_snippet="search-only",
            inferred_company="hint company",
            inferred_title="hint title",
            discovered_at=datetime(2026, 8, 24, tzinfo=UTC),
        ),
        ManualImportProvider(
            source_url="https://careers.example.com/jobs/manual-1",
        ),
    ]

    discovered = [await provider.discover() for provider in providers]

    assert [items[0].provider for items in discovered] == [
        LeadProvider.OFFICIAL_ADAPTER,
        LeadProvider.EXTERNAL_AGENT,
        LeadProvider.MANUAL_URL,
    ]
    assert discovered[1][0].search_snippet == "search-only"
    assert discovered[1][0].discovered_at == datetime(2026, 8, 24, tzinfo=UTC)


@pytest.mark.asyncio
async def test_search_snippet_and_hints_never_become_posting_facts(db_session) -> None:
    service = JobLeadService(db_session)
    lead = service.create_lead(
        user_id="pollution-user",
        provider=LeadProvider.EXTERNAL_AGENT,
        source_url="https://careers.example.com/jobs/clean-1",
        company_hint="摘要伪造公司",
        title_hint="摘要伪造岗位",
        search_snippet="摘要声称工作地点火星、要求 Rust、仅招 2099 届。",
    )

    result = await service.verify_url(
        user_id="pollution-user",
        lead_id=lead.id,
        reader=MappingHTMLReader(
            _job_page_html(),
            final_url="https://careers.example.com/jobs/clean-1",
        ),
        official_hosts={"careers.example.com"},
    )
    verification = db_session.scalar(select(LeadVerification))

    assert result.posting.company == "正文科技"
    assert result.posting.title == "AI 平台工程师"
    assert result.posting.locations == ["杭州"]
    assert result.posting.job_type == "campus"
    assert "火星" not in result.posting.raw_content
    assert verification.field_evidence["graduation_years"][0]["value"] == "2027"
    assert verification.field_evidence["requirements"]
    assert "search_snippet" not in verification.field_evidence


@pytest.mark.asyncio
async def test_concurrent_verification_has_one_owner_and_one_audit(db_session) -> None:
    service = JobLeadService(db_session)
    lead = service.create_lead(
        user_id="concurrent-user",
        provider=LeadProvider.EXTERNAL_AGENT,
        source_url="https://careers.example.com/jobs/concurrent-1",
    )
    reader = BlockingReader(
        _job_page_html(),
        final_url="https://careers.example.com/jobs/concurrent-1",
    )
    first = asyncio.create_task(
        service.verify_url(
            user_id="concurrent-user",
            lead_id=lead.id,
            reader=reader,
            official_hosts={"careers.example.com"},
        )
    )
    await reader.entered.wait()

    with pytest.raises(JobLeadStateError):
        await service.verify_url(
            user_id="concurrent-user",
            lead_id=lead.id,
            reader=reader,
            official_hosts={"careers.example.com"},
        )

    reader.release.set()
    await first
    assert db_session.scalar(select(func.count(LeadVerification.id))) == 1
    assert db_session.scalar(select(func.count(JobPosting.id))) == 1


@pytest.mark.asyncio
async def test_browser_handoff_is_read_only_verified_and_audited(db_session) -> None:
    service = JobLeadService(db_session)
    lead = service.create_lead(
        user_id="browser-user",
        provider=LeadProvider.EXTERNAL_AGENT,
        source_url="https://careers.example.com/jobs/dynamic-1",
    )
    browser = FakeBrowserReader(_dynamic_job_snapshot())

    result = await service.verify_browser(
        user_id="browser-user",
        lead_id=lead.id,
        reader=browser,
        official_hosts={"careers.example.com"},
    )
    verification = db_session.scalar(select(LeadVerification))

    assert browser.calls == ["https://careers.example.com/jobs/dynamic-1"]
    assert result.posting.source_type == "verified_browser"
    assert result.posting.verification_status == "VERIFIED_OFFICIAL"
    assert verification.field_evidence["browser"]["mode"] == "read_only"


@pytest.mark.asyncio
async def test_browser_handoff_stops_at_login_or_security_gate(db_session) -> None:
    service = JobLeadService(db_session)
    lead = service.create_lead(
        user_id="browser-user",
        provider=LeadProvider.EXTERNAL_AGENT,
        source_url="https://careers.example.com/jobs/gated-1",
    )
    browser = FakeBrowserReader(
        BrowserReadError("需要登录", code="browser_login_required")
    )

    with pytest.raises(LeadVerificationFailure):
        await service.verify_browser(
            user_id="browser-user",
            lead_id=lead.id,
            reader=browser,
            official_hosts={"careers.example.com"},
        )

    blocked = service.get_lead(user_id="browser-user", lead_id=lead.id)
    assert blocked.status == JobLeadStatus.NEEDS_USER.value
    assert blocked.failure_code == "browser_login_required"
    assert db_session.scalar(select(func.count(JobPosting.id))) == 0


@pytest.mark.asyncio
async def test_browser_reader_rejects_private_url_before_launch() -> None:
    reader = PlaywrightBrowserJobReader(
        safety_checker=URLSafetyChecker(
            resolver=lambda _host, _port: ["127.0.0.1"]
        )
    )

    with pytest.raises(BrowserReadError) as captured:
        await reader.read("https://careers.example.com/jobs/private")

    assert captured.value.code == "unsafe_url"


@pytest.mark.asyncio
async def test_read_failures_progress_unknown_to_stale_never_closed(db_session) -> None:
    result = await DiscoveryService(db_session, OneOfficialAdapter()).run(
        user_id="availability-user"
    )
    job_id = result.job_posting_ids[0]
    service = JobAvailabilityService(db_session)

    statuses = [
        (
            await service.check_url(
                user_id="availability-user",
                job_posting_id=job_id,
                reader=FailingReader(),
            )
        ).result_status
        for _ in range(3)
    ]
    posting = db_session.get(JobPosting, job_id)

    assert statuses == ["UNKNOWN", "UNKNOWN", "STALE"]
    assert posting.availability_status == JobAvailabilityStatus.STALE.value
    assert posting.availability_failure_count == 3
    assert posting.closed_at is None
    assert db_session.scalar(select(func.count(JobAvailabilityCheck.id))) == 3


@pytest.mark.asyncio
async def test_only_explicit_evidence_or_human_confirmation_closes_job(db_session) -> None:
    result = await DiscoveryService(db_session, OneOfficialAdapter()).run(
        user_id="close-user"
    )
    job_id = result.job_posting_ids[0]
    service = JobAvailabilityService(db_session)

    explicit = await service.check_url(
        user_id="close-user",
        job_posting_id=job_id,
        reader=MappingHTMLReader(
            "<html><body><h1>AI Agent 校招工程师</h1><p>该职位已关闭，不再接受投递。</p></body></html>",
            final_url="https://careers.example.com/jobs/m13-100",
        ),
    )
    reopened = service.confirm(
        user_id="close-user",
        job_posting_id=job_id,
        status=JobAvailabilityStatus.ACTIVE,
        reason="招聘负责人确认岗位重新开放",
    )
    confirmed_closed = service.confirm(
        user_id="close-user",
        job_posting_id=job_id,
        status=JobAvailabilityStatus.CLOSED,
        reason="公司招聘页面负责人确认停止招聘",
    )

    assert explicit.result_status == "CLOSED"
    assert explicit.evidence_type == "explicit_closed"
    assert reopened.result_status == "ACTIVE"
    assert confirmed_closed.result_status == "CLOSED"
    assert confirmed_closed.evidence_type == "human_confirmation"


def test_browser_and_availability_apis_are_user_scoped(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(app)
    lead = client.post(
        "/api/discovery/leads",
        headers={"X-User-ID": "api-owner"},
        json={
            "provider": "external_agent",
            "source_url": "https://careers.example.com/jobs/dynamic-1",
            "search_snippet": "untrusted",
            "discovered_at": "2026-08-24T10:00:00Z",
        },
    ).json()
    monkeypatch.setattr(
        discovery_api,
        "create_browser_reader",
        lambda: FakeBrowserReader(_dynamic_job_snapshot()),
    )
    monkeypatch.setattr(
        discovery_api,
        "enabled_company_source_hosts",
        lambda: {"careers.example.com"},
    )

    denied = client.post(
        f"/api/discovery/leads/{lead['id']}/handoff/browser",
        headers={"X-User-ID": "api-other"},
    )
    verified = client.post(
        f"/api/discovery/leads/{lead['id']}/handoff/browser",
        headers={"X-User-ID": "api-owner"},
    )
    job_id = verified.json()["job_posting_id"]
    denied_history = client.get(
        f"/api/jobs/{job_id}/availability/checks",
        headers={"X-User-ID": "api-other"},
    )
    confirmed = client.post(
        f"/api/jobs/{job_id}/availability/confirm",
        headers={"X-User-ID": "api-owner"},
        json={"status": "CLOSED", "reason": "用户已在官方页面确认岗位关闭"},
    )

    assert denied.status_code == 404
    assert verified.status_code == 200
    assert denied_history.status_code == 404
    assert confirmed.status_code == 200
    assert confirmed.json()["result_status"] == "CLOSED"
