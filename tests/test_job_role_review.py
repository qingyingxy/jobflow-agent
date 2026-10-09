import asyncio
import hashlib
import json
from dataclasses import replace

import pytest

from src.config import Settings
from src.infrastructure.llm_client import FakeModelClient
from src.services.discovery_matching import classify_discovery_job
from src.services.discovery_sources import JobStub
from src.services.job_role_review import (
    JobRoleReviewer,
    duty_text,
    load_role_review,
    valid_review,
)

QUERY = "2027届 上海 AI Agent、RAG、大模型应用开发校招"
DUTIES = "负责供应链系统的售前方案设计，协调仓储和物流运营团队，梳理客户的计费规则并推动业务流程优化和实施交付。"
BASE = JobStub(
    source_id="test",
    source_job_id="1",
    title="系统方案",
    company="示例",
    locations=["上海"],
    job_type="campus",
    published_at=None,
    detail_url="https://example.com/jobs/1",
    raw_content="面向2027届毕业生。\n岗位职责\n"
    + DUTIES
    + "\n任职要求\n熟悉供应链业务。",
)


def reviewer(decision, **settings):
    return JobRoleReviewer(
        Settings(_env_file=None, **settings), client=FakeModelClient(output=decision)
    )


@pytest.mark.asyncio
async def test_review_excludes_other_duties_and_reuses_source_bound_cache(db_session):
    engine = reviewer(
        {
            "status": "excluded",
            "reason": "主要工作为物流运营方案，方向不符",
            "evidence": [DUTIES],
        }
    )
    review = await engine.review(
        BASE, query=QUERY, session=db_session, user_id="u", lead_id="lead"
    )
    assert (
        classify_discovery_job(BASE, query=QUERY, role_review=review).filter_status
        == "excluded"
    )
    assert (
        await engine.review(
            BASE, query=QUERY, session=db_session, user_id="u", lead_id="lead"
        )
        == review
    )
    assert len(engine.client.requests) == 1
    assert load_role_review(db_session, user_id="other", job=BASE, query=QUERY) is None
    assert (
        load_role_review(
            db_session,
            user_id="u",
            job=replace(BASE, raw_content=BASE.raw_content + "负责Agent开发。"),
            query=QUERY,
        )
        is None
    )
    assert (
        load_role_review(db_session, user_id="u", job=BASE, query="物流系统岗位")
        is None
    )
    assert (
        classify_discovery_job(
            BASE, query="上海物流岗位", role_review=review
        ).filter_status
        != "excluded"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "quotes", [[], ["原文不存在的职责证据"], ["系统方案"], ["面向2027届毕业生。"]]
)
async def test_unsupported_or_non_duty_evidence_cannot_exclude(db_session, quotes):
    engine = reviewer({"status": "excluded", "reason": "方向不符", "evidence": quotes})
    result = await engine.review(
        BASE, query=QUERY, session=db_session, user_id="u", lead_id="lead"
    )
    assert result is None
    assert (
        classify_discovery_job(BASE, query=QUERY, role_review=result).filter_status
        == "pending"
    )


@pytest.mark.asyncio
async def test_review_does_not_override_location_or_use_partial_content(db_session):
    engine = reviewer({"status": "matched", "reason": "方向相关", "evidence": [DUTIES]})
    for job in [
        replace(BASE, locations=["北京"]),
        replace(BASE, raw_content="岗位职责：未知"),
    ]:
        assert (
            await engine.review(
                job, query=QUERY, session=db_session, user_id="u", lead_id="lead"
            )
            is None
        )
    assert not engine.client.requests


@pytest.mark.asyncio
async def test_role_timeout_and_call_budget_preserve_pending(db_session):
    class Slow:
        async def generate(self, request):
            await asyncio.Event().wait()

    engine = JobRoleReviewer(
        Settings(
            _env_file=None,
            web_search_role_review_timeout_seconds=0.01,
            web_search_role_review_max_calls=1,
        ),
        client=Slow(),
    )
    assert (
        await engine.review(
            BASE, query=QUERY, session=db_session, user_id="u", lead_id="lead"
        )
        is None
    )
    assert (
        await engine.review(
            BASE, query=QUERY, session=db_session, user_id="u", lead_id="lead"
        )
        is None
    )
    assert engine.calls == 1


def test_team_keyword_does_not_make_infrastructure_an_application_role():
    job = replace(
        BASE,
        title="AI Infra工程师",
        raw_content="职位描述\n团队介绍：服务大模型应用和Agent生态。\n岗位职责\n负责GPU算子优化和模型训练集群的性能调优，开发分布式通信工具。\n任职要求\n熟悉C++和CUDA。",
    )
    assert "Agent" not in duty_text(job)
    check = next(
        c
        for c in classify_discovery_job(job, query=QUERY).checks
        if c["field"] == "role"
    )
    assert check["status"] == "pending"
    assert (
        next(
            c
            for c in classify_discovery_job(
                replace(job, title="大模型训练工程师"), query="大模型岗位"
            ).checks
            if c["field"] == "role"
        )["status"]
        == "matched"
    )


def test_numbered_duties_ignore_vision_but_include_unusual_role_titles():
    job = replace(
        BASE,
        title="研发工程师",
        raw_content="职位描述\n我们的使命是构建智能体。团队介绍... 1. 负责数据库存储引擎开发与性能调优。 2. 负责查询执行器优化。\n任职要求\n精通C++。",
    )
    assert "智能体" not in duty_text(job)
    job = replace(
        BASE,
        title="研发工程师",
        raw_content="面向2027届毕业生。\n岗位职责\n负责Agent工具调用和RAG检索增强问答服务的设计开发。\n任职要求\n熟悉Python。",
    )
    assert classify_discovery_job(job, query=QUERY).filter_status == "matched"


@pytest.mark.asyncio
async def test_non_ai_role_review_uses_same_mechanism(db_session):
    engine = reviewer(
        {
            "status": "excluded",
            "reason": "主要职责为供应链运营，而非前端开发",
            "evidence": [DUTIES],
        }
    )
    result = await engine.review(
        BASE, query="上海前端开发校招", session=db_session, user_id="u", lead_id="lead"
    )
    assert (
        classify_discovery_job(
            BASE, query="上海前端开发校招", role_review=result
        ).filter_status
        == "excluded"
    )


@pytest.mark.parametrize(
    "text,status",
    [
        ("2027届校园招聘-正式批", "matched"),
        ("2027 届本科、硕士或博士毕业生，计算机科学等相关专业", "matched"),
        ("2027校园招聘", "pending"),
        ("2027届海外毕业生", "pending"),
        ("2027届本科毕业生，仅限海外毕业生", "pending"),
        ("2027届本科毕业生，毕业时间2026年10月至2027年9月", "pending"),
        ("2027届校园招聘-正式批\n2026届校园招聘", "pending"),
        ("2027届校园招聘-正式批\n招聘对象：2027届毕业生", "matched"),
    ],
)
def test_explicit_cohort_headers_and_degree_words_keep_qualified_cases_pending(
    text, status
):
    job = replace(
        BASE,
        title="RAG工程师",
        raw_content=text
        + "\n岗位职责\n负责RAG知识库及检索服务的研发。\n任职要求\n熟悉Python。",
    )
    check = next(
        c
        for c in classify_discovery_job(job, query=QUERY).checks
        if c["field"] == "graduation_year"
    )
    assert check["status"] == status


@pytest.mark.asyncio
async def test_cached_review_is_used_by_api_reads_without_more_model_calls(db_session):
    from datetime import UTC, datetime

    from src.domain.discovery import DiscoveryRun, LeadProvider
    from src.services.discovery_results import current_run_matches
    from src.services.job_lead_service import JobLeadService

    run = DiscoveryRun(
        id="review-run",
        user_id="u",
        source="test",
        source_url="https://example.com",
        search_query=QUERY,
        started_at=datetime.now(UTC),
    )
    db_session.add(run)
    db_session.commit()
    service = JobLeadService(db_session)
    lead = service.create_lead(
        user_id="u",
        provider=LeadProvider.EXTERNAL_AGENT,
        source_url=BASE.detail_url,
        discovery_run_id=run.id,
    )
    service.verify_stub(user_id="u", lead_id=lead.id, stub=BASE)
    engine = reviewer(
        {"status": "excluded", "reason": "供应链运营而非目标方向", "evidence": [DUTIES]}
    )
    await engine.review(
        BASE, query=QUERY, session=db_session, user_id="u", lead_id=lead.id
    )
    for _ in range(2):
        matches = current_run_matches(db_session, [run])[run.id]
        assert matches[0]["filter_status"] == "excluded"
        assert next(c for c in matches[0]["checks"] if c["field"] == "role")[
            "evidence"
        ] == [DUTIES]
    assert len(engine.client.requests) == 1
    run.search_query = "上海产品校招"
    assert (
        current_run_matches(db_session, [run])[run.id][0]["filter_status"] == "pending"
    )


@pytest.mark.asyncio
async def test_gateway_format_repairs_never_change_source_evidence(db_session):
    engine = reviewer(
        {"result": "excluded", "reason": "方向不符", "evidence": ["“" + DUTIES + "”"]}
    )
    result = await engine.review(
        BASE, query=QUERY, session=db_session, user_id="u", lead_id="lead"
    )
    assert result["decision"]["status"] == "excluded"
    assert result["decision"]["evidence"] == [DUTIES]
    assert result["proposed_output"]["evidence"] == ["“" + DUTIES + "”"]


def test_previous_scope_policy_cache_cannot_keep_excluding_after_upgrade():
    previous_key = hashlib.sha256(json.dumps([
        "job-role-review-v2", QUERY, BASE.title, BASE.raw_content, BASE.detail_url,
    ], ensure_ascii=False).encode()).hexdigest()
    assert valid_review({
        "fingerprint": previous_key,
        "decision": {"status": "excluded", "reason": "旧方向边界", "evidence": [DUTIES]},
    }, BASE, QUERY) is None
