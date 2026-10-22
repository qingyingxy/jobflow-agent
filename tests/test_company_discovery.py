import asyncio
import json
from datetime import UTC, datetime, timedelta
from io import BytesIO
from zipfile import ZipFile

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from src.config import Settings
from src.domain.company_source import DiscoveredCompany
from src.domain.discovery import DiscoveryRun
from src.domain.search_goal import SearchGoal
from src.infrastructure.llm_client import FakeModelClient
from src.main import app
from src.services.company_coverage import CompanyCoverage
from src.services.company_discovery import (
    CompanyDiscoveryAgent,
    list_discovered_companies,
)
from src.services.company_registry import (
    enabled_company_source_hosts,
    enabled_company_sources,
)
from src.services.company_search_progress import (
    CompanyProgressStore,
    progress_summaries,
)
from src.services.lead_providers import LeadCandidate, LeadProviderKind
from src.services.official_hiring_resolver import OfficialHiringResolver
from src.services.url_reader import FetchedResponse, URLFetchError
from src.services.user_data_lifecycle import UserDataLifecycleService

HOME = "https://nova.example/"
CAREER = "https://app.mokahr.com/campus-recruitment/nova/100"
PROOF = "https://career.university.edu.cn/nova"
QUERY = "北京 上海 Agent RAG 2027 校招"
NAME = "新星科技"


def lead(url):
    return LeadCandidate(provider=LeadProviderKind.EXTERNAL_AGENT, source_url=url,
                         discovered_at=datetime.now(UTC), title_hint=NAME + "招聘")


class Pages:
    def __init__(self):
        self.html = {
            HOME: f'<title>{NAME}官网</title><h1>让 AI 改变工作</h1><a href="{CAREER}">校园招聘</a>',
            PROOF: f'<title>{NAME}校招宣讲会</title><p>{NAME}公司介绍</p><a href="{HOME}">官网</a>',
            CAREER: f'<title>{NAME}校园招聘</title><h1>招聘职位</h1>',
        }
        self.redirects = {}
        self.calls = []

    async def fetch(self, url):
        self.calls.append(url)
        if url not in self.html:
            raise URLFetchError("unavailable")
        return FetchedResponse(url, self.redirects.get(url, url), 200, "text/html", self.html[url].encode())


def agent(session, *, pages=None, suggestions=None, results=None):
    pages = pages or Pages()
    searches, events = [], []

    class Provider:
        async def discover(self):
            return [lead(url) for url in (results if results is not None else [HOME, PROOF])]

    def factory(query):
        searches.append(query)
        return Provider()

    client = FakeModelClient(output={"companies": suggestions if suggestions is not None else [
        {"company": NAME, "homepage_url": HOME, "career_url": CAREER}]})
    instance = CompanyDiscoveryAgent(session, user_id="owner", run_id="run", query=QUERY,
        reader=pages, provider_factory=factory, client_factory=lambda: client,
        on_event=lambda kind, data: events.append((kind, data)))
    return instance, pages, searches, events


def goal(session):
    item = SearchGoal(id="goal", user_id="owner", name="AI 校招", input_text=QUERY,
                      query=QUERY, conditions={}, version=1, condition_sources={})
    session.add(item)
    session.commit()
    return item


@pytest.mark.asyncio
async def test_discover_verify_persist_and_queue_with_tenant_scoped_trust(db_session):
    worker, pages, searches, events = agent(db_session)
    await worker.run()
    row = db_session.scalar(select(DiscoveredCompany))
    assert row.status == "verified"
    assert row.evidence["hiring_link"]["linked_url"] == CAREER
    assert row.evidence["corroboration"]["url"] == PROOF
    assert len(searches) <= 2
    assert any(kind == "company_source_verified" for kind, _ in events)
    saved_goal = goal(db_session)
    with Session(db_session.bind) as reloaded:
        sources = enabled_company_sources(session=reloaded, user_id="owner")
        new = next(s for s in sources if s.id == row.id)
        assert new.career_url == CAREER
        assert "app.mokahr.com" not in enabled_company_source_hosts(session=reloaded, user_id="owner")
        coverage = CompanyCoverage(sources=sources, store=CompanyProgressStore(reloaded,
            user_id="owner", goal_id=saved_goal.id, version=1), query=QUERY, batch_size=1)
        assert coverage.sources == [new]
        task = coverage.next_task(type("Direct", (), {"states": {}})())
        assert "site:app.mokahr.com/campus-recruitment/nova/" in task.query
        assert any(p["source_id"] == row.id for p in progress_summaries(saved_goal, reloaded))
        resolver = OfficialHiringResolver(sources=[new], reader=pages, browser=None)
        evidence = await resolver.resolve(lead(CAREER + "/jobs/123"), record_snapshot=lambda *_: None)
        assert evidence.company == NAME
        assert await resolver.resolve(lead("https://app.mokahr.com/campus-recruitment/other/100"), record_snapshot=lambda *_: None) is None
        assert all(s.id != row.id for s in enabled_company_sources(session=reloaded, user_id="stranger"))


@pytest.mark.asyncio
@pytest.mark.parametrize("problem", ["no_independent_link", "spoofed_title", "no_hiring_link", "wrong_tenant", "unsafe_redirect", "no_career_body"])
async def test_insufficient_or_conflicting_evidence_never_becomes_trusted(db_session, problem):
    worker, pages, _, _ = agent(db_session)
    if problem == "no_independent_link":
        pages.html[PROOF] = f'<title>{NAME}</title><p>https://nova.example/ 招聘官网已认证</p>'
    elif problem == "spoofed_title":
        pages.html[HOME] = pages.html[HOME].replace(NAME, "另一家公司")
    elif problem == "no_hiring_link":
        pages.html[HOME] = f'<title>{NAME}</title><p>招聘 {CAREER}</p>'
        pages.html[PROOF] += f'<a href="{CAREER}">招聘</a>'
    elif problem == "wrong_tenant":
        pages.redirects[CAREER] = "https://app.mokahr.com/campus-recruitment/other/100"
    elif problem == "unsafe_redirect":
        pages.redirects[HOME] = "https://attacker.example/"
    else:
        pages.html[CAREER] = "<title>Security challenge</title>Enable JavaScript"
    await worker.run()
    row = db_session.scalar(select(DiscoveredCompany))
    assert row is not None and row.status == "pending"
    assert all(s.id != row.id for s in enabled_company_sources(session=db_session, user_id="owner"))


@pytest.mark.asyncio
@pytest.mark.parametrize("home,career", [("https://invented.example/", CAREER), (HOME, "https://nova.example/invented"), ("javascript:alert(1)", CAREER), ("https://app.mokahr.com/", CAREER)])
async def test_model_cannot_invent_urls_or_promote_shared_platform(db_session, home, career):
    worker, _, _, _ = agent(db_session, suggestions=[{"company": NAME, "homepage_url": home, "career_url": career}])
    await worker.run()
    assert list_discovered_companies(db_session, "owner") == []


@pytest.mark.asyncio
async def test_deduplication_cooldown_and_pending_retry_survive_restart(db_session):
    worker, pages, _, _ = agent(db_session, results=[HOME])
    await worker.run()
    row = db_session.scalar(select(DiscoveredCompany))
    assert row.status == "pending" and row.attempts == 1
    await agent(db_session, pages=pages, results=[HOME])[0].run()
    assert row.attempts == 1
    row.last_checked_at = datetime.now(UTC) - timedelta(days=1)
    db_session.commit()
    with Session(db_session.bind) as reloaded:
        retry, _, _, _ = agent(reloaded, suggestions=[])
        await retry.run()
    db_session.expire_all()
    assert row.status == "verified" and row.attempts == 2
    assert len(list_discovered_companies(db_session, "owner")) == 1


@pytest.mark.asyncio
async def test_cancellation_preserves_candidate_without_trusting_it(db_session):
    worker, _, _, _ = agent(db_session)
    row = DiscoveredCompany(user_id="owner", company=NAME, homepage_url=HOME, career_url=CAREER,
                            discovered_query=QUERY, discovery_run_id="run")
    db_session.add(row)
    db_session.commit()

    async def slow(_, **kwargs):
        await asyncio.Event().wait()

    worker.read = slow
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(worker.verify(row), timeout=0.01)
    db_session.expire_all()
    assert row.status == "pending" and row.attempts == 1
    assert row.last_checked_at is not None


@pytest.mark.asyncio
async def test_api_and_account_lifecycle_keep_discovered_sources_private(db_session, tmp_path):
    await agent(db_session)[0].run()
    row = db_session.scalar(select(DiscoveredCompany))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        own = await client.get("/api/discovery/sources", headers={"X-User-Id": "owner"})
        other = await client.get("/api/discovery/sources", headers={"X-User-Id": "other"})
        assert own.status_code == other.status_code == 200
        assert row.id in {s["id"] for s in own.json()}
        assert row.id not in {s["id"] for s in other.json()}
    db_session.add(DiscoveredCompany(user_id="other", company=NAME, homepage_url=HOME, career_url=CAREER,
                                    discovered_query=QUERY, discovery_run_id="other-run"))
    db_session.commit()
    lifecycle = UserDataLifecycleService(db_session, storage_root=tmp_path)
    with ZipFile(BytesIO(lifecycle.export(user_id="owner").content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    assert len(manifest["tables"]["discovered_companies"]) == 1
    assert manifest["tables"]["discovered_companies"][0]["evidence"]["corroboration"]["url"] == PROOF
    lifecycle.delete(user_id="owner")
    assert list_discovered_companies(db_session, "owner") == []
    assert len(list_discovered_companies(db_session, "other")) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("scoped", [False, True])
async def test_saved_goal_search_discovers_then_next_run_searches_new_company(db_session, monkeypatch, scoped):
    from src.services import multiround_search as execution
    from src.services import web_search_service

    settings = Settings(_env_file=None, structured_model_provider="openai_compatible",
        web_search_max_rounds=1, web_search_company_batch_size=1,
        web_search_budget_seconds=5, web_search_role_review_enabled=False,
        web_search_direct_sources_enabled=False)
    calls = []
    client = FakeModelClient(output={"companies": [{"company": NAME, "homepage_url": HOME, "career_url": CAREER}]})

    class Provider:
        source_id, source_url = "test", "https://search.example/"

        def __init__(self, query, companies=None, **kwargs):
            self.companies = companies
            if companies:
                calls.extend(companies)

        async def discover(self):
            return [] if self.companies else [lead(HOME), lead(PROOF)]

    monkeypatch.setattr(execution, "get_settings", lambda: settings)
    monkeypatch.setattr(execution, "SessionLocal", sessionmaker(bind=db_session.bind))
    monkeypatch.setattr(execution, "SafeHTTPReader", lambda **_: Pages())
    monkeypatch.setattr(execution, "PlaywrightBrowserJobReader", lambda **_: object())
    monkeypatch.setattr(execution, "create_structured_model_client", lambda *_: client)
    monkeypatch.setattr(web_search_service, "create_web_search_provider", Provider)
    item = goal(db_session)
    if scoped:
        item.company_ids = ["baidu"]
        db_session.commit()
    for number in range(2):
        run = DiscoveryRun(id=f"run-{number}", user_id="owner", source="test", source_url="https://search.example/",
            search_goal_id=item.id, search_goal_version=1, search_query=QUERY, started_at=datetime.now(UTC))
        db_session.add(run)
        db_session.commit()
        await execution.execute_multiround_search(run_id=run.id, user_id="owner", query=QUERY, company_ids=item.company_ids)
        db_session.expire_all()
        if not scoped:
            from src.services.company_discovery_queue import run_company_discovery_step

            def worker_factory(session, saved_goal, task, *, settings, on_event, checkpoint):
                worker, _, _, _ = agent(session)
                worker.on_event, worker.checkpoint = on_event, checkpoint
                return worker

            for _ in range(8):
                await run_company_discovery_step(sessionmaker(bind=db_session.bind), settings=settings,
                    agent_factory=worker_factory, now=datetime.now(UTC) + timedelta(minutes=1))
            db_session.expire_all()
    discovered = list_discovered_companies(db_session, "owner")
    if scoped:
        assert discovered == [] and client.requests == []
        assert set(calls) == {"baidu"}
    else:
        assert len(discovered) == 1 and discovered[0].status == "verified"
        assert discovered[0].id in calls


@pytest.mark.asyncio
async def test_pending_verification_still_runs_when_model_is_unavailable(db_session):
    row = DiscoveredCompany(user_id="owner", company=NAME, homepage_url=HOME, career_url=CAREER,
                            discovered_query=QUERY, discovery_run_id="old-run")
    db_session.add(row)
    db_session.commit()
    worker, _, _, events = agent(db_session)
    worker.client_factory = lambda: FakeModelClient(error=RuntimeError("offline"))
    await worker.run()
    assert row.status == "verified"
    assert any(kind == "company_discovery_deferred" for kind, _ in events)


@pytest.mark.asyncio
async def test_employer_redirect_saves_actual_verified_entry_and_original_link(db_session):
    entry, destination = HOME + "careers", "https://careers.nova.example/join"
    pages = Pages()
    pages.html[HOME] = f'<title>{NAME}</title><a href="{entry}">校园招聘</a>'
    pages.html[entry] = f'<title>{NAME}招聘</title><p>招聘职位</p>'
    pages.redirects[entry] = destination
    worker, _, _, _ = agent(db_session, pages=pages, suggestions=[{
        "company": NAME, "homepage_url": HOME, "career_url": entry}])
    await worker.run()
    row = db_session.scalar(select(DiscoveredCompany))
    assert row.status == "verified" and row.career_url == destination
    assert row.evidence["hiring_link"]["linked_url"] == entry
    assert "careers.nova.example" in enabled_company_source_hosts(session=db_session, user_id="owner")


@pytest.mark.asyncio
async def test_discovered_career_subdomain_can_resolve_homepage_from_independent_link(db_session):
    entry = "https://careers.nova.example/"
    pages = Pages()
    pages.html[entry] = f'<title>{NAME}招聘</title><p>招聘职位</p>'
    pages.html[HOME] = f'<title>{NAME}</title><a href="{entry}">加入我们</a>'
    worker, _, _, _ = agent(db_session, pages=pages, results=[entry, PROOF], suggestions=[{
        "company": NAME, "homepage_url": entry, "career_url": entry}])
    await worker.run()
    row = db_session.scalar(select(DiscoveredCompany))
    assert row.status == "verified"
    assert row.homepage_url == HOME and row.career_url == entry
    assert row.evidence["hiring_link"]["url"] == HOME


@pytest.mark.asyncio
@pytest.mark.parametrize("label,path", [("Jobs", "jobs"), ("Open Positions", "positions")])
async def test_english_hiring_navigation_resolves_observed_entry(db_session, label, path):
    worker, pages, _, _ = agent(db_session)
    current = HOME + path
    pages.html[HOME] = f'<title>{NAME}</title><a href="{current}">{label}</a>'
    pages.html[current] = f'<title>{NAME} - {label}</title><p>AI Engineer</p>'
    row = DiscoveredCompany(user_id="owner", company=NAME, homepage_url=HOME,
        career_url=CAREER, discovered_query=QUERY, discovery_run_id="run")
    db_session.add(row)
    db_session.commit()
    await worker.verify(row)
    assert row.status == "verified" and row.career_url == current
    assert row.evidence["entry_chain"][0]["linked_url"] == current


@pytest.mark.asyncio
async def test_changed_entry_is_replaced_only_with_actual_official_link(db_session):
    worker, pages, _, _ = agent(db_session)
    current = HOME + "campus/new"
    pages.html[HOME] = f'<title>{NAME}</title><a href="{current}">校园招聘</a>'
    pages.html[current] = f'<title>{NAME}校园招聘</title>'
    # The old discovered URL remains observed in search results but is gone.
    worker.provider_factory = lambda _: type("Provider", (), {"discover": lambda self: asyncio.sleep(0, result=[lead(HOME), lead(PROOF), lead(CAREER)])})()
    pages.html.pop(CAREER)
    await worker.run()
    row = db_session.scalar(select(DiscoveredCompany))
    assert row.status == "verified" and row.career_url == current
    assert row.evidence["discovered_career_url"] == CAREER
    assert row.evidence["entry_chain"][0]["linked_url"] == current


@pytest.mark.asyncio
@pytest.mark.parametrize("related", [True, False])
async def test_product_corporate_and_recruitment_domains_need_identity_evidence(db_session, related):
    worker, pages, _, _ = agent(db_session)
    about = "https://holding.example/about"
    pages.html[HOME] = f'<title>{NAME}</title><a href="{about}">关于我们</a>'
    pages.html[about] = (f'<title>Holding</title><p>{NAME}是我们的产品</p><a href="{HOME}">产品官网</a>'
                         if related else '<title>Other</title> unrelated company') + f'<a href="{CAREER}">校园招聘</a>'
    worker.provider_factory = lambda _: type("Provider", (), {"discover": lambda self: asyncio.sleep(0, result=[lead(HOME), lead(PROOF), lead(CAREER)])})()
    await worker.run()
    row = db_session.scalar(select(DiscoveredCompany))
    assert row.status == ("verified" if related else "pending")
    if related:
        assert [edge["url"] for edge in row.evidence["entry_chain"]] == [HOME, about]
        assert row.evidence["hiring_link"]["url"] == about


@pytest.mark.asyncio
async def test_cyclic_about_links_are_bounded_and_never_trust_plain_text_jobs(db_session):
    worker, pages, _, _ = agent(db_session)
    pages.html[HOME] = f'<title>{NAME}</title><a href="{HOME}about">关于我们</a>'
    pages.html[HOME + "about"] = f'<title>{NAME}</title><a href="{HOME}">公司介绍</a><p>{CAREER}</p>'
    row = DiscoveredCompany(user_id="owner", company=NAME, homepage_url=HOME, career_url=CAREER,
                            discovered_query=QUERY, discovery_run_id="run", evidence={"corroboration_candidates": [PROOF]})
    db_session.add(row)
    db_session.commit()
    await asyncio.wait_for(worker.verify(row), timeout=1)
    assert row.status == "pending" and len(pages.calls) <= 4


@pytest.mark.asyncio
async def test_homepage_protocol_and_www_aliases_do_not_duplicate_company(db_session):
    worker, _, _, _ = agent(db_session, results=[HOME])
    await worker.run()
    alternate = "http://www.nova.example/"
    worker, _, _, _ = agent(db_session, results=[alternate], suggestions=[{
        "company": NAME, "homepage_url": alternate, "career_url": alternate}])
    await worker.run()
    assert len(list_discovered_companies(db_session, "owner")) == 1


@pytest.mark.asyncio
async def test_inaccessible_first_sources_rotate_to_other_evidence(db_session):
    worker, pages, _, _ = agent(db_session, results=[HOME])
    broken = ["https://one.edu.cn/nova", "https://two.gov.cn/nova"]

    class Provider:
        async def discover(self):
            return [lead(u) for u in [*broken, PROOF]]

    row = DiscoveredCompany(user_id="owner", company=NAME, homepage_url=HOME, career_url=CAREER,
                            discovered_query=QUERY, discovery_run_id="run")
    db_session.add(row)
    db_session.commit()
    worker.provider_factory = lambda _: Provider()
    await worker.verify(row)
    assert row.status == "verified" and row.evidence["corroboration"]["url"] == PROOF
    assert all(url in pages.calls for url in broken)
    assert len(row.evidence["read_attempts"]) >= 5


@pytest.mark.asyncio
async def test_each_candidate_gets_a_corroboration_search(db_session):
    second_home, second_proof = "https://second.example/", "https://second.edu.cn/company"
    second_career = second_home + "careers"
    worker, pages, searches, _ = agent(db_session, results=[HOME, second_home], suggestions=[
        {"company": NAME, "homepage_url": HOME, "career_url": CAREER},
        {"company": "Second", "homepage_url": second_home, "career_url": second_career},
    ])
    pages.html[second_home] = f'<title>Second</title><a href="{second_career}">Careers</a>'
    pages.html[second_career] = '<title>Second Careers</title>'
    pages.html[second_proof] = f'<title>Second company</title><a href="{second_home}">Website</a>'

    class Provider:
        def __init__(self, query):
            searches.append(query)
            self.query = query

        async def discover(self):
            urls = [second_proof] if '"Second"' in self.query else [PROOF] if f'"{NAME}"' in self.query else [HOME, second_home]
            return [lead(url) for url in urls]

    worker.provider_factory = Provider
    await worker.run()
    assert len(searches) == 3
    assert {row.status for row in list_discovered_companies(db_session, "owner")} == {"verified"}
    assert len(list_discovered_companies(db_session, "owner")) == 2


@pytest.mark.asyncio
async def test_saved_unread_evidence_resumes_without_another_search(db_session):
    worker, _, searches, _ = agent(db_session)
    row = DiscoveredCompany(user_id="owner", company=NAME, homepage_url=HOME, career_url=CAREER,
        discovered_query=QUERY, discovery_run_id="interrupted", attempts=1,
        evidence={"corroboration_candidates": [PROOF]})
    db_session.add(row)
    db_session.commit()
    await worker.verify(row)
    assert row.status == "verified" and searches == []


@pytest.mark.asyncio
async def test_evidence_search_prompt_excludes_self_asserted_company_pages():
    from src.services.responses_search import ResponsesSearchProvider

    def handle(request):
        prompt = json.loads(request.content)["input"]
        assert "只返回高校" in prompt and "不要返回公司自身官网" in prompt
        return httpx.Response(200, json={"status": "completed", "output": [
            {"type": "web_search_call", "status": "completed", "action": {"sources": [{"url": PROOF, "title": NAME}]}},
            {"type": "message", "content": [{"type": "output_text", "text": f'[{NAME}]({PROOF})'}]},
        ]})

    provider = ResponsesSearchProvider(query=NAME, base_url="https://api.example/v1",
        api_key="fake", model="test", transport=httpx.MockTransport(handle))
    provider.search_purpose, provider.company_evidence_only = "companies", True
    assert [r.source_url for r in await provider.discover()] == [PROOF]


@pytest.mark.asyncio
async def test_retry_reuses_successful_evidence_and_refreshes_missing_link(db_session):
    worker, pages, _, _ = agent(db_session)
    pages.html.pop(CAREER)
    await worker.run()
    row = db_session.scalar(select(DiscoveredCompany))
    assert row.status == "pending" and row.evidence["corroboration"]["url"] == PROOF
    saved_evidence = json.loads(json.dumps(row.evidence))
    for page in saved_evidence["read_attempts"]:
        page["checked_at"] = (datetime.now(UTC) - timedelta(hours=3)).isoformat()
    # Assign a fresh JSON value so SQLAlchemy persists the updated test clock.
    row.evidence = saved_evidence
    row.last_checked_at = datetime.now(UTC) - timedelta(hours=3)
    db_session.commit()
    pages.calls.clear()
    pages.html[CAREER] = f'<title>{NAME}招聘</title>'
    retry, _, searches, _ = agent(db_session, pages=pages)
    await retry.verify(row)
    assert row.status == "verified"
    assert pages.calls == [CAREER] and searches == []


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["bing", "tavily", "responses"])
async def test_discovery_search_keeps_homepages_and_corroboration_pages(kind):
    from src.services.responses_search import ResponsesSearchProvider
    from src.services.web_search_service import (
        BingRSSSearchProvider,
        TavilySearchProvider,
    )

    if kind == "responses":
        def handle(request):
            body = json.loads(request.content)
            assert "新公司" in body["input"] and "高校" in body["input"]
            return httpx.Response(200, json={"status": "completed", "output": [
                {"type": "web_search_call", "status": "completed", "action": {"sources": [{"url": HOME, "title": NAME}]}},
                {"type": "message", "content": [{"type": "output_text", "text": f'[{NAME}]({HOME})'}]},
            ]})
        provider = ResponsesSearchProvider(query=QUERY, base_url="https://api.example/v1", api_key="fake",
            model="test", transport=httpx.MockTransport(handle))
    else:
        class Reader:
            async def fetch(self, url):
                return FetchedResponse(url, url, 200, "application/xml",
                    f'<rss><channel><item><title>{NAME}</title><link>{HOME}</link><description>公司介绍</description></item></channel></rss>'.encode())

            async def post_json(self, *args):
                return object(), {"results": [{"url": HOME, "title": NAME, "content": "公司介绍"}]}

        provider = (BingRSSSearchProvider(query=QUERY, reader=Reader()) if kind == "bing"
                    else TavilySearchProvider(query=QUERY, api_key="fake", reader=Reader()))
    provider.search_purpose = "companies"
    results = await provider.discover()
    assert [r.source_url for r in results] == [HOME]
    assert all(r.verification_stub is None and r.official_entry_url is None for r in results)


@pytest.mark.asyncio
async def test_manual_verification_reuses_only_this_users_verified_company_scope(db_session):
    from src.services.job_lead_service import JobLeadService

    await agent(db_session)[0].run()
    service = JobLeadService(db_session)
    own = service.capture_candidate(user_id="owner", discovery_run_id=None, candidate=lead(CAREER + "/jobs/123"))
    stranger = service.capture_candidate(user_id="other", discovery_run_id=None, candidate=lead(CAREER + "/jobs/123"))
    wrong_tenant = service.capture_candidate(user_id="owner", discovery_run_id=None,
        candidate=lead("https://app.mokahr.com/campus-recruitment/other/100/jobs/123"))
    hosts = set()
    service._prepare_official_transport(own, object(), hosts)
    assert service._official_target(own, own.source_url, hosts)
    assert "app.mokahr.com" not in hosts
    for item in (stranger, wrong_tenant):
        other_hosts = set()
        service._prepare_official_transport(item, object(), other_hosts)
        assert not service._official_target(item, item.source_url, other_hosts)


@pytest.mark.asyncio
async def test_static_adapter_cannot_follow_another_tenant_from_discovered_entry(db_session):
    from src.services.discovery_sources import OfficialCompanyRegistryAdapter

    await agent(db_session)[0].run()
    source = next(s for s in enabled_company_sources(session=db_session, user_id="owner") if s.official_homepage_url)
    pages = Pages()
    pages.html[CAREER] = '<title>招聘</title><a href="https://app.mokahr.com/campus-recruitment/other/100/jobs/123">Agent 工程师</a>'
    adapter = OfficialCompanyRegistryAdapter(sources=[source], reader=pages, query=QUERY)
    assert await adapter.list_jobs() == []
    assert pages.calls == [CAREER]


@pytest.mark.asyncio
async def test_finished_job_search_does_not_wait_for_slow_company_discovery(db_session, monkeypatch):
    from src.services import multiround_search as execution
    from src.services import web_search_service

    cancelled = asyncio.Event()

    async def slow(self):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    class Provider:
        source_id, source_url = "test", "https://search.example/"

        async def discover(self):
            return []

    settings = Settings(_env_file=None, structured_model_provider="openai_compatible",
        web_search_max_rounds=1, web_search_budget_seconds=5, web_search_role_review_enabled=False)
    monkeypatch.setattr(CompanyDiscoveryAgent, "run", slow)
    monkeypatch.setattr(execution, "get_settings", lambda: settings)
    monkeypatch.setattr(execution, "SessionLocal", sessionmaker(bind=db_session.bind))
    monkeypatch.setattr(execution, "PlaywrightBrowserJobReader", lambda **_: object())
    monkeypatch.setattr(web_search_service, "create_web_search_provider", lambda *a, **kw: Provider())
    item = goal(db_session)
    run = DiscoveryRun(id="slow-discovery", user_id="owner", source="test", source_url="https://search.example/",
        search_goal_id=item.id, search_goal_version=1, search_query=QUERY, started_at=datetime.now(UTC))
    db_session.add(run)
    db_session.commit()
    await asyncio.wait_for(execution.execute_multiround_search(run_id=run.id, user_id="owner", query=QUERY, company_ids=None), timeout=3)
    db_session.expire_all()
    from src.domain.company_source import CompanyDiscoveryTask
    task = db_session.get(CompanyDiscoveryTask, item.id)
    assert not cancelled.is_set() and run.status == "SUCCEEDED"
    assert task.status == "queued" and task.state["queries"]
