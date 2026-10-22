from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from src.domain.application import CandidateJob, CandidateStatus
from src.domain.discovery import LeadProvider
from src.domain.source_review_cache import put_record
from src.services.application_service import ApplicationService
from src.services.body_quality import assess_body
from src.services.body_review_queue import review_items
from src.services.browser_job_reader import BrowserPageSnapshot
from src.services.direct_recruitment_search import DirectRecruitmentSearch
from src.services.discovery_matching import search_filter_conditions
from src.services.job_lead_service import JobLeadService, LeadVerificationFailure
from src.services.job_url import canonical_job_url
from src.services.lead_retry import can_retry
from src.services.result_status import enrich_result
from src.services.search_goal_service import SearchGoalService, posting_stub
from src.services.search_scheduling import listing_priority
from src.services.source_understanding import fingerprint
from src.services.url_reader import FetchedResponse
from tests.test_direct_recruitment_search import SOURCE
from tests.test_readable_detail_recovery import detail_html
from tests.test_search_goals import add_posting

SHELL = "Job Location：{{model.jobArea}}\nWhat We Offer\nWe offer a professional career.\nMain Responsibilities\n{{model.mainBusiness}}\nRequirements\n{{model.jobRequire}}\nApply"


@pytest.mark.parametrize("body,status", [
    ("", "empty"), ("工程师\n岗位职责\n任职要求\n加载中...", "empty"),
    (SHELL, "incomplete"), ("岗位职责：{{description}}", "incomplete"),
    ("开发 Java 后端服务。", "readable"),
    ("负责模板引擎，支持 {{model.field}} 语法。", "readable"),
    ("任职要求：熟悉Mustache模板。\n例如：\n{{model.field}}\n负责开发渲染服务。", "readable"),
    ("工作地点：上海\n负责 RAG 检索服务，熟悉 Python。", "readable"),
    ("Main Responsibilities\n请您详见岗位意向中的岗位职责\nRequirements\n请您详见岗位意向中的岗位要求", "reference_only"),
    ("岗位职责\n详见附件中的岗位说明\n任职要求\n本科以上", "reference_only"),
    ("岗位职责\n负责Java服务研发。\n更多详情参见岗位说明。\n任职要求\n本科以上", "readable"),
    ("岗位职责\n查看岗位申请并筛选候选人。\n任职要求\n本科以上", "readable"),
    ("Responsibilities\nRefer to the job description and develop the recruiting platform.\nRequirements\nJava", "readable"),
])
def test_transport_quality_does_not_require_headings_or_cohort(body, status):
    assert assess_body(body, title="工程师")["status"] == status


@pytest.mark.asyncio
async def test_placeholder_switches_to_browser_without_an_ai_call_and_recovers(db_session):
    class NeverModel:
        primary = True

        async def analyze_page(self, *args, **kwargs):
            pytest.fail("A page shell must be reread before semantic analysis")

    class Reader:
        async def fetch(self, url):
            return FetchedResponse(url, url, 200, "text/html", ("<h1>工程师</h1><pre>" + SHELL + "</pre>").encode())

        async def read(self, url):
            return BrowserPageSnapshot(url, url, "职位", detail_html(), "")

    service = JobLeadService(db_session, understanding=NeverModel())
    url = "https://unregistered.example/jobs/123"
    lead = service.create_lead(user_id="owner", provider=LeadProvider.EXTERNAL_AGENT, source_url=url)
    with pytest.raises(LeadVerificationFailure) as error:
        await service.verify_url(user_id="owner", lead_id=lead.id, reader=Reader(), official_hosts={"unregistered.example"})
    assert error.value.code == "page_body_incomplete"
    assert lead.job_posting_id is None and lead.retry_state["next_method"] == "browser"
    assert can_retry(lead.retry_state)
    service.understanding = None
    result = await service.verify_browser(user_id="owner", lead_id=lead.id, reader=Reader(),
                                          official_hosts={"unregistered.example"})
    assert "工具调用模块" in result.posting.raw_content
    assert lead.retry_state["mode"] == "succeeded"


@pytest.mark.asyncio
async def test_unrendered_browser_body_gets_three_failures_not_one(db_session):
    class Reader:
        async def read(self, url):
            return BrowserPageSnapshot(url, url, "工程师", "<h1>工程师</h1><pre>" + SHELL + "</pre>", SHELL)

    service = JobLeadService(db_session)
    lead = service.create_lead(user_id="owner", provider=LeadProvider.EXTERNAL_AGENT,
                               source_url="https://unregistered.example/jobs/123")
    for count in range(1, 4):
        with pytest.raises(LeadVerificationFailure) as error:
            await service.verify_browser(user_id="owner", lead_id=lead.id, reader=Reader(), official_hosts={"unregistered.example"})
        assert error.value.code == "browser_body_incomplete"
        assert lead.retry_state["transient_failures"] == count
        assert can_retry(lead.retry_state, now=datetime.now(UTC) + timedelta(hours=1)) == (count < 3)
    assert lead.job_posting_id is None
    snapshots = service.list_verifications(user_id="owner", lead_id=lead.id)
    assert any(s.field_evidence.get("body_quality", {}).get("status") == "incomplete" for s in snapshots)
    assert all(not s.field_evidence.get("ai_reading_pending") for s in snapshots)


def test_legacy_shell_leaves_semantic_queue_and_returns_to_reading(db_session):
    job = add_posting(db_session)
    job.raw_content = SHELL
    db_session.commit()
    service = SearchGoalService(db_session)
    goal = SimpleNamespace(user_id="owner", id="goal", version=1, query="上海后端校招",
                           conditions=search_filter_conditions("上海后端校招"))
    assert service.cached_posting("owner", job.source_url) is None
    assert not review_items(db_session, goal)
    candidates = service.refresh_candidates("owner", query=goal.query, conditions=goal.conditions, include_body_reviews=False)
    assert [c.source_url for c in candidates] == [job.source_url]


@pytest.mark.parametrize("variant", ["deptCodes=a", "deptCodes=b&pageIndex=2", "pageSize=30"])
def test_known_detail_selector_discards_list_filters(variant):
    assert canonical_job_url("https://example.com/campus/position/199907720043?" + variant) == "https://example.com/campus/position/199907720043"


@pytest.mark.parametrize("url", [
    "https://example.com/campus/position/199907720044", "https://example.com/social/position/199907720043",
    "https://example.com/campus/position/199907720043?channel=social",
    "https://example.com/tenant2/position/199907720043", "https://other.example.com/campus/position/199907720043",
])
def test_distinct_selectors_tenants_channels_and_hosts_remain_distinct(url):
    assert canonical_job_url(url) != "https://example.com/campus/position/199907720043"


def test_list_filters_are_kept_on_list_pages_and_spa_job_routes_preserved():
    assert canonical_job_url("https://example.com/list?deptCodes=a") != canonical_job_url("https://example.com/list?deptCodes=b")
    assert canonical_job_url("https://example.com/#/detail?jobId=12&deptCodes=x") == "https://example.com/#/detail?jobId=12"


def test_department_alias_preserves_saved_action_and_records(db_session):
    a, b = add_posting(db_session, identifier="a"), add_posting(db_session, identifier="b")
    a.source_url = "https://example.com/position/123?deptCodes=a"
    b.source_url = "https://example.com/position/123?deptCodes=b"
    db_session.get(CandidateJob, "candidate-b").status = "SAVED"
    db_session.commit()
    service = ApplicationService(db_session)
    rows = service.list_candidates(user_id="owner")
    assert len(rows) == 1 and rows[0].candidate.status == "SAVED"
    service.transition_candidate(user_id="owner", candidate_id=rows[0].candidate.id, target_status=CandidateStatus.IGNORED)
    assert db_session.get(CandidateJob, "candidate-a").status == "IGNORED"
    assert db_session.get(CandidateJob, "candidate-b").status == "IGNORED"
    assert len(SearchGoalService(db_session).postings("owner")) == 1


def ranking(items, *, runtime=None, known=()):
    engine = DirectRecruitmentSearch(sources=[SOURCE], query="上海 Agent 校招", reader=None, browser=None,
        on_event=lambda *_: None, understanding=runtime, known_urls=known)
    state = {"reader_kind": "html", "buffer": deepcopy(items), "listing_url": SOURCE.career_url}
    return engine, state


def card(index, text="Agent工程师 上海 校招"):
    return {"id": f"https://jobs.example.com/position/{index}", "title": text, "listing_text": text}


def test_card_location_is_used_but_city_in_responsibilities_is_not_a_gate():
    query = "上海 Agent 校招"
    good = listing_priority("Agent工程师\n工作地点：上海\n校园招聘", query, ["校招"])
    unknown = listing_priority("Agent工程师\n岗位职责：为北京客户开发服务。", query, ["校招"])
    bad = listing_priority("Agent工程师\n工作地点：深圳\n校园招聘", query, ["校招"])
    assert good < unknown < bad


@pytest.mark.asyncio
async def test_pool_dedup_new_jobs_and_waiting_candidates_get_detail_slots():
    items = [card(1), {**card(1), "id": card(1)["id"] + "?deptCodes=x"}, card(2), card(3), card(4)]
    engine, state = ranking(items, known=[card(1)["id"]])
    state["candidate_wait_rounds"] = {card(4)["id"]: 2}
    await engine._rank_buffer(SOURCE, state)
    urls = [canonical_job_url(item["id"]) for item in state["buffer"]]
    assert len(urls) == len(set(urls)) == 4
    assert urls[:3] == [card(2)["id"], card(3)["id"], card(4)["id"]]


@pytest.mark.asyncio
@pytest.mark.parametrize("wait_rounds,third", [(0, 3), (2, 4)])
async def test_waiting_tail_gets_one_slot_without_displacing_top_two(wait_rounds, third):
    engine, state = ranking([card(i) for i in range(1, 6)])
    state["candidate_wait_rounds"] = {card(4)["id"]: wait_rounds}
    await engine._rank_buffer(SOURCE, state)
    assert [item["id"] for item in state["buffer"][:3]] == [card(1)["id"], card(2)["id"], card(third)["id"]]
    assert len(state["buffer"]) == 5


@pytest.mark.asyncio
async def test_model_sees_pool_tail_and_changed_card_invalidates_ranking_cache():
    class Model:
        primary = True

        def __init__(self):
            self.calls = []

        async def rank_listing(self, texts, **kwargs):
            self.calls.append(texts)
            return list(reversed(range(len(texts))))

    model = Model()
    items = [card(i, f"Agent工程师 {i} 上海 校招") for i in range(60)]
    engine, state = ranking(items, runtime=model)
    await engine._rank_buffer(SOURCE, state)
    assert len(model.calls[0]) == 30 and any("工程师 56 " in value for value in model.calls[0])
    assert len(state["buffer"]) == 60
    await engine._rank_buffer(SOURCE, state)
    assert len(model.calls) == 1
    state["buffer"][0]["listing_text"] += "\n岗位职责：负责开发RAG检索服务"
    await engine._rank_buffer(SOURCE, state)
    assert len(model.calls) == 2


def result(checks):
    return {"filter_status": "pending", "review_status": "recommended", "match_tier": "expanded",
            "checks": checks, "decision_policy": "ai"}


@pytest.mark.parametrize("failures,state", [(0, "waiting"), (1, "retrying"), (3, "blocked")])
def test_waiting_and_failed_ai_never_claim_source_omission(db_session, failures, state):
    job = add_posting(db_session)
    conditions = search_filter_conditions("上海校招")
    attempt = {"fingerprint": fingerprint(posting_stub(job), conditions), "failures": failures}
    job.recruitment_context = put_record(job.recruitment_context, "source_review_attempt", attempt)
    match = result([{"field": "location", "status": "pending", "diagnosis": "not_extracted"}])
    status = enrich_result(match, job, None, conditions=conditions)["result_status"]
    assert status["analysis"]["state"] == state
    assert status["search"]["state"] == "pending" and not status["search"]["missing_fields"]


def test_understood_omission_is_distinct_from_personal_eligibility(db_session):
    job = add_posting(db_session)
    match = result([{"field": "location", "status": "matched"},
                    {"field": "graduation_year", "status": "pending", "diagnosis": "source_missing"}])
    projected = enrich_result(match, job, SimpleNamespace(degree="硕士", educations=[]), conditions={})
    assert projected["result_status"]["analysis"]["state"] == "completed"
    assert projected["result_status"]["search"]["missing_fields"] == ["届别"]
    assert projected["result_status"]["personal"]["state"] == "unreviewed"
    assert projected["review_status"] == "recommended"  # Broad browsing remains available.


def test_bad_old_body_cannot_recommend_exclude_or_claim_personal_pass(db_session):
    job = add_posting(db_session)
    job.raw_content = SHELL
    match = {**result([{"field": "role", "status": "excluded"}]), "filter_status": "excluded", "review_status": "excluded"}
    projected = enrich_result(match, job, None, conditions={})
    assert projected["filter_status"] == projected["review_status"] == "pending"
    assert projected["result_status"]["analysis"]["state"] == "reading_required"
    assert projected["checks"] == [] and projected["personal_requirements"] == []


def test_phd_conflict_and_search_match_are_independent_and_serialized(db_session):
    from src.api.schemas import DiscoveryResultMatchRead

    job = add_posting(db_session)
    job.raw_content = "岗位职责：开发Agent产品。\n任职要求：博士学历；优先条件：熟悉RAG。"
    match = result([{"field": "location", "status": "matched"}])
    projected = enrich_result(match, job, SimpleNamespace(degree="硕士", educations=[]), conditions={})
    assert projected["result_status"]["search"]["state"] == "matched"
    assert projected["personal_gate_conflict"] and projected["review_status"] == "pending"
    serialized = DiscoveryResultMatchRead.model_validate({**projected, "job_posting_id": job.id}).model_dump()
    assert serialized["result_status"]["personal"]["state"] == "conflict"
