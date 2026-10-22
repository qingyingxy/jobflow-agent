import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.config import Settings
from src.domain.job import JobPosting
from src.domain.search_goal import SearchGoalConditions
from src.domain.source_review_cache import put_record
from src.infrastructure.database import Base
from src.infrastructure.llm_client import FakeModelClient
from src.main import app
from src.services.body_review_queue import (
    enqueue_body_review,
    review_queue_summary,
    run_body_review_batch,
)
from src.services.search_goal_service import SearchGoalService, posting_stub
from src.services.search_intent import interpret_intent, parse_conditions
from src.services.source_understanding import (
    SourceUnderstanding,
    checked_decisions,
    fingerprint,
    review_attempt,
)
from tests.test_search_goals import add_posting


def output(status):
    return {"decisions": [{"field": "location", "status": status, "diagnosis": "supported",
                           "reason": "岗位仅在深圳", "evidence_ids": [0], "basis": "explicit"}]}


SETTINGS = Settings(_env_file=None, web_search_understanding_mode="ai")
A = SearchGoalConditions(locations=["上海"]).model_dump()
B = SearchGoalConditions(locations=["深圳"]).model_dump()


def setup(session):
    posting = add_posting(session, city="深圳")
    posting.raw_content = "工作地点：深圳。\n岗位职责：参与Java后端服务的设计、开发与上线维护，承担接口设计、数据存储及分布式系统研发。"
    session.commit()
    return posting


@pytest.mark.asyncio
async def test_two_targets_retain_decisions_after_stale_checkpoints_and_restart(db_session):
    posting = setup(db_session)
    factory = sessionmaker(bind=db_session.bind, expire_on_commit=False)
    # Both calls start from the same old body, as overlapping foreground and
    # background workers do. Save B after A without refreshing B's ORM object.
    with factory() as first, factory() as second:
        a, b = first.get(JobPosting, posting.id), second.get(JobPosting, posting.id)
        model_a, model_b = FakeModelClient(output=output("excluded")), FakeModelClient(output=output("matched"))
        reviewed_a, reviewed_b = await asyncio.gather(
            SourceUnderstanding(SETTINGS, client=model_a).review(posting_stub(a), query="上海", conditions=A),
            SourceUnderstanding(SETTINGS, client=model_b).review(posting_stub(b), query="深圳", conditions=B),
        )
        a.recruitment_context = reviewed_a.recruitment_context
        first.commit()
        b.recruitment_context = reviewed_b.recruitment_context
        second.commit()
    with factory() as restarted:
        current = posting_stub(restarted.get(JobPosting, posting.id))
        assert checked_decisions(current, A, primary=True)["location"]["status"] == "excluded"
        assert checked_decisions(current, B, primary=True)["location"]["status"] == "matched"
        for conditions, query in ((A, "上海"), (B, "深圳"), (A, "上海")):
            client = FakeModelClient(output=output("matched"))
            assert await SourceUnderstanding(SETTINGS, client=client).review(current, query=query, conditions=conditions) is current
            assert not client.requests
        assert not checked_decisions(replace(current, raw_content=current.raw_content + "\n工作地点已变更为北京。"), A)
        assert not checked_decisions(current, {**B, "locations": ["北京"]})


def test_retry_state_and_manual_reset_are_target_local(db_session):
    posting = setup(db_session)
    service = SearchGoalService(db_session)
    goals = [service.save(user_id="owner", input_text=city, conditions=SearchGoalConditions(locations=[city]), condition_sources={})
             for city in ("上海", "深圳")]
    for goal in goals:
        posting.recruitment_context = put_record(posting.recruitment_context, "source_review_attempt", {
            "fingerprint": fingerprint(posting_stub(posting), goal.conditions), "error_code": "semantic_timeout",
            "failures": 3, "timeout_failures": 3, "fields": ["location"], "next_retry_at": None})
    db_session.commit()
    enqueue_body_review(db_session, goals[0], retry_failed=True)
    assert review_attempt(posting_stub(posting), A)["failures"] == 0
    assert review_attempt(posting_stub(posting), B)["failures"] == 3
    assert review_queue_summary(db_session, goals[1])["blocked"] == 1


def test_simultaneous_sqlite_writers_merge_target_records(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'targets.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        identifier = setup(session).id
    ready = Barrier(2)

    def write(conditions):
        with factory() as session:
            job = session.get(JobPosting, identifier)
            context = put_record(job.recruitment_context, "source_review_attempt", {
                "fingerprint": fingerprint(posting_stub(job), conditions), "failures": 1})
            ready.wait(timeout=5)
            job.recruitment_context = context
            session.commit()

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(write, conditions) for conditions in (A, B)]
            for future in futures:
                future.result(timeout=10)
        with factory() as session:
            stub = posting_stub(session.get(JobPosting, identifier))
            assert review_attempt(stub, A)["failures"] == 1
            assert review_attempt(stub, B)["failures"] == 1
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_each_goal_worker_finishes_its_source_lane_without_reopening_the_other(db_session):
    setup(db_session)
    service = SearchGoalService(db_session)
    goals = [service.save(user_id="owner", input_text=city, conditions=SearchGoalConditions(locations=[city]), condition_sources={})
             for city in ("上海", "深圳")]
    for goal in goals:
        enqueue_body_review(db_session, goal)
    factory = sessionmaker(bind=db_session.bind, expire_on_commit=False)
    for goal, status in zip(goals, ("excluded", "matched"), strict=True):
        assert await run_body_review_batch(factory, settings=SETTINGS, goal_id=goal.id, client=FakeModelClient(output=output(status)))
    db_session.expire_all()
    for goal in goals:
        assert review_queue_summary(db_session, goal)["lanes"]["source"]["remaining"] == 0
    with TestClient(app) as client:
        rows = client.get("/api/discovery/goals/overview", headers={"X-User-ID": "owner"}).json()
        assert {row["goal_id"] for row in rows} == {goal.id for goal in goals}
        assert client.get("/api/discovery/goals/overview", headers={"X-User-ID": "stranger"}).json() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["Java后端开发", "Java后端研发", "Java后端开发工程师", "Java后端"])
async def test_occupational_suffix_does_not_become_an_extra_gate(role):
    result, _, _ = await interpret_intent(f"杭州/深圳，2027届校招，{role}", settings=Settings(_env_file=None, structured_model_provider="fake"))
    assert result == parse_conditions("杭州/深圳，2027届校招，Java后端")
    assert result.pending_conditions == []


def test_real_role_qualifiers_exclusions_and_requirements_remain_intact():
    assert parse_conditions("上海大模型应用开发校招").roles == ["大模型应用开发"]
    assert parse_conditions("深圳前端研发校招，排除后端开发").excluded_roles == ["后端"]
    assert parse_conditions("杭州Java后端开发，要求双休").pending_conditions == ["要求双休"]
    # Bare 开发 is not silently dropped when it is an unrecognized requirement.
    assert "开发" in parse_conditions("杭州Java，开发").keywords


@pytest.mark.parametrize("origin, repaired", [("本次输入", True), ("用户修改", False)])
def test_existing_machine_added_gates_are_repaired_but_manual_keywords_are_preserved(db_session, origin, repaired):
    text = "杭州/深圳，2027届校招，Java后端开发"
    conditions = parse_conditions(text).model_copy(update={
        "keywords": ["java", "开发"], "pending_conditions": ["意图待核实：开发", "要求双休"]})
    service = SearchGoalService(db_session)
    goal = service.save(user_id="owner", input_text=text, conditions=conditions, condition_sources={})
    goal.condition_sources = {"_intent_version": "2", "keywords": origin,
                              "pending_conditions": "本次输入（意图尚未确认）"}
    db_session.commit()
    result = service.get("owner", goal.id)
    assert result.version == (2 if repaired else 1)
    assert result.conditions["keywords"] == (["java"] if repaired else ["java", "开发"])
    assert "要求双休" in result.conditions["pending_conditions"]
    assert service.get("owner", goal.id).version == result.version
