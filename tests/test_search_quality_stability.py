"""General search contracts; synthetic boundary cases, not accuracy gold."""

import asyncio
from datetime import UTC, datetime, timedelta
from time import monotonic

import pytest

from src.config import Settings
from src.domain.discovery import DiscoveryRun
from src.domain.search_goal import SearchGoal, SearchGoalConditions
from src.infrastructure.llm_client import FakeModelClient
from src.services.discovery_matching import classify_discovery_job
from src.services.discovery_sources import JobStub
from src.services.job_lead_service import JobLeadService
from src.services.job_role_review import JobRoleReviewer, fingerprint
from src.services.lead_providers import LeadCandidate, LeadProviderKind
from src.services.search_goal_service import SearchGoalService
from src.services.search_intent import conditions_query, parse_conditions
from src.services.search_pipeline import VerificationFailure, run_search_pipeline


def job(direction="数据分析", body=None):
    return JobStub(
        source_id="contract", source_job_id="one", company="示例公司",
        title=direction + "工程师", locations=["上海"], job_type="campus",
        published_at=None, detail_url="https://example.com/jobs/one",
        raw_content=body or "面向2027届毕业生。\n岗位职责：\n负责业务需求梳理，协调不同团队确定交付范围，持续跟踪项目进展和质量，整理客户反馈并推动流程改善。\n任职要求：\n了解" + direction + "优先。",
    )


@pytest.mark.parametrize("text,roles", [
    ("上海大模型应用开发校招", ["大模型应用开发"]),
    ("上海Agent应用开发实习", ["agent应用开发"]),
    ("杭州数据分析校招", ["数据分析"]),
    ("深圳产品运营实习", ["产品运营"]),
    ("武汉测试平台开发校招", ["测试平台开发"]),
    ("成都后端基础平台校招", ["后端基础平台"]),
    ("上海大模型算法校招", ["大模型算法"]),
    ("深圳产品数据分析实习", ["产品数据分析"]),
])
def test_complete_direction_survives_condition_roundtrip(text, roles):
    scope = parse_conditions(text)
    assert scope.roles == roles
    assert not scope.keywords
    assert parse_conditions(conditions_query(scope)) == scope


def test_optional_role_is_not_a_required_gate():
    scope = parse_conditions("上海校招，数据分析优先")
    assert scope.roles == [] and scope.preferred_roles == ["数据分析"]
    verdict = classify_discovery_job(job("产品"), query=conditions_query(scope))
    assert verdict.filter_status == "matched"
    assert any(c["field"] == "preferred_role" and not c["required"] for c in verdict.checks)


@pytest.mark.parametrize("direction", ["数据分析", "产品运营", "固件开发", "前端", "后端", "大模型应用开发"])
def test_title_and_qualification_keywords_cannot_prove_actual_work(direction):
    scope = SearchGoalConditions(roles=[direction])
    assert classify_discovery_job(job(direction), query=conditions_query(scope)).filter_status == "pending"


@pytest.mark.parametrize("direction", ["数据分析", "产品运营", "固件开发"])
@pytest.mark.asyncio
async def test_paraphrased_duties_use_grounded_semantic_review(direction, db_session):
    posting = job(direction)
    query = conditions_query(SearchGoalConditions(roles=[direction]))
    model = FakeModelClient(output={"status": "excluded", "reason": "职责是项目协调", "evidence_ids": [0]})
    reviewer = JobRoleReviewer(Settings(_env_file=None), client=model)
    try:
        review = await reviewer.review(posting, query=query, session=db_session, user_id="u", lead_id="lead")
    finally:
        await reviewer.aclose()
    assert direction in model.requests[0].messages[-1].content
    assert review and review["decision"]["status"] == "excluded"
    assert classify_discovery_job(posting, query=query, role_review=review).filter_status == "excluded"


def test_edited_conditions_also_control_review_fingerprint_and_semantic_helpers():
    posting = job()
    scope = SearchGoalConditions(roles=["数据分析"])
    query = conditions_query(scope)
    from src.services.job_role_review import duty_text

    review = {"fingerprint": fingerprint(posting, query), "decision": {
        "status": "excluded", "reason": "职责为项目协调", "evidence": [duty_text(posting)],
    }}
    verdict = classify_discovery_job(posting, query="上海后端", conditions=scope.model_dump(), role_review=review)
    assert verdict.filter_status == "excluded"


def test_work_on_a_platform_for_a_direction_does_not_prove_that_direction():
    posting = job(body="岗位职责：\n负责数据分析平台的日常运维，执行集群部署、值班监控与故障排查。\n任职要求：\n熟悉Linux。")
    assert classify_discovery_job(posting, query="岗位方向：数据分析").filter_status == "pending"


def candidate(number, source="bad"):
    return LeadCandidate(provider=LeadProviderKind.EXTERNAL_AGENT,
                         source_url=f"https://{source}.example/jobs/{number}",
                         discovered_at=datetime.now(UTC))


@pytest.mark.asyncio
async def test_bootstrap_verify_review_and_drain_share_one_deadline():
    cancelled = asyncio.Event()
    events = []

    async def bootstrap(enqueue):
        await asyncio.sleep(.03)
        enqueue([candidate(1)])

    async def search(*_):
        await asyncio.sleep(.02)

    async def verify(_):
        await asyncio.sleep(.02)
        return "job", False

    async def review(_):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    start = monotonic()
    await run_search_pipeline(bootstrap=bootstrap, search=search, verify=verify, review=review,
                             canonicalize=lambda u: u, report=lambda *_: None,
                             seconds=.12, item_seconds=5, verification_seconds=5,
                             on_event=lambda k, d: events.append((k, d)))
    assert monotonic() - start < .5
    assert cancelled.is_set()
    assert any(k == "queue_budget" for k, _ in events)


@pytest.mark.asyncio
async def test_failed_source_is_deferred_while_other_sources_continue():
    attempted, events = [], []

    async def search(*_):
        return [*(candidate(i) for i in range(8)), candidate(9, "healthy")]

    async def verify(lead):
        attempted.append(lead.source_url)
        return VerificationFailure("source_timeout") if "bad.example" in lead.source_url else ("good", True)

    await run_search_pipeline(search=search, verify=verify, canonicalize=lambda u: u,
                             report=lambda *_: None, max_rounds=1, seconds=1,
                             source_key=lambda c: c.source_url.split("/")[2],
                             on_event=lambda k, d: events.append((k, d)))
    assert len([u for u in attempted if "bad.example" in u]) == 3
    assert candidate(9, "healthy").source_url in attempted
    deferred = [d for k, d in events if k == "verification_deferred"]
    assert len(deferred) == 5 and all(d["error_code"] == "source_circuit_open" for d in deferred)


@pytest.mark.asyncio
async def test_irrelevant_jobs_do_not_trip_source_failure_guard_and_queue_is_bounded():
    attempted, deferred = [], []

    async def search(*_):
        return [candidate(i) for i in range(9)]

    async def verify(lead):
        attempted.append(lead.source_url)
        return lead.source_url, False

    await run_search_pipeline(search=search, verify=verify, canonicalize=lambda u: u,
                             report=lambda *_: None, max_rounds=1, seconds=1, max_pending=5,
                             source_key=lambda _: "same",
                             on_event=lambda k, d: deferred.append(d) if k == "verification_deferred" else None)
    assert len(attempted) == 5
    assert len(deferred) == 4 and all(d["error_code"] == "verification_queue_full" for d in deferred)


def run_row(identifier, user="owner", version=1):
    return DiscoveryRun(id=identifier, user_id=user, source="test", source_url="https://example.com",
                        search_goal_id="goal", search_goal_version=version, status="COMPLETED",
                        started_at=datetime.now(UTC))


def test_resume_uses_latest_status_same_goal_version_and_keeps_ignored_closed_out(db_session):
    for run in [run_row("old"), run_row("new"), run_row("foreign", user="other"), run_row("changed", version=2)]:
        db_session.add(run)
    db_session.commit()
    leads = JobLeadService(db_session)
    now = datetime.now(UTC)
    for number, run, user, status, ignored in [
        (1, "old", "owner", "DEFERRED", False), (2, "old", "owner", "FAILED", False),
        (2, "new", "owner", "CLOSED", False), (3, "old", "owner", "DEFERRED", True),
        (4, "foreign", "other", "DEFERRED", False), (5, "changed", "owner", "DEFERRED", False),
    ]:
        lead = leads.capture_candidate(user_id=user, discovery_run_id=run, candidate=candidate(number))
        lead.status = status
        lead.selection_status = "IGNORED" if ignored else "DISCOVERED"
        lead.created_at = now + timedelta(seconds=int(run == "new"))
        db_session.commit()
    pending = SearchGoalService(db_session).resume_candidates("owner", goal_id="goal", version=1, current_run_id="current")
    assert [c.source_url for c in pending] == [candidate(1).source_url]
    assert db_session.get(DiscoveryRun, "old") is not None


@pytest.mark.parametrize("manual", [False, True])
def test_legacy_scope_upgrade_never_overwrites_manual_edits(db_session, manual):
    old = SearchGoalConditions(roles=["llm"])
    goal = SearchGoal(id="goal", user_id="owner", name="目标", version=1,
                      input_text="大模型应用开发校招", query=conditions_query(old), conditions=old.model_dump(),
                      condition_sources={"roles": "用户修改" if manual else "本次输入"})
    db_session.add(goal)
    db_session.commit()
    resolved = SearchGoalService(db_session).get("owner", "goal")
    assert resolved.conditions["roles"] == (["llm"] if manual else ["大模型应用开发"])
    assert resolved.version == (1 if manual else 2)
    assert SearchGoalService(db_session).get("owner", "goal").version == resolved.version


def test_cache_reuse_requires_ownership_freshness_and_official_open_evidence(db_session):
    from src.domain.application import CandidateJob
    from src.domain.job import JobPosting

    now = datetime.now(UTC)
    posting = JobPosting(id="job", title="岗位", raw_content=job().raw_content,
                         source_url=job().detail_url, verification_status="VERIFIED_OFFICIAL",
                         availability_status="ACTIVE", last_verified_at=now, retrieved_at=now,
                         content_hash="hash", trace_id="test")
    db_session.add(posting)
    db_session.add(CandidateJob(id="link", user_id="owner", job_posting_id="job", status="DISCOVERED"))
    db_session.commit()
    service = SearchGoalService(db_session)
    assert service.cached_posting("owner", posting.source_url) == posting
    assert service.cached_posting("other", posting.source_url) is None
    for state in [{"last_verified_at": now - timedelta(days=8)},
                  {"last_verified_at": now, "availability_status": "CLOSED"},
                  {"availability_status": "ACTIVE", "verification_status": "USER_PROVIDED"}]:
        for name, value in state.items():
            setattr(posting, name, value)
        db_session.commit()
        assert service.cached_posting("owner", posting.source_url) is None
