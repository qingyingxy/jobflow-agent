from types import SimpleNamespace

import httpx
import pytest

from src.config import Settings
from src.services.browser_job_reader import PlaywrightBrowserJobReader
from src.services.direct_recruitment_search import DirectRecruitmentSearch
from src.services.recruitment_listing import (
    allowed_entry_navigation,
    inspect_listing,
    observed_hiring_redirect,
)
from src.services.url_reader import (
    FetchedResponse,
    SafeHTTPReader,
    URLSafetyChecker,
    URLSafetyError,
)
from tests.test_recruitment_capabilities import QUERY, SOURCE


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_browser_honors_configured_public_proxy_policy_and_keeps_private_targets_blocked(monkeypatch, enabled):
    from src import config

    monkeypatch.setattr(config, "get_settings", lambda: Settings(_env_file=None,
        url_fetch_proxy="http://proxy.example:8080", url_fetch_proxy_allow_unlisted_hosts=enabled))
    browser = PlaywrightBrowserJobReader()
    browser.safety_checker.resolver = lambda *_: ["198.18.0.1"]
    if enabled:
        assert await browser._validate_url("https://assets.public.example/app.js")
    else:
        with pytest.raises(Exception) as error:
            await browser._validate_url("https://assets.public.example/app.js")
        assert error.value.code == "unsafe_url"
    for url in ("https://127.0.0.1/", "https://service.internal/", "https://user:pass@public.example/", "https://public.example:444/"):
        with pytest.raises(URLSafetyError):
            await browser.safety_checker.validate(url)
    checker = URLSafetyChecker()
    assert PlaywrightBrowserJobReader(safety_checker=checker).safety_checker is checker


@pytest.mark.asyncio
async def test_http_reader_preserves_observed_redirect_status_and_target():
    source, target = "https://careers.example/", "https://newcompany.zhiye.com/"
    transport = httpx.MockTransport(lambda request: httpx.Response(
        302, headers={"Location": target}) if str(request.url) == source else httpx.Response(200, text="jobs"))
    reader = SafeHTTPReader(transport=transport, safety_checker=URLSafetyChecker(resolver=lambda *_: ["8.8.8.8"]))
    response = await reader.fetch(source)
    assert response.redirect_chain == ({"url": source, "status": 302, "target": target},)
    assert observed_hiring_redirect(source, target, response.redirect_chain)
    assert not observed_hiring_redirect(source, "https://other.zhiye.com/", response.redirect_chain)
    assert not observed_hiring_redirect(source, target, ())
    assert not observed_hiring_redirect(source, target, ({"url": source, "status": 200, "target": target},))


@pytest.mark.asyncio
@pytest.mark.parametrize("branded,observed", [(True, True), (False, True), (True, False)])
async def test_direct_reader_uses_only_branded_observed_official_redirect_and_keeps_proof(branded, observed):
    target = "https://newcompany.zhiye.com/"
    html = f'<title>{SOURCE.company if branded else "别的公司"}招聘</title><a href="/jobs/1">Agent工程师</a>'
    chain = ({"url": SOURCE.career_url, "status": 301, "target": target},) if observed else ()

    async def fetch(url):
        assert url == SOURCE.career_url
        return FetchedResponse(url, target, 200, "text/html", html.encode(), redirect_chain=chain)

    found = []
    direct = DirectRecruitmentSearch(sources=[SOURCE], query=QUERY,
        reader=SimpleNamespace(fetch=fetch), browser=object(), on_event=lambda *_: None, max_jobs=1)

    async def verified(_):
        return False

    await direct.discover(found.extend, await_result=verified)
    if branded and observed:
        assert [item.source_url for item in found] == [target + "jobs/1"]
        evidence = direct.evidence[found[0].source_url]
        assert evidence.official_redirects == chain
        assert evidence.official_url == SOURCE.career_url
    else:
        assert not found


def test_ats_tenant_cannot_redirect_into_another_company():
    source, target = "https://first.zhiye.com/", "https://second.zhiye.com/"
    assert not observed_hiring_redirect(source, target, [{"url": source, "status": 301, "target": target}])
    assert not allowed_entry_navigation(target, source)
    assert not allowed_entry_navigation("https://new.example/login", "https://official.example/")
    assert allowed_entry_navigation("https://new.example/campus", "https://official.example/")


@pytest.mark.asyncio
async def test_dynamic_cards_are_read_before_unrelated_campus_faq_links():
    from src.services.browser_job_reader import BrowserPageSnapshot
    from src.services.url_reader import HTMLLink
    from tests.test_recruitment_capabilities import Browser, Reader, run_direct

    html = '<a href="/campus/faq">校招常见问题</a><div class="position-list-item"><div class="title">Agent工程师</div></div>'
    assert inspect_listing(html, url=SOURCE.career_url).job_controls

    class DynamicBrowser(Browser):
        async def read_dynamic_listing(self, url, **kwargs):
            assert url == SOURCE.career_url
            return BrowserPageSnapshot(url, url, "", html, "Agent工程师",
                discovered_links=(HTMLLink("https://careers.example/jobs/1", "Agent工程师"),),
                dynamic_listing={"reason": "listing_boundary"})

    direct, found, _ = await run_direct(Reader({SOURCE.career_url: html}), browser=DynamicBrowser())
    assert found[0].source_url == "https://careers.example/jobs/1"
    assert direct.fresh_sources == {SOURCE.id}


@pytest.mark.asyncio
@pytest.mark.parametrize("path,query", [("campus/", QUERY), ("internship/", "北京 Agent 实习")])
async def test_targeted_portal_renders_navigation_before_leaving_for_global_footer(path, query):
    from dataclasses import replace

    from tests.test_recruitment_capabilities import Browser, Reader

    source = replace(SOURCE, career_url="https://careers.example/" + path)
    target = source.career_url + "position"
    static = '<footer><a href="https://global.example/jobs">全球招聘</a></footer>'
    rendered = f'<nav><a href="{target}">职位</a></nav>' + static
    reader = Reader({source.career_url: static, target: '<a href="/jobs/one">Agent工程师</a>'})
    browser = Browser({source.career_url: rendered})
    direct = DirectRecruitmentSearch(sources=[source], query=query, reader=reader,
        browser=browser, on_event=lambda *_: None, max_jobs=1)
    found = []

    async def verified(_):
        return True

    await direct.discover(found.extend, await_result=verified)
    assert [item.source_url for item in found] == ["https://careers.example/jobs/one"]
    assert browser.calls == [source.career_url]
    assert reader.calls == [source.career_url, target]


@pytest.mark.asyncio
async def test_old_unproductive_navigation_resumes_at_target_without_erasing_acknowledgements():
    from dataclasses import replace

    from tests.test_recruitment_capabilities import Browser, Reader

    source = replace(SOURCE, career_url="https://careers.example/campus/")
    stale = {"url": "https://global.example/jobs", "scope_url": "https://global.example/"}
    state = {"html_queue": [stale], "html_seen_pages": [source.career_url],
             "checked_urls": ["https://careers.example/jobs/old"], "reader_kind": "html"}
    raw = '<a href="/campus/position">职位</a>'
    reader = Reader({source.career_url: raw,
        "https://careers.example/campus/position": '<a href="/jobs/new">Agent工程师</a>'})
    direct = DirectRecruitmentSearch(sources=[source], query=QUERY, reader=reader, browser=Browser(),
        states={source.id: state}, on_event=lambda *_: None, target_per_company=1)
    found = []
    await direct.discover(found.extend)
    assert [item.source_url for item in found] == ["https://careers.example/jobs/new"]
    assert "https://careers.example/jobs/old" in state["checked_urls"]
    assert stale in state["html_queue"]
    assert state["targeted_navigation_version"] == 1
