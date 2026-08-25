from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Generator
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from src.domain.analysis import ANALYSIS_VERSION, JobAnalysis
from src.domain.application import (
    Application,
    ApplicationStatus,
    CandidateJob,
    CandidateStatus,
    DomainEvent,
)
from src.domain.application_packet import PacketDecision
from src.domain.job import JobPosting
from src.domain.materials import (
    CandidatePrivateProfile,
    PrivateFieldState,
    ResumeAsset,
    ResumeVersion,
)
from src.domain.models import EvidenceItem
from src.domain.runs import JobParseResult
from src.infrastructure.database import Base, get_session
from src.main import app


def _seed_application(
    session: Session,
    *,
    user_id: str = "packet-owner",
    eligibility: str = "pass",
    complete_profile: bool = True,
    with_resume: bool = True,
) -> tuple[str, str]:
    suffix = user_id.replace("-", "_")[:18]
    job_id = f"job_{suffix}"
    application_id = f"application_{suffix}"
    content = "Example AI engineer role requiring Python and evidence-driven delivery."
    content_hash = hashlib.sha256(content.encode()).hexdigest()
    posting = JobPosting(
        id=job_id,
        source_url="https://example.com/jobs/ai-engineer",
        source_type="manual_text",
        source_id=f"source_{suffix}",
        source_job_id=f"role_{suffix}",
        company="Example Co",
        title="AI Engineer",
        locations=["Shanghai"],
        job_type="full_time",
        raw_content=content,
        content_hash=content_hash,
        retrieved_at=datetime.now(UTC),
        trace_id=f"trace_{suffix}",
    )
    parse_result = JobParseResult(
        id=f"parse_{suffix}",
        job_posting_id=job_id,
        content_hash=content_hash,
        schema_version="jd-v1",
        parser_version="test-parser",
        prompt_version="test-prompt",
        model="fixture",
        structured_jd={
            "company": "Example Co",
            "title": "AI Engineer",
            "job_type": "full_time",
            "locations": ["Shanghai"],
            "requirements": [],
        },
    )
    analysis = JobAnalysis(
        id=f"analysis_{suffix}",
        user_id=user_id,
        job_posting_id=job_id,
        parse_result_id=parse_result.id,
        analysis_version=ANALYSIS_VERSION,
        input_hash=("a" * 63) + ("1" if eligibility == "pass" else "2"),
        eligibility={
            "eligible": eligibility,
            "checks": [
                {
                    "rule_name": "fixture",
                    "field": "fixture",
                    "result": eligibility,
                    "reason": "Fixture eligibility result.",
                    "jd_evidence": [],
                    "missing_information": (
                        [] if eligibility == "pass" else ["work_authorization"]
                    ),
                }
            ],
        },
        matches=[],
        score={
            "score": 90 if eligibility == "pass" else None,
            "eligibility": eligibility,
            "recommendation": (
                "recommended" if eligibility == "pass" else "needs_confirmation"
            ),
            "groups": [],
            "missing_information": [],
        },
        risks=[],
        missing_information=[],
    )
    candidate = CandidateJob(
        id=f"candidate_{suffix}",
        user_id=user_id,
        job_posting_id=job_id,
        status=CandidateStatus.CONVERTED.value,
    )
    application = Application(
        id=application_id,
        candidate_job_id=candidate.id,
        status=ApplicationStatus.PREPARING.value,
    )
    profile_state = (
        PrivateFieldState.NOT_APPLICABLE.value
        if complete_profile
        else PrivateFieldState.MISSING.value
    )
    profile = CandidatePrivateProfile(
        user_id=user_id,
        revision=1,
        contact_email_state=profile_state,
        contact_phone_state=profile_state,
        current_status_state=profile_state,
        availability_date_state=profile_state,
        work_authorization_state=profile_state,
        sponsorship_required_state=profile_state,
        salary_strategy_state=profile_state,
        relocation_willing_state=profile_state,
    )
    session.add_all(
        [posting, parse_result, analysis, candidate, application, profile]
    )
    if with_resume:
        asset = ResumeAsset(
            id=f"resume_asset_{suffix}",
            user_id=user_id,
            original_filename="resume.pdf",
            media_type="application/pdf",
            size_bytes=128,
            sha256="b" * 64,
            storage_key=f"fixture/{suffix}.pdf",
        )
        version = ResumeVersion(
            id=f"resume_version_{suffix}",
            user_id=user_id,
            asset_id=asset.id,
            version_number=1,
            label="AI Engineer baseline",
            job_family="AI",
            generation_reason="Fixture",
            is_default=True,
        )
        session.add_all([asset, version])
    session.commit()
    return application_id, analysis.id


@pytest.mark.asyncio
async def test_packet_approval_is_user_only_idempotent_and_immutable(
    db_session: Session,
) -> None:
    application_id, _ = _seed_application(db_session)
    headers = {"X-User-ID": "packet-owner"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        generated = await client.post(
            f"/api/applications/{application_id}/packet",
            headers={**headers, "X-Actor-Type": "agent"},
            json={},
        )
        revision_id = generated.json()["current_revision_id"]
        review = await client.post(
            f"/api/packet-revisions/{revision_id}/review", headers=headers
        )
        agent_approval = await client.post(
            f"/api/packet-revisions/{revision_id}/approve",
            headers={**headers, "X-Actor-Type": "agent"},
            json={"confirmed": True},
        )
        approved = await client.post(
            f"/api/packet-revisions/{revision_id}/approve",
            headers=headers,
            json={"confirmed": True},
        )
        duplicate = await client.post(
            f"/api/packet-revisions/{revision_id}/approve",
            headers=headers,
            json={"confirmed": True},
        )
        edit = await client.patch(
            f"/api/packet-revisions/{revision_id}/items",
            headers=headers,
            json={"evidence_ids": []},
        )
        other_user = await client.get(
            f"/api/packet-revisions/{revision_id}",
            headers={"X-User-ID": "not-the-owner"},
        )

    assert generated.status_code == 201
    assert generated.json()["status"] == "DRAFT"
    assert generated.json()["current_revision"]["created_by_actor"] == "agent"
    assert review.status_code == 200
    assert review.json()["status"] == "NEEDS_REVIEW"
    assert agent_approval.status_code == 403
    assert agent_approval.json()["error"]["code"] == "user_approval_required"
    assert approved.status_code == 200
    assert approved.json()["status"] == "APPROVED"
    assert len(approved.json()["current_revision"]["decisions"]) == 1
    assert duplicate.status_code == 200
    assert len(duplicate.json()["current_revision"]["decisions"]) == 1
    assert edit.status_code == 409
    assert edit.json()["error"]["code"] == "approved_revision_immutable"
    assert other_user.status_code == 404
    assert db_session.scalar(select(func.count(PacketDecision.id))) == 1
    event_text = " ".join(
        str(item.payload)
        for item in db_session.scalars(select(DomainEvent)).all()
    )
    assert "contact_email" not in event_text
    assert "resume.pdf" not in event_text


@pytest.mark.asyncio
async def test_packet_blockers_prevent_approval_and_stale_analysis_is_rejected(
    db_session: Session,
) -> None:
    application_id, analysis_id = _seed_application(
        db_session,
        user_id="blocked-owner",
        eligibility="unknown",
        complete_profile=False,
        with_resume=False,
    )
    headers = {"X-User-ID": "blocked-owner"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        generated = await client.post(
            f"/api/applications/{application_id}/packet", headers=headers, json={}
        )
        revision_id = generated.json()["current_revision_id"]
        review = await client.post(
            f"/api/packet-revisions/{revision_id}/review", headers=headers
        )
        blocked = await client.post(
            f"/api/packet-revisions/{revision_id}/approve",
            headers=headers,
            json={"confirmed": True},
        )

        analysis = db_session.get(JobAnalysis, analysis_id)
        assert analysis is not None
        analysis.invalidated_at = datetime.now(UTC)
        db_session.commit()
        stale = await client.post(
            f"/api/packet-revisions/{revision_id}/approve",
            headers=headers,
            json={"confirmed": True},
        )

    blocker_codes = {
        item["code"] for item in generated.json()["current_revision"]["blockers"]
    }
    assert generated.status_code == 201
    assert {
        "eligibility_unknown",
        "private_profile_incomplete",
        "resume_missing",
    } <= blocker_codes
    assert review.status_code == 200
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "packet_approval_blocked"
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "packet_sources_changed"
    assert (
        "analysis_invalidated"
        in stale.json()["error"]["details"]["source_change_codes"]
    )


@pytest.mark.asyncio
async def test_user_confirmed_open_question_and_new_revision_supersedes_approval(
    db_session: Session,
) -> None:
    application_id, _ = _seed_application(
        db_session, user_id="revision-owner"
    )
    headers = {"X-User-ID": "revision-owner"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        generated = await client.post(
            f"/api/applications/{application_id}/packet", headers=headers, json={}
        )
        revision_id = generated.json()["current_revision_id"]
        agent_edit = await client.patch(
            f"/api/packet-revisions/{revision_id}/items",
            headers={**headers, "X-Actor-Type": "agent"},
            json={
                "open_questions": [
                    {
                        "question": "Why this role?",
                        "answer": "Because the work is evidence-driven.",
                        "sensitivity": "personal",
                        "confirmed": True,
                    }
                ]
            },
        )
        edited = await client.patch(
            f"/api/packet-revisions/{revision_id}/items",
            headers=headers,
            json={
                "open_questions": [
                    {
                        "question": "Why this role?",
                        "answer": "Because the work is evidence-driven.",
                        "sensitivity": "personal",
                        "confirmed": True,
                    }
                ]
            },
        )
        reviewed = await client.post(
            f"/api/packet-revisions/{revision_id}/review", headers=headers
        )
        approved = await client.post(
            f"/api/packet-revisions/{revision_id}/approve",
            headers=headers,
            json={"confirmed": True},
        )

        profile = db_session.get(CandidatePrivateProfile, "revision-owner")
        assert profile is not None
        profile.revision += 1
        profile.availability_date_state = PrivateFieldState.PROVIDED.value
        profile.availability_date = date(2026, 9, 1)
        db_session.commit()
        changed = await client.get(
            f"/api/packet-revisions/{revision_id}", headers=headers
        )
        new_revision = await client.post(
            f"/api/application-packets/{approved.json()['id']}/revisions",
            headers=headers,
            json={},
        )

    assert agent_edit.status_code == 422
    assert agent_edit.json()["error"]["code"] == "agent_cannot_confirm"
    assert edited.status_code == 200
    assert edited.json()["current_revision"]["blockers"] == []
    assert reviewed.status_code == 200
    assert approved.status_code == 200
    assert changed.json()["source_changed"] is True
    assert "private_profile_changed" in changed.json()["source_change_codes"]
    assert new_revision.status_code == 201
    assert new_revision.json()["status"] == "DRAFT"
    assert new_revision.json()["current_revision"]["revision_number"] == 2
    by_number = {
        item["revision_number"]: item for item in new_revision.json()["revisions"]
    }
    assert by_number[1]["status"] == "SUPERSEDED"
    assert by_number[2]["supersedes_revision_id"] == revision_id
    assert by_number[1]["profile_snapshot"]["revision"] == 1
    assert by_number[2]["profile_snapshot"]["revision"] == 2


@pytest.mark.asyncio
async def test_cross_user_sources_are_rejected(db_session: Session) -> None:
    application_id, _ = _seed_application(db_session, user_id="source-owner")
    db_session.add(
        EvidenceItem(
            id="ev_other_user",
            user_id="other-user",
            type="project",
            title="Private evidence",
            claim="Must not cross the user boundary.",
            skills=["Python"],
            source="manual",
        )
    )
    db_session.commit()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/applications/{application_id}/packet",
            headers={"X-User-ID": "source-owner"},
            json={"evidence_ids": ["ev_other_user"]},
        )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "evidence_not_found"


@pytest.mark.asyncio
async def test_concurrent_packet_approval_creates_one_decision(tmp_path: Path) -> None:
    database_path = tmp_path / "packet-concurrency.db"
    engine = create_engine(
        f"sqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 15},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with factory() as session:
        application_id, _ = _seed_application(
            session, user_id="concurrent-owner"
        )

    def independent_session() -> Generator[Session, None, None]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_session] = independent_session
    headers = {"X-User-ID": "concurrent-owner"}
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            generated = await client.post(
                f"/api/applications/{application_id}/packet",
                headers=headers,
                json={},
            )
            revision_id = generated.json()["current_revision_id"]
            await client.post(
                f"/api/packet-revisions/{revision_id}/review", headers=headers
            )
            responses = await asyncio.gather(
                *(
                    client.post(
                        f"/api/packet-revisions/{revision_id}/approve",
                        headers=headers,
                        json={"confirmed": True},
                    )
                    for _ in range(2)
                )
            )
        with factory() as session:
            decision_count = session.scalar(select(func.count(PacketDecision.id)))
    finally:
        app.dependency_overrides.pop(get_session, None)
        engine.dispose()

    assert [response.status_code for response in responses] == [200, 200]
    assert {response.json()["status"] for response in responses} == {"APPROVED"}
    assert decision_count == 1
