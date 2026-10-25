import asyncio
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import sessionmaker

from src.domain.campaign import CampaignDiscoveryTask, CampaignWatch
from src.domain.company_source import DiscoveredCompany
from src.domain.search_goal import SearchGoal
from src.main import app
from src.services.campaign_discovery import (
    discovery_queries,
    discovery_summary,
    enqueue_discovery,
    run_discovery_step,
)
from src.services.campaign_service import campaign_snapshot, save_campaign
from src.services.company_registry import enabled_company_sources
from src.services.user_data_lifecycle import UserDataLifecycleService
from tests.test_campaigns import FACTS
from tests.test_company_discovery import NAME, goal
from tests.test_company_discovery_queue import SETTINGS, Harness


class CampusHarness(Harness):
    def factory(self, session, task, **kwargs):
        return super().factory(session, SimpleNamespace(user_id=task.user_id,
            query=f"{task.year}届秋季校园招聘公司，不限岗位和城市"), task, **kwargs)


async def step(session, harness):
    return await run_discovery_step(sessionmaker(bind=session.bind), settings=SETTINGS,
        agent_factory=harness.factory, now=datetime.now(UTC) + timedelta(minutes=1))


@pytest.mark.asyncio
async def test_independent_discovery_verifies_new_company_then_checks_campus(db_session):
    personal = goal(db_session)
    personal.query = "北京 Python 后端 实习"
    db_session.commit()
    enqueue_discovery(db_session, "owner", 2027)
    harness = CampusHarness()
    await step(db_session, harness)  # search checkpoint
    assert db_session.scalar(select(DiscoveredCompany)) is None
    await step(db_session, harness)  # candidate is not a trusted company yet
    db_session.expire_all()
    row = db_session.scalar(select(DiscoveredCompany))
    assert row.status == "pending"
    assert discovery_summary(db_session, "owner", 2027)["error"] is None
    assert not any(c["company"] == NAME for c in campaign_snapshot(db_session, "owner", 2027)["company_cards"])
    await step(db_session, harness)  # official ownership + hiring link
    db_session.expire_all()
    watch = db_session.scalar(select(CampaignWatch).where(CampaignWatch.company_id == row.id))
    assert watch and watch.year == 2027 and watch.status == "queued"
    cards = campaign_snapshot(db_session, "owner", 2027)["company_cards"]
    card = next(c for c in cards if c["company"] == NAME)
    assert card["recruitment_status"] == "unknown"  # verified employer != open campus recruiting
    assert card["recruitment_url"] == row.career_url
    for _ in range(12):
        if not await step(db_session, harness):
            break
    db_session.expire_all()
    summary = discovery_summary(db_session, "owner", 2027)
    assert summary["status"] == "completed"
    assert summary["companies_verified"] == summary["companies_queued"] == 1
    assert len(list(db_session.scalars(select(CampaignWatch)))) == 1
    assert len(list(db_session.scalars(select(SearchGoal)))) == 1
    assert all("2027" in q and not any(v in q for v in ["北京", "Python", "后端", "实习"]) for q in harness.searches)
    assert all("2027" in q["fallback"] for q in discovery_queries(2027))
    assert discovery_queries(2027, 0) != discovery_queries(2027, 1)


@pytest.mark.asyncio
async def test_discovery_without_saved_goal_and_duplicate_clicks_are_isolated(db_session, monkeypatch):
    from src.api import campaigns
    monkeypatch.setattr(campaigns, "get_settings", lambda: SETTINGS)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        for _ in range(2):
            response = await client.post("/api/campaigns/discover", json={"year": 2027}, headers={"X-User-ID": "owner"})
            assert response.status_code == 202
            assert response.json()["discovery"]["status"] == "queued"
        assert (await client.post("/api/campaigns/discover", json={"year": 2027, "roles": ["Python"]})).status_code == 422
    assert len(list(db_session.scalars(select(CampaignDiscoveryTask)))) == 1
    assert db_session.scalar(select(SearchGoal)) is None
    assert discovery_summary(db_session, "other", 2027)["status"] == "idle"
    assert discovery_summary(db_session, "owner", 2028)["status"] == "idle"
    service = UserDataLifecycleService(db_session)
    assert service.summary(user_id="owner").record_counts["campaign_discovery_tasks"] == 1
    service.delete(user_id="owner")
    assert db_session.scalar(select(CampaignDiscoveryTask)) is None


@pytest.mark.asyncio
async def test_search_retry_keeps_cohort_and_does_not_lose_other_sectors(db_session):
    enqueue_discovery(db_session, "owner", 2027)
    harness = CampusHarness()
    harness.fail_search = True
    await step(db_session, harness)
    await step(db_session, harness)
    assert len(harness.searches) == 2 and harness.searches[0] != harness.searches[1]
    assert all("2027" in q for q in harness.searches)
    db_session.expire_all()
    state = db_session.scalar(select(CampaignDiscoveryTask)).state
    assert state["queries"][0]["stage"] == "extract"
    assert state["queries"][1]["stage"] == "search"


@pytest.mark.asyncio
async def test_expired_lease_resumes_saved_search_results(db_session):
    enqueue_discovery(db_session, "owner", 2027)
    harness = CampusHarness()
    await step(db_session, harness)
    task = db_session.scalar(select(CampaignDiscoveryTask))
    task.status, task.lease_until = "running", datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()
    await step(db_session, harness)
    assert len(harness.searches) == 1
    assert db_session.scalar(select(DiscoveredCompany)) is not None


@pytest.mark.asyncio
async def test_pending_verification_does_not_block_next_discovery_cycle(db_session):
    enqueue_discovery(db_session, "owner", 2027)
    harness = CampusHarness()
    # An unavailable independent source leaves the candidate unverified.
    from tests.test_company_discovery import PROOF
    harness.pages.html.pop(PROOF)
    for _ in range(16):
        if not await step(db_session, harness):
            break
    db_session.expire_all()
    assert discovery_summary(db_session, "owner", 2027)["status"] == "waiting"
    before = db_session.scalar(select(CampaignDiscoveryTask)).state
    enqueue_discovery(db_session, "owner", 2027)
    db_session.expire_all()
    after = db_session.scalar(select(CampaignDiscoveryTask)).state
    assert after["cycle"] == before["cycle"] + 1
    assert after["verify_ids"] == before["verify_ids"]
    assert after["queries"] != before["queries"]
    await step(db_session, harness)
    db_session.expire_all()
    assert db_session.scalar(select(CampaignDiscoveryTask)).state["queries"][0]["stage"] == "extract"


@pytest.mark.asyncio
async def test_interrupted_extraction_resumes_without_searching_again(db_session):
    enqueue_discovery(db_session, "owner", 2027)
    harness = CampusHarness()
    await step(db_session, harness)
    started, original = asyncio.Event(), harness.client.generate

    async def slow(request):
        started.set()
        await asyncio.Event().wait()

    harness.client.generate = slow
    running = asyncio.create_task(step(db_session, harness))
    await started.wait()
    assert not await step(db_session, harness)  # active lease excludes a second worker
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    harness.client.generate = original
    await step(db_session, harness)
    assert len(harness.searches) == 1
    assert db_session.scalar(select(DiscoveredCompany)) is not None


@pytest.mark.asyncio
async def test_deleted_discovery_cannot_recreate_candidates_or_watches(db_session):
    enqueue_discovery(db_session, "owner", 2027)
    harness = CampusHarness()
    await step(db_session, harness)
    original = harness.client.generate

    async def remove_then_return(request):
        with sessionmaker(bind=db_session.bind)() as other:
            other.execute(delete(CampaignDiscoveryTask))
            other.commit()
        return await original(request)

    harness.client.generate = remove_then_return
    await step(db_session, harness)
    assert db_session.scalar(select(DiscoveredCompany)) is None
    assert db_session.scalar(select(CampaignWatch)) is None


def store(session, source, *, title, status="open", age=0, entry=None):
    facts = {**deepcopy(FACTS), "title": title, "status": status,
             "starts": None, "deadline": None, "published": None,
             "status_quote": "网申进行中" if status == "open" else "已截止" if status == "closed" else "待确认"}
    facts["entry"] = {"kind": "listing", "url": source.career_url, "status": "unknown",
                      "job_presence": "found" if status == "open" else "unknown",
                      "job_titles": ["软件工程师"] if status == "open" else [],
                      "checked_at": (datetime.now(UTC) - timedelta(days=age)).isoformat()}
    if entry:
        facts["entry"].update(entry)
    return save_campaign(session, "owner", source, facts, source.career_url + title,
                         datetime.now(UTC) - timedelta(days=age))


def test_company_aggregation_keeps_evidence_and_open_wins_over_closed_program(db_session):
    source = enabled_company_sources()[0]
    store(db_session, source, title="校园招聘", status="open")
    store(db_session, source, title="提前批", status="closed")
    store(db_session, source, title="专项计划", status="unknown")
    db_session.flush()
    snapshot = campaign_snapshot(db_session, "owner", 2027)
    cards = [c for c in snapshot["company_cards"] if c["company_id"] == source.id]
    assert len(cards) == 1
    assert cards[0]["recruitment_status"] == "open"
    assert cards[0]["evidence_count"] == len(cards[0]["evidence_ids"]) == 3
    assert len(snapshot["campaigns"]) == 3
    assert campaign_snapshot(db_session, "other", 2027)["campaigns"] == []
    assert all(c["evidence_count"] == 0 for c in campaign_snapshot(db_session, "owner", 2028)["company_cards"])


@pytest.mark.parametrize("status,age", [("closed", 0), ("open", 2)])
def test_closed_or_stale_evidence_never_claims_company_closed_or_open(db_session, status, age):
    source = enabled_company_sources()[0]
    store(db_session, source, title="旧校招", status=status, age=age)
    db_session.flush()
    card = next(c for c in campaign_snapshot(db_session, "owner", 2027)["company_cards"] if c["company_id"] == source.id)
    assert card["recruitment_status"] == "unknown"
    if age:
        assert card["availability_stale"]


def test_job_evidence_does_not_replace_company_portal_or_processing_state(db_session):
    source = enabled_company_sources()[0]
    watch = CampaignWatch(user_id="owner", company_id=source.id, year=2027, status="partial", error="部分公告未读取")
    db_session.add(watch)
    store(db_session, source, title="软件工程师", entry={"kind": "job", "url": source.career_url + "job/123",
        "status": "open", "checked_at": datetime.now(UTC).isoformat()})
    db_session.flush()
    card = next(c for c in campaign_snapshot(db_session, "owner", 2027)["company_cards"] if c["company_id"] == source.id)
    assert card["status"] == "partial" and card["recruitment_status"] == "open"
    assert card["recruitment_url"] == source.career_url
