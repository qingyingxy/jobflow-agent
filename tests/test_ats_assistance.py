from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

import src.api.ats_assistance as ats_api
from src.domain.application import Application, DomainEvent
from src.domain.application_attempt import SubmissionReceipt
from src.domain.ats_assistance import (
    AtsFieldAction,
    AtsProvider,
    AtsSubmissionAuthorization,
)
from src.main import app
from src.services.ats_adapters import (
    AtsAdapterError,
    AtsAdapterRegistry,
    AtsFieldDescriptor,
    AtsFillOperation,
    AtsPageSnapshot,
    AtsPreparationResult,
    AtsSubmissionEvidence,
)
from tests.test_application_attempts import _approved_revision

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "ats"


def _snapshot(
    name: str,
    *,
    url: str = "https://careers.example.com/jobs/ai-engineer",
    gates: tuple[str, ...] = (),
) -> AtsPageSnapshot:
    payload = json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))
    return AtsPageSnapshot(
        requested_url=url,
        final_url=url,
        title=payload["title"],
        visible_text=payload["title"],
        fields=tuple(
            AtsFieldDescriptor(
                key=item["key"],
                label=item["label"],
                name=item["name"],
                input_type=item["input_type"],
                required=item["required"],
                selector=item["selector"],
            )
            for item in payload["fields"]
        ),
        provider_hint=AtsProvider(payload["provider"]),
        gates=gates,
    )


class FakeAtsExecutor:
    def __init__(
        self,
        snapshot: AtsPageSnapshot,
        *,
        submission_success: bool = True,
        submission_text: str = "Thank you. Your application was submitted successfully.",
    ) -> None:
        self.snapshot = snapshot
        self.submission_success = submission_success
        self.submission_text = submission_text
        self.inspect_calls = 0
        self.prepare_calls: list[list[AtsFillOperation]] = []
        self.submit_calls: list[list[AtsFillOperation]] = []

    async def inspect(self, url: str) -> AtsPageSnapshot:
        self.inspect_calls += 1
        return self.snapshot

    async def prepare(
        self,
        *,
        url: str,
        provider: AtsProvider,
        operations: list[AtsFillOperation],
    ) -> AtsPreparationResult:
        self.prepare_calls.append(operations)
        return AtsPreparationResult(
            page_fingerprint=self.snapshot.fingerprint,
            filled_field_keys=tuple(item.field_key for item in operations),
        )

    async def submit(
        self,
        *,
        url: str,
        provider: AtsProvider,
        operations: list[AtsFillOperation],
    ) -> AtsSubmissionEvidence:
        self.submit_calls.append(operations)
        return AtsSubmissionEvidence(
            success=self.submission_success,
            confirmation_text=self.submission_text,
            confirmation_url="https://careers.example.com/jobs/ai-engineer",
            application_number=("APP-ATS-001" if self.submission_success else None),
            captured_at=datetime.now(UTC),
            failure_code=(None if self.submission_success else "ats_submission_unverified"),
        )


class CrashingSubmitExecutor(FakeAtsExecutor):
    async def submit(
        self,
        *,
        url: str,
        provider: AtsProvider,
        operations: list[AtsFillOperation],
    ) -> AtsSubmissionEvidence:
        self.submit_calls.append(operations)
        raise RuntimeError("unexpected executor failure with private details")


async def _create_attempt(
    client: httpx.AsyncClient,
    session: Session,
    *,
    user_id: str,
) -> tuple[str, str]:
    application_id, revision_id = await _approved_revision(
        client,
        session,
        user_id=user_id,
    )
    response = await client.post(
        f"/api/packet-revisions/{revision_id}/attempts",
        headers={"X-User-ID": user_id},
        json={},
    )
    assert response.status_code == 201, response.text
    return application_id, response.json()["id"]


@pytest.mark.asyncio
async def test_greenhouse_flow_requires_confirmation_and_consumes_one_time_token(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = "ats-greenhouse-owner"
    headers = {"X-User-ID": user_id}
    executor = FakeAtsExecutor(_snapshot("greenhouse_application.json"))
    monkeypatch.setattr(ats_api, "create_ats_executor", lambda: executor)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        application_id, attempt_id = await _create_attempt(
            client,
            db_session,
            user_id=user_id,
        )
        inspected = await client.post(
            f"/api/application-attempts/{attempt_id}/ats-session",
            headers=headers,
        )
        prepare_calls_before_confirmation = len(executor.prepare_calls)
        session_id = inspected.json()["id"]
        cross_user = await client.get(
            f"/api/ats-sessions/{session_id}",
            headers={"X-User-ID": "another-user"},
        )
        confirmed = await client.post(
            f"/api/ats-sessions/{session_id}/confirm-fields",
            headers=headers,
            json={"field_keys": ["greenhouse_privacy"], "confirmed": True},
        )
        grant = await client.post(
            f"/api/ats-sessions/{session_id}/authorization",
            headers=headers,
            json={"confirmed": True},
        )
        first_token = grant.json()["authorization_token"]
        renewed_grant = await client.post(
            f"/api/ats-sessions/{session_id}/authorization",
            headers=headers,
            json={"confirmed": True},
        )
        token = renewed_grant.json()["authorization_token"]
        revoked_token = await client.post(
            f"/api/ats-sessions/{session_id}/submit",
            headers=headers,
            json={"authorization_token": first_token},
        )
        ordinary_read = await client.get(
            f"/api/ats-sessions/{session_id}",
            headers=headers,
        )
        submitted = await client.post(
            f"/api/ats-sessions/{session_id}/submit",
            headers=headers,
            json={"authorization_token": token},
        )
        repeated = await client.post(
            f"/api/ats-sessions/{session_id}/submit",
            headers=headers,
            json={"authorization_token": token},
        )

    assert inspected.status_code == 200, inspected.text
    assert inspected.json()["status"] == "NEEDS_USER"
    by_key = {item["field_key"]: item for item in inspected.json()["field_plan"]}
    assert by_key["greenhouse_resume"]["action"] == "FILL"
    assert by_key["greenhouse_email"]["action"] == "SKIP"
    assert by_key["greenhouse_privacy"]["action"] == "NEEDS_CONFIRMATION"
    assert prepare_calls_before_confirmation == 0
    assert cross_user.status_code == 404
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "READY_FOR_APPROVAL"
    assert {item.field_key for item in executor.prepare_calls[0]} == {
        "greenhouse_resume",
        "greenhouse_privacy",
    }
    assert grant.status_code == 200, grant.text
    assert renewed_grant.status_code == 200, renewed_grant.text
    assert revoked_token.status_code == 409
    assert revoked_token.json()["error"]["code"] == "invalid_ats_authorization"
    assert token not in ordinary_read.text
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "SUBMITTED"
    assert repeated.status_code == 200
    assert len(executor.submit_calls) == 1
    assert db_session.get(Application, application_id).status == "SUBMITTED"
    assert db_session.scalar(select(func.count(SubmissionReceipt.id))) == 1
    authorizations = list(
        db_session.scalars(
            select(AtsSubmissionAuthorization).order_by(
                AtsSubmissionAuthorization.created_at,
                AtsSubmissionAuthorization.id,
            )
        ).all()
    )
    assert len(authorizations) == 2
    assert sum(item.revoked_at is not None for item in authorizations) == 1
    assert all(item.token_hash not in {first_token, token} for item in authorizations)
    assert sum(item.used_at is not None for item in authorizations) == 1
    event_text = " ".join(
        str(event.payload)
        for event in db_session.scalars(
            select(DomainEvent).where(DomainEvent.user_id == user_id)
        ).all()
    )
    assert token not in event_text
    assert "APP-ATS-001" not in event_text


@pytest.mark.asyncio
async def test_human_gate_never_prepares_or_authorizes(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = "ats-human-gate-owner"
    headers = {"X-User-ID": user_id}
    executor = FakeAtsExecutor(
        _snapshot(
            "greenhouse_application.json",
            gates=("browser_captcha_required",),
        )
    )
    monkeypatch.setattr(ats_api, "create_ats_executor", lambda: executor)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        _, attempt_id = await _create_attempt(
            client,
            db_session,
            user_id=user_id,
        )
        inspected = await client.post(
            f"/api/application-attempts/{attempt_id}/ats-session",
            headers=headers,
        )
        authorization = await client.post(
            f"/api/ats-sessions/{inspected.json()['id']}/authorization",
            headers=headers,
            json={"confirmed": True},
        )

    assert inspected.json()["status"] == "NEEDS_USER"
    assert "browser_captcha_required" in {
        item["code"] for item in inspected.json()["handoff_reasons"]
    }
    assert executor.prepare_calls == []
    assert authorization.status_code == 409


@pytest.mark.asyncio
async def test_pseudo_success_consumes_authorization_without_creating_receipt(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = "ats-pseudo-success-owner"
    headers = {"X-User-ID": user_id}
    executor = FakeAtsExecutor(
        _snapshot("greenhouse_application.json"),
        submission_success=False,
        submission_text="Thanks for visiting our careers page.",
    )
    monkeypatch.setattr(ats_api, "create_ats_executor", lambda: executor)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        application_id, attempt_id = await _create_attempt(
            client,
            db_session,
            user_id=user_id,
        )
        inspected = await client.post(
            f"/api/application-attempts/{attempt_id}/ats-session",
            headers=headers,
        )
        session_id = inspected.json()["id"]
        await client.post(
            f"/api/ats-sessions/{session_id}/confirm-fields",
            headers=headers,
            json={"field_keys": ["greenhouse_privacy"], "confirmed": True},
        )
        grant = await client.post(
            f"/api/ats-sessions/{session_id}/authorization",
            headers=headers,
            json={"confirmed": True},
        )
        failed = await client.post(
            f"/api/ats-sessions/{session_id}/submit",
            headers=headers,
            json={"authorization_token": grant.json()["authorization_token"]},
        )
        current = await client.get(f"/api/ats-sessions/{session_id}", headers=headers)

    assert failed.status_code == 409
    assert failed.json()["error"]["code"] == "ats_submission_unverified"
    assert current.json()["status"] == "FAILED"
    assert db_session.get(Application, application_id).status == "PREPARING"
    assert db_session.scalar(select(func.count(SubmissionReceipt.id))) == 0
    authorization = db_session.scalar(
        select(AtsSubmissionAuthorization).where(
            AtsSubmissionAuthorization.user_id == user_id
        )
    )
    assert authorization is not None and authorization.used_at is not None


@pytest.mark.asyncio
async def test_page_change_invalidates_bound_authorization_before_submit(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = "ats-page-change-owner"
    headers = {"X-User-ID": user_id}
    original = _snapshot("greenhouse_application.json")
    executor = FakeAtsExecutor(original)
    monkeypatch.setattr(ats_api, "create_ats_executor", lambda: executor)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        application_id, attempt_id = await _create_attempt(
            client,
            db_session,
            user_id=user_id,
        )
        inspected = await client.post(
            f"/api/application-attempts/{attempt_id}/ats-session",
            headers=headers,
        )
        session_id = inspected.json()["id"]
        await client.post(
            f"/api/ats-sessions/{session_id}/confirm-fields",
            headers=headers,
            json={"field_keys": ["greenhouse_privacy"], "confirmed": True},
        )
        grant = await client.post(
            f"/api/ats-sessions/{session_id}/authorization",
            headers=headers,
            json={"confirmed": True},
        )
        executor.snapshot = AtsPageSnapshot(
            requested_url=original.requested_url,
            final_url=original.final_url,
            title=original.title,
            visible_text=original.visible_text,
            fields=(
                *original.fields,
                AtsFieldDescriptor(
                    key="new_required_field",
                    label="New required question",
                    name="new_question",
                    input_type="text",
                    required=True,
                    selector="#new-question",
                ),
            ),
            provider_hint=AtsProvider.GREENHOUSE,
        )
        failed = await client.post(
            f"/api/ats-sessions/{session_id}/submit",
            headers=headers,
            json={"authorization_token": grant.json()["authorization_token"]},
        )

    assert failed.status_code == 409
    assert failed.json()["error"]["code"] == "ats_page_changed"
    assert executor.submit_calls == []
    assert db_session.get(Application, application_id).status == "PREPARING"
    assert db_session.scalar(select(func.count(SubmissionReceipt.id))) == 0


@pytest.mark.asyncio
async def test_unexpected_submit_error_requires_manual_verification(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = "ats-submit-crash-owner"
    headers = {"X-User-ID": user_id}
    executor = CrashingSubmitExecutor(_snapshot("greenhouse_application.json"))
    monkeypatch.setattr(ats_api, "create_ats_executor", lambda: executor)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        application_id, attempt_id = await _create_attempt(
            client,
            db_session,
            user_id=user_id,
        )
        inspected = await client.post(
            f"/api/application-attempts/{attempt_id}/ats-session",
            headers=headers,
        )
        session_id = inspected.json()["id"]
        await client.post(
            f"/api/ats-sessions/{session_id}/confirm-fields",
            headers=headers,
            json={"field_keys": ["greenhouse_privacy"], "confirmed": True},
        )
        grant = await client.post(
            f"/api/ats-sessions/{session_id}/authorization",
            headers=headers,
            json={"confirmed": True},
        )
        failed = await client.post(
            f"/api/ats-sessions/{session_id}/submit",
            headers=headers,
            json={"authorization_token": grant.json()["authorization_token"]},
        )
        current = await client.get(f"/api/ats-sessions/{session_id}", headers=headers)
        retry = await client.post(
            f"/api/ats-sessions/{session_id}/retry",
            headers=headers,
            json={"user_completed_handoff": True},
        )

    assert failed.status_code == 409
    assert failed.json()["error"]["code"] == "ats_submission_internal_error"
    assert "private details" not in failed.text
    assert current.json()["status"] == "FAILED"
    assert current.json()["handoff_reasons"][0]["category"] == "submission"
    assert retry.status_code == 409
    assert retry.json()["error"]["code"] == "ats_submission_manual_verification_required"
    assert db_session.get(Application, application_id).status == "PREPARING"
    assert db_session.scalar(select(func.count(SubmissionReceipt.id))) == 0


def test_lever_fixture_maps_salary_as_high_impact() -> None:
    snapshot = _snapshot(
        "lever_application.json",
        url="https://jobs.lever.co/example/platform-engineer",
    )
    adapter = AtsAdapterRegistry().detect(snapshot)
    packet = {
        "id": "packet_revision_fixture",
        "job_snapshot": {"company": "Example", "title": "Platform Engineer"},
        "profile_snapshot": {
            "salary_strategy": {"state": "provided", "value": "面议"},
            "work_authorization": {"state": "provided", "value": "Yes"},
        },
        "resume_snapshot": {
            "label": "Platform baseline",
            "asset": {"id": "resume_asset_fixture"},
        },
        "form_answer_snapshots": [],
        "open_questions": [],
    }
    plans = adapter.map_fields(snapshot, packet, [])
    by_key = {item["field_key"]: item for item in plans}

    assert adapter.provider is AtsProvider.LEVER
    assert by_key["lever_resume"]["action"] == AtsFieldAction.FILL.value
    assert by_key["lever_salary"]["risk"] == "HIGH_IMPACT"
    assert by_key["lever_salary"]["action"] == "NEEDS_CONFIRMATION"
    confirmed = adapter.map_fields(
        snapshot,
        packet,
        [
            {
                "field_key": "lever_work_auth",
                "value_hash": by_key["lever_work_auth"]["value_hash"],
            }
        ],
    )
    operations = adapter.fill(confirmed)
    work_auth = next(item for item in operations if item.field_key == "lever_work_auth")
    assert work_auth.input_type == "select"
    assert work_auth.value == "Yes"


def test_unsupported_ats_is_rejected() -> None:
    snapshot = AtsPageSnapshot(
        requested_url="https://workday.example.com/job/1",
        final_url="https://workday.example.com/job/1",
        title="Unsupported",
        visible_text="Application",
        fields=(),
    )
    with pytest.raises(AtsAdapterError, match="不受支持|不是受支持"):
        AtsAdapterRegistry().detect(snapshot)
