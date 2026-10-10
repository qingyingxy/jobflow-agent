from __future__ import annotations

import asyncio
import base64
import json
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

from src.services.url_reader import URLReaderError, URLSafetyChecker


class BrowserReadError(RuntimeError):
    def __init__(self, message: str, *, code: str = "browser_read_failed") -> None:
        super().__init__(message)
        self.code = code


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
        )
        self.timeout_ms = max(1_000, min(60_000, int(timeout_seconds * 1000)))
        self.max_chars = max(20_000, min(2_000_000, max_chars))
        self._shared_browser = None
        self._playwright = None
        self._reuse = False
        self._launch_lock = asyncio.Lock()

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

    async def read_listing(self, url, *, max_pages=3, record_snapshot=None):
        return await self._read(url, listing_pages=max_pages, record_snapshot=record_snapshot)

    async def read_search_listing(self, url):
        return await self._read(url, listing_pages=1, capture_api=True)

    async def _read(self, url, *, listing_pages=1, record_snapshot=None, capture_api=False):
        requested_url = await self._validate_url(url)
        try:
            from playwright.async_api import TimeoutError as PlaywrightTimeoutError
        except ImportError as error:
            raise BrowserReadError(
                "服务端未安装 Playwright 浏览器运行时",
                code="browser_runtime_unavailable",
            ) from error

        try:
            async with self.browser_session() as browser:
                context = await browser.new_context(
                    java_script_enabled=True,
                    accept_downloads=False,
                    service_workers="block",
                )
                api_records, api_tasks = [], []
                try:
                    page = await context.new_page()

                    async def capture_response(response):
                        parsed = urlsplit(response.url)
                        if parsed.hostname != urlsplit(requested_url).hostname or not (
                            parsed.path == "/api/v1/search/job/posts"
                            or re.fullmatch(r"/api/v1/config/job/filters/\d+", parsed.path)
                        ) or response.status != 200:
                            return
                        try:
                            raw = await response.text()
                            if len(raw) > self.max_chars * 4:
                                return
                            payload = json.loads(raw)
                            request = json.loads(response.request.post_data or "{}")
                        except Exception:  # noqa: BLE001 - response may be cancelled with the page
                            return
                        api_records.append({
                            "url": f"{parsed.scheme}://{parsed.netloc}{parsed.path}",
                            "request": request, "payload": payload,
                        })

                    if capture_api:
                        page.on("response", lambda response: api_tasks.append(
                            asyncio.create_task(capture_response(response))
                        ))

                    async def guard_request(route) -> None:
                        request_url = route.request.url
                        if urlsplit(request_url).scheme not in {"http", "https"}:
                            await route.abort()
                            return
                        try:
                            await resource_checker.validate(request_url)
                        except Exception:  # noqa: BLE001 - block unsafe subresources
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
                        )
                    else:
                        resource_checker = self.safety_checker
                    await page.route("**/*", guard_request)
                    await page.goto(
                        requested_url,
                        wait_until="domcontentloaded",
                        timeout=self.timeout_ms,
                    )
                    await wait_for_recruitment_content(page, timeout_ms=min(self.timeout_ms, 8000), listing=listing_pages > 1 or capture_api)
                    final_url = await self._validate_url(page.url)
                    visible_text = await page.locator("body").inner_text(
                        timeout=self.timeout_ms
                    )
                    _raise_for_human_gate(visible_text)
                    raw_html, html_compacted = await bounded_page_html(page, max_chars=self.max_chars)
                    screenshots = []
                    screenshot_error = None
                    from src.config import get_settings
                    from src.services.job_detail_scope import closed_page_notice
                    from src.services.vision_job_extraction import needs_visual_fallback
                    if not capture_api and listing_pages == 1 and get_settings().vision_fallback_enabled and not closed_page_notice(raw_html, url=final_url) and needs_visual_fallback(raw_html, final_url):
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
                        if not any(discovery_kind(link.url, link.text) == "job" for link in extract_html_links(current_html, base_url=page.url)):
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
                        if len(previous) > self.max_chars:
                            raise BrowserReadError("浏览器可见内容超过大小限制", code="browser_response_too_large")
                        page_html, _ = await bounded_page_html(page, max_chars=self.max_chars)
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
                        await asyncio.gather(*api_tasks, return_exceptions=True)
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
                    )
                finally:
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
        const attrs = new Set(['class','id','style','hidden','aria-hidden','role','itemprop','href','type']);
        for (const el of copy.querySelectorAll('*')) {
            for (const attr of [...el.attributes]) if (!attrs.has(attr.name)) el.removeAttribute(attr.name);
        }
        const compact = copy.outerHTML;
        return compact.length <= limit ? {html: compact, compacted: true} : null;
    }""", max_chars)
    if result is None:
        raise BrowserReadError("浏览器页面内容超过大小限制", code="browser_response_too_large")
    return result["html"], result["compacted"]


async def wait_for_recruitment_content(page, *, timeout_ms, listing=False):
    """Wait for meaningful job content and idle loading indicators, bounded."""
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError

    try:
        await page.wait_for_function("""listing => {
            const text = document.body?.innerText || '';
            const busy = [...document.querySelectorAll('[aria-busy="true"], [role="progressbar"]')]
                .some(el => el.getClientRects().length > 0);
            const detail = /职位描述|职位要求|任职要求|岗位描述|岗位要求|岗位职责|工作职责|(?:该|此|本)?(?:职位|岗位)已(?:下线|关闭|结束)|responsibilities|qualifications|job description|no longer accepting applications/i.test(text);
            const links = document.querySelector('a[href*="/job/"],a[href*="/jobs/"],a[href*="/position/"]');
            return !busy && (detail || (listing && links));
        }""", arg=listing, timeout=timeout_ms)
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
