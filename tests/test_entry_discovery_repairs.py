import asyncio
from dataclasses import replace

import pytest

from src.services.direct_recruitment_search import DirectRecruitmentSearch
from src.services.entry_identity import entry_brand_matches
from src.services.recruitment_listing import inspect_listing
from src.services.url_reader import URLFetchError
from tests.test_recruitment_capabilities import SOURCE, Reader, listing, run_direct


def test_discovery_keeps_navigation_and_footer_entrances_without_importing_jobs():
    raw = '<div class="header-nav"><a class="nav-li" href="https://campus.other.example/">校园招聘</a></div>' \
          '<footer><a href="/campus/jobs/1">Agent工程师</a><a href="/campus">校园招聘</a></footer>'
    caps = inspect_listing(raw, url=SOURCE.career_url)
    assert {link.url for link in caps.entries} == {"https://campus.other.example/", "https://careers.example/campus"}
    assert not caps.jobs


@pytest.mark.parametrize("company,title,origin,expected", [
    ("未见科技", "加入未见集团", "https://weijian.example/", True),
    ("新星公司", "Nova Careers", "https://jobs.nova.example/", True),
    ("新星公司", "Other Careers", "https://jobs.nova.example/", False),
    ("新星公司", "Careers", "https://jobs.nova.example/", False),
])
def test_brand_alias_requires_name_or_trusted_origin_evidence(company, title, origin, expected):
    assert entry_brand_matches(company, title, official_url=origin) == expected


@pytest.mark.asyncio
async def test_one_failed_entry_yields_to_other_entrance_and_persists_retry():
    root = SOURCE.career_url
    first, second = "https://careers.example/campus-broken", "https://careers.example/campus-working"
    pages = {root: f'<a href="{first}">校园招聘</a><a href="{second}">校园招聘</a>',
             first: URLFetchError("unavailable"), second: listing([1, 2])}
    direct, jobs, events = await run_direct(Reader(pages))
    assert len(jobs) == 2
    failed = next(p for p in direct.states[SOURCE.id]["html_queue"] if p["url"] == first)
    assert failed["read_failures"] == 1 and failed["retry_at"]
    assert any(e.get("url") == first and e.get("error_code") for e in events)


@pytest.mark.asyncio
async def test_translated_brand_works_from_observed_official_outbound_link():
    source = replace(SOURCE, company="新星公司", career_url="https://nova.example/careers")
    target = "https://jobs.newportal.example/"
    pages = {source.career_url: f'<a href="{target}">校园招聘</a>',
             target: '<title>Nova Careers</title>' + listing([1])}
    _, jobs, _ = await run_direct(Reader(pages), source=source)
    assert len(jobs) == 1


@pytest.mark.asyncio
async def test_stalled_dynamic_entry_is_saved_before_company_deadline_and_next_entry_runs():
    from tests.test_recruitment_capabilities import QUERY, Browser

    first, second = SOURCE.career_url, "https://careers.example/campus-working"

    class StalledBrowser(Browser):
        async def read_dynamic_listing(self, url, **kwargs):
            await asyncio.Event().wait()

    entry = {"scope_url": first, "proof_url": first, "official_html": ""}
    states = {SOURCE.id: {"html_queue": [{**entry, "url": first}, {**entry, "url": second}]}}
    direct = DirectRecruitmentSearch(sources=[SOURCE], query=QUERY,
        reader=Reader({first: '<div class="position-list-item"><div class="title">Agent工程师</div></div>', second: listing([1])}),
        browser=StalledBrowser(), states=states, company_seconds=1, on_event=lambda *_: None)
    found = []
    await direct.discover(found.extend)
    assert len(found) == 1
    failed = next(p for p in states[SOURCE.id]["html_queue"] if p["url"] == first)
    assert failed["last_error"] == "entry_timeout" and failed["retry_at"]
