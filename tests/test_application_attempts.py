from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.domain.analysis import ANALYSIS_VERSION, JobAnalysis
from src.domain.application import (
    Application,
    ApplicationStatus,
    CandidateJob,
    CandidateStatus,
)
from src.domain.application_attempt import (
    ApplicationAttempt,
    AttemptStatus,
    SubmissionReceipt,
)
from src.domain.job import JobPosting
from src.domain.materials import (
    CandidatePrivateProfile,
    PrivateFieldState,
    ResumeAsset,
    ResumeVersion,
)
from src.domain.runs import JobParseResult
from src.main import app
from src.services.application_attempt_service import ApplicationAttemptService


def _seed_application(session: Session, *, user_id: str) -> str:
    suffix = user_id.replace("-", "_")[:18]
    content = "Verified AI engineer role requiring Python and careful delivery."
    content_hash = hashlib.sha256(content.encode()).hexdigest()
    job_id = f"job_attempt_{suffix}"
    application_id = f"application_attempt_{suffix}"
    posting = JobPosting(
        id=job_id,
        source_url="https://careers.example.com/jobs/ai-engineer",
        source_type="manual_text",
        source_id=f"source_attempt_{suffix}",
        source_job_id=f"role_attempt_{suffix}",
        company="Example Careers",
        title="AI Engineer",
        locations=["Shanghai"],
        job_type="full_time",
        raw_content=content,
        content_hash=content_hash,
        retrieved_at=datetime.now(UTC),
        trace_id=f"trace_attempt_{suffix}",
    )
    parse_result = JobParseResult(
        id=f"parse_attempt_{suffix}",
        job_posting_id=job_id,
        content_hash=content_hash,
        schema_version="jd-v1",
        parser_version="test-parser",
        prompt_version="test-prompt",
        model="fixture",
        structured_jd={
            "company": "Example Careers",
            "title": "AI Engineer",
            "job_type": "full_time",
            "locations": ["Shanghai"],
            "requirements": [],
        },
    )
    analysis = JobAnalysis(
        id=f"analysis_attempt_{suffix}",
        user_id=user_id,
        job_posting_id=job_id,
        parse_result_id=parse_result.id,
        analysis_version=ANALYSIS_VERSION,
        input_hash="a" * 64,
        eligibility={"eligible": "pass", "checks": []},
        matches=[],
        score={
            "score": 90,
            "eligibility": "pass",
            "recommendation": "recommended",
            "groups": [],
            "missing_information": [],
        },
        risks=[],
        missing_information=[],
    )
    candidate = CandidateJob(
        id=f"candidate_attempt_{suffix}",
        user_id=user_id,
        job_posting_id=job_id,
        status=CandidateStatus.CONVERTED.value,
    )
    application = Application(
        id=application_id,
        candidate_job_id=candidate.id,
        status=ApplicationStatus.PREPARING.value,
    )
    profile = CandidatePrivateProfile(
        user_id=user_id,
        revision=1,
        contact_email_state=PrivateFieldState.NOT_APPLICABLE.value,
        contact_phone_state=PrivateFieldState.NOT_APPLICABLE.value,
        current_status_state=PrivateFieldState.NOT_APPLICABLE.value,
        availability_date_state=PrivateFieldState.NOT_APPLICABLE.value,
        work_authorization_state=PrivateFieldState.NOT_APPLICABLE.value,
        sponsorship_required_state=PrivateFieldState.NOT_APPLICABLE.value,
        salary_strategy_state=PrivateFieldState.NOT_APPLICABLE.value,
        relocation_willing_state=PrivateFieldState.NOT_APPLICABLE.value,
    )
    asset = ResumeAsset(
        id=f"resume_asset_attempt_{suffix}",
        user_id=user_id,
        original_filename="resume.pdf",
        media_type="application/pdf",
        size_bytes=128,
        sha256="b" * 64,
        storage_key=f"fixture/{suffix}.pdf",
    )
    version = ResumeVersion(
        id=f"resume_version_attempt_{suffix}",
        user_id=user_id,
        asset_id=asset.id,
        version_number=1,
        label="AI baseline",
        job_family="AI",
        generation_reason="Fixture",
        is_default=True,
    )
    session.add_all(
        [
            posting,
            parse_result,
            analysis,
            candidate,
            application,
            profile,
            asset,
            version,
        ]
    )
    session.commit()
    return application_id


async def _approved_revision(
    client: httpx.AsyncClient,
    session: Session,
    *,
    user_id: str,
) -> tuple[str, str]:
    application_id = _seed_application(session, user_id=user_id)
    headers = {"X-User-ID": user_id}
    packet = await client.post(
        f"/api/applications/{application_id}/packet", headers=headers, json={}
    )
    assert packet.status_code == 201, packet.text
    revision_id = packet.json()["current_revision_id"]
    review = await client.post(
        f"/api/packet-revisions/{revision_id}/review", headers=headers
    )
    assert review.status_code == 200, review.text
    approval = await client.post(
        f"/api/packet-revisions/{revision_id}/approve",
        headers=headers,
        json={"confirmed": True},
    )
    assert approval.status_code == 200, approval.text
    return application_id, revision_id


@pytest.mark.asyncio
async def test_manual_attempt_requires_receipt_and_tracks_blockers(
    db_session: Session,
) -> None:
    user_id = "attempt-owner"
    headers = {"X-User-ID": user_id}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        application_id, revision_id = await _approved_revision(
            client, db_session, user_id=user_id
        )
        attempt = await client.post(
            f"/api/packet-revisions/{revision_id}/attempts",
            headers=headers,
            json={},
        )
        duplicate_attempt = await client.post(
            f"/api/packet-revisions/{revision_id}/attempts",
            headers=headers,
            json={},
        )
        attempt_id = attempt.json()["id"]
        direct_application_submit = await client.patch(
            f"/api/applications/{application_id}/status",
            headers=headers,
            json={"status": "SUBMITTED"},
        )
        direct_attempt_submit = await client.patch(
            f"/api/application-attempts/{attempt_id}/status",
            headers=headers,
            json={"status": "SUBMITTED"},
        )
        started = await client.patch(
            f"/api/application-attempts/{attempt_id}/status",
            headers=headers,
            json={"status": "FORM_IN_PROGRESS"},
        )
        blocked = await client.post(
            f"/api/application-attempts/{attempt_id}/blockers",
            headers=headers,
            json={
                "category": "login",
                "observation": "招聘门户要求登录",
                "stop_reason": "需要候选人本人完成账号验证",
                "retryable": True,
                "next_strategy": "登录后继续填写",
                "required_user_action": "完成登录并返回此页面",
            },
        )
        blocker_id = blocked.json()["blockers"][0]["id"]
        ready_while_blocked = await client.patch(
            f"/api/application-attempts/{attempt_id}/status",
            headers=headers,
            json={"status": "READY_TO_SUBMIT"},
        )
        resolved = await client.post(
            f"/api/application-attempts/{attempt_id}/blockers/{blocker_id}/resolve",
            headers=headers,
        )
        ready = await client.patch(
            f"/api/application-attempts/{attempt_id}/status",
            headers=headers,
            json={"status": "READY_TO_SUBMIT"},
        )
        no_receipt = await client.post(
            f"/api/application-attempts/{attempt_id}/finalize", headers=headers
        )
        fake_receipt = await client.post(
            f"/api/application-attempts/{attempt_id}/receipt",
            headers=headers,
            json={
                "confirmation_url": "https://careers.example.com/confirmation",
                "user_confirmed": True,
            },
        )
        receipt = await client.post(
            f"/api/application-attempts/{attempt_id}/receipt",
            headers=headers,
            json={
                "confirmation_text": "Your application has been submitted successfully.",
                "confirmation_url": "https://careers.example.com/confirmation",
                "application_number": "APP-2026-001",
                "user_confirmed": True,
            },
        )
        before_finalize = await client.get(
            f"/api/applications/{application_id}", headers=headers
        )
        finalized = await client.post(
            f"/api/application-attempts/{attempt_id}/finalize", headers=headers
        )
        duplicate_finalize = await client.post(
            f"/api/application-attempts/{attempt_id}/finalize", headers=headers
        )

    assert attempt.status_code == 201
    assert duplicate_attempt.status_code == 200
    assert duplicate_attempt.json()["id"] == attempt_id
    assert direct_application_submit.status_code == 409
    assert direct_application_submit.json()["error"]["code"] == "submission_receipt_required"
    assert direct_attempt_submit.status_code == 409
    assert started.json()["status"] == "FORM_IN_PROGRESS"
    assert blocked.json()["status"] == "NEEDS_USER"
    assert ready_while_blocked.status_code == 409
    assert ready_while_blocked.json()["error"]["code"] == "invalid_attempt_transition"
    assert resolved.json()["status"] == "FORM_IN_PROGRESS"
    assert ready.json()["status"] == "READY_TO_SUBMIT"
    assert no_receipt.status_code == 409
    assert no_receipt.json()["error"]["code"] == "submission_receipt_required"
    assert fake_receipt.status_code == 422
    assert fake_receipt.json()["error"]["code"] == "invalid_submission_receipt"
    assert receipt.status_code == 200
    assert receipt.json()["receipt"]["is_valid"] is True
    assert before_finalize.json()["status"] == "PREPARING"
    assert finalized.json()["status"] == "SUBMITTED"
    assert duplicate_finalize.json()["receipt"]["id"] == receipt.json()["receipt"]["id"]
    assert db_session.scalar(select(func.count(SubmissionReceipt.id))) == 1
    assert db_session.get(Application, application_id).status == "SUBMITTED"


@pytest.mark.asyncio
async def test_attempt_is_private_and_rejects_unverified_url(
    db_session: Session,
) -> None:
    user_id = "private-attempt-owner"
    headers = {"X-User-ID": user_id}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        _, revision_id = await _approved_revision(client, db_session, user_id=user_id)
        wrong_url = await client.post(
            f"/api/packet-revisions/{revision_id}/attempts",
            headers=headers,
            json={"application_url": "https://unverified.example.net/apply"},
        )
        created = await client.post(
            f"/api/packet-revisions/{revision_id}/attempts",
            headers=headers,
            json={},
        )
        forbidden = await client.get(
            f"/api/application-attempts/{created.json()['id']}",
            headers={"X-User-ID": "different-user"},
        )

    assert wrong_url.status_code == 409
    assert wrong_url.json()["error"]["code"] == "application_url_not_verified"
    assert created.status_code == 201
    assert forbidden.status_code == 404


@pytest.mark.asyncio
async def test_finalize_rolls_back_attempt_and_application_together(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = "rollback-attempt-owner"
    headers = {"X-User-ID": user_id}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        application_id, revision_id = await _approved_revision(
            client, db_session, user_id=user_id
        )
        created = await client.post(
            f"/api/packet-revisions/{revision_id}/attempts",
            headers=headers,
            json={},
        )
    attempt_id = created.json()["id"]
    service = ApplicationAttemptService(db_session)
    service.transition(
        user_id=user_id,
        attempt_id=attempt_id,
        target_status=AttemptStatus.FORM_IN_PROGRESS,
    )
    service.transition(
        user_id=user_id,
        attempt_id=attempt_id,
        target_status=AttemptStatus.READY_TO_SUBMIT,
    )
    service.record_receipt(
        user_id=user_id,
        attempt_id=attempt_id,
        confirmation_text="Application submitted successfully",
        confirmation_url=None,
        application_number="ROLLBACK-001",
        screenshot_metadata=None,
        user_confirmed=True,
    )

    def fail_commit() -> None:
        raise RuntimeError("commit failed")

    monkeypatch.setattr(db_session, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="commit failed"):
        service.finalize_submission(user_id=user_id, attempt_id=attempt_id)

    db_session.expire_all()
    assert db_session.get(ApplicationAttempt, attempt_id).status == "READY_TO_SUBMIT"
    assert db_session.get(Application, application_id).status == "PREPARING"
