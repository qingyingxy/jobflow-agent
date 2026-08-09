from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from src.config import get_settings
from src.domain.discovery import DiscoveryRun, DiscoveryRunStatus
from src.infrastructure.database import SessionLocal
from src.infrastructure.llm_client import (
    ModelClientError,
    create_structured_model_client,
)
from src.services.company_registry import (
    company_source_hosts,
    enabled_company_sources,
)
from src.services.discovery_service import DiscoveryFailure, DiscoveryService
from src.services.discovery_sources import OfficialCompanyRegistryAdapter
from src.services.evidence_matcher import EvidenceMatcher
from src.services.jd_analysis_service import JDAnalysisService
from src.services.staged_jd_parser import StagedJDParser
from src.services.url_reader import SafeHTTPReader

OFFICIAL_SEARCH_MAX_RESULTS = 20
OFFICIAL_SEARCH_ANALYSIS_LIMIT = 5


def execute_official_search_in_worker(
    *,
    run_id: str,
    user_id: str,
    query: str,
    company_ids: list[str] | None = None,
) -> None:
    """Keep network and model work off the API server's event loop."""

    asyncio.run(
        execute_official_search(
            run_id=run_id,
            user_id=user_id,
            query=query,
            company_ids=company_ids,
        )
    )


async def execute_official_search(
    *,
    run_id: str,
    user_id: str,
    query: str,
    company_ids: list[str] | None = None,
) -> None:
    """Run one official-site search and analyze up to five strict matches."""

    with SessionLocal() as session:
        run = session.get(DiscoveryRun, run_id)
        if run is None or run.user_id != user_id:
            return

        settings = get_settings()
        sources = enabled_company_sources(company_ids)
        adapter = OfficialCompanyRegistryAdapter(
            sources=sources,
            query=query,
            reader=SafeHTTPReader(
                timeout_seconds=8,
                max_retries=0,
                proxy=settings.url_fetch_proxy,
                proxy_allowed_hosts=company_source_hosts(sources),
                proxy_allow_unlisted_hosts=settings.url_fetch_proxy_allow_unlisted_hosts,
            ),
            max_jobs=OFFICIAL_SEARCH_MAX_RESULTS,
        )
        discovery = DiscoveryService(session, adapter)
        try:
            result = await discovery.run(user_id=user_id, run=run)
        except DiscoveryFailure:
            return
        except Exception as error:  # noqa: BLE001 - persist an actionable run failure
            session.rollback()
            _finish_run_with_failure(session, run_id, f"发现阶段：{str(error)[:500]}")
            return

        job_ids = result.analysis_job_posting_ids[:OFFICIAL_SEARCH_ANALYSIS_LIMIT]
        run = session.get(DiscoveryRun, run_id)
        if run is None:
            return
        run.analysis_target_count = len(job_ids)
        if not job_ids:
            run.analysis_status = "NOT_REQUESTED"
            run.status = (
                DiscoveryRunStatus.PARTIAL.value
                if run.failure_summary
                else DiscoveryRunStatus.SUCCEEDED.value
            )
            run.finished_at = datetime.now(UTC)
            session.commit()
            return

        run.analysis_status = "RUNNING"
        _append_agent_trace(
            run,
            phase="act",
            tool="staged_jd_parser → eligibility_checker → evidence_matcher",
            outcome="selected",
            observation=f"准备分析排序靠前的 {len(job_ids)} 条岗位。",
            decision="语义抽取交给模型，资格、证据和评分交给确定性代码。",
        )
        session.commit()

        try:
            parser, matcher = _analysis_dependencies()
        except ModelClientError as error:
            _finish_analysis_with_failure(
                session,
                run_id,
                len(job_ids),
                f"分析阶段：{str(error)[:500]}",
                failed_all=True,
            )
            return

        for job_id in job_ids:
            try:
                await JDAnalysisService(
                    session,
                    parser=parser,
                    matcher=matcher,
                ).analyze(user_id=user_id, job_id=job_id)
            except Exception as error:  # noqa: BLE001 - continue with remaining jobs
                session.rollback()
                _record_analysis_failure(session, run_id, job_id, error)
                continue

            run = session.get(DiscoveryRun, run_id)
            if run is None:
                return
            run.analysis_completed_count += 1
            session.commit()

        _finish_analysis(session, run_id)


def _analysis_dependencies() -> tuple[StagedJDParser, EvidenceMatcher]:
    settings = get_settings()
    client = create_structured_model_client(settings)
    parser = StagedJDParser(
        client,
        prompt_version=settings.staged_prompt_version,
        parser_version=settings.staged_parser_version,
        core_prompt_version=settings.core_prompt_version,
        detail_prompt_version=settings.detail_prompt_version,
        validation_retries=settings.parser_validation_retries,
    )
    return parser, EvidenceMatcher(client)


def _record_analysis_failure(
    session: Session,
    run_id: str,
    job_id: str,
    error: Exception,
) -> None:
    run = session.get(DiscoveryRun, run_id)
    if run is None:
        return
    run.analysis_failure_count += 1
    detail = f"岗位 {job_id}：{str(error)[:400]}"
    existing = run.failure_summary or ""
    run.failure_summary = f"{existing}\n{detail}".strip()[:4000]
    session.commit()


def _finish_analysis(session: Session, run_id: str) -> None:
    run = session.get(DiscoveryRun, run_id)
    if run is None:
        return
    run.analysis_status = (
        "PARTIAL" if run.analysis_failure_count else "SUCCEEDED"
    )
    run.status = (
        DiscoveryRunStatus.PARTIAL.value
        if run.analysis_failure_count or run.failure_summary
        else DiscoveryRunStatus.SUCCEEDED.value
    )
    _append_agent_trace(
        run,
        phase="observe",
        tool="analysis_validator",
        outcome="partial" if run.analysis_failure_count else "succeeded",
        observation=(
            f"完成 {run.analysis_completed_count}/{run.analysis_target_count} 条分析；"
            f"失败 {run.analysis_failure_count} 条。"
        ),
        decision="等待用户查看证据并决定是否准备申请。",
    )
    run.finished_at = datetime.now(UTC)
    session.commit()


def _finish_analysis_with_failure(
    session: Session,
    run_id: str,
    target_count: int,
    detail: str,
    *,
    failed_all: bool,
) -> None:
    run = session.get(DiscoveryRun, run_id)
    if run is None:
        return
    run.analysis_target_count = target_count
    run.analysis_failure_count = target_count if failed_all else 1
    run.analysis_status = "FAILED"
    existing = run.failure_summary or ""
    run.failure_summary = f"{existing}\n{detail}".strip()[:4000]
    run.status = DiscoveryRunStatus.PARTIAL.value
    _append_agent_trace(
        run,
        phase="fallback",
        tool="analysis_validator",
        outcome="failed",
        observation=detail,
        decision="不保存半成品分析，保留岗位事实并向用户报告失败。",
    )
    run.finished_at = datetime.now(UTC)
    session.commit()


def _finish_run_with_failure(session: Session, run_id: str, detail: str) -> None:
    run = session.get(DiscoveryRun, run_id)
    if run is None:
        return
    run.status = DiscoveryRunStatus.FAILED.value
    run.analysis_status = "FAILED"
    run.failure_summary = detail[:4000]
    _append_agent_trace(
        run,
        phase="stop",
        tool="discovery_orchestrator",
        outcome="failed",
        observation=detail,
        decision="停止运行并保留失败轨迹。",
    )
    run.finished_at = datetime.now(UTC)
    session.commit()


def _append_agent_trace(
    run: DiscoveryRun,
    *,
    phase: str,
    tool: str,
    outcome: str,
    observation: str,
    decision: str,
) -> None:
    run.agent_trace = [
        *(run.agent_trace or []),
        {
            "phase": phase,
            "tool": tool,
            "outcome": outcome,
            "observation": observation[:500],
            "decision": decision[:500],
            "source_id": None,
            "company": None,
            "url": None,
        },
    ][-60:]
