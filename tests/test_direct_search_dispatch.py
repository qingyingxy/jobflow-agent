"""Behavioral checks for bounded discovery independent of final verification."""
import asyncio
import json
from dataclasses import replace

import pytest

from tests.test_company_search_progress import ManyJobs, direct
from tests.test_direct_recruitment_search import SOURCE


@pytest.mark.asyncio
async def test_first_three_publish_and_producer_finishes_without_waiting_for_reviews():
    from datetime import UTC, datetime

    from src.services.direct_recruitment_search import DirectJobEvidence, payload_stub
    from src.services.lead_providers import LeadCandidate, LeadProviderKind
    from tests.test_direct_recruitment_search import ITEM

    search = direct(ManyJobs(), company_seconds=.05)
    stub = payload_stub(ITEM, company=SOURCE.company, listing_url=SOURCE.career_url + 'position')

    async def source_items(source):
        for index in range(6):
            item = replace(stub, source_job_id=str(index),
                           detail_url=SOURCE.career_url + f'position/{index}/detail')
            search.evidence[item.detail_url] = DirectJobEvidence(
                item, source.career_url, '', source.career_url, {}, True)
            yield LeadCandidate(provider=LeadProviderKind.EXTERNAL_AGENT,
                                source_url=item.detail_url, source_job_id=str(index),
                                discovered_at=datetime.now(UTC))

    search._source = source_items
    published, release = asyncio.Event(), asyncio.Event()
    found, events = [], []
    search.on_event = lambda kind, data: events.append((kind, data))

    def publish(items):
        found.extend(items)
        if len(found) == 3:
            published.set()

    async def reviewed(candidate):
        await release.wait()
        return candidate.source_job_id != '0'

    task = asyncio.create_task(search.discover(publish, await_result=reviewed))
    try:
        await asyncio.wait_for(published.wait(), 1)
        # Hold verification longer than the company's entire read allowance.
        await asyncio.sleep(.08)
        assert len(found) == 3 and task.done()
        release.set()
        await asyncio.wait_for(task, 1)
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    state = search.states[SOURCE.id]
    assert [c.source_job_id for c in found] == ['0', '1', '2']
    assert not state['matched_urls'] and state['reason'] == 'company_read_limit'
    assert len(state['pending_candidates']) == 3
    timing = next(data for kind, data in events if kind == 'direct_search')
    assert timing['verification_wait_ms'] == 0


@pytest.mark.asyncio
async def test_waiting_for_verification_releases_company_reader_slot():
    search = direct(ManyJobs(), company_concurrency=1)
    search.sources.append(replace(SOURCE, id='second', company='另一家公司',
                                  career_url='https://second.example/campus/'))
    # The second source uses the same fixture transport but a separate cursor.
    seen, release, both = set(), asyncio.Event(), asyncio.Event()

    def publish(items):
        seen.update(c.company_hint for c in items)
        if len(seen) == 2:
            both.set()

    async def reviewed(_):
        await release.wait()
        return True

    # A synthetic producer avoids sharing fixture page state between sources.
    from datetime import UTC, datetime

    from src.services.direct_recruitment_search import DirectJobEvidence, payload_stub
    from src.services.lead_providers import LeadCandidate, LeadProviderKind
    from tests.test_direct_recruitment_search import ITEM

    async def source_items(source):
        for index in range(5):
            stub = payload_stub({**ITEM, 'id': str(index)}, company=source.company,
                                listing_url=source.career_url + 'position')
            search.evidence[stub.detail_url] = DirectJobEvidence(
                stub, source.career_url, '', source.career_url, {}, True)
            yield LeadCandidate(provider=LeadProviderKind.EXTERNAL_AGENT,
                                source_url=stub.detail_url, source_job_id=str(index),
                                company_hint=source.company, discovered_at=datetime.now(UTC))

    search._source = source_items
    task = asyncio.create_task(search.discover(publish, await_result=reviewed))
    try:
        await asyncio.wait_for(both.wait(), 1)
        release.set()
        await asyncio.wait_for(task, 1)
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert all(len(state['pending_candidates']) + len(state['checked_urls']) == 3 for state in search.states.values())


@pytest.mark.asyncio
async def test_cancelled_prefetch_resumes_saved_candidates_without_repeating_completed_jobs():
    browser = ManyJobs()
    first = direct(browser)
    ready, first_finished = asyncio.Event(), asyncio.Event()
    found = []

    def publish(items):
        found.extend(items)
        if len(found) >= 3:
            ready.set()

    async def reviewed(candidate):
        if candidate.source_job_id == '0':
            first_finished.set()
            return True
        await asyncio.Event().wait()

    task = asyncio.create_task(first.discover(publish, await_result=reviewed))
    try:
        await asyncio.wait_for(ready.wait(), 1)
        await asyncio.wait_for(first_finished.wait(), 1)
        # Let the completed acknowledgement persist before cancellation.
        while not first.states[SOURCE.id]['checked_urls']:
            await asyncio.sleep(0)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    states = json.loads(json.dumps(first.states))
    assert states[SOURCE.id]['reason'] in {'interrupted', 'company_read_limit'}
    assert len(states[SOURCE.id]['pending_candidates']) == 2
    calls = len(browser.calls)
    resumed = direct(browser, states=states)
    more = []
    await resumed.discover(more.extend)
    assert [c.source_job_id for c in more] == ['1', '2', '3']
    assert len(browser.calls) == calls
    assert not resumed.states[SOURCE.id]['pending_candidates']
    assert len(resumed.states[SOURCE.id]['matched_urls']) == 4


@pytest.mark.asyncio
async def test_unfinished_verification_is_resumable_and_not_a_listing_payload_error():
    search = direct(ManyJobs())

    async def unfinished(_):
        return None

    await search.discover(lambda _: None, await_result=unfinished)
    state = search.states[SOURCE.id]
    assert state['status'] == 'paused' and state['reason'] == 'verification_pending'
    assert state['pending_candidates'] and not state['checked_urls']
    resumed = direct(ManyJobs(), states=json.loads(json.dumps(search.states)))
    found = []
    await resumed.discover(found.extend)
    assert found[0].source_job_id == '0'
    assert len(resumed.states[SOURCE.id]['matched_urls']) == 3


@pytest.mark.asyncio
async def test_company_waiting_for_review_does_not_hold_a_detail_worker():
    from src.services.search_pipeline import run_search_pipeline
    from tests.test_search_scheduling import lead

    active, completed = set(), []
    other_read, release = asyncio.Event(), asyncio.Event()
    candidates = [lead(1, host='a.example'), lead(2, host='a.example'),
                  lead(3, host='b.example')]

    def company(candidate):
        return candidate.source_url.split('/')[2]

    async def search(*_):
        return candidates

    async def verify(candidate):
        if company(candidate) == 'b.example':
            other_read.set()
        return candidate.source_url, False

    async def review(url):
        await release.wait()
        return url, False

    def done(candidate, result, error):
        active.remove(company(candidate))
        completed.append(candidate.source_url)

    task = asyncio.create_task(run_search_pipeline(
        search=search, verify=verify, review=review, review_concurrency=2,
        report=lambda *_: None, canonicalize=lambda url: url,
        max_rounds=1, max_concurrency=1, seconds=2,
        can_verify=lambda candidate: company(candidate) not in active,
        on_candidate_start=lambda candidate: active.add(company(candidate)),
        on_candidate_done=done))
    try:
        await asyncio.wait_for(other_read.wait(), 1)
        assert not completed
        release.set()
        await asyncio.wait_for(task, 1)
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert len(completed) == 3 and not active


@pytest.mark.asyncio
async def test_duplicate_finished_failure_acknowledges_without_reading_again():
    from src.services.search_pipeline import VerificationFailure, run_search_pipeline
    from tests.test_search_scheduling import lead

    candidate = lead(1)
    acknowledged, reads = [], []
    first_done, second_done = asyncio.Event(), asyncio.Event()

    async def bootstrap(enqueue):
        enqueue([candidate])
        await first_done.wait()
        enqueue([candidate])
        await second_done.wait()

    def done(*args):
        acknowledged.append(args)
        (first_done if len(acknowledged) == 1 else second_done).set()

    async def verify(item):
        reads.append(item.source_url)
        return VerificationFailure('source_not_found')

    async def search(*_):
        return None

    await asyncio.wait_for(run_search_pipeline(
        bootstrap=bootstrap, search=search, verify=verify,
        report=lambda *_: None, canonicalize=lambda url: url,
        on_candidate_done=done, seconds=2), 1)
    assert reads == [candidate.source_url]
    assert len(acknowledged) == 2 and acknowledged[1][2] == 'source_not_found'


@pytest.mark.asyncio
async def test_late_acknowledgement_survives_producer_wait_budget():
    search = direct(ManyJobs(), verification_seconds=.01)
    receipts, found = {}, []

    def publish(items):
        found.extend(items)
        for candidate in items:
            receipts[candidate.source_url] = asyncio.get_running_loop().create_future()

    async def reviewed(candidate):
        return await asyncio.shield(receipts[candidate.source_url])

    await search.discover(publish, await_result=reviewed)
    assert len(found) == 3
    assert all(not future.cancelled() for future in receipts.values())
    search.record_result(found[0], True)
    search.record_result(found[0], True)
    state = search.states[SOURCE.id]
    assert state['checked_urls'] == state['matched_urls'] == [found[0].source_url]
    assert len(state['pending_candidates']) == 2


@pytest.mark.asyncio
async def test_direct_and_web_candidates_share_three_job_quota_during_overlap(db_session, monkeypatch):
    from sqlalchemy import select
    from sqlalchemy.orm import sessionmaker

    from src.config import Settings
    from src.domain.discovery import DiscoveryRun, JobLead
    from src.services import multiround_search as execution
    from src.services import web_search_service
    from src.services.direct_recruitment_search import DirectRecruitmentSearch
    from src.services.job_lead_service import JobLeadService
    from tests.test_company_coverage import goal_and_store, run_search
    from tests.test_direct_recruitment_search import QUERY

    candidates, verified = [], []
    ready, web_returned = asyncio.Event(), asyncio.Event()
    original_source = DirectRecruitmentSearch._source

    async def overlapping_source(self, source):
        iterator = original_source(self, source)
        try:
            for _ in range(6):
                candidates.append(await anext(iterator))
        finally:
            await iterator.aclose()
        ready.set()
        yield candidates[0]
        await web_returned.wait()
        for candidate in candidates[1:]:
            yield candidate

    class Provider:
        source_id, source_url = 'test', SOURCE.career_url

        async def discover(self):
            await ready.wait()
            web_returned.set()
            return [*candidates[3:], candidates[0]]

    original_verify = JobLeadService.verify_stub

    def track_verify(service, **kwargs):
        verified.append(kwargs['stub'].source_job_id)
        return original_verify(service, **kwargs)

    settings = Settings(_env_file=None, web_search_direct_sources_enabled=True,
                        web_search_role_review_enabled=False, company_discovery_enabled=False,
                        web_search_target_jobs=3, web_search_max_rounds=1, web_search_budget_seconds=3)
    monkeypatch.setattr(execution, 'get_settings', lambda: settings)
    monkeypatch.setattr(execution, 'SessionLocal', sessionmaker(bind=db_session.bind))
    monkeypatch.setattr(execution, 'enabled_company_sources', lambda *_, **__: [SOURCE])
    monkeypatch.setattr(execution, 'enabled_company_source_hosts', lambda **_: {'jobs.bytedance.com'})
    monkeypatch.setattr(execution, 'PlaywrightBrowserJobReader', lambda **_: ManyJobs())
    monkeypatch.setattr(web_search_service, 'create_web_search_provider', lambda *_: Provider())
    monkeypatch.setattr(DirectRecruitmentSearch, '_source', overlapping_source)
    monkeypatch.setattr(DirectRecruitmentSearch, 'fallback_ready', lambda *_: True)
    monkeypatch.setattr(JobLeadService, 'verify_stub', track_verify)
    goal, _ = goal_and_store(db_session, [SOURCE.id])
    goal.query = QUERY
    db_session.commit()
    await asyncio.wait_for(run_search(db_session, goal, 'overlap'), 2)
    run = db_session.get(DiscoveryRun, 'coverage-run-overlap')
    assert len(verified) == len(set(verified)) == 3
    assert len(run.result_matches) == 3
    assert all(match['filter_status'] == 'matched' for match in run.result_matches)
    assert len(goal.company_search_state['sources'][SOURCE.id]['matched_urls']) == 3
    leads = list(db_session.scalars(select(JobLead).where(JobLead.discovery_run_id == run.id)))
    assert any(lead.status == 'DEFERRED' for lead in leads)


@pytest.mark.asyncio
async def test_provisional_matches_do_not_stop_discovery_before_final_review(db_session, monkeypatch):
    from sqlalchemy.orm import sessionmaker

    from src.config import Settings
    from src.domain.discovery import DiscoveryRun
    from src.services import multiround_search as execution
    from src.services import web_search_service
    from src.services.job_role_review import JobRoleReviewer
    from tests.test_company_coverage import goal_and_store, run_search
    from tests.test_direct_recruitment_search import QUERY

    published, reviewed = set(), set()
    three_read, release = asyncio.Event(), asyncio.Event()
    classify = execution.classify_discovery_job

    def classify_after_review(job, **kwargs):
        match = classify(job, **kwargs)
        if job.source_job_id not in reviewed:
            published.add(job.source_job_id)
            if len(published) == 3:
                three_read.set()
        elif job.source_job_id in {'0', '1'}:
            return replace(match, filter_status='excluded')
        return match

    async def review(self, job, **kwargs):
        await release.wait()
        reviewed.add(job.source_job_id)

    class Provider:
        source_id, source_url = 'test', SOURCE.career_url

        async def discover(self):
            pytest.fail('Final matches should satisfy the company without a web request')

    settings = Settings(_env_file=None, web_search_direct_sources_enabled=True,
                        company_discovery_enabled=False, web_search_target_jobs=3,
                        web_search_max_rounds=1, web_search_budget_seconds=3)
    monkeypatch.setattr(execution, 'get_settings', lambda: settings)
    monkeypatch.setattr(execution, 'SessionLocal', sessionmaker(bind=db_session.bind))
    monkeypatch.setattr(execution, 'enabled_company_sources', lambda *_, **__: [SOURCE])
    monkeypatch.setattr(execution, 'enabled_company_source_hosts', lambda **_: {'jobs.bytedance.com'})
    monkeypatch.setattr(execution, 'PlaywrightBrowserJobReader', lambda **_: ManyJobs())
    monkeypatch.setattr(execution, 'classify_discovery_job', classify_after_review)
    monkeypatch.setattr(web_search_service, 'create_web_search_provider', lambda *_: Provider())
    monkeypatch.setattr(JobRoleReviewer, 'review', review)
    goal, _ = goal_and_store(db_session, [SOURCE.id])
    goal.query = QUERY
    db_session.commit()
    task = asyncio.create_task(run_search(db_session, goal, 'final-review'))
    try:
        await asyncio.wait_for(three_read.wait(), 1)
        db_session.refresh(goal)
        assert not goal.company_search_state['sources'][SOURCE.id]['matched_urls']
        assert not task.done()
        release.set()
        await asyncio.wait_for(task, 1)
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    run = db_session.get(DiscoveryRun, 'coverage-run-final-review')
    assert [m['filter_status'] for m in run.result_matches].count('matched') == 1
    assert len(published) == 3
    assert len(goal.company_search_state['sources'][SOURCE.id]['matched_urls']) == 1
