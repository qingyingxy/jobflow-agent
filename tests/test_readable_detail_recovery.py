from pathlib import Path

import pytest

from src.domain.discovery import LeadProvider, LeadVerification
from src.services.browser_job_reader import BrowserPageSnapshot
from src.services.job_detail_scope import DetailScopeError, scope_job_document
from src.services.job_fact_verifier import verify_page_facts
from src.services.job_lead_service import JobLeadService, LeadVerificationFailure
from src.services.url_reader import FetchedResponse, parse_html_document
from src.services.vision_job_extraction import needs_visual_fallback

TITLE = '【2027届校招】Agent开发工程师'
DUTIES = '岗位职责：开发Agent应用和工具调用模块，完成服务接口、评测流程和稳定性建设。'
REQUIREMENTS = '任职要求：2027届计算机相关专业本科及以上学历，熟悉Python、数据库及软件测试，能够独立分析问题。'


def detail_html(prefix='pos', label='tit', title=TITLE):
    return f'''<title>职位列表</title><nav><h1>招聘导航</h1>北京 已结束</nav>
    <div class="{prefix}-detail-wrap">
      <div class="sticky"><p class="{label}">{title}</p><button>立即投递</button></div>
      <div class="{prefix}-detail-inner">
        <div class="{prefix}-detail-header"><span class="{label}">{title}<span class="badge">热招</span><span><span>职位类别：研发</span></span></span></div>
        <div>工作地点：上海</div><div>{DUTIES}</div><section>{REQUIREMENTS}</section>
        <button>立即投递</button>
      </div>
    </div><aside><h1>其他工程师</h1>工作地点：北京 岗位状态：已结束</aside>'''


@pytest.mark.parametrize('prefix,label', [('pos', 'tit'), ('job', 'title'), ('position', 'name'), ('vacancy', 'tit')])
@pytest.mark.parametrize('host', ['unregistered.example', 'another-employer.example'])
def test_repeated_title_and_nested_metadata_bind_to_one_body(prefix, label, host):
    html = detail_html(prefix, label)
    doc, closed = scope_job_document(html, parse_html_document(html), url=f'https://{host}/jobs/123')
    assert doc.title == TITLE
    assert DUTIES in doc.text and REQUIREMENTS in doc.text
    assert '职位类别：研发' in doc.text
    assert verify_page_facts(doc).locations == ['上海']
    assert '其他工程师' not in doc.text and '招聘导航' not in doc.text
    assert not closed
    assert not needs_visual_fallback(html, f'https://{host}/jobs/123')


@pytest.mark.parametrize('second', [TITLE, '后端工程师'])
def test_independent_job_bodies_cannot_merge_even_with_identical_titles(second):
    html = '<main>' + ''.join(f'<article class="job-detail"><span class="title">{title}</span><p>{DUTIES}</p></article>' for title in (TITLE, second)) + '</main>'
    with pytest.raises(DetailScopeError):
        scope_job_document(html, parse_html_document(html), url='https://example.com/jobs/123')


def test_generic_title_class_without_job_context_is_not_enough():
    html = f'<div class="title">欢迎加入我们</div><p>{DUTIES}</p><p>{REQUIREMENTS}</p>'
    with pytest.raises(DetailScopeError):
        scope_job_document(html, parse_html_document(html), url='https://example.com/jobs/123')


def test_badge_words_inside_real_title_are_preserved():
    html = detail_html(title='HOT业务平台工程师（校招）')
    doc, _ = scope_job_document(html, parse_html_document(html), url='https://example.com/jobs/123')
    assert doc.title == 'HOT业务平台工程师（校招）'


def test_outer_detail_status_and_sibling_requirements_are_preserved():
    html = f'<div class="job-detail-wrap"><div>已结束</div><div class="job-detail-inner"><span class="title">{TITLE}</span><p>{DUTIES}</p></div><section>{REQUIREMENTS}</section></div>'
    doc, closed = scope_job_document(html, parse_html_document(html), url='https://example.com/jobs/123')
    assert closed and REQUIREMENTS in doc.text


@pytest.mark.asyncio
@pytest.mark.parametrize('method', ['http', 'browser'])
async def test_readable_dom_verifies_despite_site_title_and_does_not_call_vision(db_session, monkeypatch, method):
    from sqlalchemy import select

    from src.services import vision_job_extraction

    async def unexpected(*args, **kwargs):
        pytest.fail('Readable DOM must not be replaced by screenshot transcription')

    monkeypatch.setattr(vision_job_extraction, 'extract_visual_job', unexpected)
    url = 'https://unregistered.example/jobs/123'
    html = detail_html()

    class Reader:
        async def fetch(self, url):
            return FetchedResponse(url, url, 200, 'text/html', html.encode())

        async def read(self, url):
            return BrowserPageSnapshot(url, url, '职位列表', html, '', screenshots=({'base64': 'saved-evidence'},))

    service = JobLeadService(db_session)
    lead = service.create_lead(user_id='u', provider=LeadProvider.EXTERNAL_AGENT, source_url=url)
    verify = service.verify_url if method == 'http' else service.verify_browser
    result = await verify(user_id='u', lead_id=lead.id, reader=Reader(), official_hosts={'unregistered.example'}, official_only=True)
    assert result.posting.title == TITLE
    assert result.posting.availability_status == 'UNKNOWN'  # A hot badge/apply button is insufficient.
    assert result.posting.locations == ['上海']
    assert REQUIREMENTS in result.posting.raw_content
    snapshots = db_session.scalars(select(LeadVerification).where(LeadVerification.result == 'SNAPSHOT')).all()
    assert any(s.field_evidence.get('raw_html') == html for s in snapshots)
    if method == 'browser':
        assert any(s.field_evidence.get('screenshots') for s in snapshots)


@pytest.mark.asyncio
async def test_known_list_url_does_not_become_a_job_from_one_card(db_session):
    html = detail_html()
    url = 'https://unregistered.example/jobs/list'

    class Reader:
        async def fetch(self, url):
            return FetchedResponse(url, url, 200, 'text/html', html.encode())

    service = JobLeadService(db_session)
    lead = service.create_lead(user_id='u', provider=LeadProvider.EXTERNAL_AGENT, source_url=url)
    with pytest.raises(LeadVerificationFailure):
        await service.verify_url(user_id='u', lead_id=lead.id, reader=Reader(), official_hosts={'unregistered.example'})
    assert lead.job_posting_id is None


def test_recorded_public_detail_recovered_without_company_specific_rules():
    html = (Path(__file__).parent / 'fixtures' / 'readable_detail_dom.html').read_text(encoding='utf-8')
    doc, closed = scope_job_document(html, parse_html_document(html), url='https://unseen.example/jobs/123')
    assert doc.title == '【2027届校招】AI芯片Linux/Android平台软件工程师'
    assert '参与量产项目开发' in doc.text
    assert '硕士及以上学历' in doc.text
    assert 'MIPI' in doc.text and 'PCIe' in doc.text
    assert not closed
    assert not needs_visual_fallback(html, 'https://unseen.example/jobs/123')


@pytest.mark.parametrize('case,expected', [('old_readable', True), ('current_parser', False),
    ('already_retried', False), ('image_only', False), ('captcha', False), ('ignored', False),
    ('wrong_url', False), ('foreign_snapshot', False)])
def test_parser_upgrade_retries_only_newly_readable_owned_evidence_once(db_session, case, expected):
    from datetime import UTC, datetime

    from src.services.job_detail_scope import EXTRACTOR_VERSION
    from src.services.lead_retry import can_retry, failed_state, parser_retry_state
    from src.services.search_goal_service import SearchGoalService
    from tests.test_verification_retry import candidate, run

    old = run(db_session, 'old')
    service = JobLeadService(db_session)
    lead = service.capture_candidate(user_id='owner', discovery_run_id=old.id, candidate=candidate(1))
    lead.status = 'NEEDS_USER'
    lead.failure_code = 'browser_captcha_required' if case == 'captcha' else 'visual_extraction_unverified'
    lead.retry_state = failed_state({}, lead.failure_code)
    if case == 'already_retried':
        lead.retry_state = {**lead.retry_state, 'structure_retry_version': EXTRACTOR_VERSION}
    if case == 'ignored':
        lead.selection_status = 'IGNORED'
    before = dict(lead.retry_state)
    html = '<img src="poster.png">' if case == 'image_only' else detail_html()
    snapshot = LeadVerification(id='original', user_id='foreign' if case == 'foreign_snapshot' else 'owner',
        lead_id=lead.id, result='SNAPSHOT', source_type='browser_snapshot',
        source_url='https://test.example/jobs/other' if case == 'wrong_url' else lead.source_url,
        field_evidence={'raw_html': html, 'extractor': EXTRACTOR_VERSION if case == 'current_parser' else 'generic-job-scope-v3'},
        checked_at=datetime.now(UTC))
    db_session.add(snapshot)
    db_session.commit()
    assert can_retry(parser_retry_state(db_session, lead)) == expected
    resumed = SearchGoalService(db_session).resume_candidates('owner', goal_id='goal', version=1, current_run_id='new')
    assert bool(resumed) == expected
    new_run = run(db_session, 'new')
    new = service.capture_candidate(user_id='owner', discovery_run_id=new_run.id, candidate=candidate(1))
    assert can_retry(new.retry_state) == expected
    assert new.job_posting_id is None  # Recovery permission is not verification.
    assert lead.retry_state == before
    assert snapshot.field_evidence['raw_html'] == html
    if expected:
        assert new.retry_state['next_method'] == 'browser'
        new.retry_state = failed_state(new.retry_state, 'visual_extraction_unverified')
        assert not can_retry(parser_retry_state(db_session, new))
