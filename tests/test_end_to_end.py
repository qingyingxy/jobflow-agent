from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from src.api import applications as applications_api
from src.api import discovery as discovery_api
from src.api import jobs as jobs_api
from src.config import Settings
from src.main import app
from src.services.discovery_sources import JobStub

RAW_MANUAL_JD = "示例公司招聘 AI 应用开发实习生，熟悉 RAG，工作地点为北京。"
RAW_DISCOVERY_JD = "目标公司招聘 Python 后端开发实习生，要求 Python，工作地点上海。"


def fake_settings() -> Settings:
    return Settings(
        structured_model_provider="fake",
        prompt_version="e2e-prompt-v1",
        parser_version="e2e-parser-v1",
    )


@pytest.mark.asyncio
async def test_manual_jd_to_approved_application_timeline(monkeypatch) -> None:
    settings = fake_settings()
    monkeypatch.setattr(jobs_api, "get_settings", lambda: settings)
    monkeypatch.setattr(applications_api, "get_settings", lambda: settings)
    headers = {"X-User-ID": "e2e-manual-user"}
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        profile = await client.put(
            "/api/profile",
            headers=headers,
            json={
                "graduation_year": 2027,
                "degree": "硕士",
                "major": "计算机科学",
                "search_preferences": {
                    "preferred_locations": ["北京"],
                    "job_types": ["internship"],
                },
            },
        )
        evidence = await client.post(
            "/api/evidence",
            headers=headers,
            json={
                "type": "project",
                "title": "RAG 项目",
                "claim": "在项目中实现 RAG 应用。",
                "skills": ["RAG"],
                "source": "e2e_fixture",
            },
        )
        imported = await client.post(
            "/api/jobs/import-text",
            json={"raw_content": RAW_MANUAL_JD},
        )
        job_id = imported.json()["id"]
        analysis = await client.post(
            f"/api/jobs/{job_id}/analyze",
            headers=headers,
        )
        candidate = await client.post(
            "/api/candidates",
            headers=headers,
            json={"job_posting_id": job_id},
        )
        candidate_id = candidate.json()["id"]
        application = await client.post(
            f"/api/candidates/{candidate_id}/prepare-application",
            headers=headers,
        )
        application_id = application.json()["id"]
        suggestion = await client.post(
            f"/api/applications/{application_id}/suggestions",
            headers=headers,
            json={
                "original_text": "我参与了一个项目。",
                "target_type": "project_bullet",
                "target_label": "RAG 项目经历",
            },
        )
        decided = await client.post(
            f"/api/suggestions/{suggestion.json()['id']}/decide",
            headers=headers,
            json={"decision": "accept"},
        )
        submitted = await client.patch(
            f"/api/applications/{application_id}/status",
            headers=headers,
            json={"status": "SUBMITTED", "next_action": "等待反馈"},
        )
        events = await client.get(
            f"/api/applications/{application_id}/events",
            headers=headers,
        )

    assert profile.status_code == 200
    assert evidence.status_code == 201
    assert imported.status_code == 201
    assert analysis.status_code == 200
    assert analysis.json()["matches"][0]["support_level"] == "supported"
    assert candidate.status_code == 201
    assert application.status_code == 201
    assert suggestion.status_code == 201
    assert decided.status_code == 200
    assert decided.json()["status"] == "ACCEPTED"
    assert decided.json()["final_text"]
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "SUBMITTED"
    assert events.status_code == 200
    assert [item["event_type"] for item in events.json()] == [
        "ApplicationCreated",
        "SuggestionCreated",
        "SuggestionDecisionRecorded",
        "ApplicationStatusChanged",
    ], events.json()


class FixtureDiscoveryAdapter:
    source_id = "greenhouse:e2e-fixture"
    source_url = "https://boards.greenhouse.io/e2e-fixture"

    async def list_jobs(self) -> list[JobStub]:
        return [
            JobStub(
                source_id=self.source_id,
                source_job_id="1001",
                company="目标公司",
                title="Python 后端开发实习生",
                locations=["上海"],
                job_type="internship",
                published_at=datetime.now(UTC),
                detail_url="https://boards.greenhouse.io/e2e-fixture/jobs/1001",
                raw_content=RAW_DISCOVERY_JD,
            )
        ]

    async def fetch_job(self, source_job_id: str) -> JobStub:
        jobs = await self.list_jobs()
        if source_job_id != jobs[0].source_job_id:
            raise LookupError(source_job_id)
        return jobs[0]


@pytest.mark.asyncio
async def test_discovery_pool_to_analysis(monkeypatch) -> None:
    settings = fake_settings()
    monkeypatch.setattr(jobs_api, "get_settings", lambda: settings)
    monkeypatch.setattr(
        discovery_api,
        "create_greenhouse_adapter",
        lambda source_url, company=None: FixtureDiscoveryAdapter(),
    )
    headers = {"X-User-ID": "e2e-discovery-user"}
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        discovery_run = await client.post(
            "/api/discovery/runs",
            headers=headers,
            json={"source_url": "https://boards.greenhouse.io/e2e-fixture"},
        )
        candidates = await client.get(
            "/api/candidates?status=DISCOVERED",
            headers=headers,
        )
        job_id = candidates.json()[0]["job_posting_id"]
        analysis = await client.post(
            f"/api/jobs/{job_id}/analyze",
            headers=headers,
        )

    assert discovery_run.status_code == 201
    assert discovery_run.json()["status"] == "SUCCEEDED"
    assert discovery_run.json()["new_count"] == 1
    assert candidates.status_code == 200
    assert len(candidates.json()) == 1
    assert analysis.status_code == 200
    assert analysis.json()["job"]["source_id"] == "greenhouse:e2e-fixture"
    assert analysis.json()["structured_jd"]["job_type"] == "internship"
