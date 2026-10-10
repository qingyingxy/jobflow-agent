import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from src.config import Settings
from src.domain.discovery import DiscoveryRun, LeadProvider, SearchEvidence
from src.infrastructure.llm_client import StructuredModelResponse
from src.services import multiround_search as execution
from src.services import web_search_service
from src.services.job_lead_service import JobLeadService, LeadVerificationFailure
from src.services.lead_providers import LeadCandidate
from src.services.search_pipeline import SearchSnapshot
from src.services.search_planner import SearchTask


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode, invalid", [("agent", False), ("rule", False), ("agent", True)]
)
async def test_real_search_orchestration_observes_results_and_persists_decisions(
    db_session, monkeypatch, mode, invalid
):
    queries, inputs, client_settings = [], [], []

    class Provider:
        source_id = "test"

        async def discover(self):
            queries.append(self.query)
            self.last_evidence = {
                "raw_response": "fixture",
                "actual_queries": [self.query],
            }
            return [
                LeadCandidate(
                    provider=LeadProvider.EXTERNAL_AGENT,
                    source_url="https://example.com/jobs/1",
                    discovered_at=datetime.now(UTC),
                )
            ]

    def provider_factory(query, company_ids):
        assert company_ids == ["example"]
        provider = Provider()
        provider.query = query
        return provider

    class DecisionClient:
        model_name = "fake-search-decision"

        async def generate(self, request):
            payload = json.loads(request.messages[1].content)
            inputs.append(payload)
            if invalid:
                output = {
                    "action": "search_web",
                    "query_id": "outside_allowed_queries",
                    "reason": "invalid test decision",
                }
            elif len(inputs) == 1:
                selected = next(
                    option
                    for option in reversed(payload["query_options"])
                    if option["strategy"] == "同义岗位"
                )
                output = {
                    "action": "search_web",
                    "query_id": selected["query_id"],
                    "reason": "页面核验失败，切换同义岗位查询",
                }
            else:
                output = {
                    "action": "finish",
                    "query_id": None,
                    "reason": "补搜仍然重复，保留线索供后续处理",
                }
            return StructuredModelResponse(
                output=output,
                model=self.model_name,
                provider="fake",
                usage={"prompt_tokens": 20, "completion_tokens": 10},
            )

    def client_factory(settings):
        client_settings.append(settings)
        return DecisionClient()

    async def fail_verify(service, *, user_id, lead_id, **kwargs):
        lead = service.get_lead(user_id=user_id, lead_id=lead_id)
        lead.status = "NEEDS_USER"
        lead.failure_code = "lead_not_job_page"
        lead.failure_reason = "未找到岗位正文"
        service.session.commit()
        raise LeadVerificationFailure(
            code=lead.failure_code,
            message=lead.failure_reason,
            lead_id=lead_id,
        )

    settings = Settings(
        _env_file=None,
        web_search_decision_mode=mode,
        web_search_max_rounds=4,
        web_search_budget_seconds=5,
        web_search_verification_budget_seconds=1,
    )
    monkeypatch.setattr(execution, "get_settings", lambda: settings)
    monkeypatch.setattr(execution, "SessionLocal", sessionmaker(bind=db_session.bind))
    monkeypatch.setattr(
        execution, "enabled_company_source_hosts", lambda: {"example.com"}
    )
    monkeypatch.setattr(
        execution,
        "enabled_company_sources",
        lambda *args: [
            SimpleNamespace(id="example", company="Example", career_url="https://example.com/careers")
        ],
    )
    monkeypatch.setattr(execution, "create_structured_model_client", client_factory)
    monkeypatch.setattr(
        web_search_service, "create_web_search_provider", provider_factory
    )
    monkeypatch.setattr(JobLeadService, "verify_url", fail_verify)
    run = DiscoveryRun(
        id="agent-test",
        user_id="owner",
        source="test",
        source_url="https://example.com",
        started_at=datetime.now(UTC),
    )
    db_session.add(run)
    db_session.commit()
    original = "上海 2027 校招 AI应用开发"
    await execution.execute_multiround_search(
        run_id=run.id,
        user_id="owner",
        query=original,
        company_ids=["example"],
    )
    db_session.expire_all()
    evidence = list(db_session.scalars(select(SearchEvidence)))
    decisions = [step for step in run.agent_trace if step["tool"] == "search_decision"]
    assert queries[0] == original
    assert len(evidence) == len(queries)
    assert all(record.raw_response == "fixture" for record in evidence)
    if mode == "agent" and not invalid:
        assert len(queries) == len(inputs) == len(decisions) == 2
        assert inputs[0]["observation"]["verification_failures"] == {
            "lead_not_job_page": 1
        }
        assert inputs[1]["observation"]["search_history"][-1]["duplicate_count"] == 1
        assert inputs[0]["goal"]["company_ids"] == ["example"]
        assert all(query.startswith(original) for query in queries)
        assert client_settings[0].llm_max_retries == 0
        assert decisions[0]["details"]["usage"]["prompt_tokens"] == 20
        assert any(
            "搜索 Agent 建议结束" in step["decision"] for step in run.agent_trace
        )
    elif mode == "rule":
        assert len(queries) == 4
        assert not inputs and not decisions and not client_settings
    else:
        assert len(queries) == len(set(queries)) == 4
        assert len(inputs) == len(decisions) == 6
        assert all(query.startswith(original) for query in queries)
        assert all(
            step["error_code"] == "invalid_or_repeated_query" for step in decisions
        )
        assert (
            sum(step["tool"] == "search_decision_fallback" for step in run.agent_trace)
            == 3
        )


@pytest.mark.asyncio
async def test_target_reached_during_decision_prevents_another_provider_call(
    db_session, monkeypatch
):
    queries, callbacks = [], {}

    class Provider:
        source_id = "test"

        async def discover(self):
            queries.append(self.query)
            return []

    def provider_factory(query, company_ids):
        provider = Provider()
        provider.query = query
        return provider

    class DecisionClient:
        model_name = "fake-search-decision"

        async def generate(self, request):
            payload = json.loads(request.messages[1].content)
            assert payload["observation"]["useful_jobs"] == 0
            assert payload["observation"]["pending_verification"] == 1
            # The verification worker can publish new facts while this call awaits.
            callbacks["on_snapshot"](SearchSnapshot(1, 1, 0, 1, 4))
            return StructuredModelResponse(
                output={
                    "action": "search_web",
                    "query_id": payload["query_options"][0]["query_id"],
                    "reason": "继续查询",
                },
                model=self.model_name,
                provider="fake",
            )

    async def controlled_pipeline(**kwargs):
        callbacks.update(kwargs)
        await kwargs["search"](1, set())
        kwargs["on_snapshot"](SearchSnapshot(0, 0, 1, 0, 4))
        assert await kwargs["search"](2, set()) is None
        assert kwargs["get_stop_reason"]() == "达到有效岗位目标"

    settings = Settings(
        _env_file=None,
        web_search_decision_mode="agent",
        web_search_target_jobs=1,
    )
    monkeypatch.setattr(execution, "get_settings", lambda: settings)
    monkeypatch.setattr(execution, "SessionLocal", sessionmaker(bind=db_session.bind))
    monkeypatch.setattr(execution, "enabled_company_source_hosts", lambda: set())
    monkeypatch.setattr(execution, "enabled_company_sources", lambda *args: [])
    monkeypatch.setattr(
        execution, "create_structured_model_client", lambda _: DecisionClient()
    )
    monkeypatch.setattr(execution, "run_search_pipeline", controlled_pipeline)
    monkeypatch.setattr(
        web_search_service, "create_web_search_provider", provider_factory
    )
    run = DiscoveryRun(
        id="target-during-decision",
        user_id="owner",
        source="test",
        source_url="https://example.com",
        started_at=datetime.now(UTC),
    )
    db_session.add(run)
    db_session.commit()
    original = "上海 2027 校招 AI应用开发"
    await execution.execute_multiround_search(
        run_id=run.id,
        user_id="owner",
        query=original,
        company_ids=[],
    )
    assert queries == [original]


@pytest.mark.asyncio
async def test_agent_mode_routes_non_responses_provider_through_bounded_pipeline(
    monkeypatch,
):
    calls = []
    monkeypatch.setattr(
        web_search_service,
        "get_settings",
        lambda: Settings(
            _env_file=None,
            web_search_provider="bing_rss",
            web_search_decision_mode="agent",
        ),
    )

    async def dispatch(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(execution, "execute_multiround_search", dispatch)
    await web_search_service.execute_web_search(
        run_id="test",
        user_id="owner",
        query="上海校招",
        company_ids=["example"],
    )
    assert calls == [
        {
            "run_id": "test",
            "user_id": "owner",
            "query": "上海校招",
            "company_ids": ["example"],
        }
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["agent", "rule"])
async def test_probe_uses_shared_query_candidates_and_skips_downstream_analysis(
    db_session, monkeypatch, mode
):
    original = "上海 2027 校招 AI应用开发"
    tasks = [
        SearchTask(original, "原始条件"),
        SearchTask(original + " RAG", "同义岗位"),
    ]
    captured = {}

    async def pipeline(**kwargs):
        captured["feedback_wait_seconds"] = kwargs["feedback_wait_seconds"]

    async def analyze(session, **kwargs):
        captured["analysis_limit"] = kwargs["analysis_limit"]

    monkeypatch.setattr(
        execution,
        "get_settings",
        lambda: Settings(
            _env_file=None,
            web_search_decision_mode=mode,
        ),
    )
    monkeypatch.setattr(execution, "SessionLocal", sessionmaker(bind=db_session.bind))
    monkeypatch.setattr(
        web_search_service,
        "create_web_search_provider",
        lambda *args: SimpleNamespace(source_id="test"),
    )
    monkeypatch.setattr(execution, "run_search_pipeline", pipeline)
    monkeypatch.setattr(execution, "analyze_discovery_jobs", analyze)
    run = DiscoveryRun(
        id="shared-candidates",
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
        query=original,
        company_ids=[],
        query_tasks=tasks,
        analysis_limit=0,
        feedback_wait_seconds=1,
    )
    db_session.expire_all()
    plan = next(
        step["details"] for step in run.agent_trace if step["tool"] == "query_plan"
    )
    assert plan["planned_queries"] == [
        {"query": task.query, "strategy": task.strategy} for task in tasks
    ]
    assert plan["decision_mode"] == mode
    assert captured == {"feedback_wait_seconds": 1, "analysis_limit": 0}
