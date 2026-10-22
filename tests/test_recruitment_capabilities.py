import json
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from src.services.browser_job_reader import BrowserPageSnapshot, BrowserReadError
from src.services.company_coverage import CompanyCoverage
from src.services.company_registry import CompanySource
from src.services.direct_recruitment_search import DirectRecruitmentSearch
from src.services.job_detail_scope import scope_job_document
from src.services.recruitment_context import (
    collect_recruitment_context,
    resolve_availability,
)
from src.services.recruitment_listing import inspect_listing
from src.services.url_reader import FetchedResponse, URLFetchError, parse_html_document

QUERY = "北京上海 2027届 Agent RAG 校招"
SOURCE = CompanySource(
    "unseen-company",
    "未见过的公司",
    "C",
    "https://careers.example/jobs",
    "official_career_page",
)
DETAIL = "<main><h1>Agent工程师</h1><p>工作地点：上海</p><p>招聘类型：校园招聘</p><h2>岗位职责</h2><p>负责Agent工具调用、RAG知识库研发、效果评估和生产服务部署。</p><h2>任职要求</h2><p>熟悉Python，了解数据库与分布式系统，能够完成应用研发任务。</p>{fields}<button>立即申请</button></main>"


class Reader:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    async def fetch(self, url):
        self.calls.append(url)
        value = self.pages[url]
        if isinstance(value, Exception):
            raise value
        return FetchedResponse(url, url, 200, "text/html", value.encode())


class Browser:
    def __init__(self, pages=None):
        self.pages, self.calls = pages or {}, []

    async def read_search_listing(self, url):
        self.calls.append(url)
        if url not in self.pages:
            raise BrowserReadError("unreadable")
        return BrowserPageSnapshot(url, url, "", self.pages[url], "")


def listing(ids, next_page=None):
    links = "".join(f'<a href="/jobs/{i}">Agent工程师 {i}</a>' for i in ids)
    return f"<main>{links}</main>" + (
        f'<nav><a rel="next" href="{next_page}">下一页</a></nav>' if next_page else ""
    )


async def run_direct(reader, *, source=SOURCE, states=None, browser=None, result=True):
    candidates, events = [], []
    direct = DirectRecruitmentSearch(
        sources=[source],
        query=QUERY,
        reader=reader,
        browser=browser or Browser(),
        states=states,
        on_event=lambda _, data: events.append(data),
    )

    async def verified(candidate):
        return result

    await direct.discover(candidates.extend, await_result=verified)
    return direct, candidates, events


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name,host",
    [
        ("company-alpha", "alpha.example"),
        ("company-beta", "beta.example"),
        ("unknown-987", "hiring.gamma.example"),
    ],
)
async def test_unseen_employers_share_reader_without_registry_or_company_rules(
    name, host
):
    source = replace(SOURCE, id=name, company=name, career_url=f"https://{host}/jobs")
    reader, browser = Reader({source.career_url: listing(range(1, 6))}), Browser()
    direct, jobs, _ = await run_direct(reader, source=source, browser=browser)
    assert [j.source_url for j in jobs] == [
        f"https://{host}/jobs/{i}" for i in range(1, 4)
    ]
    assert direct.states[name]["reader_kind"] == "html"
    assert direct.states[name]["reason"] == "company_read_limit"
    assert len(direct.states[name]["buffer"]) == 2
    assert browser.calls == []
    assert all(not direct.evidence[j.source_url].full_body for j in jobs)


@pytest.mark.asyncio
async def test_serialized_resume_drains_buffer_then_follows_observed_next_link():
    reader = Reader(
        {
            SOURCE.career_url: listing(range(1, 6), "?page=2"),
            SOURCE.career_url + "?page=2": listing(range(6, 8)),
        }
    )
    first, a, _ = await run_direct(reader)
    second, b, _ = await run_direct(reader, states=json.loads(json.dumps(first.states)))
    third, c, _ = await run_direct(reader, states=json.loads(json.dumps(second.states)))
    assert [j.source_job_id for j in [*a, *b, *c]] == [
        f"https://careers.example/jobs/{i}" for i in range(1, 8)
    ]
    assert reader.calls == [SOURCE.career_url, SOURCE.career_url + "?page=2"]
    assert third.states[SOURCE.id]["reason"] == "listing_boundary"
    assert third.states[SOURCE.id]["status"] == "paused"
    coverage = CompanyCoverage(
        sources=[SOURCE],
        store=SimpleNamespace(load=lambda: third.states),
        query=QUERY,
        batch_size=1,
    )
    assert coverage.next_task(third).company_id == SOURCE.id


@pytest.mark.asyncio
async def test_incomplete_verification_retries_same_buffer_without_losing_job():
    reader = Reader({SOURCE.career_url: listing([1, 2])})
    first, jobs, _ = await run_direct(reader, result=None)
    assert len(jobs) == 1 and first.states[SOURCE.id]["checked_urls"] == []
    second, jobs, _ = await run_direct(reader, states=deepcopy(first.states))
    assert len(jobs) == 2
    assert reader.calls == [SOURCE.career_url]
    assert len(second.states[SOURCE.id]["checked_urls"]) == 2


@pytest.mark.asyncio
async def test_failed_next_page_resumes_without_refetching_first_page():
    next_url = SOURCE.career_url + "?page=2"
    reader = Reader(
        {SOURCE.career_url: listing([1], "?page=2"), next_url: URLFetchError("timeout")}
    )
    first, jobs, _ = await run_direct(reader)
    assert len(jobs) == 1 and first.states[SOURCE.id]["reason"] == "entry_retry_pending"
    reader.pages[next_url] = listing([2])
    first.states[SOURCE.id]["html_queue"][0]["retry_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    second, jobs, _ = await run_direct(reader, states=deepcopy(first.states))
    assert [j.source_url for j in jobs] == ["https://careers.example/jobs/2"]
    assert reader.calls.count(SOURCE.career_url) == 1
    assert second.states[SOURCE.id]["pages_checked"] == 2


@pytest.mark.asyncio
async def test_dynamic_shell_uses_browser_and_unknown_pagination_stays_unfinished():
    reader = Reader({SOURCE.career_url: '<div id="root"></div>'})
    browser = Browser({SOURCE.career_url: listing([1]) + "<button>加载更多</button>"})
    first, jobs, _ = await run_direct(reader, browser=browser)
    assert (
        len(jobs) == 1 and first.states[SOURCE.id]["reason"] == "pagination_unresolved"
    )
    browser.pages[SOURCE.career_url] = listing([1, 2])
    second, jobs, _ = await run_direct(
        reader, browser=browser, states=deepcopy(first.states)
    )
    assert [j.source_url for j in jobs] == ["https://careers.example/jobs/2"]
    assert second.states[SOURCE.id]["status"] != "completed"


@pytest.mark.asyncio
async def test_campus_shell_does_not_spend_budget_following_social_footer():
    source = replace(SOURCE, career_url="https://careers.example/campus/")
    reader = Reader(
        {
            source.career_url: '<a href="/social/">社会招聘</a>',
            source.career_url + "position": listing([1]),
        }
    )
    browser = Browser(
        {
            source.career_url: '<a href="/social/">社会招聘</a><a href="/campus/position">校招职位</a>'
        }
    )
    _, jobs, _ = await run_direct(reader, source=source, browser=browser)
    assert len(jobs) == 1
    assert browser.calls == [source.career_url]
    assert not any("/social/" in url for url in reader.calls)


def test_listing_cta_and_accessible_pagination_are_readable_without_clicking_apply():
    result = inspect_listing(
        '<a href="/campus/position">立即投递 →</a>'
        '<a href="/apply/1">立即投递</a><nav><a href="?page=2" aria-label="下一页">'
        "<svg></svg></a></nav>",
        url=SOURCE.career_url,
    )
    assert [entry.url for entry in result.entries] == [
        "https://careers.example/campus/position"
    ]
    assert result.next_urls == (SOURCE.career_url + "?page=2",)


def test_hidden_disabled_foreign_and_cross_tenant_links_are_not_jobs_or_pagination():
    base = "https://app.mokahr.com/campus-recruitment/acme/"
    html = """<main><a href="jobs/1">Agent工程师</a>
    <section hidden><a href="jobs/2">Agent工程师</a></section>
    <aside><a href="jobs/3">Agent工程师</a></aside>
    <a aria-disabled="true" href="jobs/4">Agent工程师</a>
    <a href="/campus-recruitment/other/jobs/5">Agent工程师</a>
    <a href="https://foreign.example/jobs/6">Agent工程师</a>
    <a href="apply/7">申请Agent工程师</a></main>
    <nav><a href="?page=2" rel="next">下一页</a></nav>"""
    result = inspect_listing(html, url=base)
    assert [j.url for j in result.jobs] == [base + "jobs/1"]
    assert result.next_urls == (base + "?page=2",)
    assert not result.entries


@pytest.mark.asyncio
async def test_next_page_loop_remains_partial():
    reader = Reader(
        {
            SOURCE.career_url: listing([1], "?page=2"),
            SOURCE.career_url + "?page=2": listing([1], "/jobs"),
        }
    )
    direct, jobs, _ = await run_direct(reader)
    assert len(jobs) == 1
    assert direct.states[SOURCE.id]["reason"] == "pagination_loop"


@pytest.mark.asyncio
async def test_official_outbound_ats_is_bound_to_one_tenant():
    entry = "https://app.mokahr.com/campus-recruitment/acme/"
    reader = Reader(
        {
            SOURCE.career_url: f'<a href="{entry}">校园招聘</a>',
            entry: '<a href="jobs/1">Agent工程师</a><a href="/campus-recruitment/other/jobs/2">Agent工程师</a>',
        }
    )
    direct, jobs, _ = await run_direct(reader)
    assert [j.source_url for j in jobs] == [entry + "jobs/1"]
    evidence = direct.evidence[jobs[0].source_url]
    assert evidence.official_proof_url == SOURCE.career_url
    assert entry in evidence.official_html


async def context_for(
    html, *, url="https://unseen.example/jobs/1", pages=None, now=None
):
    document, _ = scope_job_document(html, parse_html_document(html), url=url)
    snapshots = []
    reader = Reader(pages or {})
    context = await collect_recruitment_context(
        raw_html=html,
        document=document,
        url=url,
        fetcher=reader,
        is_official=lambda _: True,
        save_snapshot=lambda source, raw: (
            snapshots.append((source, raw)) or "snapshot-1"
        ),
        now=now,
    )
    return context, reader, snapshots


@pytest.mark.parametrize(
    "fields",
    [
        "<dl><dt>岗位状态</dt><dd>招聘中</dd></dl>",
        "<table><tr><th>职位状态</th><td>招聘中</td></tr></table>",
        "<div><span>招聘状态：</span><span>招聘中</span></div>",
        "<dl><dt>Job status</dt><dd>Open</dd></dl>",
    ],
)
def test_semantic_status_fields_work_across_layouts(fields):
    assert (
        resolve_availability(
            DETAIL.format(fields=fields), url="https://unseen.example/jobs/1"
        )["value"]
        == "ACTIVE"
    )


@pytest.mark.parametrize(
    "fields",
    [
        "<aside><dl><dt>岗位状态</dt><dd>招聘中</dd></dl></aside>",
        "<dl hidden><dt>岗位状态</dt><dd>招聘中</dd></dl>",
        "<dl><dt>岗位状态</dt><dd>0</dd></dl>",
        "<p>其他职位岗位状态：招聘中</p>",
        "<button>立即申请</button>",
        "<div><span>岗位状态</span><span>招聘中</span><span>待更新</span></div>",
    ],
)
def test_status_is_not_inferred_from_hidden_related_numeric_or_ambiguous_fields(fields):
    assert (
        resolve_availability(
            DETAIL.format(fields=fields), url="https://unseen.example/jobs/1"
        )["value"]
        == "UNKNOWN"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("host", ["one.example", "two.example", "three.example"])
async def test_batch_link_is_bound_by_field_label_without_special_anchor_wording(host):
    url, batch = f"https://{host}/jobs/1", f"https://{host}/programs/2027"
    html = DETAIL.format(
        fields='<dl><dt>招聘项目</dt><dd><a href="/programs/2027">2027届应届毕业生</a></dd></dl>'
    )
    announcement = "<article><h1>校园招聘公告</h1><p>招聘对象：2027届本科、硕士或博士毕业生</p><dl><dt>批次状态</dt><dd>开放申请</dd></dl></article>"
    context, reader, snapshots = await context_for(
        html, url=url, pages={batch: announcement}
    )
    assert (
        context["status"] == "verified"
        and context["association"] == "job_scoped_batch_link"
    )
    assert reader.calls == [batch] and len(snapshots) == 1
    assert "2027届" in context["eligibility_text"]
    assert resolve_availability(html, url=url, context=context)["value"] == "ACTIVE"


def schema_html(**values):
    job = {
        "@type": "JobPosting",
        "url": "https://unseen.example/jobs/1",
        "title": "Agent工程师",
        "description": "岗位职责：负责Agent工具调用、RAG研发和上线。任职要求：熟悉Python和数据库。",
        **values,
    }
    return (
        '<script type="application/ld+json">'
        + json.dumps(job, ensure_ascii=False)
        + "</script>"
    )


@pytest.mark.asyncio
async def test_structured_eligibility_keeps_regional_and_date_qualifiers_and_never_invents_active():
    html = schema_html(
        educationRequirements="2027届海外本科毕业生，毕业时间2026年9月至2027年8月",
        validThrough="2026-12-31",
    )
    context, reader, snapshots = await context_for(
        html, now=datetime(2026, 10, 17, tzinfo=UTC)
    )
    assert context["association"] == "job_structured_data"
    assert (
        context["eligibility_text"]
        == "2027届海外本科毕业生，毕业时间2026年9月至2027年8月"
    )
    assert context["availability"]["value"] == "UNKNOWN"
    assert snapshots and not reader.calls


@pytest.mark.asyncio
async def test_structured_deadline_expires_during_cache_ttl():
    start = datetime(2026, 10, 17, 0, tzinfo=UTC)
    html = schema_html(validThrough="2026-10-17")
    context, _, _ = await context_for(html, now=start)
    assert (
        resolve_availability(
            html, url="https://unseen.example/jobs/1", context=context, now=start
        )["value"]
        == "UNKNOWN"
    )
    assert (
        resolve_availability(
            html,
            url="https://unseen.example/jobs/1",
            context=context,
            now=start + timedelta(days=1),
        )["value"]
        == "CLOSED"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("deadline", ["2026-99-99", "2026-10-01T00:00:00", 0, None])
async def test_invalid_or_timezone_ambiguous_deadline_is_unknown(deadline):
    context, _, _ = await context_for(schema_html(validThrough=deadline))
    assert context["availability"]["value"] == "UNKNOWN"


@pytest.mark.asyncio
async def test_unsupported_qualifier_object_cannot_leave_an_unqualified_cohort():
    html = schema_html(
        educationRequirements="2027届本科毕业生",
        eligibilityToWorkRequirement={"@type": "Thing", "name": "仅海外"},
    )
    context, _, _ = await context_for(html)
    assert not context


@pytest.mark.asyncio
async def test_schema_evidence_rejects_wrong_title_and_duplicate_identity():
    from src.services.recruitment_semantics import structured_context

    url = "https://unseen.example/jobs/1"
    document = parse_html_document(schema_html())
    for raw in [
        schema_html(title="其他岗位"),
        schema_html(validThrough="2020-01-01") * 2,
    ]:
        with pytest.raises(ValueError, match="identity_conflict"):
            structured_context(
                raw_html=raw,
                document=document,
                url=url,
                base={},
                save_snapshot=lambda *_: pytest.fail("must reject before snapshot"),
            )
    assert (
        structured_context(
            raw_html=schema_html(
                url="https://other.example/jobs/1", validThrough="2020-01-01"
            ),
            document=document,
            url=url,
            base={},
            save_snapshot=lambda *_: "s",
        )
        is None
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("host", ["ats-one.example", "ats-two.example"])
async def test_observed_protocol_selects_acceleration_without_company_or_host_whitelist(
    host,
):
    from urllib.parse import parse_qs, urlsplit

    source = replace(
        SOURCE, id="never-registered", career_url=f"https://{host}/campus/"
    )

    class ProtocolBrowser(Browser):
        async def read_search_listing(self, url):
            query = parse_qs(urlsplit(url).query)
            if not query:
                record = {
                    "url": f"https://{host}/api/v1/config/job/filters/1",
                    "payload": {"code": 0, "data": {}},
                }
            else:
                record = {
                    "url": f"https://{host}/api/v1/search/job/posts",
                    "request": {
                        "keyword": query["keywords"][0],
                        "offset": 0,
                        "limit": 10,
                        "location_code_list": [],
                        "subject_id_list": [],
                    },
                    "payload": {
                        "code": 0,
                        "data": {
                            "count": 1,
                            "job_post_list": [
                                {
                                    "id": "123",
                                    "title": "Agent工程师",
                                    "city_list": [{"name": "上海"}],
                                    "description": "负责Agent和RAG应用开发。",
                                    "requirement": "2027届本科毕业生。",
                                }
                            ],
                        },
                    },
                }
            return BrowserPageSnapshot(
                url,
                url,
                "",
                '<a href="/campus/position/123/detail">Agent工程师</a>',
                "",
                recruitment_api=(record,),
            )

    direct, jobs, _ = await run_direct(None, source=source, browser=ProtocolBrowser())
    assert len(jobs) == 1
    assert direct.states[source.id]["reader_kind"] == "feishu"
    assert direct.evidence[jobs[0].source_url].full_body


@pytest.mark.asyncio
async def test_formal_search_reads_generic_details_persists_evidence_and_reports_real_metrics(
    db_session, monkeypatch
):
    from sqlalchemy import select
    from sqlalchemy.orm import sessionmaker

    from src.config import Settings
    from src.domain.discovery import DiscoveryRun, LeadVerification
    from src.services import multiround_search as execution
    from src.services import web_search_service
    from src.services.discovery_results import current_run_matches

    detail_url = "https://careers.example/jobs/1"
    html = DETAIL.format(
        fields="<dl><dt>岗位状态</dt><dd>招聘中</dd></dl><p>招聘对象：2027届本科毕业生。</p>"
    )
    reader = Reader({SOURCE.career_url: listing([1]), detail_url: html})

    class Provider:
        source_id = "test"

        async def discover(self):
            return []

    monkeypatch.setattr(
        execution,
        "get_settings",
        lambda: Settings(
            _env_file=None,
            web_search_direct_sources_enabled=True,
            web_search_target_jobs=1,
            web_search_role_review_enabled=False,
            web_search_max_rounds=1,
            web_search_budget_seconds=5,
            web_search_verification_budget_seconds=3,
        ),
    )
    monkeypatch.setattr(execution, "SessionLocal", sessionmaker(bind=db_session.bind))
    monkeypatch.setattr(
        execution, "enabled_company_sources", lambda *args, **kwargs: [SOURCE]
    )
    monkeypatch.setattr(
        execution, "enabled_company_source_hosts", lambda **kwargs: {"careers.example"}
    )
    monkeypatch.setattr(execution, "SafeHTTPReader", lambda **kwargs: reader)
    monkeypatch.setattr(
        execution, "PlaywrightBrowserJobReader", lambda **kwargs: Browser()
    )
    monkeypatch.setattr(
        web_search_service, "create_web_search_provider", lambda *args: Provider()
    )
    run = DiscoveryRun(
        id="generic-formal-test",
        user_id="generic-user",
        source="test",
        source_url=SOURCE.career_url,
        search_query=QUERY,
        started_at=datetime.now(UTC),
    )
    db_session.add(run)
    db_session.commit()
    await execution.execute_multiround_search(
        run_id=run.id, user_id=run.user_id, query=QUERY, company_ids=[]
    )
    db_session.expire_all()
    matches = current_run_matches(db_session, [run])[run.id]
    assert len(matches) == 1 and matches[0]["filter_status"] == "matched"
    assert reader.calls.count(detail_url) == 1  # List titles alone never verify a job.
    records = list(
        db_session.scalars(
            select(LeadVerification).where(LeadVerification.user_id == run.user_id)
        )
    )
    assert any(
        r.result == "SNAPSHOT" and r.source_url == SOURCE.career_url for r in records
    )
    assert (
        run.usage_metrics["read_attempts"] == run.usage_metrics["read_successes"] == 1
    )
    assert run.usage_metrics["new_effective_jobs"] == 1
