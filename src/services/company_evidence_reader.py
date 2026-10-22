"""Bounded, format-aware reading of public company ownership evidence."""

from __future__ import annotations

import asyncio
import hashlib
import re
from datetime import UTC, datetime, timedelta
from html import unescape
from io import BytesIO
from time import monotonic
from urllib.parse import urlsplit

import httpx
from pypdf import PdfReader

from src.services.browser_job_reader import BrowserReadError
from src.services.url_reader import (
    HTMLLink,
    URLReaderError,
    extract_html_links,
    parse_html_document,
)

CACHE_VERSION = 1
READ_TIMEOUT = 10
BROWSER_TIMEOUT = 12
MAX_CACHE_PAGES = 12


def decode_html(body, content_type):
    """Honor declared encodings, then try common Chinese legacy encodings."""
    head = body[:4096].decode("ascii", errors="ignore")
    encodings = re.findall(r"charset\s*=\s*['\"]?([\w-]+)", (content_type or "") + " " + head, re.IGNORECASE)
    for encoding in [*encodings, "utf-8-sig", "gb18030", "big5"]:
        try:
            return body.decode(encoding)
        except (LookupError, UnicodeError):
            continue
    raise URLReaderError("页面编码无法识别", code="evidence_encoding_invalid")


def html_page(html, *, url, digest, method="http"):
    parsed = parse_html_document(html)
    title_tag = re.search(r"<title\b[^>]*>(.*?)</title\s*>", html, re.IGNORECASE | re.DOTALL)
    title = unescape(re.sub(r"<[^>]+>", "", title_tag.group(1))).strip() if title_tag else parsed.title
    text = parsed.text[:16000]
    # Gate checks apply to small challenge pages, not articles discussing bots.
    if len(text) < 1200 and re.search(
        r"verify you are human|checking your browser|完成验证码|人机验证|access denied|just a moment", text, re.IGNORECASE
    ):
        raise URLReaderError("页面需要人工验证", code="evidence_human_gate")
    links = extract_html_links(html, base_url=url)[:200]
    return {"url": url, "title": (title or "")[:500], "text": text,
            "links": links, "sha256": digest, "method": method,
            "needs_render": not links and len(text.strip()) < 100,
            "checked_at": datetime.now(UTC).isoformat()}


def pdf_page(body, *, url):
    """Only real PDF URI annotations count as links; plain text URLs do not."""
    try:
        document = PdfReader(BytesIO(body), strict=False)
        if document.is_encrypted:
            raise ValueError("encrypted")
        if len(document.pages) > 30:
            raise URLReaderError("PDF 页数超过核验预算", code="evidence_pdf_too_large")
        texts, links = [], []
        for page in document.pages:
            content = page.get_contents()
            if content and len(content.get_data()) > 2_000_000:
                raise URLReaderError("PDF 内容超过核验预算", code="evidence_pdf_too_large")
            page_text = (page.extract_text() or "")[:16000]
            texts.append(page_text)
            for ref in (page.get("/Annots") or [])[:200]:
                annotation = ref.get_object()
                action = annotation.get("/A")
                action = action.get_object() if action else {}
                uri = action.get("/URI") if action.get("/S") == "/URI" else None
                if uri and urlsplit(str(uri)).scheme in {"https", "http"}:
                    links.append(HTMLLink(url=str(uri), text=page_text[:1200]))
        text = "\n".join(texts)[:16000]
        if not text.strip():
            raise URLReaderError("PDF 没有可读取的文字", code="evidence_pdf_no_text")
        return {"url": url, "title": (document.metadata.title if document.metadata else "") or text[:200],
                "text": text, "links": links[:200], "sha256": hashlib.sha256(body).hexdigest(),
                "method": "pdf", "needs_render": False, "checked_at": datetime.now(UTC).isoformat()}
    except URLReaderError:
        raise
    except Exception as error:
        raise URLReaderError("PDF 解析失败", code="evidence_pdf_invalid") from error


def failure_code(error):
    if isinstance(error, TimeoutError):
        return "url_fetch_timeout"
    cause = error
    while cause is not None:
        if isinstance(cause, httpx.ConnectError):
            return "url_connection_failed"
        if isinstance(cause, OSError) and getattr(error, "code", "") == "unsafe_url":
            return "url_dns_failed"
        cause = cause.__cause__
    return getattr(error, "code", "evidence_read_failed")


def fresh(timestamp, hours):
    try:
        checked = datetime.fromisoformat(timestamp)
        if checked.tzinfo is None:
            checked = checked.replace(tzinfo=UTC)
        return timedelta(0) <= datetime.now(UTC) - checked < timedelta(hours=hours)
    except (ValueError, TypeError):
        return False


class CompanyEvidenceReader:
    def __init__(self, reader, *, browser=None, on_event):
        self.reader, self.browser, self.on_event = reader, browser, on_event
        self.pages, self.failures, self.attempts = {}, {}, []
        self.slots = asyncio.Semaphore(2)
        self.browser_remaining = 0

    def restore(self, evidence):
        if evidence.get("read_cache_version") != CACHE_VERSION:
            return
        for item in evidence.get("read_cache", [])[:MAX_CACHE_PAGES]:
            if fresh(item.get("checked_at"), 24 * 7):
                page = {**item, "links": [HTMLLink(**link) for link in item.get("links", [])[:200]]}
                self.pages.setdefault(page["url"], page)
        for item in evidence.get("read_attempts", [])[-40:]:
            if item not in self.attempts:
                self.attempts.append(item)
            if item.get("error_code") and fresh(item.get("checked_at"), 1):
                self.failures.setdefault(item["url"], item)

    def snapshot(self):
        pages = {page["url"]: page for page in self.pages.values()}
        return {"read_cache_version": CACHE_VERSION,
                "read_cache": [{**p, "links": [{"url": link.url, "text": link.text[:1200]} for link in p["links"]]}
                               for p in list(pages.values())[-MAX_CACHE_PAGES:]],
                "read_attempts": self.attempts[-40:]}

    def record(self, url, method, started, error=None):
        item = {"url": url, "method": method, "checked_at": datetime.now(UTC).isoformat(),
                "elapsed_ms": round((monotonic() - started) * 1000),
                "error_code": failure_code(error) if error else None,
                "status_code": getattr(error, "status_code", None)}
        self.attempts.append(item)
        if error:
            self.failures[url] = item
        else:
            self.failures.pop(url, None)
        self.on_event("company_evidence_read", item)

    async def read(self, url, *, allow_browser=True, force_browser=False):
        cached = self.pages.get(url)
        if cached and not force_browser and not (allow_browser and cached.get("needs_render")):
            return cached
        page = cached
        async with self.slots:
            if not cached and url not in self.failures:
                started = monotonic()
                try:
                    response = await asyncio.wait_for(self.reader.fetch(url), timeout=READ_TIMEOUT)
                    if response.status_code >= 400:
                        raise URLReaderError("来源拒绝请求", code="source_http_error", status_code=response.status_code)
                    content_type = (response.content_type or "").lower()
                    if response.body.startswith(b"%PDF-") or "application/pdf" in content_type:
                        page = await asyncio.wait_for(asyncio.to_thread(pdf_page, response.body, url=response.final_url), timeout=4)
                    elif "html" in content_type or not content_type or content_type.startswith("text/"):
                        page = html_page(decode_html(response.body, content_type), url=response.final_url,
                                         digest=hashlib.sha256(response.body).hexdigest())
                    else:
                        raise URLReaderError("不支持此证据格式", code="evidence_format_unsupported")
                    self.record(url, page["method"], started)
                except (URLReaderError, TimeoutError, ValueError) as error:
                    self.record(url, "http", started, error)
            if page:
                self.pages[url] = self.pages[page["url"]] = page
            # Render only readable HTML shells or explicitly missing links.
            # Network errors, denials, unsafe URLs and human gates do not retry in a browser.
            if (page and page["method"] == "http" and (page.get("needs_render") or force_browser)
                    and url not in self.failures and allow_browser and self.browser_remaining > 0
                    and hasattr(self.browser, "read_evidence")):
                self.browser_remaining -= 1
                started = monotonic()
                try:
                    result = await asyncio.wait_for(self.browser.read_evidence(url), timeout=BROWSER_TIMEOUT)
                    page = html_page(result.raw_html, url=result.final_url,
                                     digest=hashlib.sha256(result.raw_html.encode()).hexdigest(), method="browser")
                    self.record(url, "browser", started)
                    self.pages[url] = self.pages[page["url"]] = page
                except (URLReaderError, BrowserReadError, TimeoutError, ValueError) as error:
                    self.record(url, "browser", started, error)
            return page
