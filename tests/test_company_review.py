import json
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import select

from src.api import company_sources as api
from src.domain.company_source import DiscoveredCompany
from src.domain.discovery import LeadVerification
from src.main import app
from src.services.company_discovery import CompanyDiscoveryAgent
from src.services.company_registry import (
    enabled_company_source_hosts,
    enabled_company_sources,
)
from src.services.company_review import review_revision
from src.services.job_lead_service import JobLeadService
from src.services.lead_providers import LeadProviderKind
from src.services.url_reader import URLSafetyChecker

HOME = "https://nova.example/"
CAREER = "https://app.mokahr.com/campus-recruitment/nova/100"


def candidate(session):
    row = DiscoveredCompany(user_id="owner", company="Nova", homepage_url=HOME, career_url=HOME + "old",
        reason="未读到独立来源", discovered_query="北京上海 Agent RAG 校招", discovery_run_id="run",
        evidence={"discovered_urls": [HOME], "homepage": {"url": HOME}})
    session.add(row)
    session.commit()
    return row


def payload(row, **overrides):
    return {"homepage_url": HOME, "career_url": CAREER, "confirmed": True,
            "expected_revision": review_revision(row), **overrides}


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    monkeypatch.setattr(api, "confirmation_checker", lambda: URLSafetyChecker(resolver=lambda *_: ["8.8.8.8"]))


@pytest.mark.asyncio
async def test_manual_confirmation_keeps_provenance_private_and_tenant_scoped(db_session):
    row = candidate(db_session)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(f"/api/discovery/companies/{row.id}/confirm", headers={"X-User-ID": "owner"}, json=payload(row))
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["status"] == "manually_confirmed" and result["verification_method"] == "manual"
        assert (await client.get("/api/discovery/companies", headers={"X-User-ID":"stranger"})).json() == []
    db_session.refresh(row)
    assert row.evidence["manual_confirmation"]["automatic_reason"] == "未读到独立来源"
    assert row.evidence["manual_confirmation"]["previous_career_url"] == HOME + "old"
    assert "hiring_link" not in row.evidence
    own = enabled_company_sources(session=db_session, user_id="owner")
    assert next(s for s in own if s.id == row.id).verification_method == "manual"
    assert "app.mokahr.com" not in enabled_company_source_hosts(session=db_session, user_id="owner")
    service = JobLeadService(db_session)
    lead = service.create_lead(user_id="owner", provider=LeadProviderKind.EXTERNAL_AGENT, source_url=CAREER + "/jobs/1")
    service._prepare_official_transport(lead, object(), set())
    proof = db_session.scalar(select(LeadVerification).where(LeadVerification.lead_id == lead.id))
    assert proof.source_type == "user_confirmed_company"
    assert proof.field_evidence["verification_method"] == "manual"
    hosts = enabled_company_source_hosts(session=db_session, user_id="owner")
    assert service._official_target(lead, lead.source_url, hosts)
    assert not service._official_target(lead, "https://app.mokahr.com/campus-recruitment/other/100/jobs/1", hosts)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    {"confirmed":False}, {"confirmed":1}, {"confirmed":"true"},
    {"homepage_url":"https://localhost/"}, {"career_url":"http://127.0.0.1/"},
    {"career_url":"https://app.mokahr.com/"}, {"career_url":"https://zhipin.com/"},
    {"career_url":"https://name:password@example.com/"},
])
async def test_confirmation_requires_explicit_ack_and_public_employer_scope(db_session, change):
    row = candidate(db_session)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(f"/api/discovery/companies/{row.id}/confirm", headers={"X-User-ID":"owner"}, json=payload(row, **change))
        assert response.status_code == 422, response.text
    db_session.refresh(row)
    assert row.status == "pending"


@pytest.mark.asyncio
async def test_stale_and_other_user_cannot_confirm_or_overwrite(db_session):
    row = candidate(db_session)
    old = payload(row)
    row.last_checked_at = datetime.now(UTC)
    db_session.commit()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.post(f"/api/discovery/companies/{row.id}/confirm", headers={"X-User-ID":"stranger"}, json=payload(row))).status_code == 404
        assert (await client.post(f"/api/discovery/companies/{row.id}/confirm", headers={"X-User-ID":"owner"}, json=old)).status_code == 409
        current = payload(row)
        assert (await client.post(f"/api/discovery/companies/{row.id}/confirm", headers={"X-User-ID":"owner"}, json=current)).status_code == 200
        assert (await client.post(f"/api/discovery/companies/{row.id}/confirm", headers={"X-User-ID":"owner"}, json=current)).status_code == 409


@pytest.mark.asyncio
async def test_auto_finish_cannot_overwrite_a_manual_confirmation(db_session):
    row = candidate(db_session)
    row.status, row.evidence = "manually_confirmed", {"manual_confirmation": {"confirmed_by":"owner"}}
    db_session.commit()
    worker = CompanyDiscoveryAgent(db_session,user_id="owner",run_id="run",query="",reader=None,
        provider_factory=None,client_factory=None,on_event=lambda *_:None)
    worker.active_row = row
    row.status, row.reason = "verified", "stale automatic result"
    worker.finish(row, "automatic")
    worker.save_read_progress()
    db_session.refresh(row)
    assert row.status == "manually_confirmed" and row.reason == "未读到独立来源"
    assert json.loads(json.dumps(row.evidence)) == {"manual_confirmation":{"confirmed_by":"owner"}}
