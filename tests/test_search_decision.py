import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError

from src.config import Settings
from src.infrastructure.llm_client import (
    FakeModelClient,
    ModelUnavailableError,
    OpenAICompatibleModelClient,
)
from src.services.search_decision import SearchDecisionPlanner, query_options
from src.services.search_planner import (
    SearchTask,
    build_agent_search_tasks,
    query_identity,
)

GOAL = "上海 2027 校招 AI应用开发"
TASKS = build_agent_search_tasks(GOAL)


def observation(**updates):
    return {
        "verified_jobs": 0,
        "useful_jobs": 0,
        "pending_verification": 2,
        "target_jobs": 5,
        "remaining_search_calls": 3,
        "remaining_seconds": 10,
        "completed_queries": [GOAL],
        "search_history": [{"new_links": 2, "duplicate_count": 8}],
        **updates,
    }


def valid_decision():
    return {
        "action": "search_web",
        "query_id": next(reversed(query_options(TASKS, [GOAL]))),
        "reason": "重复结果较多，尝试同义岗位",
    }


def planner(client, *, max_calls=6, timeout=1):
    events = []
    policy = SearchDecisionPlanner(
        lambda: client,
        max_calls=max_calls,
        timeout_seconds=timeout,
        on_event=lambda kind, details: events.append((kind, details)),
    )
    return policy, events


async def choose(policy, **updates):
    return await policy.choose(
        original_query=GOAL,
        company_ids=["company-a"],
        tasks=TASKS,
        observation=observation(**updates),
    )


def test_query_compiler_preserves_unknown_constraints_and_company_names():
    original = "只看数据堂 上海或杭州 2027校招 AI应用开发 不接受外包"
    sources = [SimpleNamespace(company="数据堂", career_url="https://jobs.example/")]
    tasks = build_agent_search_tasks(original, sources)
    assert len(tasks) > 2
    assert all(t.query.startswith(original) for t in tasks)
    assert any("site:jobs.example" in t.query for t in tasks)
    assert any(t.strategy == "同义岗位" for t in tasks)
    assert len({query_identity(t.query) for t in tasks}) == len(tasks)


def test_options_exclude_normalized_duplicates():
    tasks = [SearchTask("Python 上海", "test"), SearchTask("SQL 上海", "test")]
    options = query_options(tasks, [" ＰＹＴＨＯＮ   上海 "])
    assert [task.query for task in options.values()] == ["SQL 上海"]


@pytest.mark.asyncio
async def test_model_selects_a_query_from_observation_and_records_usage():
    client = FakeModelClient(output=valid_decision())
    policy, events = planner(client)
    result = await choose(policy)
    assert result.action == "search_web"
    assert result.task == query_options(TASKS, [GOAL])[valid_decision()["query_id"]]
    payload = json.loads(client.last_request.messages[1].content)
    assert payload["observation"]["pending_verification"] == 2
    assert payload["observation"]["search_history"][0]["duplicate_count"] == 8
    assert payload["goal"] == {"original_query": GOAL, "company_ids": ["company-a"]}
    assert all(option["query"] != GOAL for option in payload["query_options"])
    assert events[0][1]["selected_query"] == result.task.query
    assert events[0][1]["decision_calls"] == 1
    assert "usage" in events[0][1]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid",
    [
        {"action": "expand_entry", "query_id": "https://evil.example", "reason": "x"},
        {"action": "search_web", "query_id": "unknown", "reason": "x"},
        {"action": "search_web", "query": "北京 2026 社招", "reason": "x"},
        {**valid_decision(), "company_ids": ["unauthorized-company"]},
        {"action": "finish", "query_id": "something", "reason": "x"},
        {"action": "finish", "query_id": None, "reason": "   "},
    ],
)
async def test_invalid_scope_or_action_gets_at_most_one_repair(invalid):
    client = FakeModelClient(outputs=[invalid, invalid])
    policy, events = planner(client)
    result = await choose(policy)
    assert result.action == "fallback"
    assert policy.calls == len(client.requests) == 2
    assert events[-1][0] == "search_decision_fallback"
    assert "校验错误" in client.last_request.messages[-1].content


@pytest.mark.asyncio
async def test_repair_can_select_a_valid_query_but_cannot_replay_a_completed_query():
    used_id = next(iter(query_options(TASKS[:1], [])))
    client = FakeModelClient(
        outputs=[
            {"action": "search_web", "query_id": used_id, "reason": "repeat"},
            valid_decision(),
        ]
    )
    policy, events = planner(client)
    result = await choose(policy)
    assert result.action == "search_web"
    assert result.task.query != GOAL
    assert policy.calls == 2
    assert events[0][1]["error_code"] == "invalid_or_repeated_query"
    assert events[1][1]["error_code"] is None


@pytest.mark.asyncio
async def test_repair_consumes_call_budget_and_future_decisions_fall_back():
    client = FakeModelClient(output={"unexpected": True})
    policy, _ = planner(client, max_calls=1)
    assert (await choose(policy)).action == "fallback"
    assert (await choose(policy)).reason == "decision_call_budget_exhausted"
    assert len(client.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"remaining_seconds": 0},
        {"remaining_search_calls": 0},
        {"completed_queries": [task.query for task in TASKS]},
    ],
)
async def test_no_model_call_when_execution_budget_or_options_are_exhausted(changes):
    client = FakeModelClient(output=valid_decision())
    policy, _ = planner(client)
    assert (await choose(policy, **changes)).action == "fallback"
    assert not client.requests


@pytest.mark.asyncio
async def test_timeout_cancels_model_and_falls_back_without_retry():
    cancelled = asyncio.Event()

    class SlowClient:
        model_name = "slow-test"

        async def generate(self, request):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    policy, events = planner(SlowClient(), timeout=0.02)
    assert (await choose(policy)).reason == "decision_timeout"
    assert cancelled.is_set()
    assert policy.calls == 1
    assert events[0][1]["error_code"] == "decision_timeout"


@pytest.mark.asyncio
async def test_provider_error_is_not_retried_or_exposed_as_raw_exception():
    client = FakeModelClient(error=ModelUnavailableError("private provider error"))
    policy, events = planner(client)
    assert (await choose(policy)).action == "fallback"
    assert len(client.requests) == 1
    assert "private provider error" not in json.dumps(events)


@pytest.mark.asyncio
async def test_malformed_json_repair_preserves_usage_from_actual_client_protocol():
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": f"response-{len(requests)}",
                "model": "test-model",
                "choices": [
                    {
                        "message": {
                            "content": (
                                "not JSON"
                                if len(requests) == 1
                                else json.dumps(valid_decision())
                            )
                        }
                    }
                ],
                "usage": {"prompt_tokens": 30, "completion_tokens": 12},
            },
        )

    client = OpenAICompatibleModelClient(
        base_url="https://model.example/v1",
        api_key="test",
        model="test-model",
        max_retries=0,
        transport=httpx.MockTransport(respond),
    )
    policy, events = planner(client)
    result = await choose(policy)
    assert result.action == "search_web"
    assert policy.calls == len(requests) == 2
    assert events[0][1]["error_code"] == "invalid_model_response"
    assert events[0][1]["usage"] == {"prompt_tokens": 30, "completion_tokens": 12}
    assert events[0][1]["response_id"] == "response-1"
    assert events[1][1]["error_code"] is None
    assert all(request["max_tokens"] == 500 for request in requests)


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [ModelUnavailableError, ValueError])
async def test_client_initialization_error_falls_back_without_exposing_details(
    error_type,
):
    policy, events = planner(None)

    def broken_factory():
        raise error_type("private configuration error")

    policy.client_factory = broken_factory
    assert (await choose(policy)).reason == "decision_model_unavailable"
    assert policy.calls == 0
    assert "private configuration error" not in json.dumps(events)


@pytest.mark.asyncio
async def test_finish_is_allowed_with_pending_verification():
    client = FakeModelClient(
        output={
            "action": "finish",
            "query_id": None,
            "reason": "先完成现有线索核验",
        }
    )
    policy, _ = planner(client)
    result = await choose(policy)
    assert result.action == "finish"
    assert result.task is None


def test_configuration_requires_explicit_valid_mode_and_bounded_budget():
    assert Settings(_env_file=None).web_search_decision_mode == "rule"
    for options in (
        {"web_search_decision_mode": "unbounded"},
        {"web_search_decision_max_calls": -1},
        {"web_search_decision_timeout_seconds": 0},
    ):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, **options)
