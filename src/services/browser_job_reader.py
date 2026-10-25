from __future__ import annotations

import asyncio
import base64
import json
import re
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from html.parser import HTMLParser
from typing import Protocol
from urllib.parse import parse_qs, urljoin, urlsplit

from src.services.browser_read_trace import BrowserReadTrace
from src.services.url_reader import URLReaderError, URLSafetyChecker


class BrowserReadError(RuntimeError):
    def __init__(self, message: str, *, code: str = "browser_read_failed") -> None:
        super().__init__(message)
        self.code = code


def declared_static_resource_host(url, *, resource_type, declared_urls):
    """A page may load declared assets from public CDN infrastructure via its proxy.

    This is transport permission for scripts/styles only, never employer trust
    or permission for arbitrary API hosts. Other resources retain DNS checks.
    """
    try:
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        port = parsed.port
    except ValueError:
        return None
    if (resource_type not in {"script", "stylesheet"} or url not in declared_urls
            or parsed.scheme != "https" or parsed.username or parsed.password
            or port not in {None, 443}):
        return None
    if any(host.endswith("." + suffix) for suffix in (
        "cdn.bcebos.com", "alicdn.com", "feishucdn.com",
    )):
        return host
    return None


def static_resource_declarations(html, base):
    class Resources(HTMLParser):
        def __init__(self):
            super().__init__()
            self.urls = []

        def handle_starttag(self, tag, attrs):
            values = dict(attrs)
            target = values.get("src") if tag == "script" else values.get("href") if (
                tag == "link" and values.get("rel") in {"stylesheet", "preload"}
            ) else None
            if target:
                self.urls.append(urljoin(base, target))

    parser = Resources()
    parser.feed(html)
    return parser.urls


def recruitment_api_request(url, post_data):
    """Both Feishu portal variants are observed: JSON POST and query-string GET."""
    if post_data:
        return json.loads(post_data)
    if urlsplit(url).path != "/api/v1/search/job/posts":
        return {}
    query = parse_qs(urlsplit(url).query, keep_blank_values=True)
    result = {"keyword": query.get("keyword", [""])[0]}
    for key in ("offset", "limit"):
        value = query.get(key, [""])[0]
        result[key] = int(value) if value.isdigit() else None
    for key in ("location_code_list", "subject_id_list"):
        result[key] = [v for part in query.get(key, []) for v in part.split(",") if v]
    return result


async def top_level_navigation(request):
    # A popup's first request can precede Playwright's Frame object.
    try:
        return request.frame.parent_frame is None
    except Exception as error:  # noqa: BLE001 - only Playwright's initial navigation case qualifies
        # Playwright cannot expose a popup Frame until its first document request completes.
        # Some proxy transports omit Sec-Fetch-Dest. An iframe has an existing parent Frame;
        # arbitrary frame errors and non-document requests still receive no entry permission.
        return ("Frame for this navigation request is not available" in str(error)
                and request.is_navigation_request() and request.resource_type == "document"
                and await request.header_value("sec-fetch-dest") in {None, "document"})


@dataclass(frozen=True)
class BrowserPageSnapshot:
    requested_url: str
    final_url: str
    title: str
    raw_html: str
    visible_text: str
    additional_pages: tuple[tuple[str, str], ...] = ()
    screenshots: tuple[dict, ...] = ()
    screenshot_error: str | None = None
    html_compacted: bool = False
    recruitment_api: tuple[dict, ...] = ()
    discovered_links: tuple = ()
    dynamic_listing: dict | None = None
    discovered_entries: tuple = ()
    redirect_chain: tuple[dict, ...] = ()
    application_actions: tuple[str, ...] = ()
    navigation_controls: tuple[dict, ...] = ()


class BrowserJobReader(Protocol):
    async def read(self, url: str) -> BrowserPageSnapshot:
        ...


class PlaywrightBrowserJobReader:
    """Read public pages and explicit listing pagination; never signs in or applies."""

    def __init__(
        self,
        *,
        safety_checker: URLSafetyChecker | None = None,
        timeout_seconds: float = 20.0,
        max_chars: int = 500_000,
    ) -> None:
        from src.config import get_settings
        from src.services.company_registry import enabled_company_source_hosts

        settings = get_settings()
        self.proxy = settings.url_fetch_proxy
        self.safety_checker = safety_checker or URLSafetyChecker(
            proxy_url=self.proxy,
            proxy_allowed_hosts=enabled_company_source_hosts(),
            proxy_allow_unlisted_hosts=settings.url_fetch_proxy_allow_unlisted_hosts,
        )
        self.timeout_ms = max(1_000, min(60_000, int(timeout_seconds * 1000)))
        self.max_chars = max(20_000, min(2_000_000, max_chars))
        self._shared_browser = None
        self._playwright = None
        self._reuse = False
        self._launch_lock = asyncio.Lock()
        self._read_traces = {}

    def diagnostics_for(self, url):
        trace = self._read_traces.get(url)
        return trace.snapshot() if trace else None

    @asynccontextmanager
    async def reuse(self):
        """One browser per search run; every page retains its own context."""
        if self._reuse:
            raise RuntimeError("Browser reuse scopes cannot overlap")
        self._reuse = True
        try:
            yield self
        finally:
            self._reuse = False
            try:
                if self._shared_browser is not None:
                    await self._shared_browser.close()
            finally:
                self._shared_browser = None
                if self._playwright is not None:
                    await self._playwright.stop()
                    self._playwright = None

    @asynccontextmanager
    async def browser_session(self):
        from playwright.async_api import async_playwright

        def options():
            result = {"headless": True}
            if self.proxy:
                url = urlsplit(self.proxy)
                proxy = {"server": f"{url.scheme}://{url.hostname}:{url.port}"}
                if url.username:
                    proxy["username"] = url.username
                if url.password:
                    proxy["password"] = url.password
                result["proxy"] = proxy
            return result

        if not self._reuse:
            async with async_playwright() as runtime:
                browser = await runtime.chromium.launch(**options())
                try:
                    yield browser
                finally:
                    await browser.close()
            return
        async with self._launch_lock:
            if self._shared_browser is None:
                self._playwright = await async_playwright().start()
                try:
                    self._shared_browser = await self._playwright.chromium.launch(**options())
                except BaseException:
                    await self._playwright.stop()
                    self._playwright = None
                    raise
        yield self._shared_browser

    async def read(self, url: str) -> BrowserPageSnapshot:
        return await self._read(url)

    async def read_evidence(self, url: str) -> BrowserPageSnapshot:
        """Read a public ownership page without job-specific waits or vision calls."""
        return await self._read(url, evidence_page=True)

    async def read_listing(self, url, *, max_pages=3, record_snapshot=None):
        return await self._read(url, listing_pages=max_pages, record_snapshot=record_snapshot)

    async def read_search_listing(self, url):
        return await self._read(url, listing_pages=1, capture_api=True)

    async def read_campaign_page(self, url):
        """Read public recruitment evidence, resolving one linkless navigation control."""
        return await self._read(url, capture_api=True, campaign_controls=True)

    async def read_agent_page(self, url, *, control=None):
        """Render without choosing navigation; execute only a previously observed control."""
        if control is not None:
            return await self._read(url, capture_api=True, dynamic_listing={
                "selected_control": control, "max_links": 1, "restore_after_navigation": False,
            })
        return await self._read(url, capture_api=True, agent_controls=True)

    async def read_dynamic_listing(self, url, *, cursor=None, keywords=(), max_links=8):
        return await self._read(url, capture_api=True, dynamic_listing={
            "cursor": cursor, "keywords": keywords, "max_links": max_links,
        })

    async def _read(self, url, *, listing_pages=1, record_snapshot=None, capture_api=False, evidence_page=False, dynamic_listing=None, campaign_controls=False, agent_controls=False):
        trace = BrowserReadTrace(url)
        self._read_traces[url] = trace
        while len(self._read_traces) > 30:
            self._read_traces.pop(next(iter(self._read_traces)))
        trace.phase("validate_url")
        try:
            result = await self._read_page(url, listing_pages=listing_pages, record_snapshot=record_snapshot,
                capture_api=capture_api, evidence_page=evidence_page, dynamic_listing=dynamic_listing,
                campaign_controls=campaign_controls, agent_controls=agent_controls, trace=trace)
        except BaseException as error:
            trace.finish("cancelled" if isinstance(error, asyncio.CancelledError) else "failed", type(error).__name__)
            raise
        trace.finish("success")
        return result

    async def _read_page(self, url, *, listing_pages, record_snapshot, capture_api, evidence_page, dynamic_listing, campaign_controls, trace, agent_controls=False):
        requested_url = await self._validate_url(url)
        try:
            from playwright.async_api import TimeoutError as PlaywrightTimeoutError
        except ImportError as error:
            raise BrowserReadError(
                "服务端未安装 Playwright 浏览器运行时",
                code="browser_runtime_unavailable",
            ) from error

        try:
            trace.phase("launch_browser")
            async with self.browser_session() as browser:
                trace.phase("create_context")
                context = await browser.new_context(
                    java_script_enabled=True,
                    accept_downloads=False,
                    service_workers="block",
                )
                api_records, api_tasks = [], []
                resource_documents = {}
                try:
                    page = await context.new_page()
                    page._jobflow_trace = trace
                    context.on("requestfailed", lambda request: trace.event("request_failed", request.url,
                        resource_type=request.resource_type, failure=(request.failure or "unknown").split()[0][:80]))
                    context.on("response", lambda response: trace.event("http_error", response.url,
                        status=response.status, resource_type=response.request.resource_type) if response.status >= 400 else None)

                    async def capture_response(response):
                        from src.services.recruitment_context import captures_detail_api

                        parsed = urlsplit(response.url)
                        detail_api = captures_detail_api(response.url, requested_url)
                        if not detail_api and (parsed.hostname != urlsplit(requested_url).hostname or not (
                            parsed.path == "/api/v1/search/job/posts"
                            or re.fullmatch(r"/api/v1/config/job/filters/\d+", parsed.path)
                        )) or response.status != 200:
                            return
                        try:
                            raw = await response.text()
                            if len(raw) > self.max_chars * 4:
                                return
                            payload = json.loads(raw)
                            request = recruitment_api_request(response.url, response.request.post_data)
                        except Exception:  # noqa: BLE001 - response may be cancelled with the page
                            return
                        api_records.append({
                            "url": response.url if detail_api else f"{parsed.scheme}://{parsed.netloc}{parsed.path}",
                            "request": request, "payload": payload,
                        })

                    from src.services.recruitment_context import oppo_detail_api
                    from src.services.recruitment_templates import alibaba_job_id

                    if capture_api or oppo_detail_api(requested_url) or alibaba_job_id(requested_url):
                        page.on("response", lambda response: api_tasks.append(
                            asyncio.create_task(capture_response(response))
                        ))

                    async def guard_request(route) -> None:
                        request_url = route.request.url
                        if (dynamic_listing is not None or campaign_controls) and route.request.is_navigation_request():
                            from src.services.recruitment_listing import (
                                allowed_entry_navigation,
                                allowed_listing_url,
                                listing_document_url,
                            )

                            entry_mode = getattr(page, "_jobflow_entry_navigation", False)
                            is_top_level = await top_level_navigation(route.request)
                            entry_navigation = entry_mode and is_top_level
                            navigation_url = listing_document_url(request_url, requested_url)
                            allowed = (allowed_entry_navigation(navigation_url, requested_url) if entry_navigation
                                       else allowed_listing_url(navigation_url, requested_url))
                            if campaign_controls and is_top_level and (navigation_url == requested_url or
                                    getattr(page, '_jobflow_announcement_navigation', False)):
                                allowed |= allowed_listing_url(navigation_url, requested_url, allow_documents=True)
                            if route.request.method != "GET" or not allowed:
                                trace.event("blocked", request_url, reason="navigation_scope", resource_type=route.request.resource_type,
                                            entry_mode=entry_mode, top_level=is_top_level,
                                            fetch_destination=await route.request.header_value("sec-fetch-dest"),
                                            permitted_entry=allowed_entry_navigation(navigation_url, requested_url))
                                await route.abort()
                                return
                        if urlsplit(request_url).scheme not in {"http", "https"}:
                            await route.abort()
                            return
                        try:
                            await resource_checker.validate(request_url)
                        except Exception as validation_error:  # noqa: BLE001 - block unsafe subresources
                            host = None
                            # Some configured proxies resolve public CDNs remotely.
                            # Admit only a script/style actually declared in this
                            # rendered document, on known public CDN infrastructure.
                            if capture_api and self.proxy and route.request.method == "GET" and route.request.resource_type in {"script", "stylesheet"}:
                                try:
                                    frame = route.request.frame
                                    if urlsplit(frame.url).netloc == urlsplit(requested_url).netloc:
                                        declared = await frame.evaluate("() => [...document.querySelectorAll('script[src],link[rel=stylesheet][href],link[rel=preload][href]')].map(e => e.src || e.href)")
                                        if request_url not in declared and declared_static_resource_host(request_url, resource_type=route.request.resource_type, declared_urls=[request_url]):
                                            # The preload scanner can request scripts
                                            # before their nodes enter the DOM. Read the
                                            # same public document to bind those URLs.
                                            async def declarations(document_url):
                                                from src.services.url_reader import (
                                                    SafeHTTPReader,
                                                )

                                                response = await SafeHTTPReader(
                                                    safety_checker=self.safety_checker,
                                                    proxy=self.proxy, timeout_seconds=6, max_retries=0,
                                                ).fetch(document_url)
                                                if urlsplit(response.final_url).netloc != urlsplit(document_url).netloc:
                                                    return []
                                                return static_resource_declarations(response.body.decode("utf-8", errors="replace"), response.final_url)

                                            if frame.url not in resource_documents:
                                                resource_documents[frame.url] = asyncio.create_task(declarations(frame.url))
                                            declared = [*declared, *await resource_documents[frame.url]]
                                        host = declared_static_resource_host(request_url, resource_type=route.request.resource_type, declared_urls=declared)
                                    if host:
                                        await URLSafetyChecker(proxy_url=self.proxy, proxy_allowed_hosts={host}).validate(request_url)
                                except Exception:  # noqa: BLE001 - an unreadable declaration grants nothing
                                    host = None
                            if not host:
                                trace.event("blocked", request_url, reason=getattr(validation_error, "reason", None) or getattr(validation_error, "code", "validation_failed"),
                                            resource_type=route.request.resource_type)
                                await route.abort()
                                return
                        await route.continue_()

                    # Exact public CDN hosts observed on these recruiting pages.
                    # Keep URL validation for every request, including redirects.
                    resource_hosts = recruitment_resource_hosts(requested_url)
                    if resource_hosts and self.proxy:
                        resource_checker = URLSafetyChecker(
                            proxy_url=self.proxy,
                            proxy_allowed_hosts=enabled_resource_hosts() | resource_hosts | set(getattr(self.safety_checker, "proxy_allowed_hosts", ())),
                            proxy_allow_unlisted_hosts=getattr(self.safety_checker, "proxy_allow_unlisted_hosts", False),
                        )
                    else:
                        resource_checker = self.safety_checker
                    await context.route("**/*", guard_request)
                    trace.phase("document_navigation")
                    response = await page.goto(
                        requested_url,
                        wait_until="domcontentloaded",
                        timeout=self.timeout_ms,
                    )
                    redirect_chain = []
                    request = response.request if response is not None else None
                    while request is not None and request.redirected_from is not None:
                        previous = request.redirected_from
                        previous_response = await previous.response()
                        redirect_chain.insert(0, {"url": previous.url,
                            "status": previous_response.status if previous_response else None,
                            "target": request.url})
                        request = previous
                    if evidence_page:
                        if response is not None and response.status >= 400:
                            raise BrowserReadError("核验页面拒绝读取", code="evidence_http_error")
                        try:
                            await page.wait_for_function(
                                "() => document.body && document.body.innerText.trim().length > 100 && document.querySelector('a[href]')",
                                timeout=min(self.timeout_ms, 3000),
                            )
                        except PlaywrightTimeoutError:
                            pass  # Preserve the DOM actually observed, even when sparse.
                    else:
                        trace.phase("wait_recruitment_content")
                        await wait_for_recruitment_content(page, timeout_ms=min(self.timeout_ms, 8000), listing=listing_pages > 1 or capture_api,
                                                          campaign=campaign_controls or agent_controls)
                    if not page.url.startswith(("https://", "http://")):
                        raise BrowserReadError("页面初始化后离开公开招聘网址，无法继续读取", code="browser_navigation_unavailable")
                    if dynamic_listing is not None:
                        from src.services.dynamic_recruitment_listing import (
                            read_dynamic_listing_page,
                        )

                        trace.phase("dynamic_navigation")
                        return await read_dynamic_listing_page(page, reader=self, **dynamic_listing)
                    trace.phase("read_dom")
                    final_url = await self._validate_url(page.url)
                    visible_text = await page.locator("body").inner_text(
                        timeout=self.timeout_ms
                    )
                    _raise_for_human_gate(visible_text)
                    raw_html, html_compacted = await bounded_page_html(page, max_chars=self.max_chars)
                    navigation_controls = []
                    if agent_controls:
                        from src.services.dynamic_recruitment_listing import CONTROLS
                        controls = await page.evaluate(CONTROLS)
                        navigation_controls = [{"kind": kind, **control}
                            for kind in ("entries", "cards", "navigation") for control in controls[kind]][:60]
                    if campaign_controls:
                        trace.phase("inspect_navigation_controls")
                        from src.services.dynamic_recruitment_listing import (
                            ANNOUNCEMENT_CONTROL,
                            CONTROLS,
                            read_dynamic_listing_page,
                        )
                        from src.services.lead_presentation import discovery_kind
                        from src.services.recruitment_listing import inspect_listing

                        capabilities = inspect_listing(raw_html, url=final_url)
                        controls = await page.evaluate(CONTROLS)
                        notices = None
                        notice_pattern = ANNOUNCEMENT_CONTROL
                        if discovery_kind(final_url) != "job" and any(re.search(notice_pattern, c["label"]) for c in controls["entries"]):
                            index_pattern = r'^(?:校招|招聘)(?:公告|简章)$'
                            notice_filter = index_pattern if any(re.search(index_pattern, c['label']) for c in controls['entries']) else notice_pattern
                            notices = await read_dynamic_listing_page(page, reader=self, keywords=("校招",),
                                max_links=4, entry_filter=notice_filter, allow_documents=True)
                        if not capabilities.jobs and not capabilities.outbound_jobs and discovery_kind(final_url) != "job":
                            trace.event("controls", page.url, cards=len(controls["cards"]),
                                        entries=[c["label"][:100] for c in controls["entries"][:8]])
                            if controls["cards"] or any(not notices or not re.search(notice_pattern, c['label']) for c in controls['entries']):
                                trace.phase("dynamic_navigation")
                                snapshot = await read_dynamic_listing_page(page, reader=self, keywords=("校招",),
                                                                          max_links=1, restore_after_navigation=False,
                                                                          exclude_entry_filter=notice_pattern if notices else None,
                                                                          allow_documents=True)
                                return replace(snapshot, discovered_entries=tuple(dict.fromkeys(
                                    [*(notices.discovered_entries if notices else ()), *snapshot.discovered_entries])))
                        if notices:
                            return notices
                    if html_compacted and len(visible_text) > self.max_chars:
                        from src.services.url_reader import parse_html_document
                        visible_text = parse_html_document(raw_html).text
                    screenshots = []
                    screenshot_error = None
                    from src.config import get_settings
                    from src.services.job_detail_scope import closed_page_notice
                    from src.services.vision_job_extraction import needs_visual_fallback
                    if not evidence_page and not capture_api and listing_pages == 1 and get_settings().vision_fallback_enabled and not closed_page_notice(raw_html, url=final_url) and needs_visual_fallback(raw_html, final_url):
                        try:
                            await page.set_viewport_size({"width": 1280, "height": 1000})
                            height = await page.evaluate("document.documentElement.scrollHeight")
                            # Bounded overlapping viewports preserve legibility on long JDs.
                            for offset in range(0, min(height, 4600), 900):
                                await page.evaluate("y => window.scrollTo(0, y)", offset)
                                data = await page.screenshot(type="jpeg", quality=80, timeout=self.timeout_ms)
                                screenshots.append({"base64": base64.b64encode(data).decode("ascii"), "offset": offset, "page_height": height, "coverage_limited": height > 4600})
                        except Exception as error:  # noqa: BLE001 - retain readable DOM when screenshot capture fails
                            screenshot_error = type(error).__name__
                    additional_pages = []
                    if record_snapshot:
                        record_snapshot(final_url, raw_html)
                    previous = visible_text
                    for _ in range(max(0, min(listing_pages, 3)-1)):
                        from src.services.lead_presentation import discovery_kind
                        from src.services.url_reader import extract_html_links
                        current_html, _ = await bounded_page_html(page, max_chars=self.max_chars)
                        if not any(discovery_kind(link.url, link.text, observed_title=True) == "job" for link in extract_html_links(current_html, base_url=page.url)):
                            break
                        # Only unambiguous public pagination controls, never form
                        # submissions or arbitrary "continue"/"apply" buttons.
                        next_page = page.get_by_role("button", name=re.compile(r"^(下一页|下页|加载更多|更多职位|Next|Load more)$", re.IGNORECASE))
                        if await next_page.count() != 1 or not await next_page.is_visible() or not await next_page.is_enabled():
                            break
                        if await next_page.get_attribute("aria-disabled") == "true":
                            break
                        if await next_page.get_attribute("type") == "submit":
                            break
                        await next_page.click(timeout=self.timeout_ms)
                        try:
                            await page.wait_for_function("old => document.body.innerText !== old", arg=previous, timeout=5000)
                        except PlaywrightTimeoutError:
                            break
                        await wait_for_recruitment_content(page, timeout_ms=5000, listing=True)
                        page_url = await self._validate_url(page.url)
                        previous = await page.locator("body").inner_text(timeout=self.timeout_ms)
                        _raise_for_human_gate(previous)
                        page_html, page_compacted = await bounded_page_html(page, max_chars=self.max_chars)
                        if page_compacted and len(previous) > self.max_chars:
                            from src.services.url_reader import parse_html_document
                            previous = parse_html_document(page_html).text
                        if len(previous) > self.max_chars:
                            raise BrowserReadError("浏览器可见内容超过大小限制", code="browser_response_too_large")
                        if record_snapshot:
                            record_snapshot(page_url, page_html)
                        additional_pages.append((page_url, page_html))
                    if (
                        len(raw_html) > self.max_chars
                        or len(visible_text) > self.max_chars
                    ):
                        raise BrowserReadError(
                            "浏览器页面内容超过大小限制",
                            code="browser_response_too_large",
                        )
                    if api_tasks:
                        trace.phase("capture_api_responses", pending=sum(not task.done() for task in api_tasks))
                        await asyncio.gather(*api_tasks, return_exceptions=True)
                    application_actions = []
                    trace.phase("application_controls")
                    if capture_api:
                        from src.services.campaign_entry import (
                            APPLICATION_CONTROLS,
                            APPLY_LABEL,
                            INTENT_LABEL,
                        )
                        application_actions = [label for label in await page.evaluate(APPLICATION_CONTROLS)
                                               if APPLY_LABEL.fullmatch(label) or INTENT_LABEL.fullmatch(label)]
                    return BrowserPageSnapshot(
                        requested_url=requested_url,
                        final_url=final_url,
                        title=await page.title(),
                        raw_html=raw_html,
                        visible_text=visible_text,
                        additional_pages=tuple(additional_pages),
                        screenshots=tuple(screenshots),
                        screenshot_error=screenshot_error,
                        html_compacted=html_compacted,
                        recruitment_api=tuple(api_records),
                        redirect_chain=tuple(redirect_chain),
                        application_actions=tuple(application_actions),
                        navigation_controls=tuple(navigation_controls),
                    )
                finally:
                    # Record the active stage before cleanup obscures a cancellation/exception.
                    if sys.exc_info()[0] is not None:
                        trace.failure_phase = trace.current_phase
                    trace.phase("cleanup")
                    for task in resource_documents.values():
                        if not task.done():
                            task.cancel()
                    if resource_documents:
                        await asyncio.gather(*resource_documents.values(), return_exceptions=True)
                    for task in api_tasks:
                        if not task.done():
                            task.cancel()
                    if api_tasks:
                        await asyncio.gather(*api_tasks, return_exceptions=True)
                    await context.close()
        except BrowserReadError:
            raise
        except Exception as error:
            message = str(error)
            code = (
                "browser_timeout"
                if "Timeout" in type(error).__name__ or "Timeout" in message
                else "browser_read_failed"
            )
            raise BrowserReadError("浏览器无法读取岗位页面", code=code) from error

    async def _validate_url(self, url: str) -> str:
        try:
            return await self.safety_checker.validate(url)
        except URLReaderError as error:
            raise BrowserReadError(str(error), code=error.code) from error


async def bounded_page_html(page, *, max_chars):
    """Keep DOM evidence and links, while bounding serialized page payloads.

    Inline bundles, styles and SVG paths are not JD evidence. Preserve original
    HTML when small; explicitly mark compact snapshots and reject large DOMs.
    """
    result = await page.evaluate(r"""limit => {
        const html = document.documentElement.outerHTML;
        if (html.length <= limit) return {html, compacted: false};
        if (document.getElementsByTagName('*').length > 30000) return null;
        const copy = document.documentElement.cloneNode(true);
        const originals = document.documentElement.querySelectorAll('*');
        const clones = copy.querySelectorAll('*');
        originals.forEach((el, i) => {
            const style = getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden') clones[i].setAttribute('hidden', '');
        });
        copy.querySelectorAll('script,style,svg,canvas,iframe').forEach(el => {
            if (el.tagName === 'SCRIPT' && /application\/(ld\+json|json\+ld)/i.test(el.type)) return;
            el.remove();
        });
        const attrs = new Set(['class','id','style','hidden','aria-hidden','aria-disabled','aria-label','aria-current','disabled','role','itemprop','href','type','rel','title']);
        for (const el of copy.querySelectorAll('*')) {
            for (const attr of [...el.attributes]) if (!attrs.has(attr.name)) el.removeAttribute(attr.name);
        }
        const compact = copy.outerHTML;
        if (compact.length <= limit) return {html: compact, compacted: true};
        // Preserve an entire unambiguous content region. Never slice a JD:
        // its final clauses may contain qualifications or exception paths.
        const regions = copy.querySelectorAll('main,[role="main"]');
        if (regions.length !== 1) return null;
        const region = regions[0];
        region.querySelectorAll('[hidden],[aria-hidden="true"]').forEach(el => el.remove());
        const relevant = /岗位职责|工作职责|任职要求|职位要求|responsibilities|qualifications/i.test(region.textContent || '')
            || region.querySelectorAll('a[href*="/job/"],a[href*="/jobs/"],a[href*="/position/"]').length > 1;
        if (!relevant) return null;
        const scoped = '<html><head>' + (copy.querySelector('title')?.outerHTML || '') + '</head><body>' + region.outerHTML + '</body></html>';
        return scoped.length <= limit ? {html: scoped, compacted: true} : null;
    }""", max_chars)
    if result is None:
        raise BrowserReadError("浏览器页面内容超过大小限制", code="browser_response_too_large")
    return result["html"], result["compacted"]


async def wait_for_recruitment_content(page, *, timeout_ms, listing=False, campaign=False):
    """Wait for meaningful job content and idle loading indicators, bounded."""
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError

    trace = getattr(page, "_jobflow_trace", None)
    if trace:
        trace.phase("wait_recruitment_ready", budget_ms=timeout_ms)
    try:
        await page.wait_for_function(r"""({listing,campaign}) => {
            const text = document.body?.innerText || '';
            const busy = [...document.querySelectorAll('[aria-busy="true"], [role="progressbar"]')]
                .some(el => el.getClientRects().length > 0);
            const detail = /职位描述|职位要求|任职要求|岗位描述|岗位要求|岗位职责|工作职责|(?:该|此|本)?(?:职位|岗位)已(?:下线|关闭|结束)|responsibilities|qualifications|job description|no longer accepting applications/i.test(text);
            const unresolved = /\{\{\s*(?:[$\w]+\.[\w.]+|\$t\([^}]*\))\s*\}\}/.test(text);
            const links = document.querySelector('a[href*="/job/"],a[href*="/jobs/"],a[href*="/position/"]');
            const cards = [...document.querySelectorAll('[class*="title"],[class*="name"]')].some(el =>
                el.getClientRects().length && /(?:job|post|position|pos|vacancy)/i.test(el.className || '') &&
                /工程师|研究员|开发|算法|实习生|engineer|developer|scientist/i.test(el.innerText || ''));
            const structural = [...document.querySelectorAll('span,h2,h3,h4')].some(el => {
                const title = (el.innerText || '').trim();
                if (!el.getClientRects().length || title.length > 140 ||
                    !/工程师|研究员|产品经理|engineer|developer|scientist/i.test(title)) return false;
                for(let p=el.parentElement,d=0;p && d<4;p=p.parentElement,d++) {
                    const content=(p.innerText || '').trim();
                    if (/(?:^|[\s_-])(?:item|card|row)(?:$|[\s_-])/i.test(p.className || '') &&
                        content.startsWith(title) && /工作地点|所属业务|岗位职责|工作职责|location|department/i.test(content)) return true;
                }
                return false;
            });
            const entries = [...document.querySelectorAll('button,[role="button"],p,a')].some(el =>
                el.getClientRects().length && !el.closest('form,[hidden],[aria-hidden="true"]') &&
                /^(?:(?:查看|浏览|全部|搜索|进入)(?:工作)?(?:\s*\d+\s*个?)?(?:职位|岗位)|校园招聘与实习|(?:view|browse|all|search)\s+(?:\d+\s+)?jobs)[\s→›»]*$/i.test((el.innerText || '').trim()));
            const campaignEntry = campaign && [...document.querySelectorAll('button,a,p,span,div,[role="button"],[role="link"]')].some(el => {
                if (!el.getClientRects().length || getComputedStyle(el).visibility === 'hidden' ||
                    el.closest('form,header,nav,[role="navigation"],[hidden],[aria-hidden="true"],[disabled],[aria-disabled="true"]') ||
                    [...function*(n) { while(n) { yield n; n=n.parentElement; } }(el)]
                        .some(n => /(?:^|[\s_-])(?:header\w*|nav|navbar|menu)(?:$|[\s_-])/i.test(n.className || ''))) return false;
                const label = (el.innerText || '').trim();
                const clickable = ['A','BUTTON'].includes(el.tagName) || ['button','link'].includes(el.getAttribute('role')) ||
                    getComputedStyle(el).cursor === 'pointer';
                return clickable && /^(?:(?:\d{4}届?\s*)?(?:校园招聘|应届生招聘|应届校招)(?:与实习)?|campus recruitment)[\s→›»]*$/i.test(label);
            });
            const announcement = campaign && /(?:校招|校园招聘|管培生).{0,180}(?:启动|开启)/.test(text);
            return !busy && !unresolved && (detail || (listing && (links || cards || structural || entries)) || campaignEntry || announcement);
        }""", arg={"listing": listing, "campaign": campaign}, timeout=timeout_ms)
        if trace:
            trace.phase("wait_dom_stable", budget_ms=min(timeout_ms, 3000))
        # A short quiet DOM window also catches delayed replacement of a shell.
        await page.wait_for_function("""() => {
            const text = document.body?.innerText || '';
            const now = Date.now();
            if (window.__jobflowText !== text) {
                window.__jobflowText = text; window.__jobflowChanged = now;
            }
            return now - window.__jobflowChanged >= 600;
        }""", timeout=min(timeout_ms, 3000))
    except PlaywrightTimeoutError:
        if trace:
            trace.event("wait_timeout", page.url, phase=trace.current_phase)
        return  # preserve whatever content was available at the deadline


def _raise_for_human_gate(text: str) -> None:
    folded = " ".join(text.casefold().split())
    gates = {
        "browser_login_required": ("登录后查看", "请登录", "sign in to continue"),
        "browser_captcha_required": ("captcha", "验证码", "人机验证"),
        "browser_2fa_required": ("two-factor", "2fa", "双重验证", "两步验证"),
        "browser_security_challenge": ("cloudflare", "security check", "安全检查"),
    }
    for code, markers in gates.items():
        if any(marker in folded for marker in markers):
            raise BrowserReadError("页面需要用户完成登录或安全验证", code=code)


def enabled_resource_hosts() -> set[str]:
    from src.services.company_registry import enabled_company_source_hosts
    return enabled_company_source_hosts() | {"g.alicdn.com", "lang.alicdn.com"}


def recruitment_resource_hosts(url: str) -> set[str]:
    host = urlsplit(url).hostname or ""
    from src.services.company_registry import enabled_company_sources
    registered = {resource for source in enabled_company_sources() if urlsplit(source.career_url).hostname == host for resource in source.resource_hosts}
    if registered:
        return registered
    if host.endswith((".jobs.feishu.cn", ".jobs.f.mioffice.cn")):
        return {"lf-package-cn.feishucdn.com"}
    return {
        "campus-talent.alibaba.com": {"g.alicdn.com", "lang.alicdn.com"},
        "jobs.bytedance.com": {"lf-package-cn.feishucdn.com"},
    }.get(urlsplit(url).hostname, set())
