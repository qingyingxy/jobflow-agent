"""Local redaction, exact preview consent and reusable resume extraction."""

import asyncio
import hashlib
import re
from datetime import UTC, datetime
from weakref import WeakValueDictionary

from src.domain.materials import ResumeAsset
from src.services.candidate_material_service import CandidateMaterialService
from src.services.resume_ingestion_service import (
    RESUME_EVIDENCE_PROMPT_VERSION,
    ExtractedResumeEvidence,
    ResumeIngestionError,
    ResumeIngestionService,
    extract_resume_text,
    is_current_resume_asset,
)

_locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()
REDACTION_VERSION = "resume-redaction-v1"


def redact_resume_text(text: str, *, known_names=()) -> str:
    """Remove common identifiers locally. The user reviews the exact remainder."""
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[邮箱已隐藏]", text)
    text = re.sub(r"(?<!\d)(?:\+?86[ -]?)?1[3-9]\d[ -]?\d{4}[ -]?\d{4}(?!\d)", "[电话已隐藏]", text)
    text = re.sub(r"(?<!\d)\d{17}[\dXx](?!\w)|(?<!\d)\d{15}(?!\d)", "[证件号已隐藏]", text)
    text = re.sub(r"https?://[^\s<>]+", "[个人链接已隐藏]", text)
    text = re.sub(
        r"(?im)(?:姓名|名字|name|微信|wechat|weixin|QQ|身份证号?|护照号?|通讯地址|家庭住址|住址|地址|address|电话|手机|phone|tel)\s*[:：]\s*[^\n|｜;；]+",
        "[个人信息已隐藏]", text,
    )
    for name in known_names:
        if name and len(name.strip()) >= 2:
            text = text.replace(name.strip(), "[姓名已隐藏]")
    # A short first-line name is common in PDF resumes without labeled fields.
    lines = text.splitlines()
    if (lines and re.fullmatch(r"[\u4e00-\u9fff]{2,4}|[A-Z][a-z]+(?: [A-Z][a-z]+){1,3}", lines[0].strip())
            and lines[0].strip() not in {"个人简历", "教育经历", "教育背景", "工作经历", "项目经历", "专业技能"}):
        lines[0] = "[姓名已隐藏]"
    return "\n".join(lines)


def preview_hash(asset, text):
    return hashlib.sha256(f"{asset.id}:{asset.sha256}:{REDACTION_VERSION}:{text}".encode()).hexdigest()


def deletion_only(original: str, edited: str) -> bool:
    # Review may remove additional identifying text, but cannot invent facts.
    remaining = iter(original)
    return all(any(value == character for value in remaining) for character in edited)


class ResumePrivacyService:
    def __init__(self, session, materials=None):
        self.session = session
        self.materials = materials or CandidateMaterialService(session)

    def preview(self, user_id, asset_id):
        from src.domain.materials import CandidatePrivateProfile

        asset, path = self.materials.get_resume_download(user_id=user_id, asset_id=asset_id)
        text = extract_resume_text(content=path.read_bytes(), media_type=asset.media_type)
        profile = self.session.get(CandidatePrivateProfile, user_id)
        names = [getattr(profile, field, None) for field in ("full_name", "legal_name", "preferred_name")]
        redacted = redact_resume_text(text, known_names=names)
        return asset, {"asset_id": asset.id, "text": redacted, "preview_hash": preview_hash(asset, redacted),
                       "cached": bool(asset.parse_cache), "redaction_version": REDACTION_VERSION}

    def activate_cached(self, user_id, asset_id):
        asset = self.materials.get_resume_asset(user_id=user_id, asset_id=asset_id)
        if not asset.parse_cache or is_current_resume_asset(self.session, user_id=user_id, asset_id=asset_id):
            return
        evidence = [ExtractedResumeEvidence.model_validate(item) for item in asset.parse_cache["evidence"]]
        ResumeIngestionService(self.session, None)._replace_extracted_evidence(
            user_id=user_id, asset_id=asset_id, extracted=evidence,
        )

    async def parse(self, user_id, asset_id, payload, extractor):
        lock = _locks.setdefault(asset_id, asyncio.Lock())
        async with lock:
            self.session.expire_all()
            asset, preview = self.preview(user_id, asset_id)
            if payload.preview_hash != preview["preview_hash"]:
                raise ResumeIngestionError("resume_preview_changed", "简历预览已变化，请重新核对")
            text = payload.text.strip()
            if not text or not deletion_only(preview["text"], text):
                raise ResumeIngestionError("resume_preview_invalid", "预览只能删除内容，不能添加或改写经历")
            text_hash = hashlib.sha256(text.encode()).hexdigest()
            if (asset.parse_cache and asset.parse_cache.get("text_hash") == text_hash
                    and asset.parse_cache.get("prompt_version") == RESUME_EVIDENCE_PROMPT_VERSION
                    and asset.parse_cache.get("redaction_version") == REDACTION_VERSION):
                self.activate_cached(user_id, asset_id)
                return {"cached": True}
            # No private text is sent before the request's explicit confirmation.
            extracted = await extractor.extract(text)
            self.session.expire_all()
            asset = self.session.get(ResumeAsset, asset_id)
            if asset is None or asset.user_id != user_id:
                raise ResumeIngestionError("resume_deleted", "简历已删除，解析结果未保存")
            asset.parse_cache = {
                "text_hash": text_hash, "preview_hash": preview["preview_hash"],
                "redaction_version": REDACTION_VERSION, "prompt_version": RESUME_EVIDENCE_PROMPT_VERSION,
                "confirmed_at": datetime.now(UTC).isoformat(),
                "evidence": [item.model_dump(mode="json") for item in extracted],
            }
            ResumeIngestionService(self.session, extractor)._replace_extracted_evidence(
                user_id=user_id, asset_id=asset_id, extracted=extracted,
            )
            return {"cached": False}
