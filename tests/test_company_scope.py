from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient

from src.domain.discovery import DiscoveryRun, JobLead
from src.domain.search_goal import SearchGoal
from src.main import app
from src.services.company_registry import CompanySource
from src.services.company_scope import in_company_scope
from src.services.search_goal_service import SearchGoalService
from src.services.search_intent import parse_conditions
from tests.test_search_goals import add_posting


def test_company_scope_keeps_ats_tenants_separate_and_allows_verified_names():
    source = CompanySource('one', '企业甲', 'A', 'https://app.mokahr.com/campus-recruitment/one/123', 'test')
    assert in_company_scope(SimpleNamespace(source_url=source.career_url + '/job/1'), [source])
    assert not in_company_scope(SimpleNamespace(source_url='https://app.mokahr.com/campus-recruitment/two/456/job/1',
                                                company='企业甲', source_id='one'), [source])
    assert in_company_scope(SimpleNamespace(source_url='https://alternate.example/jobs/1', company='企业甲'), [source])
    assert not in_company_scope(SimpleNamespace(source_url='https://other.example/jobs/1', company='企业乙'), [source])


def test_company_library_history_and_refresh_share_scope_without_changing_favorites(db_session):
    chosen = add_posting(db_session, identifier='chosen', age=10)
    chosen.company, chosen.source_url = '百度', 'https://talent.baidu.com/jobs/detail/chosen'
    other = add_posting(db_session, identifier='other', age=10)
    other.company, other.source_url = '字节跳动', 'https://jobs.bytedance.com/campus/position/other/detail'
    db_session.commit()
    service = SearchGoalService(db_session)
    goal = service.save(user_id='owner', input_text='2027届后端校招', conditions=parse_conditions('2027届后端校招'),
                        condition_sources={}, company_ids=['baidu'])
    run = DiscoveryRun(id='scope-run', user_id='owner', source='test', source_url='https://example.com',
        status='SUCCEEDED', started_at=datetime.now(UTC), search_query=goal.query,
        search_goal_id=goal.id, search_goal_version=goal.version, goal_conditions=goal.conditions,
        library_baseline={}, result_matches=[{'job_posting_id':j.id,'match_tier':'strict'} for j in (chosen, other)],
        agent_trace=[{'phase':'plan','tool':'query_plan','outcome':'completed',
                      'observation':'scope','decision':'test','details':{'company_ids':['baidu']}}])
    db_session.add(run)
    for job in (chosen, other):
        db_session.add(JobLead(id='lead-'+job.id, user_id='owner', discovery_run_id=run.id,
            source_url=job.source_url, normalized_url=job.source_url, provider='external_agent',
            title_hint=job.title, company_hint=job.company, discovered_at=datetime.now(UTC),
            status='VERIFIED', job_posting_id=job.id))
    db_session.commit()
    with TestClient(app) as client:
        headers={'X-User-ID':'owner'}
        library=client.get(f'/api/discovery/goals/{goal.id}/library?include_progress=false',headers=headers).json()
        assert [m['job_posting_id'] for m in library['result_matches']] == [chosen.id]
        assert library['lead_ids'] == ['lead-chosen']
        for job, status in ((chosen, 200), (other, 404)):
            detail = client.get(f'/api/discovery/goals/{goal.id}/jobs/{job.id}?expected_version={goal.version}', headers=headers)
            assert detail.status_code == status
        assert {u['job_posting_id'] for u in library['updates']} <= {chosen.id}
        assert sum(library['counts'][s] for s in ('matched','pending','excluded')) == 1
        from src.services.company_scope import goal_company_sources

        refreshed=service.refresh_candidates('owner',query=goal.query,conditions=goal.conditions,
            company_sources=goal_company_sources(db_session,goal),limit=1)
        assert [c.source_url for c in refreshed] == [chosen.source_url]
        # Both complete and compact history must also hide cross-company old results.
        for path in ('/api/discovery/runs','/api/discovery/runs/scope-run'):
            for suffix in ('','?compact=true'):
                response=client.get(path+suffix,headers=headers)
                assert response.status_code == 200, response.text
                data=response.json()
                data=data[0] if isinstance(data,list) else data
                assert [m['job_posting_id'] for m in data['result_matches']] == [chosen.id]
        favorites=client.get('/api/candidates?status=SAVED',headers=headers).json()
        assert {c['job_posting_id'] for c in favorites} == {chosen.id,other.id}
    # Changing the goal later cannot rewrite the old run's employer scope.
    stored=db_session.get(SearchGoal,goal.id)
    stored.company_ids=['bytedance']
    stored.version += 1
    db_session.commit()
    from src.services.discovery_results import current_run_matches

    assert [m['job_posting_id'] for m in current_run_matches(db_session,[run])[run.id]] == [chosen.id]
