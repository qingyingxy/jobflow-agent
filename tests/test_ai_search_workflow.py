"""AI-led reading must retain evidence, recover false exclusions and resume safely."""
import asyncio
import json
from dataclasses import replace

import httpx
import pytest

from src.config import Settings
from src.domain.discovery import LeadProvider
from src.infrastructure.llm_client import FakeModelClient
from src.services.discovery_matching import (
    classify_discovery_job,
    search_filter_conditions,
)
from src.services.discovery_sources import JobStub
from src.services.job_detail_scope import readable_page_text
from src.services.job_lead_service import JobLeadService
from src.services.source_understanding import (
    SourceUnderstanding,
    checked_decisions,
    paragraphs,
)
from src.services.url_reader import FetchedResponse

QUERY = "北京或上海 AI Agent、RAG、AI产品 2027届 校招"
URL = "https://example.com/jobs/17"
RAW = """<main><h1>智能助手产品伙伴</h1><div>上海市 · 校园招聘 · 发布于2026-07-21</div>
<h1>职责要求：</h1><p>定义知识助手的用户需求，设计多轮任务产品方案，负责功能迭代与效果评估。</p>
<p>本科以上学历，能够与工程团队合作，具有良好的产品分析和沟通能力。</p></main>
<aside><h1>你的AI求职搭子来了</h1><p>推荐岗位：成都数据运营，仅限2026届。</p></aside>"""


def decision(field, status, ids, diagnosis="supported"):
    return {"field": field, "status": status, "evidence_ids": ids, "diagnosis": diagnosis, "reason": "依据当前岗位完整原文"}


def page_output():
    parts = paragraphs(readable_page_text(RAW))
    title = parts.index("智能助手产品伙伴")
    loc = next(i for i, p in enumerate(parts) if "上海市" in p)
    duty = next(i for i, p in enumerate(parts) if "定义知识助手" in p)
    req = next(i for i, p in enumerate(parts) if "本科以上" in p)
    return {"page_type": "single_job", "title": parts[title], "first_paragraph": title,
        "last_paragraph": req, "duty_ids": [duty], "requirement_ids": [req], "decisions": [
            decision("location", "matched", [loc]), decision("job_type", "matched", [loc]),
            decision("role", "matched", [duty]),
            decision("graduation_year", "pending", [], "source_missing")]}


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["http", "browser"])
async def test_one_read_handles_column_and_modal_titles_and_keeps_missing_cohort(db_session, transport):
    from src.services.browser_job_reader import BrowserPageSnapshot

    client = FakeModelClient(output=page_output())
    runtime = SourceUnderstanding(Settings(_env_file=None), client=client, query=QUERY)
    service = JobLeadService(db_session, understanding=runtime)
    lead = service.create_lead(user_id="ai-user", provider=LeadProvider.EXTERNAL_AGENT, source_url=URL)

    class Reader:
        async def fetch(self, url):
            return FetchedResponse(requested_url=url, final_url=url, status_code=200,
                                   content_type="text/html", body=RAW.encode())

        async def read(self, url):
            return BrowserPageSnapshot(requested_url=url, final_url=url, title="招聘官网",
                                       raw_html=RAW, visible_text=readable_page_text(RAW))

    result = await getattr(service, "verify_url" if transport == "http" else "verify_browser")(
        user_id="ai-user", lead_id=lead.id, reader=Reader(), official_hosts={"example.com"}, official_only=True)
    from src.services.search_goal_service import posting_stub

    stub = posting_stub(result.posting)
    assert "求职搭子" not in stub.raw_content and "成都" not in stub.raw_content
    decisions = checked_decisions(stub, search_filter_conditions(QUERY))
    assert len(decisions) == 4
    assert decisions["graduation_year"]["diagnosis"] == "source_missing"
    assert decisions["role"]["status"] == "matched"
    assert all(q in stub.raw_content for d in decisions.values() for q in d["evidence"])
    assert await runtime.review(stub, query=QUERY) is stub
    assert len(client.requests) == 1
    assert client.requests[0].schema_name == "job_page_understanding"
    # Editing a goal or source must invalidate its interpretation, not its snapshot.
    assert not checked_decisions(stub, search_filter_conditions(QUERY.replace("2027", "2028")))
    assert not checked_decisions(replace(stub, raw_content=stub.raw_content + "\n仅限2026届"), search_filter_conditions(QUERY))


@pytest.mark.asyncio
async def test_ai_reviews_a_rule_exclusion_and_overrides_wrong_metadata():
    body = "智能助手产品伙伴\n工作地点：上海市\n负责定义知识助手的用户需求，设计多轮任务产品方案并迭代产品。"
    stub = JobStub("s", "1", "公司", "智能助手产品伙伴", ["合肥"], None, None, URL, body)
    query = "上海 AI产品"
    assert classify_discovery_job(stub, query=query).filter_status == "excluded"
    runtime = SourceUnderstanding(Settings(_env_file=None), client=FakeModelClient(output={"decisions": [
        decision("location", "matched", [1]), decision("role", "matched", [2])]}))
    updated = await runtime.review(stub, query=query)
    assert classify_discovery_job(updated, query=query).filter_status == "matched"
    assert len(runtime.client.requests) == 1


@pytest.mark.asyncio
async def test_timeout_preserves_job_and_later_review_can_finish():
    class Slow:
        async def generate(self, request):
            await asyncio.Event().wait()

    body = "智能助手产品伙伴\n工作地点：上海市\n负责定义知识助手的用户需求并设计产品方案，持续跟踪效果并完善用户体验。"
    stub = JobStub("s", "1", "公司", "智能助手产品伙伴", ["上海"], None, None, URL, body)
    runtime = SourceUnderstanding(Settings(_env_file=None, web_search_semantic_timeout_seconds=.02), client=Slow())
    updated = await runtime.review(stub, query="上海")
    assert updated.raw_content == body
    assert classify_discovery_job(updated, query="上海").filter_status == "pending"
    assert updated.recruitment_context["source_review_attempt"]["error_code"] == "semantic_timeout"
    context = {**updated.recruitment_context, "source_review_attempt": {
        **updated.recruitment_context["source_review_attempt"], "next_retry_at": None}}
    retry = SourceUnderstanding(Settings(_env_file=None), client=FakeModelClient(output={"decisions": [
        decision("location", "matched", [1])]}))
    completed = await retry.review(replace(updated, recruitment_context=context), query="上海")
    assert classify_discovery_job(completed, query="上海").filter_status == "matched"


@pytest.mark.asyncio
@pytest.mark.parametrize("override", [{"evidence_ids": [999]}, {"basis": "inferred"}])
async def test_invalid_quote_or_inference_never_becomes_a_confirmed_match(override):
    body = "智能助手产品伙伴\n工作地点：上海市\n负责定义知识助手的用户需求并设计产品方案，持续跟踪效果并完善用户体验。"
    stub = JobStub("s", "1", "公司", "智能助手产品伙伴", ["上海"], None, None, URL, body)
    runtime = SourceUnderstanding(Settings(_env_file=None), client=FakeModelClient(output={"decisions": [
        {**decision("location", "matched", [1]), **override}]}))
    updated = await runtime.review(stub, query="上海")
    assert not checked_decisions(updated, search_filter_conditions("上海"))
    assert classify_discovery_job(updated, query="上海").filter_status == "pending"


@pytest.mark.asyncio
async def test_search_keeps_link_purpose_and_bounds_initial_admission(db_session):
    from src.services.responses_search import ResponsesSearchProvider
    rows = [{"url": f"https://example.com/jobs/{i}", "title": f"AI产品经理{i}",
                 "purpose": "recommended", "reason": "上海校招岗位"} for i in range(7)]
    rows.append({"url": "https://example.com/jobs/social", "title": "AI产品经理",
                     "purpose": "negative", "reason": "此岗位明确为社招，不符合校招要求"})
    response = {"status": "completed", "output": [
        {"type": "web_search_call", "status": "completed", "action": {"sources": [
            {"url": "https://example.com/jobs/reference", "title": "参考职位"}]}},
        {"type": "message", "content": [{"type": "output_text", "text": json.dumps({"results": rows})}]}]}
    provider = ResponsesSearchProvider(query=QUERY, base_url="https://api.example.com/v1", api_key="test",
        model="test", transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response)))
    candidates = await provider.discover()
    assert sum(not c.search_context["deferred"] for c in candidates) == 5
    negative = next(c for c in candidates if c.source_url.endswith("/social"))
    reference = next(c for c in candidates if c.source_url.endswith("/reference"))
    assert negative.search_context["purpose"] == "negative" and negative.search_context["deferred"]
    assert reference.search_context["origins"] == ["tool_source"] and reference.search_context["deferred"]
    saved = JobLeadService(db_session).capture_candidate(user_id="ai-user", candidate=negative)
    assert saved.extracted_fields["search_context"] == negative.search_context


@pytest.mark.asyncio
async def test_listing_order_cannot_add_or_discard_observed_jobs():
    client = FakeModelClient(outputs=[{"ranked_ids": [2, 0, 1]}, {"ranked_ids": [7, 0]}])
    runtime = SourceUnderstanding(Settings(_env_file=None), client=client, query=QUERY)
    assert await runtime.rank_listing(["运维", "后端", "AI产品"], url=URL) == [2, 0, 1]
    assert await runtime.rank_listing(["数据", "产品"], url=URL) == [0, 1]


@pytest.mark.asyncio
async def test_closed_page_skips_model_and_unrelated_closed_card_does_not_close_job(db_session):
    from src.services.job_detail_scope import closed_page_notice
    from src.services.job_lead_service import LeadVerificationFailure

    assert closed_page_notice(RAW + '<aside><h2>推荐职位</h2><p>该职位已下线</p></aside>', url=URL) is None
    runtime = SourceUnderstanding(Settings(_env_file=None), client=FakeModelClient(output={}), query=QUERY)
    service = JobLeadService(db_session, understanding=runtime)
    lead = service.create_lead(user_id="ai-user", provider=LeadProvider.EXTERNAL_AGENT, source_url=URL)

    class Reader:
        async def fetch(self, url):
            return FetchedResponse(requested_url=url, final_url=url, status_code=200,
                content_type="text/html", body='<main><p>该职位已下线</p></main>'.encode())

    with pytest.raises(LeadVerificationFailure, match="下线"):
        await service.verify_url(user_id=lead.user_id, lead_id=lead.id, reader=Reader(), official_hosts={"example.com"})
    assert runtime.calls == 0


@pytest.mark.asyncio
async def test_failed_page_interpretation_resumes_snapshot_without_another_fetch(db_session):
    from src.services.job_lead_service import LeadVerificationFailure

    raw = RAW.replace('<h1>', '<div>').replace('</h1>', '</div>')
    good = page_output()
    runtime = SourceUnderstanding(Settings(_env_file=None), client=FakeModelClient(outputs=[{}, good]), query=QUERY)
    service = JobLeadService(db_session, understanding=runtime)
    lead = service.create_lead(user_id="ai-user", provider=LeadProvider.EXTERNAL_AGENT, source_url=URL)

    class Reader:
        calls = 0

        async def fetch(self, url):
            self.calls += 1
            assert self.calls == 1
            return FetchedResponse(requested_url=url, final_url=url, status_code=200,
                content_type="text/html", body=raw.encode())

    reader = Reader()
    with pytest.raises(LeadVerificationFailure) as error:
        await service.verify_url(user_id=lead.user_id, lead_id=lead.id, reader=reader, official_hosts={"example.com"})
    assert error.value.code == "semantic_page_pending"
    retry = SourceUnderstanding(Settings(_env_file=None), client=FakeModelClient(output=good), query=QUERY)
    result = await JobLeadService(db_session, understanding=retry).verify_url(
        user_id=lead.user_id, lead_id=lead.id, reader=reader, official_hosts={"example.com"})
    assert result.posting.title == "智能助手产品伙伴"
    assert reader.calls == 1


def test_web_fallback_becomes_ready_even_after_a_candidate_was_published(monkeypatch):
    from src.services import direct_recruitment_search as module
    search = module.DirectRecruitmentSearch(sources=[], query=QUERY, reader=None, browser=None,
                                            on_event=lambda *_: None)
    search.running = True
    search.pending_sources = {"company"}
    search.active_started = {"company": 1}
    search.published_sources = {"company"}
    search.last_progress = {"company": 2}
    monkeypatch.setattr(module, "monotonic", lambda: 11)
    assert search.fallback_ready("company")


@pytest.mark.asyncio
async def test_saved_goal_agent_selects_queries_inside_the_rotated_company(db_session, monkeypatch):
    from src.services import multiround_search as execution
    from src.services.search_decision import DecisionResult, SearchDecisionPlanner
    from tests.test_company_coverage import goal_and_store, mock_runtime, run_search

    calls = mock_runtime(monkeypatch, db_session, rounds=1)
    settings = execution.get_settings().model_copy(update={"web_search_decision_mode": "agent"})
    monkeypatch.setattr(execution, "get_settings", lambda: settings)
    choices = []

    async def choose(self, *, tasks, observation, **kwargs):
        assert observation["must_search"]
        assert all(task.company_id == "baidu" and "百度" in task.query for task in tasks)
        assert all("site:" not in task.query for task in tasks)  # No working listing observed yet.
        choices.extend(tasks)
        return DecisionResult("search_web", task=tasks[-1], reason="选择当前公司内的另一个查询")

    monkeypatch.setattr(SearchDecisionPlanner, "choose", choose)
    goal, _ = goal_and_store(db_session, ["baidu"])
    await run_search(db_session, goal, "ai-scope")
    assert choices and calls == [("baidu", choices[-1].query)]
