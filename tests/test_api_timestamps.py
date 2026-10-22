# Intentionally reproduce the naive UTC values returned by legacy SQLite rows.
# ruff: noqa: DTZ001
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy.orm import Session

from src.api.materials_schemas import PrivateDateField
from src.api.schemas import DomainEventRead
from src.domain.discovery import DiscoveryRun
from src.domain.materials import AnswerBankEntry
from src.main import app


@pytest.mark.parametrize("value", [
    "2026-10-16T09:30:00",
    "2026-10-16T09:30:00Z",
    "2026-10-16T17:30:00+08:00",
    "2026-10-16T04:30:00-05:00",
])
def test_event_timestamps_identify_the_same_instant(value):
    event = DomainEventRead(
        id="event", entity_type="job", entity_id="job", event_type="created",
        payload={}, created_at=value,
    )
    assert event.model_dump(mode="json")["created_at"] == "2026-10-16T09:30:00Z"


def test_date_only_fields_are_not_shifted_by_timezone():
    field = PrivateDateField(state="provided", value="2027-07-01")
    assert field.model_dump(mode="json")["value"] == "2027-07-01"


@pytest.mark.asyncio
async def test_answer_bank_create_and_sqlite_read_return_aware_timestamps(db_session: Session):
    headers = {"X-User-ID": "timestamp-owner"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/api/answer-bank", headers=headers, json={
            "question_pattern": "到岗时间", "answer": "2027年7月", "confirmed": True,
        })
        assert created.status_code == 201
        for field in ("created_at", "updated_at", "confirmed_at"):
            assert datetime.fromisoformat(created.json()[field]).tzinfo is not None
        entry = db_session.get(AnswerBankEntry, created.json()["id"])
        assert entry is not None
        entry.created_at = entry.updated_at = entry.confirmed_at = datetime(2026, 10, 16, 9, 30)
        db_session.commit()
        db_session.expire_all()
        response = await client.get("/api/answer-bank", headers=headers)
    assert response.status_code == 200
    for field in ("created_at", "updated_at", "confirmed_at"):
        assert response.json()[0][field] == "2026-10-16T09:30:00Z"
    # Serialization must not rewrite historical database values.
    db_session.refresh(entry)
    assert entry.created_at == datetime(2026, 10, 16, 9, 30)


@pytest.mark.asyncio
async def test_discovery_history_serializes_legacy_sqlite_utc(db_session: Session):
    db_session.add(DiscoveryRun(
        id="time-run", user_id="timestamp-owner", source="web_search",
        source_url="https://example.com", status="SUCCEEDED",
        started_at=datetime(2026, 10, 16, 9, 30),
        finished_at=datetime(2026, 10, 16, 9, 31),
        created_at=datetime(2026, 10, 16, 9, 30),
    ))
    db_session.commit()
    db_session.expire_all()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/discovery/runs/time-run", headers={"X-User-ID": "timestamp-owner"})
    assert response.status_code == 200
    body = response.json()
    assert body["created_at"] == body["started_at"] == "2026-10-16T09:30:00Z"
    assert datetime.fromisoformat(body["finished_at"]) == datetime(2026, 10, 16, 9, 31, tzinfo=UTC)
