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
