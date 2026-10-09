import pytest

from src.services.job_detail_scope import DetailScopeError, scope_job_document
from src.services.job_fact_verifier import verify_page_facts
from src.services.url_reader import parse_html_document

HTML = """<title>滴滴招聘</title><nav>校园招聘 实习生招聘</nav>
<div class="position-detail-title-box"><div class="position-detail-title">测试开发工程师 (JR1)</div>杭州市 / 技术 / 1 人</div>
<div class="position-detail-invalid-word">已结束</div>
<div class="position-detail-box-desc">职位描述 开发测试工具。任职要求 至少一年经验，Python。</div>
<div class="position-detail-similarPosts">AI应用开发校招 北京市</div>"""


@pytest.mark.parametrize(
    "body,expected",
    [
        ("招聘类型：校园招聘。任职要求：熟悉 Python。", "campus"),
        ("招聘类别：实习招聘。任职要求：熟悉 Python。", "internship"),
        ("任职要求：有校园招聘平台开发经验或实习经验。", "full_time"),
    ],
)
def test_explicit_recruitment_type_is_distinct_from_full_time_hours(body, expected):
    import json

    item = {
        "@type": "JobPosting",
        "title": "Python 开发工程师",
        "description": body,
        "employmentType": "FULL_TIME",
    }
    html = '<script type="application/ld+json">' + json.dumps(item) + "</script>"
    doc, _ = scope_job_document(
        html, parse_html_document(html), url="https://example.com/jobs/1"
    )
    facts = verify_page_facts(doc)
    assert facts.job_type == expected
    assert facts.evidence["job_type"]["value"] == expected


def test_current_job_excludes_navigation_and_related_jobs():
    doc, closed = scope_job_document(
        HTML, parse_html_document(HTML), url="https://talent.didiglobal.com/social/p/1"
    )
    assert doc.title == "测试开发工程师 (JR1)"
    assert doc.locations == ["杭州市"]
    assert doc.company == "滴滴"
    assert verify_page_facts(doc).job_type == "full_time"
    assert closed
    assert "校园招聘" not in doc.text
    assert "AI应用" not in doc.text
    assert "北京市" not in doc.text
    assert "至少一年经验" in doc.text


def test_unloaded_detail_cannot_use_site_title():
    html = "<title>滴滴招聘</title><nav>校园招聘</nav>"
    with pytest.raises(DetailScopeError):
        scope_job_document(
            html,
            parse_html_document(html),
            url="https://talent.didiglobal.com/social/p/1",
        )


def test_hidden_closed_banner_is_not_evidence_of_closure():
    html = HTML.replace(
        'class="position-detail-invalid-word"',
        'class="position-detail-invalid-word" hidden',
    )
    _, closed = scope_job_document(
        html, parse_html_document(html), url="https://talent.didiglobal.com/campus/p/1"
    )
    assert not closed


@pytest.mark.asyncio
async def test_closed_detail_is_persisted_as_closed(db_session):
    from src.domain.discovery import LeadProvider
    from src.services.job_lead_service import JobLeadService
    from src.services.url_reader import FetchedResponse

    class Reader:
        async def fetch(self, url):
            return FetchedResponse(
                requested_url=url,
                final_url=url,
                status_code=200,
                content_type="text/html",
                body=HTML.encode(),
            )

    service = JobLeadService(db_session)
    lead = service.create_lead(
        user_id="scope-user",
        provider=LeadProvider.EXTERNAL_AGENT,
        source_url="https://talent.didiglobal.com/social/p/1",
    )
    result = await service.verify_url(
        user_id="scope-user",
        lead_id=lead.id,
        reader=Reader(),
        official_hosts={"talent.didiglobal.com"},
    )
    assert result.posting.availability_status == "CLOSED"
    assert result.posting.job_type == "full_time"
    assert result.posting.locations == ["杭州市"]


@pytest.mark.parametrize(
    "host", ["jobs.example.com", "careers.other.org", "recruit.third.cn"]
)
def test_same_dom_works_on_unregistered_hosts(host):
    html = """<title>招聘中心</title><nav>校园招聘 上海 已结束</nav>
    <main><h1>Python后端工程师</h1><p>工作地点：深圳。</p>
    <section><h2>岗位职责</h2><p>维护接口服务。</p><h2>任职要求</h2><p>熟悉Python。</p></section>
    <aside><h1>推荐工程师</h1><p>已结束</p></aside></main>"""
    doc, closed = scope_job_document(
        html, parse_html_document(html), url=f"https://{host}/jobs/123"
    )
    facts = verify_page_facts(doc)
    assert doc.title == "Python后端工程师"
    assert facts.locations == ["深圳"]
    assert facts.job_type is None
    assert not closed
    assert "校园招聘" not in doc.text
    assert "推荐工程师" not in doc.text


def test_jsonld_description_does_not_absorb_other_jobs():
    import json

    item = {
        "@type": "JobPosting",
        "title": "Agent开发工程师",
        "description": "职责：构建Agent。要求：Python。",
        "url": "https://example.org/jobs/1",
        "hiringOrganization": {"name": "示例公司"},
        "employmentType": "FULL_TIME",
        "jobLocation": {"address": {"addressLocality": "上海"}},
    }
    html = (
        '<script type="application/ld+json">'
        + json.dumps(item)
        + "</script><nav>校招 已结束</nav><aside>推荐岗位 北京</aside>"
    )
    doc, closed = scope_job_document(html, parse_html_document(html), url=item["url"])
    assert doc.company == "示例公司"
    assert doc.locations == ["上海"]
    assert "推荐" not in doc.text
    assert "校招" not in doc.text
    assert not closed


def test_plain_related_heading_and_hidden_banner_are_ignored():
    html = """<main><h2>后端开发工程师</h2><p>岗位职责：开发接口。</p>
    <div style="display:none">已结束</div><h3>相关职位</h3><div><h2>前端开发工程师</h2>已结束 北京</div></main>"""
    doc, closed = scope_job_document(
        html, parse_html_document(html), url="https://example.com/job/1"
    )
    assert doc.title == "后端开发工程师"
    assert "前端" not in doc.text
    assert not closed


def test_multiple_jobs_are_not_merged():
    html = "<main><article><h1>后端工程师</h1><p>岗位职责：后端开发。</p></article><article><h1>前端工程师</h1><p>岗位职责：前端开发。</p></article></main>"
    with pytest.raises(DetailScopeError):
        scope_job_document(
            html, parse_html_document(html), url="https://example.com/jobs"
        )


def test_conflicting_metadata_is_not_silently_accepted():
    import json

    data = {
        "@type": "JobPosting",
        "title": "前端工程师",
        "description": "岗位职责：开发页面。",
    }
    html = (
        '<script type="application/ld+json">'
        + json.dumps(data)
        + "</script><main><h1>后端工程师</h1><p>岗位职责：开发接口。</p></main>"
    )
    with pytest.raises(DetailScopeError):
        scope_job_document(
            html, parse_html_document(html), url="https://example.com/job/1"
        )


def test_hashed_component_classes_and_explicit_type_override_route():
    html = """<div class="PositionDetail--container--xyz"><div class="PositionDetail--name--abc">AI应用研发工程师</div>
    <div>北京 / 杭州 / 上海</div><div>招聘项目 2027届实习生</div>
    <div class="PositionDetail--title--xyz">基础信息</div>
    <div class="PositionDetail--title--xyz">职位描述</div><p>构建Agent系统。</p>
    <div>任职要求：Python。</div></div>"""
    doc, _ = scope_job_document(
        html, parse_html_document(html), url="https://new-employer.example/campus/job/1"
    )
    assert doc.title == "AI应用研发工程师"
    assert doc.locations == ["北京", "杭州", "上海"]
    assert doc.job_type == "internship"


@pytest.mark.parametrize("wrapper", ["section", "div", "article"])
def test_sibling_requirements_and_status_are_retained(wrapper):
    html = f"<main><div>已结束</div><{wrapper}><h1>Python工程师</h1><h2>岗位职责</h2><p>开发接口。</p></{wrapper}><{wrapper}><h2>任职要求</h2><div>硕士学历，三年经验。</div></{wrapper}><div>工作地点：成都</div></main>"
    doc, closed = scope_job_document(
        html, parse_html_document(html), url="https://example.com/jobs/1"
    )
    assert "开发接口" in doc.text
    assert "硕士学历，三年经验" in doc.text
    assert verify_page_facts(doc).locations == ["成都"]
    assert closed


def test_mixed_tags_and_split_labels_preserve_each_fact():
    html = "<main><h1>Python工程师</h1><div>工作地点</div><div>成都</div><div>招聘类型：实习</div><h2>岗位职责</h2><p>开发接口。</p><div>任职要求：硕士学历。</div><table><tr><td>薪资</td><td>每月8000元</td></tr></table></main>"
    doc, _ = scope_job_document(
        html, parse_html_document(html), url="https://example.com/jobs/1"
    )
    for fact in ["成都", "实习", "开发接口", "硕士学历", "每月8000元"]:
        assert fact in doc.text
    assert doc.text.count("开发接口") == 1
    assert verify_page_facts(doc).locations == ["成都"]


def test_structured_description_keeps_additional_dom_requirements():
    import json

    data = {
        "@type": "JobPosting",
        "title": "Python工程师",
        "description": "岗位职责：开发接口。",
    }
    html = (
        '<script type="application/ld+json">'
        + json.dumps(data)
        + "</script><main><h1>Python工程师</h1><div>任职要求：硕士学历，三年经验。</div><div>工作地点：成都</div></main>"
    )
    doc, _ = scope_job_document(
        html, parse_html_document(html), url="https://example.com/jobs/1"
    )
    assert "开发接口" in doc.text
    assert "硕士学历，三年经验" in doc.text
    assert verify_page_facts(doc).locations == ["成都"]


@pytest.mark.asyncio
@pytest.mark.parametrize("valid", [True, False])
async def test_original_snapshot_survives_success_and_failure(db_session, valid):
    import base64

    from sqlalchemy import select

    from src.domain.discovery import LeadProvider, LeadVerification
    from src.services.job_lead_service import JobLeadService, LeadVerificationFailure
    from src.services.url_reader import FetchedResponse

    html = (
        "<nav>导航原文</nav><main><h1>Python工程师</h1><div>岗位职责：负责后端接口开发、数据库设计和服务维护。</div><div>任职要求：熟悉Python，能够独立开发测试并参与代码评审，具有良好的团队协作能力，愿意持续学习软件工程实践。</div><div>工作地点：成都。</div></main>"
        if valid
        else "<main>未加载的原始页面</main>"
    )

    class Reader:
        async def fetch(self, url):
            return FetchedResponse(
                requested_url=url,
                final_url=url,
                status_code=200,
                content_type="text/html",
                body=html.encode(),
            )

    service = JobLeadService(db_session)
    lead = service.create_lead(
        user_id="snapshot-user",
        provider=LeadProvider.EXTERNAL_AGENT,
        source_url="https://example.com/jobs/1",
    )
    try:
        await service.verify_url(
            user_id="snapshot-user",
            lead_id=lead.id,
            reader=Reader(),
            official_hosts={"example.com"},
        )
    except LeadVerificationFailure:
        assert not valid
    observation = db_session.scalar(
        select(LeadVerification).where(
            LeadVerification.lead_id == lead.id, LeadVerification.result == "SNAPSHOT"
        )
    )
    assert observation.field_evidence["raw_html"] == html
    assert (
        base64.b64decode(observation.field_evidence["raw_bytes_base64"])
        == html.encode()
    )
