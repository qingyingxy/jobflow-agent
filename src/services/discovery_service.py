from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from time import perf_counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.config import get_settings
from src.domain.discovery import (
    DiscoveryPlanBudget,
    DiscoveryPlanRoute,
    DiscoveryRun,
    DiscoveryRunStatus,
    DiscoverySearchPlan,
    generate_discovery_run_id,
)
from src.services.discovery_matching import classify_discovery_job
from src.services.discovery_sources import JobSourceAdapter, JobStub
from src.services.job_lead_service import JobLeadService
from src.services.lead_providers import OfficialAdapterLeadProvider
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
        self.leads = JobLeadService(session)
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
        search_plan = self._build_search_plan(
            search_query=search_query,
            max_results=max_results,
        )
        started_at = datetime.now(UTC)
        run = DiscoveryRun(
            id=generate_discovery_run_id(),
            user_id=user_id,
            source=self.adapter.source_id,
            source_url=self.adapter.source_url,
            search_query=search_query,
            max_results=max_results,
            status=DiscoveryRunStatus.RUNNING.value,
            search_plan=search_plan.model_dump(mode="json"),
            agent_trace=[self._plan_trace(search_plan, occurred_at=started_at)],
            result_matches=[],
            started_at=started_at,
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
        self.processed_job_ids = []
        self.analysis_job_ids = []
        if run is None:
            run = self.create_run(user_id=user_id)

        try:
            candidates = await OfficialAdapterLeadProvider(self.adapter).discover()
        except Exception as error:
            self.session.rollback()
            self._mark_failed(run.id, error)
            raise self._failure(run.id, error) from error

        validation_started = perf_counter()
        failures: list[str] = []
        result_matches: list[dict[str, object]] = []
        new_count = 0
        duplicate_count = 0
        for index, candidate in enumerate(candidates, start=1):
            stub = candidate.verification_stub
            if stub is None:
                failures.append(f"第 {index} 条线索缺少官方验证快照")
                continue
            try:
                lead = self.leads.capture_candidate(
                    user_id=user_id,
                    discovery_run_id=run.id,
                    candidate=candidate,
                )
                verified = self.leads.verify_stub(
                    user_id=user_id,
                    lead_id=lead.id,
                    stub=stub,
                )
                created = verified.posting_created
                job_id = verified.posting.id
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
        run.discovered_count = len(candidates)
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
            discovered_count=len(candidates),
            strict_count=len(self.analysis_job_ids),
            expanded_count=len(result_matches) - len(self.analysis_job_ids),
            failure_count=len(all_failures),
            duration_ms=max(
                0,
                round((perf_counter() - validation_started) * 1000),
            ),
        )
        run.agent_trace = [
            *(run.agent_trace or []),
            *adapter_trace[:55],
            result_trace,
        ]
        if not candidates:
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
                    "occurred_at": datetime.now(UTC).isoformat(),
                    "duration_ms": None,
                    "error_code": None,
                    "details": {"requires_human_input": True},
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
                    "occurred_at": finished_at.isoformat(),
                    "duration_ms": None,
                    "error_code": "discovery_run_timeout",
                    "details": {
                        "timeout_seconds": self.run_timeout_seconds,
                    },
                },
            ][-60:]
            run.finished_at = finished_at
        self.session.commit()
        return len(runs)

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
            *(run.agent_trace or []),
            {
                "phase": "stop",
                "tool": "discovery_orchestrator",
                "outcome": "failed",
                "observation": str(error)[:500],
                "decision": "停止运行并向用户报告可操作的失败原因。",
                "source_id": None,
                "company": None,
                "url": None,
                "occurred_at": datetime.now(UTC).isoformat(),
                "duration_ms": None,
                "error_code": getattr(error, "code", "discovery_source_failed"),
                "details": {},
            },
        ]
        run.finished_at = datetime.now(UTC)
        self.session.commit()

    def _build_search_plan(
        self,
        *,
        search_query: str | None,
        max_results: int,
    ) -> DiscoverySearchPlan:
        if self.adapter is None:
            raise RuntimeError("发现运行缺少来源适配器")
        builder = getattr(self.adapter, "build_search_plan", None)
        if callable(builder):
            return builder(query=search_query, max_results=max_results)

        source_id = self.adapter.source_id
        return DiscoverySearchPlan(
            query=search_query,
            allowed_source_ids=[source_id],
            routes=[
                DiscoveryPlanRoute(
                    source_id=source_id,
                    company=None,
                    source_url=self.adapter.source_url,
                    tool_sequence=["source_adapter"],
                )
            ],
            budget=DiscoveryPlanBudget(
                max_results=min(max_results, 20),
                max_analysis=(
                    5 if getattr(self.adapter, "auto_analyze_top", False) else 0
                ),
                max_concurrency=1,
            ),
            stop_conditions=[
                "max_results_reached",
                "source_route_exhausted",
            ],
        )

    @staticmethod
    def _plan_trace(
        plan: DiscoverySearchPlan,
        *,
        occurred_at: datetime,
    ) -> dict[str, object]:
        dedicated_count = sum(
            route.tool_sequence[0]
            in {"bytedance_public_job_adapter", "tencent_public_job_adapter"}
            for route in plan.routes
        )
        static_count = len(plan.routes) - dedicated_count
        return {
            "phase": "plan",
            "tool": "bounded_discovery_planner",
            "outcome": "selected",
            "observation": (
                f"已将 {len(plan.allowed_source_ids)} 个用户选择的官方来源锁定为"
                "本次访问白名单。"
            ),
            "decision": (
                f"{dedicated_count} 个来源优先使用专用 Adapter，"
                f"{static_count} 个来源直接使用受控页面验证；"
                "失败时只按计划内后续工具回退，并严格执行结果上限和停止条件。"
            ),
            "source_id": None,
            "company": None,
            "url": None,
            "occurred_at": occurred_at.isoformat(),
            "duration_ms": 0,
            "error_code": None,
            "details": {
                "plan_version": plan.version,
                "allowed_source_ids": plan.allowed_source_ids,
                "budget": plan.budget.model_dump(mode="json"),
                "stop_conditions": plan.stop_conditions,
            },
        }

    @staticmethod
    def _result_trace(
        *,
        discovered_count: int,
        strict_count: int,
        expanded_count: int,
        failure_count: int,
        duration_ms: int,
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
            "occurred_at": datetime.now(UTC).isoformat(),
            "duration_ms": duration_ms,
            "error_code": None,
            "details": {
                "output_count": discovered_count,
                "strict_count": strict_count,
                "expanded_count": expanded_count,
                "failure_count": failure_count,
            },
        }

    def _item_failure(self, index: int, stub: JobStub, error: Exception) -> str:
        identifier = stub.source_job_id or stub.detail_url
        return f"#{index} {identifier}: {str(error)[:300]}"
