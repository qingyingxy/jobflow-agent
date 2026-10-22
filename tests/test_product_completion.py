import asyncio
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from io import BytesIO
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from docx import Document
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from src.api import materials as materials_api
from src.api.materials_schemas import ResumeParseConfirmation
from src.domain.application import DomainEvent
from src.domain.discovery import LeadProvider
from src.domain.job import JobPosting
from src.domain.job_correction import JobCorrection
from src.domain.materials import ResumeAsset
from src.domain.models import EvidenceItem
from src.domain.runs import AgentRun, JobParseResult
from src.domain.search_goal import SearchGoal, SearchGoalConditions
from src.infrastructure.llm_client import FakeModelClient
from src.main import app
from src.services.candidate_material_service import CandidateMaterialService
from src.services.lead_providers import LeadCandidate
from src.services.resume_ingestion_service import ResumeIngestionError
from src.services.resume_privacy import ResumePrivacyService, redact_resume_text
from src.services.search_goal_scheduler import run_due_goals
from src.services.search_pipeline import run_search_pipeline
from src.services.search_planner import diversity_task
from src.services.user_data_lifecycle import UserDataLifecycleService

OWNER = {"X-User-ID": "completion-owner"}
OTHER = {"X-User-ID": "completion-other"}


def client():
    return TestClient(app)


def upload(api):
    document = Document()
    for line in ["张三", "手机：13812345678", "邮箱：owner@example.com", "住址：上海市某路12号", "使用 Python 开发服务"]:
        document.add_paragraph(line)
    buffer = BytesIO()
    document.save(buffer)
    response = api.post("/api/resumes/assets", headers=OWNER, files={"file": (
        "resume.docx", buffer.getvalue(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )})
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.fixture
def resume_client(tmp_path, monkeypatch):
    monkeypatch.setattr(materials_api, "CandidateMaterialService", lambda session: CandidateMaterialService(session, storage_root=tmp_path))
    model = FakeModelClient(output={"evidence": [{"type": "project", "title": "服务", "claim": "使用 Python 开发服务", "skills": ["Python"]}]})
    monkeypatch.setattr(materials_api, "create_structured_model_client", lambda settings: model)
    return client(), model


def test_resume_needs_exact_preview_consent_and_cache_prevents_repeated_model_calls(resume_client):
    api, model = resume_client
    asset = upload(api)
    assert not model.requests
    preview = api.get(f"/api/resumes/assets/{asset}/preview", headers=OWNER).json()
    assert not model.requests
    for identifier in ("张三", "13812345678", "owner@example.com", "某路12号"):
        assert identifier not in preview["text"]
    body = {"confirmed": True, "preview_hash": preview["preview_hash"], "text": preview["text"]}
    url = f"/api/resumes/assets/{asset}/parse"
    assert api.post(url, headers=OWNER, json={**body, "confirmed": False}).status_code == 422
    assert api.post(url, headers=OWNER, json={**body, "preview_hash": "0" * 64}).status_code == 422
    assert api.post(url, headers=OWNER, json={**body, "text": "虚构 Kubernetes 经历"}).status_code == 422
    assert api.get(f"/api/resumes/assets/{asset}/preview", headers=OTHER).status_code == 404
    assert api.post(url, headers=OTHER, json=body).status_code == 404
    assert not model.requests
    response = api.post(url, headers=OWNER, json=body)
    assert response.status_code == 200, response.text
    assert len(model.requests) == 1
    sent = model.requests[0].messages[-1].content
    assert "owner@example.com" not in sent and "13812345678" not in sent
    assert api.post(url, headers=OWNER, json=body).json()["cached"] is True
    assert len(model.requests) == 1
    assert api.get("/api/evidence", headers=OWNER).json()[0]["claim"] == "使用 Python 开发服务"


def test_saving_a_resume_version_without_consent_never_sends_it(resume_client):
    api, model = resume_client
    asset = upload(api)
    version = api.post("/api/resumes/versions", headers=OWNER, json={"asset_id": asset, "label": "仅存文件"})
    assert version.status_code == 201
    assert api.patch(f"/api/resumes/versions/{version.json()['id']}", headers=OWNER, json={"is_default": True}).status_code == 200
    assert not model.requests
    assert api.get("/api/evidence", headers=OWNER).json() == []


def test_redaction_keeps_qualification_dates_and_removes_identifiers():
    text = "Alice Smith\nalice@example.org +86 13812345678\n身份证：110101200001010011\n2024-2027 硕士 计算机\nPython 项目 https://github.com/private-name"
    safe = redact_resume_text(text)
    assert "2024-2027 硕士 计算机" in safe and "Python 项目" in safe
    for identifier in ("Alice Smith", "alice@example.org", "13812345678", "110101200001010011", "github.com"):
        assert identifier not in safe


def analyzed_job(api):
    raw = "示例公司招聘后端工程师。岗位职责：负责使用 Python 开发后端服务。任职要求：熟悉 Python 或 Java 中至少一种语言。"
    response = api.post("/api/jobs/import-text", headers=OWNER, json={"company": "示例公司", "title": "后端工程师", "raw_content": raw})
    assert response.status_code == 201, response.text
    job = response.json()["id"]
    result = api.post(f"/api/jobs/{job}/analyze", headers=OWNER)
    assert result.status_code == 200, result.text
    return job, result.json()


def test_jd_correction_is_user_scoped_grounded_versioned_and_local(db_session):
    api = client()
    job, original = analyzed_job(api)
    url = f"/api/jobs/{job}/corrections"
    before = api.get(url, headers=OWNER).json()
    immutable = deepcopy(db_session.get(JobParseResult, original["parse_result_id"]).structured_jd)
    model_runs = list(db_session.scalars(select(AgentRun.id)))
    requirements = before["requirements"]
    requirements[0]["mandatory"] = False
    body = {"parse_result_id": before["parse_result_id"], "expected_revision": 0, "requirements": requirements, "reason": "核对原文后调整强度"}
    assert api.put(url, headers=OTHER, json=body).status_code == 404
    bad = deepcopy(body)
    bad["requirements"][0]["description"] = "不存在的原文"
    assert api.put(url, headers=OWNER, json=bad).status_code == 422
    saved = api.put(url, headers=OWNER, json=body)
    assert saved.status_code == 200, saved.text
    assert saved.json()["matches"][0]["requirement"]["mandatory"] is False
    assert saved.json()["agent_run_ids"] == []
    assert api.put(url, headers=OWNER, json=body).status_code == 409
    assert list(db_session.scalars(select(AgentRun.id))) == model_runs
    assert db_session.get(JobParseResult, original["parse_result_id"]).structured_jd == immutable
    refreshed = api.get(f"/api/jobs/{job}/analysis", headers=OWNER).json()
    assert refreshed["structured_jd"]["requirements"][0]["mandatory"] is False
    restored = api.put(url, headers=OWNER, json={**body, "expected_revision": 1, "requirements": None})
    assert restored.status_code == 200
    assert restored.json()["structured_jd"]["requirements"] == original["structured_jd"]["requirements"]
    assert len(list(db_session.scalars(select(JobCorrection)))) == 2


def test_manual_submission_is_explicit_idempotent_and_does_not_invent_receipts(db_session):
    api = client()
    job, _ = analyzed_job(api)
    candidate = api.post("/api/candidates", headers=OWNER, json={"job_posting_id": job}).json()
    application = api.post(f"/api/candidates/{candidate['id']}/prepare-application", headers=OWNER).json()
    url = f"/api/applications/{application['id']}/manual-submission"
    assert api.post(url, headers=OWNER, json={"confirmed": False}).status_code == 422
    assert api.post(url, headers=OTHER, json={"confirmed": True}).status_code == 404
    saved = api.post(url, headers=OWNER, json={"confirmed": True, "note": "在官网完成"})
    assert saved.status_code == 200, saved.text
    assert saved.json()["status"] == "SUBMITTED"
    assert saved.json()["submission_source"] == "user_confirmed"
    assert api.post(url, headers=OWNER, json={"confirmed": True}).status_code == 200
    assert len(list(db_session.scalars(select(DomainEvent).where(DomainEvent.event_type == "ManualSubmissionRecorded")))) == 1
    assert api.get("/api/application-attempts", headers=OWNER).json() == []


@pytest.mark.asyncio
async def test_background_schedule_survives_sessions_and_does_not_catch_up_repeatedly(db_session, test_engine):
    now = datetime.now(UTC)
    goal = SearchGoal(id="scheduled", user_id="owner", name="后台", input_text="上海后端", query="上海后端",
                      conditions=SearchGoalConditions().model_dump(), update_interval_minutes=30,
                      next_update_at=now - timedelta(days=1))
    db_session.add(goal)
    db_session.commit()
    calls = []

    async def dispatch(saved, session):
        calls.append((saved.id, saved.user_id, saved.version))

    factory = sessionmaker(bind=test_engine)
    assert await run_due_goals(factory, now=now, dispatch=dispatch)
    assert not await run_due_goals(factory, now=now, dispatch=dispatch)
    assert calls == [("scheduled", "owner", 1)]
    db_session.expire_all()
    goal.update_interval_minutes = 0
    db_session.commit()
    assert not await run_due_goals(factory, now=now + timedelta(hours=1), dispatch=dispatch)


def test_background_schedule_requires_current_user_and_target_version():
    api = client()
    goal = api.post("/api/discovery/goals", headers=OWNER, json={"input_text": "上海后端", "conditions": {"roles": ["后端"]}}).json()
    url = f"/api/discovery/goals/{goal['id']}/schedule"
    body = {"expected_version": goal["version"], "interval_minutes": 30}
    assert api.put(url, headers=OTHER, json=body).status_code == 404
    assert api.put(url, headers=OWNER, json={**body, "expected_version": 999}).status_code == 409
    assert api.put(url, headers=OWNER, json={**body, "interval_minutes": 1}).status_code == 422
    saved = api.put(url, headers=OWNER, json=body)
    assert saved.status_code == 200 and saved.json()["next_update_at"]
    assert api.get("/api/discovery/goals", headers=OWNER).json()[0]["update_interval_minutes"] == 30


def test_diversity_probe_retains_constraints_and_skips_covered_sources():
    sources = [SimpleNamespace(company=name, career_url=f"https://{name}.example/jobs") for name in ("a", "b")]
    query = "2027届上海后端，不考虑北京"
    task = diversity_task(query, sources, {"a"}, set())
    assert task.query == f"{query} b site:b.example"
    assert diversity_task(query, sources, {"a"}, {task.query}) is None


def test_correction_does_not_change_other_users_and_rejects_stale_content(db_session):
    api = client()
    job, _ = analyzed_job(api)
    other = api.post(f"/api/jobs/{job}/analyze", headers=OTHER).json()
    url = f"/api/jobs/{job}/corrections"
    preview = api.get(url, headers=OWNER).json()
    response = api.put(url, headers=OWNER, json={"parse_result_id": preview["parse_result_id"],
        "expected_revision": 0, "requirements": [], "reason": "误解析条件"})
    assert response.status_code == 200, response.text
    assert api.get(f"/api/jobs/{job}/analysis", headers=OTHER).json()["structured_jd"] == other["structured_jd"]
    db_session.get(JobPosting, job).content_hash = "f" * 64
    db_session.commit()
    assert api.get(url, headers=OWNER).status_code == 409


def test_parse_failure_preserves_file_and_previous_evidence(resume_client, db_session):
    api, model = resume_client
    db_session.add(EvidenceItem(id="existing", user_id=OWNER["X-User-ID"], type="project", title="已有项目", claim="已确认事实", skills=[]))
    db_session.commit()
    asset = upload(api)
    model.output = {"evidence": [{"type": "project", "title": "虚构", "claim": "这段文字并不来自简历", "skills": []}]}
    preview = api.get(f"/api/resumes/assets/{asset}/preview", headers=OWNER).json()
    response = api.post(f"/api/resumes/assets/{asset}/parse", headers=OWNER,
                        json={"confirmed": True, "preview_hash": preview["preview_hash"], "text": preview["text"]})
    assert response.status_code == 422, response.text
    assert api.get(f"/api/resumes/assets/{asset}/download", headers=OWNER).status_code == 200
    assert api.get("/api/evidence", headers=OWNER).json()[0]["claim"] == "已确认事实"
    db_session.expire_all()
    assert db_session.get(ResumeAsset, asset).parse_cache is None


@pytest.mark.asyncio
async def test_deletion_during_resume_parse_does_not_restore_user_data(resume_client, db_session, test_engine, tmp_path):
    api, _ = resume_client
    asset = upload(api)
    service = ResumePrivacyService(db_session, CandidateMaterialService(db_session, storage_root=tmp_path))
    _, preview = service.preview(OWNER["X-User-ID"], asset)

    class DeletingExtractor:
        async def extract(self, text):
            with sessionmaker(bind=test_engine)() as other:
                other.delete(other.get(ResumeAsset, asset))
                other.commit()
            return []

    payload = ResumeParseConfirmation(confirmed=True, preview_hash=preview["preview_hash"], text=preview["text"])
    with pytest.raises(ResumeIngestionError, match="已删除"):
        await service.parse(OWNER["X-User-ID"], asset, payload, DeletingExtractor())
    assert not list(db_session.scalars(select(EvidenceItem)))


def test_export_and_delete_include_corrections_schedules_and_parse_cache(resume_client, db_session, tmp_path):
    api, _ = resume_client
    asset = upload(api)
    preview = api.get(f"/api/resumes/assets/{asset}/preview", headers=OWNER).json()
    assert api.post(f"/api/resumes/assets/{asset}/parse", headers=OWNER, json={"confirmed": True, "preview_hash": preview["preview_hash"], "text": preview["text"]}).status_code == 200
    job, analysis = analyzed_job(api)
    assert api.put(f"/api/jobs/{job}/corrections", headers=OWNER, json={"parse_result_id": analysis["parse_result_id"], "expected_revision": 0, "requirements": [], "reason": "测试"}).status_code == 200
    for owner in (OWNER, OTHER):
        goal = api.post("/api/discovery/goals", headers=owner, json={"input_text": "上海后端", "conditions": {"roles": ["后端"]}}).json()
        assert api.put(f"/api/discovery/goals/{goal['id']}/schedule", headers=owner, json={"expected_version": goal["version"], "interval_minutes": 60}).status_code == 200
    lifecycle = UserDataLifecycleService(db_session, storage_root=tmp_path)
    archive = lifecycle.export(user_id=OWNER["X-User-ID"])
    with ZipFile(BytesIO(archive.content)) as bundle:
        tables = json.loads(bundle.read("manifest.json"))["tables"]
    assert tables["resume_assets"][0]["parse_cache"]["evidence"]
    assert len(tables["job_corrections"]) == 1
    assert tables["search_goals"][0]["update_interval_minutes"] == 60
    lifecycle.delete(user_id=OWNER["X-User-ID"])
    db_session.expire_all()
    assert db_session.get(ResumeAsset, asset) is None
    assert not list(db_session.scalars(select(JobCorrection)))
    assert [g.user_id for g in db_session.scalars(select(SearchGoal))] == [OTHER["X-User-ID"]]


@pytest.mark.asyncio
async def test_scheduler_claim_blocks_concurrent_dispatch_and_records_failure(db_session, test_engine):
    now = datetime.now(UTC)
    goal = SearchGoal(id="schedule-race", user_id="owner", name="test", input_text="上海后端", query="上海后端",
                      conditions={}, update_interval_minutes=30, next_update_at=now - timedelta(seconds=1))
    db_session.add(goal)
    db_session.commit()
    factory = sessionmaker(bind=test_engine)

    async def dispatch(saved, session):
        assert not await run_due_goals(factory, now=now, dispatch=dispatch)
        raise RuntimeError("fixture failure")

    assert await run_due_goals(factory, now=now, dispatch=dispatch)
    db_session.expire_all()
    assert goal.schedule_error
    assert not await run_due_goals(factory, now=now, dispatch=dispatch)


@pytest.mark.asyncio
async def test_target_reached_during_drain_bounds_tail_and_cancels_pending_verification():
    entered, cancelled = [], []

    async def search(number, seen):
        return [LeadCandidate(provider=LeadProvider.EXTERNAL_AGENT, source_url=f"https://jobs.example/{i}",
                              discovered_at=datetime.now(UTC)) for i in range(2)]

    async def verify(candidate):
        entered.append(candidate.source_url)
        if candidate.source_url.endswith("0"):
            return "job", True
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.append(candidate.source_url)
            raise

    stop = await asyncio.wait_for(run_search_pipeline(search=search, verify=verify, canonicalize=lambda s: s,
        report=lambda *args: None, max_rounds=1, seconds=10, verification_seconds=10, target=1,
        target_drain_seconds=0.02), timeout=1)
    assert len(entered) == 2 and cancelled == ["https://jobs.example/1"]
    assert "保留待核验" in stop
