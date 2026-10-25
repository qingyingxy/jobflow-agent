"""Current-policy display, protected discovery and resumable shortlist regressions."""
import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from src.config import Settings
from src.domain.discovery import DiscoveryRun
from src.infrastructure.llm_client import FakeModelClient
from src.main import app
from src.services.direct_recruitment_search import DirectRecruitmentSearch
from src.services.discovery_matching import (
    classify_discovery_job,
    search_filter_conditions,
)
from src.services.search_goal_service import SearchGoalService, posting_stub
from src.services.source_understanding import (
    PREVIOUS_VERSION,
    VERSION,
    SourceUnderstanding,
    fingerprint,
)
from tests.test_ai_search_workflow import decision
from tests.test_direct_recruitment_search import ITEM, QUERY, SOURCE, ListingBrowser
from tests.test_search_goals import add_posting, create_goal


@pytest.mark.asyncio
@pytest.mark.parametrize("old_policy", [None, "hybrid", "ai"])
async def test_library_run_and_compact_history_invalidate_old_decisions(db_session, monkeypatch, old_policy):
    from src import config

    posting = add_posting(db_session)
    posting.raw_content = "后端工程师\n上海\n2027届校园招聘\n负责后端服务开发及接口设计，保证服务可靠性。"
    with TestClient(app) as client:
        goal = create_goal(client, text="上海后端校招2027届")
        stub = posting_stub(posting)
        if old_policy:
            posting.recruitment_context = {"source_understanding": {
                "version": PREVIOUS_VERSION, "policy": old_policy,
                "fingerprint": fingerprint(stub, goal["conditions"], version=PREVIOUS_VERSION),
                "output": {"decisions": [decision("role", "excluded", [3])]}},
                "understanding_policy": old_policy}
        run = DiscoveryRun(id="old-run", user_id="owner", source="test", source_url=posting.source_url,
            status="SUCCEEDED", started_at=datetime.now(UTC), search_query=goal["query"],
            goal_conditions=goal["conditions"], search_goal_id=goal["id"], search_goal_version=1,
            result_matches=[{"job_posting_id": posting.id, "filter_status": "excluded",
                             "match_tier": "expanded", "review_status": "excluded"}])
        db_session.add(run)
        db_session.commit()
        settings = Settings(_env_file=None, structured_model_provider="openai_compatible")
        monkeypatch.setattr(config, "get_settings", lambda: settings)
        endpoints = [f"/api/discovery/goals/{goal['id']}/library", "/api/discovery/runs/old-run",
                     "/api/discovery/runs/old-run?compact=true", "/api/discovery/runs?compact=true"]
        for endpoint in endpoints:
            response = client.get(endpoint, headers={"X-User-ID": "owner"})
            assert response.status_code == 200, response.text
            data = response.json()
            match = (data[0] if isinstance(data, list) else data)["result_matches"][0]
            assert match["filter_status"] == "pending" and match["review_status"] == "pending"
            assert match["filter_version"] == VERSION and match["decision_policy"] == "ai"
            assert all(check.get("version") == VERSION for check in match["checks"])
        model = FakeModelClient(output={"decisions": [decision("location", "matched", [1]),
            decision("role", "matched", [3]), decision("job_type", "matched", [2]),
            decision("graduation_year", "matched", [2])]})
        updated = await SourceUnderstanding(settings, client=model).review(posting_stub(posting),
            query=goal["query"], conditions=goal["conditions"])
        posting.recruitment_context = updated.recruitment_context
        db_session.commit()
        library = SearchGoalService(db_session).library("owner", goal["id"])
        assert library["result_matches"][0]["filter_status"] == "matched"


@pytest.mark.asyncio
async def test_historical_model_work_cannot_block_listing_or_new_job(db_session):
    entered, release = asyncio.Event(), asyncio.Event()
    model = FakeModelClient(output={"decisions": [decision("location", "matched", [1])]})

    class Gated:
        async def generate(self, request):
            payload = json.loads(request.messages[-1].content)
            if payload["url"].endswith("/old"):
                entered.set()
                await release.wait()
            if request.schema_name == "job_listing_order":
                return await FakeModelClient(output={"ranked_ids": [1, 0]}).generate(request)
            return await model.generate(request)

    stub = replace(posting_stub(add_posting(db_session)), detail_url="https://example.com/old",
                   raw_content="工程师\n上海\n负责业务系统开发和维护，包含稳定性建设、架构设计和持续迭代，并与业务团队共同交付产品。")
    # The limit now applies across all interpretation lanes: one running history
    # call leaves one shared slot for listing/new work, which can run in sequence.
    runtime = SourceUnderstanding(Settings(_env_file=None, web_search_semantic_concurrency=2,
        web_search_semantic_max_calls=4, web_search_semantic_history_max_calls=1), client=Gated(), known_urls=[stub.detail_url])
    old = asyncio.create_task(runtime.review(stub, query="上海"))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        ranked, fresh = await asyncio.wait_for(asyncio.gather(
            runtime.rank_listing(["运维", "Agent工程师"], url="https://example.com/list"),
            runtime.review(replace(stub, detail_url="https://example.com/new"), query="上海")), 1)
        assert ranked == [1, 0] and classify_discovery_job(fresh, query="上海").filter_status == "matched"
        assert not old.done()
    finally:
        release.set()
        await old
    blocked = await runtime.review(replace(stub, detail_url="https://example.com/old-2"), query="上海", historical=True)
    assert blocked.recruitment_context["source_review_attempt"]["error_code"] == "semantic_budget"
    assert blocked.recruitment_context["source_review_attempt"]["failures"] == 0
    assert runtime.calls == 3


@pytest.mark.asyncio
async def test_history_queue_does_not_occupy_fresh_review_consumers():
    from src.services.search_pipeline import run_search_pipeline
    from tests.test_search_execution import candidate

    entered, fresh_done = asyncio.Event(), asyncio.Event()
    events = []

    async def bootstrap(enqueue):
        enqueue([candidate(1)])
        await entered.wait()
        enqueue([candidate(2)])

    async def review(job_id):
        if job_id == "old":
            entered.set()
            await asyncio.wait_for(fresh_done.wait(), 1)
        else:
            events.append("new")
            fresh_done.set()
        events.append(job_id)
        return job_id, True

    async def verify(item):
        return ("old" if item.source_url == candidate(1).source_url else "new"), False

    async def search(_):
        return None

    await run_search_pipeline(search=search, verify=verify, review=review,
        historical_review=lambda item: item.source_url == candidate(1).source_url,
        bootstrap=bootstrap, bootstrap_concurrent=True, review_concurrency=1,
        report=lambda *_: None, canonicalize=lambda url: url, seconds=3)
    assert fresh_done.is_set() and events.index("new") < events.index("old")


@pytest.mark.asyncio
async def test_timeout_retry_extends_transport_and_outer_deadline_from_saved_body(db_session, monkeypatch):
    from src.services import source_understanding as module

    timeouts = []

    def factory(settings):
        timeouts.append(settings.llm_timeout_seconds)

        class Transport:
            async def generate(self, request):
                # A response too slow for the first deadline, fast enough for retry.
                await asyncio.sleep(.14)
                return await FakeModelClient(output={"decisions": [decision("location", "matched", [1])]}).generate(request)
        return Transport()

    monkeypatch.setattr(module, "create_structured_model_client", factory)
    settings = Settings(_env_file=None, structured_model_provider="openai_compatible",
                        web_search_semantic_timeout_seconds=.1, web_search_semantic_retry_timeout_seconds=.4)
    stub = replace(posting_stub(add_posting(db_session)), raw_content="工程师\n上海\n负责业务系统开发和维护，包含稳定性建设、架构设计和持续迭代，并与业务团队共同交付产品。")
    failed = await SourceUnderstanding(settings).review(stub, query="上海")
    assert failed.recruitment_context["source_review_attempt"]["error_code"] == "semantic_timeout"
    # Exercise a real previous-version timeout with the same source/conditions.
    attempt = failed.recruitment_context["source_review_attempt"]
    attempt.update(next_retry_at=None, fingerprint=fingerprint(stub, search_filter_conditions("上海"), version=PREVIOUS_VERSION))
    updated = await SourceUnderstanding(settings).review(failed, query="上海")
    assert timeouts == [.1, .2]
    assert updated.recruitment_context["source_review_attempt"]["error_code"] is None
    assert updated.raw_content == stub.raw_content
    assert classify_discovery_job(updated, query="上海").filter_status == "matched", updated.recruitment_context
    assert updated.recruitment_context["source_review_attempt"]["failures"] == 0


@pytest.mark.asyncio
async def test_multiterm_shortlist_keeps_metadata_original_proof_and_unchecked_rows():
    keywords = []
    observed_pools = []

    class Browser(ListingBrowser):
        async def read_search_listing(self, url):
            page = await super().read_search_listing(url)
            params = parse_qs(urlsplit(url).query)
            if not params:
                return page
            term = params["keywords"][0]
            keywords.append(term)
            # A weak first page must not monopolize the three detail checks.
            items = ([{**ITEM, "id": str(i), "title": "基础设施工程师",
                "description": "负责集群容量扩展和故障排查，维护服务器系统稳定运行。"} for i in range(1, 4)]
                if term == "agent" else [{**ITEM, "id": "4" if term == "rag" else "5",
                                        "title": "智能应用工程师"}])
            page.recruitment_api[0]["payload"]["data"].update(job_post_list=items, count=len(items))
            return replace(page, raw_html="".join(f'<a href="/campus/position/{i["id"]}/detail">{i["title"]}</a>' for i in items))

    class Ranker:
        async def generate(self, request):
            pool = json.loads(request.messages[-1].content)["items"]
            observed_pools.append(pool)
            assert all("上海" in row["text"] and "岗位职责" in row["text"] for row in pool)
            order = sorted(pool, key=lambda row: ("RAG知识库" not in row["text"], "已入库岗位" in row["text"]))
            return await FakeModelClient(output={"ranked_ids": [row["id"] for row in order]}).generate(request)

    runtime = SourceUnderstanding(Settings(_env_file=None), client=Ranker(), query=QUERY)
    state, candidates, events = {}, [], []
    search = DirectRecruitmentSearch(sources=[SOURCE], query=QUERY, reader=None, browser=Browser(),
        understanding=runtime, on_event=lambda k, d: events.append((k, d)), states=state,
        known_urls={"https://jobs.bytedance.com/campus/position/4/detail"})
    await search.discover(candidates.extend)
    assert len(candidates) == 3, (events, search.states)
    assert len(observed_pools[0]) == 5
    assert [c.source_job_id for c in candidates[:2]] == ["5", "4"]
    assert keywords[:3] == ["agent", "rag", "大模型应用开发"]
    for candidate in candidates:
        evidence = search.evidence[candidate.source_url]
        assert candidate.source_job_id in {str(item["id"]) for item in evidence.api_record["payload"]["data"]["job_post_list"]}
        assert parse_qs(urlsplit(evidence.listing_url).query)["keywords"][0] == evidence.api_record["request"]["keyword"]
    remaining = {item["id"] for item in search.states[SOURCE.id]["buffer"]}
    assert len(remaining) == 2
    again = []
    resumed = DirectRecruitmentSearch(sources=[SOURCE], query=QUERY, reader=None, browser=Browser(),
        understanding=runtime, on_event=lambda *_: None, states=search.states)
    await resumed.discover(again.extend)
    assert {c.source_job_id for c in again} == remaining
    assert resumed.states[SOURCE.id]["status"] == "completed"


@pytest.mark.asyncio
async def test_ranking_timeout_publishes_saved_candidates_instead_of_losing_company():
    class Browser(ListingBrowser):
        async def read_search_listing(self, url):
            page = await super().read_search_listing(url)
            if not urlsplit(url).query:
                return page
            items = [{**ITEM, "id": str(i)} for i in range(5)]
            page.recruitment_api[0]["payload"]["data"].update(job_post_list=items, count=5)
            return replace(page, raw_html="".join(f'<a href="/campus/position/{i}/detail">Agent工程师</a>' for i in range(5)))

    class Slow:
        async def generate(self, request):
            await asyncio.Event().wait()

    runtime = SourceUnderstanding(Settings(_env_file=None), client=Slow(), query=QUERY)
    candidates = []
    search = DirectRecruitmentSearch(sources=[SOURCE], query=QUERY, reader=None, browser=Browser(),
        understanding=runtime, on_event=lambda *_: None, company_seconds=.3)
    await search.discover(candidates.extend)
    assert len(candidates) == 3
    assert len(search.states[SOURCE.id]["buffer"]) == 2
    assert search.states[SOURCE.id].get("ranking_version") is None


@pytest.mark.asyncio
async def test_timeout_fallback_prefers_new_agent_duties_to_old_exact_title():
    from time import monotonic

    from src.services.direct_recruitment_search import search_keywords

    query = "工作地点：北京、上海；岗位方向：ai agent、rag、ai产品；招聘类型：校招；届别：2027届"
    assert search_keywords(query) == ["agent", "rag", "ai产品"]

    class Slow:
        primary = True

        async def rank_listing(self, *args, **kwargs):
            await asyncio.Event().wait()

    old = {"id": "https://example.com/jobs/1", "title": "AI Agent工程师",
           "listing_text": "AI Agent工程师 上海 校招 设计Agent系统和工具调用"}
    new = {"id": "https://example.com/jobs/2", "title": "软件研发工程师",
           "listing_text": "软件研发工程师 上海 校招 负责Agent系统和工具调用开发"}
    other = {"id": "https://example.com/jobs/3", "title": "财务专员", "listing_text": "上海 校招 财务专员"}
    state = {"reader_kind": "html", "buffer": [old, other, new]}
    events = []
    search = DirectRecruitmentSearch(sources=[SOURCE], query=query, reader=None, browser=None,
        understanding=Slow(), known_urls={old["id"]}, on_event=lambda k, d: events.append((k, d)))
    search.read_deadlines[SOURCE.id] = monotonic() + .52
    await search._rank_buffer(SOURCE, state)
    assert [item["id"] for item in state["buffer"]] == [new["id"], old["id"], other["id"]]
    assert events[-1][1]["stage"] == "ranking_timeout"
    assert events[-1][1]["candidates"][0]["known"] is False


def test_html_ranking_keeps_metadata_with_its_own_card():
    from src.services.recruitment_listing import listing_card_texts

    cards = listing_card_texts('<ul><li><a href="/jobs/1">产品经理</a><p>上海 校招 AI产品需求和方案设计</p></li>'
        '<li><a href="/jobs/2">运维工程师</a><p>成都 实习 集群维护</p></li></ul>',
        url="https://example.com/jobs", job_urls=["https://example.com/jobs/1", "https://example.com/jobs/2"])
    assert "上海 校招" in cards["https://example.com/jobs/1"]
    assert "成都" not in cards["https://example.com/jobs/1"]
    assert "成都 实习" in cards["https://example.com/jobs/2"]


@pytest.mark.asyncio
async def test_embedded_page_analysis_cannot_be_promoted_across_prompt_versions(db_session):
    import hashlib

    from src.services.source_understanding import (
        attach_page_understanding,
        checked_decisions,
    )

    stub = posting_stub(add_posting(db_session))
    conditions = search_filter_conditions("上海")
    context = {"text_sections": {"content_hash": hashlib.sha256(stub.raw_content.encode()).hexdigest(),
        "duties": [stub.raw_content], "requirements": [], "understanding": {
            "version": PREVIOUS_VERSION, "conditions": conditions,
            "output": {"decisions": [decision("location", "matched", [0])]}}}}
    updated = attach_page_understanding(replace(stub, recruitment_context=context))
    assert not checked_decisions(updated, conditions)
    assert updated.recruitment_context["source_review_attempt"]["error_code"] == "semantic_pending"
    assert classify_discovery_job(updated, query="上海").filter_status == "pending"
