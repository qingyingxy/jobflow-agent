from datetime import UTC, datetime

import pytest

from src.domain.discovery import LeadProvider
from src.services.lead_providers import LeadCandidate
from src.services.multiround_search import (
    canonical_search_url,
    is_recruitment_entry,
    search_rounds,
)


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://campus.example.com/", True),
        ("https://talent.example.com/jobs/list?recruitType=GRADUATE", True),
        ("https://talent.example.com/jobs/detail/GRADUATE/abc", False),
    ],
)
def test_recruitment_entry_is_not_a_job(url, expected):
    assert is_recruitment_entry(url) is expected


def lead(url):
    return LeadCandidate(
        provider=LeadProvider.EXTERNAL_AGENT,
        source_url=url,
        discovered_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_replenishes_duplicates_and_stops_only_after_unique_useful_target():
    calls = []
    verified = []
    progress = []

    async def search(number, seen):
        calls.append(number)
        return [
            lead("https://jobs.example/a?utm_source=x"),
            lead(f"https://jobs.example/{number}"),
        ]

    async def verify(candidate):
        verified.append(candidate.source_url)
        return candidate.source_url, candidate.source_url.endswith(("2", "3"))

    stop = await search_rounds(
        search=search,
        verify=verify,
        report=lambda *args: progress.append(args),
        target=2,
    )
    assert calls == [1, 2, 3]
    assert verified.count("https://jobs.example/a") == 1
    assert stop == "达到有效岗位目标"
    assert progress[-1][2] == 2


@pytest.mark.asyncio
async def test_empty_and_failed_searches_continue_until_round_limit():
    calls = []

    async def search(number, seen):
        calls.append(number)
        if number == 1:
            raise RuntimeError("provider unavailable")
        return []

    async def verify(candidate):
        raise AssertionError("no links")

    stop = await search_rounds(
        search=search, verify=verify, report=lambda *args: None, max_rounds=3
    )
    assert calls == [1, 2, 3]
    assert stop == "达到搜索轮数上限"


@pytest.mark.asyncio
async def test_budget_stops_before_next_search():
    async def search(number, seen):
        raise AssertionError("budget exhausted")

    ticks = iter([0, 10])
    stop = await search_rounds(
        search=search,
        verify=None,
        report=lambda *args: None,
        seconds=5,
        clock=lambda: next(ticks),
    )
    assert stop == "达到搜索时间预算"


def test_url_identity_preserves_job_ids():
    assert (
        canonical_search_url("https://x.test/job?id=1&utm_source=x#top")
        == "https://x.test/job?id=1"
    )
    assert canonical_search_url("https://x.test/job?id=1") != canonical_search_url(
        "https://x.test/job?id=2"
    )


def test_ai_application_and_campus_title_are_not_rejected():
    from src.services.discovery_matching import classify_discovery_job
    from src.services.discovery_sources import JobStub
    from src.services.job_fact_verifier import verify_page_facts
    from src.services.url_reader import ParsedHTMLDocument
    document = ParsedHTMLDocument(
        text="2027校招 实时AI应用开发工程师 任职要求 Python", title="2027校招 实时AI应用开发工程师",
        company="Example", locations=["上海"], job_type="FULL_TIME", published_at=None, json_ld=[],
    )
    facts = verify_page_facts(document)
    assert facts.job_type == "campus"
    job = JobStub(source_id="test", source_job_id="1", company=facts.company, title=facts.title,
                  locations=facts.locations, job_type=facts.job_type, published_at=None,
                  detail_url="https://example.com/jobs/1", raw_content=document.text)
    match = classify_discovery_job(job, query="2027校招 AI应用开发 Agent开发 RAG开发 Python后端 上海 杭州")
    assert match.filter_status == "pending"
    assert "graduation_year" in match.mismatch_reasons
    assert "role" in match.mismatch_reasons  # Title/requirements do not establish duties.


@pytest.mark.asyncio
async def test_browser_proxy_keeps_private_addresses_blocked():
    from src.services.browser_job_reader import (
        BrowserReadError,
        PlaywrightBrowserJobReader,
    )
    reader = PlaywrightBrowserJobReader()
    with pytest.raises(BrowserReadError):
        await reader._validate_url("http://127.0.0.1/")
