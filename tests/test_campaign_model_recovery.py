"""Durable retries of model decisions without repeating completed discovery."""
import asyncio
import json
import socket
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.domain.campaign import CampaignDiscoveryTask, CampaignWatch
from src.domain.company_source import DiscoveredCompany
from src.infrastructure.database import Base
from src.infrastructure.llm_client import (
    ChatMessage,
    ModelResponseError,
    ModelUnavailableError,
    OpenAICompatibleModelClient,
    StructuredModelRequest,
    model_error_diagnostics,
)
from src.services.campaign_discovery import enqueue_discovery, run_discovery_step
from src.services.campaign_service import utc
from tests.test_campaign_company_agent import Harness, action, step
from tests.test_company_discovery import HOME
from tests.test_company_discovery_queue import SETTINGS


async def run_due(factory, harness, now=None):
    return await run_discovery_step(factory, settings=SETTINGS, agent_factory=harness.factory,
                                    now=now or datetime.now(UTC) + timedelta(seconds=5))


@pytest.mark.asyncio
async def test_disk_checkpoint_survives_restart_and_resumes_without_repeating_tools(tmp_path):
    path = tmp_path / "restart.db"
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    first = Harness([action("search", query="2027 校招"), action("read", url=HOME),
                     action("extract"), ModelUnavailableError("offline")])
    with factory() as session:
        enqueue_discovery(session, "owner", 2027)
    for _ in range(4):
        assert await run_due(factory, first)
    with factory() as session:
        task = session.scalar(select(CampaignDiscoveryTask))
        saved = deepcopy(task.state)
        task_id, run_id, retry_at = task.id, task.run_id, utc(task.next_run_at)
        assert task.status == "waiting" and task.stage == "model_retry"
        assert task.lease_token is None and task.lease_until is None
        assert saved["planner"]["steps"] == 3
        assert saved["planner"]["reads"] == saved["planner"]["search_count"] == 1
        assert saved["planner"]["evidence"]["read_cache"]
        assert enqueue_discovery(session, "owner", 2027).state == saved
        assert utc(task.next_run_at) == retry_at  # Repeated clicks respect backoff.
    engine.dispose()

    # Only disk state survives; use a new engine, sessions and Agent instance.
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    factory = sessionmaker(bind=engine)
    resumed = Harness([action("verify"), action("finish")])
    assert not await run_due(factory, resumed, retry_at - timedelta(seconds=1))
    assert not resumed.contexts
    assert await run_due(factory, resumed, retry_at)
    assert await run_due(factory, resumed, retry_at + timedelta(seconds=5))
    with factory() as session:
        task = session.get(CampaignDiscoveryTask, task_id)
        assert task.status == "completed" and task.run_id == run_id
        assert task.error is None and task.state["planner"]["model_retry_at"] is None
        assert task.state["planner"]["model_retries"] == 1
        assert task.state["planner"]["steps"] == 5
        assert task.state["queries"] == saved["queries"]
        assert len(list(session.scalars(select(DiscoveredCompany)))) == 1
        assert len(list(session.scalars(select(CampaignWatch)))) == 1
        assert resumed.contexts[0]["pages"]
        assert resumed.contexts[0]["candidates"][0]["company_id"] == saved["verify_ids"][0]
        assert resumed.contexts[0]["budget"]["remaining_searches"] == 5
        assert resumed.searches == []
    engine.dispose()


@pytest.mark.asyncio
async def test_retries_back_off_and_stop_even_with_pending_companies(db_session):
    task = enqueue_discovery(db_session, "owner", 2027)
    harness = Harness([action("search", query="2027 校招"), action("read", url=HOME), action("extract"),
                       *(ModelUnavailableError("offline") for _ in range(4))])
    for _ in range(3):
        await step(db_session, harness)
    factory = sessionmaker(bind=db_session.bind)
    for attempt in range(4):
        db_session.refresh(task)
        assert await run_due(factory, harness, utc(task.next_run_at) + timedelta(seconds=1))
        db_session.refresh(task)
        planner = task.state["planner"]
        assert planner["steps"] == 3 and planner["search_count"] == planner["reads"] == 1
        assert db_session.scalar(select(DiscoveredCompany)).status == "pending"
        if attempt < 3:
            assert task.status == "waiting" and task.stage == "model_retry"
            assert planner["history"][-1]["result"]["retry_after_seconds"] == (30, 60, 120)[attempt]
            assert planner["model_retries"] == attempt + 1
        else:
            assert task.status == "blocked" and task.next_run_at is None
            assert planner["status"] == "failed" and planner["model_retry_exhausted"]
            assert "上限" in task.error
    assert not await run_due(factory, harness, datetime.now(UTC) + timedelta(days=3))
    saved = deepcopy(task.state)
    resumed = enqueue_discovery(db_session, "owner", 2027)
    assert resumed.state["planner"]["model_retries"] == 0
    assert resumed.state["planner"]["model_retry_at"] is None
    assert resumed.state["planner"]["evidence"] == saved["planner"]["evidence"]
    assert resumed.state["verify_ids"] == saved["verify_ids"]


@pytest.mark.asyncio
async def test_success_does_not_reset_total_retry_budget(db_session):
    task = enqueue_discovery(db_session, "owner", 2027)
    harness = Harness([ModelUnavailableError("offline"), action("search", query="2027 校招"),
                       ModelUnavailableError("offline")])
    factory = sessionmaker(bind=db_session.bind)
    await run_due(factory, harness)
    db_session.refresh(task)
    await run_due(factory, harness, utc(task.next_run_at))
    db_session.refresh(task)
    assert task.state["planner"]["decision_failures"] == 0 and task.error is None
    await run_due(factory, harness, utc(task.next_run_at))
    db_session.refresh(task)
    assert task.state["planner"]["model_retries"] == 2
    assert task.state["planner"]["history"][-1]["result"]["retry_after_seconds"] == 60


@pytest.mark.asyncio
@pytest.mark.parametrize("status,retry", [(401, False), (403, False), (422, False), (429, True), (503, True)])
async def test_http_errors_are_classified_before_retrying(db_session, status, retry):
    task = enqueue_discovery(db_session, "owner", 2027)
    harness = Harness([ModelResponseError("sensitive response", {"status_code": status, "api_key": "secret"})])
    await step(db_session, harness)
    db_session.refresh(task)
    assert task.status == ("waiting" if retry else "blocked")
    assert task.state["planner"]["model_error"]["status_code"] == status
    assert task.state["planner"]["model_error"]["retryable"] is retry
    assert "secret" not in json.dumps(task.state) and "sensitive response" not in json.dumps(task.state)


@pytest.mark.asyncio
async def test_waiting_model_does_not_hold_up_other_discovery_tasks(db_session):
    enqueue_discovery(db_session, "owner", 2027)
    unavailable = Harness([TimeoutError()])
    await step(db_session, unavailable)
    enqueue_discovery(db_session, "other", 2027)
    healthy = Harness([action("search", query="2027 其他公司")])
    assert await step(db_session, healthy)
    assert healthy.searches == ["2027 其他公司"]
    db_session.expire_all()
    waiting = db_session.scalar(select(CampaignDiscoveryTask).where(CampaignDiscoveryTask.user_id == "owner"))
    assert waiting.status == "waiting" and waiting.lease_token is None


@pytest.mark.asyncio
async def test_lost_lease_cannot_write_retry_state(db_session):
    task = enqueue_discovery(db_session, "owner", 2027)
    harness = Harness([])
    original = harness.factory

    def factory(session, claimed, **kwargs):
        agent = original(session, claimed, **kwargs)

        async def lose_lease(context):
            claimed.lease_token = "replacement-worker"
            session.commit()
            raise ModelUnavailableError("offline")

        agent.decide = lose_lease
        return agent

    harness.factory = factory
    await step(db_session, harness)
    db_session.refresh(task)
    assert task.lease_token == "replacement-worker"
    assert task.state.get("planner", {}).get("model_retries", 0) == 0


@pytest.mark.asyncio
async def test_shutdown_after_failure_checkpoint_keeps_retry_deadline(db_session):
    task = enqueue_discovery(db_session, "owner", 2027)
    harness = Harness([ModelUnavailableError("offline")])
    original, checkpointed = harness.factory, asyncio.Event()

    def factory(*args, **kwargs):
        agent = original(*args, **kwargs)
        advance = agent.advance

        async def hold(state, rows):
            await advance(state, rows)
            checkpointed.set()
            await asyncio.Event().wait()

        agent.advance = hold
        return agent

    harness.factory = factory
    running = asyncio.create_task(step(db_session, harness))
    await checkpointed.wait()
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    db_session.refresh(task)
    assert task.status == "waiting" and task.stage == "model_retry"
    assert utc(task.next_run_at) == datetime.fromisoformat(task.state["planner"]["model_retry_at"])
    assert task.lease_token is None and task.state["planner"]["model_retries"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,reason", [(httpx.ConnectError, "dns"), (httpx.ProxyError, "proxy"),
                                        (httpx.RemoteProtocolError, "remote_protocol"),
                                        (httpx.ReadError, "read")])
async def test_real_http_client_preserves_safe_connection_diagnostics(kind, reason):
    def fail(request):
        error = kind("secret: https://user:password@private.example/token", request=request)
        if kind is httpx.ConnectError:
            raise error from socket.gaierror(-2, "private.example")
        raise error

    client = OpenAICompatibleModelClient(base_url="https://model.example/v1", api_key="secret", model="test",
                                        transport=httpx.MockTransport(fail))
    request = StructuredModelRequest(schema_name="test", json_schema={"type": "object"},
        messages=[ChatMessage(role="user", content="Return JSON")], prompt_version="test", transport_retries=0)
    with pytest.raises(ModelUnavailableError) as caught:
        await client.generate(request)
    diagnostic = model_error_diagnostics(caught.value)
    assert diagnostic["transport_reason"] == reason and diagnostic["retryable"]
    assert diagnostic["transport_error_type"] == kind.__name__
    assert diagnostic["request_duration_ms"] >= 0
    encoded = json.dumps(diagnostic)
    assert not any(value in encoded for value in ("secret", "private.example", "password", "https://"))


def test_diagnostic_allowlist_rejects_arbitrary_details_and_handles_cause_cycles():
    error = ModelUnavailableError("private", {"status_code": "secret", "timeout_stage": "private",
                                              "timeout_seconds": "private", "request_duration_ms": 5})
    error.__cause__ = error
    result = model_error_diagnostics(error)
    assert result == {"type": "ModelUnavailableError", "cause_types": [], "retryable": True,
                      "request_duration_ms": 5}
