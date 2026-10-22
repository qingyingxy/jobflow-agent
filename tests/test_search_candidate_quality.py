"""Regressions from the six-company trial; no employer-specific selectors."""

import asyncio
from dataclasses import replace

import pytest
from sqlalchemy import select

from src.domain.discovery import JobLead
from src.services.job_detail_scope import DetailScopeError, scope_job_document
from src.services.job_fact_verifier import verify_page_facts
from src.services.lead_presentation import discovery_kind
from src.services.retrieval_quality import search_link_rejection
from src.services.search_pipeline import run_search_pipeline
from src.services.search_scheduling import (
    VerificationQueue,
    candidate_priority,
    candidate_source,
)
from src.services.url_reader import parse_html_document
from src.services.vision_job_extraction import needs_visual_fallback
from tests.test_search_scheduling import lead

QUERY = "北京上海 AI Agent RAG 2027届校招"


@pytest.mark.parametrize("path", [
    "/community/detail/imagetext/123.html", "/community/detail/ugc_article/123.html",
    "/community/topic/123.html", "/ugc_article/123.html", "/help/topic/1-1.html",
    "/community/articleDetail/123.html", "/article-detail/123.html", "/article_detail/123.html",
])
def test_reference_routes_never_become_jobs_from_recruitment_titles(path):
    url = "https://unseen.example" + path
    assert search_link_rejection(url, "Agent校招工程师", query=QUERY)
    assert discovery_kind(url, "Agent校招工程师", observed_title=True) == "entry"


@pytest.mark.parametrize("path", [
    "/community/jobs/123", "/jobs/community-engineer", "/campus/detail?jobAdId=abc",
    "/position/detail?jobUnionId=123",
])
def test_actual_detail_routes_are_retained(path):
    url = "https://unseen.example" + path
    assert search_link_rejection(url, "Agent校招工程师", query=QUERY) is None
    assert discovery_kind(url) == "job"


@pytest.mark.asyncio
async def test_old_reference_candidate_is_retained_without_http_browser_or_expansion(db_session, monkeypatch):
    from src.services import multiround_search as execution
    from tests.test_search_bottlenecks import configure_execution, execute

    reference = replace(lead(1, host="official.example"),
                        source_url="https://official.example/community/detail/123.html")

    class Provider:
        source_id = "test"

        async def discover(self):
            return [reference]

    async def forbidden(*args, **kwargs):
        pytest.fail("Reference sources must not consume detail or entry reads")

    configure_execution(db_session, monkeypatch, lambda *_: Provider(), web_search_max_rounds=1)
    monkeypatch.setattr(execution, "expand_entry", forbidden)
    monkeypatch.setattr(execution.JobLeadService, "verify_url", forbidden)
    monkeypatch.setattr(execution.JobLeadService, "verify_browser", forbidden)
    await execute()
    db_session.expire_all()
    saved = db_session.scalar(select(JobLead))
    assert saved.source_url == reference.source_url
    assert saved.status == "REJECTED_NON_JOB" and saved.job_posting_id is None
    assert saved.retry_state["mode"] == "stopped"


def priority(candidate):
    return candidate_priority(candidate, query=QUERY, official_hosts={"a.example"})


@pytest.mark.asyncio
async def test_rotation_does_not_promote_unrelated_company_over_waiting_target_job():
    queue = VerificationQueue(priority=priority, source_key=candidate_source)
    for i in range(4):
        queue.put_nowait(lead(i, title="Agent校招工程师"))
    queue.put_nowait(lead(10, host="b.example", title="市场运营"))
    selected = []
    while queue.qsize():
        item = await queue.get()
        selected.append(item.candidate)
        queue.task_done(item)
    assert [candidate.title_hint for candidate in selected[:4]] == ["Agent校招工程师"] * 4
    assert selected[-1].source_url.endswith("/10")


def test_wrong_recruitment_type_is_deferred_without_discarding_candidates():
    candidates = [lead(1, title="Agent实习工程师"), lead(2, title="后端工程师"),
                  lead(3, title="Agent校招工程师")]
    assert [c.source_url for c in sorted(candidates, key=priority)] == [
        candidates[2].source_url, candidates[1].source_url, candidates[0].source_url,
    ]


@pytest.mark.asyncio
async def test_better_title_promotes_pending_url_preserves_official_proof_and_reads_once():
    started, updated = asyncio.Event(), asyncio.Event()
    seen = []
    original = lead(2, official="https://a.example/careers")

    async def search(number, _):
        if number == 1:
            return [lead(1, title="Agent校招工程师"), lead(3, title="后端工程师"), original]
        await started.wait()
        updated.set()
        return [replace(original, title_hint="RAG校招工程师", official_entry_url=None)]

    async def verify(candidate):
        seen.append(candidate)
        if candidate.source_url.endswith("/1"):
            started.set()
            await updated.wait()
        return candidate.source_url, False

    await run_search_pipeline(search=search, verify=verify, report=lambda *_: None,
                              canonicalize=lambda url: url, priority=priority, max_rounds=2,
                              verification_seconds=1, seconds=2)
    assert [c.source_url for c in seen] == [lead(1).source_url, lead(2).source_url, lead(3).source_url]
    assert seen[1].title_hint == "RAG校招工程师"
    assert seen[1].official_entry_url == original.official_entry_url


def component_html(field="工作城市", *, two_jobs=False):
    extra = '<section><h1>另一个工程师</h1><p>岗位职责：研发另一个产品。</p></section>' if two_jobs else ""
    return f'''<div class="global-header">社会招聘 深圳市</div>
    <div class="custom_detail_wrapper">
      <section class="detail-header"><span class="title">AI全栈工程师</span>
        <div>应届-校园招聘</div><div>工作地点：北京市、上海市</div></section>
      <section><div class="title">岗位职责</div><p>参与AI应用研发，包括RAG检索管线和Agent工作流编排。</p></section>
      <section><div class="title">任职要求</div><p>计算机相关专业本科及以上，熟悉Python。</p></section>
      <section><div class="title">{field}</div><p>北京市、上海市</p></section>
      {extra}
    </div><div class="global-footer">招聘已结束</div>'''


@pytest.mark.parametrize("field", ["工作城市", "工作地点", "招聘对象", "学历要求", "Job location"])
def test_detail_metadata_headings_do_not_create_fake_second_jobs(field):
    html = component_html(field)
    doc, closed = scope_job_document(html, parse_html_document(html), url="https://unseen.example/jobs/123")
    assert doc.title == "AI全栈工程师"
    assert "RAG检索管线" in doc.text and "熟悉Python" in doc.text
    assert "社会招聘" not in doc.text and "招聘已结束" not in doc.text
    facts = verify_page_facts(doc)
    assert facts.locations == ["北京市", "上海市"] and facts.job_type == "campus"
    assert not closed and not needs_visual_fallback(html, "https://unseen.example/jobs/123")


def test_two_real_job_titles_still_require_disambiguation():
    html = component_html(two_jobs=True)
    with pytest.raises(DetailScopeError, match="唯一"):
        scope_job_document(html, parse_html_document(html), url="https://unseen.example/jobs/123")
