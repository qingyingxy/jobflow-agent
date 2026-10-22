import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from src.config import Settings
from src.domain.company_source import CompanyDiscoveryTask, DiscoveredCompany
from src.infrastructure.llm_client import FakeModelClient
from src.main import app
from src.services.company_discovery import CompanyDiscoveryAgent, diverse_company_links
from src.services.company_discovery_queue import (
    discovery_queries,
    discovery_queue_summary,
    enqueue_company_discovery,
    run_company_discovery_step,
)
from tests.test_company_discovery import CAREER, HOME, NAME, PROOF, Pages, goal, lead

SETTINGS = Settings(_env_file=None, structured_model_provider="openai_compatible")


class Harness:
    def __init__(self):
        self.searches = []
        self.pages = Pages()
        self.client = FakeModelClient(output={"companies": [
            {"company": NAME, "homepage_url": HOME, "career_url": CAREER}]})
        self.fail_search = False

    def factory(self, session, goal, task, *, settings, on_event, checkpoint):
        harness = self

        class Provider:
            timeout_seconds = 10

            async def discover(self):
                assert self.timeout_seconds == 60
                if harness.fail_search:
                    harness.fail_search = False
                    raise TimeoutError()
                return [lead(HOME), lead(PROOF)]

        def provider(query):
            self.searches.append(query)
            return Provider()

        return CompanyDiscoveryAgent(session, user_id=goal.user_id, run_id=task.run_id, query=goal.query,
            reader=self.pages, provider_factory=provider, client_factory=lambda: self.client,
            on_event=on_event, checkpoint=checkpoint, request_timeout=settings.company_discovery_request_timeout_seconds)


async def step(session, harness):
    return await run_company_discovery_step(sessionmaker(bind=session.bind), settings=SETTINGS,
        agent_factory=harness.factory, now=datetime.now(UTC) + timedelta(minutes=1))


@pytest.mark.asyncio
async def test_search_extraction_verification_resume_in_separate_sessions(db_session):
    item = goal(db_session)
    enqueue_company_discovery(db_session, item)
    harness = Harness()
    await step(db_session, harness)
    db_session.expire_all()
    task = db_session.get(CompanyDiscoveryTask, item.id)
    assert task.state["queries"][0]["stage"] == "extract"
    assert task.state["queries"][0]["results"] and not harness.client.requests
    assert db_session.scalar(select(DiscoveredCompany)) is None
    await step(db_session, harness)
    db_session.expire_all()
    row = db_session.scalar(select(DiscoveredCompany))
    assert row.status == "pending" and row.attempts == 0
    assert len(harness.searches) == 1
    await step(db_session, harness)
    db_session.refresh(row)
    assert row.status == "verified"
    for _ in range(8):
        if not await step(db_session, harness):
            break
    db_session.expire_all()
    assert discovery_queue_summary(db_session, item)["status"] == "completed"
    assert len(harness.searches) == len(discovery_queries(item))


@pytest.mark.asyncio
async def test_timeout_retries_smaller_query_without_losing_other_directions(db_session):
    item = goal(db_session)
    item.query = "北京 上海 ai agent rag ai产品 2027 校招"
    db_session.commit()
    enqueue_company_discovery(db_session, item)
    harness = Harness()
    harness.fail_search = True
    await step(db_session, harness)
    await step(db_session, harness)
    assert len(harness.searches) == 2 and harness.searches[0] != harness.searches[1]
    assert "2027" not in harness.searches[0] and "北京" not in harness.searches[1]
    db_session.expire_all()
    task = db_session.get(CompanyDiscoveryTask, item.id)
    assert len(task.state["queries"]) == 3
    assert task.state["queries"][0]["stage"] == "extract"
    assert task.state["queries"][1]["stage"] == "search"


@pytest.mark.asyncio
async def test_restart_after_cancelled_extraction_does_not_repeat_search(db_session):
    item = goal(db_session)
    enqueue_company_discovery(db_session, item)
    harness = Harness()
    await step(db_session, harness)
    started = asyncio.Event()
    original = harness.client.generate

    async def slow(request):
        started.set()
        await asyncio.Event().wait()

    harness.client.generate = slow
    running = asyncio.create_task(step(db_session, harness))
    await started.wait()
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    db_session.expire_all()
    task = db_session.get(CompanyDiscoveryTask, item.id)
    assert task.state["queries"][0]["results"]
    task.lease_until = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()
    harness.client.generate = original
    await step(db_session, harness)
    assert len(harness.searches) == 1
    assert db_session.scalar(select(DiscoveredCompany)) is not None


@pytest.mark.asyncio
async def test_lease_and_goal_version_prevent_duplicate_or_stale_work(db_session):
    item = goal(db_session)
    enqueue_company_discovery(db_session, item)
    task = db_session.get(CompanyDiscoveryTask, item.id)
    task.status = "running"
    task.lease_until = datetime.now(UTC) + timedelta(minutes=5)
    db_session.commit()
    harness = Harness()
    assert not await step(db_session, harness)
    task.lease_until = datetime.now(UTC) - timedelta(seconds=1)
    item.version = 2
    db_session.commit()
    assert await step(db_session, harness)
    db_session.refresh(task)
    assert task.status == "superseded" and not harness.searches


@pytest.mark.asyncio
async def test_api_ownership_version_and_idempotent_enqueue(db_session, monkeypatch):
    from src import config
    monkeypatch.setattr(config, "get_settings", lambda: SETTINGS)
    item = goal(db_session)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        url = f"/api/discovery/goals/{item.id}/discover"
        assert (await client.post(url, json={"expected_version": 1}, headers={"X-User-ID": "stranger"})).status_code == 404
        assert (await client.post(url, json={"expected_version": 2}, headers={"X-User-ID": "owner"})).status_code == 409
        for _ in range(2):
            assert (await client.post(url, json={"expected_version": 1}, headers={"X-User-ID": "owner"})).status_code == 202
    assert len(list(db_session.scalars(select(CompanyDiscoveryTask)))) == 1


def test_diversity_removes_known_company_and_retains_other_ats_tenants():
    from src.services.company_registry import CompanySource
    known = CompanySource("known", "Known", "C", "https://known.example/careers", "official_career_page")
    results = [lead(f"https://known.example/jobs/{i}") for i in range(8)]
    results += [lead(f"https://new.example/jobs/{i}") for i in range(8)] + [lead("https://another.example/careers")]
    selected = diverse_company_links(results, [known], limit=4)
    assert selected[0].source_url.startswith("https://new.example")
    assert selected[1].source_url.startswith("https://another.example")


@pytest.mark.asyncio
async def test_changed_goal_while_model_is_running_does_not_save_stale_candidates(db_session):
    item = goal(db_session)
    enqueue_company_discovery(db_session, item)
    harness = Harness()
    await step(db_session, harness)
    original = harness.client.generate

    async def change_goal(request):
        item.version += 1
        db_session.commit()
        return await original(request)

    harness.client.generate = change_goal
    await step(db_session, harness)
    db_session.expire_all()
    assert db_session.scalar(select(DiscoveredCompany)) is None
    assert db_session.get(CompanyDiscoveryTask, item.id).status == "superseded"
