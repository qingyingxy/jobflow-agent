from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import func, select

from src.domain.analysis import JobAnalysis
from src.domain.job import JobPosting
from src.domain.models import EvidenceItem, UserProfile
from src.domain.runs import AgentRun, JobParseResult
from src.infrastructure.llm_client import FakeModelClient, ModelTimeoutError
from src.main import app
from src.services.evidence_matcher import EvidenceMatcher
from src.services.evidence_service import EvidenceService
from src.services.jd_analysis_service import (
    AnalysisContentChangedError,
    JDAnalysisFailure,
    JDAnalysisService,
)
from src.services.jd_parser import JDParser
from src.services.job_parse_service import JobParseService

RAW_CONTENT = "示例公司招聘 AI 应用开发实习生，熟悉 RAG，工作地点为北京。"


def create_posting(db_session, job_id: str = "job_m07_test") -> JobPosting:
    posting = JobPosting(
        id=job_id,
        source_url="https://example.com/job/1",
        source_type="manual_text",
        company="示例公司",
        title="AI 应用开发实习生",
        raw_content=RAW_CONTENT,
        content_hash=hashlib.sha256(RAW_CONTENT.encode("utf-8")).hexdigest(),
        retrieved_at=datetime.now(UTC),
        trace_id=f"trace_{job_id}",
    )
    db_session.add(posting)
    db_session.commit()
    return posting


def valid_jd_output() -> dict[str, object]:
    return {
        "company": "示例公司",
        "title": "AI 应用开发实习生",
        "job_type": "internship",
        "locations": ["北京"],
        "required_skills": ["RAG"],
        "requirements": [
            {
                "category": "required_skill",
                "name": "RAG",
                "description": "熟悉 RAG",
                "mandatory": True,
                "evidence": [
                    {
                        "field_path": "requirements[0]",
                        "source_text": "熟悉 RAG",
                    }
                ],
            }
        ],
        "field_evidence": [
            {"field_path": "company", "source_text": "示例公司"},
            {"field_path": "title", "source_text": "AI 应用开发实习生"},
            {"field_path": "job_type", "source_text": "实习生"},
            {"field_path": "locations", "source_text": "北京"},
            {"field_path": "required_skills", "source_text": "熟悉 RAG"},
            {"field_path": "requirements[0]", "source_text": "熟悉 RAG"},
        ],
    }


def add_profile_and_evidence(db_session, evidence_id: str = "ev_m07") -> None:
    db_session.add(
        UserProfile(
            user_id="user-a",
            graduation_year=2027,
            degree="硕士",
            major="计算机科学",
            search_preferences={
                "preferred_locations": ["北京"],
                "job_types": ["internship"],
            },
        )
    )
    db_session.add(
        EvidenceItem(
            id=evidence_id,
            user_id="user-a",
            type="project",
            title="Memory-RAG",
            claim="在 Memory-RAG 项目中实现 RAG。",
            skills=["RAG"],
            source="resume_project_1",
        )
    )
    db_session.commit()


@pytest.mark.asyncio
async def test_parse_service_reuses_job_parse_result_and_records_cache_hit(
    db_session,
) -> None:
    posting = create_posting(db_session)
    parser = JDParser(FakeModelClient(output=valid_jd_output()))
    service = JobParseService(db_session, parser)

    first = await service.parse(user_id="user-a", job_id=posting.id)
    second = await service.parse(user_id="user-a", job_id=posting.id)

    assert first.parse_result.id == second.parse_result.id
    assert second.agent_run.validation_result["cache_hit"] is True
    assert db_session.scalar(select(func.count(JobParseResult.id))) == 1


@pytest.mark.asyncio
async def test_analysis_service_persists_user_scoped_result_and_risks(db_session) -> None:
    posting = create_posting(db_session)
    add_profile_and_evidence(db_session)
    parser = JDParser(FakeModelClient(output=valid_jd_output()))
    matcher = EvidenceMatcher(
        FakeModelClient(
            output={
                "support_level": "supported",
                "evidence_ids": ["ev_m07"],
                "explanation": "在 Memory-RAG 项目中实现 RAG。",
                "claims": ["RAG"],
            }
        )
    )

    execution = await JDAnalysisService(
        db_session,
        parser=parser,
        matcher=matcher,
    ).analyze(user_id="user-a", job_id=posting.id)

    assert execution.analysis.user_id == "user-a"
    assert execution.analysis.job_posting_id == posting.id
    assert execution.analysis.invalidated_at is None
    assert execution.analysis.matches[0]["support_level"] == "supported"
    assert execution.analysis.score["score"] is not None
    assert execution.agent_run_ids
    assert db_session.scalar(select(JobAnalysis)) is not None

    other_user = JDAnalysisService(db_session).latest(
        user_id="user-b",
        job_id=posting.id,
    )
    assert other_user is None


@pytest.mark.asyncio
async def test_profile_and_evidence_changes_invalidate_latest_analysis(db_session) -> None:
    posting = create_posting(db_session)
    add_profile_and_evidence(db_session)
    parser = JDParser(FakeModelClient(output=valid_jd_output()))
    matcher = EvidenceMatcher(
        FakeModelClient(
            output={
                "support_level": "supported",
                "evidence_ids": ["ev_m07"],
                "explanation": "在 Memory-RAG 项目中实现 RAG。",
                "claims": ["RAG"],
            }
        )
    )
    service = JDAnalysisService(db_session, parser=parser, matcher=matcher)
    execution = await service.analyze(user_id="user-a", job_id=posting.id)

    db_session.get(UserProfile, "user-a").major = "金融"
    from src.services.jd_analysis_service import invalidate_analyses_for_user

    invalidate_analyses_for_user(db_session, "user-a")
    db_session.commit()
    assert service.latest(user_id="user-a", job_id=posting.id) is None

    # Re-analysis creates a fresh row instead of reviving the invalidated one.
    replacement = await service.analyze(user_id="user-a", job_id=posting.id)
    assert replacement.analysis.id != execution.analysis.id
    assert execution.analysis.invalidated_at is not None

    EvidenceService(db_session).update(
        "user-a",
        "ev_m07",
        {"claim": "更新后的 RAG 项目经历。"},
    )
    assert service.latest(user_id="user-a", job_id=posting.id) is None


@pytest.mark.asyncio
async def test_delete_evidence_hard_deletes_referencing_analysis(db_session) -> None:
    posting = create_posting(db_session)
    add_profile_and_evidence(db_session)
    parser = JDParser(FakeModelClient(output=valid_jd_output()))
    matcher = EvidenceMatcher(
        FakeModelClient(
            output={
                "support_level": "supported",
                "evidence_ids": ["ev_m07"],
                "explanation": "在 Memory-RAG 项目中实现 RAG。",
                "claims": ["RAG"],
            }
        )
    )
    execution = await JDAnalysisService(
        db_session,
        parser=parser,
        matcher=matcher,
    ).analyze(user_id="user-a", job_id=posting.id)

    assert EvidenceService(db_session).delete("user-a", "ev_m07") is True
    assert db_session.get(EvidenceItem, "ev_m07") is None
    assert db_session.get(JobAnalysis, execution.analysis.id) is None


@pytest.mark.asyncio
async def test_latest_rejects_analysis_when_job_content_changed(db_session) -> None:
    posting = create_posting(db_session)
    add_profile_and_evidence(db_session)
    parser = JDParser(FakeModelClient(output=valid_jd_output()))
    matcher = EvidenceMatcher(
        FakeModelClient(
            output={
                "support_level": "supported",
                "evidence_ids": ["ev_m07"],
                "explanation": "在 Memory-RAG 项目中实现 RAG。",
                "claims": ["RAG"],
            }
        )
    )
    service = JDAnalysisService(db_session, parser=parser, matcher=matcher)
    await service.analyze(user_id="user-a", job_id=posting.id)

    posting.raw_content = f"{RAW_CONTENT} 内容已更新。"
    posting.content_hash = hashlib.sha256(
        posting.raw_content.encode("utf-8")
    ).hexdigest()
    db_session.commit()

    with pytest.raises(AnalysisContentChangedError):
        service.latest(user_id="user-a", job_id=posting.id)


@pytest.mark.asyncio
async def test_analysis_failure_does_not_save_half_finished_job_analysis(db_session) -> None:
    posting = create_posting(db_session)
    add_profile_and_evidence(db_session)
    parser = JDParser(FakeModelClient(error=ModelTimeoutError("timeout")))

    with pytest.raises(JDAnalysisFailure) as error:
        await JDAnalysisService(
            db_session,
            parser=parser,
        ).analyze(user_id="user-a", job_id=posting.id)

    assert error.value.code == "model_timeout"
    assert db_session.scalar(select(JobAnalysis)) is None
    assert db_session.scalar(select(AgentRun).where(AgentRun.status == "failed")) is not None


@pytest.mark.asyncio
async def test_analysis_and_latest_endpoints_return_user_scoped_result() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        import_response = await client.post(
            "/api/jobs/import-text",
            json={
                "company": "示例公司",
                "title": "AI 应用开发实习生",
                "raw_content": RAW_CONTENT,
            },
        )
        job_id = import_response.json()["id"]
        analyze_response = await client.post(
            f"/api/jobs/{job_id}/analyze",
            headers={"X-User-ID": "user-a"},
        )
        latest_response = await client.get(
            f"/api/jobs/{job_id}/analysis",
            headers={"X-User-ID": "user-a"},
        )
        other_response = await client.get(
            f"/api/jobs/{job_id}/analysis",
            headers={"X-User-ID": "user-b"},
        )

    assert import_response.status_code == 201
    assert analyze_response.status_code == 200
    assert analyze_response.json()["analysis_id"].startswith("analysis_")
    assert analyze_response.json()["structured_jd"]["requirements"][0]["name"] == "RAG"
    assert analyze_response.json()["matches"][0]["support_level"] == "needs_confirmation"
    assert analyze_response.json()["decision"]["recommendation"] == (
        "insufficient_information"
    )
    assert latest_response.status_code == 200
    assert latest_response.json()["analysis_id"] == analyze_response.json()["analysis_id"]
    assert other_response.status_code == 404
    assert other_response.json()["error"]["code"] == "analysis_not_found"


@pytest.mark.asyncio
async def test_demo_api_matches_current_user_evidence() -> None:
    transport = httpx.ASGITransport(app=app)
    headers = {"X-User-ID": "demo-user"}
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        profile_response = await client.put(
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
        evidence_response = await client.post(
            "/api/evidence",
            headers=headers,
            json={
                "type": "project",
                "title": "Memory-RAG",
                "claim": "在 Memory-RAG 项目中实现 RAG。",
                "skills": ["RAG"],
                "source": "test_demo",
            },
        )
        import_response = await client.post(
            "/api/jobs/import-text",
            json={"raw_content": RAW_CONTENT},
        )
        analysis_response = await client.post(
            f"/api/jobs/{import_response.json()['id']}/analyze",
            headers=headers,
        )

    assert profile_response.status_code == 200
    assert evidence_response.status_code == 201
    assert analysis_response.status_code == 200
    body = analysis_response.json()
    assert body["matches"][0]["support_level"] == "supported"
    assert body["matches"][0]["evidence_ids"] == [evidence_response.json()["id"]]
    assert body["decision"]["recommendation"] == "insufficient_information"
    assert body["score"]["score"] == 100.0
    assert body["score"]["recommendation"] == "needs_confirmation"


@pytest.mark.asyncio
async def test_analysis_endpoint_returns_unified_not_found_error() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/jobs/job_missing/analyze")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "job_not_found"
