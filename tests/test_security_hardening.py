from __future__ import annotations

import json
import logging
from io import BytesIO, StringIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import httpx
import pytest
from sqlalchemy.orm import Session

from src.api import dependencies
from src.config import Settings
from src.logging_config import JsonFormatter
from src.main import app
from src.services.candidate_material_service import (
    CandidateMaterialService,
    CandidateMaterialValidationError,
)


def _docx_with(extra_name: str) -> bytes:
    target = BytesIO()
    with ZipFile(target, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr("word/document.xml", "<document />")
        archive.writestr(extra_name, b"payload")
    return target.getvalue()


def test_json_logs_redact_credentials_contact_data_and_exceptions() -> None:
    output = StringIO()
    handler = logging.StreamHandler(output)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("jobflow.security-test")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)

    try:
        raise RuntimeError(
            "private-person@example.com 13800138000 Bearer secret-token-value"
        )
    except RuntimeError:
        logger.exception("api_key=super-secret private-person@example.com")

    rendered = output.getvalue()
    payload = json.loads(rendered)
    assert "super-secret" not in rendered
    assert "secret-token-value" not in rendered
    assert "private-person@example.com" not in rendered
    assert "13800138000" not in rendered
    assert "[REDACTED]" in rendered
    assert "[REDACTED_EMAIL]" in rendered
    assert "[REDACTED_PHONE]" in rendered
    assert payload["message"].startswith("api_key=[REDACTED]")


@pytest.mark.asyncio
async def test_deployed_environment_requires_trusted_gateway_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = httpx.ASGITransport(app=app)
    insecure = Settings(
        app_env="production",
        allow_insecure_user_header=True,
        trusted_identity_header=None,
    )
    monkeypatch.setattr(dependencies, "get_settings", lambda: insecure)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        refused = await client.get(
            "/api/private-profile",
            headers={"X-User-ID": "forged-user"},
        )

    assert refused.status_code == 503
    assert refused.json()["error"]["code"] == "trusted_identity_not_configured"

    trusted = Settings(
        app_env="production",
        allow_insecure_user_header=False,
        trusted_identity_header="X-Verified-User-ID",
    )
    monkeypatch.setattr(dependencies, "get_settings", lambda: trusted)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        missing = await client.get(
            "/api/private-profile",
            headers={"X-User-ID": "forged-user"},
        )
        accepted = await client.get(
            "/api/private-profile",
            headers={
                "X-User-ID": "forged-user",
                "X-Verified-User-ID": "verified-user",
            },
        )

    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "authenticated_identity_required"
    assert accepted.status_code == 200
    assert accepted.json()["user_id"] == "verified-user"


def test_resume_content_rejects_active_pdf_macro_and_path_traversal(
    db_session: Session,
    tmp_path: Path,
) -> None:
    service = CandidateMaterialService(db_session, storage_root=tmp_path)
    active_pdf = b"%PDF-1.7\n/JavaScript (alert)\n%%EOF"
    macro_docx = _docx_with("word/vbaProject.bin")
    traversal_docx = _docx_with("../outside.bin")

    with pytest.raises(CandidateMaterialValidationError, match="活动内容"):
        service.upload_resume_asset(
            user_id="active-pdf-owner",
            filename="resume.pdf",
            media_type="application/pdf",
            content=active_pdf,
        )
    with pytest.raises(CandidateMaterialValidationError, match="宏|嵌入"):
        service.upload_resume_asset(
            user_id="macro-docx-owner",
            filename="resume.docx",
            media_type=(
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            ),
            content=macro_docx,
        )
    with pytest.raises(CandidateMaterialValidationError, match="结构不安全"):
        service.upload_resume_asset(
            user_id="traversal-docx-owner",
            filename="resume.docx",
            media_type=(
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            ),
            content=traversal_docx,
        )

    assert list(tmp_path.rglob("*.pdf")) == []
    assert list(tmp_path.rglob("*.docx")) == []
