import asyncio
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from src.domain.campaign import CampaignDiscoveryTask, CampaignWatch
from src.domain.company_source import DiscoveredCompany
from src.infrastructure.llm_client import FakeModelClient
from src.services.campaign_company_agent import CampaignCompanyAgent, DiscoveryAction
from src.services.campaign_discovery import (
    _runtime,
    enqueue_discovery,
    run_discovery_step,
)
from tests.test_company_discovery import CAREER, HOME, NAME, PROOF, Pages, lead
from tests.test_company_discovery_queue import SETTINGS


def action(kind, **values):
    return DiscoveryAction(action=kind, reason="根据当前证据决定", query=values.get("query", ""),
                           url=values.get("url", ""), company_id=values.get("company_id", ""))


def identity_action(kind, *, url="", status="verified", home=HOME, career=CAREER, reason="已读企业官网与其招聘页面，确认公司身份及入口", quote="招聘公司为新星科技"):
    return {"action": kind, "reason": "依据已读页面判断", "url": url, "query": "", "control_index": None,
            "report": {"status": status, "homepage_url": home, "career_url": career, "reasoning": reason,
                       "citations": [{"url": career, "quote": quote}]} if kind == "report" else None}


class Harness:
    def __init__(self, actions):
        self.actions, self.contexts, self.searches = list(actions), [], []
        self.pages = Pages()
        self.client = FakeModelClient(output={"companies": [{"company": NAME, "homepage_url": HOME, "career_url": CAREER}]})
        self.identity = FakeModelClient(outputs=[identity_action("read", url=CAREER), identity_action("report")])
        self.fail_search = False

    def factory(self, session, task, *, settings, on_event, checkpoint):
        harness = self

        class Agent(CampaignCompanyAgent):
            async def decide(self, context):
                harness.contexts.append(context)
                choice = harness.actions.pop(0)
                if isinstance(choice, Exception):
                    raise choice
                if choice.action == "verify" and not choice.company_id:
                    choice.company_id = context["candidates"][0]["company_id"]
                return choice

        class Provider:
            async def discover(self):
                if harness.fail_search:
                    harness.fail_search = False
                    raise TimeoutError()
                return [lead(HOME), lead(PROOF)]

        def provider(query):
            self.searches.append(query)
            return Provider()

        class Client:
            async def generate(self, request):
                return await (harness.identity if request.schema_name == "campus_company_identity" else harness.client).generate(request)

        agent = Agent(session, user_id=task.user_id, run_id=task.run_id,
                     query="2027届校园招聘公司，不限岗位和城市", reader=self.pages,
                     provider_factory=provider, client_factory=Client,
                     on_event=on_event, checkpoint=checkpoint)
        agent.settings = settings
        return agent


async def step(session, harness):
    return await run_discovery_step(sessionmaker(bind=session.bind), settings=SETTINGS,
        agent_factory=harness.factory, now=datetime.now(UTC) + timedelta(seconds=5))


@pytest.mark.asyncio
async def test_agent_drives_search_read_extract_verify_and_company_card_queue(db_session):
    enqueue_discovery(db_session, "owner", 2027)
    harness = Harness([action("search", query="2027 校招 新材料 公司官网"), action("read", url=HOME),
                       action("extract"), action("verify"), action("finish")])
    for _ in range(5):
        await step(db_session, harness)
    db_session.expire_all()
    task = db_session.scalar(select(CampaignDiscoveryTask))
    assert task.status == "completed"
    assert len(task.state["queries"]) == 1
    assert harness.searches[0] == "2027 校招 新材料 公司官网"
    row = db_session.scalar(select(DiscoveredCompany))
    assert row.status == "verified"
    assert db_session.scalar(select(CampaignWatch)).company_id == row.id
    assert [h["action"] for h in task.state["planner"]["history"]] == ["search", "read", "extract", "verify", "finish"]


@pytest.mark.asyncio
async def test_truncated_id_gets_exact_options_then_agent_repairs_without_losing_tool_budget(db_session):
    task = enqueue_discovery(db_session, "owner", 2027)
    harness = Harness([action("search", query="2027 新公司"), action("read", url=HOME), action("extract")])
    for _ in range(3):
        await step(db_session, harness)
    db_session.refresh(task)
    company_id = task.state["verify_ids"][0]
    harness.actions.extend([action("verify", company_id=company_id[:-1]), action("verify"), action("finish")])
    await step(db_session, harness)
    db_session.refresh(task)
    planner = task.state["planner"]
    rejected = planner["history"][-1]["result"]
    assert rejected["executed"] is False
    assert rejected["verification_options"] == [{"company_id": company_id, "company": NAME}]
    assert planner["steps"] == 3 and planner["invalid_streak"] == 1
    assert db_session.get(DiscoveredCompany, company_id).attempts == 0
    for _ in range(2):
        await step(db_session, harness)
    db_session.refresh(task)
    assert task.status == "completed"
    assert task.state["planner"]["steps"] == 5
    assert task.state["planner"]["invalid_streak"] == 0
    assert harness.contexts[-2]["verification_options"] == rejected["verification_options"]


@pytest.mark.asyncio
async def test_repeated_invalid_actions_pause_early_and_retry_preserves_evidence(db_session):
    task = enqueue_discovery(db_session, "owner", 2027)
    harness = Harness([action("search", query="2027 公司"), action("read", url=HOME),
                       *(action("read", url=HOME) for _ in range(3))])
    for _ in range(5):
        await step(db_session, harness)
    db_session.refresh(task)
    assert task.status == "blocked" and task.stage == "action_error"
    assert task.state["planner"]["status"] == "stalled"
    assert task.state["planner"]["steps"] == 2
    assert task.next_run_at is None
    evidence = deepcopy(task.state["planner"]["evidence"])
    resumed = enqueue_discovery(db_session, "owner", 2027)
    assert resumed.state["planner"]["invalid_actions"] == 0
    assert resumed.state["planner"]["evidence"] == evidence


@pytest.mark.asyncio
async def test_company_decision_schema_contains_only_current_exact_ids(db_session):
    task = enqueue_discovery(db_session, "owner", 2027)
    harness = Harness([])
    agent = harness.factory(db_session, task, settings=SETTINGS, on_event=lambda *_: None, checkpoint=lambda *_: None)
    client = FakeModelClient(output=action("verify", company_id="company_exact").model_dump())
    agent.client = client
    await CampaignCompanyAgent.decide(agent, {"verification_options":[{"company_id":"company_exact","company":NAME}]})
    assert client.requests[0].json_schema["properties"]["company_id"]["enum"] == ["", "company_exact"]


@pytest.mark.asyncio
async def test_resuming_many_verified_companies_keeps_new_discovery_pages_for_extraction(db_session):
    task = enqueue_discovery(db_session, "owner", 2027)
    harness = Harness([action("search", query="2027 新公司"), action("read", url=HOME), action("extract")])
    for _ in range(2):
        await step(db_session, harness)
    db_session.refresh(task)
    fresh_evidence = deepcopy(task.state["planner"]["evidence"])
    for index in range(14):
        url = f"https://known{index}.example/"
        evidence = deepcopy(fresh_evidence)
        evidence["read_cache"][0].update(url=url, title=f"旧公司{index}", text="旧公司招聘", links=[])
        db_session.add(DiscoveredCompany(user_id="owner", company=f"旧公司{index}", status="verified",
            homepage_url=url, career_url=url, discovered_query="校招", discovery_run_id=task.run_id,
            evidence=evidence))
    db_session.commit()
    await step(db_session, harness)
    context = json.loads(harness.client.requests[-1].messages[-1].content)
    assert HOME in {page["url"] for page in context["pages"]}
    assert HOME in {page["url"] for page in harness.contexts[-1]["pages"]}
    db_session.refresh(task)
    assert HOME in {page["url"] for page in task.state["planner"]["evidence"]["read_cache"]}
    assert task.state["planner"]["history"][-1]["result"]["companies"] == [NAME]


@pytest.mark.asyncio
async def test_page_evicted_from_checkpoint_can_be_read_again(db_session):
    task = enqueue_discovery(db_session, "owner", 2027)
    harness = Harness([action("search", query="2027 新公司"), action("read", url=HOME), action("read", url=HOME)])
    for _ in range(2):
        await step(db_session, harness)
    db_session.refresh(task)
    state = deepcopy(task.state)
    state["planner"]["evidence"]["read_cache"] = []
    task.state = state
    db_session.commit()
    await step(db_session, harness)
    db_session.refresh(task)
    assert task.state["planner"]["history"][-1]["result"]["code"] == "page_read"
    assert harness.pages.calls.count(HOME) == 2


@pytest.mark.asyncio
async def test_failed_tool_cannot_loop_on_unchanged_evidence(db_session):
    task = enqueue_discovery(db_session, "owner", 2027)
    harness = Harness([action("search", query="2027 公司"), action("read", url=HOME),
                       action("extract"), action("extract"), action("extract"),
                       action("read", url=PROOF), action("extract")])
    original = harness.factory
    calls = []

    def factory(*args, **kwargs):
        agent = original(*args, **kwargs)
        async def fail(*args, **kwargs):
            calls.append(True)
            raise TimeoutError()
        agent.extract = fail
        return agent

    harness.factory = factory
    for _ in range(5):
        await step(db_session, harness)
    db_session.refresh(task)
    assert len(calls) == 2
    assert task.state["planner"]["history"][-1]["result"]["code"] == "failed_action_repeated"
    for _ in range(2):
        await step(db_session, harness)
    assert len(calls) == 3  # New evidence permits a new attempt.


@pytest.mark.asyncio
async def test_failed_search_is_feedback_for_an_agent_selected_new_query(db_session):
    enqueue_discovery(db_session, "owner", 2027)
    harness = Harness([action("search", query="2027 秋招 公司"), action("search", query="2027 企业校园招聘 官网")])
    harness.fail_search = True
    await step(db_session, harness)
    await step(db_session, harness)
    assert harness.contexts[-1]["history"][-1]["result"]["code"] == "tool_failed"
    assert harness.searches == ["2027 秋招 公司", "2027 企业校园招聘 官网"]
    db_session.expire_all()
    assert [q["stage"] for q in db_session.scalar(select(CampaignDiscoveryTask)).state["queries"]] == ["failed", "done"]


@pytest.mark.asyncio
async def test_invented_url_and_unattempted_candidate_finish_are_rejected(db_session):
    enqueue_discovery(db_session, "owner", 2027)
    harness = Harness([action("read", url="https://invented.test/"), action("finish"),
                       action("search", query="2027 校招 公司"), action("read", url=HOME),
                       action("extract"), action("finish")])
    for _ in range(6):
        await step(db_session, harness)
    db_session.expire_all()
    task = db_session.scalar(select(CampaignDiscoveryTask))
    codes = [h["result"]["code"] for h in task.state["planner"]["history"]]
    assert codes[0:2] == ["observed_url_required", "discovery_required"]
    assert codes[-1] == "verification_required"
    assert db_session.scalar(select(CampaignWatch)) is None


@pytest.mark.asyncio
async def test_interrupted_search_can_be_resumed_without_losing_lease_guards(db_session):
    enqueue_discovery(db_session, "owner", 2027)
    harness = Harness([action("search", query="2027 校招 公司")])
    original = harness.factory
    started = asyncio.Event()

    def blocking(*args, **kwargs):
        agent = original(*args, **kwargs)
        async def search(query):
            started.set()
            await asyncio.Event().wait()
        agent.search = search
        return agent

    harness.factory = blocking
    running = asyncio.create_task(step(db_session, harness))
    await started.wait()
    assert not await step(db_session, harness)
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    harness.factory = original
    harness.actions.append(action("search", query="2027 校招 公司"))
    await step(db_session, harness)
    db_session.expire_all()
    queries = db_session.scalar(select(CampaignDiscoveryTask)).state["queries"]
    assert [q["stage"] for q in queries] == ["failed", "done"]


def test_default_campus_runtime_uses_the_discovery_agent(db_session):
    task = SimpleNamespace(user_id="owner", run_id="trial", year=2027)
    agent = _runtime(db_session, task, settings=SETTINGS, on_event=lambda *_: None, checkpoint=lambda *_: None)
    assert isinstance(agent, CampaignCompanyAgent)
    assert hasattr(agent.evidence_reader.browser, "navigate_evidence")
    assert agent.evidence_reader.collect_actions


@pytest.mark.asyncio
async def test_successful_decision_breaks_the_consecutive_failure_streak(db_session):
    enqueue_discovery(db_session, "owner", 2027)
    harness = Harness([ValueError(), action("search", query="2027 公司官网"), ValueError(), action("read", url=HOME)])
    for _ in range(4):
        await step(db_session, harness)
    db_session.expire_all()
    planner = db_session.scalar(select(CampaignDiscoveryTask)).state["planner"]
    assert planner["status"] == "active" and planner["decision_failures"] == 0
    assert planner["history"][-1]["result"]["code"] == "page_read"


@pytest.mark.asyncio
async def test_blocked_retry_renews_budgets_but_preserves_evidence_and_candidates(db_session):
    task = enqueue_discovery(db_session, "owner", 2027)
    harness = Harness([action("search", query="2027 公司官网"), action("read", url=HOME), action("extract")])
    for _ in range(3):
        await step(db_session, harness)
    db_session.refresh(task)
    state = deepcopy(task.state)
    state["planner"].update(status="budget_exhausted", steps=32, reads=16, search_count=6)
    row_id = state["verify_ids"][0]
    state["planner"]["verification_attempts"] = {row_id: 2}
    task.state, task.status = state, "blocked"
    db_session.commit()
    resumed = enqueue_discovery(db_session, "owner", 2027)
    assert resumed.state["planner"]["evidence"] == state["planner"]["evidence"]
    assert resumed.state["verify_ids"] == [row_id]
    harness.actions.extend([action("search", query="2027 更多校园招聘"), action("verify")])
    await step(db_session, harness)
    await step(db_session, harness)
    assert harness.contexts[-2]["budget"]["remaining_searches"] == 6
    assert harness.contexts[-2]["budget"]["remaining_reads"] == 16
    db_session.expire_all()
    assert db_session.get(DiscoveredCompany, row_id).status == "verified"


@pytest.mark.asyncio
async def test_previous_cycle_attempts_do_not_block_verification_with_new_evidence(db_session):
    task = enqueue_discovery(db_session, "owner", 2027)
    harness = Harness([action("search", query="2027 公司官网"), action("read", url=HOME), action("extract")])
    for _ in range(3):
        await step(db_session, harness)
    db_session.refresh(task)
    state = deepcopy(task.state)
    row_id = state["verify_ids"][0]
    state["verification_attempts"][row_id] = 3
    task.state, task.status = state, "waiting"
    db_session.commit()
    enqueue_discovery(db_session, "owner", 2027)
    harness.actions.extend([action("read", url=PROOF), action("verify")])
    await step(db_session, harness)
    await step(db_session, harness)
    db_session.expire_all()
    assert harness.contexts[-1]["candidates"][0]["attempts_this_cycle"] == 0
    assert db_session.get(DiscoveredCompany, row_id).status == "verified"


@pytest.mark.asyncio
async def test_campus_extraction_can_collect_six_observed_companies_without_auto_verifying(db_session):
    task = enqueue_discovery(db_session, "owner", 2027)
    harness = Harness([])
    suggestions = [{"company": f"样例企业{i}", "homepage_url": f"https://sample{i}.example/",
                    "career_url": f"https://sample{i}.example/campus"} for i in range(6)]
    harness.pages.html[HOME] = '<h1>校园招聘企业汇总</h1>' + ''.join(
        f'<a href="{s["homepage_url"]}">{s["company"]}官网</a>'
        f'<a href="{s["career_url"]}">{s["company"]}校园招聘</a>' for s in suggestions)
    harness.client = FakeModelClient(output={"companies": suggestions})
    agent = harness.factory(db_session, task, settings=SETTINGS, on_event=lambda *_: None, checkpoint=lambda *_: None)
    rows = await agent.extract([lead(HOME)])
    assert len(rows) == 6 and all(r.status == "pending" for r in rows)
    assert db_session.scalar(select(CampaignWatch)) is None
    request = harness.client.requests[0]
    assert request.json_schema["properties"]["companies"]["maxItems"] == 6
    assert "最多选6家" in request.messages[0].content


@pytest.mark.asyncio
async def test_next_discovery_cycles_remember_prior_search_directions(db_session):
    task = enqueue_discovery(db_session, "owner", 2027)
    harness = Harness([action("search", query="2027 医药 校招 官网"),
                       action("search", query="2027 制造业 校招 官网"), action("finish")])
    for _ in range(2):
        await step(db_session, harness)
        db_session.refresh(task)
        task.status = "completed"
        db_session.commit()
        enqueue_discovery(db_session, "owner", 2027)
    await step(db_session, harness)
    history = harness.contexts[-1]["previous_searches"]
    assert [h["query"] for h in history] == ["2027 医药 校招 官网", "2027 制造业 校招 官网"]
    assert all(h["result_count"] == 2 for h in history)
    assert harness.contexts[-1]["searches"] == []
    assert harness.contexts[-1]["pages"] == []
    assert harness.contexts[-1]["budget"]["remaining_searches"] == 6


@pytest.mark.asyncio
async def test_identity_agent_accepts_official_portal_without_independent_domain_or_literal_gate(db_session):
    task = enqueue_discovery(db_session, "owner", 2027)
    harness = Harness([])
    portal = "https://hiring.example/#/campus?company=nova"
    harness.pages.html[portal] = '<title>新星科技校园招聘</title><p>欢迎应届毕业生</p>'
    harness.identity = FakeModelClient(outputs=[identity_action("render", url=portal),
        identity_action("read", url=portal), identity_action("report", career=portal,
        quote="新星科技\n校园招聘", reason="官网主体及租户信息一致；已读招聘页面确认入口归属")])
    row = DiscoveredCompany(user_id="owner", company=NAME, homepage_url=HOME, career_url=portal,
                            discovered_query="秋招", discovery_run_id=task.run_id)
    db_session.add(row)
    db_session.commit()
    agent = harness.factory(db_session, task, settings=SETTINGS, on_event=lambda *_: None, checkpoint=lambda *_: None)
    await agent.verify(row)
    assert row.status == "verified" and row.career_url == portal
    assert PROOF not in harness.pages.calls and not harness.searches
    assert row.evidence["identity_report"]["citations"][0]["quote"] == "新星科技\n校园招聘"
    assert row.evidence["identity_trace"][0]["result"]["executed"] is False
    assert db_session.scalar(select(CampaignWatch)) is None  # identity is not job presence


@pytest.mark.asyncio
async def test_identity_unknown_keeps_candidate_and_preserves_reason(db_session):
    task = enqueue_discovery(db_session, "owner", 2027)
    harness = Harness([])
    harness.identity = FakeModelClient(outputs=[identity_action("read", url=HOME),
        identity_action("report", status="unknown", reason="集团页面未注明目标子公司招聘入口")])
    row = DiscoveredCompany(user_id="owner", company=NAME, homepage_url=HOME, career_url=CAREER,
                            discovered_query="秋招", discovery_run_id=task.run_id)
    db_session.add(row)
    db_session.commit()
    agent = harness.factory(db_session, task, settings=SETTINGS, on_event=lambda *_: None, checkpoint=lambda *_: None)
    await agent.verify(row)
    assert row.status == "pending" and row.verified_at is None
    assert row.reason == "集团页面未注明目标子公司招聘入口"
    assert row.evidence["read_cache"] and db_session.scalar(select(CampaignWatch)) is None


@pytest.mark.asyncio
async def test_identity_report_cannot_write_after_losing_task_lease(db_session):
    from src.services.campaign_discovery import LostLease
    task = enqueue_discovery(db_session, "owner", 2027)
    harness = Harness([])
    row = DiscoveredCompany(user_id="owner", company=NAME, homepage_url=HOME, career_url=CAREER,
                            discovered_query="秋招", discovery_run_id=task.run_id)
    db_session.add(row)
    db_session.commit()
    calls = 0
    def checkpoint(_):
        nonlocal calls
        calls += 1
        if calls == 5:  # after model report, immediately before persisting its verdict
            raise LostLease()
    agent = harness.factory(db_session, task, settings=SETTINGS, on_event=lambda *_: None, checkpoint=checkpoint)
    with pytest.raises(LostLease):
        await agent.verify(row)
    db_session.rollback()
    db_session.refresh(row)
    assert row.status == "pending" and row.verified_at is None
