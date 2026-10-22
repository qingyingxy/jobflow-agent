from dataclasses import replace

import pytest

from src.services.recruitment_listing import (
    entry_priority,
    inspect_listing,
    recruitment_priority,
)
from src.services.url_reader import HTMLLink
from tests.test_recruitment_capabilities import SOURCE, Reader, run_direct


@pytest.mark.asyncio
async def test_observed_outbound_jobs_preserve_exact_proof_without_trusting_other_tenants():
    a = "https://app.mokahr.com/social-recruitment/alpha/100#/job/one"
    b = "https://app.mokahr.com/social-recruitment/beta/200#/job/two"
    raw = f'<main><a href="{a}">Agent工程师</a></main><footer><a href="{b}">Agent工程师</a></footer>'
    direct, jobs, _ = await run_direct(Reader({SOURCE.career_url: raw}))
    assert [job.source_url for job in jobs] == [a]
    proof = direct.evidence[a]
    assert proof.listing_url == SOURCE.career_url and proof.listing_html == raw
    assert not proof.full_body
    # A tenant page cannot introduce another tenant as this employer's job.
    tenant = replace(SOURCE, career_url=a, official_homepage_url="https://company.example/", hiring_evidence_url="https://company.example/careers")
    _, foreign, _ = await run_direct(Reader({a: f'<main><a href="{b}">Agent工程师</a></main>'}), source=tenant)
    assert not foreign


def test_conflicting_type_labels_remain_readable_but_do_not_prove_campus():
    link = HTMLLink("https://example.jobs.feishu.cn/campusOfTeam/position/list", "社招职位")
    assert recruitment_priority(link, ["校招"]) == 1
    assert recruitment_priority(HTMLLink("https://careers.example/social", "社会招聘"), ["校招"]) == 2


def test_regional_portal_is_routed_before_job_type_and_only_with_target_location():
    link = HTMLLink("https://careers.example/experienced", "Careers in China")
    assert entry_priority(link, ["校招"], "北京上海 Agent 校招") == 0
    assert entry_priority(link, ["校招"], "Agent 校招") == 2


def test_generic_card_hint_needs_role_and_metadata():
    raw = '<div class="item___123"><div><span>Agent工程师</span></div><p>工作地点：上海</p></div>'
    assert inspect_listing(raw, url=SOURCE.career_url).job_controls
    assert not inspect_listing(raw.replace('工作地点：上海', '最新文章'), url=SOURCE.career_url).job_controls


def test_image_only_ats_portal_links_are_navigation_but_application_actions_are_not():
    portal = "https://app.mokahr.com/apply/example/100#/jobs?page=1"
    caps = inspect_listing(f'<a href="{portal}"><svg></svg></a>'
                           '<a href="https://app.mokahr.com/apply/example/100">申请职位</a>', url=SOURCE.career_url)
    assert [entry.url for entry in caps.entries] == [portal]
    assert not caps.jobs and not caps.outbound_jobs
    assert inspect_listing('<a href="/apply">Agent工程师</a>', url=SOURCE.career_url).jobs == ()


def test_document_route_restoration_never_changes_another_host_tenant_or_query():
    from src.services.recruitment_listing import listing_document_url

    portal = "https://app.mokahr.com/apply/example/100#/jobs?page=1"
    document = portal.split('#')[0]
    assert listing_document_url(document, portal) == portal
    for target in (document.replace('example', 'other'), document + '?apply=1', document.replace('app.', 'evil.')):
        assert listing_document_url(target, portal) == target


@pytest.mark.asyncio
async def test_http_document_without_fragment_keeps_observed_spa_listing_route():
    from src.services.url_reader import FetchedResponse
    from tests.test_recruitment_capabilities import Browser

    portal = "https://app.mokahr.com/apply/example/100#/jobs?page=1"
    job = "https://app.mokahr.com/apply/example/100#/job/abc"

    class DocumentReader:
        async def fetch(self, url):
            return FetchedResponse(url, url.split('#')[0], 200, "text/html", b'<div id="app"></div>')

    browser = Browser({portal: f'<a href="{job}">Agent工程师</a>'})
    _, jobs, _ = await run_direct(DocumentReader(), source=replace(SOURCE, career_url=portal,
        official_homepage_url="https://company.example/", hiring_evidence_url="https://company.example/careers"), browser=browser)
    assert [item.source_url for item in jobs] == [job]
    assert browser.calls == [portal]


@pytest.mark.asyncio
async def test_verified_external_origin_allows_generic_list_title_and_prioritizes_new_campus_entry():
    from tests.test_recruitment_capabilities import Browser

    portal = "https://external.example/careers"
    campus = "https://external.example/campus"
    job = "https://external.example/jobs/1"
    pages = {SOURCE.career_url: f'<a href="{portal}">招聘官网</a>',
             portal: f'<title>{SOURCE.company}招聘</title><a href="/other/jobs">更多职位</a><a href="{campus}">校园招聘</a>',
             campus: f'<title>Job Search</title><a href="{job}">Agent工程师</a>'}
    direct, jobs, _ = await run_direct(Reader(pages), browser=Browser())
    assert [candidate.source_url for candidate in jobs] == [job]
    proof = direct.states[SOURCE.id]["verified_entry"]
    assert proof["brand_evidence"]["url"] == portal
    assert proof["require_brand"] is False
