from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from src.api import discovery as discovery_api
from src.domain.application import CandidateJob
from src.domain.discovery import (
    JobLead,
    JobLeadStatus,
    LeadProvider,
    LeadVerification,
)
from src.domain.job import (
    JobAvailabilityStatus,
    JobPosting,
    JobVerificationStatus,
)
from src.main import app
from src.services.discovery_service import DiscoveryService
from src.services.discovery_sources import JobStub
from src.services.job_lead_service import JobLeadService, LeadVerificationFailure
from src.services.url_reader import FetchedResponse


class OneJobAdapter:
    source_id = "official:test"
    source_url = "https://careers.example.com/jobs"

    def __init__(self) -> None:
        self.job = JobStub(
            source_id=self.source_id,
            source_job_id="job-1001",
            company="示例科技",
            title="AI Agent 校招工程师",
            locations=["上海"],
            job_type="campus",
            published_at=datetime(2026, 8, 20, tzinfo=UTC),
            detail_url="https://careers.example.com/jobs/job-1001#detail",
            raw_content=(
                "岗位职责：负责 AI Agent 执行链路、评测系统和服务开发。"
                "任职要求：熟悉 Python、LLM 应用开发和基础软件工程实践。"
            ),
        )

    async def list_jobs(self) -> list[JobStub]:
        return [self.job]

    async def fetch_job(self, source_job_id: str) -> JobStub:
        assert source_job_id == self.job.source_job_id
        return self.job


class HTMLReader:
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


def job_page_html() -> str:
    return """
    <html><head><title>AI Agent 校招工程师</title></head><body>
      <h1>AI Agent 校招工程师</h1>
      <p>岗位职责：负责 AI Agent 执行链路、模型评测平台、服务接口和线上质量建设。</p>
      <p>任职要求：熟悉 Python、LLM 应用开发、数据库和常见软件工程实践，能够参与校园招聘项目交付。</p>
      <p>工作地点：上海。欢迎符合条件的应届毕业生投递。</p>
    </body></html>
    """


@pytest.mark.asyncio
async def test_official_discovery_persists_lead_verification_before_candidate(
    db_session,
) -> None:
    result = await DiscoveryService(db_session, OneJobAdapter()).run(
        user_id="user-lead"
    )

    lead = db_session.scalar(select(JobLead))
    posting = db_session.get(JobPosting, result.job_posting_ids[0])
    verification = db_session.scalar(select(LeadVerification))
    candidate = db_session.scalar(select(CandidateJob))

    assert lead is not None
    assert lead.discovery_run_id == result.run.id
    assert lead.provider == LeadProvider.OFFICIAL_ADAPTER.value
    assert lead.status == JobLeadStatus.VERIFIED.value
    assert lead.job_posting_id == posting.id
    assert verification is not None
    assert verification.lead_id == lead.id
    assert verification.result == JobLeadStatus.VERIFIED.value
    assert posting.verification_status == JobVerificationStatus.VERIFIED_OFFICIAL.value
    assert posting.availability_status == JobAvailabilityStatus.ACTIVE.value
    assert posting.first_seen_at is not None
    assert posting.last_verified_at is not None
    assert candidate.job_posting_id == posting.id


def test_external_lead_is_idempotent_and_does_not_create_job(db_session) -> None:
    service = JobLeadService(db_session)
    first = service.create_lead(
        user_id="user-lead",
        provider=LeadProvider.EXTERNAL_AGENT,
        source_url="https://careers.example.com/jobs/123#overview",
        company_hint="示例科技",
        title_hint="AI 工程师",
        search_snippet="网页搜索发现的岗位摘要，只作为待验证线索。",
    )
    second = service.create_lead(
        user_id="user-lead",
        provider=LeadProvider.EXTERNAL_AGENT,
        source_url="https://careers.example.com/jobs/123",
    )

    assert second.id == first.id
    assert first.status == JobLeadStatus.NEW.value
    assert db_session.scalar(select(func.count(JobPosting.id))) == 0
    assert db_session.scalar(select(func.count(CandidateJob.id))) == 0


@pytest.mark.asyncio
async def test_external_official_url_is_verified_before_job_creation(db_session) -> None:
    service = JobLeadService(db_session)
    lead = service.create_lead(
        user_id="user-lead",
        provider=LeadProvider.EXTERNAL_AGENT,
        source_url="https://careers.example.com/jobs/123",
        company_hint="示例科技",
    )

    result = await service.verify_url(
        user_id="user-lead",
        lead_id=lead.id,
        reader=HTMLReader(
            job_page_html(),
            final_url="https://careers.example.com/jobs/123",
        ),
        official_hosts={"careers.example.com"},
    )

    assert result.lead.status == JobLeadStatus.VERIFIED.value
    assert result.posting.verification_status == (
        JobVerificationStatus.VERIFIED_OFFICIAL.value
    )
    assert result.posting.availability_status == JobAvailabilityStatus.ACTIVE.value
    assert db_session.scalar(select(func.count(LeadVerification.id))) == 1
    assert db_session.scalar(select(func.count(CandidateJob.id))) == 1


@pytest.mark.asyncio
async def test_repeated_verification_is_idempotent(db_session) -> None:
    service = JobLeadService(db_session)
    lead = service.create_lead(
        user_id="user-lead",
        provider=LeadProvider.EXTERNAL_AGENT,
        source_url="https://careers.example.com/jobs/123",
    )
    reader = HTMLReader(
        job_page_html(),
        final_url="https://careers.example.com/jobs/123",
    )

    first = await service.verify_url(
        user_id="user-lead",
        lead_id=lead.id,
        reader=reader,
        official_hosts={"careers.example.com"},
    )
    second = await service.verify_url(
        user_id="user-lead",
        lead_id=lead.id,
        reader=reader,
        official_hosts={"careers.example.com"},
    )

    assert second.lead.status == JobLeadStatus.VERIFIED.value
    assert second.posting.id == first.posting.id
    assert second.posting_created is False
    assert db_session.scalar(select(func.count(LeadVerification.id))) == 1
    assert db_session.scalar(select(func.count(JobPosting.id))) == 1
    assert db_session.scalar(select(func.count(CandidateJob.id))) == 1


@pytest.mark.asyncio
async def test_non_job_page_is_rejected_without_formal_job(db_session) -> None:
    service = JobLeadService(db_session)
    lead = service.create_lead(
        user_id="user-lead",
        provider=LeadProvider.THIRD_PARTY,
        source_url="https://careers.example.com/guide",
    )

    with pytest.raises(LeadVerificationFailure) as captured:
        await service.verify_url(
            user_id="user-lead",
            lead_id=lead.id,
            reader=HTMLReader(
                "<html><title>招聘指南</title><body>了解招聘流程和公司文化。</body></html>",
                final_url="https://careers.example.com/guide",
            ),
            official_hosts={"careers.example.com"},
        )

    assert captured.value.code == "lead_not_job_page"
    rejected = service.get_lead(user_id="user-lead", lead_id=lead.id)
    assert rejected.status == JobLeadStatus.REJECTED_NON_JOB.value
    assert rejected.failure_code == "lead_not_job_page"
    assert db_session.scalar(select(func.count(JobPosting.id))) == 0
    assert db_session.scalar(select(func.count(CandidateJob.id))) == 0
    assert db_session.scalar(select(func.count(LeadVerification.id))) == 1


def test_manual_handoff_completes_lead_without_claiming_source_verification(
    db_session,
) -> None:
    service = JobLeadService(db_session)
    lead = service.create_lead(
        user_id="user-lead",
        provider=LeadProvider.MANUAL_URL,
        source_url="https://careers.example.com/jobs/dynamic-123",
        company_hint="示例科技",
        title_hint="AI Agent 工程师",
    )

    result = service.complete_manual_handoff(
        user_id="user-lead",
        lead_id=lead.id,
        raw_content=(
            "岗位职责：负责 AI Agent 执行链路和模型评测平台建设。"
            "任职要求：熟悉 Python、LLM 应用开发和数据库。"
        ),
        locations=["上海"],
        job_type="campus",
    )

    assert result.lead.status == JobLeadStatus.VERIFIED.value
    assert result.lead.next_action == "open_job"
    assert result.posting.verification_status == JobVerificationStatus.USER_PROVIDED.value
    assert result.posting.availability_status == JobAvailabilityStatus.UNKNOWN.value
    assert result.posting.source_type == "manual_handoff"
    verification = db_session.scalar(select(LeadVerification))
    assert verification.source_type == "manual_handoff"
    assert verification.field_evidence["verification_status"] == "USER_PROVIDED"
    assert db_session.scalar(select(func.count(CandidateJob.id))) == 1


@pytest.mark.asyncio
async def test_manual_handoff_cannot_downgrade_existing_official_posting(
    db_session,
) -> None:
    discovery = await DiscoveryService(db_session, OneJobAdapter()).run(
        user_id="user-lead"
    )
    posting = db_session.get(JobPosting, discovery.job_posting_ids[0])
    original_content = posting.raw_content
    original_source_id = posting.source_id
    lead = JobLeadService(db_session).create_lead(
        user_id="user-lead",
        provider=LeadProvider.MANUAL_URL,
        source_url="https://careers.example.com/jobs/job-1001",
    )

    result = JobLeadService(db_session).complete_manual_handoff(
        user_id="user-lead",
        lead_id=lead.id,
        raw_content="用户粘贴的内容可能不完整，因此不能覆盖已经验证的官方岗位正文和来源字段。",
        company="错误公司提示",
        title="错误岗位提示",
    )

    assert result.lead.status == JobLeadStatus.DUPLICATE.value
    assert result.posting.id == posting.id
    assert result.posting.verification_status == (
        JobVerificationStatus.VERIFIED_OFFICIAL.value
    )
    assert result.posting.availability_status == JobAvailabilityStatus.ACTIVE.value
    assert result.posting.source_id == original_source_id
    assert result.posting.raw_content == original_content
    assert result.posting.company == "示例科技"
    assert db_session.scalar(select(func.count(JobPosting.id))) == 1
    assert db_session.scalar(select(func.count(CandidateJob.id))) == 1


def test_job_lead_api_is_user_scoped(db_session) -> None:
    client = TestClient(app)
    created = client.post(
        "/api/discovery/leads",
        headers={"X-User-ID": "owner"},
        json={
            "provider": "external_agent",
            "source_url": "https://careers.example.com/jobs/123#detail",
            "company_hint": "示例科技",
            "title_hint": "AI 工程师",
            "search_snippet": "搜索结果摘要",
        },
    )

    assert created.status_code == 201
    lead_id = created.json()["id"]
    assert created.json()["status"] == "NEW"
    assert created.json()["normalized_url"] == (
        "https://careers.example.com/jobs/123"
    )
    assert client.get(
        "/api/discovery/leads",
        headers={"X-User-ID": "other"},
    ).json() == []
    assert client.get(
        f"/api/discovery/leads/{lead_id}",
        headers={"X-User-ID": "other"},
    ).status_code == 404


def test_job_lead_api_verifies_url_and_returns_audit_history(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(app)
    created = client.post(
        "/api/discovery/leads",
        headers={"X-User-ID": "owner"},
        json={
            "provider": "external_agent",
            "source_url": "https://careers.example.com/jobs/123",
        },
    )
    lead_id = created.json()["id"]
    monkeypatch.setattr(
        discovery_api,
        "create_lead_reader",
        lambda: HTMLReader(
            job_page_html(),
            final_url="https://careers.example.com/jobs/123",
        ),
    )
    monkeypatch.setattr(
        discovery_api,
        "enabled_company_source_hosts",
        lambda: {"careers.example.com"},
    )

    verified = client.post(
        f"/api/discovery/leads/{lead_id}/verify",
        headers={"X-User-ID": "owner"},
    )

    assert verified.status_code == 200
    assert verified.json()["status"] == "VERIFIED"
    assert verified.json()["job_posting_id"]
    assert len(verified.json()["verifications"]) == 1
    posting = db_session.get(JobPosting, verified.json()["job_posting_id"])
    assert posting.verification_status == JobVerificationStatus.VERIFIED_OFFICIAL.value


def test_manual_handoff_api_is_user_scoped_and_audited(db_session) -> None:
    client = TestClient(app)
    created = client.post(
        "/api/discovery/leads",
        headers={"X-User-ID": "owner"},
        json={
            "provider": "manual_url",
            "source_url": "https://careers.example.com/jobs/dynamic-123",
            "company_hint": "示例科技",
            "title_hint": "AI Agent 工程师",
        },
    )
    lead_id = created.json()["id"]
    payload = {
        "raw_content": (
            "岗位职责：负责 AI Agent 产品研发与评测。"
            "任职要求：熟悉 Python、LLM 和软件工程。"
        ),
        "locations": ["上海"],
        "job_type": "campus",
    }

    denied = client.post(
        f"/api/discovery/leads/{lead_id}/handoff/manual-jd",
        headers={"X-User-ID": "other"},
        json=payload,
    )
    completed = client.post(
        f"/api/discovery/leads/{lead_id}/handoff/manual-jd",
        headers={"X-User-ID": "owner"},
        json=payload,
    )

    assert denied.status_code == 404
    assert completed.status_code == 200
    assert completed.json()["status"] == "VERIFIED"
    assert completed.json()["next_action"] == "open_job"
    assert len(completed.json()["verifications"]) == 1
    posting = db_session.get(JobPosting, completed.json()["job_posting_id"])
    assert posting.verification_status == JobVerificationStatus.USER_PROVIDED.value
    assert posting.availability_status == JobAvailabilityStatus.UNKNOWN.value
