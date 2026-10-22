import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from src.services.browser_job_reader import BrowserReadError, PlaywrightBrowserJobReader


@contextmanager
def public_listing(*, popup=False, change=False, loop=False, numbered=False, abbreviated=False, entry=False,
                   plain_title=False, entry_label="查看职位", shell=False, entry_popup=False):
    requests = []
    html = r"""<!doctype html><html><body><main id="jobs"></main>
    <nav class="pagination"><button aria-label="下一页" class="pagination-next"
      onclick="history.replaceState({p:2},'',location.href);render()">›</button></nav>
    <form action="/apply" method="post"><button>申请Agent工程师</button></form>
    <script>
    function render() {
      const p = LOOP ? 1 : (history.state?.p || 1);
      document.querySelector('#jobs').innerHTML = [1,2,3,4].map(i => {
        const id = p*10+i;
        return '<div class="position-card"><div class="position-title" style="cursor:pointer" ' +
          'onclick="OPEN(\'/jobs/' + id + '\')"><span>Agent工程师 ' + id + (CHANGE ? '新版' : '') + '</span></div></div>';
      }).join('');
      document.querySelector('.pagination-next').disabled = p === 2;
      if (NUMBERED) {
        document.querySelector('.pagination-next').textContent = '2';
        document.querySelector('.pagination-next').removeAttribute('aria-label');
        document.querySelector('.pagination-next').className = 'pagination-next-number';
        document.querySelector('#current').setAttribute('aria-current', p === 1 ? 'page' : 'false');
        document.querySelector('.pagination-next-number').setAttribute('aria-current', p === 2 ? 'page' : 'false');
      }
    }
    if (ENTRY && !location.search) {
      document.querySelector('#jobs').innerHTML = '<section><h2>应届生职位</h2><button onclick="location.assign(\'/campus?view=graduate\')">查看职位</button></section><section><h2>实习生职位</h2><button onclick="location.assign(\'/campus?view=intern\')">查看职位</button></section>';
      document.querySelector('nav').remove();
    } else render();
    </script></body></html>"""
    html = html.replace("LOOP", json.dumps(loop)).replace("CHANGE", json.dumps(change))
    html = html.replace("NUMBERED", json.dumps(numbered)).replace("ENTRY", json.dumps(entry))
    if abbreviated:
        html = html.replace("position-card", "list-card-item").replace("position-title", "pos-title-item")
    if plain_title:
        html = html.replace("position-title", "title")
    if entry_label != "查看职位":
        html = html.replace("查看职位", entry_label)
        html = html.replace('<main id="jobs">', '<p class="selected" style="cursor:pointer" onclick="location.assign(\'/wrong\')">校园招聘与实习</p><main id="jobs">')
    if shell:
        html = '<!doctype html><html><body><div id="app"></div></body></html>'
    if entry_popup:
        html = html.replace('onclick="location.assign(', 'onclick="window.open(')
    if numbered:
        html = html.replace('<nav class="pagination">', '<nav class="pagination"><button id="current">1</button>')
        html = html.replace("querySelector('.pagination-next')", "querySelector('.pagination-next,.pagination-next-number')")
        html = html.replace('pagination-next-number', 'page-number-item')
    html = html.replace("OPEN", "window.open" if popup else "location.assign")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            requests.append(("GET", self.path))
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write((html if self.path.startswith("/campus") else
                             "<h1>Agent工程师</h1><p>岗位职责：负责Agent研发</p>").encode())

        def do_POST(self):
            requests.append(("POST", self.path))
            self.send_response(405)
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/campus", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


class FixtureOnlySafetyChecker:
    async def validate(self, url):
        assert url.startswith("http://127.0.0.1:")
        return url


def reader():
    from src.config import Settings
    from src.services.source_understanding import SourceUnderstanding

    result = PlaywrightBrowserJobReader(safety_checker=FixtureOnlySafetyChecker(), timeout_seconds=5)
    result.proxy = None
    result.search_understanding = SourceUnderstanding(Settings(_env_file=None))
    return result


@pytest.mark.asyncio
@pytest.mark.parametrize("popup", [False, True])
async def test_real_browser_reads_linkless_cards_and_resumes_button_pagination(popup):
    with public_listing(popup=popup) as (url, requests):
        browser = reader()
        async with browser.reuse():
            first = await browser.read_dynamic_listing(url, max_links=2)
            cursor = json.loads(json.dumps(first.dynamic_listing["next_cursor"]))
            second = await browser.read_dynamic_listing(url, cursor=cursor, max_links=2)
            third = await browser.read_dynamic_listing(url, cursor=second.dynamic_listing["next_cursor"], max_links=4)
        assert [link.url.rsplit("/", 1)[-1] for p in (first, second, third) for link in p.discovered_links] == [
            "11", "12", "13", "14", "21", "22", "23", "24",
        ]
        assert third.dynamic_listing["next_cursor"] is None
        assert third.dynamic_listing["reason"] == "listing_boundary"
        assert not any(method == "POST" or "/apply" in path for method, path in requests)
        assert all(o["listing_url"] == url for o in first.dynamic_listing["observed_links"])


@pytest.mark.asyncio
async def test_changed_page_cursor_is_rejected_before_skipping_cards():
    with public_listing() as (url, _):
        browser = reader()
        first = await browser.read_dynamic_listing(url, max_links=1)
        cursor = first.dynamic_listing["next_cursor"]
        cursor["fingerprint"] = "different-visible-jobs"
        with pytest.raises(BrowserReadError, match="当前页已变化") as error:
            await browser.read_dynamic_listing(url, cursor=cursor)
        assert error.value.code == "pagination_changed"


@pytest.mark.asyncio
async def test_next_button_that_repeats_page_does_not_claim_exhaustion():
    with public_listing(loop=True) as (url, _):
        browser = reader()
        first = await browser.read_dynamic_listing(url, max_links=4)
        with pytest.raises(BrowserReadError) as error:
            await browser.read_dynamic_listing(url, cursor=first.dynamic_listing["next_cursor"])
        assert error.value.code == "pagination_loop"


@pytest.mark.asyncio
async def test_numbered_pagination_uses_only_unique_visible_successor():
    with public_listing(numbered=True) as (url, _):
        browser = reader()
        first = await browser.read_dynamic_listing(url, max_links=4)
        second = await browser.read_dynamic_listing(url, cursor=first.dynamic_listing["next_cursor"], max_links=4)
        assert [link.url.rsplit('/', 1)[-1] for link in second.discovered_links] == ['21', '22', '23', '24']
        assert second.dynamic_listing['next_cursor'] is None


@pytest.mark.asyncio
async def test_abbreviated_position_titles_in_generic_list_cards():
    with public_listing(abbreviated=True) as (url, _):
        page = await reader().read_dynamic_listing(url, max_links=2)
        assert len(page.discovered_links) == 2
        assert page.dynamic_listing["next_cursor"]["offset"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("popup", [False, True])
async def test_view_jobs_button_discovers_campus_entry_without_entering_internship(popup):
    with public_listing(entry=True, entry_popup=popup) as (url, requests):
        page = await reader().read_dynamic_listing(url, keywords=("Agent", "校招"))
        assert not page.discovered_links
        assert [link.url for link in page.discovered_entries] == [url + "?view=graduate"]
        assert not any("view=intern" in path or method == "POST" for method, path in requests)


@pytest.mark.asyncio
async def test_plain_title_inside_job_card_is_read_without_site_specific_selectors():
    with public_listing(plain_title=True) as (url, _):
        page = await reader().read_dynamic_listing(url, max_links=2)
        assert [link.url.rsplit("/", 1)[-1] for link in page.discovered_links] == ["11", "12"]


@pytest.mark.asyncio
@pytest.mark.parametrize("label", ["了解更多", "查看12个职位"])
async def test_learn_more_uses_own_recruitment_section_to_choose_campus_entry(label):
    with public_listing(entry=True, entry_label=label) as (url, requests):
        page = await reader().read_dynamic_listing(url, keywords=("Agent", "校招"))
        assert [link.url for link in page.discovered_entries] == [url + "?view=graduate"]
        assert not any("view=intern" in path or path == "/wrong" for _, path in requests)


@pytest.mark.asyncio
async def test_unrendered_shell_is_not_reported_as_end_of_listing():
    with public_listing(shell=True) as (url, _):
        page = await reader().read_dynamic_listing(url)
        assert page.dynamic_listing["reason"] == "listing_not_ready"
        assert not page.discovered_links


@pytest.mark.asyncio
async def test_observed_external_hiring_entry_is_recorded_without_becoming_a_job():
    from types import SimpleNamespace

    from playwright.async_api import async_playwright

    from src.services.dynamic_recruitment_listing import read_dynamic_listing_page

    origin, target = "https://official.example/campus", "https://hiring.example/graduate"
    requested = []

    async def respond(route):
        requested.append(route.request.url)
        assert route.request.url in {origin, target}
        html = ('<section><h2>2027校园招聘</h2><button onclick="location.assign(\'' + target +
                '\')">查看职位</button></section>') if route.request.url == origin else '<h1>公司校园招聘</h1>'
        await route.fulfill(status=200, content_type="text/html; charset=utf-8", body=html)

    async def validate(url):
        assert url in {origin, target}
        return url

    async with async_playwright() as runtime:
        browser = await runtime.chromium.launch()
        try:
            context = await browser.new_context()
            await context.route("**/*", respond)
            page = await context.new_page()
            await page.goto(origin)
            snapshot = await read_dynamic_listing_page(page,
                reader=SimpleNamespace(timeout_ms=3000, max_chars=500000, _validate_url=validate), keywords=("校招",))
            assert not snapshot.discovered_links
            assert [link.url for link in snapshot.discovered_entries] == [target], (snapshot.dynamic_listing, requested)
            assert snapshot.dynamic_listing["observed_links"][0]["listing_url"] == origin
            assert page.url == origin
        finally:
            await browser.close()
