from __future__ import annotations

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


class BrowserJobReader(Protocol):
    async def read(self, url: str) -> BrowserPageSnapshot:
        ...


class PlaywrightBrowserJobReader:
    """Read one public dynamic page; never signs in or performs page actions."""

    def __init__(
        self,
        *,
        safety_checker: URLSafetyChecker | None = None,
        timeout_seconds: float = 20.0,
        max_chars: int = 500_000,
    ) -> None:
        self.safety_checker = safety_checker or URLSafetyChecker()
        self.timeout_ms = max(1_000, min(60_000, int(timeout_seconds * 1000)))
        self.max_chars = max(20_000, min(2_000_000, max_chars))

    async def read(self, url: str) -> BrowserPageSnapshot:
        requested_url = await self._validate_url(url)
        try:
            from playwright.async_api import async_playwright
        except ImportError as error:
            raise BrowserReadError(
                "服务端未安装 Playwright 浏览器运行时",
                code="browser_runtime_unavailable",
            ) from error

        try:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(headless=True)
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
                            await self.safety_checker.validate(request_url)
                        except Exception:  # noqa: BLE001 - block unsafe subresources
                            await route.abort()
                            return
                        await route.continue_()

                    await page.route("**/*", guard_request)
                    await page.goto(
                        requested_url,
                        wait_until="domcontentloaded",
                        timeout=self.timeout_ms,
                    )
                    await page.wait_for_timeout(750)
                    final_url = await self._validate_url(page.url)
                    visible_text = await page.locator("body").inner_text(
                        timeout=self.timeout_ms
                    )
                    _raise_for_human_gate(visible_text)
                    raw_html = await page.content()
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
