from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from datetime import UTC, date, datetime
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from src import domain as domain_registry
from src.config import get_settings
from src.domain.application import Application, CandidateJob
from src.domain.discovery import JobLead
from src.domain.job import JobPosting
from src.domain.materials import ResumeAsset
from src.domain.runs import JobParseResult
from src.infrastructure.database import Base


class UserDataLifecycleError(RuntimeError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class UserDataSummary:
    record_counts: dict[str, int]
    related_application_count: int
    related_job_posting_count: int
    resume_file_count: int
    resume_file_bytes: int


@dataclass(frozen=True)
class UserDataExport:
    content: bytes
    filename: str
    record_counts: dict[str, int]


@dataclass(frozen=True)
class UserDataDeletion:
    deleted_counts: dict[str, int]
    deleted_application_count: int
    deleted_exclusive_job_count: int
    deleted_resume_file_count: int


class UserDataLifecycleService:
    """Export and hard-delete one user's rows and private resume files."""

    def __init__(
        self,
        session: Session,
        *,
        storage_root: Path | None = None,
        export_max_bytes: int | None = None,
    ) -> None:
        settings = get_settings()
        self.session = session
        self.storage_root = (
            storage_root or Path(settings.private_storage_dir)
        ).resolve()
        self.export_max_bytes = export_max_bytes or settings.account_export_max_bytes

    def summary(self, *, user_id: str) -> UserDataSummary:
        candidate_ids, job_ids = self._owned_candidate_and_job_ids(user_id)
        record_counts = {
            table.name: int(
                self.session.scalar(
                    select(func.count())
                    .select_from(table)
                    .where(table.c.user_id == user_id)
                )
                or 0
            )
            for table in self._user_tables()
        }
        assets = self._resume_assets(user_id)
        return UserDataSummary(
            record_counts=record_counts,
            related_application_count=self._application_count(candidate_ids),
            related_job_posting_count=len(job_ids),
            resume_file_count=len(assets),
            resume_file_bytes=sum(asset.size_bytes for asset in assets),
        )

    def export(self, *, user_id: str) -> UserDataExport:
        candidate_ids, job_ids = self._owned_candidate_and_job_ids(user_id)
        tables: dict[str, list[dict[str, Any]]] = {}
        for table in self._user_tables():
            rows = self.session.execute(
                select(table)
                .where(table.c.user_id == user_id)
                .order_by(*table.primary_key.columns)
            ).mappings()
            tables[table.name] = [
                self._serialize_row(dict(row)) for row in rows
            ]

        application_rows: list[dict[str, Any]] = []
        if candidate_ids:
            application_rows = [
                self._serialize_row(dict(row))
                for row in self.session.execute(
                    select(Application.__table__)
                    .where(Application.candidate_job_id.in_(candidate_ids))
                    .order_by(Application.id)
                ).mappings()
            ]
        posting_rows: list[dict[str, Any]] = []
        parse_rows: list[dict[str, Any]] = []
        if job_ids:
            posting_rows = [
                self._serialize_row(dict(row))
                for row in self.session.execute(
                    select(JobPosting.__table__)
                    .where(JobPosting.id.in_(job_ids))
                    .order_by(JobPosting.id)
                ).mappings()
            ]
            parse_rows = [
                self._serialize_row(dict(row))
                for row in self.session.execute(
                    select(JobParseResult.__table__)
                    .where(JobParseResult.job_posting_id.in_(job_ids))
                    .order_by(JobParseResult.id)
                ).mappings()
            ]
        tables["applications"] = application_rows
        tables["related_job_postings"] = posting_rows
        tables["related_job_parse_results"] = parse_rows

        assets = self._resume_assets(user_id)
        file_inventory: list[dict[str, Any]] = []
        file_entries: list[tuple[str, bytes]] = []
        for asset in assets:
            path = self._resolve_storage_key(asset.storage_key)
            export_path = (
                f"resumes/{asset.id}/{Path(asset.original_filename).name}"
            )
            exists = path.is_file()
            file_inventory.append(
                {
                    "asset_id": asset.id,
                    "export_path": export_path if exists else None,
                    "sha256": asset.sha256,
                    "size_bytes": asset.size_bytes,
                    "present": exists,
                }
            )
            if exists:
                content = path.read_bytes()
                if hashlib.sha256(content).hexdigest() != asset.sha256:
                    raise UserDataLifecycleError(
                        "简历文件哈希与数据库记录不一致，已停止导出",
                        code="account_export_file_integrity_failed",
                    )
                file_entries.append((export_path, content))

        for row in tables.get("resume_assets", []):
            row.pop("storage_key", None)
            inventory = next(
                (
                    item
                    for item in file_inventory
                    if item["asset_id"] == row["id"]
                ),
                None,
            )
            row["export_path"] = (
                inventory["export_path"] if inventory else None
            )

        manifest = {
            "schema_version": "jobflow-account-export-v1",
            "generated_at": datetime.now(UTC).isoformat(),
            "user_id": user_id,
            "scope": (
                "All user-owned database rows, related applications/job facts, "
                "and available resume files."
            ),
            "record_counts": {
                name: len(rows) for name, rows in tables.items()
            },
            "file_inventory": file_inventory,
            "tables": tables,
        }
        target = BytesIO()
        with ZipFile(
            target,
            "w",
            ZIP_DEFLATED,
            strict_timestamps=False,
        ) as archive:
            archive.writestr(
                "manifest.json",
                json.dumps(
                    manifest,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ).encode("utf-8"),
            )
            for export_path, content in file_entries:
                archive.writestr(export_path, content)
        payload = target.getvalue()
        if len(payload) > self.export_max_bytes:
            raise UserDataLifecycleError(
                "账户导出文件超过大小限制",
                code="account_export_too_large",
            )
        return UserDataExport(
            content=payload,
            filename=(
                f"jobflow-account-export-{datetime.now(UTC):%Y%m%d-%H%M%S}.zip"
            ),
            record_counts=manifest["record_counts"],
        )

    def delete(self, *, user_id: str) -> UserDataDeletion:
        candidate_ids, job_ids = self._owned_candidate_and_job_ids(user_id)
        assets = self._resume_assets(user_id)
        moved_paths = self._quarantine_private_files(user_id, assets)
        deleted_counts: dict[str, int] = {}
        deleted_applications = 0
        deleted_jobs = 0
        try:
            if candidate_ids:
                result = self.session.execute(
                    delete(Application).where(
                        Application.candidate_job_id.in_(candidate_ids)
                    )
                )
                deleted_applications = int(result.rowcount or 0)
            for table in reversed(self._user_tables()):
                result = self.session.execute(
                    delete(table).where(table.c.user_id == user_id)
                )
                deleted_counts[table.name] = int(result.rowcount or 0)
            for job_id in job_ids:
                if self._job_has_other_owner(job_id):
                    continue
                self.session.execute(
                    delete(JobParseResult).where(
                        JobParseResult.job_posting_id == job_id
                    )
                )
                result = self.session.execute(
                    delete(JobPosting).where(JobPosting.id == job_id)
                )
                deleted_jobs += int(result.rowcount or 0)
            self.session.commit()
        except Exception:
            self.session.rollback()
            self._restore_quarantined_files(moved_paths)
            raise

        deleted_files = self._destroy_quarantined_files(moved_paths)
        return UserDataDeletion(
            deleted_counts=dict(sorted(deleted_counts.items())),
            deleted_application_count=deleted_applications,
            deleted_exclusive_job_count=deleted_jobs,
            deleted_resume_file_count=deleted_files,
        )

    @staticmethod
    def _user_tables():
        _ = domain_registry.__all__
        return sorted(
            (
                table
                for table in Base.metadata.tables.values()
                if "user_id" in table.c
            ),
            key=lambda table: table.name,
        )

    def _owned_candidate_and_job_ids(
        self,
        user_id: str,
    ) -> tuple[list[str], list[str]]:
        rows = self.session.execute(
            select(CandidateJob.id, CandidateJob.job_posting_id).where(
                CandidateJob.user_id == user_id
            )
        ).all()
        return [row.id for row in rows], sorted(
            {row.job_posting_id for row in rows}
        )

    def _application_count(self, candidate_ids: list[str]) -> int:
        if not candidate_ids:
            return 0
        return int(
            self.session.scalar(
                select(func.count(Application.id)).where(
                    Application.candidate_job_id.in_(candidate_ids)
                )
            )
            or 0
        )

    def _resume_assets(self, user_id: str) -> list[ResumeAsset]:
        return list(
            self.session.scalars(
                select(ResumeAsset)
                .where(ResumeAsset.user_id == user_id)
                .order_by(ResumeAsset.id)
            ).all()
        )

    def _job_has_other_owner(self, job_id: str) -> bool:
        candidate = self.session.scalar(
            select(CandidateJob.id)
            .where(CandidateJob.job_posting_id == job_id)
            .limit(1)
        )
        if candidate is not None:
            return True
        lead = self.session.scalar(
            select(JobLead.id).where(JobLead.job_posting_id == job_id).limit(1)
        )
        return lead is not None

    def _quarantine_private_files(
        self,
        user_id: str,
        assets: list[ResumeAsset],
    ) -> list[tuple[Path, Path, bool]]:
        operation_root = self.storage_root / ".deleting" / uuid4().hex
        user_storage_id = hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:24]
        user_dir = (self.storage_root / user_storage_id).resolve()
        candidates: list[tuple[Path, bool]] = []
        if user_dir.is_dir():
            candidates.append((user_dir, True))
        for asset in assets:
            target = self._resolve_storage_key(asset.storage_key)
            if target.exists() and not target.is_relative_to(user_dir):
                candidates.append((target, False))
        moved: list[tuple[Path, Path, bool]] = []
        try:
            for index, (source, is_directory) in enumerate(candidates):
                destination = operation_root / f"{index:04d}"
                destination.parent.mkdir(parents=True, exist_ok=True)
                os.replace(source, destination)
                moved.append((source, destination, is_directory))
        except Exception:
            self._restore_quarantined_files(moved)
            raise
        return moved

    @staticmethod
    def _restore_quarantined_files(
        moved: list[tuple[Path, Path, bool]],
    ) -> None:
        for original, quarantined, _ in reversed(moved):
            if not quarantined.exists():
                continue
            original.parent.mkdir(parents=True, exist_ok=True)
            os.replace(quarantined, original)

    @staticmethod
    def _destroy_quarantined_files(
        moved: list[tuple[Path, Path, bool]],
    ) -> int:
        file_count = 0
        roots: set[Path] = set()
        for _, quarantined, is_directory in moved:
            roots.add(quarantined.parent)
            if not quarantined.exists():
                continue
            if is_directory:
                file_count += sum(
                    item.is_file() for item in quarantined.rglob("*")
                )
                shutil.rmtree(quarantined)
            else:
                quarantined.unlink()
                file_count += 1
        for root in sorted(
            roots,
            key=lambda item: len(item.parts),
            reverse=True,
        ):
            if root.exists() and not any(root.iterdir()):
                root.rmdir()
            parent = root.parent
            if (
                parent.name == ".deleting"
                and parent.exists()
                and not any(parent.iterdir())
            ):
                parent.rmdir()
        return file_count

    def _resolve_storage_key(self, storage_key: str) -> Path:
        target = (self.storage_root / storage_key).resolve()
        if target != self.storage_root and not target.is_relative_to(
            self.storage_root
        ):
            raise UserDataLifecycleError(
                "简历存储标识超出私密目录",
                code="private_storage_path_invalid",
            )
        return target

    @classmethod
    def _serialize_row(cls, row: dict[str, Any]) -> dict[str, Any]:
        return {key: cls._serialize(value) for key, value in row.items()}

    @classmethod
    def _serialize(cls, value: Any) -> Any:
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, dict):
            return {
                str(key): cls._serialize(item) for key, item in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [cls._serialize(item) for item in value]
        return value
