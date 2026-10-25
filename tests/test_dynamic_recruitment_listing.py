import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from src.services.browser_job_reader import BrowserReadError, PlaywrightBrowserJobReader


@contextmanager
def public_listing(*, popup=False, change=False, loop=False, numbered=False, abbreviated=False, entry=False,
                   plain_title=False, entry_label="查看职位", shell=False, entry_popup=False,
                   replace_navigation=False, entry_tag="button", detail_html=None, delayed=False,
                   entry_prefix="", plain_projects=False, shift_wrapper=False, carousel=False):
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
    if plain_projects:
        html = html.replace('<h2>应届生职位</h2>', '<p>海洋科技人才</p>')
        html = html.replace('<h2>实习生职位</h2>', '<p>航空人才</p>')
    if entry_label != "查看职位":
        html = html.replace("查看职位", entry_label)
        html = html.replace('<main id="jobs">', '<p class="selected" style="cursor:pointer" onclick="location.assign(\'/wrong\')">校园招聘与实习</p><main id="jobs">')
    if shell:
        html = '<!doctype html><html><body><div id="app"></div></body></html>'
    if delayed:
        html = html.replace('<main id="jobs"></main>', '<a href="/campus">校园招聘</a><main id="jobs">职位类别 筛选 搜索 暂无相关岗位</main>')
        html = html.replace('} else render();', '} else setTimeout(render, 400);')
    if entry_popup:
        html = html.replace('onclick="location.assign(', 'onclick="window.open(')
    if numbered:
        html = html.replace('<nav class="pagination">', '<nav class="pagination"><button id="current">1</button>')
        html = html.replace("querySelector('.pagination-next')", "querySelector('.pagination-next,.pagination-next-number')")
        html = html.replace('pagination-next-number', 'page-number-item')
    html = html.replace("OPEN", "window.open" if popup else "location.assign")
    if replace_navigation:
        html = html.replace("location.assign", "location.replace")
    if entry_tag != "button":
        html = html.replace('<button onclick=', f'<{entry_tag} style="cursor:pointer" onclick=')
        html = html.replace(f'{entry_label}</button>', f'{entry_label}</{entry_tag}>')
    html = html.replace('<body>', '<body>' + entry_prefix)
    if carousel:
        html = html.replace('<main id="jobs"></main>', '''<div class="el-carousel">
          <main id="jobs"></main><ul class="el-carousel__indicators">
          <li><button onclick="document.querySelector('#jobs').dataset.page='1'"></button></li>
          <li><button onclick="document.querySelector('#jobs').dataset.page='2'"></button></li></ul></div>
          <style>#jobs{position:relative;width:300px;height:240px;overflow:hidden}
          #jobs section{position:absolute;width:300px;height:240px;top:0;left:0}
          #jobs section:nth-child(2){transform:translateX(300px)}
          #jobs[data-page="2"] section:first-child{transform:translateX(-300px)}
          #jobs[data-page="2"] section:nth-child(2){transform:translateX(0)}
          .el-carousel__indicators button{width:30px;height:20px}</style>''')
        html = html.replace('<section>', '<section class="el-carousel__item">')

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            requests.append(("GET", self.path))
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            rendered = html
            if shift_wrapper and requests.count(("GET", "/campus")) > 1:
                rendered = html.replace('<main id="jobs">', '<div>新横幅</div><main id="jobs">')
            self.wfile.write((rendered if self.path.startswith("/campus") else
                             detail_html or "<h1>Agent工程师</h1><p>岗位职责：负责Agent研发</p>").encode())

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
async def test_agent_render_keeps_control_choice_and_clicks_only_the_selected_card():
    with public_listing() as (url, requests):
        browser = reader()
        snapshot = await browser.read_agent_page(url)
        assert not any("/jobs/" in path or "/apply" in path for _, path in requests)
        cards = [c for c in snapshot.navigation_controls if c["kind"] == "cards"]
        assert len(cards) >= 2
        selected = cards[1]
        result = await browser.read_agent_page(url, control=selected)
        assert len(result.discovered_links) == 1
        assert result.discovered_links[0].text == selected["label"]
        assert not any("/apply" in path or method == "POST" for method, path in requests)


@pytest.mark.asyncio
async def test_agent_navigation_rejects_unobserved_or_changed_selector_before_clicking():
    with public_listing() as (url, requests):
        browser = reader()
        result = await browser.read_agent_page(url, control={"kind": "cards", "selector": "#apply", "label": "算法工程师"})
        assert result.dynamic_listing["reason"] == "navigation_control_changed"
        assert result.dynamic_listing["navigation_executed"] is False
        assert result.navigation_controls
        assert not any("/apply" in path or method == "POST" for method, path in requests)


@pytest.mark.asyncio
async def test_identical_view_job_buttons_keep_plain_text_project_context():
    with public_listing(entry=True, plain_projects=True, entry_tag="span") as (url, requests):
        browser = reader()
        snapshot = await browser.read_agent_page(url)
        controls = [c for c in snapshot.navigation_controls if c["kind"] == "entries"]
        assert any("海洋科技人才" in c["label"] for c in controls)
        assert any("航空人才" in c["label"] for c in controls)
        selected = next(c for c in controls if "海洋科技人才" in c["label"])
        await browser.read_agent_page(url, control=selected)
        assert any("view=graduate" in path for _, path in requests)
        assert not any("view=intern" in path for _, path in requests)


@pytest.mark.asyncio
async def test_agent_rebinds_same_project_after_dom_wrapper_changes():
    with public_listing(entry=True, plain_projects=True, entry_tag="span", shift_wrapper=True) as (url, requests):
        browser = reader()
        snapshot = await browser.read_agent_page(url)
        selected = next(c for c in snapshot.navigation_controls if c["kind"] == "entries" and "海洋科技人才" in c["label"])
        await browser.read_agent_page(url, control=selected)
        assert any("view=graduate" in path for _, path in requests)
        assert not any("view=intern" in path or method == "POST" for method, path in requests)


def test_rebinding_rejects_ambiguous_or_changed_project_labels():
    from src.services.dynamic_recruitment_listing import resolve_selected_control
    selected = {"selector": "#old", "label": "海洋科技人才 查看职位", "navigation": False}
    one = {**selected, "selector": "#one"}
    assert resolve_selected_control(selected, [one]) == one
    assert resolve_selected_control(selected, [one, {**one, "selector": "#two"}]) is None
    assert resolve_selected_control(selected, [{**one, "label": "航空人才 查看职位"}]) is None


@pytest.mark.asyncio
async def test_agent_switches_carousel_and_restores_in_page_state_before_next_click():
    with public_listing(entry=True, plain_projects=True, entry_tag="span", carousel=True) as (url, requests):
        browser = reader()
        initial = await browser.read_agent_page(url)
        assert not any("航空人才" in c["label"] for c in initial.navigation_controls if c["kind"] == "entries")
        switch = next(c for c in initial.navigation_controls if c["label"].startswith("轮播第2页"))
        changed = await browser.read_agent_page(url, control=switch)
        target = next(c for c in changed.navigation_controls if c["kind"] == "entries" and "航空人才" in c["label"])
        assert target["replay"] == [switch]
        result = await browser.read_agent_page(url, control=target)
        assert any("view=intern" in link.url for link in result.discovered_entries)
        assert not any("view=graduate" in path or method == "POST" for method, path in requests)


@pytest.mark.asyncio
@pytest.mark.parametrize("container", ['nav', 'div class="recruit-filter"'])
async def test_agent_can_choose_observed_menu_or_company_filter_without_auto_clicking(container):
    tag = container.split()[0]
    prefix = (f'<{container}><span style="cursor:pointer" onclick="location.assign(\'/campus?view=company\')">海洋科技人才</span>'
              '<button onclick="location.assign(\'/apply\')">申请</button> '
              f'<button onclick="location.assign(\'/login\')">登录</button></{tag}>')
    with public_listing(entry_prefix=prefix) as (url, requests):
        browser = reader()
        snapshot = await browser.read_agent_page(url)
        controls = [c for c in snapshot.navigation_controls if c["kind"] == "navigation"]
        selected = next(c for c in controls if c["label"] == "海洋科技人才")
        assert all(c["label"] not in {"申请", "登录"} for c in controls)
        assert not any("view=company" in path for _, path in requests)
        await browser.read_agent_page(url, control=selected)
        assert any("view=company" in path for _, path in requests)
        assert not any("/apply" in path or "/login" in path for _, path in requests)


@pytest.mark.asyncio
@pytest.mark.parametrize("prefix,unresolved", [
    ('<header><button onclick="location.assign(location.href)">校园招聘</button></header>', False),
    ('<button>校园招聘</button>', True),
])
async def test_campaign_entry_ready_without_job_text_and_skips_self_or_inactive_controls(prefix, unresolved):
    with public_listing(entry=True, entry_popup=True, entry_label="校园招聘", entry_prefix=prefix) as (url, requests):
        browser = reader()
        snapshot = await browser.read_campaign_page(url)
        assert [link.url for link in snapshot.discovered_entries] == [url + "?view=graduate"]
        trace = browser.diagnostics_for(url)
        assert not any(event["event"] == "wait_timeout" for event in trace["network"])
        assert any(event["event"] == "navigation_unresolved" for event in trace["network"]) == unresolved
        assert requests.count(("GET", "/campus")) == 1
        assert not any("view=intern" in path or method == "POST" for method, path in requests)


@pytest.mark.asyncio
async def test_campaign_page_resolves_one_public_job_card_without_applying():
    with public_listing() as (url, requests):
        snapshot = await reader().read_campaign_page(url)
        assert len(snapshot.discovered_links) == 1
        assert snapshot.discovered_links[0].url.endswith("/jobs/11")
        assert snapshot.final_url == url
        assert requests.count(("GET", "/campus")) == 1
        assert not any(method == "POST" or "/apply" in path for method, path in requests)


@pytest.mark.asyncio
async def test_campaign_observes_css_application_controls_without_clicking_them():
    html = '''<style>.action{cursor:pointer}.hidden{display:none}</style>
    <h1>算法工程师</h1><p>2027届校招 岗位职责：负责研发和系统评测</p>
    <span class="action" onclick="fetch('/apply',{method:'POST'})">投递岗位</span>
    <div role="button">加入意向单</div><div class="is-disabled"><span class="action">立即申请</span></div>
    <button class="hidden">申请岗位</button><div class="cookie-settings"><button>Apply</button></div>'''
    with public_listing(detail_html=html) as (url, requests):
        snapshot = await reader().read_campaign_page(url.replace('/campus', '/jobs/123'))
        assert set(snapshot.application_actions) == {'投递岗位', '加入意向单'}
        assert not any(method == 'POST' or '/apply' in path for method, path in requests)


@pytest.mark.asyncio
async def test_campaign_renders_empty_http_listing_until_delayed_cards_are_available():
    from types import SimpleNamespace

    from src.services.company_evidence_reader import CompanyEvidenceReader
    from src.services.url_reader import SafeHTTPReader

    with public_listing(delayed=True) as (url, requests):
        browser = reader()
        worker = CompanyEvidenceReader(SafeHTTPReader(safety_checker=FixtureOnlySafetyChecker()),
            browser=SimpleNamespace(read_evidence=browser.read_campaign_page), on_event=lambda *_: None,
            collect_actions=True)
        worker.browser_remaining = 1
        page = await worker.read(url)
        assert page['method'] == 'browser'
        assert any(link.url.endswith('/jobs/11') for link in page['links'])
        assert not any(method == 'POST' for method, _ in requests)


@pytest.mark.asyncio
async def test_campaign_resolves_announcement_navigation_even_when_job_cards_are_present():
    prefix = '<header><span style="cursor:pointer" onclick="location.assign(\'/notice\')">校招公告</span></header>'
    with public_listing(entry_prefix=prefix) as (url, requests):
        snapshot = await reader().read_campaign_page(url)
        assert snapshot.discovered_entries[0].url.endswith('/notice')
        assert snapshot.discovered_links[0].url.endswith('/jobs/11')
        assert not any(method == 'POST' or '/apply' in path for method, path in requests)


@pytest.mark.asyncio
@pytest.mark.parametrize('active_inside', [False, True])
async def test_campaign_reads_current_announcement_cards_without_mistaking_them_for_jobs(active_inside):
    titles = ['2027届校招正式启动', '2027届校招提前批启动', '2027届仓储类管培生招聘启动',
              '2027届研发实习生招聘正式启动']
    prefix = '<li class="index_active__xyz" style="cursor:pointer"><div><span>校招公告</span></div></li>'
    if active_inside:
        prefix = '<li style="cursor:pointer"><div><span class="index_active__xyz">校招公告</span></div></li>'
    prefix += ''.join(f'<a style="cursor:pointer" onclick="location.assign(\'/news/{i}\')">{title}</a>'
                     for i, title in enumerate(titles))
    with public_listing(entry_prefix=prefix) as (url, requests):
        snapshot = await reader().read_campaign_page(url)
        assert {link.url.rsplit('/', 1)[-1] for link in snapshot.discovered_entries} == {'0', '1', '2'}
        assert all('/jobs/' in link.url for link in snapshot.discovered_links)
        assert ('GET', '/news/3') not in requests


@pytest.mark.asyncio
async def test_campaign_uses_announcement_index_and_does_not_reclick_static_article_links():
    prefix = ('<a href="/news/static"><span style="cursor:pointer">2027届校招正式启动</span></a>'
              '<button onclick="location.assign(\'/notice\')">校招公告</button>'
              '<button onclick="location.assign(\'/news/dynamic\')">2027届校招提前批启动</button>')
    with public_listing(entry_prefix=prefix) as (url, requests):
        snapshot = await reader().read_campaign_page(url)
        assert [link.url.rsplit('/', 1)[-1] for link in snapshot.discovered_entries] == ['notice']
        assert ('GET', '/news/static') not in requests and ('GET', '/news/dynamic') not in requests


@pytest.mark.asyncio
@pytest.mark.parametrize('header_tag', ['header', 'div'])
async def test_campaign_waits_for_delayed_announcement_instead_of_navigation_shell(header_tag):
    html = '''<HEADER class="index_headerContent__abc"><div><ul><li><div><span style="cursor:pointer">应届生招聘</span></div></li></ul></div></HEADER>
    <main id="article"></main><script>
    setTimeout(() => {document.getElementById('article').innerHTML =
      '<h1>2027届仓储类管培生招聘启动</h1><p>面向2027届毕业生</p>';}, 1500);
    </script>'''.replace('HEADER', header_tag)
    with public_listing(detail_html=html) as (url, _):
        snapshot = await reader().read_campaign_page(url.replace('/campus', '/jobs/notice'))
        assert '2027届仓储类管培生招聘启动' in snapshot.visible_text


@pytest.mark.asyncio
async def test_linkless_cards_restore_observed_listing_after_replace_navigation():
    with public_listing(replace_navigation=True) as (url, requests):
        snapshot = await reader().read_dynamic_listing(url, max_links=2)
        assert [link.url.rsplit('/', 1)[-1] for link in snapshot.discovered_links] == ['11', '12']
        assert snapshot.final_url == url
        assert not any(method == "POST" or "/apply" in path for method, path in requests)


@pytest.mark.asyncio
@pytest.mark.parametrize("label,tag", [("查看12个职位", "p"), ("了解更多", "div")])
async def test_campaign_detects_contextual_navigation_controls_without_site_selectors(label, tag):
    with public_listing(entry=True, entry_label=label, entry_tag=tag) as (url, requests):
        snapshot = await reader().read_campaign_page(url)
        assert [link.url for link in snapshot.discovered_entries] == [url + "?view=graduate"]
        assert not any("view=intern" in path or method == "POST" for method, path in requests)


@pytest.mark.asyncio
@pytest.mark.parametrize("label", ["查看所有职位", "查看全部岗位", "View all jobs"])
async def test_agent_can_select_all_jobs_button_and_reach_the_public_list(label):
    with public_listing(entry=True, entry_label=label, entry_tag="div") as (url, requests):
        browser = reader()
        snapshot = await browser.read_agent_page(url)
        control = next(c for c in snapshot.navigation_controls if c["kind"] == "entries" and "应届生" in c["label"])
        assert label in control["label"]
        assert not any("view=" in path for _, path in requests)
        result = await browser.read_agent_page(url, control=control)
        assert [link.url for link in result.discovered_entries] == [url + "?view=graduate"]
        assert not any("view=intern" in path or "/apply" in path or method == "POST" for method, path in requests)


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
