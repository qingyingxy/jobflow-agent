from __future__ import annotations

import argparse
import asyncio
import json
import platform
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.domain.application import CandidateJob
from src.domain.discovery import DiscoveryRun
from src.domain.job import JobPosting
from src.infrastructure.database import Base
from src.services.company_registry import CompanySource, enabled_company_sources
from src.services.discovery_service import DiscoveryService
from src.services.discovery_sources import (
    ByteDanceAdapter,
    JobStub,
    OfficialCompanyRegistryAdapter,
)
from src.services.url_reader import (
    FetchedResponse,
    SafeHTTPReader,
    URLFetchError,
    URLSafetyChecker,
    URLSafetyError,
)


class MetricThreshold(BaseModel):
    model_config = ConfigDict(extra="forbid")

    minimum: float | None = Field(default=None, ge=0, le=1)
    maximum: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def require_one_bound(self) -> MetricThreshold:
        if (self.minimum is None) == (self.maximum is None):
            raise ValueError("指标阈值必须且只能设置 minimum 或 maximum")
        return self


class DiscoveryExpected(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str | None = None
    discovered_count: int | None = Field(default=None, ge=0)
    strict_count: int | None = Field(default=None, ge=0)
    expanded_count: int | None = Field(default=None, ge=0)
    duplicate_count: int | None = Field(default=None, ge=0)
    unauthorized_access_occurred: bool | None = None
    trace_complete: bool | None = None
    tool_route_correct: bool | None = None
    fallback_correct: bool | None = None
    non_job_accepted: bool | None = None
    human_gate_correct: bool | None = None
    budget_compliant: bool | None = None
    state_consistent: bool | None = None


class DiscoveryEvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=80)
    category: str = Field(min_length=1, max_length=80)
    fixture: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=300)
    expected: DiscoveryExpected


class DiscoveryEvaluationManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest_version: str = Field(min_length=1, max_length=80)
    dataset_version: str = Field(min_length=1, max_length=80)
    purpose: str = Field(min_length=1, max_length=500)
    source_policy: str = Field(min_length=1, max_length=500)
    thresholds: dict[str, MetricThreshold]
    cases: list[DiscoveryEvaluationCase] = Field(min_length=1)

    @field_validator("cases")
    @classmethod
    def validate_cases(
        cls,
        value: list[DiscoveryEvaluationCase],
    ) -> list[DiscoveryEvaluationCase]:
        ids = [case.id for case in value]
        if len(ids) != len(set(ids)):
            raise ValueError("Discovery Agent 评测 case id 必须唯一")
        unknown = sorted({case.fixture for case in value} - set(SCENARIOS))
        if unknown:
            raise ValueError(f"未知 Discovery Agent fixture：{', '.join(unknown)}")
        return value


class DiscoveryObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str | None = None
    discovered_count: int | None = Field(default=None, ge=0)
    strict_count: int | None = Field(default=None, ge=0)
    expanded_count: int | None = Field(default=None, ge=0)
    duplicate_count: int | None = Field(default=None, ge=0)
    unauthorized_access_occurred: bool | None = None
    trace_complete: bool | None = None
    tool_route_correct: bool | None = None
    fallback_correct: bool | None = None
    non_job_accepted: bool | None = None
    human_gate_correct: bool | None = None
    budget_compliant: bool | None = None
    state_consistent: bool | None = None
    trace_phases: list[str] = Field(default_factory=list)
    trace_tools: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class MappingReader:
    def __init__(self, responses: dict[str, bytes | Exception]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    async def fetch(self, url: str) -> FetchedResponse:
        self.calls.append(url)
        response = self.responses.get(url)
        if isinstance(response, Exception):
            raise response
        if response is None:
            raise URLFetchError(f"Fixture 未登记 URL：{url}")
        return FetchedResponse(
            requested_url=url,
            final_url=url,
            status_code=200,
            content_type="text/html; charset=utf-8",
            body=response,
        )


class ByteDanceFixtureReader(MappingReader):
    def __init__(
        self,
        *,
        mode: str,
        responses: dict[str, bytes | Exception] | None = None,
    ) -> None:
        super().__init__(responses or {})
        self.mode = mode

    async def post_json(
        self,
        url: str,
        payload: object,
        *,
        headers: dict[str, str] | None = None,
    ) -> tuple[None, object]:
        self.calls.append(url)
        if self.mode == "failed":
            raise URLFetchError("字节 Fixture 接口不可用")
        if url == ByteDanceAdapter.filter_url:
            return None, {"code": 0, "data": {"city_list": []}}
        if self.mode == "empty":
            return None, {"code": 0, "data": {"job_post_list": [], "count": 0}}
        return None, _bytedance_payload()


class TencentFixtureReader(MappingReader):
    def __init__(
        self,
        *,
        mode: str,
        responses: dict[str, bytes | Exception] | None = None,
    ) -> None:
        super().__init__(responses or {})
        self.mode = mode

    async def fetch_json(self, url: str) -> tuple[None, object]:
        self.calls.append(url)
        if self.mode == "failed":
            raise URLFetchError("腾讯 Fixture 接口不可用")
        if urlsplit(url).path.endswith("/Query"):
            if self.mode == "empty":
                return None, {"Code": 200, "Data": {"Count": 0, "Posts": []}}
            return None, _tencent_query_payload()
        return None, _tencent_detail_payload()


class StubAdapter:
    source_id = "fixture:bounded-gate"
    source_url = "https://jobs.example.com/fixture"
    auto_analyze_top = True

    def __init__(self, jobs: list[JobStub]) -> None:
        self.jobs = jobs

    async def list_jobs(self) -> list[JobStub]:
        return self.jobs

    async def fetch_job(self, source_job_id: str) -> JobStub:
        return next(job for job in self.jobs if job.source_job_id == source_job_id)


@contextmanager
def _evaluation_session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    try:
        with factory() as session:
            yield session
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def _source(source_id: str, company: str, url: str) -> CompanySource:
    return CompanySource(
        id=source_id,
        company=company,
        priority="A",
        career_url=url,
        entry_type="official_campus_page",
    )


async def _run_official(
    *,
    sources: list[CompanySource],
    query: str,
    reader: object,
    max_jobs: int = 20,
) -> tuple[DiscoveryObservation, list[dict[str, Any]]]:
    with _evaluation_session() as session:
        adapter = OfficialCompanyRegistryAdapter(
            sources=sources,
            query=query,
            reader=reader,  # type: ignore[arg-type]
            max_jobs=max_jobs,
            max_concurrency=1,
        )
        result = await DiscoveryService(session, adapter).run(user_id="evaluation-user")
        observation = _run_observation(result.run)
        return observation, list(result.run.agent_trace)


def _run_observation(run: DiscoveryRun) -> DiscoveryObservation:
    trace = list(run.agent_trace or [])
    matches = list(run.result_matches or [])
    return DiscoveryObservation(
        status=str(run.status),
        discovered_count=int(run.discovered_count),
        strict_count=sum(item.get("match_tier") == "strict" for item in matches),
        expanded_count=sum(item.get("match_tier") == "expanded" for item in matches),
        duplicate_count=int(run.duplicate_count),
        trace_complete=_trace_complete(trace),
        trace_phases=[str(step.get("phase", "")) for step in trace],
        trace_tools=[str(step.get("tool", "")) for step in trace],
    )


def _trace_complete(trace: list[dict[str, Any]]) -> bool:
    required = {"phase", "tool", "outcome", "observation", "decision"}
    if len(trace) < 2 or trace[0].get("phase") != "plan":
        return False
    if not any(step.get("phase") == "observe" for step in trace):
        return False
    if trace[-1].get("phase") not in {"observe", "human_gate", "stop"}:
        return False
    return all(
        required.issubset(step)
        and all(step.get(key) not in {None, ""} for key in required)
        and step.get("occurred_at") not in {None, ""}
        for step in trace
    )


def _has_route(trace: list[dict[str, Any]], tools: list[str]) -> bool:
    actual = [str(step.get("tool", "")) for step in trace]
    cursor = 0
    for tool in actual:
        if cursor < len(tools) and tool == tools[cursor]:
            cursor += 1
    return cursor == len(tools)


async def _unknown_company_blocked() -> DiscoveryObservation:
    try:
        enabled_company_sources(["not-registered"])
    except ValueError:
        blocked = True
    else:
        blocked = False
    return DiscoveryObservation(
        unauthorized_access_occurred=not blocked,
        details={"network_call_count": 0, "blocked_before_adapter": blocked},
    )


async def _private_url_blocked() -> DiscoveryObservation:
    network_calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal network_calls
        network_calls += 1
        return httpx.Response(200, request=request, text="should not be read")

    reader = SafeHTTPReader(
        safety_checker=URLSafetyChecker(resolver=lambda _host, _port: ["127.0.0.1"]),
        transport=httpx.MockTransport(handler),
    )
    try:
        await reader.fetch("http://127.0.0.1/private")
    except URLSafetyError:
        blocked = True
    else:
        blocked = False
    return DiscoveryObservation(
        unauthorized_access_occurred=not blocked or network_calls > 0,
        details={"network_call_count": network_calls, "blocked_before_request": blocked},
    )


async def _bytedance_success() -> DiscoveryObservation:
    reader = ByteDanceFixtureReader(mode="success")
    observation, trace = await _run_official(
        sources=[
            _source(
                "bytedance",
                "字节跳动",
                "https://jobs.bytedance.com/campus/",
            )
        ],
        query="AI Agent",
        reader=reader,
    )
    observation.tool_route_correct = _has_route(
        trace,
        [
            "bounded_discovery_planner",
            "bytedance_public_job_adapter",
            "candidate_validator",
        ],
    )
    return observation


async def _tencent_success() -> DiscoveryObservation:
    reader = TencentFixtureReader(mode="success")
    observation, trace = await _run_official(
        sources=[
            _source(
                "tencent",
                "腾讯",
                "https://careers.tencent.com/campusrecruit.html",
            )
        ],
        query="北京 AI Agent 校招",
        reader=reader,
    )
    observation.tool_route_correct = _has_route(
        trace,
        [
            "bounded_discovery_planner",
            "tencent_public_job_adapter",
            "candidate_validator",
        ],
    )
    return observation


async def _bytedance_failure_static_success() -> DiscoveryObservation:
    listing_url = "https://jobs.bytedance.com/campus/"
    detail_url = "https://jobs.bytedance.com/job/fixture-1"
    reader = ByteDanceFixtureReader(
        mode="failed",
        responses={
            listing_url: _listing_html(detail_url),
            detail_url: _job_detail_html(),
        },
    )
    observation, trace = await _run_official(
        sources=[_source("bytedance", "字节跳动", listing_url)],
        query="AI Agent 校招",
        reader=reader,
    )
    expected_route = [
        "bounded_discovery_planner",
        "bytedance_public_job_adapter",
        "visible_job_link_reader",
        "candidate_validator",
    ]
    observation.tool_route_correct = _has_route(trace, expected_route)
    observation.fallback_correct = (
        observation.discovered_count == 1
        and _has_route(trace, expected_route)
        and any(
            step.get("tool") == "bytedance_public_job_adapter"
            and step.get("phase") == "fallback"
            and step.get("error_code") == "url_fetch_failed"
            for step in trace
        )
    )
    return observation


async def _tencent_empty_static_success() -> DiscoveryObservation:
    listing_url = "https://careers.tencent.com/campusrecruit.html"
    detail_url = "https://careers.tencent.com/job/fixture-2"
    reader = TencentFixtureReader(
        mode="empty",
        responses={
            listing_url: _listing_html(detail_url),
            detail_url: _job_detail_html(title="腾讯 AI Agent 校园招聘工程师"),
        },
    )
    observation, trace = await _run_official(
        sources=[_source("tencent", "腾讯", listing_url)],
        query="AI Agent 校招",
        reader=reader,
    )
    expected_route = [
        "bounded_discovery_planner",
        "tencent_public_job_adapter",
        "visible_job_link_reader",
        "candidate_validator",
    ]
    observation.tool_route_correct = _has_route(trace, expected_route)
    observation.fallback_correct = (
        observation.discovered_count == 1
        and _has_route(trace, expected_route)
        and any(
            step.get("tool") == "tencent_public_job_adapter"
            and step.get("phase") == "fallback"
            and step.get("outcome") == "empty"
            for step in trace
        )
    )
    return observation


async def _dynamic_shell_human_gate() -> DiscoveryObservation:
    listing_url = "https://dynamic.example.com/campus"
    html = (
        "<html><head><title>校园招聘</title></head><body>"
        "<div id='app'>输入城市或职位进行搜索</div>"
        + "".join(f"<script src='/static/{index}.js'></script>" for index in range(6))
        + "</body></html>"
    ).encode()
    observation, trace = await _run_official(
        sources=[_source("dynamic", "动态官网", listing_url)],
        query="AI Agent 校招",
        reader=MappingReader({listing_url: html}),
    )
    observation.tool_route_correct = _has_route(
        trace,
        [
            "bounded_discovery_planner",
            "json_ld_job_parser → static_job_page_validator → visible_job_link_reader",
            "candidate_validator",
            "manual_jd_input",
        ],
    )
    observation.non_job_accepted = observation.discovered_count != 0
    observation.human_gate_correct = (
        observation.discovered_count == 0
        and trace[-1].get("phase") == "human_gate"
    )
    return observation


async def _guideline_rejected() -> DiscoveryObservation:
    listing_url = "https://campus.example.com/guideline"
    html = (
        "<html><head><title>校园招聘指南</title></head><body>"
        "<h1>校园招聘流程</h1><p>了解网申、测评、面试和录用流程。</p>"
        "<p>常见问题与投递注意事项请参考本页面说明。</p>"
        "</body></html>"
    ).encode()
    observation, trace = await _run_official(
        sources=[_source("guideline", "说明页公司", listing_url)],
        query="AI Agent 校招",
        reader=MappingReader({listing_url: html}),
    )
    observation.tool_route_correct = _has_route(
        trace,
        [
            "bounded_discovery_planner",
            "structured_data → static_html",
            "candidate_validator",
            "manual_jd_input",
        ],
    )
    observation.non_job_accepted = observation.discovered_count != 0
    observation.human_gate_correct = (
        observation.discovered_count == 0
        and trace[-1].get("phase") == "human_gate"
    )
    return observation


async def _jsonld_job_accepted() -> DiscoveryObservation:
    listing_url = "https://jsonld.example.com/jobs/agent-campus"
    observation, trace = await _run_official(
        sources=[_source("jsonld", "JSON-LD 公司", listing_url)],
        query="北京 AI Agent 校招",
        reader=MappingReader({listing_url: _jsonld_jobs_html(1)}),
    )
    observation.tool_route_correct = _has_route(
        trace,
        [
            "bounded_discovery_planner",
            "json_ld_job_parser",
            "candidate_validator",
        ],
    )
    return observation


async def _source_failure_isolated() -> DiscoveryObservation:
    broken_url = "https://broken.example.com/campus"
    valid_url = "https://healthy.example.com/jobs/agent-campus"
    reader = MappingReader(
        {
            broken_url: URLFetchError("来源暂时不可用"),
            valid_url: _jsonld_jobs_html(1),
        }
    )
    observation, trace = await _run_official(
        sources=[
            _source("broken", "失败来源", broken_url),
            _source("healthy", "正常来源", valid_url),
        ],
        query="北京 AI Agent 校招",
        reader=reader,
    )
    observation.tool_route_correct = _has_route(
        trace,
        [
            "bounded_discovery_planner",
            "safe_http_reader",
            "json_ld_job_parser",
            "candidate_validator",
        ],
    )
    observation.details["failed_source_isolated"] = (
        observation.discovered_count == 1
        and any(
            step.get("tool") == "safe_http_reader"
            and step.get("outcome") == "failed"
            for step in trace
        )
    )
    observation.fallback_correct = bool(
        observation.details["failed_source_isolated"]
    )
    return observation


async def _result_and_analysis_budget() -> DiscoveryObservation:
    listing_url = "https://many.example.com/jobs"
    with _evaluation_session() as session:
        adapter = OfficialCompanyRegistryAdapter(
            sources=[_source("many", "批量岗位公司", listing_url)],
            query="北京 AI Agent 校招",
            reader=MappingReader({listing_url: _jsonld_jobs_html(25)}),
            max_jobs=20,
            max_concurrency=1,
        )
        result = await DiscoveryService(session, adapter).run(
            user_id="evaluation-user"
        )
        observation = _run_observation(result.run)
        trace = list(result.run.agent_trace)
        observation.tool_route_correct = _has_route(
            trace,
            [
                "bounded_discovery_planner",
                "json_ld_job_parser",
                "candidate_validator",
            ],
        )
        observation.budget_compliant = (
            result.run.discovered_count == 20
            and observation.strict_count == 20
            and result.run.analysis_target_count == 5
            and len(result.analysis_job_posting_ids) == 20
        )
        observation.details["analysis_target_count"] = (
            result.run.analysis_target_count
        )
        return observation


async def _strict_expanded_gate() -> DiscoveryObservation:
    jobs = [
        _job_stub(
            "strict",
            title="AI Agent 算法工程师 - 校园招聘",
            locations=["北京"],
            job_type="campus",
        ),
        _job_stub(
            "expanded",
            title="Senior AI Agent Engineer",
            locations=["San Jose"],
            job_type="full_time",
        ),
    ]
    with _evaluation_session() as session:
        service = DiscoveryService(session, StubAdapter(jobs))
        run = service.create_run(
            user_id="evaluation-user",
            search_query="北京 AI Agent 校招岗位",
        )
        result = await service.run(user_id="evaluation-user", run=run)
        observation = _run_observation(result.run)
        observation.budget_compliant = (
            result.run.analysis_target_count == 1
            and result.analysis_job_posting_ids == [result.job_posting_ids[0]]
        )
        observation.details["analysis_target_count"] = result.run.analysis_target_count
        return observation


async def _duplicate_rerun_idempotent() -> DiscoveryObservation:
    adapter = StubAdapter([_job_stub("duplicate")])
    with _evaluation_session() as session:
        first = await DiscoveryService(session, adapter).run(user_id="evaluation-user")
        second = await DiscoveryService(session, adapter).run(user_id="evaluation-user")
        job_count = int(session.scalar(select(func.count(JobPosting.id))) or 0)
        candidate_count = int(session.scalar(select(func.count(CandidateJob.id))) or 0)
        observation = _run_observation(second.run)
        observation.state_consistent = (
            first.run.new_count == 1
            and second.run.duplicate_count == 1
            and job_count == 1
            and candidate_count == 1
        )
        observation.details.update(
            {"job_count": job_count, "candidate_count": candidate_count}
        )
        return observation


SCENARIOS: dict[str, Callable[[], Any]] = {
    "unknown_company_blocked": _unknown_company_blocked,
    "private_url_blocked": _private_url_blocked,
    "bytedance_success": _bytedance_success,
    "tencent_success": _tencent_success,
    "bytedance_failure_static_success": _bytedance_failure_static_success,
    "tencent_empty_static_success": _tencent_empty_static_success,
    "dynamic_shell_human_gate": _dynamic_shell_human_gate,
    "guideline_rejected": _guideline_rejected,
    "jsonld_job_accepted": _jsonld_job_accepted,
    "source_failure_isolated": _source_failure_isolated,
    "result_and_analysis_budget": _result_and_analysis_budget,
    "strict_expanded_gate": _strict_expanded_gate,
    "duplicate_rerun_idempotent": _duplicate_rerun_idempotent,
}


async def evaluate_discovery_agent(
    manifest: DiscoveryEvaluationManifest,
) -> dict[str, Any]:
    started_at = datetime.now(UTC)
    started_clock = perf_counter()
    case_reports: list[dict[str, Any]] = []
    observations: list[tuple[DiscoveryEvaluationCase, DiscoveryObservation, bool]] = []

    for case in manifest.cases:
        try:
            observation = await SCENARIOS[case.fixture]()
        except Exception as error:  # noqa: BLE001 - evaluation records case failures
            observation = DiscoveryObservation(
                error=f"{error.__class__.__name__}: {str(error)[:500]}"
            )
        expected = case.expected.model_dump(exclude_none=True)
        actual = observation.model_dump()
        checks = {
            key: {"expected": value, "actual": actual.get(key), "passed": actual.get(key) == value}
            for key, value in expected.items()
        }
        passed = observation.error is None and all(
            check["passed"] for check in checks.values()
        )
        observations.append((case, observation, passed))
        case_reports.append(
            {
                "id": case.id,
                "category": case.category,
                "fixture": case.fixture,
                "description": case.description,
                "passed": passed,
                "checks": checks,
                "trace_phases": observation.trace_phases,
                "trace_tools": observation.trace_tools,
                "details": observation.details,
                "error": observation.error,
            }
        )

    metrics = _metrics(observations, manifest.thresholds)
    passed_count = sum(passed for _, _, passed in observations)
    report = {
        "evaluation_version": "discovery-agent-control-plane-v1",
        "manifest_version": manifest.manifest_version,
        "dataset_version": manifest.dataset_version,
        "purpose": manifest.purpose,
        "source_policy": manifest.source_policy,
        "scope": {
            "mode": "offline_deterministic_fixtures",
            "live_source_results_included": False,
            "claim_boundary": (
                "验证受控发现流程的安全、路由、轨迹、回退和状态边界；"
                "不代表真实官网召回率或端到端语义准确率。"
            ),
        },
        "case_count": len(observations),
        "passed_case_count": passed_count,
        "case_pass_rate": passed_count / len(observations),
        "all_thresholds_passed": all(item["passed"] for item in metrics.values()),
        "metrics": metrics,
        "cases": case_reports,
        "limitations": [
            "场景使用固定离线响应，不能衡量招聘官网实时可用性或岗位召回率。",
            "非岗位误收率只覆盖清单中的动态壳与招聘指南负例，不等于互联网总体误收率。",
            "本评测验证控制面与用户可见轨迹，不替代 39 条 JD Parser 字段评测。",
            "字节与腾讯 Fixture 固化当前公开接口契约，官网接口变化仍需单独实时验收。",
        ],
        "run": {
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(UTC).isoformat(),
            "duration_ms": round((perf_counter() - started_clock) * 1000, 2),
            "python_version": sys.version.split()[0],
            "platform": platform.platform(),
        },
    }
    return report


def _metrics(
    observations: list[tuple[DiscoveryEvaluationCase, DiscoveryObservation, bool]],
    thresholds: dict[str, MetricThreshold],
) -> dict[str, dict[str, Any]]:
    metric_specs = {
        "case_pass_rate": (None, True),
        "unauthorized_source_access_rate": ("unauthorized_access_occurred", False),
        "trace_completeness_rate": ("trace_complete", True),
        "tool_route_accuracy": ("tool_route_correct", True),
        "fallback_correctness_rate": ("fallback_correct", True),
        "non_job_false_accept_rate": ("non_job_accepted", False),
        "human_gate_accuracy": ("human_gate_correct", True),
        "budget_compliance_rate": ("budget_compliant", True),
        "state_consistency_rate": ("state_consistent", True),
    }
    result: dict[str, dict[str, Any]] = {}
    for metric_name, (field_name, positive) in metric_specs.items():
        if field_name is None:
            values = [passed for _, _, passed in observations]
        else:
            values = [
                bool(getattr(observation, field_name))
                for case, observation, _ in observations
                if getattr(case.expected, field_name) is not None
            ]
        numerator = sum(values)
        denominator = len(values)
        value = numerator / denominator if denominator else None
        threshold = thresholds[metric_name]
        passed = _threshold_passed(value, threshold)
        result[metric_name] = {
            "value": value,
            "numerator": numerator,
            "denominator": denominator,
            "direction": "higher_is_better" if positive else "lower_is_better",
            "threshold": threshold.model_dump(exclude_none=True),
            "passed": passed,
        }
    return result


def _threshold_passed(value: float | None, threshold: MetricThreshold) -> bool:
    if value is None:
        return False
    if threshold.minimum is not None:
        return value >= threshold.minimum
    assert threshold.maximum is not None
    return value <= threshold.maximum


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# M12 Discovery Agent 控制面评测",
        "",
        f"> 数据集：`{report['dataset_version']}`  ",
        f"> 场景：{report['passed_case_count']}/{report['case_count']} 通过  ",
        "> 模式：离线确定性 Fixture，不包含实时官网结果",
        "",
        "## 评测边界",
        "",
        report["scope"]["claim_boundary"],
        "",
        "## 聚合指标",
        "",
        "| 指标 | 结果 | 阈值 | 状态 |",
        "|---|---:|---:|---|",
    ]
    for name, metric in report["metrics"].items():
        threshold = metric["threshold"]
        threshold_text = (
            f">= {threshold['minimum']:.0%}"
            if "minimum" in threshold
            else f"<= {threshold['maximum']:.0%}"
        )
        value_text = (
            "undefined"
            if metric["value"] is None
            else f"{metric['value']:.2%} ({metric['numerator']}/{metric['denominator']})"
        )
        lines.append(
            f"| `{name}` | {value_text} | {threshold_text} | "
            f"{'PASS' if metric['passed'] else 'FAIL'} |"
        )

    lines.extend(
        [
            "",
            "## 场景结果",
            "",
            "| 场景 | 类别 | 结果 |",
            "|---|---|---|",
        ]
    )
    for case in report["cases"]:
        lines.append(
            f"| `{case['id']}` | {case['category']} | "
            f"{'PASS' if case['passed'] else 'FAIL'} |"
        )

    lines.extend(["", "## 限制", ""])
    lines.extend(f"- {item}" for item in report["limitations"])
    lines.extend(
        [
            "",
            "## 复现命令",
            "",
            "```text",
            "uv run python -m src.evaluation.discovery_agent `",
            "  --manifest datasets/m12_discovery_agent_manifest.json `",
            "  --output docs/evaluation/m12-discovery-agent-summary.json `",
            "  --markdown docs/DISCOVERY_AGENT_EVALUATION.md",
            "```",
            "",
            "简历只能表述为“13 个离线控制面场景全部通过”；不能扩展为“真实官网搜索 100% 准确”。",
            "",
        ]
    )
    return "\n".join(lines)


def _listing_html(detail_url: str) -> bytes:
    return (
        "<html><head><title>校园招聘职位</title></head><body>"
        f"<a href='{detail_url}'>AI Agent 校园招聘工程师</a>"
        "</body></html>"
    ).encode()


def _job_detail_html(title: str = "AI Agent 校园招聘工程师") -> bytes:
    return (
        f"<html><head><title>{title}</title></head><body>"
        f"<h1>{title}</h1>"
        "<p>岗位职责：负责大模型 Agent 平台开发和服务评测。</p>"
        "<p>职位要求：熟悉 Python，面向应届毕业生，工作地点北京。</p>"
        "</body></html>"
    ).encode()


def _jsonld_jobs_html(count: int) -> bytes:
    jobs = [
        {
            "@context": "https://schema.org",
            "@type": "JobPosting",
            "title": f"AI Agent 算法工程师 {index} - 校园招聘",
            "description": "负责 AI Agent 和大模型算法研发，要求熟悉 Python。",
            "employmentType": "campus",
            "url": f"https://many.example.com/jobs/{index}",
            "jobLocation": {
                "@type": "Place",
                "address": {
                    "@type": "PostalAddress",
                    "addressLocality": "北京",
                },
            },
            "hiringOrganization": {
                "@type": "Organization",
                "name": "评测公司",
            },
        }
        for index in range(1, count + 1)
    ]
    payload: object = jobs[0] if count == 1 else jobs
    return (
        "<html><head><title>AI Agent 校园招聘</title>"
        "<script type='application/ld+json'>"
        f"{json.dumps(payload, ensure_ascii=False)}"
        "</script></head><body><h1>AI Agent 校园招聘</h1></body></html>"
    ).encode()


def _job_stub(
    source_job_id: str,
    *,
    title: str = "AI Agent 算法工程师 - 校园招聘",
    locations: list[str] | None = None,
    job_type: str = "campus",
) -> JobStub:
    return JobStub(
        source_id="fixture:bounded-gate",
        source_job_id=source_job_id,
        company="评测公司",
        title=title,
        locations=locations or ["北京"],
        job_type=job_type,
        published_at=None,
        detail_url=f"https://jobs.example.com/jobs/{source_job_id}",
        raw_content=f"{title}，负责 AI Agent 和大模型平台开发，要求熟悉 Python。",
    )


def _bytedance_payload() -> dict[str, object]:
    return {
        "code": 0,
        "data": {
            "job_post_list": [
                {
                    "id": "7668536218151028997",
                    "code": "A133837A",
                    "title": "AI Agent开发工程师 - 校园招聘",
                    "description": "负责 AI 应用和 Agent 工具搭建，参与产品技术选型。",
                    "requirement": "熟练掌握 Python，具备扎实计算机基础和学习能力。",
                    "job_category": {"name": "研发", "en_name": "R&D"},
                    "recruit_type": {"id": "202", "i18n_name": "校园招聘"},
                    "city_info": {"code": "CT_11", "i18n_name": "北京"},
                }
            ],
            "count": 1,
        },
    }


def _tencent_query_payload() -> dict[str, object]:
    return {
        "Code": 200,
        "Data": {
            "Count": 1,
            "Posts": [
                {
                    "PostId": "2052685072754196480",
                    "RecruitPostName": "混元 AI Agent 工程师",
                    "LocationName": "北京",
                    "Responsibility": "参与 AI Agent 执行链路和评测系统建设。",
                    "LastUpdateTime": "2026年08月06日",
                }
            ],
        },
    }


def _tencent_detail_payload() -> dict[str, object]:
    item = dict(_tencent_query_payload()["Data"]["Posts"][0])  # type: ignore[index]
    item.update(
        {
            "Requirement": "熟悉 LLM、Agent Framework 和 Prompt Engineering。",
            "ImportantItem": "有 Agent 可观测性系统开发经验者优先。",
            "RequireWorkYearsName": "不限",
        }
    )
    return {"Code": 200, "Data": item}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run deterministic Discovery Agent control-plane evaluation"
    )
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output")
    parser.add_argument("--markdown")
    return parser.parse_args()


def main() -> int:
    arguments = _parse_args()
    manifest_path = Path(arguments.manifest)
    manifest = DiscoveryEvaluationManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    report = asyncio.run(evaluate_discovery_agent(manifest))
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if arguments.output:
        output_path = Path(arguments.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered, encoding="utf-8")
    if arguments.markdown:
        markdown_path = Path(arguments.markdown)
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(render_markdown(report), encoding="utf-8")
    print(
        "discovery-agent-evaluation "
        f"dataset={report['dataset_version']} "
        f"cases={report['passed_case_count']}/{report['case_count']} "
        f"thresholds={'passed' if report['all_thresholds_passed'] else 'failed'}"
    )
    if arguments.output:
        print(f"report={arguments.output}")
    if arguments.markdown:
        print(f"markdown={arguments.markdown}")
    return 0 if report["all_thresholds_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
