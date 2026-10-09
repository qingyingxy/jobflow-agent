"""Regressions from the 2026-10-08 public search audit and validity controls."""

import pytest
from sqlalchemy import select

from src.domain.discovery import LeadProvider, LeadVerification
from src.services.browser_job_reader import (
    BrowserPageSnapshot,
    BrowserReadError,
    bounded_page_html,
    recruitment_resource_hosts,
    wait_for_recruitment_content,
)
from src.services.discovery_matching import classify_discovery_job
from src.services.discovery_sources import JobStub
from src.services.job_detail_scope import closed_page_notice, scope_job_document
from src.services.job_fact_verifier import verify_page_facts
from src.services.job_lead_service import JobLeadService, LeadVerificationFailure
from src.services.lead_presentation import discovery_kind
from src.services.url_reader import FetchedResponse, parse_html_document


def test_resource_exception_is_limited_to_observed_cdn_and_employer():
    assert recruitment_resource_hosts(
        "https://jobs.bytedance.com/campus/position/1/detail"
    ) == {"lf-package-cn.feishucdn.com"}
    assert recruitment_resource_hosts("https://untrusted.example/jobs/1") == set()


def test_new_scoped_verification_can_retract_previous_incorrect_type(db_session):
    service = JobLeadService(db_session)

    def verify(number, job_type):
        lead = service.create_lead(
            user_id="type-correction",
            provider=LeadProvider.EXTERNAL_AGENT,
            source_url=f"https://example.com/jobs/{number}",
        )
        return service.verify_stub(
            user_id="type-correction",
            lead_id=lead.id,
            stub=JobStub(
                source_id="audit",
                source_job_id="same-job",
                company="示例公司",
                title="工程师",
                locations=["上海"],
                job_type=job_type,
                published_at=None,
                detail_url="https://example.com/jobs/1",
                raw_content="岗位职责：研发服务。任职要求：Python。",
            ),
            source_type="verified_html",
        )

    first = verify(1, "campus")
    second = verify(2, None)
    assert second.posting.id == first.posting.id
    assert second.posting.job_type is None


@pytest.mark.parametrize(
    "path",
    [
        "/web/job/job_info_list/3",
        "/web/job/job_info_list/3?requirementId=216955",
        "/jobs/search/engineering?jobId=123",
        "/position/job-list/2?positionId=123",
    ],
)
def test_listing_is_not_a_job_even_with_card_title_or_id(path):
    assert discovery_kind("https://example.com" + path, "AI工程师") == "entry"


def test_audited_footer_and_adjacent_fields_do_not_become_job_facts():
    html = """<h1>AI Infra优化工程师</h1>
    <div>职位类型：研发类 工作地点：上海市 所属部门： AI Infra研发部 招聘人数：1 发布时间：2026-05-13</div>
    <div>岗位职责：开发大模型服务。</div><div>任职要求：3年以上AI系统/HPC/深度学习框架/编译器开发经验。</div>
    <div class="footer"><span>友情链接</span><a>京东校招</a></div>"""
    doc, _ = scope_job_document(
        html, parse_html_document(html), url="https://example.com/jobs/1"
    )
    facts = verify_page_facts(doc)
    assert facts.job_type is None
    assert facts.locations == ["上海市"]
    assert "京东校招" not in doc.text
    assert "3年以上" in doc.text


@pytest.mark.parametrize(
    "body",
    [
        "招聘类型：校园招聘。面向2027届毕业生。岗位职责：开发RAG服务。任职要求：Python。",
        "招聘类型：校园招聘。面向2027届毕业生。岗位职责：开发RAG服务。任职要求：有实习经验优先。",
        "招聘类型：校园招聘。面向2027届毕业生。岗位职责：开发RAG服务。任职要求：计算机专业。",
    ],
)
def test_valid_campus_controls_survive_social_navigation_and_closed_recommendations(
    body,
):
    html = f'<nav>社会招聘</nav><main><h1>RAG开发工程师</h1><div>工作地点：上海</div><div>{body}</div><aside>该职位已下线</aside></main><div class="siteFooter">社招</div>'
    doc, closed = scope_job_document(
        html, parse_html_document(html), url="https://example.com/jobs/1"
    )
    facts = verify_page_facts(doc)
    assert not closed
    evidence = facts.evidence["job_type"]
    assert evidence["value"] == "campus"
    assert (
        doc.text[evidence["start_char"] : evidence["end_char"]]
        == evidence["source_text"]
    )
    job = JobStub(
        source_id="test",
        source_job_id="1",
        company="test",
        title=facts.title,
        locations=facts.locations,
        job_type=facts.job_type,
        published_at=None,
        raw_content=doc.text,
        detail_url="https://example.com/jobs/1",
    )
    assert (
        classify_discovery_job(job, query="2027届上海RAG校招，不考虑社招").filter_status
        == "matched"
    )


@pytest.mark.parametrize(
    "body",
    [
        "<aside>该职位已下线</aside>",
        "<div hidden>该职位已下线</div>",
        '<div class="recommended">该职位已下线</div>',
        "<h2>相关职位</h2><div>该职位已下线</div>",
    ],
)
def test_closure_must_describe_current_visible_job(body):
    html = "<main><h1>RAG工程师</h1><p>岗位职责：开发服务</p>" + body + "</main>"
    assert closed_page_notice(html, url="https://example.com/jobs/1") is None
    assert (
        closed_page_notice(
            "<main>该职位已下线</main>", url="https://example.com/jobs/list"
        )
        is None
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["http", "browser"])
async def test_removed_jd_records_closure_evidence_without_fabricating_posting(
    db_session, mode
):
    html = "<nav>校园招聘 社会招聘</nav><main><div>该职位已下线</div></main>"

    class Reader:
        async def fetch(self, url):
            return FetchedResponse(url, url, 200, "text/html", html.encode())

        async def read(self, url):
            return BrowserPageSnapshot(
                url, url, "招聘官网", html, "该职位已下线", html_compacted=True
            )

    service = JobLeadService(db_session)
    lead = service.create_lead(
        user_id="audit",
        provider=LeadProvider.EXTERNAL_AGENT,
        source_url="https://example.com/campus/position/123/detail",
    )
    with pytest.raises(LeadVerificationFailure, match="该职位已下线"):
        method = service.verify_url if mode == "http" else service.verify_browser
        await method(
            user_id="audit",
            lead_id=lead.id,
            reader=Reader(),
            official_hosts={"example.com"},
            official_only=True,
        )
    db_session.refresh(lead)
    assert lead.status == "CLOSED" and lead.job_posting_id is None
    assert lead.verified_at is not None
    evidence = db_session.scalar(
        select(LeadVerification).where(
            LeadVerification.lead_id == lead.id, LeadVerification.result == "CLOSED"
        )
    )
    assert evidence.field_evidence["availability"]["source_text"] == "该职位已下线"
    assert evidence.field_evidence["availability"]["snapshot_id"]


@pytest.mark.asyncio
async def test_browser_compacts_bundles_keeps_links_and_waits_for_delayed_closure():
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page()
            await page.set_content(
                '<nav>校园招聘</nav><main id="content">加载中</main><style>.gone {display:none}</style><div class="gone">该职位已关闭</div><a href="/jobs/1">岗位</a>'
                + '<script type="application/json">'
                + "x" * 600000
                + "</script>"
            )
            await page.evaluate(
                "setTimeout(() => document.getElementById('content').innerText = '该职位已下线', 200)"
            )
            await wait_for_recruitment_content(page, timeout_ms=2500)
            html, compacted = await bounded_page_html(page, max_chars=20000)
            assert compacted and len(html) < 20000
            assert 'href="/jobs/1"' in html
            assert (
                closed_page_notice(html, url="https://example.com/jobs/1")
                == "该职位已下线"
            )
            await page.set_content("<main>" + "x" * 22000 + "</main>")
            with pytest.raises(BrowserReadError) as exc:
                await bounded_page_html(page, max_chars=20000)
            assert exc.value.code == "browser_response_too_large"
        finally:
            await browser.close()
