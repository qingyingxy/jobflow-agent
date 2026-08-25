from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.api import account as account_api
from src.domain.application import Application, CandidateJob
from src.domain.job import JobPosting
from src.domain.models import EvidenceItem, UserProfile
from src.domain.runs import JobParseResult
from src.infrastructure.database import Base
from src.main import app
from src.services.candidate_material_service import CandidateMaterialService
from src.services.user_data_lifecycle import UserDataLifecycleService


def _posting(job_id: str) -> JobPosting:
    content = f"Verified fixture description for {job_id} with enough content."
    digest = hashlib.sha256(content.encode()).hexdigest()
    return JobPosting(
        id=job_id,
        source_url=f"https://careers.example.com/jobs/{job_id}",
        source_type="manual_text",
        source_id=f"source_{job_id}",
        source_job_id=job_id,
        company="Lifecycle Fixture",
        title="AI Engineer",
        locations=["Shanghai"],
        job_type="full_time",
        raw_content=content,
        content_hash=digest,
        retrieved_at=datetime.now(UTC),
        trace_id=f"trace_{job_id}",
    )


def _parse(job: JobPosting) -> JobParseResult:
    return JobParseResult(
        id=f"parse_{job.id}",
        job_posting_id=job.id,
        content_hash=job.content_hash,
        schema_version="jd-v1",
        parser_version="fixture",
        prompt_version="fixture",
        model="fixture",
        structured_jd={"company": job.company, "title": job.title},
    )


def _seed_lifecycle_data(session: Session, storage_root: Path) -> tuple[str, str]:
    owner = "lifecycle-owner"
    other = "lifecycle-other"
    shared = _posting("job_lifecycle_shared")
    exclusive = _posting("job_lifecycle_exclusive")
    session.add_all(
        [
            shared,
            exclusive,
            _parse(shared),
            _parse(exclusive),
            UserProfile(user_id=owner, display_name="Owner Private Name"),
            UserProfile(user_id=other, display_name="Other Private Name"),
            EvidenceItem(
                id="ev_lifecycle_owner",
                user_id=owner,
                type="project",
                title="Owner evidence",
                claim="owner-private-evidence",
                skills=["Python"],
            ),
            EvidenceItem(
                id="ev_lifecycle_other",
                user_id=other,
                type="project",
                title="Other evidence",
                claim="other-private-evidence",
                skills=["Go"],
            ),
            CandidateJob(
                id="candidate_lifecycle_owner_shared",
                user_id=owner,
                job_posting_id=shared.id,
                status="CONVERTED",
            ),
            CandidateJob(
                id="candidate_lifecycle_owner_exclusive",
                user_id=owner,
                job_posting_id=exclusive.id,
                status="CONVERTED",
            ),
            CandidateJob(
                id="candidate_lifecycle_other_shared",
                user_id=other,
                job_posting_id=shared.id,
                status="CONVERTED",
            ),
            Application(
                id="application_lifecycle_owner_shared",
                candidate_job_id="candidate_lifecycle_owner_shared",
                status="PREPARING",
            ),
            Application(
                id="application_lifecycle_owner_exclusive",
                candidate_job_id="candidate_lifecycle_owner_exclusive",
                status="PREPARING",
            ),
            Application(
                id="application_lifecycle_other_shared",
                candidate_job_id="candidate_lifecycle_other_shared",
                status="PREPARING",
            ),
        ]
    )
    session.commit()
    materials = CandidateMaterialService(session, storage_root=storage_root)
    materials.update_profile(
        user_id=owner,
        changes={
            "contact_email": {
                "state": "provided",
                "value": "owner-private@example.com",
            }
        },
    )
    materials.update_profile(
        user_id=other,
        changes={
            "contact_email": {
                "state": "provided",
                "value": "other-private@example.com",
            }
        },
    )
    owner_asset = materials.upload_resume_asset(
        user_id=owner,
        filename="owner.pdf",
        media_type="application/pdf",
        content=b"%PDF-1.7\nowner-private-resume\n%%EOF",
    )
    other_asset = materials.upload_resume_asset(
        user_id=other,
        filename="other.pdf",
        media_type="application/pdf",
        content=b"%PDF-1.7\nother-private-resume\n%%EOF",
    )
    return owner_asset.id, other_asset.id


@pytest.mark.asyncio
async def test_account_export_and_hard_delete_are_user_scoped(
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_asset_id, other_asset_id = _seed_lifecycle_data(db_session, tmp_path)

    def service_factory(session: Session) -> UserDataLifecycleService:
        return UserDataLifecycleService(session, storage_root=tmp_path)

    monkeypatch.setattr(account_api, "create_lifecycle_service", service_factory)
    headers = {"X-User-ID": "lifecycle-owner"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        summary = await client.get("/api/account/data-summary", headers=headers)
        unconfirmed = await client.request(
            "DELETE",
            "/api/account",
            headers=headers,
            json={"confirmation": "not-confirmed"},
        )
        exported = await client.post(
            "/api/account/export",
            headers=headers,
            json={"confirmed": True},
        )
        deleted = await client.request(
            "DELETE",
            "/api/account",
            headers=headers,
            json={"confirmation": "DELETE_MY_DATA"},
        )

    assert summary.status_code == 200
    assert summary.json()["related_application_count"] == 2
    assert summary.json()["resume_file_count"] == 1
    assert unconfirmed.status_code == 422
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("application/zip")
    assert exported.headers["cache-control"] == "no-store"

    with ZipFile(BytesIO(exported.content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        names = set(archive.namelist())
        exported_text = json.dumps(manifest, ensure_ascii=False)
        resume_path = manifest["file_inventory"][0]["export_path"]
        assert resume_path in names
        assert archive.read(resume_path) == (
            b"%PDF-1.7\nowner-private-resume\n%%EOF"
        )
    assert manifest["schema_version"] == "jobflow-account-export-v1"
    assert "owner-private@example.com" in exported_text
    assert "owner-private-evidence" in exported_text
    assert "other-private@example.com" not in exported_text
    assert "other-private-evidence" not in exported_text
    assert "storage_key" not in exported_text

    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["deleted_application_count"] == 2
    assert deleted.json()["deleted_exclusive_job_count"] == 1
    assert deleted.json()["deleted_resume_file_count"] == 1
    for table in Base.metadata.tables.values():
        if "user_id" not in table.c:
            continue
        remaining = db_session.scalar(
            select(func.count()).select_from(table).where(
                table.c.user_id == "lifecycle-owner"
            )
        )
        assert remaining == 0, table.name

    assert db_session.get(Application, "application_lifecycle_owner_shared") is None
    assert db_session.get(Application, "application_lifecycle_other_shared") is not None
    assert db_session.get(JobPosting, "job_lifecycle_exclusive") is None
    assert db_session.get(JobParseResult, "parse_job_lifecycle_exclusive") is None
    assert db_session.get(JobPosting, "job_lifecycle_shared") is not None
    assert db_session.get(JobParseResult, "parse_job_lifecycle_shared") is not None

    assets = CandidateMaterialService(db_session, storage_root=tmp_path)
    assert assets.list_resume_assets("lifecycle-owner") == []
    other_asset, other_path = assets.get_resume_download(
        user_id="lifecycle-other",
        asset_id=other_asset_id,
    )
    assert other_asset.id == other_asset_id
    assert other_path.is_file()
    assert owner_asset_id not in {item.id for item in assets.list_resume_assets("lifecycle-other")}
