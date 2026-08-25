from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.domain.application import CandidateJob
from src.domain.discovery import JobLead, JobLeadStatus, LeadProvider
from src.domain.job import JobAvailabilityStatus, JobPosting
from src.infrastructure.database import Base
from src.services.browser_job_reader import BrowserPageSnapshot
from src.services.discovery_service import DiscoveryService
from src.services.discovery_sources import JobStub
from src.services.job_availability_service import JobAvailabilityService
from src.services.job_lead_service import JobLeadService, LeadVerificationFailure
from src.services.url_reader import FetchedResponse, URLFetchError


class MetricThreshold(BaseModel):
    model_config = ConfigDict(extra="forbid")

    minimum: float | None = Field(default=None, ge=0, le=1)
    maximum: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def require_one_bound(self) -> MetricThreshold:
        if (self.minimum is None) == (self.maximum is None):
            raise ValueError("指标阈值必须且只能设置 minimum 或 maximum")
        return self


class TrustedDiscoveryCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=80)
    category: str = Field(min_length=1, max_length=80)
    fixture: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=300)


class TrustedDiscoveryManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest_version: str
    dataset_version: str
    purpose: str
    scope_boundary: str
    thresholds: dict[str, MetricThreshold]
    cases: list[TrustedDiscoveryCase] = Field(min_length=1)

    @field_validator("cases")
    @classmethod
    def validate_cases(
        cls,
        cases: list[TrustedDiscoveryCase],
    ) -> list[TrustedDiscoveryCase]:
        ids = [case.id for case in cases]
        if len(ids) != len(set(ids)):
            raise ValueError("M13 评测 case id 必须唯一")
        unknown = sorted({case.fixture for case in cases} - set(SCENARIOS))
        if unknown:
            raise ValueError(f"未知 M13 fixture：{', '.join(unknown)}")
        return cases


class TrustedDiscoveryObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted: bool | None = None
    verified_official: bool | None = None
    non_job_accepted: bool | None = None
    duplicate_correct: bool | None = None
    snippet_polluted: bool | None = None
    availability_expected: str | None = None
    availability_actual: str | None = None
    browser_handoff_succeeded: bool | None = None
    failure_code: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class HTMLReader:
    def __init__(self, html: str, url: str) -> None:
        self.html = html
        self.url = url

    async def fetch(self, url: str) -> FetchedResponse:
        return FetchedResponse(
            requested_url=url,
            final_url=self.url,
            status_code=200,
            content_type="text/html; charset=utf-8",
            body=self.html.encode("utf-8"),
        )


class FailedReader:
    async def fetch(self, url: str) -> FetchedResponse:
        raise URLFetchError("fixture read failed")


class BrowserReader:
    async def read(self, url: str) -> BrowserPageSnapshot:
        return BrowserPageSnapshot(
            requested_url=url,
            final_url=url,
            title="Browser AI Engineer",
            raw_html=_job_html(title="Browser AI Engineer", company="Browser Co"),
            visible_text="Browser AI Engineer Job responsibilities Requirements Python",
        )


class OfficialAdapter:
    source_id = "official:m13-evaluation"
    source_url = "https://careers.example.com/jobs"

    def __init__(self, source_job_id: str = "evaluation-1") -> None:
        self.stub = JobStub(
            source_id=self.source_id,
            source_job_id=source_job_id,
            company="Evaluation Co",
            title="AI Engineer",
            locations=["Shanghai"],
            job_type="campus",
            published_at=datetime(2026, 8, 20, tzinfo=UTC),
            detail_url=f"https://careers.example.com/jobs/{source_job_id}",
            raw_content=(
                "AI Engineer. Campus recruitment. Location: Shanghai. "
                "Job responsibilities include evaluation systems. "
                "Requirements: Python and database experience."
            ),
        )

    async def list_jobs(self) -> list[JobStub]:
        return [self.stub]

    async def fetch_job(self, source_job_id: str) -> JobStub:
        return self.stub


@contextmanager
def _session() -> Iterator[Session]:
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


def _job_html(*, title: str = "AI Engineer", company: str = "Evaluation Co") -> str:
    return f"""
    <html><head><title>{title}</title></head><body>
      <h1>{title}</h1><p>Company: {company}.</p><p>Location: Shanghai.</p>
      <p>Campus recruitment. Job responsibilities include evaluation systems.</p>
      <p>Requirements: Python and database experience.</p>
    </body></html>
    """


async def _official_page_verified() -> TrustedDiscoveryObservation:
    with _session() as session:
        lead = JobLeadService(session).create_lead(
            user_id="eval",
            provider=LeadProvider.EXTERNAL_AGENT,
            source_url="https://careers.example.com/jobs/page-1",
        )
        result = await JobLeadService(session).verify_url(
            user_id="eval",
            lead_id=lead.id,
            reader=HTMLReader(_job_html(), lead.source_url),
            official_hosts={"careers.example.com"},
        )
        return TrustedDiscoveryObservation(
            accepted=True,
            verified_official=result.posting.verification_status
            == "VERIFIED_OFFICIAL",
        )


async def _non_job_rejected() -> TrustedDiscoveryObservation:
    with _session() as session:
        lead = JobLeadService(session).create_lead(
            user_id="eval",
            provider=LeadProvider.EXTERNAL_AGENT,
            source_url="https://careers.example.com/guide",
        )
        try:
            await JobLeadService(session).verify_url(
                user_id="eval",
                lead_id=lead.id,
                reader=HTMLReader(
                    "<html><title>Careers guide</title><body>Culture and FAQ</body></html>",
                    lead.source_url,
                ),
                official_hosts={"careers.example.com"},
            )
        except LeadVerificationFailure as error:
            failure_code = error.code
        else:
            failure_code = None
        posting_count = session.scalar(select(func.count(JobPosting.id))) or 0
        return TrustedDiscoveryObservation(
            accepted=posting_count > 0,
            non_job_accepted=posting_count > 0,
            failure_code=failure_code,
        )


async def _snippet_isolation() -> TrustedDiscoveryObservation:
    with _session() as session:
        lead = JobLeadService(session).create_lead(
            user_id="eval",
            provider=LeadProvider.EXTERNAL_AGENT,
            source_url="https://careers.example.com/jobs/clean",
            company_hint="Polluted Company",
            title_hint="Polluted Title",
            search_snippet="Location Mars and COBOL required",
        )
        result = await JobLeadService(session).verify_url(
            user_id="eval",
            lead_id=lead.id,
            reader=HTMLReader(_job_html(), lead.source_url),
            official_hosts={"careers.example.com"},
        )
        posting_text = " ".join(
            [
                result.posting.company or "",
                result.posting.title or "",
                result.posting.raw_content,
                *result.posting.locations,
            ]
        )
        polluted = any(item in posting_text for item in ("Polluted", "Mars", "COBOL"))
        return TrustedDiscoveryObservation(
            accepted=True,
            snippet_polluted=polluted,
        )


async def _dedupe_correct() -> TrustedDiscoveryObservation:
    with _session() as session:
        await DiscoveryService(session, OfficialAdapter()).run(user_id="eval")
        second = await DiscoveryService(session, OfficialAdapter()).run(user_id="eval")
        postings = session.scalar(select(func.count(JobPosting.id))) or 0
        candidates = session.scalar(select(func.count(CandidateJob.id))) or 0
        duplicate_lead = session.scalar(
            select(JobLead).where(JobLead.discovery_run_id == second.run.id)
        )
        return TrustedDiscoveryObservation(
            duplicate_correct=(
                postings == 1
                and candidates == 1
                and second.run.duplicate_count == 1
                and duplicate_lead is not None
                and duplicate_lead.status == JobLeadStatus.DUPLICATE.value
            ),
            details={"posting_count": postings, "candidate_count": candidates},
        )


async def _availability_active() -> TrustedDiscoveryObservation:
    with _session() as session:
        result = await DiscoveryService(session, OfficialAdapter()).run(user_id="eval")
        check = await JobAvailabilityService(session).check_url(
            user_id="eval",
            job_posting_id=result.job_posting_ids[0],
            reader=HTMLReader(_job_html(), "https://careers.example.com/jobs/evaluation-1"),
        )
        return TrustedDiscoveryObservation(
            availability_expected="ACTIVE",
            availability_actual=check.result_status,
        )


async def _availability_unknown() -> TrustedDiscoveryObservation:
    return await _availability_after_failures(1, "UNKNOWN")


async def _availability_stale() -> TrustedDiscoveryObservation:
    return await _availability_after_failures(3, "STALE")


async def _availability_after_failures(
    count: int,
    expected: str,
) -> TrustedDiscoveryObservation:
    with _session() as session:
        result = await DiscoveryService(session, OfficialAdapter()).run(user_id="eval")
        check = None
        for _ in range(count):
            check = await JobAvailabilityService(session).check_url(
                user_id="eval",
                job_posting_id=result.job_posting_ids[0],
                reader=FailedReader(),
            )
        assert check is not None
        return TrustedDiscoveryObservation(
            availability_expected=expected,
            availability_actual=check.result_status,
            failure_code=check.failure_code,
        )


async def _availability_closed() -> TrustedDiscoveryObservation:
    with _session() as session:
        result = await DiscoveryService(session, OfficialAdapter()).run(user_id="eval")
        check = await JobAvailabilityService(session).check_url(
            user_id="eval",
            job_posting_id=result.job_posting_ids[0],
            reader=HTMLReader(
                "<html><body><h1>AI Engineer</h1><p>This job is no longer available.</p></body></html>",
                "https://careers.example.com/jobs/evaluation-1",
            ),
        )
        return TrustedDiscoveryObservation(
            availability_expected=JobAvailabilityStatus.CLOSED.value,
            availability_actual=check.result_status,
        )


async def _browser_verified() -> TrustedDiscoveryObservation:
    with _session() as session:
        lead = JobLeadService(session).create_lead(
            user_id="eval",
            provider=LeadProvider.EXTERNAL_AGENT,
            source_url="https://careers.example.com/jobs/browser",
        )
        result = await JobLeadService(session).verify_browser(
            user_id="eval",
            lead_id=lead.id,
            reader=BrowserReader(),
            official_hosts={"careers.example.com"},
        )
        return TrustedDiscoveryObservation(
            accepted=True,
            verified_official=result.posting.verification_status
            == "VERIFIED_OFFICIAL",
            browser_handoff_succeeded=result.posting.source_type == "verified_browser",
        )


SCENARIOS: dict[str, Callable[[], Awaitable[TrustedDiscoveryObservation]]] = {
    "official_page_verified": _official_page_verified,
    "non_job_rejected": _non_job_rejected,
    "snippet_isolation": _snippet_isolation,
    "dedupe_correct": _dedupe_correct,
    "availability_active": _availability_active,
    "availability_unknown": _availability_unknown,
    "availability_stale": _availability_stale,
    "availability_closed": _availability_closed,
    "browser_verified": _browser_verified,
}


async def evaluate_trusted_discovery(
    manifest: TrustedDiscoveryManifest,
) -> dict[str, Any]:
    case_results: list[dict[str, Any]] = []
    observations: list[TrustedDiscoveryObservation] = []
    for case in manifest.cases:
        try:
            observation = await SCENARIOS[case.fixture]()
            error = None
        except Exception as caught:  # noqa: BLE001 - report every fixture failure
            observation = TrustedDiscoveryObservation()
            error = f"{type(caught).__name__}: {caught}"
        observations.append(observation)
        case_results.append(
            {
                **case.model_dump(mode="json"),
                "observation": observation.model_dump(mode="json"),
                "error": error,
                "passed": error is None and _case_passed(case.category, observation),
            }
        )

    metric_values = _metric_values(observations)
    metrics = {
        name: {
            "value": metric_values[name],
            "threshold": threshold.model_dump(exclude_none=True),
            "passed": _threshold_passed(metric_values[name], threshold),
        }
        for name, threshold in manifest.thresholds.items()
    }
    failure_distribution: dict[str, int] = {}
    for observation in observations:
        if observation.failure_code:
            failure_distribution[observation.failure_code] = (
                failure_distribution.get(observation.failure_code, 0) + 1
            )
    return {
        "manifest_version": manifest.manifest_version,
        "dataset_version": manifest.dataset_version,
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": {
            "fixture_only": True,
            "live_source_results_included": False,
            "boundary": manifest.scope_boundary,
        },
        "case_count": len(case_results),
        "passed_case_count": sum(item["passed"] for item in case_results),
        "all_thresholds_passed": all(item["passed"] for item in metrics.values()),
        "metrics": metrics,
        "verification_failure_distribution": failure_distribution,
        "cases": case_results,
    }


def _case_passed(
    category: str,
    observation: TrustedDiscoveryObservation,
) -> bool:
    if category == "official_verification":
        return observation.accepted is True and observation.verified_official is True
    if category == "non_job":
        return observation.non_job_accepted is False
    if category == "snippet_isolation":
        return observation.snippet_polluted is False
    if category == "dedupe":
        return observation.duplicate_correct is True
    if category == "availability":
        return observation.availability_actual == observation.availability_expected
    if category == "browser":
        return observation.browser_handoff_succeeded is True
    return False


def _metric_values(observations: list[TrustedDiscoveryObservation]) -> dict[str, float]:
    official = [item for item in observations if item.verified_official is not None]
    non_jobs = [item for item in observations if item.non_job_accepted is not None]
    dedupe = [item for item in observations if item.duplicate_correct is not None]
    pollution = [item for item in observations if item.snippet_polluted is not None]
    availability = [
        item for item in observations if item.availability_expected is not None
    ]
    browser = [
        item for item in observations if item.browser_handoff_succeeded is not None
    ]
    return {
        "official_verification_rate": _rate(official, lambda item: item.verified_official),
        "non_job_false_acceptance_rate": _rate(
            non_jobs,
            lambda item: item.non_job_accepted,
        ),
        "dedupe_accuracy": _rate(dedupe, lambda item: item.duplicate_correct),
        "search_snippet_pollution_rate": _rate(
            pollution,
            lambda item: item.snippet_polluted,
        ),
        "availability_status_accuracy": _rate(
            availability,
            lambda item: item.availability_actual == item.availability_expected,
        ),
        "browser_handoff_success_rate": _rate(
            browser,
            lambda item: item.browser_handoff_succeeded,
        ),
    }


def _rate(
    items: list[TrustedDiscoveryObservation],
    predicate: Callable[[TrustedDiscoveryObservation], object],
) -> float:
    if not items:
        return 0.0
    return sum(bool(predicate(item)) for item in items) / len(items)


def _threshold_passed(value: float, threshold: MetricThreshold) -> bool:
    if threshold.minimum is not None:
        return value >= threshold.minimum
    assert threshold.maximum is not None
    return value <= threshold.maximum


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# M13 Trusted Discovery Evaluation",
        "",
        "> 本报告只覆盖离线确定性 Fixture，不包含真实官网召回率，也不能扩展为真实网络验证 100% 准确。",
        "",
        f"- Cases: {report['passed_case_count']}/{report['case_count']}",
        f"- Thresholds passed: {report['all_thresholds_passed']}",
        "",
        "## Metrics",
        "",
        "| Metric | Value | Passed |",
        "| --- | ---: | --- |",
    ]
    for name, metric in report["metrics"].items():
        lines.append(f"| `{name}` | {metric['value']:.3f} | {metric['passed']} |")
    lines.extend(
        [
            "",
            "## Verification Failure Distribution",
            "",
            "```json",
            json.dumps(
                report["verification_failure_distribution"],
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run M13 trusted discovery evaluation")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output")
    parser.add_argument("--markdown")
    return parser.parse_args()


def main() -> None:
    arguments = _parse_args()
    manifest = TrustedDiscoveryManifest.model_validate_json(
        Path(arguments.manifest).read_text(encoding="utf-8")
    )
    report = asyncio.run(evaluate_trusted_discovery(manifest))
    serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if arguments.output:
        output_path = Path(arguments.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(serialized + "\n", encoding="utf-8")
    if arguments.markdown:
        markdown_path = Path(arguments.markdown)
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(render_markdown(report), encoding="utf-8")
    print(serialized)


if __name__ == "__main__":
    main()
