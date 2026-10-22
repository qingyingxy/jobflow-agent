"""Consume bounded, read-only browser observations. Never fetch arbitrary URLs."""
import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update

from src.domain.application import Application, CandidateJob, DomainEvent
from src.domain.portal_tracking import PortalObservation, PortalRecord, PortalSource

PORTAL_URL = "https://mhr.ly.com/recruit/schoolPortal/#/personal"
ERRORS = {
    "LOGIN_REQUIRED": "官网登录已失效，请在连接的浏览器中登录后再同步。原有记录已保留。",
    "ERROR": "官网暂时无法读取，原有记录已保留，请稍后重试。",
    "PAGE_CHANGED": "官网表格结构或分页发生变化，本次未更新，请检查页面。",
}


def uid(prefix):
    return f"{prefix}_{uuid4().hex[:20]}"


def utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def validate_portal_url(value: str) -> str:
    try:
        url = urlsplit(value.strip())
        allowed = (url.scheme == "https" and url.netloc == "mhr.ly.com"
                   and url.path == "/recruit/schoolPortal/"
                   and url.fragment == "/personal" and not url.query)
    except ValueError:
        allowed = False
    if not allowed:
        raise HTTPException(422, "目前支持同程校招的个人申请页，请填写已适配的官网链接。")
    return PORTAL_URL


class PortalRow(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=300)
    recruitment_type: str = Field(min_length=1, max_length=100)
    location: str = Field(max_length=200)
    submitted_at_text: str = Field(pattern=r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
    raw_status: str = Field(min_length=1, max_length=100)

    def identity(self):
        # Status is deliberately excluded. Separate submissions never merge.
        return hashlib.sha256(json.dumps(
            [self.title, self.recruitment_type, self.location, self.submitted_at_text],
            ensure_ascii=False,
        ).encode()).hexdigest()


class PortalTrackingService:
    def __init__(self, session):
        self.session = session

    def source(self, user_id, source_id):
        source = self.session.get(PortalSource, source_id)
        if source is None or source.user_id != user_id:
            raise HTTPException(404, "官网连接不存在")
        return source

    def create(self, user_id, url):
        url = validate_portal_url(url)
        source = self.session.scalar(select(PortalSource).where(
            PortalSource.user_id == user_id, PortalSource.url == url))
        if source is None:
            source = PortalSource(id=uid("portal"), user_id=user_id, url=url,
                                  company="同程旅行", state="NEW")
            self.session.add(source)
            self.session.commit()
        return source

    def begin(self, user_id, source_id):
        source = self.source(user_id, source_id)
        token = secrets.token_hex(24)
        # A new request invalidates any older in-flight response.
        source.sync_token = token
        source.sync_started_at = datetime.now(UTC)
        self.session.commit()
        return token

    def report(self, user_id, source_id, *, token, state, rows, complete, page_url):
        source = self.source(user_id, source_id)
        now = datetime.now(UTC)
        validate_portal_url(page_url)
        if (not source.sync_started_at
                or utc(source.sync_started_at) < now - timedelta(minutes=5)):
            raise HTTPException(409, "同步请求已过期，请重新同步")
        claimed = self.session.execute(update(PortalSource).where(
            PortalSource.id == source_id, PortalSource.sync_token == token,
        ).values(sync_token=None).execution_options(synchronize_session=False))
        if claimed.rowcount != 1:
            self.session.rollback()
            raise HTTPException(409, "已有新的同步请求，本次结果未覆盖新结果")
        source.sync_token = None
        source.checked_at = now
        if state != "READY" or not complete:
            source.state = state if state in ERRORS else "PAGE_CHANGED"
            source.error = ERRORS[source.state]
            self.session.commit()
            return {"new": 0, "changed": 0}
        identities = [row.identity() for row in rows]
        if len(set(identities)) != len(identities):
            self.session.rollback()
            raise HTTPException(422, "官网记录重复，本次结果未写入")
        existing = {r.identity: r for r in self.session.scalars(select(PortalRecord).where(
            PortalRecord.source_id == source_id))}
        counts = {"new": 0, "changed": 0}
        for row in rows:
            key = row.identity()
            record = existing.get(key)
            previous = record.raw_status if record else None
            if record is None:
                record = PortalRecord(id=uid("portal_record"), source_id=source_id,
                    identity=key, **row.model_dump(), first_seen_at=now,
                    last_seen_at=now, changed_at=now)
                self.session.add(record)
                counts["new"] += 1
            record.last_seen_at = now
            if previous != row.raw_status:
                record.raw_status = row.raw_status
                record.changed_at = now
                counts["changed"] += int(previous is not None)
                self.session.add(PortalObservation(id=uid("portal_obs"), record_id=record.id,
                    observed_at=now, previous_status=previous, raw_status=row.raw_status,
                    evidence={"page_url": source.url, "row": row.model_dump()}))
                self._application_event(user_id, record, source, previous)
        # Disappearing rows remain historical observations; never infer rejection.
        source.state = "READY"
        source.error = None
        source.succeeded_at = now
        self.session.commit()
        return counts

    def _application_event(self, user_id, record, source, previous):
        if not record.application_id:
            return
        self.session.add(DomainEvent(id=uid("event"), user_id=user_id,
            entity_type="application", entity_id=record.application_id,
            event_type="PortalApplicationObserved", payload={
                "source_url": source.url, "raw_status": record.raw_status,
                "previous_status": previous, "record_id": record.id,
            }))

    def link(self, user_id, record_id, application_id):
        record = self.session.get(PortalRecord, record_id)
        if not record:
            raise HTTPException(404, "官网申请记录不存在")
        source = self.source(user_id, record.source_id)
        if application_id:
            owned = self.session.scalar(select(Application).join(
                CandidateJob, CandidateJob.id == Application.candidate_job_id).where(
                Application.id == application_id, CandidateJob.user_id == user_id))
            if owned is None:
                raise HTTPException(404, "申请不存在")
            duplicate = self.session.scalar(select(PortalRecord).where(
                PortalRecord.application_id == application_id, PortalRecord.id != record_id))
            if duplicate:
                raise HTTPException(409, "该申请已关联另一条官网记录，请先解除关联")
        if record.application_id == application_id:
            return
        if record.application_id:
            self.session.add(DomainEvent(id=uid("event"), user_id=user_id,
                entity_type="application", entity_id=record.application_id,
                event_type="PortalApplicationUnlinked", payload={"record_id": record.id}))
        record.application_id = application_id
        self._application_event(user_id, record, source, None)
        self.session.commit()

    def list(self, user_id):
        result = []
        for source in self.session.scalars(select(PortalSource).where(PortalSource.user_id == user_id)):
            records = []
            for record in self.session.scalars(select(PortalRecord).where(
                PortalRecord.source_id == source.id).order_by(PortalRecord.first_seen_at.desc())):
                history = list(self.session.scalars(select(PortalObservation).where(
                    PortalObservation.record_id == record.id).order_by(
                    PortalObservation.observed_at.desc()).limit(20)))
                records.append({
                    **{name: getattr(record, name) for name in (
                        "id", "title", "recruitment_type", "location", "submitted_at_text",
                        "raw_status", "application_id", "last_seen_at", "changed_at")},
                    "missing": bool(source.succeeded_at and utc(record.last_seen_at) < utc(source.succeeded_at)),
                    "history": [{"at": h.observed_at, "previous_status": h.previous_status,
                                 "raw_status": h.raw_status} for h in history],
                })
            result.append({
                **{name: getattr(source, name) for name in (
                    "id", "url", "company", "state", "error", "checked_at", "succeeded_at")},
                "records": records,
            })
        return result
