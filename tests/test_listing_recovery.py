from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from src.services.browser_job_reader import BrowserPageSnapshot
from src.services.company_coverage import CompanyCoverage
from src.services.recruitment_listing import (
    allowed_listing_url,
    inspect_listing,
    observed_ats_base,
)
from src.services.recruitment_trust import hiring_scope, within_scope
from src.services.search_run_metrics import SearchRunMetrics
from src.services.url_reader import FetchedResponse
from tests.test_recruitment_capabilities import SOURCE, Reader, listing, run_direct


@pytest.mark.asyncio
@pytest.mark.parametrize('brand,expected', [('未见过的公司', 2), ('其他企业', 0)])
async def test_redirected_official_cta_binds_custom_branded_portal(brand, expected):
    landing = '<section><h2>2027届应届生招聘</h2><a href="https://hiring.custom.example/graduate/">立即投递</a></section>'
    target = 'https://hiring.custom.example/graduate/'

    class RedirectReader(Reader):
        async def fetch(self, url):
            if url == SOURCE.career_url:
                self.calls.append(url)
                return FetchedResponse(url, url.replace('https:', 'http:'), 200, 'text/html', landing.encode())
            return await super().fetch(url)

    reader = RedirectReader({target: f'<title>加入{brand}</title>' + listing([1, 2])})
    direct, jobs, events = await run_direct(reader)
    assert len(jobs) == expected
    assert events[-1]['source_read_attempted'] is True
    assert events[-1]['source_read_success'] == bool(expected)
    if jobs:
        evidence = direct.evidence[jobs[0].source_url]
        assert target in evidence.official_html
        assert evidence.official_proof_url == SOURCE.career_url.replace('https:', 'http:')
        assert not evidence.full_body


def test_cross_scheme_permission_keeps_host_ports_and_shared_tenant_boundaries():
    base = 'https://wecruit.hotjob.cn/SU123abc/pb/school.html'
    assert hiring_scope(base) == ('wecruit.hotjob.cn', '/SU123abc/')
    assert allowed_listing_url(base.replace('https:', 'http:'), base)
    assert not allowed_listing_url('http://wecruit.hotjob.cn/SUother/pb/school.html', base)
    assert not allowed_listing_url('http://wecruit.hotjob.cn:8080/SU123abc/pb/school.html', base)
    assert not allowed_listing_url('http://wecruit.hotjob.cn:invalid/SU123abc/pb/school.html', base)
    assert not allowed_listing_url('https://other.example/SU123abc/pb/school.html', base)
    assert not within_scope(base.replace('SU123abc', 'SU123abc-extra'), hiring_scope(base))
    assert hiring_scope('https://wecruit.hotjob.cn/') is None


@pytest.mark.parametrize('prefix', ['graduate-new', 'edu', 'talent-program'])
def test_ats_route_comes_from_observed_links(prefix):
    url = f'https://unknown.example/{prefix}/?project=123'
    html = f'<a href="/{prefix}/position/123/detail">Agent工程师</a>'
    page = BrowserPageSnapshot(url, url, '', html, '')
    assert observed_ats_base(page, inspect_listing(html, url=url)) == f'https://unknown.example/{prefix}'
    unrelated = replace(page, raw_html='<a href="/other/position/123/detail">Agent工程师</a>')
    assert observed_ats_base(unrelated, inspect_listing(unrelated.raw_html, url=url)) is None


def test_explicit_view_jobs_button_in_recommendation_container_is_entry_hint_only():
    html = '<div class="campus-jobRecommend"><h2>应届生职位</h2><button>查看职位</button></div>'
    result = inspect_listing(html, url=SOURCE.career_url)
    assert result.entry_controls
    assert not result.jobs
    assert not inspect_listing('<form><button>查看职位</button></form>', url=SOURCE.career_url).entry_controls


def test_source_metrics_exclude_cache_only_runs_and_separate_first_fresh_result():
    start = datetime.now(UTC)
    now = start + timedelta(seconds=1)
    metrics = SearchRunMetrics(start, {'cached': {'filter_status': 'matched'}}, clock=lambda: now)
    metrics.cache_hit('cached-url')
    metrics.publish('cached', True)
    assert metrics.snapshot()['first_fresh_useful_ms'] is None
    assert metrics.snapshot()['source_read_success_rate'] is None
    metrics.source_read('recovered', success=True, retry=True)
    metrics.source_read('recovered', success=True, retry=True)
    metrics.source_read('failed', success=False, retry=True)
    now = start + timedelta(seconds=9)
    metrics.publish('new', True, fresh=True)
    result = metrics.snapshot()
    assert result['source_read_attempts'] == 2
    assert result['source_read_success_rate'] == 0.5
    assert result['source_retry_recovered'] == 1
    assert result['source_retry_attempts'] == 2
    assert result['first_useful_ms'] == 1000
    assert result['first_fresh_useful_ms'] == 9000


@pytest.mark.asyncio
async def test_buffer_only_continuation_does_not_count_as_fresh_source_read():
    reader = Reader({SOURCE.career_url: listing(range(1, 8))})
    direct, _, _ = await run_direct(reader)
    _, jobs, events = await run_direct(reader, states=direct.states)
    assert len(jobs) == 3
    assert events[-1]['source_read_attempted'] is False
    assert events[-1]['source_read_success'] is False


@pytest.mark.parametrize('reason', ['dynamic_navigation_unresolved', 'pagination_replay_limit', 'listing_scope_changed'])
def test_dynamic_blockers_keep_official_web_fallback_available(reason):
    from types import SimpleNamespace

    coverage = CompanyCoverage(sources=[SOURCE], store=SimpleNamespace(load=dict),
                               query='北京 Agent 校招', batch_size=1)
    direct = SimpleNamespace(states={SOURCE.id: {'status': 'paused', 'reason': reason}})
    assert coverage.next_task(direct).company_id == SOURCE.id


@pytest.mark.asyncio
async def test_small_spa_shell_requests_browser_instead_of_permanent_rejection(db_session):
    from src.domain.discovery import LeadProvider
    from src.services.job_lead_service import JobLeadService, LeadVerificationFailure

    service = JobLeadService(db_session)
    url = 'https://careers.example/jobs/123'
    lead = service.create_lead(user_id='u', provider=LeadProvider.EXTERNAL_AGENT, source_url=url)
    html = '<title></title><noscript>You need to enable JavaScript to run this app.</noscript>' \
           '<div id="root"></div><script src="/vendor.js"></script><script src="/detail.js"></script>'
    with pytest.raises(LeadVerificationFailure) as error:
        await service.verify_url(user_id='u', lead_id=lead.id, reader=Reader({url: html}),
                                 official_hosts={'careers.example'})
    assert error.value.code == 'lead_requires_browser'
    assert service.get_lead(user_id='u', lead_id=lead.id).status == 'NEEDS_BROWSER'
    assert lead.job_posting_id is None
