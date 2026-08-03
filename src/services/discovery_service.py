from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from src.domain.application import CandidateStatus
from src.domain.discovery import (
    DiscoveryRun,
    DiscoveryRunStatus,
    generate_discovery_run_id,
)
from src.domain.job import JobPosting
from src.services.application_service import ApplicationService
from src.services.discovery_sources import JobSourceAdapter, JobStub
from src.services.jd_analysis_service import invalidate_analyses_for_job
from src.services.job_service import JobImportService
from src.services.url_reader import URLReaderError


class DiscoveryFailure(RuntimeError):
    def __init__(
        self,
        *,
        run_id: str,
        code: str,
        message: str,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.run_id = run_id
        self.code = code
        self.details = details or {}


@dataclass(frozen=True)
class DiscoveryRunResult:
    run: DiscoveryRun


class DiscoveryService:
    def __init__(
        self,
        session: Session,
        adapter: JobSourceAdapter | None = None,
    ) -> None:
        self.session = session
        self.adapter = adapter
        self.user_id = ""

    async def run(self, *, user_id: str) -> DiscoveryRunResult:
        if self.adapter is None:
            raise RuntimeError("发现运行缺少来源适配器")
        self.user_id = user_id
        run = DiscoveryRun(
            id=generate_discovery_run_id(),
            user_id=user_id,
            source=self.adapter.source_id,
            source_url=self.adapter.source_url,
            status=DiscoveryRunStatus.RUNNING.value,
            started_at=datetime.now(UTC),
        )
        self.session.add(run)
        self.session.commit()

        try:
            stubs = await self.adapter.list_jobs()
        except Exception as error:
            self.session.rollback()
            self._mark_failed(run.id, error)
            raise self._failure(run.id, error) from error

        failures: list[str] = []
        new_count = 0
        duplicate_count = 0
        for index, stub in enumerate(stubs, start=1):
            try:
                created = self._upsert_stub(stub)
                if created:
                    new_count += 1
                else:
                    duplicate_count += 1
            except Exception as error:  # noqa: BLE001 - continue collecting other jobs
                self.session.rollback()
                failures.append(self._item_failure(index, stub, error))

        run = self.session.get(DiscoveryRun, run.id)
        if run is None:
            raise RuntimeError("发现运行记录在处理过程中丢失")
        run.discovered_count = len(stubs)
        run.new_count = new_count
        run.duplicate_count = duplicate_count
        run.failure_summary = "\n".join(failures)[:4000] or None
        run.status = (
            DiscoveryRunStatus.PARTIAL.value
            if failures
            else DiscoveryRunStatus.SUCCEEDED.value
        )
        run.finished_at = datetime.now(UTC)
        self.session.commit()
        self.session.refresh(run)
        return DiscoveryRunResult(run=run)

    def list_runs(self, *, user_id: str) -> list[DiscoveryRun]:
        return list(
            self.session.scalars(
                select(DiscoveryRun)
                .where(DiscoveryRun.user_id == user_id)
                .order_by(DiscoveryRun.created_at.desc(), DiscoveryRun.id.desc())
            ).all()
        )

    def _upsert_stub(self, stub: JobStub) -> bool:
        normalized_url = _normalize_url(stub.detail_url)
        raw_content = stub.raw_content.replace("\r\n", "\n").replace("\r", "\n").strip()
        if len(raw_content) < 20:
            raise ValueError("岗位正文过短")
        content_hash = hashlib.sha256(raw_content.encode("utf-8")).hexdigest()

        posting = self.session.scalar(
            select(JobPosting).where(
                JobPosting.source_id == stub.source_id,
                JobPosting.source_job_id == stub.source_job_id,
            )
        )
        if posting is None:
            posting = self.session.scalar(
                select(JobPosting).where(
                    or_(
                        JobPosting.source_url == normalized_url,
                        JobPosting.content_hash == content_hash,
                    )
                )
            )
        if posting is None:
            posting = JobImportService(self.session).import_text(
                raw_content=raw_content,
                source_url=normalized_url,
                source_type="company_adapter",
                company=stub.company,
                title=stub.title,
                source_id=stub.source_id,
                source_job_id=stub.source_job_id,
                locations=stub.locations,
                job_type=stub.job_type,
                published_at=stub.published_at,
                last_seen_at=datetime.now(UTC),
            )
            ApplicationService(self.session).create_candidate(
                user_id=self.user_id,
                job_posting_id=posting.id,
                initial_status=CandidateStatus.DISCOVERED,
            )
            return True

        content_changed = posting.content_hash != content_hash
        posting.source_url = normalized_url
        posting.source_type = "company_adapter"
        posting.source_id = stub.source_id
        posting.source_job_id = stub.source_job_id
        posting.company = stub.company or posting.company
        posting.title = stub.title or posting.title
        posting.locations = stub.locations or posting.locations or []
        posting.job_type = stub.job_type or posting.job_type
        posting.published_at = stub.published_at or posting.published_at
        posting.last_seen_at = datetime.now(UTC)
        if content_changed:
            posting.raw_content = raw_content
            posting.content_hash = content_hash
            posting.retrieved_at = datetime.now(UTC)
            invalidate_analyses_for_job(self.session, job_id=posting.id)
        self.session.commit()
        return False

    def _failure(self, run_id: str, error: Exception) -> DiscoveryFailure:
        if isinstance(error, URLReaderError):
            code = error.code
        else:
            code = getattr(error, "code", "discovery_source_failed")
        return DiscoveryFailure(
            run_id=run_id,
            code=code,
            message="读取岗位来源失败",
            details={"reason": str(error)[:500]},
        )

    def _mark_failed(self, run_id: str, error: Exception) -> None:
        run = self.session.get(DiscoveryRun, run_id)
        if run is None:
            return
        run.status = DiscoveryRunStatus.FAILED.value
        run.failure_summary = str(error)[:4000]
        run.finished_at = datetime.now(UTC)
        self.session.commit()

    def _item_failure(self, index: int, stub: JobStub, error: Exception) -> str:
        identifier = stub.source_job_id or stub.detail_url
        return f"#{index} {identifier}: {str(error)[:300]}"


def _normalize_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("岗位来源 URL 无效")
    host = (parsed.hostname or "").lower().rstrip(".")
    port = parsed.port
    netloc = host
    if port is not None and port not in {80, 443}:
        netloc = f"{host}:{port}"
    return urlunsplit(
        (parsed.scheme.lower(), netloc, parsed.path or "/", parsed.query, "")
    )
