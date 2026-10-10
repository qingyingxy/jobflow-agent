import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import sessionmaker

from src.config import Settings
from src.domain.discovery import DiscoveryRun, LeadProvider
from src.infrastructure.llm_client import FakeModelClient, StructuredModelResponse
from src.services import multiround_search as execution
from src.services import web_search_service
from src.services.job_lead_service import JobLeadService, LeadVerificationFailure
from src.services.lead_presentation import discovery_kind
from src.services.lead_providers import LeadCandidate
from src.services.search_decision import SearchDecisionPlanner
from src.services.search_pipeline import WaitForVerification, run_search_pipeline
from src.services.search_planner import SearchTask


def candidate(number):
    return LeadCandidate(
        provider=LeadProvider.EXTERNAL_AGENT,
        source_url=f"https://example.com/jobs/{number}",
        discovered_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("reaches_target", [True, False])
async def test_finish_checkpoint_rechecks_results_without_consuming_search_round(
    reaches_target,
):
    pause_started = asyncio.Event()
    calls, events, snapshots = [], [], []

    def on_event(kind, details):
        events.append(kind)
        if kind == "search_pause":
            pause_started.set()

    async def search(number, seen):
        calls.append(number)
        if len(calls) == 1:
            return [candidate(1)]
        if len(calls) == 2:
            return WaitForVerification("先核验现有线索")
        assert snapshots[-1].completed_verifications == 1
        assert snapshots[-1].useful_jobs == 0
        return [candidate(2)]

    async def verify(lead):
        await pause_started.wait()
        if lead.source_url.endswith("/1") and not reaches_target:
            return None
        return lead.source_url, True

    stop = await run_search_pipeline(
        search=search,
        verify=verify,
        report=lambda *args: None,
        canonicalize=lambda url: url,
        max_rounds=2,
        seconds=1,
        target=1,
        on_snapshot=snapshots.append,
        on_event=on_event,
    )
    assert snapshots[-1].useful_jobs == 1
    if reaches_target:
        assert calls == [1, 2]
        assert stop == "达到有效岗位目标"
        assert "search_resume" not in events
    else:
        assert calls == [1, 2, 2]
        assert "search_resume" in events


@pytest.mark.asyncio
async def test_slow_verification_checkpoint_reserves_search_time_and_can_be_cancelled():
    pause_started, cancelled = asyncio.Event(), asyncio.Event()

    async def search(number, seen):
        return [candidate(1)] if number == 1 else WaitForVerification("wait")

    async def verify(lead):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    def event(kind, details):
        if kind == "search_pause":
            assert 0 < details["timeout_seconds"] <= 0.5
            pause_started.set()

    task = asyncio.create_task(
        run_search_pipeline(
            search=search,
            verify=verify,
            report=lambda *args: None,
            canonicalize=lambda url: url,
            seconds=1,
            on_event=event,
        )
    )
    await asyncio.wait_for(pause_started.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_checkpoint_timeout_resumes_while_verification_is_still_inflight():
    resumed = asyncio.Event()
    calls, snapshots = [], []

    async def search(number, seen):
        calls.append(number)
        if len(calls) == 1:
            return [candidate(1)]
        if len(calls) == 2:
            return WaitForVerification("wait")
        assert snapshots[-1].pending_verification == 1
        assert snapshots[-1].completed_verifications == 0
        assert snapshots[-1].remaining_seconds > 0
        resumed.set()
        return []

    async def verify(lead):
        await resumed.wait()

    await run_search_pipeline(
        search=search,
        verify=verify,
        report=lambda *args: None,
        canonicalize=lambda url: url,
        seconds=0.2,
        item_seconds=1,
        max_rounds=2,
        on_snapshot=snapshots.append,
    )
    assert calls == [1, 2, 2]
    assert resumed.is_set()


@pytest.mark.asyncio
async def test_repeated_checkpoints_without_search_cannot_loop_forever():
    calls = []

    async def search(number, seen):
        calls.append(number)
        return WaitForVerification("wait")

    async def verify(lead):
        raise AssertionError("no leads")

    stop = await run_search_pipeline(
        search=search,
        verify=verify,
        report=lambda *args: None,
        canonicalize=lambda url: url,
    )
    assert calls == [1, 1]
    assert stop == "核验反馈后的搜索决策未推进"


@pytest.mark.asyncio
async def test_finish_is_rejected_after_checkpoint_and_repairs_share_call_budget():
    client = FakeModelClient(
        output={"action": "finish", "query_id": None, "reason": "wait"}
    )
    events = []
    planner = SearchDecisionPlanner(
        lambda: client,
        max_calls=2,
        timeout_seconds=1,
        on_event=lambda kind, details: events.append((kind, details)),
    )
    result = await planner.choose(
        original_query="上海校招",
        company_ids=[],
        tasks=[SearchTask("上海校招 RAG", "同义岗位")],
        observation={
            "remaining_seconds": 10,
            "remaining_search_calls": 2,
            "completed_queries": [],
            "must_search": True,
        },
    )
    assert result.action == "fallback"
    assert planner.calls == 2
    assert events[0][1]["error_code"] == "verification_incomplete_requires_search"
    assert client.last_request.json_schema["properties"]["action"]["enum"] == [
        "search_web"
    ]


@pytest.mark.parametrize(
    "url, expected",
    [
        (
            "https://jobs.bytedance.com/campus/position/7493360622731659527/detail",
            "job",
        ),
        (
            "https://jobs.bytedance.com/campus/position/7493360622731659527/detail?sourceJobId=123",
            "job",
        ),
        ("https://jobs.bytedance.com/experienced/position/123/detail/", "job"),
        ("https://example.com/#/jobs/ab-123/detail", "job"),
        ("https://example.com/positions/abc/detail.html", "job"),
        ("https://example.com/jobs/detail", "entry"),
        ("https://example.com/positions/search/detail", "entry"),
        ("https://example.com/positions/list/detail", "entry"),
        ("https://example.com/positions/list/detail.html", "entry"),
        ("https://jobs.bytedance.com/campus?sourceJobId=123", "entry"),
        ("https://jobs.bytedance.com/campus/position", "entry"),
    ],
)
def test_detail_identifiers_route_to_verification_but_list_pages_do_not(url, expected):
    assert discovery_kind(url) == expected


@pytest.mark.asyncio
async def test_real_orchestration_resumes_after_failed_bytedance_detail_verification(
    db_session, monkeypatch
):
    decision_started = asyncio.Event()
    inputs, queries, verified_urls = [], [], []
    detail_url = "https://jobs.bytedance.com/campus/position/7493360622731659527/detail"

    class Provider:
        source_id = "test"

        async def discover(self):
            queries.append(self.query)
            return [
                LeadCandidate(
                    provider=LeadProvider.EXTERNAL_AGENT,
                    source_url=detail_url,
                    discovered_at=datetime.now(UTC),
                )
            ]

    def provider_factory(query, company_ids):
        provider = Provider()
        provider.query = query
        return provider

    class Client:
        model_name = "fixture"

        async def generate(self, request):
            payload = json.loads(request.messages[1].content)
            inputs.append(payload)
            if len(inputs) == 1:
                assert payload["observation"]["pending_verification"] == 1
                decision_started.set()
                output = {"action": "finish", "query_id": None, "reason": "先核验"}
            elif len(inputs) == 2:
                observed = payload["observation"]
                assert observed["completed_verifications"] == 1
                assert observed["must_search"] is True
                assert observed["verification_failures"] == {"lead_not_job_page": 1}
                output = {
                    "action": "search_web",
                    "query_id": payload["query_options"][0]["query_id"],
                    "reason": "核验未通过，换一条查询",
                }
            else:
                output = {"action": "finish", "query_id": None, "reason": "补搜重复"}
            return StructuredModelResponse(
                output=output, model=self.model_name, provider="fake"
            )

    async def fail_verify(service, *, user_id, lead_id, **kwargs):
        lead = service.get_lead(user_id=user_id, lead_id=lead_id)
        verified_urls.append(lead.source_url)
        await decision_started.wait()
        lead.status = "NEEDS_USER"
        lead.failure_code = "lead_not_job_page"
        lead.failure_reason = "无法取得正文"
        service.session.commit()
        raise LeadVerificationFailure(
            code=lead.failure_code, message=lead.failure_reason, lead_id=lead.id
        )

    settings = Settings(
        _env_file=None,
        web_search_decision_mode="agent",
        web_search_max_rounds=3,
        web_search_budget_seconds=5,
    )
    monkeypatch.setattr(execution, "get_settings", lambda: settings)
    monkeypatch.setattr(execution, "SessionLocal", sessionmaker(bind=db_session.bind))
    monkeypatch.setattr(
        execution, "enabled_company_source_hosts", lambda: {"jobs.bytedance.com"}
    )
    monkeypatch.setattr(
        execution,
        "enabled_company_sources",
        lambda *args: [
            SimpleNamespace(
                id="bytedance", company="字节跳动", career_url="https://jobs.bytedance.com/campus"
            )
        ],
    )
    monkeypatch.setattr(execution, "create_structured_model_client", lambda _: Client())
    monkeypatch.setattr(
        web_search_service, "create_web_search_provider", provider_factory
    )
    monkeypatch.setattr(JobLeadService, "verify_url", fail_verify)
    run = DiscoveryRun(
        id="resume-test",
        user_id="owner",
        source="test",
        source_url="https://example.com",
        started_at=datetime.now(UTC),
    )
    db_session.add(run)
    db_session.commit()
    await execution.execute_multiround_search(
        run_id=run.id,
        user_id="owner",
        query="上海 2027 校招 AI应用开发",
        company_ids=[],
        analysis_limit=0,
    )
    db_session.expire_all()
    assert verified_urls == [detail_url]
    assert len(queries) == len(set(queries)) == 2
    assert len(inputs) == 3
    assert any(step["tool"] == "search_resume" for step in run.agent_trace)
