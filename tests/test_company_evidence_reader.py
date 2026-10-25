import asyncio
from datetime import UTC, datetime, timedelta
from io import BytesIO

import httpx
import pytest
from pypdf import PdfWriter
from pypdf.annotations import Link
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from src.services.browser_job_reader import BrowserPageSnapshot
from src.services.company_evidence_reader import CompanyEvidenceReader
from src.services.url_reader import (
    FetchedResponse,
    SafeHTTPReader,
    URLFetchError,
    URLSafetyChecker,
)

HOME = "https://nova.example/"
CAREER = HOME + "careers"
PROOF = "https://university.edu.cn/nova.pdf"


class Reader:
    def __init__(self, body, content_type="text/html", error=None):
        self.body, self.content_type, self.error = body, content_type, error
        self.calls = []

    async def fetch(self, url):
        self.calls.append(url)
        if self.error:
            raise self.error
        return FetchedResponse(url, url, 200, self.content_type, self.body)


class Browser:
    def __init__(self):
        self.calls = []

    async def read_evidence(self, url):
        self.calls.append(url)
        html = f'<title>Nova</title><p>招聘</p><a href="{CAREER}">加入我们</a>'
        return BrowserPageSnapshot(url, url, "Nova", html, "Nova 招聘 加入我们")


def evidence(reader, browser=None):
    result = CompanyEvidenceReader(reader, browser=browser, on_event=lambda *_: None)
    result.browser_remaining = 1
    return result


@pytest.mark.asyncio
async def test_http_200_error_page_is_a_read_failure_not_company_identity():
    worker = evidence(Reader('<title>无法显示此网页</title><p>错误代码：123</p>'.encode()))
    assert await worker.read(HOME) is None
    assert worker.failures[HOME]["error_code"] == "evidence_error_page"


@pytest.mark.asyncio
@pytest.mark.parametrize("declaration", ["header", "meta", "fallback"])
async def test_legacy_chinese_html_keeps_identity_and_actual_links(declaration):
    html = f'<title>新星科技</title><p>新星科技介绍</p><a href="{HOME}">公司官网</a>'
    if declaration == "meta":
        html = '<meta charset="gb2312">' + html
    reader = Reader(html.encode("gb2312"), "text/html; charset=gb2312" if declaration == "header" else "text/html")
    page = await evidence(reader).read(PROOF)
    assert page["title"] == "新星科技"
    assert page["links"][0].url == HOME and page["links"][0].text == "公司官网"


def pdf_bytes(*, actual_link=True):
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=200)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                             NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"):
        DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 10 100 Td (Nova company: https://nova.example/) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    if actual_link:
        writer.add_annotation(0, Link(rect=(10, 80, 280, 100), url=HOME))
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


@pytest.mark.asyncio
@pytest.mark.parametrize("actual_link", [True, False])
async def test_pdf_uses_text_and_actual_uri_annotations_only(actual_link):
    page = await evidence(Reader(pdf_bytes(actual_link=actual_link), "application/pdf")).read(PROOF)
    assert "Nova company" in page["text"] and page["method"] == "pdf"
    assert [link.url for link in page["links"]] == ([HOME] if actual_link else [])
    assert len(page["sha256"]) == 64


@pytest.mark.asyncio
async def test_sparse_html_is_rendered_once_and_cached_across_restart():
    reader, browser = Reader(b"<title>Nova</title><div id='root'></div>"), Browser()
    worker = evidence(reader, browser)
    await worker.read(HOME, allow_browser=False)
    page = await worker.read(HOME)
    assert page["method"] == "browser" and page["links"][0].url == CAREER
    assert reader.calls == [HOME] and browser.calls == [HOME]
    restored = evidence(reader, browser)
    restored.restore(worker.snapshot())
    page = await restored.read(HOME)
    assert page["method"] == "browser"
    assert reader.calls == [HOME] and browser.calls == [HOME]


@pytest.mark.asyncio
async def test_failed_reads_keep_status_and_do_not_retry_in_browser():
    reader, browser = Reader(b"", error=URLFetchError("secret", code="source_http_error", status_code=403)), Browser()
    worker = evidence(reader, browser)
    assert await worker.read(PROOF) is None
    assert await worker.read(PROOF) is None
    restored = evidence(reader, browser)
    restored.restore(worker.snapshot())
    assert await restored.read(PROOF) is None
    assert reader.calls == [PROOF] and browser.calls == []
    assert worker.attempts[0]["status_code"] == 403
    assert "secret" not in str(worker.snapshot())


@pytest.mark.asyncio
async def test_campaign_host_failures_stop_repeated_denials_without_blocking_another_host():
    reader, browser = Reader(b"", error=URLFetchError("denied", code="source_http_error", status_code=412)), Browser()
    worker = CompanyEvidenceReader(reader, browser=browser, on_event=lambda *_: None, max_host_failures=2)
    worker.browser_remaining = 6
    for suffix in ("one", "two", "three"):
        assert await worker.read(HOME + suffix) is None
    assert len(reader.calls) == 2 and not browser.calls
    assert worker.attempts[-1]["error_code"] == "evidence_host_cooldown"
    reader.error = None
    reader.body = b'<p>Public company information</p>'
    assert await worker.read(PROOF, allow_browser=False) is not None
    assert len(reader.calls) == 3


@pytest.mark.asyncio
async def test_campaign_read_keeps_scoped_hiring_links_and_resolves_navigation_on_full_html():
    reader = Reader(b'<title>Nova</title><main>' + b'company ' * 30 +
                    '<section><h2>应届生招聘</h2><a href="/graduate">立即投递</a><button>查看12个职位</button></section>'.encode() + b'</main>')
    browser = Browser()
    worker = CompanyEvidenceReader(reader, browser=browser, on_event=lambda *_: None, collect_actions=True)
    worker.browser_remaining = 1
    first = await worker.read(HOME, allow_browser=False)
    assert first["needs_navigation"]
    assert "应届生招聘" in next(link.text for link in first["links"] if link.url.endswith('/graduate'))
    await worker.read(HOME)
    assert browser.calls == [HOME]


@pytest.mark.asyncio
async def test_expired_page_is_fetched_again():
    reader = Reader(b"<title>Nova</title><p>old</p>")
    original = evidence(reader)
    await original.read(HOME)
    snapshot = original.snapshot()
    snapshot["read_cache"][0]["checked_at"] = (datetime.now(UTC) - timedelta(days=8)).isoformat()
    reader.body = b"<title>Nova</title><p>new</p>"
    restarted = evidence(reader)
    restarted.restore(snapshot)
    assert "new" in (await restarted.read(HOME))["text"]
    assert reader.calls == [HOME, HOME]


@pytest.mark.asyncio
async def test_http_status_is_preserved_without_changing_error_code():
    reader = SafeHTTPReader(transport=httpx.MockTransport(lambda _: httpx.Response(403)),
                            safety_checker=URLSafetyChecker(resolver=lambda *_: ["8.8.8.8"]))
    with pytest.raises(URLFetchError) as caught:
        await reader.fetch(PROOF)
    assert caught.value.status_code == 403 and caught.value.code == "source_http_error"


@pytest.mark.asyncio
async def test_cancellation_propagates_instead_of_becoming_cached_failure():
    class Waiting:
        async def fetch(self, url):
            await asyncio.Event().wait()

    worker = evidence(Waiting())
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(worker.read(HOME), timeout=0.01)
    assert worker.failures == {}


@pytest.mark.asyncio
async def test_human_gate_is_not_rendered_or_admitted_as_evidence():
    browser = Browser()
    worker = evidence(Reader(b"<title>Just a moment</title><p>Verify you are human</p>"), browser)
    assert await worker.read(HOME) is None
    assert worker.failures[HOME]["error_code"] == "evidence_human_gate"
    assert browser.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("resolved_job", [True, False])
async def test_browser_resolved_job_card_updates_listing_readiness(resolved_job):
    from src.services.url_reader import HTMLLink

    class Cards:
        async def read_evidence(self, url):
            html = '<h1>应届生招聘</h1><main>职位类别 筛选 搜索 下一页</main>'
            links = (HTMLLink(url + 'job/123', '算法工程师'),)
            return BrowserPageSnapshot(url, url, '应届生招聘', html, '',
                discovered_links=links if resolved_job else (),
                discovered_entries=() if resolved_job else (HTMLLink(url + 'campus', '校园招聘'),))

    worker = CompanyEvidenceReader(Reader(b'<div id="root"></div>'), browser=Cards(),
        on_event=lambda *_: None, collect_actions=True)
    worker.browser_remaining = 1
    page = await worker.read(HOME)
    assert page['listing_state'] == ('populated' if resolved_job else 'unloaded')
    assert page['needs_render'] is (not resolved_job)


@pytest.mark.asyncio
async def test_agent_cooldown_is_unexecuted_and_does_not_replay_browser_diagnostics():
    class FailingBrowser(Browser):
        async def navigate_evidence(self, url, control):
            self.calls.append(url)
            raise TimeoutError()

        def diagnostics_for(self, url):
            return {"phase": "click", "call": len(self.calls)}

    browser = FailingBrowser()
    worker = CompanyEvidenceReader(Reader(b""), browser=browser, on_event=lambda *_: None, max_host_failures=2)
    worker.browser_remaining = 8
    for _ in range(3):
        assert await worker.read_agent_page(HOME, control={"label": "查看职位"}) is None
    first, second, skipped = worker.attempts
    assert [a["executed"] for a in worker.attempts] == [True, True, False]
    assert first["error_code"] == second["error_code"] == "browser_timeout"
    assert first["retryable"] is True and second["retryable"] is False
    assert skipped["error_code"] == "evidence_host_cooldown" and skipped["read_status"] == "not_executed"
    assert "browser_diagnostics" not in skipped and skipped["elapsed_ms"] == 0
    assert worker.failures[HOME] is second and len(browser.calls) == 2
    assert worker.host_failures[("nova.example", "browser")] == 2
    assert worker.browser_remaining == 6
    # HTTP is an independent transport, and a new round renews the browser limits.
    assert await worker.read_agent_page(HOME) is not None
    assert worker.tool_state()["host_cooldowns"] == [{"host": "nova.example", "method": "browser"}]
    worker.begin_round(browser_budget=8)
    assert not worker.attempts and not worker.failures and not worker.pages
    assert worker.tool_state()["host_cooldowns"] == []
    assert worker.browser_remaining == 8


@pytest.mark.asyncio
@pytest.mark.parametrize("condition,code", [
    ("budget", "evidence_browser_budget_exhausted"),
    ("unavailable", "evidence_browser_unavailable"),
    ("denied", "evidence_access_blocked"),
])
async def test_agent_unexecuted_reasons_do_not_mutate_network_failures(condition, code):
    browser = Browser()
    worker = evidence(Reader(b"", error=URLFetchError("private", code="source_http_error", status_code=403)),
                      None if condition == "unavailable" else browser)
    if condition == "budget":
        worker.browser_remaining = 0
    if condition == "denied":
        await worker.read_agent_page(HOME)
    failures = dict(worker.failures)
    assert await worker.read_agent_page(HOME, render=True) is None
    assert worker.attempts[-1]["error_code"] == code
    assert worker.attempts[-1]["executed"] is False
    assert worker.failures == failures and not browser.calls
    restored = evidence(Reader(b""), browser)
    restored.restore(worker.snapshot())
    assert restored.failures == failures


@pytest.mark.asyncio
async def test_agent_can_retry_transient_http_failure_but_cached_success_is_explicit():
    reader = Reader(b"<h1>public</h1>", error=TimeoutError())
    worker = evidence(reader)
    assert await worker.read_agent_page(HOME) is None
    reader.error = None
    first = await worker.read_agent_page(HOME)
    assert first is not None and not worker.failures
    assert await worker.read_agent_page(HOME) is first
    assert reader.calls == [HOME, HOME]
    assert worker.attempts[-1]["read_status"] == "cached"
    assert worker.attempts[-1]["executed"] is False
    assert worker.attempts[-1]["cached_at"] == first["checked_at"]
    restored = evidence(reader)
    restored.restore(worker.snapshot())
    assert restored.failures == {}


@pytest.mark.asyncio
async def test_concurrent_browser_calls_cannot_overspend_budget():
    browser = Browser()
    worker = evidence(Reader(b""), browser)
    results = await asyncio.gather(*(worker.read_agent_page(HOME + str(i), render=True) for i in range(3)))
    assert sum(p is not None for p in results) == len(browser.calls) == 1
    assert worker.browser_remaining == 0
    assert sum(a["executed"] is False for a in worker.attempts) == 2


@pytest.mark.asyncio
async def test_browser_cancellation_is_not_a_cached_failure_or_success():
    class Waiting:
        async def read_evidence(self, url):
            await asyncio.Event().wait()
    worker = evidence(Reader(b""), Waiting())
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(worker.read_agent_page(HOME, render=True), timeout=0.01)
    assert not worker.failures and not worker.pages and not worker.attempts


def test_legacy_unexecuted_cooldown_is_not_restored_as_a_network_failure():
    worker = evidence(Reader(b""))
    worker.restore({"read_cache_version": 1, "read_attempts": [
        {"url": HOME, "error_code": "evidence_host_cooldown", "checked_at": datetime.now(UTC).isoformat()}]})
    assert not worker.failures and not worker.host_failures
