import asyncio
from types import SimpleNamespace

import httpx
import pytest

from src.services.browser_job_reader import top_level_navigation
from src.services.browser_read_trace import BrowserReadTrace, diagnostic_url
from src.services.url_reader import (
    SafeHTTPReader,
    URLFetchError,
    URLSafetyChecker,
    URLSafetyError,
)


class NavigationRequest:
    def __init__(self, *, frame_error=None, parent=None, destination=None, resource="document", navigation=True):
        self.frame_error, self.parent, self.destination = frame_error, parent, destination
        self.resource_type, self.navigation = resource, navigation

    @property
    def frame(self):
        if self.frame_error:
            raise RuntimeError(self.frame_error)
        return SimpleNamespace(parent_frame=self.parent)

    def is_navigation_request(self):
        return self.navigation

    async def header_value(self, name):
        assert name == "sec-fetch-dest"
        return self.destination


@pytest.mark.asyncio
@pytest.mark.parametrize("destination", [None, "document"])
async def test_initial_popup_navigation_without_a_frame_is_top_level(destination):
    request = NavigationRequest(frame_error="Frame for this navigation request is not available",
                                destination=destination)
    assert await top_level_navigation(request)


@pytest.mark.asyncio
@pytest.mark.parametrize("options", [
    {"parent": object()},
    {"frame_error": "Frame detached", "destination": "document"},
    {"frame_error": "Frame for this navigation request is not available", "destination": "iframe"},
    {"frame_error": "Frame for this navigation request is not available", "resource": "fetch"},
    {"frame_error": "Frame for this navigation request is not available", "navigation": False},
])
async def test_iframes_and_unrelated_frame_errors_do_not_gain_external_entry_permission(options):
    assert not await top_level_navigation(NavigationRequest(**options))


def test_trace_redacts_urls_bounds_events_and_freezes_completion_time(monkeypatch):
    from src.services import browser_read_trace

    clock = [1.0]
    monkeypatch.setattr(browser_read_trace, "monotonic", lambda: clock[0])
    secret_url = "https://user:password@careers.example/jobs;jsessionid=private?token=secret#/private"
    assert diagnostic_url(secret_url) == "https://careers.example/jobs"
    trace = BrowserReadTrace(secret_url)
    trace.phase("document_navigation")
    clock[0] = 2.0
    trace.phase("wait_navigation_document")
    for _ in range(110):
        trace.event("request_failed", secret_url)
    clock[0] = 4.0
    trace.finish("cancelled", "CancelledError")
    snapshot = trace.snapshot()
    clock[0] = 100.0
    assert trace.snapshot() == snapshot
    assert snapshot["elapsed_ms"] == 3000
    assert snapshot["failure_phase"] == "wait_navigation_document"
    assert snapshot["phases"][0]["elapsed_ms"] == 1000
    assert len(snapshot["network"]) == 100 and snapshot["dropped_events"] == 10
    assert all(value not in str(snapshot) for value in ("password", "private", "token", "secret"))


@pytest.mark.asyncio
async def test_fake_ip_http_rejection_is_distinct_from_opted_in_https_proxy_resolution():
    checker = URLSafetyChecker(resolver=lambda *_: ["198.18.0.135"],
        proxy_url="http://proxy.example:8080", proxy_allowed_hosts=["careers.example"],
        proxy_allow_unlisted_hosts=True)
    with pytest.raises(URLSafetyError) as caught:
        await checker.validate("http://campus.example/home")
    assert caught.value.code == "unsafe_url" and caught.value.reason == "dns_non_public"
    assert await checker.validate("https://campus.example/") == "https://campus.example/"
    with pytest.raises(URLSafetyError):
        await checker.validate("https://198.18.0.135/")


@pytest.mark.asyncio
@pytest.mark.parametrize("headers,reason", [({}, "redirect_missing_location"), ({"Location": "/home"}, "redirect_limit")])
async def test_redirect_failures_keep_specific_reasons_without_changing_error_codes(headers, reason):
    reader = SafeHTTPReader(transport=httpx.MockTransport(lambda _: httpx.Response(302, headers=headers)),
                            safety_checker=URLSafetyChecker(resolver=lambda *_: ["8.8.8.8"]))
    with pytest.raises(URLFetchError) as caught:
        await reader.fetch("https://careers.example/jobs/1")
    assert caught.value.code == "url_fetch_failed" and caught.value.reason == reason


@pytest.mark.asyncio
async def test_browser_timeout_keeps_failure_phase_in_evidence_attempt(monkeypatch):
    from src.services import company_evidence_reader
    from tests.test_company_evidence_reader import HOME, Reader, evidence
    from tests.test_dynamic_recruitment_listing import public_listing, reader

    with public_listing(shell=True) as (url, _):
        browser = reader()

        class EntryBrowser:
            async def read_evidence(self, unused):
                return await browser.read_campaign_page(url)

            def diagnostics_for(self, unused):
                return browser.diagnostics_for(url)

        # Wait until the actual browser is waiting on content, then cancel through
        # the same outer wait_for that enforces CompanyEvidenceReader's budget.
        original_wait_for = asyncio.wait_for

        async def timeout_after_readiness(awaitable, timeout):
            if timeout != 12:
                return await original_wait_for(awaitable, timeout)
            task = asyncio.create_task(awaitable)
            try:
                async def ready():
                    while True:
                        trace = browser.diagnostics_for(url)
                        if trace and trace["phases"][-1]["phase"] == "wait_recruitment_ready":
                            return
                        await asyncio.sleep(.01)
                await original_wait_for(ready(), 10)
                return await original_wait_for(task, .01)
            finally:
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)

        monkeypatch.setattr(company_evidence_reader.asyncio, "wait_for", timeout_after_readiness)
        worker = evidence(Reader(b'<html><body><div id="app"></div></body></html>'), EntryBrowser())
        await worker.read(HOME)
        attempt = worker.attempts[-1]
        assert attempt["error_type"] == "TimeoutError"
        assert attempt["browser_diagnostics"]["status"] == "cancelled"
        assert attempt["browser_diagnostics"]["failure_phase"] == "wait_recruitment_ready"
        assert attempt["browser_diagnostics"]["phases"][-1]["phase"] == "cleanup"
