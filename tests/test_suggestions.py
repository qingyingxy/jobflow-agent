import hashlib
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import func, select

from src.domain.analysis import JobAnalysis
from src.domain.application import DomainEvent
from src.domain.job import JobPosting
from src.domain.models import EvidenceItem
from src.domain.runs import AgentRun
from src.domain.suggestion import (
    ResumeSuggestion,
    SuggestionDecision,
    SuggestionStatus,
    SuggestionTargetInput,
)
from src.infrastructure.llm_client import FakeModelClient, ModelTimeoutError
from src.main import app
from src.services.application_service import ApplicationService
from src.services.evidence_service import EvidenceService
from src.services.suggestion_service import (
    InvalidSuggestionDecisionError,
    SuggestionGenerationFailure,
    SuggestionService,
)


def create_context(db_session, *, user_id: str = "user-a"):
    raw_content = "示例公司招聘后端开发工程师，负责服务开发和系统维护。"
    posting = JobPosting(
        id=f"job_m09_{user_id}",
        source_url="https://example.com/job/m09",
        source_type="manual_text",
        company="示例公司",
        title="后端开发工程师",
        raw_content=raw_content,
        content_hash=hashlib.sha256(raw_content.encode("utf-8")).hexdigest(),
        retrieved_at=datetime.now(UTC),
        trace_id=f"trace_m09_{user_id}",
    )
    analysis = JobAnalysis(
        id=f"analysis_m09_{user_id}",
        user_id=user_id,
        job_posting_id=posting.id,
        parse_result_id=f"parse_m09_{user_id}",
        analysis_version="job-analysis-v1",
        input_hash="a" * 64,
        eligibility={"eligible": "pass", "checks": []},
        matches=[],
        score={
            "score": 100,
            "eligibility": "pass",
            "recommendation": "recommended",
            "groups": [],
            "missing_information": [],
        },
        risks=[],
        missing_information=[],
    )
    evidence = EvidenceItem(
        id=f"ev_m09_{user_id}",
        user_id=user_id,
        type="project",
        title="Memory-RAG",
        claim="在 Memory-RAG 项目中实现 RAG。",
        skills=["RAG"],
        source="resume_project_1",
    )
    db_session.add_all([posting, analysis, evidence])
    db_session.commit()
    candidate = ApplicationService(db_session).create_candidate(
        user_id=user_id,
        job_posting_id=posting.id,
    )
    application = ApplicationService(db_session).prepare_application(
        user_id=user_id,
        candidate_id=candidate.candidate.id,
    )
    return posting, analysis, evidence, application.view.application


def valid_suggestion_output(evidence_id: str) -> dict[str, object]:
    return {
        "suggestion_text": "负责后端开发；补充经历：在 Memory-RAG 项目中实现 RAG。",
        "evidence_ids": [evidence_id],
        "claims": ["在 Memory-RAG 项目中实现 RAG。"],
    }


@pytest.mark.asyncio
async def test_generate_suggestion_is_pending_and_evidence_grounded(db_session) -> None:
    _, analysis, evidence, application = create_context(db_session)
    suggestion = await SuggestionService(
        db_session,
        FakeModelClient(output=valid_suggestion_output(evidence.id)),
    ).generate(
        user_id="user-a",
        application_id=application.id,
        job_analysis_id=analysis.id,
        target=SuggestionTargetInput(
            original_text="负责后端开发。",
            target_type="project_bullet",
            target_label="项目经历",
        ),
    )

    assert suggestion.status == SuggestionStatus.PENDING.value
    assert suggestion.final_text is None
    assert suggestion.evidence_ids == [evidence.id]
    run = db_session.get(AgentRun, suggestion.agent_run_id)
    assert run is not None
    assert run.run_type == "resume_suggestion"
    assert run.status == "succeeded"
    assert run.validation_status == "passed"
    events = db_session.scalars(
        select(DomainEvent).where(DomainEvent.entity_id == application.id)
    ).all()
    assert any(event.event_type == "SuggestionCreated" for event in events)


@pytest.mark.asyncio
async def test_accept_edit_and_reject_are_distinct_decisions(db_session) -> None:
    _, analysis, evidence, application = create_context(db_session)

    service = SuggestionService(
        db_session,
        FakeModelClient(output=valid_suggestion_output(evidence.id)),
    )

    async def make_one() -> ResumeSuggestion:
        return await service.generate(
            user_id="user-a",
            application_id=application.id,
            job_analysis_id=analysis.id,
            target=SuggestionTargetInput(
                original_text="负责后端开发。",
                target_type="project_bullet",
            ),
        )

    first = await make_one()
    accepted = service.decide(
        user_id="user-a",
        suggestion_id=first.id,
        decision=SuggestionDecision.ACCEPT,
    )
    assert accepted.status == SuggestionStatus.ACCEPTED.value
    assert accepted.final_text == accepted.suggestion_text
    with pytest.raises(InvalidSuggestionDecisionError):
        service.decide(
            user_id="user-a",
            suggestion_id=first.id,
            decision=SuggestionDecision.REJECT,
        )

    second = await make_one()
    edited = service.decide(
        user_id="user-a",
        suggestion_id=second.id,
        decision=SuggestionDecision.EDIT,
        final_text="用户确认后的项目经历文本。",
    )
    assert edited.status == SuggestionStatus.ACCEPTED.value
    assert edited.final_text == "用户确认后的项目经历文本。"

    third = await make_one()
    rejected = service.decide(
        user_id="user-a",
        suggestion_id=third.id,
        decision=SuggestionDecision.REJECT,
    )
    assert rejected.status == SuggestionStatus.REJECTED.value
    assert rejected.final_text is None
    event = db_session.scalar(
        select(DomainEvent)
        .where(
            DomainEvent.entity_id == application.id,
            DomainEvent.event_type == "SuggestionDecisionRecorded",
        )
        .order_by(DomainEvent.created_at.desc())
    )
    assert event is not None
    assert "final_text" not in event.payload
    assert "suggestion_text" not in event.payload


@pytest.mark.asyncio
async def test_invalid_suggestion_output_is_not_persisted_as_pending(
    db_session,
) -> None:
    _, analysis, _, application = create_context(db_session)
    service = SuggestionService(
        db_session,
        FakeModelClient(
            output={
                "suggestion_text": "我掌握 Kubernetes 并负责 999 个服务。",
                "evidence_ids": ["ev_missing"],
                "claims": ["Kubernetes"],
            }
        ),
    )

    with pytest.raises(SuggestionGenerationFailure) as error:
        await service.generate(
            user_id="user-a",
            application_id=application.id,
            job_analysis_id=analysis.id,
            target=SuggestionTargetInput(
                original_text="负责后端开发。",
                target_type="project_bullet",
            ),
        )

    assert error.value.code == "suggestion_evidence_invalid"
    assert db_session.scalar(select(func.count(ResumeSuggestion.id))) == 0
    run = db_session.scalar(
        select(AgentRun).where(AgentRun.id == error.value.agent_run_id)
    )
    assert run is not None
    assert run.status == "succeeded"
    assert run.validation_status == "failed"


@pytest.mark.asyncio
async def test_model_failure_records_failed_agent_run(db_session) -> None:
    _, analysis, evidence, application = create_context(db_session)
    service = SuggestionService(
        db_session,
        FakeModelClient(error=ModelTimeoutError("timeout")),
    )

    with pytest.raises(SuggestionGenerationFailure) as error:
        await service.generate(
            user_id="user-a",
            application_id=application.id,
            job_analysis_id=analysis.id,
            target=SuggestionTargetInput(
                original_text="负责后端开发。",
                target_type="project_bullet",
            ),
        )

    assert error.value.code == "model_timeout"
    run = db_session.get(AgentRun, error.value.agent_run_id)
    assert run is not None
    assert run.status == "failed"
    assert run.validation_status == "failed"
    assert evidence.id


@pytest.mark.asyncio
async def test_deleting_cited_evidence_removes_suggestion_but_keeps_audit_event(
    db_session,
) -> None:
    _, analysis, evidence, application = create_context(db_session)
    service = SuggestionService(
        db_session,
        FakeModelClient(output=valid_suggestion_output(evidence.id)),
    )

    suggestion = await service.generate(
        user_id="user-a",
        application_id=application.id,
        job_analysis_id=analysis.id,
        target=SuggestionTargetInput(
            original_text="负责后端开发。",
            target_type="project_bullet",
        ),
    )
    assert EvidenceService(db_session).delete("user-a", evidence.id) is True
    assert db_session.get(ResumeSuggestion, suggestion.id) is None
    assert db_session.scalar(
        select(func.count(DomainEvent.id)).where(
            DomainEvent.entity_id == application.id,
            DomainEvent.event_type == "SuggestionCreated",
        )
    ) == 1


@pytest.mark.asyncio
async def test_suggestion_api_is_user_scoped_and_supports_decision(
    db_session,
    monkeypatch,
) -> None:
    import src.api.applications as applications_api

    monkeypatch.setattr(applications_api, "get_settings", lambda: object())
    monkeypatch.setattr(
        applications_api,
        "create_structured_model_client",
        lambda _settings: FakeModelClient(
            output=valid_suggestion_output("ev_m09_api-user")
        ),
    )
    posting, _, evidence, application = create_context(
        db_session,
        user_id="api-user",
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            f"/api/applications/{application.id}/suggestions",
            headers={"X-User-ID": "api-user"},
            json={
                "original_text": "负责后端开发。",
                "target_type": "project_bullet",
                "target_label": "项目经历",
            },
        )
        suggestion_id = created.json()["id"]
        listed = await client.get(
            f"/api/applications/{application.id}/suggestions",
            headers={"X-User-ID": "api-user"},
        )
        invalid_edit = await client.post(
            f"/api/suggestions/{suggestion_id}/decide",
            headers={"X-User-ID": "api-user"},
            json={"decision": "edit"},
        )
        decided = await client.post(
            f"/api/suggestions/{suggestion_id}/decide",
            headers={"X-User-ID": "api-user"},
            json={"decision": "edit", "final_text": "用户最终确认文本。"},
        )
        duplicate_decision = await client.post(
            f"/api/suggestions/{suggestion_id}/decide",
            headers={"X-User-ID": "api-user"},
            json={"decision": "reject"},
        )
        forbidden = await client.get(
            f"/api/suggestions/{suggestion_id}",
            headers={"X-User-ID": "other-user"},
        )

    assert posting.id.startswith("job_m09_")
    assert evidence.id == "ev_m09_api-user"
    assert created.status_code == 201
    assert created.json()["status"] == SuggestionStatus.PENDING.value
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert invalid_edit.status_code == 422
    assert decided.status_code == 200
    assert decided.json()["final_text"] == "用户最终确认文本。"
    assert duplicate_decision.status_code == 409
    assert forbidden.status_code == 404
