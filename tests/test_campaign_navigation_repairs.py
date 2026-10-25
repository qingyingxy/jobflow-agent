import pytest

from src.services.campaign_entry import application_actions, entry_campaign
from src.services.campaign_navigation import irrelevant_document, navigation_candidate
from src.services.campaign_reader import CampaignReader
from src.services.campaign_service import effective_status
from src.services.company_evidence_reader import CompanyEvidenceReader, html_page
from src.services.company_registry import CompanySource
from src.services.recruitment_listing import allowed_listing_url, inspect_listing
from src.services.url_reader import HTMLLink

SOURCE = CompanySource("sample", "新星科技", "A", "https://nova.example/campus", "official_campus_page")
JOB_URL = "https://nova.example/job/123"
JD = "算法工程师 2027届校园招聘 岗位职责：负责检索与推理系统的开发、评测和部署。立即投递"
OUTPUT = {"kind": "job", "title": "算法工程师", "scope_quote": JD, "campus_quote": "2027届校园招聘",
          "year_quote": "2027届", "status": "open", "status_quote": "", "job_titles": ["算法工程师"], "apply_label": "立即投递"}


@pytest.mark.parametrize("url,label", [
    ("https://nova.example/news/123", "公司发展新闻"),
    ("https://nova.example/legal/security", "加入我们"),
    ("https://nova.example/social-recruitment/jobs", "招聘职位"),
    ("https://nova.example/notice/2023.pdf", "2023届校园招聘简章"),
    ("https://nova.example/investor_relations/form.docx", "申请表格"),
    ("https://nova.example/research/model", "模型发布"),
    ("https://social.example/p/123/home", ""),
])
def test_navigation_rejects_irrelevant_branches(url, label):
    assert navigation_candidate(url, label, 2027) is None


def test_picture_only_campus_portal_keeps_actual_tenant_and_query():
    target = "https://nova.jobs.feishu.cn/campus/?project=12"
    caps = inspect_listing(f'<a href="{target}"><img src="banner.png"></a>', url=SOURCE.career_url)
    assert [link.url for link in caps.entries] == [target]
    assert navigation_candidate(target, "", 2027) == (1, True)
    assert navigation_candidate("https://nova.jobs.feishu.cn/intern", "", 2027) is None


def test_current_announcement_is_kept_but_explicit_old_document_is_not_parsed():
    assert navigation_candidate("https://nova.example/news/1", "2027届校园招聘启动", 2027) == (4, False)
    assert irrelevant_document({"title": "2023届校园招聘简章", "text": "公司介绍"}, 2027)
    assert not irrelevant_document({"title": "校园招聘", "text": "历史链接：2023届校园招聘简章"}, 2027)


def test_custom_application_controls_require_clickability_and_enabled_ancestors():
    html = ('<p>投递岗位</p><div style="cursor:pointer">投递岗位</div>'
            '<div role="button">加入意向单</div><div aria-disabled="true"><span onclick="apply()">立即申请</span></div>'
            '<div class="cookie-settings"><button>Apply</button></div><button hidden>申请岗位</button>')
    assert application_actions(html) == ["投递岗位", "加入意向单"]
    facts = entry_campaign({**OUTPUT, "apply_label": "加入意向单"}, {"url": JOB_URL}, SOURCE, 2027)
    assert facts["entry"]["status"] == "unknown"
    assert entry_campaign({**OUTPUT, "apply_label": "投递岗位"}, {"url": JOB_URL}, SOURCE, 2027)["entry"]["status"] == "open"


@pytest.mark.parametrize("campus", ["2027届", "Momenta Campus", "Graduate Recruitment"])
def test_job_accepts_explicit_cohort_or_english_campus_evidence(campus):
    assert application_actions('<button>简历投递</button>') == ["简历投递"]
    facts = entry_campaign({**OUTPUT, "campus_quote": campus, "apply_label": "简历投递"},
                           {"url": JOB_URL}, SOURCE, 2027)
    assert facts["entry"]["status"] == "open"


@pytest.mark.parametrize("campus", ["Campus Internship", "Graduate Recruitment - Experienced Hire", "2027届实习"])
def test_explicit_internship_or_experienced_hire_overrides_campus_marker(campus):
    assert entry_campaign({**OUTPUT, "campus_quote": campus}, {"url": JOB_URL}, SOURCE, 2027) is None


def test_verified_cohort_field_can_supply_campus_evidence():
    facts = entry_campaign({**OUTPUT, "campus_quote": "教育背景：2026.9-2027.8 期间获得硕士学位的同学"},
                           {"url": JOB_URL}, SOURCE, 2027)
    assert facts["entry"]["status"] == "open"
    assert facts["entry"]["campus_quote"] == "2027届"
    assert facts["cohort_status"] == "confirmed"
    assert navigation_candidate("https://nova.example/p/123", "算法工程师", 2027) == (0, True)


def test_list_open_status_does_not_claim_a_verified_application_entry():
    from datetime import UTC, datetime, timedelta

    facts = entry_campaign({**OUTPUT, "kind": "listing", "status_quote": "网申进行中", "apply_label": ""},
                           {"url": SOURCE.career_url}, SOURCE, 2027)
    now = datetime.now(UTC)
    assert effective_status(facts, now) == "open"
    assert facts["entry"]["status"] == "unknown"
    assert effective_status(facts, now + timedelta(days=2)) == "unknown"


def test_empty_html_with_navigation_still_requires_rendering():
    html = '<a href="/campus">校园招聘</a><main>职位类别 筛选 搜索 下一页</main>'
    page = html_page(html, url=SOURCE.career_url, digest="abc", collect_actions=True)
    assert page["needs_render"] and page["listing_state"] == "unloaded"


class Pages:
    def __init__(self, data):
        self.data, self.visited = data, []

    async def read(self, url):
        self.visited.append(url)
        return self.data[url]


class Parser:
    def __init__(self, failures=0, output=None):
        self.calls = 0
        self.failures = failures
        self.output = output

    async def parse(self, page, year):
        self.calls += 1
        if self.calls <= self.failures:
            raise TimeoutError()
        return self.output if self.output is not None else []


def page(url, text="校园招聘", links=(), **kwargs):
    return {"url": url, "text": text, "links": [HTMLLink(*link) for link in links], **kwargs}


@pytest.mark.asyncio
async def test_reader_prefers_observed_portal_over_corporate_news_and_wrong_cohorts():
    ats = "https://nova.jobs.feishu.cn/campus/"
    reader = CampaignReader(None, None, Parser(), None)
    reader.pages = Pages({SOURCE.career_url: page(SOURCE.career_url, links=[
        ("https://nova.example/news/1", "企业新闻"), ("https://nova.example/old.pdf", "2023届校招简章"), (ats, "")]),
        ats: page(ats)})
    await reader.check(SOURCE, 2027, {})
    assert reader.pages.visited == [SOURCE.career_url, ats]


@pytest.mark.asyncio
async def test_identical_listings_reuse_parse_without_merging_distinct_urls():
    one, two = SOURCE.career_url + "?project=1", SOURCE.career_url + "?project=2"
    parser = Parser()
    reader = CampaignReader(None, None, parser, None)
    reader.pages = Pages({SOURCE.career_url: page(SOURCE.career_url, text="校招首页", links=[(one, "校园招聘"), (two, "校园招聘")]),
                          one: page(one, text="同一批次校园招聘正文"), two: page(two, text="同一批次校园招聘正文")})
    result = await reader.check(SOURCE, 2027, {})
    assert reader.pages.visited == [SOURCE.career_url, one, two]
    assert parser.calls == 2 and result["stats"]["duplicate_content_skipped"] == 1


@pytest.mark.asyncio
async def test_homepage_navigation_skips_model_despite_announcement_nav_label():
    parser = Parser()
    reader = CampaignReader(None, None, parser, None, entry_parser=Parser(output=OUTPUT))
    reader.pages = Pages({SOURCE.career_url: page(SOURCE.career_url, "首页 校园招聘 校招公告 招聘岗位",
        links=[(JOB_URL, "算法工程师")], title="新星校园招聘", hiring_links=[JOB_URL]), JOB_URL: page(JOB_URL, JD)})
    result = await reader.check(SOURCE, 2027, {})
    assert parser.calls == 0 and result["stats"]["navigation_pages"] == 1
    assert result["found"][0][0]["entry"]["status"] == "open"


@pytest.mark.asyncio
@pytest.mark.parametrize("title,text", [("2027届校园招聘公告", "校园招聘 算法工程师"),
                                        ("新星校园招聘", "2027届校园招聘 网申截止日期2026年11月30日")])
async def test_announcement_or_application_dates_still_parse_before_navigation(title, text):
    parser = Parser()
    reader = CampaignReader(None, None, parser, None, entry_parser=Parser(output=OUTPUT))
    reader.pages = Pages({SOURCE.career_url: page(SOURCE.career_url, text,
        links=[(JOB_URL, "算法工程师")], title=title, hiring_links=[JOB_URL]), JOB_URL: page(JOB_URL, JD)})
    await reader.check(SOURCE, 2027, {})
    assert parser.calls == 1


@pytest.mark.asyncio
async def test_empty_rendered_listing_requires_scoped_campus_confirmation():
    parser = Parser()
    reader = CampaignReader(None, None, parser, None, entry_parser=parser)
    reader.pages = Pages({SOURCE.career_url: page(SOURCE.career_url, text="校园招聘 暂无相关职位", listing_state="empty")})
    result = await reader.check(SOURCE, 2027, {})
    assert parser.calls == 1
    assert not result["found"]
    assert result["cache"]["job_check"]["status"] == "unknown"


@pytest.mark.asyncio
async def test_transient_entry_timeout_recovers_once_inside_budget():
    parser = Parser(failures=1, output=OUTPUT)
    reader = CampaignReader(None, None, Parser(), None, entry_parser=parser)
    reader.pages = Pages({SOURCE.career_url: page(SOURCE.career_url, links=[(JOB_URL, "算法工程师")]), JOB_URL: page(JOB_URL, JD)})
    result = await reader.check(SOURCE, 2027, {})
    assert result["stats"]["parse_retries"] == 1 and result["stats"]["parse_timeouts"] == 1
    assert result["found"][0][0]["entry"]["status"] == "open" and not result["cache"]["pending_checks"]


@pytest.mark.asyncio
async def test_failed_detail_is_persisted_and_reread_first_next_round():
    reader = CampaignReader(None, None, Parser(), None, entry_parser=Parser(failures=99))
    data = {SOURCE.career_url: page(SOURCE.career_url, links=[(JOB_URL, "算法工程师")]), JOB_URL: page(JOB_URL, JD)}
    reader.pages = Pages(data)
    failed = await reader.check(SOURCE, 2027, {})
    assert failed["cache"]["pending_checks"][0]["url"] == JOB_URL
    reader.pages, reader.entry_parser = Pages(data), Parser(output=OUTPUT)
    recovered = await reader.check(SOURCE, 2027, failed["cache"])
    assert reader.pages.visited == [JOB_URL]
    assert recovered["stats"]["stop_reason"] == "campus_jobs_found"


@pytest.mark.asyncio
async def test_pending_job_precedes_announcement_and_old_success_urls():
    reader = CampaignReader(None, None, Parser(), None, entry_parser=Parser(output=OUTPUT))
    reader.pages = Pages({JOB_URL: page(JOB_URL, JD), SOURCE.career_url: page(SOURCE.career_url)})
    cache = {"urls": [SOURCE.career_url, JOB_URL], "pending_checks": [
        {"url": SOURCE.career_url, "entry": False}, {"url": JOB_URL, "entry": True}]}
    await reader.check(SOURCE, 2027, cache)
    assert reader.pages.visited == [JOB_URL]


@pytest.mark.asyncio
async def test_budget_stop_keeps_unvisited_details_for_next_round():
    parser = Parser()
    reader = CampaignReader(None, None, parser, None, time_budget=2)
    reader.pages = Pages({SOURCE.career_url: page(SOURCE.career_url, links=[(JOB_URL, "算法工程师")])})
    result = await reader.check(SOURCE, 2027, {})
    assert result["stats"]["stop_reason"] == "verification_deferred" and parser.calls == 0
    assert {"url": JOB_URL, "entry": True, "reason": "queued", "origin_url": SOURCE.career_url} in result["cache"]["pending_checks"]


@pytest.mark.asyncio
async def test_verified_entry_does_not_turn_unused_jobs_into_failed_work():
    reader = CampaignReader(None, None, Parser(), None, entry_parser=Parser(output=OUTPUT))
    reader.pages = Pages({SOURCE.career_url: page(SOURCE.career_url, links=[
        (JOB_URL, "算法工程师"), (JOB_URL + "other", "软件工程师")]), JOB_URL: page(JOB_URL, JD)})
    result = await reader.check(SOURCE, 2027, {})
    assert result["stats"]["stop_reason"] == "campus_jobs_found"
    assert not result["cache"]["pending_checks"]


@pytest.mark.asyncio
@pytest.mark.parametrize("rendered", [True, False])
async def test_spa_detail_renders_before_http_document_deduplication(rendered):
    target = SOURCE.career_url + "#/job/123"

    class HashPages(CompanyEvidenceReader):
        def __init__(self):
            super().__init__(None, on_event=lambda *_: None)
            self.rendered_urls = []

        async def read(self, url, *, force_browser=False):
            if url == SOURCE.career_url:
                return page(url, links=[(target, "算法工程师")])
            if force_browser:
                self.rendered_urls.append(url)
                if rendered:
                    return page(url, JD, method="browser")
            return page(SOURCE.career_url, "正在加载", method="http")

    reader = CampaignReader(None, None, Parser(), None, entry_parser=Parser(output=OUTPUT))
    reader.pages = HashPages()
    result = await reader.check(SOURCE, 2027, {})
    assert reader.pages.rendered_urls == [target]
    if rendered:
        assert result["found"][0][0]["entry"]["url"] == target
        assert result["stats"]["stop_reason"] == "campus_jobs_found"
    else:
        assert not result["found"]
        assert result["cache"]["pending_checks"] == [{"url": target, "entry": True, "reason": "content_missing", "origin_url": SOURCE.career_url}]


@pytest.mark.asyncio
async def test_failed_detail_is_not_displaced_by_many_unvisited_jobs():
    reader = CampaignReader(None, None, Parser(), None, entry_parser=Parser(failures=99))
    links = [(JOB_URL + str(i), "算法工程师") for i in range(20)]

    class StopAfterFailure(Pages):
        async def read(self, url):
            result = await super().read(url)
            if url != SOURCE.career_url:
                reader.time_budget = 2
            return result

    reader.pages = StopAfterFailure({SOURCE.career_url: page(SOURCE.career_url, links=links),
                                     links[0][0]: page(links[0][0], JD)})
    result = await reader.check(SOURCE, 2027, {})
    pending = result["cache"]["pending_checks"]
    assert len(pending) == 8
    assert pending[0]["url"] == links[0][0] and pending[0]["reason"] == "remaining_budget"


@pytest.mark.asyncio
async def test_external_failure_saves_and_rechecks_its_official_origin_first():
    origin = "https://nova.example/campus/portal"
    ats = "https://nova.jobs.feishu.cn/campus/"
    target = ats + "position/123/detail"
    reader = CampaignReader(None, None, Parser(), None, entry_parser=Parser(failures=99))
    data = {SOURCE.career_url: page(SOURCE.career_url, links=[(origin, "校园招聘")], hiring_links=[origin]),
            origin: page(origin, links=[(ats, "校园招聘")], hiring_links=[ats]),
            ats: page(ats, links=[(target, "算法工程师")], hiring_links=[target]), target: page(target, JD)}
    reader.pages = Pages(data)
    failed = await reader.check(SOURCE, 2027, {})
    assert failed["cache"]["pending_checks"][0]["origin_url"] == origin
    # The source page still has to expose the same tenant; the cache itself is not a trust grant.
    reader.pages, reader.entry_parser = Pages(data), Parser(output=OUTPUT)
    recovered = await reader.check(SOURCE, 2027, failed["cache"])
    assert reader.pages.visited[:2] == [origin, target]
    assert reader.pages.visited == [origin, target]
    assert recovered["cache"]["job_check"]["status"] == "found"
    assert recovered["found"][0][0]["entry"]["status"] == "open"


@pytest.mark.asyncio
async def test_forged_external_resume_does_not_grant_trust():
    reader = CampaignReader(None, None, Parser(), None)
    reader.pages = Pages({SOURCE.career_url: page(SOURCE.career_url)})
    await reader.check(SOURCE, 2027, {"pending_checks": [{"url": "https://evil.example/job/1", "entry": True}]})
    assert reader.pages.visited == [SOURCE.career_url]


@pytest.mark.asyncio
async def test_recorded_official_redirect_accepts_only_its_ats_tenant():
    ats = "https://app.mokahr.com/campus-recruitment/nova/123"
    job = ats + "/job/123"
    other = "https://app.mokahr.com/campus-recruitment/other/job/123"
    reader = CampaignReader(None, None, Parser(), None, entry_parser=Parser(output=OUTPUT))
    reader.pages = Pages({SOURCE.career_url: page(ats, links=[(job, "算法工程师"), (other, "算法工程师")],
        redirect_chain=[{"url": SOURCE.career_url, "target": ats, "status": 302}]), job: page(job, JD)})
    result = await reader.check(SOURCE, 2027, {})
    assert reader.pages.visited == [SOURCE.career_url, job]
    assert result["found"][0][0]["entry"]["status"] == "open"


@pytest.mark.asyncio
async def test_observed_external_portal_can_follow_its_own_hiring_links():
    portal, final = "https://careers.other.example/campus/home", "https://careers.other.example/campus"
    job = final + "/job/123"
    reader = CampaignReader(None, None, Parser(), None, entry_parser=Parser(output=OUTPUT))
    reader.pages = Pages({SOURCE.career_url: page(SOURCE.career_url, links=[(portal, "校园招聘")]),
        portal: page(final, links=[(job, "算法工程师"), ("https://evil.example/job/123", "算法工程师")]), job: page(job, JD)})
    await reader.check(SOURCE, 2027, {})
    assert reader.pages.visited == [SOURCE.career_url, portal, job]


@pytest.mark.asyncio
async def test_small_remaining_budget_defers_instead_of_starting_doomed_parse():
    parser = Parser()
    reader = CampaignReader(None, None, parser, None, time_budget=2)
    reader.pages = Pages({SOURCE.career_url: page(SOURCE.career_url)})
    result = await reader.check(SOURCE, 2027, {})
    assert parser.calls == 0
    assert result["cache"]["pending_checks"][0]["reason"] == "remaining_budget"


@pytest.mark.asyncio
async def test_cached_campus_job_is_sufficient_on_repeat_checks_without_announcement_scan():
    notice = "https://nova.example/notice/supplement"
    supplement = {"title": "新星科技2027届秋招补录", "scope_quote": "新星科技2027届秋招补录正式启动",
        "year": 2027, "year_quote": "2027届", "batch": "supplement", "batch_quote": "秋招补录",
        "status": "announced", "status_quote": "正式启动", "published": None, "starts": None,
        "deadline": None, "directions": []}

    class Notices(Parser):
        async def parse(self, page, year):
            return [supplement] if page["url"] == notice else []

    reader = CampaignReader(None, None, Notices(), None, entry_parser=Parser(output=OUTPUT))
    data = {JOB_URL: page(JOB_URL, JD), SOURCE.career_url: page(SOURCE.career_url,
        links=[(notice, "2027届秋招补录公告"), (JOB_URL + "other", "软件工程师")]),
        notice: page(notice, supplement["scope_quote"])}
    cache = {"urls": [JOB_URL], "pages": {JOB_URL: {"entry_observation": OUTPUT}}}
    for _ in range(2):
        reader.pages = Pages(data)
        result = await reader.check(SOURCE, 2027, cache)
        assert reader.pages.visited == [JOB_URL]
        assert JOB_URL + "other" not in reader.pages.visited
        assert not any(fact["batch"] == "supplement" for fact, _ in result["found"])
        assert result["cache"]["job_check"]["status"] == "found"
        assert result["stats"]["stop_reason"] == "campus_jobs_found"
        cache = result["cache"]


@pytest.mark.asyncio
async def test_budget_after_campus_job_still_completes_company_check():
    class BudgetParser(Parser):
        async def parse(self, page, year):
            reader.time_budget = 0
            return OUTPUT

    reader = CampaignReader(None, None, Parser(), None, entry_parser=BudgetParser())
    reader.pages = Pages({JOB_URL: page(JOB_URL, JD)})
    result = await reader.check(SOURCE, 2027,
        {"urls": [JOB_URL], "pages": {JOB_URL: {"entry_observation": OUTPUT}}})
    assert result["found"][0][0]["entry"]["status"] == "open"
    assert not result["stats"]["announcement_check_complete"]
    assert result["cache"]["pending_checks"] == []
    assert result["stats"]["stop_reason"] == "campus_jobs_found" and result["error"] is None


@pytest.mark.asyncio
async def test_campus_job_does_not_require_an_unavailable_announcement_homepage():
    reader = CampaignReader(None, None, Parser(), None, entry_parser=Parser(output=OUTPUT))
    reader.pages = Pages({JOB_URL: page(JOB_URL, JD), SOURCE.career_url: None})
    result = await reader.check(SOURCE, 2027,
        {"urls": [JOB_URL], "pages": {JOB_URL: {"entry_observation": OUTPUT}}})
    assert result["stats"]["stop_reason"] == "campus_jobs_found"
    assert result["error"] is None and reader.pages.visited == [JOB_URL]
    assert result["cache"]["pending_checks"] == []


@pytest.mark.asyncio
async def test_known_job_does_not_resume_the_announcement_backlog():
    notice = SOURCE.career_url + '/announcements'
    reader = CampaignReader(None, None, Parser(), None, entry_parser=Parser(output=OUTPUT))
    reader.pages = Pages({SOURCE.career_url: page(SOURCE.career_url),
                          JOB_URL: page(JOB_URL, JD), notice: page(notice, '校招公告')})
    result = await reader.check(SOURCE, 2027, {'urls': [JOB_URL],
        'pages': {JOB_URL: {'entry_observation': OUTPUT}},
        'pending_checks': [{'url': notice, 'entry': False, 'reason': 'queued', 'origin_url': SOURCE.career_url}]})
    assert reader.pages.visited == [SOURCE.career_url, JOB_URL]
    assert result['cache']['pending_checks'] == []


@pytest.mark.asyncio
@pytest.mark.parametrize('observed_tenant', ['nova', 'other'])
async def test_cached_external_job_requires_current_employer_scope_before_priority_refresh(observed_tenant):
    ats = f'https://{observed_tenant}.jobs.feishu.cn/campus/'
    known_job = 'https://nova.jobs.feishu.cn/campus/position/123/detail'
    reader = CampaignReader(None, None, Parser(), None, entry_parser=Parser(output=OUTPUT))
    reader.pages = Pages({SOURCE.career_url: page(SOURCE.career_url, links=[(ats, '校园招聘')]),
                          ats: page(ats), known_job: page(known_job, JD)})
    await reader.check(SOURCE, 2027, {'urls': [known_job],
        'pages': {known_job: {'entry_observation': OUTPUT}}})
    if observed_tenant == 'nova':
        assert reader.pages.visited[:2] == [SOURCE.career_url, known_job]
    else:
        assert known_job not in reader.pages.visited


@pytest.mark.asyncio
@pytest.mark.parametrize('observed_tenant', ['nova', 'other'])
async def test_cached_custom_domain_job_requires_current_exact_portal_document(observed_tenant):
    portal = f'https://apply.custom.example/campus-recruitment/{observed_tenant}/123#/'
    known_job = 'https://apply.custom.example/campus-recruitment/nova/123#/job/abc'
    reader = CampaignReader(None, None, Parser(), None, entry_parser=Parser(output=OUTPUT))
    reader.pages = Pages({SOURCE.career_url: page(SOURCE.career_url, links=[(portal, '校园招聘')]),
                          portal: page(portal), known_job: page(known_job, JD)})
    await reader.check(SOURCE, 2027, {'urls': [known_job],
        'pages': {known_job: {'entry_observation': OUTPUT}}})
    if observed_tenant == 'nova':
        assert reader.pages.visited[:2] == [SOURCE.career_url, known_job]
    else:
        assert known_job not in reader.pages.visited


@pytest.mark.asyncio
async def test_readable_campus_job_does_not_require_dynamic_homepage_navigation():
    class FailedNavigation(CompanyEvidenceReader):
        async def read(self, url, **kwargs):
            if url == JOB_URL:
                return page(url, JD, method='browser')
            return page(url, '2027届校园招聘', method='http', needs_navigation=True)

    reader = CampaignReader(None, None, Parser(), None, entry_parser=Parser(output=OUTPUT))
    reader.pages = FailedNavigation(None, on_event=lambda *_: None)
    result = await reader.check(SOURCE, 2027, {'urls': [JOB_URL],
        'pages': {JOB_URL: {'entry_observation': OUTPUT}}})
    assert not result['stats']['announcement_check_complete']
    assert result['cache']['pending_checks'] == []
    assert result['error'] is None
    assert result['cache']['job_check']['status'] == 'found'


@pytest.mark.asyncio
async def test_unread_announcement_survives_many_queued_jobs_and_precedes_them():
    notice = "https://nova.example/notice/supplement"

    class BudgetParser(Parser):
        async def parse(self, page, year):
            reader.time_budget = 0
            return []

    reader = CampaignReader(None, None, BudgetParser(), None)
    links = [(JOB_URL + str(i), "算法工程师") for i in range(20)] + [(notice, "2027届秋招补录公告")]
    reader.pages = Pages({SOURCE.career_url: page(SOURCE.career_url, links=links)})
    result = await reader.check(SOURCE, 2027, {})
    pending = result["cache"]["pending_checks"]
    assert len(pending) == 8 and pending[0]["url"] == notice
    reader.time_budget = 90
    reader.pages = Pages({SOURCE.career_url: page(SOURCE.career_url), notice: page(notice, "2027届秋招补录公告")})
    await reader.check(SOURCE, 2027, result["cache"])
    assert reader.pages.visited == [SOURCE.career_url, notice]


@pytest.mark.asyncio
async def test_campus_job_skips_both_keyword_filtered_lists_and_announcements():
    filtered = SOURCE.career_url + '#/?keyword=算法&page=1'
    notice = SOURCE.career_url + '?projectId=supplement'
    reader = CampaignReader(None, None, Parser(), None, entry_parser=Parser(output=OUTPUT))
    reader.pages = Pages({SOURCE.career_url: page(SOURCE.career_url, links=[
        (JOB_URL, '算法工程师'), (filtered, '算法岗位'), (notice, '校招补录公告')]),
        JOB_URL: page(JOB_URL, JD), notice: page(notice)})
    result = await reader.check(SOURCE, 2027, {})
    assert notice not in reader.pages.visited and filtered not in reader.pages.visited
    assert result['cache']['job_check']['status'] == 'found'


@pytest.mark.parametrize('suffix', ['?hash=%23%2Fpage%2F%E9%9A%90%E7%A7%81%E6%94%BF%E7%AD%96', '#/page/privacy'])
def test_ats_privacy_page_is_not_an_announcement_candidate(suffix):
    assert navigation_candidate('https://app.mokahr.com/campus-recruitment/nova/123' + suffix, '隐私政策', 2027) is None


@pytest.mark.asyncio
async def test_recruitment_program_dates_on_homepage_are_parsed_before_following_job():
    parser = Parser()
    reader = CampaignReader(None, None, parser, None, entry_parser=Parser(output=OUTPUT))
    reader.pages = Pages({SOURCE.career_url: page(SOURCE.career_url,
        '2027届校园招聘 招聘对象：应届毕业生 招聘时间：2026年6月25日开启，招满即止',
        links=[(JOB_URL, '算法工程师')], hiring_links=[JOB_URL]), JOB_URL: page(JOB_URL, JD)})
    await reader.check(SOURCE, 2027, {})
    assert parser.calls == 1


@pytest.mark.asyncio
async def test_announcement_shell_requires_browser_content_before_being_complete():
    notice = SOURCE.career_url + '/announcements'

    class NoticePages(CompanyEvidenceReader):
        def __init__(self):
            super().__init__(None, on_event=lambda *_: None)
            self.rendered = []

        async def read(self, url, *, force_browser=False):
            if url == SOURCE.career_url:
                return page(url, links=[(notice, '校招公告')])
            if url == JOB_URL:
                return page(url, JD, method='browser')
            if force_browser:
                self.rendered.append(url)
                return page(url, '2027届校招正式启动，面向2027届应届毕业生', method='browser')
            return page(url, '首页 校招公告 招聘动态', method='http')

    parser = Parser()
    reader = CampaignReader(None, None, parser, None, entry_parser=Parser(output=OUTPUT))
    reader.pages = NoticePages()
    result = await reader.check(SOURCE, 2027, {})
    assert reader.pages.rendered == [notice]
    assert result['stats']['announcement_check_complete']
    assert notice in result['cache']['pages']


def test_announcement_navigation_keeps_origin_and_shared_tenant_boundaries():
    origin = 'https://app.mokahr.com/campus-recruitment/nova/123'
    assert allowed_listing_url(origin + '/news/1', origin, allow_documents=True)
    assert not allowed_listing_url(origin + '/news/1', origin)
    assert not allowed_listing_url('https://other.example/news/1', origin, allow_documents=True)
    assert not allowed_listing_url(origin.replace('/nova/', '/other/') + '/news/1', origin, allow_documents=True)
    assert not allowed_listing_url(origin + '/apply', origin, allow_documents=True)
