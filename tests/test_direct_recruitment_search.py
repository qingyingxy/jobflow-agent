import asyncio
from dataclasses import replace
from types import SimpleNamespace
from urllib.parse import parse_qs, unquote, urlsplit

import pytest

from src.services.browser_job_reader import (
    BrowserPageSnapshot,
    PlaywrightBrowserJobReader,
)
from src.services.company_registry import CompanySource
from src.services.direct_recruitment_search import (
    DirectRecruitmentSearch,
    listing_filters,
    payload_stub,
    search_keywords,
)
from src.services.discovery_matching import classify_discovery_job
from src.services.job_role_review import resolve_citations
from src.services.search_pipeline import run_search_pipeline

QUERY = "2027届，上海的 AI Agent、RAG、大模型应用开发校招岗位，不考虑北京，不考虑社招"
SOURCE = CompanySource("bytedance", "字节跳动", "A", "https://jobs.bytedance.com/campus/", "official_campus_page")
FILTERS = {"city_list": [{"code": "sh", "name": "上海"}, {"code": "bj", "name": "北京"}],
           "job_subject_list": [{"id": "s1", "name": {"zh_cn": "2027届校园招聘"}},
                                {"id": "s2", "name": {"zh_cn": "2027届Seed大模型人才校招"}},
                                {"id": "s3", "name": {"zh_cn": "2027届实习"}}]}
ITEM = {"id": "123", "title": "Agent开发工程师", "city_list": [{"name": "上海"}],
        "description": "负责基于大模型的Agent工具调用、任务规划及RAG知识库应用研发。",
        "requirement": "1、2027届获得本科及以上学历，计算机、软件工程等相关专业优先；",
        "recruit_type": {"id": "201", "name": "正式"},
        "job_subject": {"name": {"zh_cn": "2027届Seed大模型人才校招"}}}


def test_filters_resolve_live_ids_and_keep_positive_alternatives():
    assert listing_filters(FILTERS, QUERY) == {"location": "sh", "project": "s1,s2"}
    assert search_keywords(QUERY) == ["agent", "rag", "大模型应用开发"]
    assert search_keywords("上海后端校招，不考虑前端") == ["后端"]
    assert listing_filters(FILTERS, "上海或北京校招") == {"location": "sh,bj", "project": ""}
    assert listing_filters(FILTERS, "校招，排除北京") == {"location": "", "project": ""}


@pytest.mark.parametrize("text,status", [
    (ITEM["requirement"], "matched"),
    ("2026届获得本科及以上学历，专业不限", "excluded"),
    ("2027届获得硕士及以上学位，计算机等相关专业优先", "matched"),
    ("2027届海外人才校招", "pending"),
    ("2027届获得本科学历，仅限海外毕业生", "pending"),
    ("2027届获得本科学历，毕业时间2026年9月至2027年8月", "pending"),
    ("2027届获得本科学历，或满足其他条件", "pending"),
])
def test_cohort_degree_sentences_preserve_qualifiers(text, status):
    job = payload_stub(ITEM, company=SOURCE.company, listing_url=SOURCE.career_url+"position")
    job = replace(job, raw_content="岗位职责\n" + ITEM["description"] + "\n任职要求\n" + text)
    result = classify_discovery_job(job, query=QUERY)
    assert next(c["status"] for c in result.checks if c["field"] == "graduation_year") == status


def test_citations_cannot_invent_or_cross_reference_source_passages():
    passages = [ITEM["description"], "负责云平台部署运维和值班。"]
    output = resolve_citations({"status": "matched", "reason": "Agent应用研发", "evidence_ids": [0]}, passages)
    assert output["evidence"] == [passages[0]]
    for ids in [[-1], [2], [True]]:
        with pytest.raises(ValueError):
            resolve_citations({"status": "matched", "reason": "test", "evidence_ids": ids}, passages)


@pytest.mark.parametrize('html', [False, True])
def test_payload_keeps_duty_boundaries_in_plaintext_and_html(html):
    from src.services.job_role_review import duty_text
    intro='我们致力于建设面向Agent场景的资源调度平台。'
    duty='- 参与Kubernetes调度及集群稳定性建设，分析集群资源使用与碎片问题。'
    description=f'<p>{intro}</p><p>{duty}</p><script>开发Agent系统</script>' if html else intro+'\n\n你将参与：\n'+duty
    job=payload_stub({**ITEM,'title':'资源调度研发实习生','description':description},company=SOURCE.company,listing_url=SOURCE.career_url+'position')
    assert '\n'+duty in job.raw_content
    assert intro not in duty_text(job)
    assert '开发Agent系统' not in job.raw_content
    assert classify_discovery_job(job,query='上海Agent实习').filter_status!='matched'


def test_product_intern_keywords_cannot_pass_without_direction_review():
    job=payload_stub({**ITEM,'title':'大模型产品实习生-B端业务','recruit_type':{'id':'202'},
        'description':'1.参与产品的需求分析、方案设计与上线跟进。\n2.跟踪Agent Harness及开发者工具，输出竞品分析与产品建议。'},company=SOURCE.company,listing_url=SOURCE.career_url+'position')
    role=next(c for c in classify_discovery_job(job,query='上海Agent实习').checks if c['field']=='role')
    assert role['status']=='pending'


class ListingBrowser:
    safety_checker = SimpleNamespace(proxy_allowed_hosts=set())

    def __init__(self, *, incomplete=False, mismatched=False, observed=True):
        self.incomplete, self.mismatched, self.observed = incomplete, mismatched, observed

    async def read(self, url):
        from src.services.browser_job_reader import BrowserReadError
        raise BrowserReadError('No public hiring link')

    async def read_search_listing(self, url):
        params = parse_qs(urlsplit(url).query)
        if not params:
            records = [{"url": "https://jobs.bytedance.com/api/v1/config/job/filters/3", "payload": {"code": 0, "data": FILTERS}}]
        else:
            request = {"keyword": params["keywords"][0], "location_code_list": ["sh"], "subject_id_list": ["s1", "s2"], "offset":(int(params['current'][0])-1)*10,"limit":10}
            if self.mismatched:
                request["location_code_list"] = []
            item = {**ITEM, "requirement": ""} if self.incomplete else ITEM
            records = [{"url": "https://jobs.bytedance.com/api/v1/search/job/posts", "request": request, "payload": {"code": 0, "data": {"job_post_list": [item]}}}]
        html = '<a href="/campus/position/123/detail">Agent开发工程师</a>' if self.observed else ""
        return BrowserPageSnapshot(url, url, "校招", html, "岗位列表", recruitment_api=tuple(records))


class PortalQueryBrowser(ListingBrowser):
    """These portals decode URI components, not form-encoded '+' spaces."""

    async def read_search_listing(self, url):
        page = await super().read_search_listing(url)
        if urlsplit(url).query:
            components = dict(part.split("=", 1) for part in urlsplit(url).query.split("&"))
            page.recruitment_api[0]["request"]["keyword"] = unquote(components["keywords"])
        return page


@pytest.mark.asyncio
@pytest.mark.parametrize("keyword", ["machine learning", "c++ developer"])
@pytest.mark.parametrize("company_id,portal_host", [
    ("bytedance", "jobs.bytedance.com"), ("minimax", "minimax.jobs.feishu.cn"),
    ("xiaomi", "xiaomi.jobs.f.mioffice.cn"), ("nio", "nio.jobs.feishu.cn"),
])
async def test_portal_receives_exact_saved_keyword_with_spaces_and_literal_plus(company_id, portal_host, keyword):
    query = f"工作地点：上海；岗位方向：{keyword}；招聘类型：校招；届别：2027届"
    source = SOURCE if company_id == "bytedance" else replace(
        SOURCE, id=company_id, career_url=f"https://{company_id}.example/careers")
    entry = f"https://{portal_host}/campus"

    class Reader:
        async def fetch(self, url):
            return SimpleNamespace(final_url=url, body=f'<a href="{entry}">校园招聘</a>'.encode())

    class Browser(PortalQueryBrowser):
        async def read_search_listing(self, url):
            page = await super().read_search_listing(url)
            for record in page.recruitment_api:
                record["url"] = record["url"].replace("jobs.bytedance.com", portal_host)
            return page

    candidates = []
    direct = DirectRecruitmentSearch(sources=[source], query=query, reader=Reader(),
        browser=Browser(), on_event=lambda *_: None, max_jobs=1)
    await direct.discover(candidates.extend)
    assert len(candidates) == 1
    request = direct.evidence[candidates[0].source_url].api_record["request"]
    assert request["keyword"] == keyword
    assert request["location_code_list"] == ["sh"]
    assert request["subject_id_list"] == ["s1", "s2"]
    assert request["offset"] == 0 and request["limit"] == 10


@pytest.mark.asyncio
@pytest.mark.parametrize("incomplete,mismatched,observed,count", [(False, False, True, 1), (True, False, True, 1), (False, True, True, 1), (False, False, False, 0)])
async def test_only_observed_scoped_results_can_supply_full_official_facts(incomplete, mismatched, observed, count):
    source = DirectRecruitmentSearch(sources=[SOURCE], query=QUERY, reader=None,
        browser=ListingBrowser(incomplete=incomplete, mismatched=mismatched, observed=observed), on_event=lambda *_: None)
    candidates = []
    await source.discover(candidates.extend)
    assert len(candidates) == count
    if candidates:
        evidence = source.evidence[candidates[0].source_url]
        assert evidence.full_body == (not incomplete and not mismatched)
        assert evidence.stub.company == SOURCE.company
        if mismatched:
            assert evidence.stub.raw_content == "" and not evidence.api_record
            assert evidence.listing_html  # DOM discovery grants no API facts.
        else:
            assert evidence.api_record["request"]["location_code_list"] == ["sh"]
        assert candidates[0].verification_stub is None  # Provider hints alone grant no trust.


@pytest.mark.asyncio
async def test_minimax_requires_a_current_official_tenant_link():
    class Reader:
        async def fetch(self, url):
            return SimpleNamespace(final_url=url, body=b'<a href="https://attacker.example/379481/">campus</a>')
    class Browser(ListingBrowser):
        async def read_search_listing(self, url):
            return BrowserPageSnapshot(url, url, "官网", '<a href="https://attacker.example/379481/">campus</a>', "campus")
    events, candidates = [], []
    source = DirectRecruitmentSearch(sources=[replace(SOURCE, id="minimax", career_url="https://minimax.cn/careers")], query=QUERY, reader=Reader(),
        browser=Browser(), on_event=lambda k,d: events.append(d))
    await source.discover(candidates.extend)
    assert not candidates and events[0]["error_code"] == "source_payload_invalid"


def test_internship_subjects_come_from_current_config_and_exclude_formal():
    filters = {**FILTERS, 'job_subject_list': [*FILTERS['job_subject_list'],
        {'id':'daily','name':{'zh_cn':'日常实习'}}, {'id':'grouped','name':{'zh_cn':'人才项目'},'subject_group_info':{'name':'实习'}}]}
    assert listing_filters(filters, '上海Agent实习')['project'] == 's3,daily,grouped'
    assert listing_filters(filters, '2027届上海Agent实习')['project'] == 's3'
    source = DirectRecruitmentSearch(sources=[SOURCE], query='上海Agent实习，不考虑社招',reader=None,browser=ListingBrowser(),on_event=lambda *_:None)
    assert source.supported
    source.query = '上海Agent社招'
    assert not source.supported


@pytest.mark.asyncio
@pytest.mark.parametrize('bad', ['origin', 'offset', 'limit'])
async def test_api_origin_and_pagination_must_match_the_requested_page(bad):
    class WrongPage(ListingBrowser):
        async def read_search_listing(self,url):
            page=await super().read_search_listing(url)
            if urlsplit(url).query:
                record=page.recruitment_api[0]
                if bad=='origin':record['url']='https://foreign.jobs.feishu.cn/api/v1/search/job/posts'
                else:record['request'][bad]=-1
            return page
    candidates=[]
    source=DirectRecruitmentSearch(sources=[SOURCE],query=QUERY,reader=None,browser=WrongPage(),on_event=lambda *_:None)
    await source.discover(candidates.extend)
    assert len(candidates) == 1  # The independent DOM link is still usable.
    evidence = source.evidence[candidates[0].source_url]
    assert not evidence.full_body and not evidence.api_record
    assert evidence.stub.raw_content == "" and evidence.stub.locations == []
    assert source.states[SOURCE.id]["protocol_checkpoint"]["page_number"] == 1
    assert source.states[SOURCE.id]["status"] != "completed"


@pytest.mark.asyncio
async def test_page_two_adds_new_jobs_and_preserves_original_page_offset():
    class Paged(ListingBrowser):
        async def read_search_listing(self,url):
            page=await super().read_search_listing(url)
            if parse_qs(urlsplit(url).query).get('current')==['2']:
                page.recruitment_api[0]['payload']['data']['job_post_list']=[{**ITEM,'id':'124'}]
                return replace(page,raw_html='<a href="/campus/position/124/detail">Agent工程师</a>')
            return page
    candidates=[]
    source=DirectRecruitmentSearch(sources=[SOURCE],query=QUERY,reader=None,browser=Paged(),on_event=lambda *_:None)
    await source.discover(candidates.extend)
    assert len(candidates)==2
    assert source.evidence[candidates[1].source_url].api_record['request']['offset']==10


@pytest.mark.asyncio
@pytest.mark.parametrize('company_id,host', [('xiaomi','xiaomi.jobs.f.mioffice.cn'),('nio','nio.jobs.feishu.cn')])
async def test_new_sources_require_official_proof_and_keep_its_real_url(company_id,host):
    official='https://official.example/campus/'
    proof=official+'join'
    entry=f'https://{host}/campus/'
    class Reader:
        async def fetch(self,url):
            html=f'<a href="{proof}">招聘</a>' if url==official else f'<a href="{entry}">校园招聘</a>'
            return SimpleNamespace(final_url=url,body=html.encode())
    class Browser(ListingBrowser):
        async def read_search_listing(self,url):
            page=await super().read_search_listing(url)
            for rec in page.recruitment_api:
                rec['url']=rec['url'].replace('jobs.bytedance.com',host)
            return page
    candidates=[]
    source=DirectRecruitmentSearch(sources=[replace(SOURCE,id=company_id,career_url=official)],query=QUERY,reader=Reader(),browser=Browser(),on_event=lambda *_:None)
    await source.discover(candidates.extend)
    assert len(candidates)==1
    e=source.evidence[candidates[0].source_url]
    assert e.official_proof_url==proof and entry in e.official_html
    assert urlsplit(e.stub.detail_url).hostname==host


@pytest.mark.asyncio
async def test_foreign_official_redirect_cannot_prove_tenant_ownership():
    class Reader:
        async def fetch(self,url):
            return SimpleNamespace(final_url='https://foreign.example',body=b'<a href="https://nio.jobs.feishu.cn/campus/">campus</a>')
    candidates=[]
    source=DirectRecruitmentSearch(sources=[replace(SOURCE,id='nio',career_url='https://campus.nio.com/')],query=QUERY,reader=Reader(),browser=ListingBrowser(),on_event=lambda *_:None)
    await source.discover(candidates.extend)
    assert not candidates


@pytest.mark.asyncio
async def test_bootstrap_failure_keeps_emitted_jobs_and_runs_web_fallback():
    from tests.test_search_execution import candidate
    observed = []
    async def bootstrap(enqueue):
        enqueue([candidate(1)])
        raise ValueError("later source failed")
    async def search(number, seen):
        observed.append("web")
        return [candidate(2)]
    async def verify(item):
        observed.append(item.source_url)
        return item.source_url, True
    await run_search_pipeline(bootstrap=bootstrap, search=search, verify=verify, report=lambda *_: None,
                              canonicalize=lambda u:u, max_rounds=1, verification_seconds=1)
    assert "web" in observed and candidate(1).source_url in observed and candidate(2).source_url in observed


@pytest.mark.asyncio
async def test_browser_reuse_launches_once_and_closes_on_cancellation(monkeypatch):
    from playwright import async_api
    calls = []
    class Browser:
        async def close(self): calls.append("close")
    class Runtime:
        chromium = None
        def __init__(self): self.chromium = self
        async def start(self): calls.append("start"); return self
        async def launch(self, **kwargs): calls.append("launch"); await asyncio.sleep(0); return Browser()
        async def stop(self): calls.append("stop")
    monkeypatch.setattr(async_api, "async_playwright", Runtime)
    reader = PlaywrightBrowserJobReader()
    async def use():
        async with reader.browser_session() as browser:
            return browser
    with pytest.raises(asyncio.CancelledError):
        async with reader.reuse():
            first, second = await asyncio.gather(use(), use())
            assert first is second
            raise asyncio.CancelledError
    assert calls == ["start", "launch", "close", "stop"]


@pytest.mark.asyncio
async def test_execution_saves_original_payload_and_filters_without_refetch(db_session, monkeypatch):
    from datetime import UTC, datetime

    from sqlalchemy import select
    from sqlalchemy.orm import sessionmaker

    from src.config import Settings
    from src.domain.discovery import DiscoveryRun, LeadVerification
    from src.services import multiround_search as execution
    from src.services import web_search_service
    from src.services.discovery_results import current_run_matches
    from src.services.job_lead_service import JobLeadService

    async def no_refetch(*args, **kwargs):
        pytest.fail("Complete original API payload should not be fetched again")
    class Provider:
        source_id = "test"
        async def discover(self):
            pytest.fail("Sufficient direct results should stop before web fallback")
    monkeypatch.setattr(execution, "get_settings", lambda: Settings(_env_file=None,
        web_search_direct_sources_enabled=True, web_search_target_jobs=1,
        web_search_max_rounds=1, web_search_budget_seconds=5, web_search_verification_budget_seconds=3))
    monkeypatch.setattr(execution, "SessionLocal", sessionmaker(bind=db_session.bind))
    monkeypatch.setattr(execution, "enabled_company_sources", lambda *args, **kwargs:[SOURCE])
    monkeypatch.setattr(execution, "enabled_company_source_hosts", lambda **kwargs:{"jobs.bytedance.com"})
    monkeypatch.setattr(execution, "PlaywrightBrowserJobReader", lambda **kwargs: ListingBrowser())
    monkeypatch.setattr(web_search_service, "create_web_search_provider", lambda *args:Provider())
    monkeypatch.setattr(JobLeadService, "verify_url", no_refetch)
    run = DiscoveryRun(id="direct-test", user_id="u", source="test", source_url=SOURCE.career_url,
                       search_query=QUERY, started_at=datetime.now(UTC))
    db_session.add(run)
    db_session.commit()
    await execution.execute_multiround_search(run_id=run.id, user_id="u", query=QUERY, company_ids=[])
    db_session.expire_all()
    records=list(db_session.scalars(select(LeadVerification).where(LeadVerification.user_id=="u")))
    snapshots=[r for r in records if r.result=="SNAPSHOT"]
    assert any('"job_post_list"' in (r.field_evidence.get("raw_text") or "") for r in snapshots)
    matches=current_run_matches(db_session,[run])[run.id]
    assert len(matches)==1 and matches[0]["filter_status"]=="matched"
    assert run.analysis_target_count==0
    assert run.usage_metrics["read_attempts"] == run.usage_metrics["read_successes"] == 1
    assert run.usage_metrics["new_effective_jobs"] == 1
    assert run.usage_metrics["first_result_ms"] is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("custom_domain", [False, True])
async def test_verified_new_feishu_source_reuses_listing_reader(custom_domain):
    host = "recruiting.example.com" if custom_domain else "newco.jobs.feishu.cn"
    source = CompanySource("newco", "新公司", "C", f"https://{host}/", "discovered_official",
        resource_hosts=("lf-package-cn.feishucdn.com",) if custom_domain else (),
        official_homepage_url="https://newco.example", hiring_evidence_url="https://newco.example/careers")
    class Browser(ListingBrowser):
        async def read_search_listing(self, url):
            if urlsplit(url).path == "/":
                if not custom_domain:
                    assert host in self.safety_checker.proxy_allowed_hosts
                return BrowserPageSnapshot(url, url, "官网", '<a href="/982864/">校招职位</a>', "校招职位")
            page = await super().read_search_listing(url)
            for record in page.recruitment_api:
                record["url"] = record["url"].replace("jobs.bytedance.com", host)
            return replace(page, raw_html=page.raw_html.replace("/campus/", "/982864/"))
    candidates = []
    direct = DirectRecruitmentSearch(sources=[source], query=QUERY, reader=None, browser=Browser(),
                                    on_event=lambda *_: None, max_jobs=1)
    await direct.discover(candidates.extend)
    assert len(candidates) == 1
    assert candidates[0].source_url == f"https://{host}/982864/position/123/detail"


def test_unverified_shared_root_is_not_a_direct_source():
    from src.services.company_search_progress import supports_direct_listing
    source = replace(SOURCE, id="new", career_url="https://jobs.feishu.cn/")
    assert not supports_direct_listing(source)
    assert not supports_direct_listing(replace(source, career_url="https://other.jobs.feishu.cn/"))


@pytest.mark.parametrize("requirement,expected", [
    ("2027届本科、硕士或博士毕业生，计算机等相关专业", "matched"),
    ("熟悉Python", "pending"),
    ("2026届本科毕业生", "pending"),
    ("2027届海外毕业生", "pending"),
    ("2027届本科毕业生，毕业时间2026年9月至2027年8月", "pending"),
])
def test_season_label_does_not_override_explicit_eligibility(requirement, expected):
    job = payload_stub({**ITEM, "recruit_type": None, "requirement": requirement,
                        "job_subject": {"name": {"zh_cn": "2027校园招聘"}}},
                       company="新公司", listing_url="https://recruiting.example.com/982864/")
    assert job.job_type == "campus"
    check = next(c for c in classify_discovery_job(job, query=QUERY).checks if c["field"] == "graduation_year")
    assert check["status"] == expected
