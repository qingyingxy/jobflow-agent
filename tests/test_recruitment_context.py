import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from src.domain.discovery import LeadProvider
from src.services.discovery_matching import (
    apply_posting_availability,
    classify_discovery_job,
)
from src.services.job_detail_scope import scope_job_document
from src.services.job_lead_service import JobLeadService
from src.services.recruitment_context import (
    collect_recruitment_context,
    resolve_availability,
)
from src.services.search_goal_service import posting_stub
from src.services.url_reader import FetchedResponse, URLFetchError, parse_html_document

URL = "https://jobs.example.com/campus/job/17"
BATCH = "https://jobs.example.com/batch/2027"
HTML = '<title>Agent开发工程师</title><main><h1>Agent开发工程师</h1><p>工作地点：北京</p><p>招聘类型：校园招聘</p><a href="/batch/2027">招聘批次公告</a><p>岗位职责：开发Agent与RAG系统，负责文档检索、工具调用、效果评估、服务部署与运行监控。</p><h2>任职要求</h2><p>熟悉Python，了解数据库与分布式服务，具备软件研发和团队协作能力。</p><button>立即申请</button></main>'
ANNOUNCEMENT = "<main><h1>校园招聘公告</h1><p>招聘对象：2027届应届毕业生。</p><p>批次状态：开放申请</p></main>"


class Reader:
    def __init__(self, pages, final_url=None):
        self.pages, self.calls, self.final_url = pages, [], final_url

    async def fetch(self, url):
        self.calls.append(url)
        value = self.pages[url]
        if isinstance(value, Exception):
            raise value
        raw = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        return FetchedResponse(
            requested_url=url,
            final_url=self.final_url or url,
            status_code=200,
            content_type="text/html",
            body=raw.encode(),
        )


async def collect(html=HTML, url=URL, pages=None, **kwargs):
    snapshots = []
    reader = Reader(pages or {BATCH: ANNOUNCEMENT})
    doc, _ = scope_job_document(html, parse_html_document(html), url=url)
    context = await collect_recruitment_context(
        raw_html=html,
        document=doc,
        url=url,
        fetcher=reader,
        is_official=lambda _: True,
        save_snapshot=lambda source, raw: (
            snapshots.append((source, raw)) or f"snapshot-{len(snapshots)}"
        ),
        **kwargs,
    )
    return context, reader, snapshots


@pytest.mark.asyncio
async def test_associated_batch_persists_without_changing_jd_and_matches_cohort(
    db_session,
):
    service = JobLeadService(db_session)
    lead = service.create_lead(
        user_id="batch", provider=LeadProvider.EXTERNAL_AGENT, source_url=URL
    )
    result = await service.verify_url(
        user_id="batch",
        lead_id=lead.id,
        reader=Reader({URL: HTML, BATCH: ANNOUNCEMENT}),
        official_hosts={"jobs.example.com"},
    )
    posting = result.posting
    assert posting.recruitment_context["status"] == "verified"
    assert posting.availability_status == "ACTIVE"
    assert "2027届" not in posting.raw_content
    db_session.expire_all()
    match = classify_discovery_job(
        posting_stub(posting), query="北京 2027届 Agent 校招"
    )
    cohort = next(c for c in match.checks if c["field"] == "graduation_year")
    assert cohort["status"] == "matched"
    assert cohort["source_url"] == BATCH
    assert cohort["snapshot_id"]
    checks = service.list_verifications(user_id="batch", lead_id=lead.id)
    assert any(c.source_type == "recruitment_context_snapshot" for c in checks)
    assert any(
        c.field_evidence.get("availability", {}).get("value") == "ACTIVE"
        for c in checks
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "link",
    [
        '<nav><a href="/batch/2027">招聘批次公告</a></nav>',
        '<aside><a href="/batch/2027">招聘批次公告</a></aside>',
        '<a href="/batch/2027" hidden>招聘批次公告</a>',
        '<a href="https://other.example.com/batch/2027">招聘批次公告</a>',
        '<a href="/batch/2027">招聘批次公告</a><a href="/batch/2026">招聘批次公告</a>',
    ],
)
async def test_unrelated_hidden_external_or_ambiguous_links_are_not_used(link):
    context, reader, _ = await collect(
        html=HTML.replace('<a href="/batch/2027">招聘批次公告</a>', link)
    )
    assert context.get("status") != "verified"
    assert reader.calls == []


@pytest.mark.asyncio
async def test_shared_ats_tenant_boundary_is_not_crossed():
    html = HTML.replace("/batch/2027", "/campus-recruitment/other/batch/2027")
    context, reader, _ = await collect(
        html, url="https://app.mokahr.com/campus-recruitment/acme/jobs/17"
    )
    assert context["status"] == "unconfirmed"
    assert reader.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [URLFetchError("timeout"), "<main><h1>公司新闻</h1><p>成立于2027年。</p></main>"],
)
async def test_unreadable_or_unrecognized_batch_keeps_job_unknown(body):
    context, _, _ = await collect(pages={BATCH: body})
    assert context["status"] == "unconfirmed"
    assert resolve_availability(HTML, url=URL, context=context)["value"] == "UNKNOWN"


@pytest.mark.asyncio
async def test_redirect_cannot_establish_association():
    reader = Reader(
        {BATCH: ANNOUNCEMENT}, final_url="https://other.example.com/batch/2027"
    )
    doc, _ = scope_job_document(HTML, parse_html_document(HTML), url=URL)
    result = await collect_recruitment_context(
        raw_html=HTML,
        document=doc,
        url=URL,
        fetcher=reader,
        is_official=lambda _: True,
        save_snapshot=lambda *args: "s",
    )
    assert result["status"] == "unconfirmed"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        "wrong_job",
        "wrong_title",
        "wrong_batch",
        "wrong_batch_name",
        "duplicate_batch",
        "api_error",
        "good",
    ],
)
async def test_oppo_exact_job_and_project_association_without_inventing_status(change):
    url = "https://careers.oppo.com/university/oppo/campus/post/1795?recruitType=Intern"
    endpoint = "https://careers.oppo.com/openapi/position/detail?id=1795"
    projects = "https://careers.oppo.com/openapi/position/project/list"
    data = {
        "idRecruitPosition": 1795,
        "positionName": "Agent开发工程师",
        "projectId": 30,
        "projectName": "2027届应届生校园招聘",
        "positionStatus": 0,
    }
    batch = {
        "idRecruitProject": 30,
        "projectName": data["projectName"],
        "recruitRequire": "招聘对象：2027届应届毕业生",
        "recruitmentTypeName": "应届生",
    }
    if change == "wrong_job":
        data["idRecruitPosition"] = 1799
    if change == "wrong_title":
        data["positionName"] = "其他工程师"
    if change == "wrong_batch":
        batch["idRecruitProject"] = 31
    if change == "wrong_batch_name":
        batch["projectName"] = "2026届校园招聘"
    payload = {"code": 1 if change == "api_error" else 0, "data": data}
    context, reader, snapshots = await collect(
        url=url,
        pages={
            endpoint: payload,
            projects: {
                "code": 0,
                "data": [batch, batch] if change == "duplicate_batch" else [batch],
            },
        },
    )
    assert context["status"] == ("verified" if change == "good" else "unconfirmed")
    assert resolve_availability(HTML, url=url, context=context)["value"] == "UNKNOWN"
    if change == "good":
        assert context["batch_id"] == "30"
        assert context["availability"]["raw_position_status"] == 0
        assert len(reader.calls) == len(snapshots) == 2


@pytest.mark.parametrize(
    "html,expected",
    [
        (HTML, "UNKNOWN"),
        (HTML.replace("</main>", "<p>岗位状态：招聘中</p></main>"), "ACTIVE"),
        (HTML.replace("</main>", "<p>岗位已关闭</p></main>"), "CLOSED"),
        (HTML + "<aside>岗位已关闭</aside>", "UNKNOWN"),
        (HTML.replace("</main>", "<p hidden>岗位已关闭</p></main>"), "UNKNOWN"),
        ("<nav>岗位状态：招聘中</nav><main>网页加载中</main>", "UNKNOWN"),
    ],
)
def test_only_scoped_explicit_status_is_accepted(html, expected):
    assert resolve_availability(html, url=URL)["value"] == expected


@pytest.mark.asyncio
async def test_closed_dominates_and_disabled_or_stale_or_wrong_job_cannot_open():
    context, _, _ = await collect()
    assert resolve_availability(HTML, url=URL, context=context)["value"] == "ACTIVE"
    for attr in ["disabled", 'aria-disabled="true"', 'class="is-disabled"', "hidden"]:
        html = HTML.replace("<button>", f"<button {attr}>")
        assert (
            resolve_availability(html, url=URL, context=context)["value"] == "UNKNOWN"
        )
    assert (
        resolve_availability(
            HTML.replace("</main>", "<p>岗位已关闭</p></main>"),
            url=URL,
            context=context,
        )["value"]
        == "CLOSED"
    )
    assert (
        resolve_availability(HTML, url=URL, context={**context, "job_url": URL + "8"})[
            "value"
        ]
        == "UNKNOWN"
    )
    context["checked_at"] = (datetime.now(UTC) - timedelta(days=8)).isoformat()
    assert resolve_availability(HTML, url=URL, context=context)["value"] == "UNKNOWN"


@pytest.mark.asyncio
async def test_cohort_conflict_and_conditional_batch_are_pending(db_session):
    from src.services.discovery_sources import JobStub

    context, _, _ = await collect()
    stub = JobStub(
        "test",
        "17",
        None,
        "Agent开发工程师",
        ["北京"],
        "campus",
        None,
        URL,
        "岗位职责：开发Agent应用。招聘对象：2026届毕业生。",
        context,
    )
    match = classify_discovery_job(stub, query="2027届 校招")
    assert (
        next(c for c in match.checks if c["field"] == "graduation_year")["status"]
        == "pending"
    )
    conditional = {
        **context,
        "eligibility_text": "招聘对象：2027届国内毕业生、2026届海外毕业生。",
    }
    match = classify_discovery_job(
        replace(
            stub,
            raw_content="岗位职责：开发Agent应用。",
            recruitment_context=conditional,
        ),
        query="2027届 校招",
    )
    assert (
        next(c for c in match.checks if c["field"] == "graduation_year")["status"]
        == "pending"
    )


@pytest.mark.asyncio
async def test_stale_availability_is_not_refreshed_by_reading_body(db_session):
    service = JobLeadService(db_session)
    lead = service.create_lead(
        user_id="batch", provider=LeadProvider.EXTERNAL_AGENT, source_url=URL
    )
    result = await service.verify_url(
        user_id="batch",
        lead_id=lead.id,
        reader=Reader({URL: HTML, BATCH: ANNOUNCEMENT}),
        official_hosts={"jobs.example.com"},
    )
    posting = result.posting
    posting.last_availability_checked_at = datetime.now(UTC) - timedelta(days=8)
    match = classify_discovery_job(posting_stub(posting), query="北京 Agent 校招")
    assert apply_posting_availability(match, posting).filter_status == "pending"
    # A fresh lead for the same job finds readable content but loses batch proof.
    lead = service.create_lead(
        user_id="batch", provider=LeadProvider.MANUAL_URL, source_url=URL
    )
    result = await service.verify_url(
        user_id="batch",
        lead_id=lead.id,
        reader=Reader({URL: HTML, BATCH: URLFetchError("unavailable")}),
        official_hosts={"jobs.example.com"},
    )
    assert result.posting.id == posting.id
    assert result.posting.availability_status == "UNKNOWN"
    assert result.posting.recruitment_context["status"] == "unconfirmed"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "html,status",
    [
        (HTML, "UNKNOWN"),
        (HTML + "<aside>岗位已关闭</aside>", "UNKNOWN"),
        (HTML.replace("</main>", "<p>岗位状态：招聘中</p></main>"), "ACTIVE"),
    ],
)
async def test_availability_recheck_uses_same_scoped_rules(db_session, html, status):
    from src.services.job_availability_service import JobAvailabilityService

    service = JobLeadService(db_session)
    lead = service.create_lead(
        user_id="batch", provider=LeadProvider.EXTERNAL_AGENT, source_url=URL
    )
    result = await service.verify_url(
        user_id="batch",
        lead_id=lead.id,
        reader=Reader({URL: HTML, BATCH: ANNOUNCEMENT}),
        official_hosts={"jobs.example.com"},
    )
    check = await JobAvailabilityService(db_session).check_url(
        user_id="batch", job_posting_id=result.posting.id, reader=Reader({URL: html})
    )
    assert check.result_status == status


@pytest.mark.parametrize(
    "window,status",
    [
        ("2026-09-01 至 2026-11-30", "ACTIVE"),
        ("2025-09-01 至 2025-11-30", "CLOSED"),
        ("2027-09-01 至 2027-11-30", "UNKNOWN"),
        ("2026-11-30 至 2026-09-01", "UNKNOWN"),
        ("9月 至 11月", "UNKNOWN"),
    ],
)
def test_application_window_limits_explicit_open_claim(window, status):
    html = HTML.replace(
        "</main>", f"<p>岗位状态：招聘中</p><p>网申时间：{window}</p></main>"
    )
    assert (
        resolve_availability(html, url=URL, now=datetime(2026, 10, 17, tzinfo=UTC))[
            "value"
        ]
        == status
    )


@pytest.mark.asyncio
async def test_browser_response_capture_is_job_scoped_and_used_by_verifier(
    db_session, monkeypatch
):
    from src.services.browser_job_reader import BrowserPageSnapshot
    from src.services.recruitment_context import captures_detail_api

    url = "https://careers.oppo.com/university/oppo/campus/post/1795?recruitType=Intern"
    endpoint = "https://careers.oppo.com/openapi/position/detail?id=1795"
    assert captures_detail_api(endpoint, url)
    for other in [
        endpoint.replace("1795", "1799"),
        endpoint.replace("careers.oppo.com", "other.example"),
        endpoint + "&id=1799",
    ]:
        assert not captures_detail_api(other, url)
    data = {
        "idRecruitPosition": 1795,
        "positionName": "Agent开发工程师",
        "projectId": 30,
        "projectName": "2027届应届生校园招聘",
        "positionStatus": 0,
    }
    project_url = "https://careers.oppo.com/openapi/position/project/list"
    fetcher = Reader(
        {
            project_url: {
                "code": 0,
                "data": [
                    {
                        "idRecruitProject": 30,
                        "projectName": data["projectName"],
                        "recruitRequire": "招聘对象：2027届应届毕业生",
                    }
                ],
            }
        }
    )
    monkeypatch.setattr(
        "src.services.job_lead_service.SafeHTTPReader", lambda **kwargs: fetcher
    )

    class Browser:
        async def read(self, requested):
            return BrowserPageSnapshot(
                requested,
                requested,
                "OPPO招聘",
                HTML,
                "岗位正文",
                recruitment_api=(
                    {"url": endpoint, "payload": {"code": 0, "data": data}},
                ),
            )

    service = JobLeadService(db_session)
    lead = service.create_lead(
        user_id="browser-batch", provider=LeadProvider.EXTERNAL_AGENT, source_url=url
    )
    result = await service.verify_browser(
        user_id="browser-batch",
        lead_id=lead.id,
        reader=Browser(),
        official_hosts={"careers.oppo.com"},
    )
    assert result.posting.recruitment_context["batch_id"] == "30"
    assert result.posting.availability_status == "UNKNOWN"
    assert fetcher.calls == [project_url]
    assert result.posting.job_type == "campus"


@pytest.mark.asyncio
async def test_availability_button_rechecks_associated_batch(db_session):
    from src.services.job_availability_service import JobAvailabilityService

    service = JobLeadService(db_session)
    lead = service.create_lead(
        user_id="batch-check", provider=LeadProvider.EXTERNAL_AGENT, source_url=URL
    )
    result = await service.verify_url(
        user_id="batch-check",
        lead_id=lead.id,
        reader=Reader({URL: HTML, BATCH: ANNOUNCEMENT}),
        official_hosts={"jobs.example.com"},
    )
    check = await JobAvailabilityService(db_session).check_url(
        user_id="batch-check",
        job_posting_id=result.posting.id,
        reader=Reader({URL: HTML, BATCH: ANNOUNCEMENT.replace("开放申请", "已结束")}),
    )
    assert check.result_status == "CLOSED"
    assert check.evidence["snapshots"]
    assert (
        check.evidence["recruitment_context"]["association"] == "job_scoped_batch_link"
    )


@pytest.mark.asyncio
async def test_batch_window_expires_within_freshness_period():
    start = datetime(2026, 10, 16, tzinfo=UTC)
    context, _, _ = await collect(
        now=start,
        pages={
            BATCH: ANNOUNCEMENT.replace(
                "</main>", "<p>网申时间：2026-10-01 至 2026-10-16</p></main>"
            )
        },
    )
    assert (
        resolve_availability(HTML, url=URL, context=context, now=start)["value"]
        == "ACTIVE"
    )
    assert (
        resolve_availability(
            HTML, url=URL, context=context, now=start + timedelta(days=1)
        )["value"]
        == "CLOSED"
    )


@pytest.mark.asyncio
async def test_saved_match_stops_accepting_job_after_batch_deadline():
    from types import SimpleNamespace

    from src.services.discovery_matching import DiscoveryJobMatch

    start = datetime(2026, 10, 16, tzinfo=UTC)
    context, _, _ = await collect(
        now=start,
        pages={
            BATCH: ANNOUNCEMENT.replace(
                "</main>", "<p>网申时间：2026-10-01 至 2026-10-16</p></main>"
            )
        },
    )
    posting = SimpleNamespace(
        source_url=URL,
        last_verified_at=start,
        last_availability_checked_at=start,
        availability_status="ACTIVE",
        verification_status="VERIFIED_OFFICIAL",
        recruitment_context=context,
    )
    match = DiscoveryJobMatch("strict", (), (), "matched")
    assert (
        apply_posting_availability(match, posting, now=start).filter_status == "matched"
    )
    assert (
        apply_posting_availability(
            match, posting, now=start + timedelta(days=1)
        ).filter_status
        == "excluded"
    )


@pytest.mark.asyncio
async def test_job_application_window_does_not_inherit_broader_batch_open_status():
    now = datetime.now(UTC)
    context, _, _ = await collect(now=now)
    year = now.year + 1
    html = HTML.replace(
        "</main>", f"<p>网申时间：{year}-01-01 至 {year}-03-01</p></main>"
    )
    assert (
        resolve_availability(html, url=URL, context=context, now=now)["value"]
        == "UNKNOWN"
    )
