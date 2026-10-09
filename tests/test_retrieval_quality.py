import json
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import func, select

from src.domain.discovery import DiscoveryRun, JobLead, LeadProvider
from src.services.browser_job_reader import BrowserReadError
from src.services.company_registry import CompanySource
from src.services.job_lead_service import JobLeadService
from src.services.job_url import canonical_job_url
from src.services.lead_presentation import discovery_kind
from src.services.lead_providers import LeadCandidate
from src.services.official_hiring_resolver import OfficialHiringResolver
from src.services.responses_search import ResponsesSearchProvider
from src.services.retrieval_quality import search_link_rejection
from src.services.url_reader import FetchedResponse, parse_html_document


def test_compacted_head_and_hidden_void_elements_do_not_hide_visible_job():
    from src.services.job_detail_scope import scope_job_document

    html = '<html><head hidden><meta hidden><link hidden></head><body><input hidden><main><span class="job-title">RAG工程师</span><div>上海、北京 校招</div><div>职位描述：构建检索服务。</div><div hidden>已关闭</div><p>任职要求：Python。</p></main></body></html>'
    parsed = parse_html_document(html)
    assert "构建检索服务" in parsed.text and "已关闭" not in parsed.text
    doc, closed = scope_job_document(html, parsed, url="https://example.com/jobs/1")
    assert not closed and doc.locations == ["上海", "北京"]


@pytest.mark.parametrize(
    "url,title",
    [
        ("https://example.com/job/2022/recruit.pdf", "2027届AI工程师"),
        ("https://example.com/feed/main/detail/abc?jobId=1", "工程师内推"),
        ("https://example.com/blog/jobs/1", "RAG工程师"),
        ("https://example.com/teachin/view/id/150698", "校园招聘宣讲会"),
    ],
)
def test_reference_pages_never_become_jobs_due_to_title_or_path(url, title):
    assert discovery_kind(url, title) == "entry"
    assert search_link_rejection(url, title, query="2027届上海校招")


def test_url_dates_do_not_exclude_real_current_jobs():
    assert (
        search_link_rejection(
            "https://example.com/jobs/2022/123", "2027届工程师", query="2027届校招"
        )
        is None
    )
    assert (
        search_link_rejection(
            "https://example.com/jobs/123", "2023届校园招聘", query="2027届校招"
        )
        == "other_cohort_announcement"
    )
    assert (
        search_link_rejection(
            "https://example.com/jobs/123", "2026届/2027届校园招聘", query="2027届校招"
        )
        is None
    )


def test_canonical_identity_keeps_job_and_tenant_selectors_including_spa():
    assert (
        canonical_job_url("https://example.com/jobs/123?utm_source=a#top")
        == "https://example.com/jobs/123"
    )
    a = "https://app.mokahr.com/social-recruitment/acme/1#/job/123?utm_source=a&project=7"
    assert canonical_job_url(a).endswith("#/job/123?project=7")
    assert canonical_job_url(a) != canonical_job_url(a.replace("acme", "other"))
    assert canonical_job_url(a) != canonical_job_url(
        a.replace("project=7", "project=8")
    )
    assert canonical_job_url("https://example.com/jobs?jobId=1") != canonical_job_url(
        "https://example.com/jobs?jobId=2"
    )


@pytest.mark.asyncio
async def test_sources_are_filtered_after_metadata_merge_and_full_response_is_kept():
    payload = {
        "status": "completed",
        "output": [
            {
                "type": "web_search_call",
                "status": "completed",
                "action": {
                    "sources": [
                        {
                            "url": "https://example.com/jobs/1?utm_source=model",
                            "title": "RAG工程师",
                        },
                        {"url": "https://example.com/jobs/2", "title": "后端工程师"},
                        {
                            "url": "https://example.com/feed/main/detail/3",
                            "title": "工程师内推",
                        },
                        {"url": "https://example.com/job/old.pdf", "title": "招聘简章"},
                        {"url": "https://en.wikipedia.org/wiki/AI", "title": "AI"},
                    ]
                },
            },
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": "岗位：https://example.com/jobs/1"}
                ],
            },
        ],
    }
    provider = ResponsesSearchProvider(
        query="2027届上海校招",
        base_url="https://api.example/v1",
        api_key="test",
        model="test",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
    )
    candidates = await provider.discover()
    assert [c.source_url for c in candidates] == [
        "https://example.com/jobs/1",
        "https://example.com/jobs/2",
    ]
    assert candidates[0].title_hint == "RAG工程师"
    assert len(provider.last_evidence["rejected_links"]) == 3
    assert json.loads(provider.last_evidence["raw_response"]) == payload


def test_tracking_variants_with_different_provider_ids_share_one_persisted_lead(
    db_session,
):
    run = DiscoveryRun(
        id="quality-run",
        user_id="u",
        source="test",
        source_url="https://example.com",
        started_at=datetime.now(UTC),
    )
    db_session.add(run)
    db_session.commit()
    service = JobLeadService(db_session)
    first = service.create_lead(
        user_id="u",
        discovery_run_id=run.id,
        provider=LeadProvider.EXTERNAL_AGENT,
        source_id="search",
        source_job_id="hash-a",
        source_url="https://example.com/jobs/1?utm_source=old",
        search_snippet="first",
    )
    first.selection_status = "SAVED"
    db_session.commit()
    second = service.create_lead(
        user_id="u",
        discovery_run_id=run.id,
        provider=LeadProvider.EXTERNAL_AGENT,
        source_id="search",
        source_job_id="hash-b",
        source_url="https://example.com/jobs/1",
        title_hint="RAG工程师",
        search_snippet="second",
    )
    assert first.id == second.id and second.selection_status == "SAVED"
    assert second.extracted_fields["title"] == "RAG工程师"
    assert "first" in second.search_snippet and "second" in second.search_snippet
    assert db_session.scalar(select(func.count(JobLead.id))) == 1


@pytest.mark.asyncio
async def test_official_resolver_requires_observed_tenant_and_reuses_its_proof(
    db_session,
):
    source = CompanySource(
        "acme", "Acme", "A", "https://acme.example/careers", "official_career_page"
    )
    seen = []

    async def fetch(url):
        seen.append(url)
        return FetchedResponse(
            url,
            url,
            200,
            "text/html",
            b'<a href="https://app.mokahr.com/campus-recruitment/acme/1">Join</a>',
        )

    async def browser(url):
        raise AssertionError("Static outbound links are sufficient")

    resolver = OfficialHiringResolver(
        sources=[source],
        reader=SimpleNamespace(fetch=fetch),
        browser=SimpleNamespace(read=browser),
    )
    candidate = LeadCandidate(
        provider=LeadProvider.EXTERNAL_AGENT,
        source_url="https://app.mokahr.com/campus-recruitment/acme/1#/job/123",
        discovered_at=datetime.now(UTC),
        title_hint="Acme RAG工程师",
    )
    snapshots = []

    def save(url, html):
        snapshots.append((url, html))
        return "snapshot1"

    proof = await resolver.resolve(candidate, record_snapshot=save)
    assert proof.company == "Acme" and proof.snapshot_id == "snapshot1"
    assert len(seen) == 1
    assert (
        await resolver.resolve(
            replace(
                candidate,
                source_url=candidate.source_url.replace("123", "456"),
                title_hint=None,
            ),
            record_snapshot=save,
        )
        == proof
    )
    assert (
        await resolver.resolve(
            replace(
                candidate, source_url=candidate.source_url.replace("/acme/", "/other/")
            ),
            record_snapshot=save,
        )
        is None
    )
    service = JobLeadService(db_session)
    lead = service.capture_candidate(user_id="u", candidate=candidate)
    service.record_official_link(
        user_id="u",
        lead_id=lead.id,
        source_url=candidate.source_url,
        entry_url=proof.entry_url,
        from_url=proof.from_url,
        scope_url=proof.scope_url,
        snapshot_id=proof.snapshot_id,
        company=proof.company,
    )
    assert service._official_target(lead, candidate.source_url, {"acme.example"})
    assert not service._official_target(
        lead, candidate.source_url.replace("/acme/", "/other/"), {"acme.example"}
    )


@pytest.mark.asyncio
async def test_third_party_redirect_and_company_name_alone_do_not_prove_ownership():
    source = CompanySource(
        "acme", "Acme", "A", "https://acme.example/careers", "official_career_page"
    )

    async def fetch(url):
        return FetchedResponse(
            url,
            "https://unrelated.example/careers",
            200,
            "text/html",
            b'<a href="https://acme.jobs.feishu.cn/1">Join</a>',
        )

    async def browser(url):
        raise BrowserReadError("unavailable")

    resolver = OfficialHiringResolver(
        sources=[source],
        reader=SimpleNamespace(fetch=fetch),
        browser=SimpleNamespace(read=browser),
    )
    candidate = LeadCandidate(
        provider=LeadProvider.EXTERNAL_AGENT,
        source_url="https://acme.jobs.feishu.cn/1/position/123/detail",
        title_hint="Acme RAG工程师",
        discovered_at=datetime.now(UTC),
    )
    assert await resolver.resolve(candidate, record_snapshot=lambda *args: None) is None


@pytest.mark.parametrize("selection", ["SAVED", "IGNORED"])
def test_historical_tracking_duplicates_preserve_user_selection(db_session, selection):
    service = JobLeadService(db_session)
    chosen = service.create_lead(
        user_id="u",
        provider=LeadProvider.EXTERNAL_AGENT,
        source_url="https://example.com/jobs/1?utm_source=old",
    )
    chosen.selection_status = selection
    chosen.normalized_url = chosen.source_url  # Legacy identity included tracking.
    db_session.commit()
    duplicate = service.create_lead(
        user_id="u",
        provider=LeadProvider.EXTERNAL_AGENT,
        source_url="https://example.com/jobs/1",
        title_hint="RAG工程师",
    )
    assert chosen.id != duplicate.id
    displayed = service.list_leads(user_id="u")
    assert len(displayed) == 1 and displayed[0].selection_status == selection
    assert len(service.list_leads(user_id="another-user")) == 0


@pytest.mark.asyncio
async def test_search_workflow_proves_ats_ownership_then_verifies_and_filters(
    db_session, monkeypatch
):
    from sqlalchemy.orm import sessionmaker

    from src.config import Settings
    from src.domain.discovery import LeadVerification
    from src.services import multiround_search as execution
    from src.services import web_search_service

    source = CompanySource(
        "acme", "Acme", "A", "https://acme.example/careers", "official_career_page"
    )
    job_url = "https://acme.jobs.feishu.cn/1/position/123/detail"
    reads = []

    class Provider:
        source_id = "test"

        async def discover(self):
            return [
                LeadCandidate(
                    provider=LeadProvider.EXTERNAL_AGENT,
                    source_url=job_url,
                    discovered_at=datetime.now(UTC),
                    title_hint="Acme RAG工程师-2027届",
                )
            ]

    class Reader:
        async def fetch(self, url):
            reads.append(url)
            if url == source.career_url:
                html = '<a href="https://acme.jobs.feishu.cn/1">校招</a>'
            else:
                assert url == job_url
                html = "<main><h1>RAG工程师</h1><p>工作地点：上海</p><p>校园招聘</p><p>招聘对象：2027届毕业生。</p><p>职位描述：负责RAG检索增强生成应用的开发与部署，参与知识库的数据处理、检索服务与问答系统的设计，实现检索效果评估和性能优化。</p><p>任职要求：本科及以上，熟悉Python。</p><button>投递</button></main>"
            return FetchedResponse(url, url, 200, "text/html", html.encode())

    async def browser(url):
        raise AssertionError("Static official links and JD are sufficient")

    settings = Settings(
        _env_file=None,
        web_search_decision_mode="rule",
        web_search_max_rounds=1,
        web_search_budget_seconds=5,
        web_search_verification_budget_seconds=5,
    )
    monkeypatch.setattr(execution, "get_settings", lambda: settings)
    monkeypatch.setattr(execution, "SessionLocal", sessionmaker(bind=db_session.bind))
    monkeypatch.setattr(
        execution, "enabled_company_source_hosts", lambda: {"acme.example"}
    )
    monkeypatch.setattr(execution, "enabled_company_sources", lambda *args: [source])
    monkeypatch.setattr(execution, "SafeHTTPReader", lambda **kwargs: Reader())
    monkeypatch.setattr(
        execution,
        "PlaywrightBrowserJobReader",
        lambda **kwargs: SimpleNamespace(read=browser),
    )
    monkeypatch.setattr(
        web_search_service, "create_web_search_provider", lambda *args: Provider()
    )
    run = DiscoveryRun(
        id="ownership-run",
        user_id="u",
        source="test",
        source_url="https://acme.example",
        search_query="2027届 上海 RAG 校招",
        started_at=datetime.now(UTC),
    )
    db_session.add(run)
    db_session.commit()
    await execution.execute_multiround_search(
        run_id=run.id, user_id="u", query=run.search_query, company_ids=[source.id]
    )
    db_session.expire_all()
    lead = db_session.scalar(select(JobLead).where(JobLead.discovery_run_id == run.id))
    assert lead.status == "VERIFIED" and lead.job_posting_id
    assert reads == [source.career_url, job_url]
    proof = db_session.scalar(
        select(LeadVerification).where(LeadVerification.result == "OFFICIAL_LINK")
    )
    assert proof.field_evidence["company"] == "Acme"
    assert proof.field_evidence["snapshot_id"]
    assert run.result_matches[0]["filter_status"] == "matched"
    assert any(item["tool"] == "official_ownership" for item in run.agent_trace)


@pytest.mark.parametrize(
    "path", ["jobdetail/CC123.htm", "job-detail/123", "position_detail/123"]
)
def test_detail_endpoint_with_identifier_is_retained_without_search_title(path):
    url = "https://example.com/" + path
    assert discovery_kind(url) == "job"
    assert search_link_rejection(url, None, query="2027届上海校招") is None


@pytest.mark.asyncio
async def test_tenant_host_routes_official_read_before_incidental_snippet_companies():
    sources = [
        CompanySource(
            "other", "其他公司", "A", "https://other.example/careers", "official"
        ),
        CompanySource(
            "xiaomi", "小米", "A", "https://xiaomi.example/careers", "official"
        ),
    ]
    seen = []

    async def fetch(url):
        seen.append(url)
        return FetchedResponse(
            url,
            url,
            200,
            "text/html",
            b'<a href="https://xiaomi.jobs.f.mioffice.cn/campus/">Jobs</a>',
        )

    resolver = OfficialHiringResolver(
        sources=sources,
        reader=SimpleNamespace(fetch=fetch),
        browser=SimpleNamespace(),
        max_companies=1,
    )
    candidate = LeadCandidate(
        provider=LeadProvider.EXTERNAL_AGENT,
        source_url="https://xiaomi.jobs.f.mioffice.cn/campus/position/123/detail",
        discovered_at=datetime.now(UTC),
        search_snippet="其他公司也在招聘",
    )
    proof = await resolver.resolve(candidate, record_snapshot=lambda *args: "snapshot")
    assert proof.company == "小米" and seen == [sources[1].career_url]
    assert (
        await resolver.resolve(
            replace(
                candidate,
                source_url=candidate.source_url.replace("xiaomi.jobs", "other.jobs"),
                search_snippet=None,
            ),
            record_snapshot=lambda *args: None,
        )
        is None
    )


def test_resource_hosts_are_exact_and_do_not_trust_the_ats_platform():
    from src.services.browser_job_reader import recruitment_resource_hosts
    from src.services.recruitment_trust import hiring_scope

    assert recruitment_resource_hosts("https://campus.nio.com/") == {
        "cdn-fx.nio.com",
        "cdn-campus.nio.com",
    }
    assert (
        recruitment_resource_hosts("https://campus.nio.com.attacker.example/") == set()
    )
    assert recruitment_resource_hosts("https://xiaomi.jobs.f.mioffice.cn/campus/") == {
        "lf-package-cn.feishucdn.com"
    }
    assert hiring_scope("https://jobs.f.mioffice.cn/") is None
    assert hiring_scope("https://xiaomi.jobs.f.mioffice.cn/campus/") == (
        "xiaomi.jobs.f.mioffice.cn",
        "/",
    )
