import asyncio
import copy
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from src.domain.search_goal import SearchGoal, SearchGoalConditions
from src.services.company_search_progress import (
    CompanyProgressStore,
    fresh_cursor,
    progress_summaries,
)
from src.services.direct_recruitment_search import DirectRecruitmentSearch, payload_stub
from src.services.discovery_matching import classify_discovery_job
from src.services.discovery_sources import JobStub
from tests.test_direct_recruitment_search import ITEM, QUERY, SOURCE, PortalQueryBrowser


@pytest.mark.asyncio
@pytest.mark.parametrize('concurrency', [2, 4])
async def test_official_company_reads_overlap_within_the_configured_limit(concurrency):
    from src.services.direct_recruitment_search import DirectJobEvidence
    from src.services.lead_providers import LeadCandidate, LeadProviderKind

    sources = [replace(SOURCE, id=name, company=name)
               for name in ('bytedance', 'minimax', 'xiaomi', 'nio')]
    entered, active, peak = [], 0, 0
    ready, release = asyncio.Event(), asyncio.Event()

    class ParallelSearch(DirectRecruitmentSearch):
        async def _source(self, source):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            entered.append(source.id)
            if active == concurrency:
                ready.set()
            try:
                await release.wait()
            finally:
                active -= 1
            for i in range(5):
                stub = payload_stub({**ITEM, 'id': str(100 + sources.index(source) * 10 + i)},
                    company=source.company, listing_url=SOURCE.career_url + 'position')
                self.evidence[stub.detail_url] = DirectJobEvidence(
                    stub, SOURCE.career_url, '', SOURCE.career_url, {}, True)
                yield LeadCandidate(provider=LeadProviderKind.EXTERNAL_AGENT,
                    source_url=stub.detail_url, source_job_id=stub.source_job_id,
                    discovered_at=datetime.now(UTC))

    events, found = [], []
    search = ParallelSearch(sources=sources, query=QUERY, reader=None, browser=ManyJobs(),
        on_event=lambda kind, data: events.append((kind, data)),
        company_concurrency=concurrency)
    task = asyncio.create_task(search.discover(found.extend))
    try:
        await asyncio.wait_for(ready.wait(), 1)
        assert len(entered) == concurrency
    finally:
        release.set()
        await task
    assert peak == concurrency and len(found) == 12
    assert all(len(s['matched_urls']) == 3 and s['reason'] == 'company_read_limit'
               for s in search.states.values())
    summaries = [data for kind, data in events if kind == 'direct_search']
    assert len(summaries) == 4 and all('queue_wait_ms' in data for data in summaries)


@pytest.mark.asyncio
async def test_company_timeout_is_visible_in_timing_trace():
    events = []
    class SlowListing(ManyJobs):
        async def read_search_listing(self, url):
            await asyncio.Event().wait()

    search = direct(SlowListing(), company_seconds=.01)
    search.on_event = lambda kind, data: events.append((kind, data))
    async def blocked(_):
        await asyncio.Event().wait()
    await search.discover(lambda _: None, await_result=blocked)
    summary = next(data for kind, data in events if kind == 'direct_search')
    assert summary['reason'] == 'time_budget' and summary['status'] == 'paused'
    assert summary['error_code'] is None
    assert not search.states[SOURCE.id]['checked_urls']
    assert summary['read_duration_ms'] > 0 and summary['verification_wait_ms'] == 0


@pytest.mark.asyncio
async def test_historical_verification_does_not_delay_supplemental_search(db_session, monkeypatch):
    from sqlalchemy.orm import sessionmaker

    from src.config import Settings
    from src.domain.discovery import DiscoveryRun
    from src.services import multiround_search as execution
    from src.services import web_search_service
    from src.services.lead_providers import LeadCandidate, LeadProviderKind
    from src.services.search_goal_service import SearchGoalService

    searched, verifying = asyncio.Event(), asyncio.Event()
    pending = LeadCandidate(provider=LeadProviderKind.EXTERNAL_AGENT,
        source_url='https://historical.example/jobs/123', discovered_at=datetime.now(UTC))

    class Provider:
        source_id, source_url = 'test', SOURCE.career_url
        async def discover(self):
            await verifying.wait()
            searched.set()
            return []

    async def resolve(*_, **kwargs):
        verifying.set()
        await searched.wait()

    original_source = DirectRecruitmentSearch._source

    async def source_after_history(self, source):
        # Historical work must already be runnable before listing discovery ends.
        await verifying.wait()
        async for candidate in original_source(self, source):
            yield candidate

    settings = Settings(_env_file=None, web_search_direct_sources_enabled=True,
        web_search_target_jobs=15, web_search_max_rounds=2, web_search_budget_seconds=5)
    monkeypatch.setattr(execution, 'get_settings', lambda: settings)
    monkeypatch.setattr(execution, 'SessionLocal', sessionmaker(bind=db_session.bind))
    # The saved-goal queue supplements a company not covered by the direct read.
    other = replace(SOURCE, id='alibaba', company='阿里巴巴', career_url='https://campus-talent.alibaba.com/')
    monkeypatch.setattr(execution, 'enabled_company_sources', lambda *_, **__: [SOURCE, other])
    monkeypatch.setattr(execution, 'enabled_company_source_hosts', lambda **__: {'jobs.bytedance.com'})
    monkeypatch.setattr(execution, 'PlaywrightBrowserJobReader', lambda **_: ManyJobs())
    monkeypatch.setattr(web_search_service, 'create_web_search_provider', lambda *_: Provider())
    monkeypatch.setattr(execution.OfficialHiringResolver, 'resolve', resolve)
    monkeypatch.setattr(DirectRecruitmentSearch, '_source', source_after_history)
    monkeypatch.setattr(SearchGoalService, 'resume_candidates', lambda *_, **__: [pending])
    monkeypatch.setattr(SearchGoalService, 'refresh_candidates', lambda *_, **__: [])
    goal = SearchGoal(id='speed-goal', user_id='owner', name='test', input_text=QUERY,
        query=QUERY, conditions={}, condition_sources={}, version=1, company_ids=['bytedance', 'alibaba'])
    db_session.add(goal)
    db_session.commit()
    run = DiscoveryRun(id='speed-run', user_id='owner', source='test', source_url=SOURCE.career_url,
        search_goal_id=goal.id, search_goal_version=1, search_query=QUERY, started_at=datetime.now(UTC))
    db_session.add(run)
    db_session.commit()
    await asyncio.wait_for(execution.execute_multiround_search(
        run_id=run.id, user_id='owner', query=QUERY, company_ids=['bytedance']), 3)
    db_session.refresh(run)
    assert searched.is_set()
    assert sum(m['filter_status'] == 'matched' for m in run.result_matches) == 3
    assert not any(step['tool'] == 'search_pause' for step in run.agent_trace)


@pytest.mark.asyncio
async def test_failed_official_listing_is_still_eligible_for_web_fallback(db_session, monkeypatch):
    from sqlalchemy.orm import sessionmaker

    from src.config import Settings
    from src.domain.discovery import DiscoveryRun
    from src.services import multiround_search as execution
    from src.services import web_search_service
    from src.services.discovery_sources import SourcePayloadError

    class FailedBrowser(ManyJobs):
        async def read_search_listing(self, url):
            raise SourcePayloadError('Incomplete official listing response')

    queries = []
    class Provider:
        source_id, source_url = 'test', SOURCE.career_url
        def __init__(self, query):
            self.query = query
        async def discover(self):
            queries.append(self.query)
            return []

    settings = Settings(_env_file=None, web_search_direct_sources_enabled=True,
        web_search_target_jobs=15, web_search_max_rounds=1, web_search_budget_seconds=5)
    monkeypatch.setattr(execution, 'get_settings', lambda: settings)
    monkeypatch.setattr(execution, 'SessionLocal', sessionmaker(bind=db_session.bind))
    monkeypatch.setattr(execution, 'enabled_company_sources', lambda *_, **__: [SOURCE,
        replace(SOURCE, id='baidu', company='百度', career_url='https://talent.baidu.com/')])
    monkeypatch.setattr(execution, 'enabled_company_source_hosts', lambda **__: {'jobs.bytedance.com'})
    monkeypatch.setattr(execution, 'PlaywrightBrowserJobReader', lambda **_: FailedBrowser())
    monkeypatch.setattr(web_search_service, 'create_web_search_provider', lambda q, *_: Provider(q))
    run = DiscoveryRun(id='fallback-run', user_id='owner', source='test', source_url=SOURCE.career_url,
        search_query=QUERY, started_at=datetime.now(UTC))
    db_session.add(run)
    db_session.commit()
    await execution.execute_multiround_search(run_id=run.id, user_id='owner', query=QUERY, company_ids=[])
    assert len(queries) == 1
    assert '字节跳动 site:jobs.bytedance.com' in queries[0]


class ManyJobs(PortalQueryBrowser):
    def __init__(self, count=25, excluded_first=0):
        super().__init__()
        self.count, self.excluded_first, self.calls = count, excluded_first, []

    async def read_search_listing(self, url):
        self.calls.append(url)
        page = await super().read_search_listing(url)
        params = parse_qs(urlsplit(url).query)
        if not params:
            return page
        offset = (int(params['current'][0]) - 1) * 10
        items = [{**ITEM, 'id': str(i), 'requirement': '仅面向2026届毕业生' if i < self.excluded_first else ITEM['requirement']}
                 for i in range(offset, min(offset + 10, self.count))]
        page.recruitment_api[0]['payload']['data'] = {'job_post_list': items, 'count': self.count}
        from dataclasses import replace
        return replace(page, raw_html=''.join(f'<a href="/campus/position/{i["id"]}/detail">Agent</a>' for i in items))


def direct(browser, **kwargs):
    return DirectRecruitmentSearch(sources=[SOURCE], query=QUERY, reader=None,
        browser=browser, on_event=lambda *_: None, **kwargs)


@pytest.mark.asyncio
async def test_first_three_reads_then_resume_uses_unread_page_buffer():
    browser = ManyJobs(excluded_first=2)
    first = direct(browser)
    found = []
    await first.discover(found.extend)
    state = first.states[SOURCE.id]
    assert [c.source_job_id for c in found] == ['2', '3', '4']
    assert len(state['matched_urls']) == 3
    assert state['status'] == 'paused' and state['reason'] == 'company_read_limit'
    assert [i['id'] for i in state['buffer']] == ['5', '6', '7', '8', '9', '0', '1']
    calls = len(browser.calls)
    second = direct(browser, states=json.loads(json.dumps(first.states)))
    more = []
    await second.discover(more.extend)
    assert [c.source_job_id for c in more] == ['5', '6', '7']
    assert len(browser.calls) == calls
    assert len(second.states[SOURCE.id]['matched_urls']) == 6


@pytest.mark.asyncio
async def test_continuation_eventually_reads_page_three_without_restarting():
    browser, states, seen = ManyJobs(), {}, []
    for _ in range(8):
        search = direct(browser, states=states)
        await search.discover(lambda items: seen.extend(i.source_job_id for i in items))
        states = copy.deepcopy(search.states)
    assert seen == list(map(str, range(24)))
    assert sum('keywords=' not in url for url in browser.calls) == 1
    assert any(parse_qs(urlsplit(url).query).get('current') == ['3'] for url in browser.calls)


@pytest.mark.asyncio
async def test_exhaustion_is_reported_only_after_all_query_terms_are_checked():
    search = direct(ManyJobs(count=2))
    found = []
    await search.discover(found.extend)
    assert len(found) == 2
    assert search.states[SOURCE.id]['status'] == 'completed'
    assert search.states[SOURCE.id]['pages_checked'] == 3


@pytest.mark.asyncio
async def test_timeout_and_failed_verification_preserve_inflight_item():
    async def blocked(_):
        await asyncio.sleep(1)
    search = direct(ManyJobs(), verification_seconds=.01)
    await search.discover(lambda _: None, await_result=blocked)
    assert search.states[SOURCE.id]['reason'] == 'company_read_limit'
    assert any(record['candidate']['source_job_id'] == '0'
               for record in search.states[SOURCE.id]['pending_candidates'].values())
    assert not search.states[SOURCE.id]['matched_urls']
    async def failed(_):
        return None
    retry = direct(ManyJobs(), states=search.states)
    await retry.discover(lambda _: None, await_result=failed)
    assert retry.states[SOURCE.id]['status'] == 'paused'
    assert retry.states[SOURCE.id]['reason'] in {'verification_pending', 'company_read_limit'}
    assert any(record['candidate']['source_job_id'] == '0'
               for record in retry.states[SOURCE.id]['pending_candidates'].values())


@pytest.mark.asyncio
async def test_three_reads_stop_even_when_no_final_result_matches():
    search = direct(ManyJobs())
    async def reviewed(candidate):
        return int(candidate.source_job_id) >= 4
    found = []
    await search.discover(found.extend, await_result=reviewed)
    assert len(found) == 3
    assert len(search.states[SOURCE.id]['matched_urls']) == 0
    assert search.states[SOURCE.id]['buffer']


def test_cursor_storage_is_scoped_to_owner_goal_version_and_hides_page_payloads(db_session):
    goal = SearchGoal(id='goal', user_id='owner', name='test', input_text=QUERY, query=QUERY,
                      conditions={}, condition_sources={}, version=1, company_ids=['bytedance'])
    db_session.add(goal)
    db_session.commit()
    store = CompanyProgressStore(db_session, user_id='owner', goal_id='goal', version=1)
    state = {'status': 'paused', 'matched_urls': ['one'], 'started_at': datetime.now(UTC).isoformat(),
             'strategy': 'official_listing',
             'buffer': [{'private_cursor': True}], 'pages_checked': 1}
    store.save('bytedance', state)
    db_session.refresh(goal)
    summary = progress_summaries(goal)[0]
    assert summary['can_continue'] and summary['matched_count'] == 1
    assert 'buffer' not in summary
    stranger = CompanyProgressStore(db_session, user_id='other', goal_id='goal', version=1)
    assert stranger.load() == {}
    stranger.save('bytedance', {'status': 'completed'})
    assert store.load()['bytedance']['status'] == 'paused'
    goal.version = 2
    db_session.commit()
    assert store.load() == {}
    store.save('bytedance', {'status': 'completed'})
    assert not progress_summaries(goal)[0]['can_continue']


def test_expired_or_naive_cursor_cannot_be_resumed():
    assert not fresh_cursor({'started_at': (datetime.now(UTC) - timedelta(days=8)).isoformat()})
    assert not fresh_cursor({'started_at': datetime.now(UTC).replace(tzinfo=None).isoformat()})


@pytest.mark.asyncio
async def test_preview_does_not_wait_for_every_slow_supplemental_page():
    from time import monotonic

    from src.services.search_pipeline import run_search_pipeline
    from tests.test_search_execution import candidate

    events = []
    async def search(*_):
        return [candidate(1), candidate(2)]
    async def verify(item):
        if item.source_url == candidate(2).source_url:
            await asyncio.sleep(5)
        return item.source_url, True
    started = monotonic()
    stop = await run_search_pipeline(search=search, verify=verify, report=lambda *_: None,
        canonicalize=lambda url: url, max_rounds=1, max_concurrency=2, seconds=10,
        verification_seconds=10, drain_grace_seconds=.03,
        on_event=lambda kind, data: events.append(kind))
    assert monotonic() - started < 1
    assert 'queue_budget' in events and '剩余岗位保留待核验' in stop


@pytest.mark.parametrize('case', json.loads((Path(__file__).parent / 'fixtures/agent_duties_trial_20261016.json').read_text(encoding='utf-8')))
def test_real_trial_agent_duties(case):
    stub = JobStub(source_id='public-trial', source_job_id='trial', published_at=None,
        detail_url=case['source_url'], **{k: case[k] for k in ('company', 'title', 'locations', 'job_type', 'raw_content')})
    result = classify_discovery_job(stub, query='2027届北京或上海AI Agent/RAG校招，不考虑实习和社招')
    assert result.filter_status == case['expected']


def test_official_operations_category_does_not_pass_on_an_engineering_title():
    job = payload_stub({**ITEM, 'job_category': {'name': '运营'},
        'description': '负责Agent数据与评测体系建设，梳理Agent业务场景数据需求。'},
        company=SOURCE.company, listing_url=SOURCE.career_url + 'position')
    assert '官网职能分类：运营' in job.raw_content
    assert classify_discovery_job(job, query=QUERY).filter_status == 'pending'


@pytest.mark.asyncio
async def test_execution_persists_three_then_continues_only_the_selected_company(db_session, monkeypatch):
    from sqlalchemy.orm import sessionmaker

    from src.config import Settings
    from src.domain.discovery import DiscoveryRun
    from src.services import multiround_search as execution
    from src.services import web_search_service
    from src.services.search_goal_service import SearchGoalService

    browser = ManyJobs()
    class Provider:
        source_id = 'test'
        async def discover(self):
            pytest.fail('A fulfilled company quota must not trigger another web request')
    settings = Settings(_env_file=None, web_search_direct_sources_enabled=True,
                        web_search_target_jobs=3, web_search_budget_seconds=5)
    monkeypatch.setattr(execution, 'get_settings', lambda: settings)
    monkeypatch.setattr(execution, 'SessionLocal', sessionmaker(bind=db_session.bind))
    monkeypatch.setattr(execution, 'enabled_company_sources', lambda *args, **kwargs: [SOURCE])
    monkeypatch.setattr(execution, 'enabled_company_source_hosts', lambda **__: {'jobs.bytedance.com'})
    monkeypatch.setattr(execution, 'PlaywrightBrowserJobReader', lambda **kwargs: browser)
    monkeypatch.setattr(web_search_service, 'create_web_search_provider', lambda *args: Provider())
    goal = SearchGoalService(db_session).save(user_id='owner', name='test', input_text=QUERY,
        conditions=SearchGoalConditions(locations=['上海'], roles=['AI Agent', 'RAG'],
            job_types=['校招'], graduation_years=[2027]),
        condition_sources={'roles': '用户确认'}, company_ids=['bytedance'])
    for run_id, continuation in [('first', None), ('next', 'bytedance')]:
        run = DiscoveryRun(id=run_id, user_id='owner', source='test', source_url=SOURCE.career_url,
            search_goal_id=goal.id, search_goal_version=1, goal_conditions=goal.conditions,
            search_query=goal.query, continued_company_id=continuation, started_at=datetime.now(UTC))
        db_session.add(run)
        db_session.commit()
        await execution.execute_multiround_search(run_id=run_id, user_id='owner', query=goal.query, company_ids=['bytedance'])
        db_session.expire_all()
        assert len(run.result_matches) == 3
        assert all(item['filter_status'] == 'matched' for item in run.result_matches)
        assert run.status == 'SUCCEEDED'
    db_session.refresh(goal)
    assert len(goal.company_search_state['sources']['bytedance']['matched_urls']) == 6
    assert len(browser.calls) == 2  # Initial filter config + one list page, across both runs.
    from fastapi.testclient import TestClient

    from src.main import app

    client = TestClient(app)
    headers = {'X-User-ID': 'owner'}
    assert len(client.get('/api/candidates', headers=headers).json()) == 6
    assert len(client.get('/api/candidates?discovery_run_id=next', headers=headers).json()) == 3
    assert len(client.get('/api/discovery/leads?discovery_run_id=next', headers=headers).json()) == 3
    assert client.get('/api/candidates?discovery_run_id=next', headers={'X-User-ID': 'other'}).json() == []
    full = client.get('/api/discovery/runs/next', headers=headers)
    compact = client.get('/api/discovery/runs/next?compact=true', headers=headers)
    assert compact.json()['result_matches'] == full.json()['result_matches']
    assert len(compact.json()['agent_trace']) <= 1
    assert len(compact.content) < len(full.content)
    first_page = client.get('/api/discovery/runs?compact=true&limit=1', headers=headers).json()
    second_page = client.get('/api/discovery/runs?compact=true&limit=1&offset=1', headers=headers).json()
    assert len(first_page) == len(second_page) == 1 and first_page[0]['id'] != second_page[0]['id']


@pytest.mark.asyncio
async def test_unknown_open_status_still_consumes_a_detail_read(db_session, monkeypatch):
    from sqlalchemy.orm import sessionmaker

    from src.config import Settings
    from src.domain.discovery import DiscoveryRun
    from src.domain.job import JobAvailabilityStatus
    from src.services import multiround_search as execution
    from src.services import web_search_service
    from src.services.discovery_results import current_run_matches
    from src.services.job_lead_service import JobLeadService
    from src.services.search_goal_service import SearchGoalService

    browser = ManyJobs()
    class Provider:
        source_id = 'test'
        async def discover(self):
            pytest.fail('Three confirmed matches should finish this company')

    original = JobLeadService.verify_stub
    def verify_with_unknown_status(service, **kwargs):
        if kwargs['stub'].source_job_id in {'0', '1'}:
            kwargs['availability_status'] = JobAvailabilityStatus.UNKNOWN
        return original(service, **kwargs)

    settings = Settings(_env_file=None, web_search_direct_sources_enabled=True,
                        web_search_target_jobs=3, web_search_budget_seconds=5)
    monkeypatch.setattr(execution, 'get_settings', lambda: settings)
    monkeypatch.setattr(execution, 'SessionLocal', sessionmaker(bind=db_session.bind))
    monkeypatch.setattr(execution, 'enabled_company_sources', lambda *_, **__: [SOURCE])
    monkeypatch.setattr(execution, 'enabled_company_source_hosts', lambda **__: {'jobs.bytedance.com'})
    monkeypatch.setattr(execution, 'PlaywrightBrowserJobReader', lambda **__: browser)
    monkeypatch.setattr(web_search_service, 'create_web_search_provider', lambda *args: Provider())
    monkeypatch.setattr(JobLeadService, 'verify_stub', verify_with_unknown_status)
    service = SearchGoalService(db_session)
    goal = service.save(user_id='owner', name='test', input_text=QUERY,
        conditions=SearchGoalConditions(locations=['上海'], roles=['AI Agent', 'RAG'],
            job_types=['校招'], graduation_years=[2027]),
        condition_sources={'roles': '用户确认'}, company_ids=['bytedance'])
    run = DiscoveryRun(id='quota', user_id='owner', source='test', source_url=SOURCE.career_url,
        search_goal_id=goal.id, search_goal_version=1, goal_conditions=goal.conditions,
        search_query=goal.query, started_at=datetime.now(UTC))
    db_session.add(run)
    db_session.commit()
    await execution.execute_multiround_search(run_id=run.id, user_id='owner',
        query=goal.query, company_ids=['bytedance'])
    db_session.expire_all()
    statuses = [item['filter_status'] for item in run.result_matches]
    assert statuses.count('pending') == 2 and statuses.count('matched') == 1
    assert run.status == 'SUCCEEDED'
    state = goal.company_search_state['sources']['bytedance']
    assert len(state['checked_urls']) == 3 and len(state['matched_urls']) == 1
    assert state['reason'] == 'company_read_limit'
    current = current_run_matches(db_session, [run])[run.id]
    library = service.library('owner', goal.id)['result_matches']
    for items in (current, library):
        assert {m['job_posting_id']: m['filter_status'] for m in items} == {
            m['job_posting_id']: m['filter_status'] for m in run.result_matches}


def test_continue_api_checks_owner_version_cursor_and_scopes_background_work(db_session, monkeypatch):
    from fastapi.testclient import TestClient

    from src.api import discovery as api
    from src.config import Settings
    from src.main import app
    from src.services.search_intent import parse_conditions
    from src.services.url_reader import SafeHTTPReader
    from src.services.web_search_service import BingRSSSearchProvider

    settings = Settings(_env_file=None, web_search_direct_sources_enabled=True)
    monkeypatch.setattr(api, 'get_settings', lambda: settings)
    monkeypatch.setattr(api, 'create_web_search_provider', lambda query, companies: BingRSSSearchProvider(query=query, reader=SafeHTTPReader()))
    calls = []
    monkeypatch.setattr(api, 'execute_web_search_in_worker', lambda **kwargs: calls.append(kwargs))
    goal = SearchGoal(id='goal', user_id='owner', name='test', input_text=QUERY, query=QUERY,
        conditions=parse_conditions(QUERY).model_dump(), condition_sources={}, version=1, company_ids=['bytedance'])
    db_session.add(goal)
    db_session.commit()
    store = CompanyProgressStore(db_session, user_id='owner', goal_id='goal', version=1)
    store.save('bytedance', {'status':'paused', 'strategy':'official_listing', 'matched_urls':[],
                            'started_at':datetime.now(UTC).isoformat()})
    client = TestClient(app)
    payload = {'expected_version':1, 'continue_company_id':'bytedance'}
    url = '/api/discovery/goals/goal/search'
    assert client.post(url, json=payload, headers={'X-User-ID':'other'}).status_code == 404
    assert client.post(url, json={**payload, 'expected_version':2}, headers={'X-User-ID':'owner'}).status_code == 409
    assert client.post(url, json={**payload, 'continue_company_id':'nio'}, headers={'X-User-ID':'owner'}).status_code == 409
    response = client.post(url, json=payload, headers={'X-User-ID':'owner'})
    assert response.status_code == 202, response.text
    assert response.json()['continued_company_id'] == 'bytedance'
    assert calls[0]['company_ids'] == ['bytedance']
    assert client.post(url, json=payload, headers={'X-User-ID':'owner'}).json()['id'] == response.json()['id']
    assert len(calls) == 1
    assert client.post(url, json={'expected_version':1}, headers={'X-User-ID':'owner'}).status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize('timed_out', [False, True])
async def test_supplemental_search_respects_company_pause_and_stops_without_improvement(db_session, monkeypatch, timed_out):
    from dataclasses import replace

    from sqlalchemy import select
    from sqlalchemy.orm import sessionmaker

    from src.config import Settings
    from src.domain.discovery import DiscoveryRun, JobLead
    from src.services import multiround_search as execution
    from src.services import web_search_service
    from src.services.job_lead_service import JobLeadService
    from src.services.lead_providers import LeadCandidate, LeadProviderKind

    class Browser(ManyJobs):
        async def read_search_listing(self, url):
            if timed_out:
                await asyncio.sleep(1)
            return await super().read_search_listing(url)
    calls = []
    class Provider:
        source_id = 'test'
        async def discover(self):
            calls.append(1)
            if timed_out:
                return [LeadCandidate(provider=LeadProviderKind.EXTERNAL_AGENT, source_url=SOURCE.career_url + 'position/999/detail', discovered_at=datetime.now(UTC))]
            return []
    async def no_extra_verification(*args, **kwargs):
        pytest.fail('Web fallback must not restart a paused company')
    settings = Settings(_env_file=None, web_search_direct_sources_enabled=True,
        web_search_target_jobs=15, web_search_budget_seconds=5,
        web_search_company_seconds=.01 if timed_out else 3,
        web_search_max_rounds=1 if timed_out else 6)
    monkeypatch.setattr(execution, 'get_settings', lambda: settings)
    monkeypatch.setattr(execution, 'SessionLocal', sessionmaker(bind=db_session.bind))
    monkeypatch.setattr(execution, 'enabled_company_sources', lambda *_, **__: [SOURCE, replace(SOURCE, id='baidu', company='百度', career_url='https://talent.baidu.com/')])
    monkeypatch.setattr(execution, 'enabled_company_source_hosts', lambda **__: {'jobs.bytedance.com'})
    monkeypatch.setattr(execution, 'PlaywrightBrowserJobReader', lambda **kwargs: Browser())
    monkeypatch.setattr(web_search_service, 'create_web_search_provider', lambda *_: Provider())
    monkeypatch.setattr(JobLeadService, 'verify_url', no_extra_verification)
    run = DiscoveryRun(id='supplemental', user_id='owner', source='test', source_url=SOURCE.career_url,
                       search_query=QUERY, started_at=datetime.now(UTC))
    db_session.add(run)
    db_session.commit()
    await execution.execute_multiround_search(run_id=run.id, user_id='owner', query=QUERY, company_ids=[])
    db_session.expire_all()
    if timed_out:
        lead = db_session.scalar(select(JobLead).where(JobLead.discovery_run_id == run.id))
        assert lead.status == 'DEFERRED' and lead.failure_code == 'company_paused'
    else:
        assert len(calls) == 2
        assert sum(m['filter_status'] == 'matched' for m in run.result_matches) == 3
        assert any('连续两轮补搜' in (step.get('decision') or '') for step in run.agent_trace)
