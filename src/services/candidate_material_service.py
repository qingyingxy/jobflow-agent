from __future__ import annotations

import hashlib
import os
import re
import unicodedata
import zipfile
from datetime import UTC, date, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.config import get_settings
from src.domain.materials import (
    AnswerBankEntry,
    AnswerScope,
    CandidatePrivateProfile,
    PrivateFieldState,
    ResumeAsset,
    ResumeVersion,
    generate_answer_bank_id,
    generate_resume_asset_id,
    generate_resume_version_id,
)


class CandidateMaterialError(Exception):
    pass


class CandidateMaterialNotFoundError(CandidateMaterialError):
    pass


class CandidateMaterialConflictError(CandidateMaterialError):
    pass


class CandidateMaterialValidationError(CandidateMaterialError):
    pass


PROFILE_FIELDS: dict[str, tuple[str, str, type[object]]] = {
    "contact_email": ("contact_email_state", "contact_email", str),
    "contact_phone": ("contact_phone_state", "contact_phone", str),
    "current_status": ("current_status_state", "current_status", str),
    "availability_date": ("availability_date_state", "availability_date", date),
    "work_authorization": (
        "work_authorization_state",
        "work_authorization",
        str,
    ),
    "sponsorship_required": (
        "sponsorship_required_state",
        "sponsorship_required",
        bool,
    ),
    "salary_strategy": ("salary_strategy_state", "salary_strategy", str),
    "relocation_willing": (
        "relocation_willing_state",
        "relocation_willing",
        bool,
    ),
}

HIGH_IMPACT_PROFILE_FIELDS = tuple(PROFILE_FIELDS)

RESUME_MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ),
}


def normalize_question_pattern(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.rstrip("?？。.!！ ")


class CandidateMaterialService:
    def __init__(
        self,
        session: Session,
        *,
        storage_root: Path | None = None,
        resume_max_bytes: int | None = None,
    ) -> None:
        settings = get_settings()
        self.session = session
        self.storage_root = (
            storage_root or Path(settings.private_storage_dir)
        ).resolve()
        self.resume_max_bytes = resume_max_bytes or settings.resume_max_bytes

    def get_or_create_profile(self, user_id: str) -> CandidatePrivateProfile:
        profile = self.session.get(CandidatePrivateProfile, user_id)
        if profile is not None:
            return profile
        profile = CandidatePrivateProfile(user_id=user_id)
        self.session.add(profile)
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            profile = self.session.get(CandidatePrivateProfile, user_id)
            if profile is None:
                raise
            return profile
        self.session.refresh(profile)
        return profile

    def update_profile(
        self,
        *,
        user_id: str,
        changes: dict[str, Any],
    ) -> CandidatePrivateProfile:
        profile = self.session.get(CandidatePrivateProfile, user_id)
        created = profile is None
        if profile is None:
            profile = CandidatePrivateProfile(user_id=user_id)
            self.session.add(profile)

        changed = False
        for field_name, field_update in changes.items():
            if field_name == "voluntary_disclosure_policy":
                if profile.voluntary_disclosure_policy != field_update:
                    profile.voluntary_disclosure_policy = field_update
                    changed = True
                continue
            if field_name not in PROFILE_FIELDS:
                raise CandidateMaterialValidationError("不支持的私密档案字段")
            state_column, value_column, expected_type = PROFILE_FIELDS[field_name]
            state = PrivateFieldState(field_update["state"])
            value = field_update.get("value")
            self._validate_private_field(state, value, expected_type)
            if state is not PrivateFieldState.PROVIDED:
                value = None
            if getattr(profile, state_column) != state.value:
                setattr(profile, state_column, state.value)
                changed = True
            if getattr(profile, value_column) != value:
                setattr(profile, value_column, value)
                changed = True

        if changed and not created:
            profile.revision += 1
        profile.updated_at = datetime.now(UTC)
        self.session.commit()
        self.session.refresh(profile)
        return profile

    @staticmethod
    def _validate_private_field(
        state: PrivateFieldState,
        value: object,
        expected_type: type[object],
    ) -> None:
        if state is PrivateFieldState.PROVIDED:
            if value is None or not isinstance(value, expected_type):
                raise CandidateMaterialValidationError(
                    "标记为 provided 的字段必须提供有效值"
                )
            if isinstance(value, str) and not value.strip():
                raise CandidateMaterialValidationError(
                    "标记为 provided 的字段不能为空"
                )
        elif value is not None:
            raise CandidateMaterialValidationError(
                "未提供字段不能同时保存具体值"
            )

    def profile_confirmation_items(
        self, profile: CandidatePrivateProfile
    ) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
        for field_name in HIGH_IMPACT_PROFILE_FIELDS:
            state_column, _, _ = PROFILE_FIELDS[field_name]
            state = getattr(profile, state_column)
            if state in {
                PrivateFieldState.PROVIDED.value,
                PrivateFieldState.NOT_APPLICABLE.value,
            }:
                continue
            items.append(
                {
                    "field": field_name,
                    "state": state,
                    "reason": (
                        "declined_to_store_requires_runtime_confirmation"
                        if state == PrivateFieldState.DECLINED_TO_STORE.value
                        else "missing_high_impact_field"
                    ),
                }
            )
        return items

    def upload_resume_asset(
        self,
        *,
        user_id: str,
        filename: str,
        media_type: str,
        content: bytes,
    ) -> ResumeAsset:
        safe_filename, suffix = self._validate_resume_file(
            filename=filename,
            media_type=media_type,
            content=content,
        )
        digest = hashlib.sha256(content).hexdigest()
        duplicate = self.session.scalar(
            select(ResumeAsset).where(
                ResumeAsset.user_id == user_id,
                ResumeAsset.sha256 == digest,
            )
        )
        if duplicate is not None:
            raise CandidateMaterialConflictError("相同内容的简历已经上传")

        asset_id = generate_resume_asset_id()
        user_storage_id = hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:24]
        storage_key = f"{user_storage_id}/{asset_id}{suffix}"
        target = self._resolve_storage_key(storage_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(f"{target.suffix}.{asset_id}.tmp")
        temporary.write_bytes(content)
        os.replace(temporary, target)

        asset = ResumeAsset(
            id=asset_id,
            user_id=user_id,
            original_filename=safe_filename,
            media_type=media_type,
            size_bytes=len(content),
            sha256=digest,
            storage_key=storage_key,
        )
        self.session.add(asset)
        try:
            self.session.commit()
        except IntegrityError as exception:
            self.session.rollback()
            target.unlink(missing_ok=True)
            raise CandidateMaterialConflictError(
                "相同内容的简历已经上传"
            ) from exception
        except Exception:
            self.session.rollback()
            target.unlink(missing_ok=True)
            raise
        self.session.refresh(asset)
        return asset

    def _validate_resume_file(
        self,
        *,
        filename: str,
        media_type: str,
        content: bytes,
    ) -> tuple[str, str]:
        cleaned_filename = filename.strip()
        if (
            not cleaned_filename
            or len(cleaned_filename) > 180
            or "/" in cleaned_filename
            or "\\" in cleaned_filename
            or "\x00" in cleaned_filename
        ):
            raise CandidateMaterialValidationError("简历文件名无效")
        suffix = Path(cleaned_filename).suffix.casefold()
        expected_media_type = RESUME_MEDIA_TYPES.get(suffix)
        if expected_media_type is None or media_type != expected_media_type:
            raise CandidateMaterialValidationError("仅支持 MIME 匹配的 PDF 或 DOCX 简历")
        if not content:
            raise CandidateMaterialValidationError("简历文件不能为空")
        if len(content) > self.resume_max_bytes:
            raise CandidateMaterialValidationError("简历文件超过大小限制")
        if suffix == ".pdf" and not content.startswith(b"%PDF-"):
            raise CandidateMaterialValidationError("PDF 文件内容无效")
        if suffix == ".docx":
            try:
                with zipfile.ZipFile(BytesIO(content)) as archive:
                    names = set(archive.namelist())
                    if not {"[Content_Types].xml", "word/document.xml"} <= names:
                        raise CandidateMaterialValidationError("DOCX 文件内容无效")
            except zipfile.BadZipFile as exception:
                raise CandidateMaterialValidationError("DOCX 文件内容无效") from exception
        return cleaned_filename, suffix

    def _resolve_storage_key(self, storage_key: str) -> Path:
        target = (self.storage_root / storage_key).resolve()
        if not target.is_relative_to(self.storage_root):
            raise CandidateMaterialValidationError("简历存储标识无效")
        return target

    def list_resume_assets(self, user_id: str) -> list[ResumeAsset]:
        return list(
            self.session.scalars(
                select(ResumeAsset)
                .where(ResumeAsset.user_id == user_id)
                .order_by(ResumeAsset.created_at.desc(), ResumeAsset.id.desc())
            )
        )

    def get_resume_asset(self, *, user_id: str, asset_id: str) -> ResumeAsset:
        asset = self.session.scalar(
            select(ResumeAsset).where(
                ResumeAsset.id == asset_id,
                ResumeAsset.user_id == user_id,
            )
        )
        if asset is None:
            raise CandidateMaterialNotFoundError("简历文件不存在")
        return asset

    def get_resume_download(
        self, *, user_id: str, asset_id: str
    ) -> tuple[ResumeAsset, Path]:
        asset = self.get_resume_asset(user_id=user_id, asset_id=asset_id)
        path = self._resolve_storage_key(asset.storage_key)
        if not path.is_file():
            raise CandidateMaterialNotFoundError("简历文件不存在")
        return asset, path

    def create_resume_version(
        self,
        *,
        user_id: str,
        asset_id: str,
        label: str,
        job_family: str | None,
        source_version_id: str | None,
        generation_reason: str,
        is_default: bool,
    ) -> ResumeVersion:
        self.get_resume_asset(user_id=user_id, asset_id=asset_id)
        if source_version_id is not None:
            self.get_resume_version(user_id=user_id, version_id=source_version_id)
        latest_number = self.session.scalar(
            select(func.max(ResumeVersion.version_number)).where(
                ResumeVersion.user_id == user_id
            )
        )
        version_number = int(latest_number or 0) + 1
        if version_number == 1:
            is_default = True
        if is_default:
            self._clear_default_resume(user_id)
        version = ResumeVersion(
            id=generate_resume_version_id(),
            user_id=user_id,
            asset_id=asset_id,
            version_number=version_number,
            label=label,
            job_family=job_family,
            source_version_id=source_version_id,
            generation_reason=generation_reason,
            is_default=is_default,
        )
        self.session.add(version)
        self.session.commit()
        self.session.refresh(version)
        return version

    def list_resume_versions(self, user_id: str) -> list[ResumeVersion]:
        return list(
            self.session.scalars(
                select(ResumeVersion)
                .where(ResumeVersion.user_id == user_id)
                .order_by(
                    ResumeVersion.is_default.desc(),
                    ResumeVersion.version_number.desc(),
                )
            )
        )

    def get_resume_version(
        self, *, user_id: str, version_id: str
    ) -> ResumeVersion:
        version = self.session.scalar(
            select(ResumeVersion).where(
                ResumeVersion.id == version_id,
                ResumeVersion.user_id == user_id,
            )
        )
        if version is None:
            raise CandidateMaterialNotFoundError("简历版本不存在")
        return version

    def update_resume_version(
        self,
        *,
        user_id: str,
        version_id: str,
        changes: dict[str, Any],
    ) -> ResumeVersion:
        version = self.get_resume_version(user_id=user_id, version_id=version_id)
        if changes.get("is_default") is False and version.is_default:
            raise CandidateMaterialValidationError("请将另一个简历版本设为默认")
        if changes.get("is_default") is True:
            self._clear_default_resume(user_id)
        for field_name in ("label", "job_family", "generation_reason", "is_default"):
            if field_name in changes:
                setattr(version, field_name, changes[field_name])
        version.updated_at = datetime.now(UTC)
        self.session.commit()
        self.session.refresh(version)
        return version

    def _clear_default_resume(self, user_id: str) -> None:
        for version in self.session.scalars(
            select(ResumeVersion).where(
                ResumeVersion.user_id == user_id,
                ResumeVersion.is_default.is_(True),
            )
        ):
            version.is_default = False

    def create_answer(
        self,
        *,
        user_id: str,
        question_pattern: str,
        answer: str,
        scope_type: str,
        scope_value: str,
        sensitivity: str,
    ) -> AnswerBankEntry:
        normalized = normalize_question_pattern(question_pattern)
        if not normalized:
            raise CandidateMaterialValidationError("问题模式不能只包含标点或空白")
        self._validate_answer_scope(scope_type, scope_value)
        self._ensure_unique_answer(
            user_id=user_id,
            normalized_question=normalized,
            scope_type=scope_type,
            scope_value=scope_value,
        )
        now = datetime.now(UTC)
        entry = AnswerBankEntry(
            id=generate_answer_bank_id(),
            user_id=user_id,
            question_pattern=question_pattern.strip(),
            normalized_question_pattern=normalized,
            answer=answer.strip(),
            scope_type=scope_type,
            scope_value=scope_value.strip(),
            sensitivity=sensitivity,
            confirmed_at=now,
            updated_at=now,
        )
        self.session.add(entry)
        self.session.commit()
        self.session.refresh(entry)
        return entry

    def list_answers(self, user_id: str) -> list[AnswerBankEntry]:
        return list(
            self.session.scalars(
                select(AnswerBankEntry)
                .where(AnswerBankEntry.user_id == user_id)
                .order_by(AnswerBankEntry.updated_at.desc(), AnswerBankEntry.id.desc())
            )
        )

    def get_answer(self, *, user_id: str, answer_id: str) -> AnswerBankEntry:
        entry = self.session.scalar(
            select(AnswerBankEntry).where(
                AnswerBankEntry.id == answer_id,
                AnswerBankEntry.user_id == user_id,
            )
        )
        if entry is None:
            raise CandidateMaterialNotFoundError("答案记录不存在")
        return entry

    def update_answer(
        self,
        *,
        user_id: str,
        answer_id: str,
        changes: dict[str, Any],
    ) -> AnswerBankEntry:
        entry = self.get_answer(user_id=user_id, answer_id=answer_id)
        question = changes.get("question_pattern", entry.question_pattern).strip()
        scope_type = changes.get("scope_type", entry.scope_type)
        scope_value = changes.get("scope_value", entry.scope_value).strip()
        normalized = normalize_question_pattern(question)
        if not normalized:
            raise CandidateMaterialValidationError("问题模式不能只包含标点或空白")
        self._validate_answer_scope(scope_type, scope_value)
        self._ensure_unique_answer(
            user_id=user_id,
            normalized_question=normalized,
            scope_type=scope_type,
            scope_value=scope_value,
            exclude_id=entry.id,
        )
        entry.question_pattern = question
        entry.normalized_question_pattern = normalized
        entry.scope_type = scope_type
        entry.scope_value = scope_value
        for field_name in ("answer", "sensitivity"):
            if field_name in changes:
                setattr(entry, field_name, changes[field_name].strip())
        entry.confirmed_at = datetime.now(UTC)
        entry.updated_at = entry.confirmed_at
        self.session.commit()
        self.session.refresh(entry)
        return entry

    def delete_answer(self, *, user_id: str, answer_id: str) -> None:
        entry = self.get_answer(user_id=user_id, answer_id=answer_id)
        self.session.delete(entry)
        self.session.commit()

    def _ensure_unique_answer(
        self,
        *,
        user_id: str,
        normalized_question: str,
        scope_type: str,
        scope_value: str,
        exclude_id: str | None = None,
    ) -> None:
        statement = select(AnswerBankEntry.id).where(
            AnswerBankEntry.user_id == user_id,
            AnswerBankEntry.normalized_question_pattern == normalized_question,
            AnswerBankEntry.scope_type == scope_type,
            AnswerBankEntry.scope_value == scope_value.strip(),
        )
        if exclude_id is not None:
            statement = statement.where(AnswerBankEntry.id != exclude_id)
        if self.session.scalar(statement) is not None:
            raise CandidateMaterialConflictError("相同范围的问题答案已经存在")

    @staticmethod
    def _validate_answer_scope(scope_type: str, scope_value: str) -> None:
        if scope_type == AnswerScope.GENERAL.value and scope_value.strip():
            raise CandidateMaterialValidationError("通用答案不能设置范围值")
        if scope_type != AnswerScope.GENERAL.value and not scope_value.strip():
            raise CandidateMaterialValidationError("非通用答案必须设置范围值")
