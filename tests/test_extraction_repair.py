import pytest

from src.services.job_detail_scope import DetailScopeError, scope_job_document
from src.services.lead_extraction import extract_lead_preview
from src.services.lead_presentation import discovery_kind
from src.services.responses_search import text_urls
from src.services.url_reader import parse_html_document


@pytest.mark.parametrize("url", [
    "https://app.mokahr.com/campus-recruitment/company/123#/jobs?project=1&page=1",
    "https://talent.example.com/jobs/social-list",
    "https://example.com/campus/hot-jobs?source=1",
])
def test_lists_never_become_jobs_due_to_card_labels(url):
    assert discovery_kind(url, "AI工程师") == "entry"


def test_markdown_prose_does_not_enter_urls():
    assert list(text_urls("[岗位](https://example.com/job/1)：官方页面明确说明")) == ["https://example.com/job/1"]
    assert list(text_urls("[岗位](https://example.com/job?id=Engineer(J1))：说明")) == ["https://example.com/job?id=Engineer(J1)"]


def test_hashed_detail_title_preserves_requirements_and_excludes_navigation():
    html = '''<nav>其他职位</nav><main><div class="detail-head__abCD"><div class="detail-title__xyZ"><span>上海-大模型研发工程师(J100835)</span></div></div><div>上海市</div><section>工作职责：<p>负责模型训练与服务开发。</p></section><section>职责要求：<p>熟悉 Python，计算机相关专业。</p></section></main>'''
    doc, _ = scope_job_document(html,parse_html_document(html),url="https://example.com/jobs/detail/123")
    assert doc.title == "上海-大模型研发工程师(J100835)"
    assert doc.locations == ["上海市"]
    assert "熟悉 Python" in doc.text and "其他职位" not in doc.text


def test_two_detail_titles_remain_ambiguous():
    html = '<main><div class="detail-title">AI工程师</div><div class="detail-title">测试工程师</div>工作职责：研发</main>'
    with pytest.raises(DetailScopeError):
        scope_job_document(html,parse_html_document(html),url="https://example.com/jobs/list")


def test_card_metadata_separated_without_claiming_verification():
    raw = "急 工程交付经理 发布于 2026-07-02 地点：上海 北京"
    fields = extract_lead_preview("https://example.com/jobs/1",title=raw)
    assert fields["title"] == "工程交付经理"
    assert set(fields["locations"]) == {"北京","上海"}
    assert fields["verified"] is False
    assert fields["job_type"] is None
