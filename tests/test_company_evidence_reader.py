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
