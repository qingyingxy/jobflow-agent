from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import func, select

from src.domain.application import (
    Application as ApplicationModel,
)
from src.domain.application import (
    ApplicationStatus,
    CandidateStatus,
    DomainEvent,
)
from src.domain.job import JobPosting
from src.main import app
from src.services.application_service import (
    ApplicationService,
    CandidateNotFoundError,
    InvalidTransitionError,
    SubmissionReceiptRequiredError,
)


def create_posting(db_session, job_id: str = "job_m08_test") -> JobPosting:
    raw_content = "示例公司招聘后端开发工程师，工作地点上海，欢迎投递。"
    posting = JobPosting(
        id=job_id,
        source_url="https://example.com/job/1",
        source_type="manual_text",
        company="示例公司",
        title="后端开发工程师",
        raw_content=raw_content,
        content_hash=hashlib.sha256(raw_content.encode("utf-8")).hexdigest(),
        retrieved_at=datetime.now(UTC),
        trace_id=f"trace_{job_id}",
    )
    db_session.add(posting)
    db_session.commit()
    return posting


def event_count(db_session, *, user_id: str, event_type: str | None = None) -> int:
    statement = select(func.count(DomainEvent.id)).where(
        DomainEvent.user_id == user_id
    )
    if event_type is not None:
        statement = statement.where(DomainEvent.event_type == event_type)
    return int(db_session.scalar(statement) or 0)


def test_candidate_creation_is_idempotent_and_user_scoped(db_session) -> None:
    posting = create_posting(db_session)
    service = ApplicationService(db_session)

    first = service.create_candidate(user_id="user-a", job_posting_id=posting.id)
    second = service.create_candidate(user_id="user-a", job_posting_id=posting.id)

    assert first.candidate.id == second.candidate.id
    assert first.candidate.status == CandidateStatus.SAVED.value
    assert event_count(db_session, user_id="user-a", event_type="CandidateSaved") == 1
    with pytest.raises(CandidateNotFoundError):
        service.get_candidate(user_id="user-b", candidate_id=first.candidate.id)


def test_prepare_application_creates_one_application_and_one_event(db_session) -> None:
    posting = create_posting(db_session)
    service = ApplicationService(db_session)
    candidate = service.create_candidate(
        user_id="user-a",
        job_posting_id=posting.id,
    )

    first = service.prepare_application(
        user_id="user-a",
        candidate_id=candidate.candidate.id,
    )
    second = service.prepare_application(
        user_id="user-a",
        candidate_id=candidate.candidate.id,
    )

    assert first.created is True
    assert second.created is False
    assert first.view.application.id == second.view.application.id
    assert first.view.application.status == ApplicationStatus.PREPARING.value
    assert first.view.candidate.status == CandidateStatus.CONVERTED.value
    assert db_session.scalar(select(func.count(ApplicationModel.id))) == 1
    assert (
        event_count(db_session, user_id="user-a", event_type="ApplicationCreated")
        == 1
    )


def test_transition_matrix_records_application_timeline(db_session) -> None:
    posting = create_posting(db_session)
    service = ApplicationService(db_session)
    candidate = service.create_candidate(
        user_id="user-a",
        job_posting_id=posting.id,
    )
    prepared = service.prepare_application(
        user_id="user-a",
        candidate_id=candidate.candidate.id,
    )

    with pytest.raises(SubmissionReceiptRequiredError):
        service.transition_application(
            user_id="user-a",
            application_id=prepared.view.application.id,
            target_status=ApplicationStatus.SUBMITTED,
            next_action="等待笔试通知",
        )
    prepared.view.application.status = ApplicationStatus.SUBMITTED.value
    prepared.view.application.next_action = "等待笔试通知"
    db_session.commit()
    assessment = service.transition_application(
        user_id="user-a",
        application_id=prepared.view.application.id,
        target_status=ApplicationStatus.ASSESSMENT,
    )
    interview = service.transition_application(
        user_id="user-a",
        application_id=assessment.application.id,
        target_status=ApplicationStatus.INTERVIEW,
    )

    assert interview.application.status == ApplicationStatus.INTERVIEW.value
    assert interview.application.next_action == "等待笔试通知"
    assert len(interview.events) == 3
    with pytest.raises(InvalidTransitionError):
        service.transition_application(
            user_id="user-a",
            application_id=interview.application.id,
            target_status=ApplicationStatus.PREPARING,
        )


def test_prepare_application_rolls_back_candidate_when_event_write_fails(
    db_session,
    monkeypatch,
) -> None:
    posting = create_posting(db_session)
    service = ApplicationService(db_session)
    candidate = service.create_candidate(
        user_id="user-a",
        job_posting_id=posting.id,
    )

    def fail_event(**_kwargs):
        raise RuntimeError("event write failed")

    monkeypatch.setattr(service, "_add_event", fail_event)
    with pytest.raises(RuntimeError, match="event write failed"):
        service.prepare_application(
            user_id="user-a",
            candidate_id=candidate.candidate.id,
        )

    refreshed = service.get_candidate(
        user_id="user-a",
        candidate_id=candidate.candidate.id,
    )
    assert refreshed.candidate.status == CandidateStatus.SAVED.value
    assert db_session.scalar(select(func.count(ApplicationModel.id))) == 0


@pytest.mark.asyncio
async def test_application_api_covers_prepare_transition_timeline_and_ownership() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        imported = await client.post(
            "/api/jobs/import-text",
            json={
                "company": "API 公司",
                "title": "数据工程师",
                "raw_content": "API 公司招聘数据工程师，工作地点杭州，欢迎投递。",
            },
        )
        job_id = imported.json()["id"]
        owner_headers = {"X-User-ID": "api-user"}
        other_headers = {"X-User-ID": "other-user"}

        candidate_response = await client.post(
            "/api/candidates",
            headers=owner_headers,
            json={"job_posting_id": job_id},
        )
        candidate_id = candidate_response.json()["id"]
        duplicate_response = await client.post(
            "/api/candidates",
            headers=owner_headers,
            json={"job_posting_id": job_id},
        )
        prepared = await client.post(
            f"/api/candidates/{candidate_id}/prepare-application",
            headers=owner_headers,
        )
        application_id = prepared.json()["id"]
        transitioned = await client.patch(
            f"/api/applications/{application_id}/status",
            headers=owner_headers,
            json={"status": "SUBMITTED", "next_action": "等待笔试通知"},
        )
        events = await client.get(
            f"/api/applications/{application_id}/events",
            headers=owner_headers,
        )
        board = await client.get("/api/applications", headers=owner_headers)
        forbidden = await client.get(
            f"/api/applications/{application_id}",
            headers=other_headers,
        )

    assert imported.status_code == 201
    assert candidate_response.status_code == 201
    assert duplicate_response.status_code == 201
    assert duplicate_response.json()["id"] == candidate_id
    assert prepared.status_code == 201
    assert prepared.json()["status"] == ApplicationStatus.PREPARING.value
    assert "SUBMITTED" not in prepared.json()["available_transitions"]
    assert transitioned.status_code == 409
    assert transitioned.json()["error"]["code"] == "submission_receipt_required"
    assert len(events.json()) == 1
    assert len(board.json()) == 1
    assert forbidden.status_code == 404
