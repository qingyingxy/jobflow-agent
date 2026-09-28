from __future__ import annotations

import base64
import re
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

    async def read(self, url: str) -> BrowserPageSnapshot:
        return await self._read(url)

    async def read_listing(self, url, *, max_pages=3, record_snapshot=None):
        return await self._read(url, listing_pages=max_pages, record_snapshot=record_snapshot)

    async def _read(self, url, *, listing_pages=1, record_snapshot=None):
        requested_url = await self._validate_url(url)
        try:
            from playwright.async_api import TimeoutError as PlaywrightTimeoutError
            from playwright.async_api import async_playwright
        except ImportError as error:
            raise BrowserReadError(
                "服务端未安装 Playwright 浏览器运行时",
                code="browser_runtime_unavailable",
            ) from error

        try:
            async with async_playwright() as playwright:
                launch_options = {"headless": True}
                if self.proxy:
                    proxy_url = urlsplit(self.proxy)
                    proxy = {"server": f"{proxy_url.scheme}://{proxy_url.hostname}:{proxy_url.port}"}
                    if proxy_url.username:
                        proxy["username"] = proxy_url.username
                    if proxy_url.password:
                        proxy["password"] = proxy_url.password
                    launch_options["proxy"] = proxy
                browser = await playwright.chromium.launch(**launch_options)
                try:
                    context = await browser.new_context(
                        java_script_enabled=True,
                        accept_downloads=False,
                        service_workers="block",
                    )
                    page = await context.new_page()

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

                    # Known static resources observed on the Alibaba careers page.
                    if urlsplit(requested_url).hostname == "campus-talent.alibaba.com" and self.proxy:
                        resource_checker = URLSafetyChecker(
                            proxy_url=self.proxy,
                            proxy_allowed_hosts=enabled_resource_hosts(),
                        )
                    else:
                        resource_checker = self.safety_checker
                    await page.route("**/*", guard_request)
                    await page.goto(
                        requested_url,
                        wait_until="domcontentloaded",
                        timeout=self.timeout_ms,
                    )
                    await wait_for_recruitment_content(page, timeout_ms=min(self.timeout_ms, 8000))
                    final_url = await self._validate_url(page.url)
                    visible_text = await page.locator("body").inner_text(
                        timeout=self.timeout_ms
                    )
                    _raise_for_human_gate(visible_text)
                    raw_html = await page.content()
                    screenshots = []
                    screenshot_error = None
                    from src.config import get_settings
                    from src.services.vision_job_extraction import needs_visual_fallback
                    if listing_pages == 1 and get_settings().vision_fallback_enabled and needs_visual_fallback(raw_html, final_url):
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
                        if not any(discovery_kind(link.url, link.text) == "job" for link in extract_html_links(await page.content(), base_url=page.url)):
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
                        await wait_for_recruitment_content(page, timeout_ms=5000)
                        page_url = await self._validate_url(page.url)
                        previous = await page.locator("body").inner_text(timeout=self.timeout_ms)
                        _raise_for_human_gate(previous)
                        page_html = await page.content()
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
                    return BrowserPageSnapshot(
                        requested_url=requested_url,
                        final_url=final_url,
                        title=await page.title(),
                        raw_html=raw_html,
                        visible_text=visible_text,
                        additional_pages=tuple(additional_pages),
                        screenshots=tuple(screenshots),
                        screenshot_error=screenshot_error,
                    )
                finally:
                    await browser.close()
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


async def wait_for_recruitment_content(page, *, timeout_ms):
    """Wait for meaningful job content and idle loading indicators, bounded."""
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError

    try:
        await page.wait_for_function("""() => {
            const text = document.body?.innerText || '';
            const busy = [...document.querySelectorAll('[aria-busy="true"], [role="progressbar"]')]
                .some(el => el.getClientRects().length > 0);
            return !busy && text.length > 100 && /职位|岗位|任职|招聘|responsibilit|qualification|jobs/i.test(text);
        }""", timeout=timeout_ms)
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
