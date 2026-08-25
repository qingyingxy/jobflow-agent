from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from src.domain.ats_assistance import AtsProvider
from src.services.ats_adapters import (
    AtsBrowserExecutor,
    AtsFieldDescriptor,
    AtsFillOperation,
    AtsPageSnapshot,
    AtsPreparationResult,
    AtsSubmissionEvidence,
)
from src.services.url_reader import URLReaderError, URLSafetyChecker


class AtsBrowserError(RuntimeError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


class PlaywrightAtsBrowserExecutor(AtsBrowserExecutor):
    """Operate one supported public ATS form inside a guarded headless context."""

    def __init__(
        self,
        *,
        safety_checker: URLSafetyChecker | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.safety_checker = safety_checker or URLSafetyChecker()
        self.timeout_ms = max(2_000, min(60_000, int(timeout_seconds * 1000)))

    async def inspect(self, url: str) -> AtsPageSnapshot:
        return await self._run(url, self._inspect_page)

    async def prepare(
        self,
        *,
        url: str,
        provider: AtsProvider,
        operations: list[AtsFillOperation],
    ) -> AtsPreparationResult:
        async def prepare_page(page, requested_url: str) -> AtsPreparationResult:
            snapshot = await self._snapshot(page, requested_url)
            if snapshot.gates:
                return AtsPreparationResult(
                    page_fingerprint=snapshot.fingerprint,
                    filled_field_keys=(),
                    verification_issues=snapshot.gates,
                )
            filled, issues = await self._fill(page, operations)
            return AtsPreparationResult(
                page_fingerprint=snapshot.fingerprint,
                filled_field_keys=tuple(filled),
                verification_issues=tuple(issues),
            )

        return await self._run(url, prepare_page)

    async def submit(
        self,
        *,
        url: str,
        provider: AtsProvider,
        operations: list[AtsFillOperation],
    ) -> AtsSubmissionEvidence:
        async def submit_page(page, requested_url: str) -> AtsSubmissionEvidence:
            snapshot = await self._snapshot(page, requested_url)
            if snapshot.gates:
                return AtsSubmissionEvidence(
                    success=False,
                    confirmation_text=None,
                    confirmation_url=None,
                    application_number=None,
                    captured_at=datetime.now(UTC),
                    failure_code=snapshot.gates[0],
                )
            _, issues = await self._fill(page, operations)
            if issues:
                return AtsSubmissionEvidence(
                    success=False,
                    confirmation_text=None,
                    confirmation_url=None,
                    application_number=None,
                    captured_at=datetime.now(UTC),
                    failure_code="ats_field_verification_failed",
                )
            selector = (
                "button[type='submit'], input[type='submit']"
                if provider is AtsProvider.GREENHOUSE
                else "button[type='submit'], .template-btn-submit, input[type='submit']"
            )
            submit_button = page.locator(selector).first
            if await submit_button.count() == 0:
                return AtsSubmissionEvidence(
                    success=False,
                    confirmation_text=None,
                    confirmation_url=None,
                    application_number=None,
                    captured_at=datetime.now(UTC),
                    failure_code="ats_submit_control_missing",
                )
            await submit_button.click(timeout=self.timeout_ms)
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=self.timeout_ms)
            except Exception:  # noqa: BLE001 - some ATS update the page in place
                await page.wait_for_timeout(250)
            await page.wait_for_timeout(1_000)
            text = " ".join(
                (await page.locator("body").inner_text(timeout=self.timeout_ms)).split()
            )
            folded = text.casefold()
            success_markers = (
                "submitted",
                "received",
                "thank you",
                "application complete",
                "提交成功",
                "申请已提交",
                "已收到",
                "感谢申请",
            )
            success = any(marker in folded for marker in success_markers)
            number_match = re.search(
                r"(?:application|reference|申请|编号)[\s:#-]*([A-Z0-9-]{3,40})",
                text,
                flags=re.IGNORECASE,
            )
            return AtsSubmissionEvidence(
                success=success,
                confirmation_text=text[:4000] if text else None,
                confirmation_url=await self._validate_url(page.url),
                application_number=number_match.group(1) if number_match else None,
                captured_at=datetime.now(UTC),
                failure_code=None if success else "ats_submission_unverified",
            )

        return await self._run(url, submit_page)

    async def _run(self, url: str, action):
        requested_url = await self._validate_url(url)
        try:
            from playwright.async_api import async_playwright
        except ImportError as error:
            raise AtsBrowserError(
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
                        except Exception:  # noqa: BLE001 - deny unsafe subresources
                            await route.abort()
                            return
                        await route.continue_()

                    await page.route("**/*", guard_request)
                    await page.goto(
                        requested_url,
                        wait_until="domcontentloaded",
                        timeout=self.timeout_ms,
                    )
                    await page.wait_for_timeout(500)
                    return await action(page, requested_url)
                finally:
                    await browser.close()
        except AtsBrowserError:
            raise
        except Exception as error:
            message = str(error)
            code = (
                "browser_timeout"
                if "Timeout" in type(error).__name__ or "Timeout" in message
                else "ats_browser_failed"
            )
            raise AtsBrowserError("ATS 浏览器操作失败", code=code) from error

    async def _inspect_page(self, page, requested_url: str) -> AtsPageSnapshot:
        return await self._snapshot(page, requested_url)

    async def _snapshot(self, page, requested_url: str) -> AtsPageSnapshot:
        final_url = await self._validate_url(page.url)
        visible_text = await page.locator("body").inner_text(timeout=self.timeout_ms)
        raw_fields: list[dict[str, Any]] = await page.locator(
            "input:not([type='hidden']):not([type='submit']):not([type='button']), select, textarea"
        ).evaluate_all(
            """
            (elements) => elements.map((element, index) => {
              const labels = element.labels ? Array.from(element.labels).map((label) => label.innerText).join(' ') : '';
              const wrapper = element.closest('.field, .application-field, .field-container, label');
              const fallback = wrapper ? wrapper.innerText : '';
              const label = (labels || element.getAttribute('aria-label') || element.getAttribute('placeholder') || fallback || element.name || element.id || `Field ${index + 1}`).trim();
              let selector = '';
              if (element.id) selector = `#${CSS.escape(element.id)}`;
              else if (element.name) selector = `${element.tagName.toLowerCase()}[name="${CSS.escape(element.name)}"]`;
              else selector = `${element.tagName.toLowerCase()}:nth-of-type(${index + 1})`;
              return {
                id: element.id || '',
                name: element.name || '',
                label,
                input_type: element.tagName === 'SELECT' ? 'select' : element.tagName === 'TEXTAREA' ? 'textarea' : (element.type || 'text'),
                required: Boolean(element.required || element.getAttribute('aria-required') === 'true'),
                selector,
                options: element.tagName === 'SELECT' ? Array.from(element.options).map((option) => option.text.trim()).filter(Boolean) : [],
                autocomplete: element.getAttribute('autocomplete'),
              };
            })
            """
        )
        fields = tuple(
            AtsFieldDescriptor(
                key=self._field_key(item, index),
                label=str(item.get("label") or f"Field {index + 1}")[:500],
                name=str(item.get("name") or item.get("id") or "")[:240],
                input_type=str(item.get("input_type") or "text")[:40],
                required=bool(item.get("required")),
                selector=str(item.get("selector") or "")[:500],
                options=tuple(str(value)[:240] for value in item.get("options") or []),
                autocomplete=(
                    str(item["autocomplete"])[:120]
                    if item.get("autocomplete")
                    else None
                ),
            )
            for index, item in enumerate(raw_fields)
        )
        form_action = await page.locator("form").first.get_attribute("action")
        gates = list(self._human_gates(visible_text))
        if any(field.input_type == "password" for field in fields):
            gates.append("browser_login_required")
        return AtsPageSnapshot(
            requested_url=requested_url,
            final_url=final_url,
            title=await page.title(),
            visible_text=" ".join(visible_text.split())[:20_000],
            fields=fields,
            form_action=form_action,
            provider_hint=self._provider_hint(final_url, form_action),
            gates=tuple(dict.fromkeys(gates)),
        )

    async def _fill(
        self, page, operations: list[AtsFillOperation]
    ) -> tuple[list[str], list[str]]:
        filled: list[str] = []
        issues: list[str] = []
        for operation in operations:
            locator = page.locator(operation.selector).first
            if await locator.count() == 0:
                issues.append(f"field_missing:{operation.field_key}")
                continue
            try:
                if operation.input_type == "file":
                    await locator.set_input_files(operation.value, timeout=self.timeout_ms)
                elif operation.input_type == "checkbox":
                    if operation.value.casefold() in {"true", "yes", "1", "on"}:
                        await locator.check(timeout=self.timeout_ms)
                    else:
                        await locator.uncheck(timeout=self.timeout_ms)
                elif operation.input_type == "select":
                    try:
                        await locator.select_option(
                            label=operation.value, timeout=self.timeout_ms
                        )
                    except Exception:  # noqa: BLE001 - fall back to option value
                        await locator.select_option(
                            value=operation.value, timeout=self.timeout_ms
                        )
                else:
                    await locator.fill(operation.value, timeout=self.timeout_ms)
                filled.append(operation.field_key)
            except Exception:  # noqa: BLE001 - report the specific field to the service
                issues.append(f"field_fill_failed:{operation.field_key}")
        return filled, issues

    async def _validate_url(self, url: str) -> str:
        try:
            return await self.safety_checker.validate(url)
        except URLReaderError as error:
            raise AtsBrowserError(str(error), code=error.code) from error

    @staticmethod
    def _field_key(item: dict[str, Any], index: int) -> str:
        identity = "|".join(
            (
                str(item.get("id") or ""),
                str(item.get("name") or ""),
                str(item.get("label") or ""),
                str(item.get("input_type") or ""),
                str(index),
            )
        )
        return f"field_{hashlib.sha256(identity.encode()).hexdigest()[:16]}"

    @staticmethod
    def _provider_hint(url: str, form_action: str | None) -> AtsProvider | None:
        hosts = {
            (urlsplit(url).hostname or "").casefold(),
            (urlsplit(form_action or "").hostname or "").casefold(),
        }
        if hosts & {"boards.greenhouse.io", "job-boards.greenhouse.io"}:
            return AtsProvider.GREENHOUSE
        if "jobs.lever.co" in hosts:
            return AtsProvider.LEVER
        return None

    @staticmethod
    def _human_gates(text: str) -> tuple[str, ...]:
        folded = " ".join(text.casefold().split())
        gates = {
            "browser_login_required": ("登录后查看", "请登录", "sign in to continue"),
            "browser_captcha_required": ("captcha", "验证码", "人机验证"),
            "browser_2fa_required": ("two-factor", "2fa", "双重验证", "两步验证"),
            "browser_security_challenge": (
                "cloudflare",
                "security check",
                "安全检查",
            ),
        }
        return tuple(
            code
            for code, markers in gates.items()
            if any(marker in folded for marker in markers)
        )
