import asyncio
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from src.config import Settings
from src.domain.discovery import DiscoveryRun, JobLead, LeadProvider
from src.main import app
from src.services.discovery_matching import (
    classify_discovery_job,
    search_filter_conditions,
)
from src.services.discovery_service import DiscoveryService
from src.services.discovery_sources import JobStub
from src.services.job_lead_service import JobLeadService
from src.services.lead_providers import LeadCandidate
from src.services.search_pipeline import run_search_pipeline
from src.services.search_planner import SearchTask

BASE = JobStub(
    source_id="fixture",
    source_job_id="1",
    company="示例公司",
    title="后端工程师",
    locations=["上海"],
    job_type="campus",
    published_at=None,
    detail_url="https://example.com/jobs/1",
    raw_content="面向2027届毕业生。负责后端 Python 开发。",
)
QUERY = "2027届上海 Python 后端校招，不考虑北京"


@pytest.mark.parametrize(
    "changes,status",
    [
        ({}, "matched"),
        ({"locations": ["北京"]}, "excluded"),
        ({"locations": ["杭州"]}, "excluded"),
        ({"locations": []}, "pending"),
        ({"locations": ["全国"]}, "pending"),
        ({"job_type": "unknown"}, "pending"),
        ({"job_type": "full_time"}, "excluded"),
        ({"raw_content": "2027校园招聘。负责后端 Python 开发。"}, "pending"),
        ({"raw_content": "2026-10-08发布。负责后端 Python 开发。"}, "pending"),
        ({"raw_content": "面向2026届毕业生。负责后端 Python 开发。"}, "excluded"),
        (
            {
                "raw_content": "2027届国内毕业生，2026届海外毕业生。负责后端 Python 开发。"
            },
            "pending",
        ),
        (
            {
                "raw_content": "面向2027届毕业生。面向2026届毕业生。负责后端 Python 开发。"
            },
            "pending",
        ),
        ({"title": "研发工程师", "raw_content": "面向2027届毕业生。"}, "pending"),
    ],
)
def test_filter_distinguishes_conflicts_from_missing_information(changes, status):
    job = replace(BASE, **changes)
    match = classify_discovery_job(job, query=QUERY)
    assert match.filter_status == status
    assert match.checks
    assert all(check["source_url"] == job.detail_url for check in match.checks)
    for check in match.checks:
        if check["field"] in {"role", "keyword", "graduation_year"}:
            assert all(
                quote in job.raw_content or quote in job.title
                for quote in check["evidence"]
            )


def test_unrecognized_constraints_are_not_silently_passed():
    assert (
        classify_discovery_job(
            BASE, query="上海 Rust 后端校招，月薪30k，硕士不限专业"
        ).filter_status
        == "pending"
    )
    assert search_filter_conditions("上海 Rust 后端校招，月薪30k")["keywords"] == [
        "rust"
    ]
    assert (
        classify_discovery_job(
            BASE, query="2027届上海后端校招，不考虑区块链"
        ).filter_status
        == "pending"
    )


@pytest.mark.asyncio
async def test_fast_verification_is_published_while_slow_verification_is_still_running():
    first_published = asyncio.Event()
    reports, completed = [], []
    active = peak = 0

    def candidate(number):
        return LeadCandidate(
            provider=LeadProvider.EXTERNAL_AGENT,
            source_url=f"https://example.com/jobs/{number}",
            discovered_at=datetime.now(UTC),
        )

    async def search(number, seen):
        return [candidate(i) for i in (1, 2, 3)]

    async def verify(lead):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            if lead.source_url.endswith("/1"):
                await asyncio.wait_for(first_published.wait(), 1)
            completed.append(lead.source_url)
            return lead.source_url, True
        finally:
            active -= 1

    def report(number, seen, useful, message, stop):
        reports.append(useful)
        if useful and not any(url.endswith("/1") for url in completed):
            first_published.set()

    await run_search_pipeline(
        search=search,
        verify=verify,
        report=report,
        canonicalize=lambda x: x,
        max_rounds=1,
        max_concurrency=2,
        verification_seconds=2,
    )
    assert first_published.is_set()
    assert completed[0].endswith("/2")
    assert peak == 2 and active == 0
    assert reports[-1] == 3


@pytest.mark.asyncio
async def test_default_official_search_never_constructs_resume_analysis(
    db_session, monkeypatch
):
    from src.services import official_search_service as execution

    class Adapter:
        source_id = "fixture"
        source_url = "https://example.com/jobs"

        async def list_jobs(self):
            return [BASE]

    def forbidden(*args, **kwargs):
        raise AssertionError(
            "Default search must not construct an analysis/model client"
        )

    monkeypatch.setattr(execution, "SessionLocal", sessionmaker(bind=db_session.bind))
    monkeypatch.setattr(execution, "enabled_company_sources", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        execution, "OfficialCompanyRegistryAdapter", lambda **kwargs: Adapter()
    )
    monkeypatch.setattr(execution, "get_settings", lambda: Settings(_env_file=None))
    monkeypatch.setattr(execution, "_analysis_dependencies", forbidden)
    run = DiscoveryService(db_session, Adapter()).create_run(
        user_id="owner", search_query=QUERY
    )
    await execution.execute_official_search(run_id=run.id, user_id="owner", query=QUERY)
    db_session.refresh(run)
    assert run.status == "SUCCEEDED"
    assert run.analysis_status == "NOT_REQUESTED"
    assert run.analysis_target_count == run.analysis_completed_count == 0
    assert run.result_matches[0]["filter_status"] == "matched"


@pytest.mark.asyncio
async def test_default_web_search_publishes_and_defers_with_retryable_status(
    db_session, monkeypatch
):
    from src.services import (
        multiround_search as execution,
    )
    from src.services import (
        official_search_service,
        web_search_service,
    )

    class Provider:
        source_id = "fixture"

        async def discover(self):
            self.last_evidence = {"raw_response": "fixture"}
            return [
                LeadCandidate(
                    provider=LeadProvider.EXTERNAL_AGENT,
                    source_url=f"https://example.com/jobs/{i}",
                    discovered_at=datetime.now(UTC),
                )
                for i in (1, 2)
            ]

    async def verify(service, *, user_id, lead_id, **kwargs):
        lead = service.get_lead(user_id=user_id, lead_id=lead_id)
        if lead.source_url.endswith("/1"):
            await asyncio.Event().wait()
        return service.verify_stub(
            user_id=user_id,
            lead_id=lead_id,
            stub=replace(BASE, source_job_id="2", detail_url=lead.source_url),
        )

    def forbidden(*args, **kwargs):
        raise AssertionError("Unexpected resume analysis")

    settings = Settings(
        _env_file=None,
        web_search_decision_mode="rule",
        web_search_max_rounds=1,
        web_search_budget_seconds=2,
        web_search_verification_budget_seconds=1,
        web_search_verification_item_seconds=2,
    )
    monkeypatch.setattr(execution, "SessionLocal", sessionmaker(bind=db_session.bind))
    monkeypatch.setattr(execution, "get_settings", lambda: settings)
    monkeypatch.setattr(
        execution, "enabled_company_source_hosts", lambda **kwargs: {"example.com"}
    )
    monkeypatch.setattr(execution, "enabled_company_sources", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        web_search_service, "create_web_search_provider", lambda *args: Provider()
    )
    monkeypatch.setattr(JobLeadService, "verify_url", verify)
    monkeypatch.setattr(official_search_service, "_analysis_dependencies", forbidden)
    run = DiscoveryRun(
        id="filter-run",
        user_id="owner",
        source="fixture",
        source_url="https://example.com",
        search_query=QUERY,
        started_at=datetime.now(UTC),
    )
    db_session.add(run)
    db_session.commit()
    task = asyncio.create_task(
        execution.execute_multiround_search(
            run_id=run.id,
            user_id="owner",
            query=QUERY,
            company_ids=[],
            query_tasks=[SearchTask(QUERY, "原始条件")],
        )
    )
    for _ in range(50):
        await asyncio.sleep(0.01)
        db_session.refresh(run)
        if run.result_matches:
            break
    assert run.result_matches[0]["filter_status"] == "matched"
    assert run.status == "RUNNING" and not task.done()
    await task
    db_session.expire_all()
    slow = db_session.scalar(select(JobLead).where(JobLead.source_url.endswith("/1")))
    assert slow.status == "DEFERRED"
    assert slow.next_action == "retry_verification"
    assert run.analysis_status == "NOT_REQUESTED"
    assert run.analysis_target_count == 0
    # Retrying the lead independently must update the current run's displayed results.
    JobLeadService(db_session).verify_stub(
        user_id="owner",
        lead_id=slow.id,
        stub=replace(BASE, raw_content=BASE.raw_content + "另一业务团队。"),
    )
    with TestClient(app) as client:
        response = client.get(
            f"/api/discovery/runs/{run.id}", headers={"X-User-ID": "owner"}
        )
        assert response.status_code == 200
        assert len(response.json()["result_matches"]) == 2
        assert response.json()["filter_conditions"]["graduation_years"] == [2027]
        assert (
            client.get(
                f"/api/discovery/runs/{run.id}", headers={"X-User-ID": "someone-else"}
            ).status_code
            == 404
        )
