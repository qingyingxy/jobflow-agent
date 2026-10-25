import copy
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from src.config import Settings
from src.infrastructure.llm_client import FakeModelClient
from src.services.campaign_agent import CampaignAgentReader
from src.services.campaign_agent_evidence import AgentEvidence, page_references
from src.services.campaign_service import campaign_payload, company_card, save_campaign
from src.services.company_evidence_reader import CompanyEvidenceReader, html_page
from src.services.company_registry import CompanySource
from src.services.url_reader import HTMLLink

SOURCE = CompanySource("demo", "示例科技", "A", "https://example.test/campus", "official_campus_page")
SETTINGS = Settings(_env_file=None)
TEXT = "示例科技2027届校园招聘 算法工程师 产品经理"


def action(kind, url="", *, query="", status="found", text=TEXT, jobs=None, reasoning="已读公司校招列表中存在实际岗位"):
    return {"action": kind, "url": url, "query": query, "reason": "根据页面证据选择下一步",
        "control_index": None,
        "report": {"status": status, "kind": "listing", "title": "示例科技2027届校园招聘",
            "recruitment_url": url, "campus_quote": "校园招聘", "year_quote": "2027届",
            "cohort_status": "confirmed", "reasoning": reasoning,
            "job_titles": (["算法工程师", "产品经理"] if status == "found" else []) if jobs is None else jobs,
            "citations": [{"url": url, "quote": text}] if url else []} if kind == "report" else None}


def page(url, text=TEXT, *, links=(), method="http", **extra):
    return {"url": url, "title": "示例科技2027届校园招聘", "text": text, "method": method,
        "links": [HTMLLink(url=u, text=t) for u, t in links], "application_actions": [], **extra}


class Pages:
    def __init__(self, pages):
        self.data, self.calls, self.attempts, self.pages = pages, [], [], {}

    async def read_agent_page(self, url, *, render=False, control=None):
        self.calls.append((url, render) if control is None else (url, render, control))
        value = self.data.get((url, render), self.data.get(url))
        result = copy.deepcopy(value.pop(0) if isinstance(value, list) else value)
        self.attempts.append({"url": url, "error_code": None if result else "browser_timeout" if render else "read_failed"})
        if result:
            self.pages[url] = result
        return result


def reader(outputs, pages, provider=None, **options):
    client = FakeModelClient(outputs=outputs)
    agent = CampaignAgentReader(None, None, client, SETTINGS, provider, **options)
    agent.pages = Pages(pages)
    return agent, client


@pytest.mark.asyncio
@pytest.mark.parametrize("portal", ["https://campus.example.org/", "https://app.mokahr.com/apply/demo/123"])
async def test_agent_follows_literal_address_and_reports_without_second_model(portal):
    body = "2027届校园招聘公告，网申地址：" + portal.removeprefix("https://")
    agent, client = reader([action("read", SOURCE.career_url), action("read", portal), action("report", portal)],
        {SOURCE.career_url: page(SOURCE.career_url, body), portal: page(portal)})
    result = await agent.check(SOURCE, 2027, {})
    assert result["cache"]["job_check"]["status"] == "found"
    assert len(client.requests) == result["stats"]["model_calls"] == 3
    assert all(r.schema_name == "campus_navigation_action" for r in client.requests)
    state = json.loads(client.requests[1].messages[-1].content)
    assert any(r["url"] == portal and r["kind"] == "text_address" for r in state["observed_urls"])


@pytest.mark.asyncio
async def test_agent_can_render_despite_dom_readiness_hint():
    shell = html_page('<title>校园招聘</title><a href="https://vendor.test/">招聘系统</a>',
                      url=SOURCE.career_url, digest="shell", collect_actions=True)
    shell.update(needs_render=False, needs_navigation=False)
    agent, _ = reader([action("read", SOURCE.career_url), action("render", SOURCE.career_url),
                       action("report", SOURCE.career_url)],
        {(SOURCE.career_url, False): shell,
         (SOURCE.career_url, True): page(SOURCE.career_url, method="browser", listing_state="unloaded")})
    result = await agent.check(SOURCE, 2027, {})
    assert agent.pages.calls == [(SOURCE.career_url, False), (SOURCE.career_url, True)]
    assert result["cache"]["job_check"]["status"] == "found"


@pytest.mark.asyncio
async def test_agent_judges_search_discovered_portal_without_code_trust_gate():
    target, queries = "https://campus.example.org/", []
    class Provider:
        async def discover(self):
            return [SimpleNamespace(source_url=target, title_hint="示例科技校招", search_snippet=TEXT)]
        async def aclose(self):
            queries.append("closed")
    def factory(query, *_args, **_kwargs):
        queries.append(query)
        return Provider()
    agent, client = reader([action("search", query="示例科技 2027 校园招聘 官网"), action("read", target),
        action("report", target)], {target: page(target)}, factory)
    result = await agent.check(SOURCE, 2027, {})
    assert queries == ["示例科技 2027 校园招聘 官网", "closed"]
    assert result["cache"]["job_check"]["status"] == "found"
    state = json.loads(client.requests[-1].messages[-1].content)
    assert state["read_pages"][0]["read_status"] == "success"
    assert "trusted_source" not in state["read_pages"][0]


@pytest.mark.asyncio
async def test_failed_click_does_not_invalidate_a_directly_read_group_job():
    portal, job = "https://group.test/#/homePage", "https://group.test/#/postDetail/2246"
    controls = [{"kind": "navigation", "selector": "button", "label": "示例科技人才 查看职位"}]
    navigate = {**action("navigate", portal), "control_index": 0}
    proposal = action("report", job, jobs=["AI全栈研发工程师（示例科技）"])
    proposal["report"].update(kind="job", recruitment_url=portal,
        citations=[{"url": SOURCE.career_url, "quote": "官方招聘入口"},
                   {"url": job, "quote": "AI全栈研发工程师（示例科技） 应届生 2027届"}])
    agent, client = reader([action("read", SOURCE.career_url), action("render", portal), navigate,
        action("read", job), proposal],
        {SOURCE.career_url: page(SOURCE.career_url, "官方招聘入口", links=[(portal, "校园招聘")]),
         (portal, True): [page(portal, "集团校招首页", method="browser", navigation_controls=controls), None],
         job: page(job, "AI全栈研发工程师（示例科技） 应届生 2027届")})
    result = await agent.check(SOURCE, 2027, {"urls": [job]})
    assert result["cache"]["job_check"]["status"] == "found" and result["error"] is None
    state = json.loads(client.requests[-1].messages[-1].content)
    assert state["history"][2]["result"]["code"] == "browser_timeout"
    assert len(state["read_pages"]) == 3
    assert result["cache"]["agent_report"] == proposal["report"]
    assert len(result["cache"]["pages"]) == 3
    json.dumps(result["cache"])


@pytest.mark.asyncio
async def test_agent_can_retry_a_transient_navigation_failure():
    url = SOURCE.career_url
    controls = [{"kind": "entries", "selector": "button", "label": "查看职位"}]
    navigate = {**action("navigate", url), "control_index": 0}
    agent, _ = reader([action("render", url), navigate, navigate, action("report", url)],
        {(url, True): [page(url, "项目介绍", navigation_controls=controls), None, page(url)]})
    result = await agent.check(SOURCE, 2027, {})
    assert result["cache"]["job_check"]["status"] == "found"
    assert agent.pages.calls[1] == agent.pages.calls[2] == (url, True, controls[0])


@pytest.mark.asyncio
async def test_cross_page_citations_and_semantic_judgment_are_not_filtered_by_literal_rules():
    job = "https://external.test/position"
    proposal = action("report", job, jobs=["人工智能研发工程师"])
    proposal["report"].update(title="人工智能校招岗位", kind="job", campus_quote="面向应届毕业生",
        year_quote="2026年9月至2027年8月毕业", recruitment_url=SOURCE.career_url,
        citations=[{"url": SOURCE.career_url, "quote": "招聘对象：2026年9月至2027年8月毕业"},
                   {"url": job, "quote": "人工智能\n研发工程师"}])
    agent, client = reader([action("read", SOURCE.career_url), action("read", job), proposal],
        {SOURCE.career_url: page(SOURCE.career_url, "招聘对象：2026年9月至2027年8月毕业", links=[(job, "职位")]),
         job: page(job, "人工智能\n研发工程师 面向应届毕业生")})
    result = await agent.check(SOURCE, 2027, {})
    assert result["cache"]["agent_report"] == proposal["report"]
    assert result["cache"]["job_check"]["job_titles"] == ["人工智能研发工程师"]
    assert result["found"][0][0]["cohort_status"] == "confirmed"
    state = json.loads(client.requests[-1].messages[-1].content)
    assert "招聘对象" in state["read_pages"][0]["text"]


@pytest.mark.asyncio
@pytest.mark.parametrize("body,reason", [
    ("其他子公司2027届校园招聘 算法工程师", "岗位属于其他子公司，目标公司仍待确认"),
    ("社会招聘 高级开发 需五年经验", "页面仅有社招岗位，尚未发现校招列表"),
    ("校园招聘 加载中", "尚未取得实际岗位内容"),
])
async def test_unknown_judgment_and_reason_are_preserved(body, reason):
    proposal = action("report", SOURCE.career_url, status="unknown", text=body, reasoning=reason)
    agent, _ = reader([action("read", SOURCE.career_url), proposal],
        {SOURCE.career_url: page(SOURCE.career_url, body)})
    result = await agent.check(SOURCE, 2027, {})
    assert result["cache"]["job_check"]["status"] == "unknown"
    assert result["error"] == reason and not result["found"]
    assert result["cache"]["agent_report"] == proposal["report"]


@pytest.mark.asyncio
async def test_empty_report_is_final_without_url_heuristic_or_second_finish():
    url = SOURCE.career_url + "?keyword=previous"
    text = "已清空全部筛选。示例科技2027届校园招聘 暂无职位"
    agent, _ = reader([action("read", url), action("report", url, status="empty", text=text)],
        {url: page(url, text)})
    result = await agent.check(SOURCE, 2027, {"urls": [url]})
    assert result["cache"]["job_check"]["status"] == "empty"
    assert result["stats"]["stop_reason"] == "agent_reported"


@pytest.mark.asyncio
async def test_recheck_reads_again_and_gets_a_new_agent_judgment():
    outputs = [action("read", SOURCE.career_url), action("report", SOURCE.career_url)]
    agent, _ = reader(outputs, {SOURCE.career_url: page(SOURCE.career_url)})
    first = await agent.check(SOURCE, 2027, {})
    agent, client = reader(outputs, {SOURCE.career_url: page(SOURCE.career_url)})
    second = await agent.check(SOURCE, 2027, first["cache"])
    assert second["cache"]["job_check"]["status"] == "found"
    assert len(client.requests) == 2 and second["stats"]["parse_cache_hits"] == 0
    agent, _ = reader([action("read", SOURCE.career_url), action("finish")], {})
    third = await agent.check(SOURCE, 2027, second["cache"])
    assert third["cache"]["job_check"]["status"] == "unknown" and not third["found"]
    assert not third["cache"]["pages"]


@pytest.mark.asyncio
async def test_old_success_without_new_report_never_auto_promotes_company():
    agent, _ = reader([action("read", SOURCE.career_url), action("finish")], {SOURCE.career_url: page(SOURCE.career_url)}, max_steps=2)
    result = await agent.check(SOURCE, 2027, {"agent_report": action("report", SOURCE.career_url)["report"],
        "job_check": {"status": "found"}, "agent_observations": {SOURCE.career_url: {"hash": "old"}}})
    assert result["cache"]["job_check"]["status"] == "unknown"


@pytest.mark.asyncio
async def test_agent_report_survives_persistence_and_drives_company_card(db_session):
    url = SOURCE.career_url
    agent, _ = reader([action("read", url), action("report", url)], {url: page(url)})
    result = await agent.check(SOURCE, 2027, {})
    now = datetime.now(UTC)
    row = save_campaign(db_session, "owner", SOURCE, *result["found"][0], now)
    db_session.commit()
    db_session.expire_all()
    watch = SimpleNamespace(cache=result["cache"], checked_at=now, succeeded_at=now,
        followed=False, status="ready", error=None, next_check_at=None)
    card = company_card(SOURCE, watch, [campaign_payload(row, now)], 2027)
    assert card["recruitment_status"] == "open"
    assert card["judgment_reason"] == result["cache"]["agent_report"]["reasoning"]
    assert card["citations"] == result["cache"]["agent_report"]["citations"]
    assert row.facts["agent_report"] == result["cache"]["agent_report"]


@pytest.mark.asyncio
async def test_unobserved_tool_url_and_invalid_control_return_execution_feedback():
    navigate = {**action("navigate", SOURCE.career_url), "control_index": 5}
    agent, _ = reader([action("read", "https://invented.test/"), action("read", SOURCE.career_url), navigate, action("finish")],
        {SOURCE.career_url: page(SOURCE.career_url)})
    result = await agent.check(SOURCE, 2027, {})
    codes = [step["result"]["code"] for step in result["cache"]["agent_trace"]]
    assert "url_not_observed" in codes and "observed_navigation_control_required" in codes
    assert agent.pages.calls == [(SOURCE.career_url, False)]


@pytest.mark.asyncio
async def test_repeated_actions_are_bounded_by_step_budget():
    agent, _ = reader([action("read", SOURCE.career_url)] * 3, {}, max_steps=3)
    result = await agent.check(SOURCE, 2027, {})
    assert len(agent.pages.calls) == 2
    assert result["cache"]["agent_trace"][-1]["result"]["code"] == "final_report_required"
    assert result["stats"]["stop_reason"] == "step_budget"
    assert result["cache"]["job_check"]["status"] == "unknown"


@pytest.mark.asyncio
async def test_last_read_leaves_a_final_decision_within_original_time_budget(monkeypatch):
    import src.services.campaign_agent as module
    now = [0.0]
    monkeypatch.setattr(module, "monotonic", lambda: now[0])
    agent, client = reader([action("read", SOURCE.career_url), action("report", SOURCE.career_url)],
                           {SOURCE.career_url: page(SOURCE.career_url)}, time_budget=90)
    original = agent.pages.read_agent_page
    async def slow_read(*args, **kwargs):
        result = await original(*args, **kwargs)
        now[0] = 61.0
        return result
    agent.pages.read_agent_page = slow_read
    result = await agent.check(SOURCE, 2027, {})
    state = json.loads(client.requests[-1].messages[-1].content)
    assert state["finalize_only"] and state["read_pages"][0]["text"] == TEXT
    assert client.requests[-1].json_schema["properties"]["action"]["enum"] == ["report", "finish"]
    assert result["cache"]["job_check"]["status"] == "found"
    assert len(agent.pages.calls) == 1


@pytest.mark.asyncio
async def test_one_transient_decision_timeout_can_recover():
    outputs = [action("read", SOURCE.career_url), action("report", SOURCE.career_url)]
    agent, _ = reader(outputs, {SOURCE.career_url: page(SOURCE.career_url)})
    class FlakyClient(FakeModelClient):
        calls = 0
        async def generate(self, request):
            self.calls += 1
            if self.calls == 1:
                raise TimeoutError()
            return await super().generate(request)
    agent.client = FlakyClient(outputs=outputs)
    result = await agent.check(SOURCE, 2027, {})
    assert result["cache"]["job_check"]["status"] == "found" and result["error"] is None
    assert result["cache"]["agent_trace"][0]["action"] == "decision_retry"


@pytest.mark.asyncio
async def test_navigation_targets_current_page_and_agent_selected_control():
    controls = [{"kind": "entries", "selector": "button:first-child", "label": "计划一 查看职位"},
                {"kind": "entries", "selector": "button:last-child", "label": "计划二 查看职位"}]
    navigate = {**action("navigate"), "control_index": 1}
    agent, _ = reader([action("render", SOURCE.career_url), navigate, action("finish")],
        {SOURCE.career_url: page(SOURCE.career_url, "校招计划", method="browser", navigation_controls=controls)})
    result = await agent.check(SOURCE, 2027, {})
    assert agent.pages.calls[1] == (SOURCE.career_url, True, controls[1])
    assert result["cache"]["agent_trace"][1]["url"] == SOURCE.career_url


@pytest.mark.asyncio
async def test_transport_selection_does_not_depend_on_http_shell_classification():
    class HTTP:
        async def fetch(self, url):
            raise AssertionError("Agent requested browser, not HTTP")
    class Browser:
        async def read_evidence(self, url):
            return SimpleNamespace(raw_html="<h1>" + TEXT + "</h1>", final_url=url)
    pages = CompanyEvidenceReader(HTTP(), browser=Browser(), on_event=lambda *_: None, collect_actions=True)
    pages.browser_remaining = 1
    document = await pages.read_agent_page(SOURCE.career_url, render=True)
    assert document["method"] == "browser" and "算法工程师" in document["text"]


def test_evidence_records_redirected_employer_for_agent_to_judge():
    requested, other = "https://app.mokahr.com/apply/demo/123", "https://app.mokahr.com/apply/other/456"
    evidence = AgentEvidence(SOURCE)
    evidence.accept(page(SOURCE.career_url, links=[(requested, "公司招聘")]), SOURCE.career_url)
    evidence.accept(page(other), requested)
    assert evidence.references[requested]["origin_url"] == SOURCE.career_url
    assert evidence.references[other]["origin_url"] == requested


def test_text_addresses_preserve_routes_and_ignore_email():
    refs = page_references(page(SOURCE.career_url,
        "网申网址：campus.example.org/#/jobs?project=7。邮件：hr@example.org"))
    assert [item["url"] for item in refs] == ["https://campus.example.org/#/jobs?project=7"]


@pytest.mark.parametrize("prefix", ["网申地址为", "网申地址：", "请访问", "("])
@pytest.mark.parametrize("scheme", ["https://", ""])
def test_chinese_adjacent_address_keeps_complete_hostname(prefix, scheme):
    refs = page_references(page(SOURCE.career_url,
        prefix + scheme + "zhaopin.example.org/index#/jobs。邮箱hr@jobs.example.org"))
    assert [r["url"] for r in refs] == ["https://zhaopin.example.org/index#/jobs"]


def test_production_factory_uses_agent_controller(monkeypatch):
    import src.infrastructure.llm_client as llm
    from src.services.campaign_reader import create_campaign_reader
    monkeypatch.setattr(llm, "create_structured_model_client", lambda *_: FakeModelClient())
    settings = SETTINGS.model_copy(update={"structured_model_provider": "openai"})
    assert isinstance(create_campaign_reader(settings, [SOURCE]), CampaignAgentReader)


@pytest.mark.asyncio
async def test_search_candidate_survives_budget_and_multiple_rounds_without_research():
    target = "https://campus.example.org/#/jobs?project=7"
    class Provider:
        async def discover(self):
            return [SimpleNamespace(source_url=target, title_hint="示例校招岗位", search_snippet="新发现入口")]
    first, _ = reader([action("search", query="示例校招"), action("search", query="更多")], {}, lambda *_a, **_k: Provider(), max_steps=2)
    result = await first.check(SOURCE, 2027, {})
    assert result["stats"]["stop_reason"] == "step_budget"
    # The following round may stop too; the unread candidate must remain available.
    second, client = reader([action("finish")], {})
    result = await second.check(SOURCE, 2027, result["cache"])
    state = json.loads(client.requests[0].messages[-1].content)
    candidate = next(r for r in state["resume_candidates"] if r["url"] == target)
    assert candidate["snippet"] == "新发现入口" and candidate["last_read_status"] == "unread"
    assert not candidate["read_in_current_run"] and not state["read_pages"]
    third, client = reader([action("read", target), action("report", target)], {target: page(target)})
    result = await third.check(SOURCE, 2027, result["cache"])
    assert result["stats"]["searches"] == 0 and result["cache"]["job_check"]["status"] == "found"
    assert third.pages.calls == [(target, False)]
    state = json.loads(client.requests[-1].messages[-1].content)
    assert target not in [r["url"] for r in state["resume_candidates"]]
    saved = next(r for r in result["cache"]["observed_urls"] if r["url"] == target)
    assert saved["last_read_status"] == "success" and saved["last_read_at"]


@pytest.mark.asyncio
async def test_legacy_cache_recovers_search_candidates_and_page_links_as_hints_only():
    target, outbound = "https://campus.example.org/", "https://jobs.example.org/#/list"
    cache = {"agent_trace": [{"action": "search", "result": {"code": "search_results", "candidates": [
        {"url": target, "title": "校园招聘", "snippet": "历史搜索摘要"}]}}],
        "pages": {"0": {**page(SOURCE.career_url), "links": [{"url": outbound, "text": "岗位列表"}]}},
        "job_check": {"status": "found"}}
    agent, client = reader([action("finish")], {})
    result = await agent.check(SOURCE, 2027, cache)
    state = json.loads(client.requests[0].messages[-1].content)
    candidates = {r["url"]: r for r in state["resume_candidates"]}
    assert candidates[target]["snippet"] == "历史搜索摘要"
    assert candidates[outbound]["origin_url"] == SOURCE.career_url
    assert not state["read_pages"] and result["cache"]["job_check"]["status"] == "unknown"
    assert not result["cache"]["pages"] and not agent.pages.calls


@pytest.mark.asyncio
async def test_current_call_without_attempt_does_not_reuse_old_timeout():
    agent, _ = reader([action("render", SOURCE.career_url), action("finish")], {})
    agent.pages.attempts = [{"url": SOURCE.career_url, "error_code": "browser_timeout"}]
    async def skipped(*_args, **_kwargs):
        return None
    agent.pages.read_agent_page = skipped
    result = await agent.check(SOURCE, 2027, {})
    feedback = result["cache"]["agent_trace"][0]["result"]
    assert feedback["code"] == "read_failed" and feedback["executed"] is None
    assert feedback["read_status"] == "unknown"


@pytest.mark.asyncio
async def test_cooldown_feedback_reaches_agent_with_remaining_limits():
    outputs = [action("render", SOURCE.career_url)] * 3 + [action("finish")]
    agent = CampaignAgentReader(None, None, FakeModelClient(outputs=outputs), SETTINGS, None)
    class Browser:
        async def read_evidence(self, url):
            raise TimeoutError()
    agent.pages.browser = Browser()
    result = await agent.check(SOURCE, 2027, {})
    state = json.loads(agent.client.requests[-1].messages[-1].content)
    feedback = state["history"][-1]["result"]
    assert feedback["code"] == "evidence_host_cooldown" and feedback["executed"] is False
    assert feedback["read_status"] == "not_executed" and feedback["retryable"] is False
    assert state["tool_state"]["browser_remaining"] == 6
    assert state["tool_state"]["host_cooldowns"] == [{"host": "example.test", "method": "browser"}]
    assert result["stats"]["pages_read"] == 0


@pytest.mark.asyncio
async def test_unresolved_navigation_keeps_body_without_claiming_navigation_progress():
    controls = [{"kind": "entries", "selector": "button", "label": "查看岗位"}]
    navigate = {**action("navigate", SOURCE.career_url), "control_index": 0}
    agent, client = reader([action("render", SOURCE.career_url), navigate, action("finish")],
        {SOURCE.career_url: [page(SOURCE.career_url, "介绍", navigation_controls=controls),
                            page(SOURCE.career_url, "仍为介绍", navigation_result="dynamic_navigation_unresolved")]})
    await agent.check(SOURCE, 2027, {})
    state = json.loads(client.requests[-1].messages[-1].content)
    assert state["history"][-1]["result"]["code"] == "navigation_unresolved"
    assert state["current_page"]["text"] == "仍为介绍"
    assert state["current_page"]["read_status"] == "success"


@pytest.mark.asyncio
async def test_reusing_reader_starts_a_fresh_round_and_never_reuses_old_body():
    class HTTP:
        calls = 0
        async def fetch(self, url):
            from src.services.url_reader import FetchedResponse
            self.calls += 1
            return FetchedResponse(url, url, 200, "text/html", f"<h1>第{self.calls}轮</h1>".encode())
    http = HTTP()
    agent = CampaignAgentReader(http, None, FakeModelClient(outputs=[action("read", SOURCE.career_url), action("finish")]*2),
                                SETTINGS, None)
    first = await agent.check(SOURCE, 2027, {})
    second = await agent.check(SOURCE, 2027, first["cache"])
    assert http.calls == 2 and len(second["cache"]["read_attempts"]) == 1
    assert len(second["cache"]["pages"]) == 1
    assert "第2轮" in second["cache"]["pages"]["0"]["text"]
    assert "第1轮" in first["cache"]["pages"]["0"]["text"]


def test_unread_search_is_not_lost_behind_hundreds_of_page_links():
    evidence = AgentEvidence(SOURCE)
    target = "https://campus.example.org/"
    evidence.add(target, "新入口", "search", snippet="待补读")
    evidence.accept(page(SOURCE.career_url, links=[(f"https://example.test/{i}", "链接") for i in range(400)]),
                    SOURCE.career_url)
    saved = evidence.ordered_references()
    assert len(saved) == 350 and target in [r["url"] for r in saved]
    restored = AgentEvidence(SOURCE)
    restored.restore({"observed_urls": json.loads(json.dumps(saved))})
    assert any(r["url"] == target for r in restored.resume_candidates())
