"""General regressions found during repeated personal use, without live services."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import event

from src import config
from src.domain.discovery import JobLead, LeadVerification
from src.domain.search_goal import BodyReviewTask
from src.infrastructure.llm_client import FakeModelClient, ModelUnavailableError
from src.services.body_review_queue import (
    review_items,
    run_body_review_batch,
    select_review_batch,
)
from src.services.job_lead_service import JobLeadService
from src.services.personal_requirements import personal_requirement_hints
from src.services.qualification_understanding import (
    attach_qualifications,
    cached_qualifications,
)
from src.services.search_goal_service import SearchGoalService, posting_stub
from src.services.search_pipeline import run_search_pipeline
from src.services.search_scheduling import CompanyCandidateGate
from src.services.source_understanding import SourceUnderstanding
from tests.test_body_review_queue import OUTPUT, SETTINGS, setup_queue
from tests.test_search_goals import BASE
from tests.test_search_scheduling import lead


def clause(evidence, strength="required", degrees=None, scope=None, category="degree"):
    return {"category": category, "strength": strength, "evidence": evidence,
            "accepted_degrees": degrees if degrees is not None else ["doctor"], "scope": scope}


def test_source_label_cache_updates_when_company_registry_changes(tmp_path, monkeypatch):
    import json

    from src.services import company_registry, lead_presentation

    path = tmp_path / "companies.json"
    monkeypatch.setattr(company_registry, "REGISTRY_PATH", path)
    rows = [{"id": "fixture", "company": "Fixture", "career_url": "https://careers.fixture.test"}]
    path.write_text(json.dumps(rows), encoding="utf-8")
    calls = []
    original = lead_presentation.enabled_company_source_hosts

    def counted():
        calls.append(1)
        return original()

    monkeypatch.setattr(lead_presentation, "enabled_company_source_hosts", counted)
    for _ in range(100):
        assert lead_presentation.source_label("https://careers.fixture.test/jobs/1") == "官网域名"
    assert len(calls) == 1
    rows[0]["enabled"] = False
    path.write_text(json.dumps(rows), encoding="utf-8")
    assert lead_presentation.source_label("https://careers.fixture.test/jobs/1") == "来源待核实"
    assert len(calls) == 2


def test_due_high_value_retries_are_selected_among_many_untried_bodies(db_session):
    goal, _ = setup_queue(db_session, 14)
    goal.query = "上海 Agent 校招"
    items = []
    wanted = set()
    for i, job in enumerate(SearchGoalService(db_session).postings("owner")):
        job.title = "Agent平台研发工程师" if i >= 12 else "行政实习生"
        attempt = {"failures": int(i >= 12), "queued_at": f"2026-10-19T00:{i:02d}:00+00:00"}
        if i >= 12:
            wanted.add(job.id)
        items.append((job, "waiting", attempt))
    chosen = select_review_batch(items, goal)
    assert wanted <= {row[0] for row in chosen}
    assert len(chosen) == len({row[0] for row in chosen}) == 6
    assert items[0][0].id in {row[0] for row in chosen}
    items[-1] = (items[-1][0], "cooldown", items[-1][2])
    assert items[-1][0].id not in {row[0] for row in select_review_batch(items, goal)}


@pytest.mark.asyncio
async def test_provider_outage_does_not_exhaust_each_jobs_retry_limit(db_session):
    goal, _ = setup_queue(db_session, 5)
    client = FakeModelClient(error=ModelUnavailableError("fixture outage"))
    jobs = SearchGoalService(db_session).postings("owner")
    for job in jobs:
        # A different batch still shares the same provider circuit.
        runtime = SourceUnderstanding(SETTINGS, client=client, query=goal.query, conditions=goal.conditions)
        updated = await runtime.review(posting_stub(job), query=goal.query, conditions=goal.conditions)
        attempt = updated.recruitment_context["source_review_attempt"]
        assert attempt["failures"] == 0
        assert attempt["next_retry_at"]
    assert len(client.requests) == 3


@pytest.mark.asyncio
async def test_normal_shutdown_can_resume_immediately(db_session):
    goal, factory = setup_queue(db_session)
    entered = asyncio.Event()

    class Waiting:
        async def generate(self, request):
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(run_body_review_batch(factory, settings=SETTINGS, client=Waiting()))
    await asyncio.wait_for(entered.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    db_session.expire_all()
    saved = db_session.get(BodyReviewTask, goal.id)
    assert saved.status == "queued" and saved.lease_token is None and saved.lease_until is None
    assert await run_body_review_batch(factory, settings=SETTINGS, client=FakeModelClient(output=OUTPUT))


@pytest.mark.asyncio
async def test_late_official_shortlist_keeps_three_slots_despite_early_history():
    gate = CompanyCandidateGate(wait_seconds=.3)
    used, actual, finished = 0, [], False
    old = [replace(lead(i), search_context={"purpose": "reference"}) for i in range(3)]
    fresh = [lead(i, title="Agent研发工程师") for i in range(3, 6)]
    priority = lambda candidate: (6 if candidate in old else 0,)

    def done():
        nonlocal finished
        finished = True

    async def bootstrap(enqueue):
        enqueue(old)
        await asyncio.sleep(.04)
        enqueue(fresh)

    async def verify(candidate):
        nonlocal used
        if used >= 3:
            return None
        used += 1
        actual.append(candidate)
        return candidate.source_url, True

    async def search(*_):
        return None

    await run_search_pipeline(search=search, verify=verify, report=lambda *_: None,
        canonicalize=lambda url: url, bootstrap=bootstrap, bootstrap_concurrent=True,
        on_bootstrap_done=done, priority=priority, max_concurrency=2, seconds=2,
        can_verify=lambda c: gate.allows(used=used, priority=priority(c), producer_finished=finished))
    assert actual == fresh and used == 3


@pytest.mark.asyncio
async def test_gate_releases_without_results_or_new_queue_events():
    from src.services.search_scheduling import VerificationQueue

    gate = CompanyCandidateGate(wait_seconds=.02)
    queue = VerificationQueue(can_start=lambda c: gate.allows(used=0, priority=(6,), producer_finished=False))
    queue.put_nowait(lead(1))
    item = await asyncio.wait_for(queue.get(), 1)
    assert item.candidate == lead(1) or item.candidate.source_url.endswith("/1")
    queue.task_done(item)


@pytest.mark.parametrize("raw", [
    "1. 计算机、数学或相关领域博士学历毕业生；2. 熟悉Python。优先条件 1. 顶会论文优先。",
    "材料科学、人工智能或相关领域的博士学位。",
    "数学或物理方向，博士学位。\n优先条件\n顶会论文优先。",
])
def test_fallback_does_not_apply_later_bonus_or_major_alternatives_to_degree(raw):
    job = SimpleNamespace(raw_content="岗位职责：开发Agent。\n任职要求：\n" + raw,
                          recruitment_context={}, source_url=BASE.detail_url)
    hints = personal_requirement_hints(job, SimpleNamespace(degree="硕士", educations=[]))
    assert any(h["category"] == "degree" and h["status"] == "attention" for h in hints)


@pytest.mark.parametrize("team_heading", ["【为什么是我们】", "团队介绍：", "关于我们", "Why join us:"])
def test_fallback_stops_before_employer_benefits_and_clears_duty_branch(team_heading):
    job = SimpleNamespace(raw_content=(
        "岗位职责\n方向三：智能体研发\n负责Agent系统开发。\n"
        "任职要求\n【任职资格】\n必要条件：\n博士学历。\n"
        "加分项：\n发表论文者优先。\n" + team_heading + "\n团队成员来自名校，多位博士。"),
        recruitment_context={}, source_url=BASE.detail_url)
    hints = personal_requirement_hints(job, SimpleNamespace(degree="硕士", educations=[]))
    assert [(h["category"], h["status"]) for h in hints] == [("degree", "attention"), ("publication", "preferred")]
    assert all("方向三" not in h["reason"] and "团队成员" not in h["evidence"] for h in hints)


def test_fallback_keeps_alternative_branches_inside_requirements():
    job = SimpleNamespace(raw_content=("任职要求\n研究方向\n必要条件：\n博士学历。\n"
        "工程方向\n本科及以上学历。\n熟悉论文阅读。"), recruitment_context={}, source_url=BASE.detail_url)
    hints = personal_requirement_hints(job, SimpleNamespace(degree="硕士", educations=[]))
    assert all(h["status"] == "review" for h in hints)
    assert "研究方向" in hints[0]["reason"]
    assert "工程方向" in hints[1]["reason"]
    assert hints[2]["label"] == "论文相关要求"


def test_semantic_qualification_scope_cache_and_local_profile_comparison(db_session):
    _goal, _ = setup_queue(db_session)
    job = SearchGoalService(db_session).postings("owner")[0]
    required, bonus = "数学或相关领域的博士学位", "有论文发表者优先"
    job.raw_content = f"任职要求：1. {required}；优先条件：{bonus}。"
    clauses = [clause(required), clause(bonus, "preferred", [], category="publication")]
    job.recruitment_context = attach_qualifications(posting_stub(job), clauses).recruitment_context
    hints = personal_requirement_hints(job, SimpleNamespace(degree="硕士", educations=[]))
    assert [h["status"] for h in hints] == ["attention", "preferred"]
    assert all(h["source"] == "ai" for h in hints)
    assert personal_requirement_hints(job, None)[0]["status"] == "review"
    assert personal_requirement_hints(job, SimpleNamespace(degree="博士", educations=[]))[0]["status"] == "satisfied"
    changed = replace(posting_stub(job), raw_content=job.raw_content + "学历不限。")
    assert cached_qualifications(changed) is None
    assert cached_qualifications(attach_qualifications(changed, [clause("原文不存在的博士要求")])) is None
    job.recruitment_context = attach_qualifications(posting_stub(job), [clause(required, "conditional", scope="仅研究方向，工程方向本科及以上")]).recruitment_context
    assert personal_requirement_hints(job, SimpleNamespace(degree="硕士", educations=[]))[0]["status"] == "review"
    job.raw_content = "本科或博士学历。论文优先。"
    job.recruitment_context = attach_qualifications(posting_stub(job), [
        clause("本科或博士学历", degrees=["bachelor", "doctor"]),
        clause("论文优先", "preferred", [], scope="研究方向", category="publication"),
    ]).recruitment_context
    hints = personal_requirement_hints(job, SimpleNamespace(degree="硕士", educations=[]))
    assert hints[0]["status"] == "review"
    assert hints[1]["status"] == "preferred" and "加分项" in hints[1]["reason"]


@pytest.mark.asyncio
async def test_background_upgrades_legacy_qualification_once_without_sending_profile(db_session, monkeypatch):
    goal, factory = setup_queue(db_session)
    await run_body_review_batch(factory, settings=SETTINGS, client=FakeModelClient(output=OUTPUT))
    real_settings = SETTINGS.model_copy(update={"structured_model_provider": "openai_compatible"})
    monkeypatch.setattr(config, "get_settings", lambda: real_settings)
    db_session.expire_all()
    assert len(review_items(db_session, goal)) == 1
    task = db_session.get(BodyReviewTask, goal.id)
    task.status, task.next_run_at = "queued", datetime.now(UTC)
    db_session.commit()
    client = FakeModelClient(output={"qualifications": [clause("本科及以上", degrees=["bachelor", "master", "doctor"])]})
    await run_body_review_batch(factory, settings=real_settings, client=client)
    db_session.expire_all()
    assert not review_items(db_session, goal)
    assert len(client.requests) == 1
    assert client.requests[0].schema_name == "job_qualifications"
    assert '"profile"' not in client.requests[0].messages[-1].content
    assert not await run_body_review_batch(factory, settings=real_settings, client=client)


def test_latest_page_snapshot_batch_is_constant_query_count_and_user_scoped(db_session):
    now = datetime.now(UTC)
    for i in range(40):
        url = f"https://example.com/jobs/{i}"
        db_session.add(JobLead(id=f"lead-{i}", user_id="owner", provider="manual_url", source_url=url, normalized_url=url, discovered_at=now))
        db_session.add(LeadVerification(id=f"snapshot-{i}", lead_id=f"lead-{i}", user_id="owner", result="SNAPSHOT", source_url=url,
            field_evidence={"ai_reading_pending": True, "raw_html": "saved"}, checked_at=now - timedelta(seconds=1)))
    db_session.add(LeadVerification(id="newer", lead_id="lead-0", user_id="owner", result="SNAPSHOT", source_url="https://example.com/jobs/0",
        field_evidence={"ai_reading_pending": False, "raw_html": "new saved"}, checked_at=now))
    db_session.commit()
    queries = []

    def capture(*args):
        queries.append(args[2])

    event.listen(db_session.bind, "before_cursor_execute", capture)
    try:
        rows = JobLeadService(db_session).pending_page_snapshots("owner", [f"https://example.com/jobs/{i}" for i in range(40)], now=now)
    finally:
        event.remove(db_session.bind, "before_cursor_execute", capture)
    assert len(queries) == 1 and len(rows) == 39
    assert "https://example.com/jobs/0" not in rows
    assert not JobLeadService(db_session).pending_page_snapshots("someone-else", list(rows))


def test_library_can_load_without_waiting_for_progress(db_session, monkeypatch):
    from src.services import body_review_queue

    goal, _ = setup_queue(db_session)
    monkeypatch.setattr(body_review_queue, "review_queue_summary", lambda *_: pytest.fail("Library must not scan progress"))
    result = SearchGoalService(db_session).library("owner", goal.id, include_progress=False)
    assert result["result_matches"] and "review_queue" not in result
