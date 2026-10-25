import pytest
from sqlalchemy import select

from src.domain.company_source import DiscoveredCompany
from src.services.company_identity_evidence import (
    company_name_matches,
    homepage_declarations,
)
from src.services.url_reader import HTMLLink
from tests.test_company_discovery import CAREER, HOME, NAME, PROOF, agent


@pytest.mark.parametrize("name,text,expected", [
    ("千寻智能Spirit AI", "千寻智能2027校园招聘", True),
    ("千寻智能Spirit AI", "Spirit AI campus jobs", True),
    ("千寻智能Spirit AI", "AI companies", False),
    ("Moonshot AI", "Moonshot · Kimi 招聘官网", True),
    ("Moonshot AI", "Moonshotter", False),
])
def test_names_use_explicit_brand_components(name, text, expected):
    assert company_name_matches(name, text) == expected


@pytest.mark.asyncio
async def test_labeled_homepage_in_source_text_is_evidence_without_claiming_a_link(db_session):
    worker, pages, _, _ = agent(db_session)
    pages.html[PROOF] = f'<title>大学就业网</title><p>{NAME}公司介绍 公司官网：{HOME}</p>'
    await worker.run()
    row = db_session.scalar(select(DiscoveredCompany))
    assert row.status == "verified"
    proof = row.evidence["corroboration"]
    assert proof["observation"] == "labeled_text_url"
    assert proof["quote"] == "公司官网：" + HOME


@pytest.mark.parametrize("text", [
    f"{NAME} 假冒官网：{HOME}", f"{NAME} 不是官网：{HOME}",
    f"{NAME} {HOME} 招聘官网已认证", f"另一家公司 公司官网：{HOME}",
])
def test_unlabeled_negative_or_wrong_company_text_does_not_confer_trust(text):
    page = {"url": PROOF, "title": NAME, "text": text, "links": [], "method": "http"}
    assert not homepage_declarations(page, NAME, HOME)


def test_explicit_domain_selects_only_an_observed_homepage_url():
    page = {"url": PROOF, "title": NAME, "text": f'{NAME} 官网仅认准“nova.example”，避免仿冒网站', "links": [], "method": "http"}
    assert not homepage_declarations(page, NAME, "https://jobs.nova.example/")
    found = homepage_declarations(page, NAME, "https://jobs.nova.example/", [HOME])
    assert found[0]["url"] == HOME and found[0]["observation"] == "explicit_domain"


@pytest.mark.asyncio
@pytest.mark.parametrize("backlink,branded,domain,expected", [
    (True, True, "careers.nova.example", "verified"),
    (False, True, "careers.nova.example", "pending"),
    (True, False, "careers.nova.example", "pending"),
    (True, True, "other.example", "pending"),
])
async def test_corroborated_homepage_can_accept_branded_subdomain_with_actual_return_link(db_session, backlink, branded, domain, expected):
    target = f"https://{domain}/campus"
    worker, pages, _, _ = agent(db_session, suggestions=[{"company": NAME, "homepage_url": HOME, "career_url": target}], results=[HOME, PROOF, target])
    pages.html[HOME] = f'<title>{NAME}</title><p>公司产品主页</p>'
    pages.html[target] = f'<title>{NAME if branded else "Other"}校园招聘</title>' + (f'<a href="{HOME}">产品官网</a>' if backlink else "")
    await worker.run()
    row = db_session.scalar(select(DiscoveredCompany))
    assert row.status == expected
    if expected == "verified":
        edge = row.evidence["entry_chain"][0]
        assert edge["url"] == target and edge["linked_url"] == HOME
        assert edge["relation"] == "same_domain_return_to_homepage"


def test_pdf_plain_text_policy_and_wrong_homepage_stay_rejected():
    page = {"url": PROOF, "title": NAME, "text": f'{NAME} 公司官网：{HOME}', "links": [], "method": "pdf"}
    assert not homepage_declarations(page, NAME, HOME)
    page.update(method="http", links=[HTMLLink(CAREER, "招聘")])
    assert not homepage_declarations(page, NAME, "https://wrong.example/")


@pytest.mark.asyncio
async def test_official_social_portal_follows_observed_campus_link(db_session):
    social = "https://app.mokahr.com/social-recruitment/nova/100"
    campus = "https://app.mokahr.com/campus-recruitment/nova/200"
    worker, pages, _, _ = agent(db_session, suggestions=[{"company": NAME, "homepage_url": HOME, "career_url": social}])
    pages.html[HOME] = f'<title>{NAME}</title><a href="{social}">加入我们</a>'
    pages.html[social] = f'<title>{NAME}招聘</title><a href="{campus}">校园招聘</a>'
    pages.html[campus] = f'<title>{NAME}校园招聘</title>'
    await worker.run()
    row = db_session.scalar(select(DiscoveredCompany))
    assert row.status == "verified"
    assert row.career_url == campus
    assert [edge["linked_url"] for edge in row.evidence["entry_chain"]] == [social, campus]


def test_negative_domain_declaration_does_not_grant_trust():
    page = {"url": PROOF, "title": NAME, "text": f'{NAME} 假冒官网为nova.example', "links": [], "method": "http"}
    assert not homepage_declarations(page, NAME, HOME, [HOME])


@pytest.mark.parametrize("text,observed,expected", [
    (f"了解详情，请访问{NAME}·财务云网站：www.nova.example", [HOME], True),
    (f"{NAME}公司网址：www.nova.example", [HOME], True),
    (f"{NAME}公司网址：www.nova.example", [], False),
    (f"{NAME} 假冒网站：www.nova.example", [HOME], False),
    (f"{NAME} 官方网站：www.nova.example.evil.com", [HOME], False),
    (f"{NAME} 邮箱：jobs@nova.example", [HOME], False),
    ("另一家公司网站：www.nova.example", [HOME], False),
])
def test_named_bare_domain_requires_explicit_declaration_and_observed_root(text, observed, expected):
    page = {"url": PROOF, "title": NAME, "text": text, "links": [], "method": "http"}
    result = homepage_declarations(page, NAME, HOME, observed)
    assert bool(result) == expected
    if expected:
        assert result[0]["observation"] == "named_website_domain"


@pytest.mark.asyncio
@pytest.mark.parametrize("root", ["english", "error", "unavailable"])
async def test_corroborated_host_uses_observed_localized_recruitment_page(db_session, root):
    local = HOME + "cn/campus"
    worker, pages, _, _ = agent(db_session, results=[local, PROOF], suggestions=[{
        "company": NAME, "homepage_url": HOME, "career_url": CAREER}])
    pages.html[local] = f'<title>{NAME}校园招聘</title><a href="{CAREER}">立即申请职位</a>'
    if root == "unavailable":
        pages.html.pop(HOME)
    else:
        pages.html[HOME] = '<title>Nova Global</title>Innovation' if root == "english" else '<title>无法显示此网页</title>错误代码：123'
    await worker.run()
    row = db_session.scalar(select(DiscoveredCompany))
    assert row.status == "verified" and row.homepage_url == HOME
    assert row.evidence["homepage"]["url"] == local
    assert row.evidence["entry_chain"][0]["url"] == local
    assert row.evidence["corroboration"]["url"] == PROOF


@pytest.mark.asyncio
@pytest.mark.parametrize("proof,body,expected", [
    (True, True, "verified"), (False, True, "pending"), (True, False, "pending"),
])
async def test_corroborated_campus_root_does_not_require_a_second_hiring_link(db_session, proof, body, expected):
    worker, pages, _, _ = agent(db_session, results=[HOME, PROOF] if proof else [HOME], suggestions=[{
        "company": NAME, "homepage_url": HOME, "career_url": HOME}])
    pages.html[HOME] = f'<title>{NAME}校园招聘</title>' + (
        '<p>2027届校园招聘开启。欢迎海内外应届毕业生加入我们。招聘流程包含简历投递、笔试测评、面试和录用。我们提供研发、咨询和销售岗位，请关注招聘动态了解更多信息。</p>' if body else '<div id="root"></div>')
    await worker.run()
    row = db_session.scalar(select(DiscoveredCompany))
    assert row.status == expected
    if expected == "verified":
        assert row.career_url == HOME
        assert row.evidence["entry_chain"][0]["relation"] == "corroborated_recruitment_page"


@pytest.mark.asyncio
async def test_neutral_title_can_use_company_body_with_independent_proof(db_session):
    worker, pages, _, _ = agent(db_session)
    pages.html[HOME] = f'<title>首页</title><h1>{NAME}</h1><a href="{CAREER}">校园招聘</a>'
    await worker.run()
    assert db_session.scalar(select(DiscoveredCompany)).status == "verified"


def test_named_independent_result_precedes_unrelated_government_results(db_session):
    worker, _, _, _ = agent(db_session)
    unrelated = [f"https://agency{i}.gov.cn/search" for i in range(5)]
    relevant = "https://zh.wikipedia.org/wiki/Nova"
    urls = worker.evidence_urls([*unrelated, relevant], company=NAME,
        hints={relevant: NAME + " 公司简介，官方网站 nova.example"})
    assert urls[0] == relevant


@pytest.mark.asyncio
async def test_identity_search_includes_observed_domain_without_trusting_snippets(db_session):
    worker, _, searches, _ = agent(db_session, results=[HOME])
    await worker.run()
    row = db_session.scalar(select(DiscoveredCompany))
    assert row.status == "pending"
    assert '"nova.example"' in searches[-1]


@pytest.mark.parametrize("extension", ["doc", "docx", "pdf", "xlsx", "png"])
def test_named_application_download_does_not_declare_a_company_homepage(extension):
    url = f"https://download.nova.example/forms/2027.{extension}"
    page = {"url": PROOF, "title": NAME, "text": NAME + "校园招聘",
            "links": [HTMLLink(url, NAME + "应聘申请表")], "method": "http"}
    assert not homepage_declarations(page, NAME, HOME)


@pytest.mark.asyncio
@pytest.mark.parametrize("redirect,expected", [(HOME + "cn/", "verified"), ("https://other.example/", "pending")])
async def test_observed_legacy_subdomain_redirect_can_resolve_parent_home(db_session, redirect, expected):
    legacy = "https://legacy.nova.example/cn/"
    worker, pages, _, _ = agent(db_session)
    pages.html[HOME] = f'<title>{NAME}</title><a href="{CAREER}">校园招聘</a>'
    pages.html[PROOF] = f'<title>{NAME}公司介绍</title><p>企业网址：{legacy}</p>'
    pages.html[legacy] = pages.html[HOME]
    pages.redirects[legacy] = redirect
    await worker.run()
    row = db_session.scalar(select(DiscoveredCompany))
    assert row.status == expected
    if expected == "verified":
        assert row.homepage_url == HOME
        assert row.evidence["corroboration"]["declared_url"] == legacy
        assert row.evidence["corroboration"]["resolved_homepage"] == HOME
        assert row.evidence["homepage"]["url"] == redirect


@pytest.mark.asyncio
@pytest.mark.parametrize("path,title,expected", [
    ("cn/about/jobs/2026/20260922.html", NAME + "2027校园招聘公告", "verified"),
    ("jobs/123", NAME + "研发工程师招聘", "pending"),
])
async def test_dated_recruitment_announcement_is_an_entry_but_single_job_is_not(db_session, path, title, expected):
    entry = HOME + path
    worker, pages, _, _ = agent(db_session, results=[entry, PROOF], suggestions=[{
        "company": NAME, "homepage_url": HOME, "career_url": entry}])
    pages.html[HOME] = '<title>Global home</title>'
    pages.html[entry] = f'<title>{title}</title><p>' + (
        '面向2027届应届毕业生开展校园招聘，招聘研发、咨询和销售等方向。欢迎符合条件的毕业生了解招聘安排，简历投递后开展在线测评与面试，录用结果将另行通知。') + '</p>'
    await worker.run()
    row = db_session.scalar(select(DiscoveredCompany))
    assert row.status == expected
    if expected == "verified":
        assert row.career_url == entry
        assert row.evidence["entry_chain"][0]["relation"] == "corroborated_recruitment_page"


@pytest.mark.asyncio
@pytest.mark.parametrize("candidate", [HOME, "http://campus.nova.example/"])
async def test_retired_campus_link_does_not_replace_readable_declared_company_home(db_session, candidate):
    retired = "http://campus.nova.example/campusRecruitment/Jobs.html"
    worker, pages, _, _ = agent(db_session, results=[HOME, PROOF, candidate], suggestions=[{
        "company": NAME, "homepage_url": candidate, "career_url": CAREER}])
    pages.html[PROOF] = (f'<title>{NAME}2019校园招聘</title><p>{NAME}官网：www.nova.example</p>'
                        f'<p>{NAME}校招官网：campus.nova.example</p><a href="{retired}">校招官网</a>')
    await worker.run()
    row = db_session.scalar(select(DiscoveredCompany))
    assert row.status == "verified" and row.homepage_url == HOME
    assert row.evidence["corroboration"]["linked_homepage"] == HOME


@pytest.mark.asyncio
@pytest.mark.parametrize("redirect,expected", [(None, "verified"), ("https://www.hotjob.cn/wt/other/web/index", "pending")])
async def test_legacy_hotjob_official_link_is_read_before_about_pages_with_tenant_isolation(db_session, redirect, expected):
    career = "https://www.hotjob.cn/wt/nova/web/index?brandCode=1"
    worker, pages, _, _ = agent(db_session, suggestions=[{
        "company": NAME, "homepage_url": HOME, "career_url": career}])
    pages.html[HOME] = f'<title>{NAME}</title>' + ''.join(
        f'<a href="{HOME}about-{i}">公司介绍</a>' for i in range(5)) + f'<a href="{career}">加入我们</a>'
    pages.html[career] = f'<title>{NAME}校园招聘</title><p>2027届招聘职位</p>'
    if redirect:
        pages.redirects[career] = redirect
    await worker.run()
    assert career in pages.calls
    assert db_session.scalar(select(DiscoveredCompany)).status == expected
    if expected == "verified":
        assert not any("about-" in url for url in pages.calls)


def test_legacy_hotjob_scope_never_trusts_shared_root_or_other_tenant():
    from src.services.recruitment_trust import hiring_scope, within_scope

    assert hiring_scope("https://www.hotjob.cn/") is None
    assert hiring_scope("https://www.hotjob.cn/wt/") is None
    scope = hiring_scope("https://www.hotjob.cn/wt/nova/web/index")
    assert within_scope("https://www.hotjob.cn/wt/nova/web/jobs", scope)
    assert not within_scope("https://www.hotjob.cn/wt/nova-other/web/jobs", scope)
    assert not within_scope("https://other.hotjob.cn/wt/nova/web/jobs", scope)
