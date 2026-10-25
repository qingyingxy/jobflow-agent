from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from src.config import Settings
from src.infrastructure.llm_client import FakeModelClient
from src.services.campaign_cohort import cohort_status, relevant_campaign_text
from src.services.campaign_entry import (
    CampaignEntryParser,
    application_actions,
    entry_campaign,
)
from src.services.campaign_parser import (
    Announcement,
    CampaignParser,
    validate_announcement,
)
from src.services.campaign_reader import CampaignReader, campaign_url_key
from src.services.campaign_service import (
    campaign_payload,
    effective_status,
    save_campaign,
)
from src.services.company_evidence_reader import html_page
from src.services.company_registry import CompanySource
from src.services.url_reader import HTMLLink

SOURCE = CompanySource("example", "示例科技", "A", "https://careers.example.com/campus", "official")
SETTINGS = Settings(_env_file=None, app_env="testing", structured_model_provider="fake")
NOW = datetime.now(UTC)
NOTICE = "示例科技校园招聘 招聘对象为应届毕业生，欢迎加入研发团队，网申进行中。"
FACT = {"title": "示例科技校园招聘", "scope_quote": NOTICE, "year": 2027, "year_quote": "",
        "batch": "campus", "batch_quote": "校园招聘", "status": "open", "status_quote": "网申进行中",
        "published": None, "starts": None, "deadline": None, "directions": []}
JD = "算法工程师 校园招聘 面向2027年毕业的应届生 岗位职责：开发算法和模型。任职要求：熟悉Python。立即投递"
JOB = {"kind": "job", "title": "算法工程师", "scope_quote": JD, "campus_quote": "校园招聘",
       "year_quote": "面向2027年毕业的应届生", "status": "open", "status_quote": "",
       "job_titles": ["算法工程师"], "apply_label": "立即投递"}
ATS = "https://app.mokahr.com/campus-recruitment/example/"


@pytest.mark.parametrize("text,expected", [
    ("2027届", "confirmed"), ("面向27届毕业生", "confirmed"),
    ("2027年毕业的应届生", "confirmed"), ("2024年-2027年毕业的应届生", "confirmed"),
    ("2026年9月—2027年8月毕业", "confirmed"), ("2027年及以后毕业", "confirmed"),
    ("毕业时间：2027年", "confirmed"), ("2026届毕业生", "excluded"),
    ("2024年-2026年毕业的应届生", "excluded"), ("不接受2027届毕业生", "excluded"),
    ("发布日期2027年1月1日", "unspecified"), ("2027校园招聘", "unspecified"),
    ("2026年10月到2027年1月网申开放", "unspecified"), ("应届毕业生", "unspecified"),
])
def test_cohort_is_based_on_graduation_not_a_calendar_year(text, expected):
    assert cohort_status(text, 2027) == expected


@pytest.mark.asyncio
async def test_unspecified_cohort_reaches_model_and_is_not_claimed_as_confirmed():
    client = FakeModelClient(output={"announcements": [FACT]})
    facts = await CampaignParser(client, SETTINGS).parse({"url": SOURCE.career_url, "text": NOTICE}, 2027)
    assert len(client.requests) == 1
    assert facts[0]["year"] == 2027 and facts[0]["cohort_status"] == "unspecified"
    assert facts[0]["year_quote"] == ""


def test_explicit_wrong_cohort_is_excluded_even_when_model_omits_the_year_quote():
    body = NOTICE + "仅面向2026届毕业生。"
    assert validate_announcement(Announcement(**{**FACT, "scope_quote": body}), body, 2027) is None
    body = NOTICE + "招聘对象为2024年-2027年毕业的应届生。"
    fact = validate_announcement(Announcement(**{**FACT, "scope_quote": body,
        "year_quote": "2024年-2027年毕业的应届生"}), body, 2027)
    assert fact["cohort_status"] == "confirmed"


def test_long_page_keeps_application_facts_after_the_old_text_cutoff():
    text = NOTICE + "公司业务介绍。" * 8000 + "投递须知：网申截止2026年11月30日。"
    page = html_page(f"<main>{text}</main>", url=SOURCE.career_url, digest="hash", text_limit=120000)
    selected = relevant_campaign_text(page["text"])
    assert "2026年11月30日" in selected and NOTICE in selected
    assert len(selected) <= 22000


def test_disabled_and_hidden_apply_controls_do_not_prove_availability():
    assert application_actions('<button disabled>立即投递</button><div hidden><a href="/apply">申请职位</a></div>') == []
    assert application_actions('<button aria-disabled="true">立即申请</button><button class="is-disabled">投递简历</button>') == []
    assert application_actions('<button><span>立即投递</span></button>') == ["立即投递"]


@pytest.mark.asyncio
async def test_only_a_readable_concrete_job_with_current_evidence_is_applyable():
    client = FakeModelClient(output=JOB)
    page = {"url": ATS + "job/123", "text": JD, "application_actions": ["立即投递"]}
    observation = await CampaignEntryParser(client, SETTINGS).parse(page, 2027)
    facts = entry_campaign(observation, page, SOURCE, 2027)
    assert facts["entry"]["status"] == "open" and facts["cohort_status"] == "confirmed"
    checked = datetime.fromisoformat(facts["entry"]["checked_at"])
    assert effective_status(facts, checked + timedelta(seconds=5), checked) == "open"
    page["application_actions"] = []
    observation = await CampaignEntryParser(client, SETTINGS).parse(page, 2027)
    assert entry_campaign(observation, page, SOURCE, 2027)["entry"]["status"] == "unknown"
    landing = {**JOB, "kind": "project", "scope_quote": "校园招聘欢迎你，立即投递", "year_quote": "", "title": "校园招聘"}
    assert entry_campaign(landing, page, SOURCE, 2027)["entry"]["status"] == "unknown"


@pytest.mark.asyncio
async def test_detail_fields_can_be_separate_literal_quotes_on_the_same_job_page():
    output = {**JOB, "scope_quote": "岗位职责：开发算法和模型。任职要求：熟悉Python。"}
    client = FakeModelClient(output=output)
    page = {"url": ATS + "job/123", "text": JD, "application_actions": ["立即投递"]}
    observation = await CampaignEntryParser(client, SETTINGS).parse(page, 2027)
    assert observation is not None
    assert entry_campaign(observation, page, SOURCE, 2027)["entry"]["status"] == "open"
    client = FakeModelClient(output={**output, "campus_quote": "未出现的2027校招"})
    assert await CampaignEntryParser(client, SETTINGS).parse(page, 2027) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("heading", ["岗位描述", "岗位职责", "职位描述"])
async def test_equivalent_responsibility_headings_confirm_open_job_without_inventing_cohort(heading):
    description = heading + "：负责产品业务系统的全栈开发，参与需求分析和架构设计。"
    output = {**JOB, "scope_quote": description, "campus_quote": "应届毕业生", "year_quote": ""}
    page = {"url": ATS + "job/123", "text": "算法工程师 应届毕业生 " + description + "立即投递",
            "application_actions": ["立即投递"]}
    observation = await CampaignEntryParser(FakeModelClient(output=output), SETTINGS).parse(page, 2027)
    facts = entry_campaign(observation, page, SOURCE, 2027)
    assert facts["entry"]["status"] == "open"
    assert facts["cohort_status"] == "unspecified" and not facts["entry"]["year_quote"]


@pytest.mark.asyncio
async def test_listing_cannot_borrow_a_cohort_from_another_project_section():
    body = "招聘职位 社会招聘职位 实习项目：面向2027届毕业生，为同学提供转正机会。"
    output = {**JOB, "kind": "listing", "title": "招聘职位", "scope_quote": "招聘职位",
              "campus_quote": "面向2027届毕业生", "year_quote": "2027届", "status_quote": "", "apply_label": ""}
    client = FakeModelClient(output=output)
    assert await CampaignEntryParser(client, SETTINGS).parse({"url": ATS, "text": body}, 2027) is None


@pytest.mark.asyncio
async def test_entry_publication_date_is_not_kept_as_a_graduation_quote():
    client = FakeModelClient(output={**JOB, "year_quote": "2026-10-19"})
    observed = await CampaignEntryParser(client, SETTINGS).parse(
        {"url": ATS + "job/123", "text": JD + " 发布于2026-10-19", "application_actions": ["立即投递"]}, 2027)
    assert observed["year_quote"] == ""


def test_paused_job_and_single_closed_job_do_not_mark_the_whole_campaign_open_or_closed():
    page = {"url": ATS + "job/123", "text": JD}
    paused = entry_campaign({**JOB, "status_quote": "暂停接受申请"}, page, SOURCE, 2027)
    assert paused["entry"]["status"] == "unknown"
    closed = entry_campaign({**JOB, "status_quote": "职位已下线"}, page, SOURCE, 2027, {"campaign": FACT})
    assert closed["entry"]["status"] == "closed"
    assert closed["status"] == FACT["status"]


def test_placeholder_responsibilities_and_apply_button_do_not_prove_a_readable_job():
    output = {**JOB, "scope_quote": "岗位职责 请您详见岗位意向中的岗位职责 岗位要求 请您详见岗位意向中的岗位要求"}
    facts = entry_campaign(output, {"url": ATS + "job/123"}, SOURCE, 2027)
    assert facts["entry"]["status"] == "unknown"


class Pages:
    def __init__(self, data):
        self.data, self.visited = data, []

    async def read(self, url):
        self.visited.append(url)
        return self.data.get(url)


class NoticeParser:
    async def parse(self, page, year):
        return [{**FACT, "cohort_status": "unspecified"}] if page["url"] == SOURCE.career_url else []


class JobParser:
    async def parse(self, page, year):
        return JOB if "job/123" in page["url"] else {**JOB, "kind": "listing", "apply_label": ""}


def page(url, text=NOTICE, links=()):
    return {"url": url, "text": text, "links": [HTMLLink(url=u, text=t) for u, t in links]}


@pytest.mark.asyncio
async def test_official_outbound_link_reaches_a_job_without_trusting_other_ats_tenants():
    other = "https://app.mokahr.com/campus-recruitment/another/job/456"
    pages = Pages({
        SOURCE.career_url: page(SOURCE.career_url, links=[(ATS, "应届投递")]),
        ATS: page(ATS, links=[(ATS + "job/123", "算法工程师"), (other, "研发工程师")]),
        ATS + "job/123": page(ATS + "job/123", JD),
    })
    reader = CampaignReader(None, None, NoticeParser(), None, entry_parser=JobParser())
    reader.pages = pages
    result = await reader.check(SOURCE, 2027, {})
    assert pages.visited == [SOURCE.career_url, ATS, ATS + "job/123"]
    assert len(result["found"]) == 1
    facts, url = result["found"][0]
    assert url == SOURCE.career_url and facts["entry"]["url"] == ATS + "job/123"
    assert facts["entry"]["status"] == "open"
    assert result["stats"]["stop_reason"] == "campus_jobs_found"


@pytest.mark.asyncio
async def test_search_result_alone_cannot_authorize_an_external_application_host():
    class Provider:
        async def discover(self):
            return [SimpleNamespace(source_url=ATS + "job/123", title="示例科技应届投递")]
    reader = CampaignReader(None, None, NoticeParser(), lambda *_a, **_k: Provider())
    reader.pages = Pages({SOURCE.career_url: page(SOURCE.career_url)})
    result = await reader.check(SOURCE, 2027, {"urls": [ATS + "job/123"], "origins": ["https://evil.example/"]})
    assert reader.pages.visited == [SOURCE.career_url]
    assert all(not fact.get("entry") for fact, _ in result["found"])


@pytest.mark.asyncio
async def test_public_campaign_check_skips_personal_and_internship_navigation():
    links = [(SOURCE.career_url + "/resume/applied", "投递记录"),
             (SOURCE.career_url + "/personal", "我的申请"),
             (SOURCE.career_url + "/jobs/list?recruitType=INTERN", "职位")]
    reader = CampaignReader(None, None, NoticeParser(), None)
    reader.pages = Pages({SOURCE.career_url: page(SOURCE.career_url, links=links)})
    await reader.check(SOURCE, 2027, {})
    assert reader.pages.visited == [SOURCE.career_url]


@pytest.mark.asyncio
async def test_campaign_promotions_share_one_read_but_distinct_projects_keep_their_identity():
    urls = [SOURCE.career_url + '?projectId=1&referral_code=one',
            SOURCE.career_url + '?referral_code=two&projectId=1',
            SOURCE.career_url + '?projectId=2']
    data = {SOURCE.career_url: page(SOURCE.career_url, links=[(u, '校园招聘') for u in urls])}
    data.update({u: page(u) for u in urls})
    reader = CampaignReader(None, None, NoticeParser(), None)
    reader.pages = Pages(data)
    result = await reader.check(SOURCE, 2027, {})
    assert reader.pages.visited == [SOURCE.career_url, urls[0], urls[2]]
    assert result['stats']['duplicate_urls_skipped'] == 1
    assert campaign_url_key(ATS + '#/jobs?jobId=1&utm_source=a') != campaign_url_key(ATS + '#/jobs?jobId=2&utm_source=a')
    assert campaign_url_key(ATS + '#/jobs?jobId=1&recommendCode=x') == campaign_url_key(ATS + '#/jobs?jobId=1&recommendCode=y')


@pytest.mark.asyncio
async def test_help_pages_do_not_displace_a_concrete_job_and_timing_is_recorded():
    help_url, job_url = SOURCE.career_url + '/faq', SOURCE.career_url + '/job/123'
    reader = CampaignReader(None, None, NoticeParser(), None, entry_parser=JobParser())
    reader.pages = Pages({SOURCE.career_url: page(SOURCE.career_url, links=[(help_url, '投递须知'), (job_url, '算法工程师')]),
                          job_url: page(job_url, JD), help_url: page(help_url)})
    result = await reader.check(SOURCE, 2027, {})
    assert reader.pages.visited == [SOURCE.career_url, job_url]
    assert result['stats']['first_verified_entry_ms'] is not None


@pytest.mark.asyncio
async def test_repeated_source_denials_stop_same_host_searches_in_this_round():
    from src.services.url_reader import URLFetchError
    class Denied:
        calls = 0
        async def fetch(self, url):
            self.calls += 1
            raise URLFetchError("denied", code="source_http_error", status_code=412)
    class Provider:
        calls = 0
        async def discover(self):
            self.calls += 1
            return [SimpleNamespace(source_url=SOURCE.career_url + f'/notice/{i}', title='校园招聘') for i in range(5)]
    transport, provider = Denied(), Provider()
    reader = CampaignReader(transport, None, NoticeParser(), lambda *_a, **_k: provider)
    result = await reader.check(SOURCE, 2027, {})
    assert transport.calls == 2 and provider.calls == 1
    assert result['stats']['stop_reason'] == 'source_unavailable'
    assert not result['readable'] and not result['found']


@pytest.mark.asyncio
async def test_useful_navigation_can_continue_beyond_five_pages():
    urls = [SOURCE.career_url] + [SOURCE.career_url + f"/project/{i}" for i in range(1, 7)] + [SOURCE.career_url + "/job/123"]
    data = {url: page(url, links=[(urls[i + 1], "校招岗位")]) for i, url in enumerate(urls[:-1])}
    data[urls[-1]] = page(urls[-1], JD)
    reader = CampaignReader(None, None, NoticeParser(), None, entry_parser=JobParser())
    reader.pages = Pages(data)
    result = await reader.check(SOURCE, 2027, {})
    assert len(reader.pages.visited) == 8
    assert result["stats"]["stop_reason"] == "campus_jobs_found"


@pytest.mark.parametrize("status,quote,retained_date", [
    ("unknown", "", None), ("announced", "校园招聘正式启动", None),
    ("announced", "校园招聘正式启动", "starts"),
    ("announced", "校园招聘正式启动", "deadline"),
])
def test_new_announcement_read_does_not_renew_an_old_entry_or_missing_dates(db_session, status, quote, retained_date):
    window = {**FACT, "starts": {"value": "2026-01-01", "quote": "网申开始2026年1月1日"},
        "deadline": {"value": "2099-12-31", "quote": "网申截止2099年12月31日"}}
    past = NOW - timedelta(days=2)
    row = save_campaign(db_session, "owner", SOURCE, window, SOURCE.career_url, past)
    db_session.commit()
    new = {**FACT, "status": status, "status_quote": quote}
    if retained_date:
        new[retained_date] = window[retained_date]
    save_campaign(db_session, "owner", SOURCE, new, SOURCE.career_url, NOW)
    db_session.commit()
    payload = campaign_payload(row, NOW)
    assert payload["status"] == "unknown" and payload["availability_stale"]
    assert payload["facts"]["deadline"] is not None
    assert payload["availability_checked_at"] == past.isoformat()


@pytest.mark.parametrize("evidence", ["window", "current_status"])
def test_actual_availability_reread_renews_old_dates_or_current_status(db_session, evidence):
    window = {**FACT, "status": "announced", "status_quote": "校园招聘正式启动",
              "starts": {"value": "2026-01-01", "quote": "网申开始2026年1月1日"},
              "deadline": {"value": "2099-12-31", "quote": "网申截止2099年12月31日"}}
    row = save_campaign(db_session, "owner", SOURCE, window, SOURCE.career_url, NOW - timedelta(days=2))
    db_session.commit()
    fresh = window if evidence == "window" else FACT
    save_campaign(db_session, "owner", SOURCE, fresh, SOURCE.career_url, NOW)
    db_session.commit()
    payload = campaign_payload(row, NOW)
    assert payload["status"] == "open" and not payload["availability_stale"]
    assert payload["availability_checked_at"] == NOW.isoformat()


def test_announcement_without_availability_never_falls_back_to_page_read_time(db_session):
    row = save_campaign(db_session, "owner", SOURCE,
        {**FACT, "status": "announced", "status_quote": "校园招聘正式启动"}, SOURCE.career_url, NOW)
    db_session.commit()
    payload = campaign_payload(row, NOW)
    assert payload["status"] == "announced" and payload["availability_stale"]
    assert payload["availability_checked_at"] is None


def test_verified_application_url_expires_independently_of_other_page_reads(db_session):
    facts = {**FACT, "status": "unknown", "status_quote": "", "entry": {
        "status": "open", "url": ATS + "job/123", "kind": "job", "title": "算法工程师", "checked_at": NOW.isoformat()}}
    row = save_campaign(db_session, "owner", SOURCE, facts, SOURCE.career_url, NOW)
    db_session.commit()
    assert campaign_payload(row, NOW)["application_url"] == ATS + "job/123"
    save_campaign(db_session, "owner", SOURCE, {**FACT, "status": "unknown", "status_quote": ""}, SOURCE.career_url, NOW + timedelta(days=2))
    db_session.commit()
    payload = campaign_payload(row, NOW + timedelta(days=2))
    assert payload["application_url"] is None and payload["entry_url"] == ATS + "job/123"
    assert payload["status"] == "unknown"
