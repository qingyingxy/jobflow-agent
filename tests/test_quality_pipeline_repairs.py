import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import sessionmaker

from src.config import Settings
from src.domain.discovery import DiscoveryRun, LeadProvider
from src.domain.search_goal import BodyReviewTask, SearchGoalConditions
from src.infrastructure.llm_client import FakeModelClient
from src.services.body_review_queue import (
    enqueue_body_review,
    review_queue_summary,
    run_body_review_batch,
)
from src.services.job_lead_service import JobLeadService, LeadVerificationFailure
from src.services.personal_requirements import personal_requirement_hints
from src.services.search_goal_service import SearchGoalService
from src.services.source_understanding import (
    SourceUnderstanding,
    checked_decisions,
    ranking_excerpt,
)
from tests.test_ai_search_workflow import QUERY, RAW, URL, page_output
from tests.test_search_goals import BASE


@pytest.mark.asyncio
@pytest.mark.parametrize("text,basis,expected", [
    ("全职", None, "pending"), ("职位性质：全职", "audience", "pending"),
    ("3年以上相关工作经验", "experience", "pending"),
    ("仅招有工作经历人员，不接受应届生", "audience", "excluded"),
])
async def test_recruitment_contract_separates_employment_and_experience(text, basis, expected):
    original = replace(BASE, raw_content=text + "\n负责研发智能应用，开发部署Agent系统并进行产品效果迭代与测试，协同工程团队交付可靠服务。")
    conditions = SearchGoalConditions(job_types=["校招"]).model_dump()
    client = FakeModelClient(output={"decisions": [{"field": "job_type", "status": "excluded",
        "diagnosis": "supported", "basis": "explicit", "recruitment_basis": basis,
        "reason": "原文依据", "evidence_ids": [0]}]})
    result = await SourceUnderstanding(Settings(_env_file=None), client=client).review(original,
        query="校招", conditions=conditions)
    assert checked_decisions(result, conditions)["job_type"]["status"] == expected


def setup_saved_page(session, monkeypatch):
    from src.services import company_registry
    monkeypatch.setattr(company_registry, "enabled_company_source_hosts", lambda **_: {"example.com"})
    goal = SearchGoalService(session).save(user_id="owner", input_text=QUERY,
        conditions=SearchGoalConditions(locations=["北京", "上海"], job_types=["校招"],
            roles=["AI Agent", "RAG", "AI产品"], graduation_years=[2027]), condition_sources={})
    run = DiscoveryRun(id="saved-page", user_id="owner", source="test", source_url=URL,
        started_at=datetime.now(UTC), search_goal_id=goal.id, search_goal_version=goal.version)
    session.add(run)
    session.commit()
    service = JobLeadService(session)
    lead = service.create_lead(user_id="owner", provider=LeadProvider.EXTERNAL_AGENT,
        source_url=URL, discovery_run_id=run.id)
    snapshot_id = service._save_page_snapshot(user_id="owner", lead_id=lead.id, url=URL,
        raw_html=RAW.replace("<h1>", "<div>").replace("</h1>", "</div>"), raw_text=None)
    from src.domain.discovery import LeadVerification
    snapshot = session.get(LeadVerification, snapshot_id)
    snapshot.field_evidence = {**snapshot.field_evidence, "ai_reading_pending": True}
    lead.status, lead.failure_code = "DEFERRED", "semantic_page_pending"
    session.commit()
    enqueue_body_review(session, goal)
    return goal, lead, snapshot, sessionmaker(bind=session.bind, expire_on_commit=False)


@pytest.mark.asyncio
async def test_unparsed_body_joins_queue_and_retains_original_read_time(db_session, monkeypatch):
    goal, lead, snapshot, factory = setup_saved_page(db_session, monkeypatch)
    original_read = snapshot.checked_at
    assert review_queue_summary(db_session, goal)["waiting"] == 1
    await run_body_review_batch(factory, settings=Settings(_env_file=None), client=FakeModelClient(output=page_output()))
    db_session.expire_all()
    from src.domain.job import JobPosting
    posting = db_session.get(JobPosting, lead.job_posting_id)
    assert posting and posting.last_verified_at == original_read.replace(tzinfo=None)
    assert "求职搭子" not in posting.raw_content
    assert review_queue_summary(db_session, goal)["completed"] == 1
    assert review_queue_summary(db_session, goal)["remaining"] == 0


@pytest.mark.asyncio
async def test_saved_page_with_linked_context_api_never_requires_a_network_reader(db_session, monkeypatch):
    goal, lead, snapshot, factory = setup_saved_page(db_session, monkeypatch)
    from src.services import company_registry
    url = "https://careers.oppo.com/university/oppo/campus/post/1795?recruitType=Intern"
    lead.source_url = lead.normalized_url = snapshot.source_url = url
    monkeypatch.setattr(company_registry, "enabled_company_source_hosts", lambda **_: {"careers.oppo.com"})
    original_read = snapshot.checked_at
    db_session.commit()
    await run_body_review_batch(factory, settings=Settings(_env_file=None), client=FakeModelClient(output=page_output()))
    db_session.expire_all()
    from src.domain.job import JobPosting
    job = db_session.get(JobPosting, lead.job_posting_id)
    assert job and job.recruitment_context["reason"] == "saved_body_only"
    assert datetime.fromisoformat(job.recruitment_context["checked_at"]).replace(tzinfo=None) == original_read.replace(tzinfo=None)
    assert job.last_verified_at == original_read.replace(tzinfo=None)
    assert review_queue_summary(db_session, goal)["status"] == "completed"


@pytest.mark.asyncio
async def test_one_unexpected_page_error_keeps_other_results_and_bounds_retry(db_session, monkeypatch):
    from tests.test_search_goals import add_posting
    goal, lead, snapshot, factory = setup_saved_page(db_session, monkeypatch)
    job = add_posting(db_session, identifier="healthy-body")
    job.raw_content = "负责智能应用系统的设计、研发、测试和上线，持续进行迭代与维护，和业务及工程团队共同交付可靠服务。"
    db_session.commit()

    async def broken_context(*args, **kwargs):
        raise RuntimeError("one body failed after page extraction")

    monkeypatch.setattr(JobLeadService, "_recruitment_context", broken_context)

    class Model:
        async def generate(self, request):
            if request.schema_name == "job_page_understanding":
                return await FakeModelClient(output=page_output()).generate(request)
            fields = json.loads(request.messages[-1].content)["fields"]
            return await FakeModelClient(output={"decisions": [
                {"field": field, "status": "pending", "diagnosis": "source_missing", "reason": "未写明", "evidence_ids": []}
                for field in fields]}).generate(request)

    for failures in range(1, 4):
        await run_body_review_batch(factory, settings=Settings(_env_file=None), client=Model())
        db_session.expire_all()
        assert snapshot.field_evidence["ai_reading_pending"]
        assert snapshot.field_evidence["page_review_attempt"]["failures"] == failures
        assert lead.status == "DEFERRED"
        assert review_queue_summary(db_session, goal)["completed"] == 1
        if failures < 3:
            snapshot.field_evidence = {**snapshot.field_evidence, "page_review_attempt": {
                **snapshot.field_evidence["page_review_attempt"], "next_retry_at": None}}
            db_session.commit()
            enqueue_body_review(db_session, goal)
    summary = review_queue_summary(db_session, goal)
    assert summary["blocked"] == 1 and summary["status"] == "blocked"
    assert not await run_body_review_batch(factory, settings=Settings(_env_file=None), client=Model())


@pytest.mark.asyncio
async def test_page_failures_cool_down_then_manual_retry_recovers(db_session, monkeypatch):
    goal, lead, snapshot, factory = setup_saved_page(db_session, monkeypatch)
    bad = FakeModelClient(output={})
    await run_body_review_batch(factory, settings=Settings(_env_file=None), client=bad)
    db_session.expire_all()
    assert review_queue_summary(db_session, goal)["cooldown"] == 1
    assert snapshot.field_evidence["page_review_attempt"]["failures"] == 1
    assert not await run_body_review_batch(factory, settings=Settings(_env_file=None), client=bad)
    snapshot.field_evidence = {**snapshot.field_evidence, "page_review_attempt": {
        **snapshot.field_evidence["page_review_attempt"], "failures": 3, "next_retry_at": None}}
    task = db_session.get(BodyReviewTask, goal.id)
    task.status = "blocked"
    db_session.commit()
    enqueue_body_review(db_session, goal, retry_failed=True)
    await run_body_review_batch(factory, settings=Settings(_env_file=None), client=FakeModelClient(output=page_output()))
    db_session.expire_all()
    assert lead.job_posting_id


@pytest.mark.asyncio
async def test_saved_only_never_fetches_expired_page(db_session, monkeypatch):
    goal, lead, snapshot, _factory = setup_saved_page(db_session, monkeypatch)
    snapshot.checked_at = datetime.now(UTC) - timedelta(days=2)
    db_session.commit()
    assert review_queue_summary(db_session, goal)["remaining"] == 0
    with pytest.raises(LeadVerificationFailure, match="已过期"):
        await JobLeadService(db_session).verify_url(user_id="owner", lead_id=lead.id,
            reader=None, official_hosts={"example.com"}, saved_only=True)


@pytest.mark.asyncio
async def test_changed_goal_discards_inflight_page_interpretation(db_session, monkeypatch):
    goal, lead, _snapshot, factory = setup_saved_page(db_session, monkeypatch)
    class Changed:
        async def generate(self, request):
            from src.domain.search_goal import SearchGoal
            with factory() as other:
                current = other.get(SearchGoal, goal.id)
                current.version += 1
                other.commit()
            return await FakeModelClient(output=page_output()).generate(request)
    await run_body_review_batch(factory, settings=Settings(_env_file=None), client=Changed())
    db_session.expire_all()
    assert lead.job_posting_id is None
    assert db_session.get(BodyReviewTask, goal.id).status == "superseded"


@pytest.mark.asyncio
async def test_cancelled_page_attempt_survives_restart(db_session, monkeypatch):
    goal, lead, snapshot, factory = setup_saved_page(db_session, monkeypatch)
    entered = asyncio.Event()
    class Slow:
        async def generate(self, request):
            entered.set()
            await asyncio.Event().wait()
    work = asyncio.create_task(run_body_review_batch(factory, settings=Settings(_env_file=None), client=Slow()))
    await asyncio.wait_for(entered.wait(), 2)
    work.cancel()
    with pytest.raises(asyncio.CancelledError):
        await work
    db_session.expire_all()
    attempt = snapshot.field_evidence["page_review_attempt"]
    assert attempt["failures"] == 0
    snapshot.field_evidence = {**snapshot.field_evidence, "page_review_attempt": {
        **attempt, "attempted_at": (datetime.now(UTC) - timedelta(minutes=3)).isoformat()}}
    db_session.get(BodyReviewTask, goal.id).lease_until = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()
    await run_body_review_batch(factory, settings=Settings(_env_file=None), client=FakeModelClient(output=page_output()))
    db_session.expire_all()
    assert lead.job_posting_id


def test_personal_notices_inherit_bonus_heading_and_never_assume_experience():
    job = SimpleNamespace(raw_content="任职要求\n3年以上软件工程工作经验。\n加分项：\n博士研究生学历。\n发表顶会论文。",
        recruitment_context={}, source_url=URL)
    hints = personal_requirement_hints(job, SimpleNamespace(degree="硕士", educations=[]))
    assert [h["status"] for h in hints] == ["review", "preferred", "preferred"]
    assert "不据此推断社招" in hints[0]["reason"]


def test_branch_requirement_headers_end_bonus_scope_without_losing_branch():
    job = SimpleNamespace(raw_content="任职要求\n【加分项】\n博士研究生学历。\n产品运营方向\n【任职要求】\n3年以上工作经验。",
        recruitment_context={}, source_url=URL)
    hints = personal_requirement_hints(job, SimpleNamespace(degree="本科", educations=[]))
    assert [h["status"] for h in hints] == ["preferred", "review"]
    assert "产品运营方向" in hints[1]["reason"]


def test_list_fallback_prioritizes_real_duties_and_long_excerpt_keeps_tail_evidence():
    from src.services.search_scheduling import listing_priority
    real = "软件研发工程师\n上海 校招\n负责Agent系统开发与工具调用的可靠性建设。"
    tool = "机械工程师\n上海 校招\n使用AI工具辅助机械设计，提高工作效率。"
    assert listing_priority(real, QUERY, ["校招"]) < listing_priority(tool, QUERY, ["校招"])
    long = "软件研发工程师\n" + "公司介绍信息。" * 250 + "\n负责RAG知识库开发与检索效果评估。\n本科及以上。"
    assert "负责RAG知识库开发" in ranking_excerpt(long, QUERY)


@pytest.mark.asyncio
async def test_invalid_ranking_keeps_pool_and_is_not_cached_as_success():
    from src.services.direct_recruitment_search import DirectRecruitmentSearch
    from tests.test_direct_recruitment_search import SOURCE
    runtime = SourceUnderstanding(Settings(_env_file=None), client=FakeModelClient(output={"ranked_ids": [99]}), query=QUERY)
    search = DirectRecruitmentSearch(sources=[SOURCE], query=QUERY, reader=None, browser=None,
        understanding=runtime, on_event=lambda *_: None)
    state = {"reader_kind": "html", "buffer": [
        {"id": "https://example.com/jobs/1", "title": "普通运维"},
        {"id": "https://example.com/jobs/2", "title": "Agent开发"}]}
    await search._rank_buffer(SOURCE, state)
    assert len(state["buffer"]) == 2 and state.get("ranking_version") is None
    assert state["buffer"][0]["title"] == "Agent开发"


def test_company_fallback_rotates_directions_and_narrows_failed_query(db_session):
    from src.services.company_coverage import CompanyCoverage
    from src.services.company_registry import enabled_company_sources
    from tests.test_company_coverage import goal_and_store
    goal, store = goal_and_store(db_session, ["baidu"])
    coverage = CompanyCoverage(sources=enabled_company_sources(["baidu"]), store=store,
        query=QUERY, batch_size=1)
    direct = SimpleNamespace(states={"baidu": {"status": "failed"}})
    full_goal = goal.query
    first = coverage.next_task(direct).query
    coverage.start_search("baidu")
    coverage.finish_search("baidu", failed=True)
    coverage.web_attempted.clear()
    retry = coverage.next_task(direct).query
    assert "agent" in first.casefold() and "agent" in retry.casefold()
    assert "北京" in first and "北京" not in retry and "2027" not in first
    coverage.finish_search("baidu", failed=False)
    assert "rag" in coverage.next_task(direct).query.casefold()
    assert goal.query == full_goal


def test_new_ready_body_wakes_task_without_resetting_failed_item_cooldown(db_session):
    from src.services.body_review_queue import review_items
    from src.services.search_goal_service import posting_stub
    from src.services.source_understanding import queue_review
    from tests.test_body_review_queue import setup_queue
    from tests.test_search_goals import add_posting
    goal, _factory = setup_queue(db_session)
    job = SearchGoalService(db_session).postings("owner")[0]
    context = queue_review(posting_stub(job), conditions=goal.conditions, fields=["location"]).recruitment_context
    later = datetime.now(UTC) + timedelta(minutes=5)
    context["source_review_attempt"].update(failures=2, next_retry_at=later.isoformat())
    job.recruitment_context = context
    task = db_session.get(BodyReviewTask, goal.id)
    task.next_run_at = later
    db_session.commit()
    fresh = add_posting(db_session, identifier="fresh-body")
    fresh.raw_content = job.raw_content + "\n新岗位要求参与发布与维护。"
    db_session.commit()
    enqueue_body_review(db_session, goal)
    assert task.next_run_at.replace(tzinfo=UTC) < later
    assert {row.id: state for row, state, _ in review_items(db_session, goal)}[job.id] == "cooldown"


def test_page_retry_key_normalizes_legacy_partial_conditions():
    from src.services.saved_page_review import page_fingerprint
    snapshot = SimpleNamespace(source_url=URL, field_evidence={"raw_html": RAW})
    assert page_fingerprint(snapshot, {"job_types": ["校招"]}) == page_fingerprint(
        snapshot, SearchGoalConditions(job_types=["校招"]).model_dump())
