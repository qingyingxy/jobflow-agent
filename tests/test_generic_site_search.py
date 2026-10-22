import html
import json
import threading
from contextlib import contextmanager
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest

from src.services.recruitment_search_controls import has_job_search
from tests.test_dynamic_recruitment_listing import reader
from tests.test_recruitment_capabilities import QUERY, SOURCE

JOBS = [
    ("1", "2027届校招 芯片设计工程师"),
    ("2", "2027届校招 RAG研发工程师"),
    ("3", "2027届校招 Agent应用工程师"),
    ("4", "2027届校招 后端开发工程师"),
    ("5", "2027届校招 Agent平台工程师"),
    ("6", "2027届校招 Agent评测工程师"),
]


@contextmanager
def search_site(*, ajax=False, inert=False, ambiguous=False, private_form=False, real_links=False, icon_button=False, enter_only=False, unfamiliar=False, generic_cards=False, bare_search=False):
    requests = []

    def render_jobs(term, page):
        found = [(i, title) for i, title in JOBS if term.casefold() in title.casefold()]
        rows = found[(page-1)*2:page*2] if term else found[:4]
        cards = []
        for number, title in rows:
            if generic_cards:
                cards.append(f'<div class="item___a19" style="cursor:pointer" onclick="location.assign(\'/jobs/{number}\')">'
                             f'<div><span>{title}</span></div><div>工作地点：上海</div><div>所属业务：AI</div></div>')
            elif real_links:
                cards.append(f'<a href="/jobs/{number}">{title}</a>')
            else:
                cards.append(f'<div class="position-card"><span class="position-title" style="cursor:pointer" '
                             f'onclick="location.assign(\'/jobs/{number}\')">{title}</span></div>')
        if not cards:
            cards = ['<p>没有对应职位，看下其他的结果吧～</p>']
        if term and len(found) > page*2:
            cards.append('<button aria-label="下一页" onclick="location.assign(\'/campus?q=\'+'
                         f'encodeURIComponent({html.escape(json.dumps(term), quote=True)})+\'&page={page+1}\')">下一页</button>')
        return "".join(cards)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            requests.append(("GET", self.path))
            url = urlsplit(self.path)
            params = parse_qs(url.query)
            term = params.get("q", [""])[0]
            page = int(params.get("page", ["1"])[0])
            body = render_jobs(term, page)
            if url.path == "/campus":
                submit = "event.preventDefault();" if inert else (
                    "event.preventDefault();fetch('/results?q='+encodeURIComponent(this.q.value))"
                    ".then(r=>r.text()).then(t=>document.querySelector('#jobs').innerHTML=t);" if ajax else "")
                field = f'<input type="search" placeholder="搜索职位关键词" name="q" value="{html.escape(term)}">'
                extra = '<input type="email" name="email">' if private_form else ""
                button = ('<i aria-label="图标: search" style="cursor:pointer" onclick="this.closest(\'form\').requestSubmit()">⌕</i>'
                          if icon_button else '<button>搜索</button>')
                if enter_only:
                    button = button.replace('onclick="this.closest(\'form\').requestSubmit()"', '')
                form = f'<form action="/campus" method="get" onsubmit="{submit}">{field}{extra}{button}</form>'
                if bare_search:
                    form = field.replace('<input ', '<input onkeydown="if(event.key===\'Enter\')location.assign(\'/campus?q=\'+encodeURIComponent(this.value))" ')
                if unfamiliar:
                    form = form.replace('type="search" placeholder="搜索职位关键词"', 'type="text" placeholder="你想做什么"').replace('>搜索<', '>寻找机会<')
                    form = '<section><h2>加入团队 · 公开职位</h2>' + form + '</section>'
                body = form + (form if ambiguous else "") + f'<main id="jobs">{body}</main>'
            elif url.path.startswith("/jobs/"):
                body = '<h1>Agent工程师</h1><h2>岗位职责</h2><p>负责Agent研发</p>'
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(('<!doctype html><html><body>'+body+'</body></html>').encode())

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


@pytest.mark.asyncio
@pytest.mark.parametrize("ajax", [False, True])
async def test_search_replays_keyword_before_card_offset_and_pagination(ajax):
    with search_site(ajax=ajax) as (url, requests):
        browser = reader()
        async with browser.reuse():
            first = await browser.read_dynamic_listing(url, keywords=("Agent", "RAG", "校招"), max_links=1)
            assert first.dynamic_listing["search"]["status"] == "confirmed"
            cursor = json.loads(json.dumps(first.dynamic_listing["next_cursor"]))
            second = await browser.read_dynamic_listing(url, cursor=cursor, keywords=("Agent", "校招"), max_links=1)
            third = await browser.read_dynamic_listing(url, cursor=second.dynamic_listing["next_cursor"],
                                                       keywords=("Agent", "校招"), max_links=2)
        assert [link.url.rsplit("/", 1)[-1] for page in (first, second, third) for link in page.discovered_links] == ["3", "5", "6"]
        assert second.dynamic_listing["search"]["recipe_reused"] is True
        assert third.dynamic_listing["next_cursor"] is None
        assert all(method == "GET" for method, _ in requests)


@pytest.mark.asyncio
async def test_empty_search_is_confirmed_and_query_alternatives_can_start_independently():
    with search_site() as (url, _):
        browser = reader()
        page = await browser.read_dynamic_listing(url, keywords=("missing-role", "校招"))
        assert not page.discovered_links
        assert page.dynamic_listing["search"]["empty"]
        assert page.dynamic_listing["search"]["status"] == "confirmed"
        rag = await browser.read_dynamic_listing(url, cursor={"search": {"term": "RAG"}}, keywords=("Agent", "RAG", "校招"))
        assert [link.url.rsplit("/", 1)[-1] for link in rag.discovered_links] == ["2"]


@pytest.mark.asyncio
async def test_input_echo_is_not_filtering_and_unfiltered_continuation_remains_available():
    with search_site(inert=True) as (url, _):
        page = await reader().read_dynamic_listing(url, keywords=("Agent", "校招"), max_links=1)
        assert page.dynamic_listing["search"]["status"] == "unconfirmed"
        assert page.discovered_links[0].url.endswith("/3")  # Direction beats the shared campus label.
        assert page.dynamic_listing["next_cursor"]["search"] == {"term": ""}
        next_page = await reader().read_dynamic_listing(url, cursor=page.dynamic_listing["next_cursor"],
                                                       keywords=("Agent", "校招"), max_links=3)
        assert len(next_page.discovered_links) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("options", [{"ambiguous": True}, {"private_form": True}])
async def test_ambiguous_and_personal_forms_are_not_submitted(options):
    with search_site(**options) as (url, requests):
        page = await reader().read_dynamic_listing(url, keywords=("Agent", "校招"), max_links=1)
        assert page.dynamic_listing["search"]["status"] in {"ambiguous", "unavailable"}
        assert not any("q=" in path or method == "POST" for method, path in requests)


def test_search_hint_is_from_inputs_not_scripts_or_email_fields():
    assert has_job_search('<input name="keyword" placeholder="职位名称">')
    assert not has_job_search('<script>const x = "search jobs";</script><input type="email" name="job">')


@pytest.mark.asyncio
async def test_accessibly_labelled_search_icon_submits_only_the_job_query():
    with search_site(ajax=True, icon_button=True) as (url, requests):
        page = await reader().read_dynamic_listing(url, keywords=("Agent", "校招"), max_links=1)
        assert page.dynamic_listing["search"]["status"] == "confirmed"
        assert page.dynamic_listing["search"]["recipe"]["button_label"] == "图标: search"
        assert page.discovered_links[0].url.endswith("/3")
        assert any(path == "/results?q=Agent" for _, path in requests)


@pytest.mark.asyncio
async def test_enter_only_search_is_learned_and_reused_without_clicking_again():
    with search_site(ajax=True, icon_button=True, enter_only=True) as (url, _):
        browser = reader()
        first = await browser.read_dynamic_listing(url, keywords=("Agent", "校招"), max_links=1)
        assert first.dynamic_listing["search"]["status"] == "confirmed"
        assert first.dynamic_listing["search"]["recipe"]["submit_method"] == "enter"
        second = await browser.read_dynamic_listing(url, cursor=first.dynamic_listing["next_cursor"],
                                                     keywords=("Agent", "校招"), max_links=1)
        assert second.dynamic_listing["search"]["recipe_reused"]
        assert second.discovered_links[0].url.endswith("/5")


@pytest.mark.asyncio
@pytest.mark.parametrize("term,expected", [("Agent", ["3", "5", "6"]), ("RAG", ["2"])])
async def test_generic_css_cards_and_bare_enter_search_keep_single_results_and_resume(term, expected):
    with search_site(generic_cards=True, bare_search=True) as (url, requests):
        browser = reader()
        links, cursor = [], None
        async with browser.reuse():
            for _ in range(3):
                page = await browser.read_dynamic_listing(url, cursor=cursor, keywords=(term, "校招"), max_links=1)
                assert page.dynamic_listing["search"]["status"] == "confirmed"
                links.extend(link.url.rsplit("/", 1)[-1] for link in page.discovered_links)
                cursor = page.dynamic_listing["next_cursor"]
                if not cursor:
                    break
        assert links == expected
        assert all(method == "GET" for method, _ in requests)


@pytest.mark.asyncio
async def test_direct_search_keeps_other_terms_and_unfiltered_exploration_after_three_matches():
    from src.services.direct_recruitment_search import DirectRecruitmentSearch

    with search_site() as (url, _):
        browser = reader()
        source = replace(SOURCE, career_url=url)
        found = []

        async def verified(candidate):
            return candidate.source_url.rsplit("/", 1)[-1] in {"2", "3", "5", "6"}

        direct = DirectRecruitmentSearch(sources=[source], query=QUERY, reader=None, browser=browser,
                                        on_event=lambda *_: None, company_seconds=60)
        async with browser.reuse():
            await direct.discover(found.extend, await_result=verified)
            assert [c.source_url.rsplit("/", 1)[-1] for c in found] == ["3", "5", "6"]
            state = direct.states[source.id]
            assert state["reason"] == "company_read_limit"
            terms = [p.get("dynamic_cursor", {}).get("search", {}).get("term") for p in state["html_queue"]]
            assert "rag" in terms and "" in terms
            assert url in state["search_profiles"]
            resumed = DirectRecruitmentSearch(sources=[source], query=QUERY, reader=None, browser=browser,
                on_event=lambda *_: None, company_seconds=60, states=json.loads(json.dumps(direct.states)))
            continued = []
            await resumed.discover(continued.extend, await_result=verified)
        assert continued and continued[0].source_url.endswith("/2")
        assert not {c.source_url for c in found} & {c.source_url for c in continued}


@pytest.mark.asyncio
async def test_model_selects_observed_unfamiliar_search_and_reuses_validated_recipe():
    from src.config import Settings
    from src.infrastructure.llm_client import FakeModelClient
    from src.services.source_understanding import SourceUnderstanding

    with search_site(ajax=True, unfamiliar=True) as (url, requests):
        browser = reader()
        client = FakeModelClient(output={"control_id": 0})
        browser.search_understanding = SourceUnderstanding(Settings(_env_file=None), client=client)
        first = await browser.read_dynamic_listing(url, keywords=("Agent",), max_links=1)
        assert first.dynamic_listing["search"]["status"] == "confirmed"
        assert first.discovered_links[0].url.endswith("/3")
        assert first.dynamic_listing["search"]["recipe"]["discovery"] == "source_semantics"
        second = await browser.read_dynamic_listing(url, cursor=first.dynamic_listing["next_cursor"], keywords=("Agent",), max_links=1)
        assert second.discovered_links[0].url.endswith("/5")
        assert second.dynamic_listing["search"]["recipe_reused"]
        assert len(client.requests) == 1
        assert all(method == "GET" for method, _ in requests)


@pytest.mark.asyncio
@pytest.mark.parametrize("options", [{"inert": True}, {"private_form": True}])
async def test_model_cannot_make_inert_or_private_form_a_confirmed_search(options):
    from src.config import Settings
    from src.infrastructure.llm_client import FakeModelClient
    from src.services.source_understanding import SourceUnderstanding

    with search_site(unfamiliar=True, **options) as (url, requests):
        browser = reader()
        client = FakeModelClient(output={"control_id": 0})
        browser.search_understanding = SourceUnderstanding(Settings(_env_file=None), client=client)
        result = await browser.read_dynamic_listing(url, keywords=("Agent",), max_links=1)
        assert result.dynamic_listing["search"]["status"] != "confirmed"
        assert not any(method == "POST" for method, _ in requests)
        if options.get("private_form"):
            assert not client.requests


@pytest.mark.asyncio
async def test_model_cannot_invent_control_selectors():
    from src.config import Settings
    from src.infrastructure.llm_client import FakeModelClient
    from src.services.source_understanding import SourceUnderstanding

    with search_site(unfamiliar=True) as (url, requests):
        browser = reader()
        browser.search_understanding = SourceUnderstanding(Settings(_env_file=None),
            client=FakeModelClient(output={"control_id": 99, "selector": "#apply"}))
        result = await browser.read_dynamic_listing(url, keywords=("Agent",), max_links=1)
        assert result.dynamic_listing["search"]["status"] == "unavailable"
        assert not any("q=" in path for _, path in requests)
