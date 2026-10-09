"""Public-page layouts observed during the 2026-10-09 live search acceptance."""

import pytest

from src.services.discovery_matching import classify_discovery_job
from src.services.discovery_sources import JobStub
from src.services.job_detail_scope import DetailScopeError, scope_job_document
from src.services.job_fact_verifier import verify_page_facts
from src.services.url_reader import parse_html_document
from src.services.vision_job_extraction import needs_visual_fallback


def detail_html(related_label="相关岗位推荐", title_class="job__title", subtitle_class="job_sub__title"):
    return f"""<title>公司招聘 - 岗位详情</title><nav>社会招聘 校园招聘</nav>
    <main><div class="cont-wrap">
      <div class="co-mid"><div class="{title_class}"><span>AI系统工程师</span></div></div>
      <div class="{subtitle_class}"><div>南京市,深圳市</div><div>软件类</div>
        <div>应届生 (2027届应届生校园招聘)</div><div>2026-07-15 发布</div></div>
      <section><h2>岗位职责</h2><p>设计和开发系统级智能体，完成Agent应用开发及业务落地。</p></section>
      <section><h2>知识技能要求</h2><p>熟悉Python和分布式服务。</p></section>
      <div class="duty_wrap"><div class="title"><span>{related_label}</span></div></div>
      <div><div class="{title_class}">多媒体开发工程师</div>
        <div class="{subtitle_class}">上海市 2026届</div><p>该职位已下线</p></div>
      <div><div class="{title_class}">互联网安全工程师</div><p>工作地点：北京</p></div>
    </div></main><footer>实习生招聘</footer>"""


@pytest.mark.parametrize("host", ["careers.oppo.com", "jobs.unregistered.example"])
@pytest.mark.parametrize("related_label", ["相关岗位推荐", "推荐岗位", "相关职位"])
def test_wrapped_recommendations_and_subtitles_do_not_replace_current_job(host, related_label):
    html = detail_html(related_label)
    url = f"https://{host}/campus/post/1843"
    doc, closed = scope_job_document(html, parse_html_document(html), url=url)
    facts = verify_page_facts(doc)
    assert doc.title == "AI系统工程师"
    assert facts.locations == ["南京市", "深圳市"]
    assert facts.job_type == "campus"
    assert not closed
    assert "熟悉Python" in doc.text
    for unrelated in ("多媒体", "互联网安全", "上海", "北京", "2026届", "已下线"):
        assert unrelated not in doc.text
    assert not needs_visual_fallback(html, url)
    stub = JobStub(source_id="layout", source_job_id="1843", company="示例公司",
                   title=facts.title, locations=facts.locations, job_type=facts.job_type,
                   published_at=None, detail_url=url, raw_content=doc.text)
    match = classify_discovery_job(stub, query="2027届深圳AI Agent校招，不考虑北京，不考虑社招")
    assert match.filter_status == "matched"


@pytest.mark.parametrize("title,subtitle", [("job-title", "job-sub-title"), ("position-title", "position_subtitle")])
def test_subtitle_metadata_does_not_create_a_second_job_title(title, subtitle):
    html = detail_html(title_class=title, subtitle_class=subtitle)
    doc, _ = scope_job_document(html, parse_html_document(html), url="https://example.com/jobs/1")
    assert doc.title == "AI系统工程师"


def test_subtitle_alone_cannot_prove_a_current_job():
    html = '<main><div class="job_sub__title">深圳市 软件类 2027届</div><h2>岗位职责</h2><p>开发软件服务。</p></main>'
    with pytest.raises(DetailScopeError):
        scope_job_document(html, parse_html_document(html), url="https://example.com/jobs/1")


def test_two_real_jobs_without_a_related_heading_still_require_verification():
    html = '<main><div class="job__title">后端工程师</div><p>岗位职责：开发接口。</p><div class="job__title">前端工程师</div><p>岗位职责：开发网页。</p></main>'
    with pytest.raises(DetailScopeError):
        scope_job_document(html, parse_html_document(html), url="https://example.com/jobs/1")


def test_wrapped_related_section_does_not_remove_later_requirements():
    html = '<main><h1>后端工程师</h1><p>岗位职责：开发接口。</p><div><span>相关岗位推荐</span></div><div><h2>前端工程师</h2><p>已结束</p></div><h2>任职要求</h2><p>熟悉Python。</p></main>'
    doc, closed = scope_job_document(html, parse_html_document(html), url="https://example.com/jobs/1")
    assert "熟悉Python" in doc.text
    assert "前端工程师" not in doc.text
    assert not closed
