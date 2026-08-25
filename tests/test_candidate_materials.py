from __future__ import annotations

import asyncio
import logging
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import httpx
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from src.api import materials as materials_api
from src.domain.application import DomainEvent
from src.infrastructure.database import Base, get_session
from src.main import app
from src.services.candidate_material_service import CandidateMaterialService


@pytest.fixture()
def private_storage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    def service_factory(session):
        return CandidateMaterialService(session, storage_root=tmp_path)

    monkeypatch.setattr(materials_api, "CandidateMaterialService", service_factory)
    return tmp_path


def pdf_bytes(marker: bytes = b"resume") -> bytes:
    return b"%PDF-1.7\n" + marker + b"\n%%EOF"


def docx_bytes() -> bytes:
    target = BytesIO()
    with ZipFile(target, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr("word/document.xml", "<document />")
    return target.getvalue()


@pytest.mark.asyncio
async def test_private_profile_never_guesses_missing_high_impact_fields() -> None:
    headers = {"X-User-ID": "profile-owner"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        initial = await client.get("/api/private-profile", headers=headers)
        updated = await client.put(
            "/api/private-profile",
            headers=headers,
            json={
                "contact_email": {
                    "state": "provided",
                    "value": "owner@example.com",
                },
                "contact_phone": {"state": "declined_to_store", "value": None},
                "availability_date": {
                    "state": "not_applicable",
                    "value": None,
                },
                "voluntary_disclosure_policy": "prefer_not_to_answer",
            },
        )

    assert initial.status_code == 200
    assert initial.json()["readiness"] == "needs_confirmation"
    assert len(initial.json()["needs_confirmation"]) == 8
    assert updated.status_code == 200
    payload = updated.json()
    assert payload["contact_email"]["value"] == "owner@example.com"
    assert payload["contact_phone"] == {
        "state": "declined_to_store",
        "value": None,
    }
    assert payload["current_status"] == {"state": "missing", "value": None}
    confirmation = {item["field"]: item for item in payload["needs_confirmation"]}
    assert confirmation["contact_phone"]["reason"] == (
        "declined_to_store_requires_runtime_confirmation"
    )
    assert confirmation["current_status"]["reason"] == "missing_high_impact_field"
    assert "availability_date" not in confirmation
    assert payload["voluntary_disclosure_policy"] == "prefer_not_to_answer"
    assert "voluntary_identity_answer" not in payload


@pytest.mark.asyncio
async def test_concurrent_first_profile_reads_are_idempotent(tmp_path: Path) -> None:
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'concurrent.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def independent_session():
        with factory() as session:
            yield session

    app.dependency_overrides[get_session] = independent_session
    headers = {"X-User-ID": "concurrent-profile-owner"}
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            responses = await asyncio.gather(
                *(client.get("/api/private-profile", headers=headers) for _ in range(4))
            )
    finally:
        engine.dispose()

    assert [response.status_code for response in responses] == [200, 200, 200, 200]
    assert {response.json()["revision"] for response in responses} == {1}


@pytest.mark.asyncio
async def test_private_field_state_and_value_are_consistent() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        missing_value = await client.put(
            "/api/private-profile",
            json={"work_authorization": {"state": "provided", "value": None}},
        )
        hidden_value = await client.put(
            "/api/private-profile",
            json={
                "salary_strategy": {
                    "state": "declined_to_store",
                    "value": "secret",
                }
            },
        )

    assert missing_value.status_code == 422
    assert hidden_value.status_code == 422


@pytest.mark.asyncio
async def test_resume_upload_hash_duplicate_version_and_owner_boundaries(
    private_storage: Path,
) -> None:
    owner = {"X-User-ID": "resume-owner"}
    other = {"X-User-ID": "other-user"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        uploaded = await client.post(
            "/api/resumes/assets",
            headers=owner,
            files={"file": ("resume.pdf", pdf_bytes(), "application/pdf")},
        )
        duplicate = await client.post(
            "/api/resumes/assets",
            headers=owner,
            files={"file": ("copy.pdf", pdf_bytes(), "application/pdf")},
        )
        asset_id = uploaded.json()["id"]
        version = await client.post(
            "/api/resumes/versions",
            headers=owner,
            json={
                "asset_id": asset_id,
                "label": "AI Agent 中文简历",
                "job_family": "AI Agent",
                "generation_reason": "用户上传基线",
                "is_default": False,
            },
        )
        owner_download = await client.get(
            f"/api/resumes/assets/{asset_id}/download", headers=owner
        )
        other_list = await client.get("/api/resumes/assets", headers=other)
        other_download = await client.get(
            f"/api/resumes/assets/{asset_id}/download", headers=other
        )
        other_version = await client.post(
            "/api/resumes/versions",
            headers=other,
            json={"asset_id": asset_id, "label": "stolen"},
        )

    assert uploaded.status_code == 201
    assert uploaded.json()["sha256"]
    assert "storage_key" not in uploaded.json()
    assert duplicate.status_code == 409
    assert version.status_code == 201
    assert version.json()["version_number"] == 1
    assert version.json()["is_default"] is True
    assert owner_download.status_code == 200
    assert owner_download.content == pdf_bytes()
    assert other_list.json() == []
    assert other_download.status_code == 404
    assert other_version.status_code == 404
    stored_files = [item for item in private_storage.rglob("*") if item.is_file()]
    assert len(stored_files) == 1
    assert "resume-owner" not in str(stored_files[0])


@pytest.mark.asyncio
async def test_resume_file_type_mime_size_and_content_validation(
    private_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def tiny_service_factory(session):
        return CandidateMaterialService(
            session,
            storage_root=private_storage,
            resume_max_bytes=32,
        )

    monkeypatch.setattr(
        materials_api,
        "CandidateMaterialService",
        tiny_service_factory,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        mismatched_mime = await client.post(
            "/api/resumes/assets",
            files={"file": ("resume.pdf", pdf_bytes(), "text/plain")},
        )
        fake_pdf = await client.post(
            "/api/resumes/assets",
            files={"file": ("resume.pdf", b"not a pdf", "application/pdf")},
        )
        too_large = await client.post(
            "/api/resumes/assets",
            files={"file": ("resume.pdf", pdf_bytes(b"x" * 40), "application/pdf")},
        )
        valid_docx = await client.post(
            "/api/resumes/assets",
            headers={"X-User-ID": "docx-owner"},
            files={
                "file": (
                    "resume.docx",
                    docx_bytes(),
                    (
                        "application/vnd.openxmlformats-officedocument."
                        "wordprocessingml.document"
                    ),
                )
            },
        )

    assert mismatched_mime.status_code == 422
    assert fake_pdf.status_code == 422
    assert too_large.status_code == 422
    assert valid_docx.status_code == 422  # The valid container still exceeds this test limit.


@pytest.mark.asyncio
async def test_answer_bank_requires_confirmation_and_is_user_scoped() -> None:
    owner = {"X-User-ID": "answer-owner"}
    other = {"X-User-ID": "other-user"}
    payload = {
        "question_pattern": "Why do you want to join us?",
        "answer": "I value evidence-first product work.",
        "scope_type": "company",
        "scope_value": "Example Co",
        "sensitivity": "personal",
        "confirmed": True,
    }
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        unconfirmed = await client.post(
            "/api/answer-bank",
            headers=owner,
            json={**payload, "confirmed": False},
        )
        created = await client.post("/api/answer-bank", headers=owner, json=payload)
        answer_id = created.json()["id"]
        duplicate = await client.post(
            "/api/answer-bank",
            headers=owner,
            json={**payload, "question_pattern": " why do you want to join us？？ "},
        )
        other_list = await client.get("/api/answer-bank", headers=other)
        other_update = await client.patch(
            f"/api/answer-bank/{answer_id}",
            headers=other,
            json={"answer": "changed", "confirmed": True},
        )
        owner_update = await client.patch(
            f"/api/answer-bank/{answer_id}",
            headers=owner,
            json={"answer": "Confirmed revision.", "confirmed": True},
        )

    assert unconfirmed.status_code == 422
    assert created.status_code == 201
    assert duplicate.status_code == 409
    assert other_list.json() == []
    assert other_update.status_code == 404
    assert owner_update.status_code == 200
    assert owner_update.json()["answer"] == "Confirmed revision."


@pytest.mark.asyncio
async def test_private_values_and_resume_body_do_not_enter_logs_or_domain_events(
    private_storage: Path,
    db_session,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_email = "private-person@example.com"
    secret_answer = "my-private-salary-answer"
    secret_resume_marker = b"private-resume-body-marker"
    caplog.set_level(logging.INFO)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await client.put(
            "/api/private-profile",
            json={
                "contact_email": {"state": "provided", "value": secret_email}
            },
        )
        await client.post(
            "/api/answer-bank",
            json={
                "question_pattern": "Expected salary",
                "answer": secret_answer,
                "scope_type": "general",
                "scope_value": "",
                "sensitivity": "high_impact",
                "confirmed": True,
            },
        )
        await client.post(
            "/api/resumes/assets",
            files={
                "file": (
                    "private.pdf",
                    pdf_bytes(secret_resume_marker),
                    "application/pdf",
                )
            },
        )

    assert secret_email not in caplog.text
    assert secret_answer not in caplog.text
    assert secret_resume_marker.decode() not in caplog.text
    assert db_session.scalar(select(func.count(DomainEvent.id))) == 0
