from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from test_follow_ups import _seed_application

from src.domain.application import Application, DomainEvent
from src.domain.portal_tracking import PortalObservation, PortalRecord
from src.main import app
from src.services.portal_tracking import (
    PORTAL_URL,
    PortalRow,
    PortalTrackingService,
    validate_portal_url,
)


def row(**overrides):
    return PortalRow(**{
        "title": "Agent 开发工程师", "recruitment_type": "常规校招", "location": "北京,成都",
        "submitted_at_text": "2026-10-21 12:30:00", "raw_status": "进行中", **overrides,
    })


def sync(service, source, rows=None, **overrides):
    token = service.begin("alice", source.id)
    return service.report("alice", source.id, **{
        "token": token, "state": "READY", "rows": [row()] if rows is None else rows,
        "complete": True, "page_url": PORTAL_URL, **overrides,
    })


def test_updates_are_idempotent_and_submission_identity_is_distinct(db_session):
    service = PortalTrackingService(db_session)
    source = service.create("alice", PORTAL_URL)
    assert service.create("alice", PORTAL_URL).id == source.id
    assert sync(service, source) == {"new": 1, "changed": 0}
    assert sync(service, source) == {"new": 0, "changed": 0}
    assert sync(service, source, [row(raw_status="面试中"), row(title="产品经理")]) == {"new": 1, "changed": 1}
    assert sync(service, source, [row(raw_status="面试中"), row(submitted_at_text="2026-10-22 12:30:00")]) == {"new": 1, "changed": 0}
    assert db_session.scalar(select(func.count()).select_from(PortalRecord)) == 3
    assert db_session.scalar(select(func.count()).select_from(PortalObservation)) == 4
    data = service.list("alice")[0]
    assert len(data["records"]) == 3
    assert sum(r["missing"] for r in data["records"]) == 1


@pytest.mark.parametrize("state,complete", [("LOGIN_REQUIRED", False), ("ERROR", False), ("READY", False), ("PAGE_CHANGED", False)])
def test_read_failures_never_overwrite_good_observations(db_session, state, complete):
    service = PortalTrackingService(db_session)
    source = service.create("alice", PORTAL_URL)
    sync(service, source)
    success = source.succeeded_at
    sync(service, source, [row(raw_status="已拒绝")], state=state, complete=complete)
    result = service.list("alice")[0]
    assert result["records"][0]["raw_status"] == "进行中"
    assert result["succeeded_at"] == success
    assert result["error"]
    assert not result["records"][0]["missing"]


def test_authenticated_empty_result_preserves_missing_records(db_session):
    service = PortalTrackingService(db_session)
    source = service.create("alice", PORTAL_URL)
    sync(service, source)
    sync(service, source, [])
    record = service.list("alice")[0]["records"][0]
    assert record["missing"] and record["raw_status"] == "进行中"
    assert len(record["history"]) == 1


def test_stale_duplicate_and_expired_responses_cannot_win(db_session):
    service = PortalTrackingService(db_session)
    source = service.create("alice", PORTAL_URL)
    old = service.begin("alice", source.id)
    current = service.begin("alice", source.id)
    with pytest.raises(HTTPException) as exc:
        service.report("alice", source.id, token=old, state="READY", rows=[row()], complete=True, page_url=PORTAL_URL)
    assert exc.value.status_code == 409
    service.report("alice", source.id, token=current, state="READY", rows=[row()], complete=True, page_url=PORTAL_URL)
    with pytest.raises(HTTPException):
        service.report("alice", source.id, token=current, state="READY", rows=[row(raw_status="已拒绝")], complete=True, page_url=PORTAL_URL)
    token = service.begin("alice", source.id)
    source.sync_started_at = datetime.now(UTC) - timedelta(minutes=6)
    db_session.commit()
    with pytest.raises(HTTPException):
        service.report("alice", source.id, token=token, state="READY", rows=[], complete=True, page_url=PORTAL_URL)
    assert service.list("alice")[0]["records"][0]["raw_status"] == "进行中"


def test_duplicate_rows_do_not_partially_commit(db_session):
    service = PortalTrackingService(db_session)
    source = service.create("alice", PORTAL_URL)
    with pytest.raises(HTTPException):
        sync(service, source, [row(), row(raw_status="面试中")])
    assert not service.list("alice")[0]["records"]


def test_link_ownership_history_and_ambiguous_status(db_session):
    service = PortalTrackingService(db_session)
    source = service.create("alice", PORTAL_URL)
    alice_app = _seed_application(db_session, user_id="alice")
    bob_app = _seed_application(db_session, user_id="bob")
    sync(service, source)
    record = db_session.scalar(select(PortalRecord))
    for user_id, application_id in [("bob", bob_app), ("alice", bob_app)]:
        with pytest.raises(HTTPException):
            service.link(user_id, record.id, application_id)
    service.link("alice", record.id, alice_app)
    service.link("alice", record.id, alice_app)
    sync(service, source, [row(raw_status="人才库留存")])
    assert db_session.get(Application, alice_app).status == "SUBMITTED"
    events = list(db_session.scalars(select(DomainEvent).where(DomainEvent.event_type == "PortalApplicationObserved")))
    assert len(events) == 2 and events[-1].payload["raw_status"] == "人才库留存"
    service.link("alice", record.id, None)
    sync(service, source, [row(raw_status="面试中")])
    assert db_session.scalar(select(func.count()).select_from(DomainEvent).where(DomainEvent.event_type == "PortalApplicationObserved")) == 2
    assert service.list("bob") == []


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/private", "https://mhr.ly.com.evil.test/recruit/schoolPortal/#/personal",
    "https://user:pass@mhr.ly.com/recruit/schoolPortal/#/personal", "https://mhr.ly.com:8443/recruit/schoolPortal/#/personal",
    "https://mhr.ly.com/recruit/schoolPortal/?url=http://localhost/#/personal",
    "https://campus.163.com/app/personal/apply", "javascript:alert(1)",
])
def test_urls_are_strictly_scoped_without_network_access(url):
    with pytest.raises(HTTPException):
        validate_portal_url(url)


@pytest.mark.asyncio
async def test_api_contract_and_identity_isolation(db_session):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        headers = {"X-User-ID": "alice"}
        source = (await client.post("/api/portal-tracking", headers=headers, json={"url": PORTAL_URL})).json()
        token = (await client.post(f"/api/portal-tracking/{source['id']}/sync", headers=headers)).json()["token"]
        response = await client.post(f"/api/portal-tracking/{source['id']}/report", headers=headers, json={
            "token": token, "state": "READY", "page_url": PORTAL_URL, "complete": True, "rows": [row().model_dump()],
        })
        assert response.status_code == 200 and response.json()["new"] == 1
        assert (await client.get("/api/portal-tracking", headers={"X-User-ID": "bob"})).json() == {"sources": []}
        assert (await client.post(f"/api/portal-tracking/{source['id']}/sync", headers={"X-User-ID": "bob"})).status_code == 404
        response = await client.post(f"/api/portal-tracking/{source['id']}/report", headers=headers, json={
            "token": token, "state": "READY", "page_url": PORTAL_URL, "complete": True,
            "rows": [{**row().model_dump(), "phone": "must-not-store"}],
        })
        assert response.status_code == 422
