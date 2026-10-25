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


def html_page(html, *, url, digest, method="http", text_limit=16000, collect_actions=False):
    parsed = parse_html_document(html)
    title_tag = re.search(r"<title\b[^>]*>(.*?)</title\s*>", html, re.IGNORECASE | re.DOTALL)
    title = unescape(re.sub(r"<[^>]+>", "", title_tag.group(1))).strip() if title_tag else parsed.title
    text = parsed.text[:text_limit]
    # Gate checks apply to small challenge pages, not articles discussing bots.
    if len(text) < 1200 and re.search(
        r"verify you are human|checking your browser|完成验证码|人机验证|access denied|just a moment", text, re.IGNORECASE
    ):
        raise URLReaderError("页面需要人工验证", code="evidence_human_gate")
    if len(text) < 1200 and re.search(
        r"^(?:无法显示此网页|无法显示此页|网页无法访问|页面不存在|404(?:\s|$)|page not found|service unavailable)",
        title or text, re.IGNORECASE,
    ):
        raise URLReaderError("来源返回错误页面", code="evidence_error_page")
    links = extract_html_links(html, base_url=url)[:200]
    result = {"url": url, "title": (title or "")[:500], "text": text,
            "links": links, "sha256": digest, "method": method,
            "needs_render": not links and len(text.strip()) < 100,
            "checked_at": datetime.now(UTC).isoformat()}
    if collect_actions:
        from src.services.campaign_entry import application_actions
        from src.services.recruitment_listing import inspect_listing
        result["application_actions"] = application_actions(html)
        capabilities = inspect_listing(html, url=url)
        # Keep short CTA labels bound to their own recruitment section.
        scoped = {link.url: link for link in (*capabilities.entries, *capabilities.jobs, *capabilities.outbound_jobs)}
        result["links"] = list({**{link.url: link for link in links}, **scoped}.values())[:200]
        result["needs_navigation"] = bool(capabilities.job_controls or capabilities.entry_controls)
        detail = bool(re.search(r"岗位职责|工作职责|任职要求|职位描述|responsibilities|qualifications", text, re.IGNORECASE))
        listing = bool(re.search(r"职位类别|职位分类|职能分类|在招职位|全部职位|岗位列表|职位列表", text)
                       and re.search(r"筛选|搜索|下一页|暂无|个职位|职位\s*[（(]?\d", text))
        empty = bool(re.search(r"暂无(?:相关)?(?:岗位|职位)|没有(?:相关)?(?:岗位|职位)|no (?:jobs|positions) found", text, re.IGNORECASE))
        result["listing_state"] = ("populated" if capabilities.jobs or capabilities.job_controls else
                                   "empty" if empty and not detail else "unloaded" if listing and not detail else None)
        result["needs_render"] |= result["listing_state"] in {"empty", "unloaded"}
        result["hiring_links"] = [link.url for link in scoped.values()]
        from src.services.campaign_navigation import navigation_candidate
        from src.services.job_url import canonical_job_url
        has_entry = any(canonical_job_url(link.url) != canonical_job_url(url)
                        and navigation_candidate(link.url, link.text)
                        for link in result["links"])
        if not detail and re.search(r"应届生招聘|校园招聘", text) and not has_entry:
            result["needs_navigation"] = True
    return result


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


def agent_read_feedback(attempts, offset, url, page):
    """Only this call's records may describe its execution; old errors are history."""
    attempt = next((a for a in reversed(attempts[offset:]) if a.get("url") == url), {})
    status = attempt.get("read_status") or ("success" if page else "failed" if attempt else "unknown")
    return {"code": "page_read" if page else attempt.get("error_code") or "read_failed",
            "url": url, "read_status": status, "executed": attempt.get("executed"),
            "retryable": attempt.get("retryable"),
            **{key: attempt[key] for key in ("blocked_by", "status_code", "cached_at") if key in attempt}}


class CompanyEvidenceReader:
    def __init__(self, reader, *, browser=None, on_event, text_limit=16000, collect_actions=False, max_host_failures=0):
        self.reader, self.browser, self.on_event = reader, browser, on_event
        self.pages, self.failures, self.attempts = {}, {}, []
        self.slots = asyncio.Semaphore(2)
        self.browser_remaining = 0
        self.browser_timeout = BROWSER_TIMEOUT
        self.text_limit = text_limit
        self.collect_actions = collect_actions
        self.max_host_failures, self.host_failures = max_host_failures, {}

    def cooling(self, url, method):
        return bool(self.max_host_failures and self.host_failures.get((urlsplit(url).hostname, method), 0) >= self.max_host_failures)

    def begin_round(self, *, browser_budget):
        """Renew execution limits; history is restored as navigation hints elsewhere."""
        self.pages.clear()
        self.failures.clear()
        self.attempts.clear()
        self.host_failures.clear()
        self.browser_remaining = browser_budget

    def access_blocked(self, url):
        failure = self.failures.get(url, {})
        return (failure.get("error_code") in {"evidence_human_gate", "unsafe_url"}
                or failure.get("status_code") in {401, 403, 429})

    def tool_state(self):
        return {"browser_available": hasattr(self.browser, "read_evidence"),
                "browser_remaining": self.browser_remaining,
                "host_cooldowns": [{"host": host, "method": method}
                    for (host, method), count in self.host_failures.items()
                    if self.max_host_failures and count >= self.max_host_failures],
                "blocked_urls": [{"url": url, "code": item.get("error_code"),
                                  "status_code": item.get("status_code")}
                                 for url, item in self.failures.items() if self.access_blocked(url)]}

    def record_unexecuted(self, url, method, code, *, cached=None):
        """Report this invocation without changing failures or copying old traces."""
        item = {"url": url, "method": method, "checked_at": datetime.now(UTC).isoformat(),
                "elapsed_ms": 0, "executed": False,
                "read_status": "cached" if cached else "not_executed",
                "error_code": None if cached else code, "retryable": False}
        if cached:
            item["cached_at"] = cached.get("checked_at")
        elif url in self.failures:
            item["blocked_by"] = {key: self.failures[url].get(key)
                                  for key in ("error_code", "status_code", "checked_at")}
        self.attempts.append(item)
        self.on_event("company_evidence_read", item)

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
        # Older snapshots used error_code for cooldowns, even though no request ran.
        latest = {}
        for item in self.attempts:
            if item.get("executed") is not False and item.get("error_code") != "evidence_host_cooldown":
                latest[item["url"]] = item
        for url, item in latest.items():
            if item.get("error_code") and fresh(item.get("checked_at"), 1):
                self.failures[url] = item
            else:
                self.failures.pop(url, None)

    def snapshot(self):
        pages = {page["url"]: page for page in self.pages.values()}
        return {"read_cache_version": CACHE_VERSION,
                "read_cache": [{**p, "links": [{"url": link.url, "text": link.text[:1200]} for link in p["links"]]}
                               for p in list(pages.values())[-MAX_CACHE_PAGES:]],
                "read_attempts": self.attempts[-40:]}

    async def read_agent_page(self, url, *, render=False, control=None):
        """Execute the agent's chosen transport without readiness heuristics."""
        if not render and control is None:
            return await self.read(url, allow_browser=False, retry_failed=True)
        async with self.slots:
            # Check inside the semaphore: concurrent callers must not overspend.
            code = ("evidence_access_blocked" if self.access_blocked(url) else
                    "evidence_browser_unavailable" if not hasattr(self.browser,
                        "navigate_evidence" if control is not None else "read_evidence") else
                    "evidence_browser_budget_exhausted" if self.browser_remaining <= 0 else
                    "evidence_host_cooldown" if self.cooling(url, "browser") else None)
            if code:
                self.record_unexecuted(url, "browser", code)
                return None
            self.browser_remaining -= 1
            started = monotonic()
            try:
                read = self.browser.navigate_evidence(url, control) if control is not None else self.browser.read_evidence(url)
                result = await asyncio.wait_for(read, timeout=self.browser_timeout)
                page = html_page(result.raw_html, url=result.final_url,
                    digest=hashlib.sha256(result.raw_html.encode()).hexdigest(), method="browser",
                    text_limit=self.text_limit, collect_actions=self.collect_actions)
                if self.collect_actions:
                    page["navigation_controls"] = list(getattr(result, "navigation_controls", ()))
                    page["navigation_result"] = (getattr(result, "dynamic_listing", None) or {}).get("reason")
                    page["application_actions"] = list(getattr(result, "application_actions", ()))
                    links = (*page["links"], *getattr(result, "discovered_links", ()),
                             *getattr(result, "discovered_entries", ()))
                    page["links"] = list({link.url: link for link in links}.values())
                page["redirect_chain"] = list(getattr(result, "redirect_chain", ()))
                self.record(url, "browser", started)
                self.pages[url] = self.pages[page["url"]] = page
                return page
            except (URLReaderError, BrowserReadError, TimeoutError, ValueError) as error:
                self.record(url, "browser", started, error)
                return None

    def record(self, url, method, started, error=None):
        item = {"url": url, "method": method, "checked_at": datetime.now(UTC).isoformat(),
                "elapsed_ms": round((monotonic() - started) * 1000),
                "executed": True, "read_status": "failed" if error else "success",
                "error_code": ("browser_timeout" if method == "browser" and isinstance(error, TimeoutError)
                               else failure_code(error)) if error else None,
                "status_code": getattr(error, "status_code", None)}
        if error:
            item["error_type"] = type(error).__name__
            item["cause_type"] = type(error.__cause__).__name__ if error.__cause__ else None
            item["reason"] = getattr(error, "reason", None) or getattr(error.__cause__, "reason", None)
        if method == "browser" and hasattr(self.browser, "diagnostics_for"):
            item["browser_diagnostics"] = self.browser.diagnostics_for(url)
        self.attempts.append(item)
        if error:
            self.failures[url] = item
        else:
            self.failures.pop(url, None)
        key = (urlsplit(url).hostname, method)
        if item["error_code"] != "evidence_host_cooldown":
            self.host_failures[key] = self.host_failures.get(key, 0) + 1 if error else 0
        item["retryable"] = (not self.access_blocked(url) and not self.cooling(url, method)
                             and (method != "browser" or self.browser_remaining > 0))
        self.on_event("company_evidence_read", item)

    async def read(self, url, *, allow_browser=True, force_browser=False, retry_failed=False):
        cached = self.pages.get(url)
        if cached and not force_browser and not (allow_browser and (cached.get("needs_render") or cached.get("needs_navigation"))):
            self.record_unexecuted(url, cached["method"], "page_cached", cached=cached)
            return cached
        page = cached
        async with self.slots:
            if not cached and url in self.failures:
                if retry_failed and not self.access_blocked(url):
                    # The Agent may retry transient failures within this round's limits.
                    # Keep the failure until an actual success replaces it.
                    retry = True
                else:
                    self.record_unexecuted(url, "http", "evidence_access_blocked" if self.access_blocked(url)
                                           else "evidence_previous_failure")
                    return None
            else:
                retry = False
            if not cached and (url not in self.failures or retry):
                started = monotonic()
                if self.cooling(url, "http"):
                    self.record_unexecuted(url, "http", "evidence_host_cooldown")
                    return None
                try:
                    response = await asyncio.wait_for(self.reader.fetch(url), timeout=READ_TIMEOUT)
                    if response.status_code >= 400:
                        raise URLReaderError("来源拒绝请求", code="source_http_error", status_code=response.status_code)
                    content_type = (response.content_type or "").lower()
                    if response.body.startswith(b"%PDF-") or "application/pdf" in content_type:
                        page = await asyncio.wait_for(asyncio.to_thread(pdf_page, response.body, url=response.final_url), timeout=4)
                    elif "html" in content_type or not content_type or content_type.startswith("text/"):
                        page = html_page(decode_html(response.body, content_type), url=response.final_url,
                                         digest=hashlib.sha256(response.body).hexdigest(), text_limit=self.text_limit,
                                         collect_actions=self.collect_actions)
                    else:
                        raise URLReaderError("不支持此证据格式", code="evidence_format_unsupported")
                    self.record(url, page["method"], started)
                    page["redirect_chain"] = list(getattr(response, "redirect_chain", ()))
                except (URLReaderError, TimeoutError, ValueError) as error:
                    self.record(url, "http", started, error)
            if page:
                self.pages[url] = self.pages[page["url"]] = page
            # Render only readable HTML shells or explicitly missing links.
            # Network errors, denials, unsafe URLs and human gates do not retry in a browser.
            if (page and page["method"] == "http" and (page.get("needs_render") or page.get("needs_navigation") or force_browser)
                    and url not in self.failures and allow_browser and self.browser_remaining > 0
                    and not self.cooling(url, "browser")
                    and hasattr(self.browser, "read_evidence")):
                self.browser_remaining -= 1
                started = monotonic()
                try:
                    result = await asyncio.wait_for(self.browser.read_evidence(url), timeout=self.browser_timeout)
                    page = html_page(result.raw_html, url=result.final_url,
                                     digest=hashlib.sha256(result.raw_html.encode()).hexdigest(), method="browser", text_limit=self.text_limit,
                                     collect_actions=self.collect_actions)
                    if self.collect_actions and hasattr(result, "application_actions"):
                        page["application_actions"] = list(result.application_actions)
                    if self.collect_actions:
                        observed = (*getattr(result, "discovered_links", ()), *getattr(result, "discovered_entries", ()))
                        existing = {link.url for link in page["links"]}
                        page["links"].extend(link for link in observed if link.url not in existing)
                        page["hiring_links"] = list(dict.fromkeys([*page.get("hiring_links", []), *(link.url for link in observed)]))
                        # Linkless cards become concrete links only after browser navigation.
                        # Reconcile readiness with that evidence instead of keeping the HTTP/DOM guess.
                        if getattr(result, "discovered_links", ()):
                            page["listing_state"] = "populated"
                            page["needs_render"] = False
                    page["redirect_chain"] = list(getattr(result, "redirect_chain", ()))
                    self.record(url, "browser", started)
                    self.pages[url] = self.pages[page["url"]] = page
                except (URLReaderError, BrowserReadError, TimeoutError, ValueError) as error:
                    self.record(url, "browser", started, error)
            return page
