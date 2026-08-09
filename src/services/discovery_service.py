from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from src.config import get_settings
from src.domain.application import CandidateStatus
from src.domain.discovery import (
    DiscoveryRun,
    DiscoveryRunStatus,
    generate_discovery_run_id,
)
from src.domain.job import JobPosting
from src.services.application_service import ApplicationService
from src.services.discovery_matching import classify_discovery_job
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
    job_posting_ids: list[str] = field(default_factory=list)
    analysis_job_posting_ids: list[str] = field(default_factory=list)


class DiscoveryService:
    def __init__(
        self,
        session: Session,
        adapter: JobSourceAdapter | None = None,
        *,
        run_timeout_seconds: int | None = None,
    ) -> None:
        self.session = session
        self.adapter = adapter
        configured_timeout = (
            run_timeout_seconds
            if run_timeout_seconds is not None
            else get_settings().discovery_run_timeout_seconds
        )
        self.run_timeout_seconds = max(60, configured_timeout)
        self.user_id = ""
        self.processed_job_ids: list[str] = []
        self.analysis_job_ids: list[str] = []

    def create_run(
        self,
        *,
        user_id: str,
        search_query: str | None = None,
        max_results: int = 20,
    ) -> DiscoveryRun:
        if self.adapter is None:
            raise RuntimeError("发现运行缺少来源适配器")
        run = DiscoveryRun(
            id=generate_discovery_run_id(),
            user_id=user_id,
            source=self.adapter.source_id,
            source_url=self.adapter.source_url,
            search_query=search_query,
            max_results=max_results,
            status=DiscoveryRunStatus.RUNNING.value,
            agent_trace=[self._plan_trace()],
            result_matches=[],
            started_at=datetime.now(UTC),
        )
        self.session.add(run)
        self.session.commit()
        self.session.refresh(run)
        return run

    async def run(
        self,
        *,
        user_id: str,
        run: DiscoveryRun | None = None,
    ) -> DiscoveryRunResult:
        if self.adapter is None:
            raise RuntimeError("发现运行缺少来源适配器")
        self.user_id = user_id
        self.processed_job_ids = []
        self.analysis_job_ids = []
        if run is None:
            run = self.create_run(user_id=user_id)

        try:
            stubs = await self.adapter.list_jobs()
        except Exception as error:
            self.session.rollback()
            self._mark_failed(run.id, error)
            raise self._failure(run.id, error) from error

        failures: list[str] = []
        result_matches: list[dict[str, object]] = []
        new_count = 0
        duplicate_count = 0
        for index, stub in enumerate(stubs, start=1):
            try:
                created, job_id = self._upsert_stub(stub)
                self.processed_job_ids.append(job_id)
                match = classify_discovery_job(stub, query=run.search_query)
                result_matches.append(match.as_dict(job_posting_id=job_id))
                if match.match_tier == "strict":
                    self.analysis_job_ids.append(job_id)
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
        run.result_matches = result_matches
        source_failures = [str(item) for item in getattr(self.adapter, "failures", [])]
        all_failures = [*source_failures, *failures]
        run.failure_summary = "\n".join(all_failures)[:4000] or None
        adapter_trace = [
            step.as_dict() if hasattr(step, "as_dict") else dict(step)
            for step in getattr(self.adapter, "trace_steps", [])
        ]
        result_trace = self._result_trace(
            discovered_count=len(stubs),
            strict_count=len(self.analysis_job_ids),
            expanded_count=len(result_matches) - len(self.analysis_job_ids),
            failure_count=len(all_failures),
        )
        run.agent_trace = [
            *(run.agent_trace or [self._plan_trace()]),
            *adapter_trace[:40],
            result_trace,
        ]
        if not stubs:
            run.agent_trace = [
                *run.agent_trace,
                {
                    "phase": "human_gate",
                    "tool": "manual_jd_input",
                    "outcome": "recommended",
                    "observation": "本次没有获得可验证的具体岗位。",
                    "decision": "请用户粘贴具体 JD，继续进入证据分析闭环。",
                    "source_id": None,
                    "company": None,
                    "url": None,
                },
            ]
        should_analyze = bool(getattr(self.adapter, "auto_analyze_top", False))
        run.analysis_target_count = min(5, len(self.analysis_job_ids)) if should_analyze else 0
        run.analysis_status = "PENDING" if run.analysis_target_count else "NOT_REQUESTED"
        if run.analysis_target_count:
            run.status = DiscoveryRunStatus.RUNNING.value
            run.finished_at = None
        else:
            run.status = (
                DiscoveryRunStatus.PARTIAL.value
                if all_failures
                else DiscoveryRunStatus.SUCCEEDED.value
            )
            run.finished_at = datetime.now(UTC)
        self.session.commit()
        self.session.refresh(run)
        return DiscoveryRunResult(
            run=run,
            job_posting_ids=list(self.processed_job_ids),
            analysis_job_posting_ids=list(self.analysis_job_ids),
        )

    def list_runs(self, *, user_id: str) -> list[DiscoveryRun]:
        self.recover_stale_runs(user_id=user_id)
        return list(
            self.session.scalars(
                select(DiscoveryRun)
                .where(DiscoveryRun.user_id == user_id)
                .order_by(DiscoveryRun.created_at.desc(), DiscoveryRun.id.desc())
            ).all()
        )

    def get_run(self, *, user_id: str, run_id: str) -> DiscoveryRun | None:
        self.recover_stale_runs(user_id=user_id)
        return self.session.scalar(
            select(DiscoveryRun).where(
                DiscoveryRun.id == run_id,
                DiscoveryRun.user_id == user_id,
            )
        )

    def recover_stale_runs(self, *, user_id: str) -> int:
        cutoff = datetime.now(UTC) - timedelta(seconds=self.run_timeout_seconds)
        runs = list(
            self.session.scalars(
                select(DiscoveryRun).where(
                    DiscoveryRun.user_id == user_id,
                    DiscoveryRun.status == DiscoveryRunStatus.RUNNING.value,
                    DiscoveryRun.started_at < cutoff,
                )
            ).all()
        )
        if not runs:
            return 0

        finished_at = datetime.now(UTC)
        for run in runs:
            detail = (
                f"运行超时：超过 {self.run_timeout_seconds} 秒未完成，"
                "已自动结束；可以重新发起搜索。"
            )
            run.status = DiscoveryRunStatus.FAILED.value
            run.analysis_status = "FAILED"
            run.failure_summary = "\n".join(
                item for item in (run.failure_summary, detail) if item
            )[:4000]
            run.agent_trace = [
                *(run.agent_trace or []),
                {
                    "phase": "stop",
                    "tool": "stale_run_recovery",
                    "outcome": "failed",
                    "observation": detail,
                    "decision": "终止失联运行，保留已写入的岗位事实并允许用户重试。",
                    "source_id": None,
                    "company": None,
                    "url": None,
                },
            ][-60:]
            run.finished_at = finished_at
        self.session.commit()
        return len(runs)

    def _upsert_stub(self, stub: JobStub) -> tuple[bool, str]:
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
            return True, posting.id

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
        return False, posting.id

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
        run.analysis_status = "FAILED"
        run.failure_summary = str(error)[:4000]
        run.agent_trace = [
            *(run.agent_trace or [self._plan_trace()]),
            {
                "phase": "stop",
                "tool": "discovery_orchestrator",
                "outcome": "failed",
                "observation": str(error)[:500],
                "decision": "停止运行并向用户报告可操作的失败原因。",
                "source_id": None,
                "company": None,
                "url": None,
            },
        ]
        run.finished_at = datetime.now(UTC)
        self.session.commit()

    def _plan_trace(self) -> dict[str, object]:
        if self.adapter is None:
            source_count = 0
        else:
            sources = getattr(self.adapter, "sources", None)
            source_count = len(sources) if isinstance(sources, list) else 1
        return {
            "phase": "plan",
            "tool": "discovery_orchestrator",
            "outcome": "selected",
            "observation": f"已登记 {source_count} 个本次允许访问的公开来源。",
            "decision": (
                "按结构化数据、静态页面、专用 Adapter、人工粘贴 JD 的"
                "有界顺序执行。"
            ),
            "source_id": None,
            "company": None,
            "url": None,
        }

    @staticmethod
    def _result_trace(
        *,
        discovered_count: int,
        strict_count: int,
        expanded_count: int,
        failure_count: int,
    ) -> dict[str, object]:
        return {
            "phase": "observe",
            "tool": "candidate_validator",
            "outcome": "succeeded" if discovered_count else "empty",
            "observation": (
                f"获得 {discovered_count} 条可验证岗位；"
                f"严格匹配 {strict_count} 条，拓展候选 {expanded_count} 条；"
                f"{failure_count} 个来源需要回退或适配。"
            ),
            "decision": (
                "只分析严格匹配中排序靠前的最多 5 条岗位。"
                if strict_count
                else "拓展候选不自动分析，等待用户手动确认。"
                if expanded_count
                else "不生成虚假候选岗位，转入人工 JD 入口。"
            ),
            "source_id": None,
            "company": None,
            "url": None,
        }

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
