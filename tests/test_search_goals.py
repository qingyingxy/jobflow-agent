from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select

from src.api import discovery as discovery_api
from src.api import search_goals as goals_api
from src.config import Settings
from src.domain.application import CandidateJob
from src.domain.discovery import DiscoveryRun, DiscoverySearchPlan
from src.domain.job import JobPosting
from src.domain.models import UserProfile
from src.domain.search_goal import SearchGoalConditions
from src.infrastructure.llm_client import FakeModelClient, ModelTimeoutError
from src.main import app
from src.services.discovery_matching import classify_discovery_job
from src.services.discovery_sources import JobStub
from src.services.search_goal_service import SearchGoalService
from src.services.search_intent import (
    conditions_query,
    interpret_intent,
    parse_conditions,
)

BASE = JobStub(
    source_id="fixture",
    source_job_id="one",
    company="测试公司",
    title="后端工程师",
    locations=["上海"],
    job_type="campus",
    published_at=None,
    detail_url="https://example.com/jobs/one",
    raw_content="面向2027届毕业生。负责后端Python服务开发。",
)


@pytest.fixture(autouse=True)
def offline_goal_parser(monkeypatch):
    settings = Settings(_env_file=None, structured_model_provider="fake")
    monkeypatch.setattr(goals_api, "get_settings", lambda: settings)
    from src.services import discovery_service

    monkeypatch.setattr(discovery_service, "get_settings", lambda: settings)


def create_goal(client, text="2027届上海Python后端校招，不考虑北京", **extra):
    response = client.post(
        "/api/discovery/goals",
        headers={"X-User-ID": "owner"},
        json={"input_text": text, **extra},
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.parametrize(
    "text,required,preferred",
    [
        ("2027届上海后端校招", ["上海"], []),
        ("上海优先，其他城市也可以，后端校招", [], ["上海"]),
        ("只考虑上海，Python优先，后端校招", ["上海"], []),
        ("上海后端校招 Python优先", ["上海"], []),
        ("上海后端校招Python优先", ["上海"], []),
        ("上海或杭州后端校招，Python优先", ["上海", "杭州"], []),
        ("上海优先但杭州必须，后端校招", ["杭州"], ["上海"]),
        ("上海必须杭州优先，后端校招", ["上海"], ["杭州"]),
        ("首选上海或杭州后端校招", [], ["上海", "杭州"]),
        ("上海、杭州优先的Python后端校招", [], ["上海", "杭州"]),
        ("只考虑上海，上海优先，后端校招", ["上海"], []),
        ("合肥或昆明后端校招", ["合肥", "昆明"], []),
        ("上海优先，杭州也接受，后端校招", [], ["上海", "杭州"]),
    ],
)
def test_local_location_scope(text, required, preferred):
    result = parse_conditions(text)
    assert result.locations == required
    assert result.preferred_locations == preferred


@pytest.mark.parametrize(
    "text,required,preferred",
    [
        ("上海后端校招 Python优先", [], ["python"]),
        ("上海后端校招 Python和Java优先", [], ["python", "java"]),
        ("上海后端校招 Python必须Java优先", ["python"], ["java"]),
        ("上海优先，Python后端校招", ["python"], []),
    ],
)
def test_keyword_preference_is_bound_to_the_keyword(text, required, preferred):
    result = parse_conditions(text)
    assert result.keywords == required
    assert result.preferred_keywords == preferred
    assert parse_conditions(conditions_query(result)) == result


@pytest.mark.parametrize("city,status", [("上海", "matched"), ("北京", "excluded")])
def test_optional_keyword_does_not_relax_city_or_make_missing_keyword_pending(city, status):
    job = replace(BASE, locations=[city], raw_content="面向2027届，负责后端服务开发。")
    result = classify_discovery_job(job, query="上海后端校招 Python优先")
    assert result.filter_status == status
    assert result.preference_score == 0
    with_keyword = classify_discovery_job(
        replace(job, raw_content=job.raw_content + "使用Python。"),
        query="上海后端校招 Python优先",
    )
    assert with_keyword.filter_status == status
    assert with_keyword.preference_score == 1


def test_typed_conditions_round_trip_arbitrary_fields():
    expected = SearchGoalConditions(
        locations=["湛江", "shanghai"],
        preferred_locations=["巴黎"],
        preferred_keywords=["Python"],
        roles=["固件开发", "C/C++"],
        graduation_years=[2027],
        pending_conditions=["硕士不限专业，年薪待定"],
    )
    assert parse_conditions(conditions_query(expected)) == expected


def test_matcher_consumes_structured_conditions_instead_of_reinterpreting_search_text():
    conditions = SearchGoalConditions(
        locations=["上海"], roles=["后端"], job_types=["校招"], graduation_years=[2027]
    )
    result = classify_discovery_job(
        BASE, query="北京社招", conditions=conditions.model_dump()
    )
    assert result.filter_status == "matched"


@pytest.mark.parametrize(
    "text,role,excluded",
    [
        ("上海AI校招", ["ai"], []),
        ("上海后端校招，排除人工智能", ["后端"], ["ai"]),
    ],
)
def test_generic_ai_scope_survives_saved_goal(text, role, excluded):
    conditions = parse_conditions(text)
    assert conditions.roles == role and conditions.excluded_roles == excluded
    assert parse_conditions(conditions_query(conditions)) == conditions


@pytest.mark.parametrize(
    "query,locations,status,score",
    [
        ("上海优先，后端校招", ["深圳"], "matched", 0),
        ("上海优先，后端校招", ["上海"], "matched", 1),
        ("只考虑上海，后端校招", ["深圳"], "excluded", 0),
        ("合肥后端校招", ["上海"], "excluded", 0),
        ("只考虑上海，后端校招，Python优先", ["深圳"], "excluded", 1),
    ],
)
def test_preference_is_ordering_not_qualification(query, locations, status, score):
    job = replace(
        BASE, locations=locations, raw_content=BASE.raw_content + "为合肥客户提供服务。"
    )
    result = classify_discovery_job(job, query=query)
    assert result.filter_status == status
    assert result.preference_score == score


@pytest.mark.asyncio
async def test_unknown_location_cannot_pass_from_customer_prose():
    conditions, _, _ = await interpret_intent(
        "湛江后端校招", settings=Settings(_env_file=None)
    )
    job = replace(BASE, raw_content=BASE.raw_content + "为湛江客户提供服务。")
    assert (
        classify_discovery_job(job, query=conditions_query(conditions)).filter_status
        == "pending"
    )


@pytest.mark.asyncio
async def test_model_extracts_complete_request_including_unknown_city_and_exclusions():
    model = FakeModelClient(
        output={
            "clauses": [
                {"field": "locations", "value": "湛江", "source_text": "湛江后端校招"},
                {"field": "roles", "value": "后端", "source_text": "湛江后端校招"},
                {"field": "job_types", "value": "校招", "source_text": "湛江后端校招"},
                {"field": "excluded_locations", "value": "北京", "source_text": "排除北京"},
            ]
        }
    )
    conditions, sources, notice = await interpret_intent(
        "湛江后端校招，排除北京", settings=Settings(_env_file=None), client=model
    )
    assert conditions.locations == ["湛江"]
    assert conditions.excluded_locations == ["北京"]
    assert not conditions.keywords and not conditions.pending_conditions
    assert "原文" in sources["locations"] and notice is None
    assert len(model.requests) == 1
    assert "湛江后端校招，排除北京" in model.last_request.messages[-1].content
    assert (
        classify_discovery_job(BASE, query=conditions_query(conditions)).filter_status
        == "excluded"
    )


@pytest.mark.asyncio
async def test_model_promoted_city_removes_only_conversational_prefix():
    model = FakeModelClient(
        output={
            "clauses": [
                {
                    "field": "locations",
                    "value": "湛江",
                    "source_text": "我想在湛江找后端校招",
                },
                {"field": "roles", "value": "后端", "source_text": "后端校招"},
                {"field": "job_types", "value": "校招", "source_text": "后端校招"},
            ]
        }
    )
    conditions, _, _ = await interpret_intent(
        "我想在湛江找后端校招", settings=Settings(_env_file=None), client=model
    )
    assert conditions.locations == ["湛江"]
    assert not conditions.keywords and not conditions.pending_conditions


@pytest.mark.asyncio
async def test_model_city_scope_and_keyword_priority_reach_distinct_fields():
    conditions, _, notice = await interpret_intent(
        "湛江后端校招 Python优先",
        settings=Settings(_env_file=None),
        client=FakeModelClient(output={"clauses": [
            {"field": "locations", "value": "湛江", "source_text": "湛江后端校招"},
            {"field": "roles", "value": "后端", "source_text": "湛江后端校招"},
            {"field": "job_types", "value": "校招", "source_text": "湛江后端校招"},
            {"field": "preferred_keywords", "value": "Python", "source_text": "Python优先"},
        ]}),
    )
    assert conditions.locations == ["湛江"] and notice is None
    assert conditions.preferred_keywords == ["Python"]
    assert not conditions.preferred_locations


@pytest.mark.asyncio
async def test_unknown_preferred_city_can_be_promoted_without_becoming_required():
    conditions, _, notice = await interpret_intent(
        "湛江优先，后端校招",
        settings=Settings(_env_file=None),
        client=FakeModelClient(output={"clauses": [
            {"field": "preferred_locations", "value": "湛江", "source_text": "湛江优先"},
            {"field": "roles", "value": "后端", "source_text": "后端校招"},
            {"field": "job_types", "value": "校招", "source_text": "后端校招"},
        ]}),
    )
    assert conditions.preferred_locations == ["湛江"] and notice is None
    assert not conditions.locations and not conditions.preferred_keywords


@pytest.mark.parametrize(
    "output,error",
    [
        (
            {
                "clauses": [
                    {
                        "field": "locations",
                        "value": "杭州",
                        "source_text": "湛江后端校招",
                    }
                ]
            },
            None,
        ),
        (
            {
                "clauses": [
                    {
                        "field": "locations",
                        "value": "湛江",
                        "source_text": "不存在的原文",
                    }
                ]
            },
            None,
        ),
        (None, ModelTimeoutError("timeout")),
    ],
)
@pytest.mark.asyncio
async def test_model_failure_keeps_original_request_without_guessed_filters(output, error):
    conditions, sources, notice = await interpret_intent(
        "湛江后端校招，排除北京",
        settings=Settings(_env_file=None),
        client=FakeModelClient(output=output, error=error),
    )
    assert not conditions.excluded_locations and not conditions.roles
    assert conditions.pending_conditions == ["湛江后端校招，排除北京"]
    assert sources["_intent_status"] == "needs_review" and notice


@pytest.mark.parametrize(
    "values",
    [
        {"locations": ["Shanghai"], "excluded_locations": ["上海"]},
        {"job_types": ["campus"], "excluded_job_types": ["校招"]},
        {"graduation_years": [20]},
    ],
)
def test_invalid_or_conflicting_conditions_fail_validation(values):
    with pytest.raises(ValidationError):
        SearchGoalConditions(**values)


def add_posting(session, user="owner", identifier="one", city="上海", age=0):
    now = datetime.now(UTC)
    job = JobPosting(
        id=identifier,
        title=BASE.title,
        company=BASE.company,
        locations=[city],
        job_type="campus",
        raw_content=BASE.raw_content,
        source_url=f"https://example.com/jobs/{identifier}",
        source_type="official",
        verification_status="VERIFIED_OFFICIAL",
        availability_status="ACTIVE",
        last_verified_at=now - timedelta(days=age),
        retrieved_at=now,
        trace_id="test",
        content_hash=f"hash-{identifier}",
    )
    session.add(job)
    session.add(
        CandidateJob(
            id=f"candidate-{identifier}",
            user_id=user,
            job_posting_id=identifier,
            status="SAVED",
        )
    )
    session.commit()
    return job


def test_library_reuses_jobs_keeps_selection_and_reclassifies_on_goal_change(
    db_session,
):
    job = add_posting(db_session)
    foreign = add_posting(db_session, user="foreign", identifier="foreign")
    with TestClient(app) as client:
        goal = create_goal(client)
        path = f"/api/discovery/goals/{goal['id']}"
        headers = {"X-User-ID": "owner"}
        library = client.get(path + "/library", headers=headers).json()
        assert library["counts"]["matched"] == 1
        assert library["counts"]["recommended"] == 1
        assert library["result_matches"][0]["review_status"] == "recommended"
        assert [m["job_posting_id"] for m in library["result_matches"]] == [job.id]
        assert foreign.id not in str(library)
        job.availability_status = "UNKNOWN"
        db_session.commit()
        partial = client.get(path + "/library", headers=headers).json()
        assert partial["counts"]["recommended"] == 1
        assert partial["counts"]["matched"] == partial["counts"]["needs_review"] == 0
        assert partial["counts"]["pending"] == 1
        assert SearchGoalService(db_session).snapshot("owner", goal["query"])[job.id]["review_status"] == "recommended"
        changed = client.patch(
            path,
            headers=headers,
            json={"input_text": "2027届北京后端校招", "expected_version": 1},
        )
        assert changed.status_code == 200
        assert changed.json()["version"] == 2
        assert (
            client.get(path + "/library", headers=headers).json()["counts"]["excluded"]
            == 1
        )
        candidate = db_session.scalar(
            select(CandidateJob).where(CandidateJob.job_posting_id == job.id)
        )
        assert candidate.status == "SAVED"
        assert (
            client.patch(
                path,
                headers=headers,
                json={"input_text": "上海后端校招", "expected_version": 1},
            ).status_code
            == 409
        )
        assert (
            client.get(path + "/library", headers={"X-User-ID": "foreign"}).status_code
            == 404
        )


def test_stale_jobs_pending_and_new_changed_closed_updates_are_distinct(db_session):
    old = add_posting(db_session, identifier="old", age=8)
    closed = add_posting(db_session, identifier="closed")
    with TestClient(app) as client:
        goal = create_goal(client)
    service = SearchGoalService(db_session)
    snapshot = service.snapshot("owner", query=goal["query"])
    db_session.add(
        DiscoveryRun(
            id="run",
            user_id="owner",
            source="test",
            source_url=BASE.detail_url,
            search_goal_id=goal["id"],
            search_goal_version=1,
            goal_conditions=goal["conditions"],
            library_baseline=snapshot,
            search_query=goal["query"],
            status="SUCCEEDED",
            started_at=datetime.now(UTC),
        )
    )
    old.content_hash = "changed-hash"
    closed.availability_status = "CLOSED"
    db_session.commit()
    add_posting(db_session, identifier="new")
    library = service.library("owner", goal["id"])
    assert {u["job_posting_id"]: u["kind"] for u in library["updates"]} == {
        "old": "changed",
        "closed": "closed",
        "new": "new",
    }
    assert {
        m["job_posting_id"]: m["filter_status"] for m in library["result_matches"]
    } == {"old": "pending", "closed": "excluded", "new": "matched"}
    assert library["counts"]["closed"] == 1


@pytest.mark.parametrize(
    "availability,age,verification,city,expected",
    [
        ("ACTIVE", 0, "VERIFIED_OFFICIAL", "上海", "matched"),
        ("UNKNOWN", 0, "VERIFIED_OFFICIAL", "上海", "pending"),
        ("ACTIVE", 8, "VERIFIED_OFFICIAL", "上海", "pending"),
        ("ACTIVE", 0, "LEGACY_UNVERIFIED", "上海", "pending"),
        ("CLOSED", 0, "VERIFIED_OFFICIAL", "上海", "excluded"),
        ("UNKNOWN", 0, "VERIFIED_OFFICIAL", "北京", "excluded"),
    ],
)
def test_run_api_library_and_baseline_agree_on_availability(
    db_session, availability, age, verification, city, expected
):
    from src.domain.discovery import JobLead

    job = add_posting(db_session, city=city, age=age)
    job.availability_status = availability
    job.verification_status = verification
    db_session.commit()
    with TestClient(app) as client:
        goal = create_goal(client)
        # An old run may have counted an uncertain job as matched.
        run = DiscoveryRun(
            id="availability-run", user_id="owner", source="test", source_url=BASE.detail_url,
            search_goal_id=goal["id"], search_goal_version=1, goal_conditions=goal["conditions"],
            search_query=goal["query"], status="SUCCEEDED", started_at=datetime.now(UTC),
            result_matches=[{"job_posting_id": job.id, "filter_status": "matched", "match_tier": "strict"}],
        )
        db_session.add(run)
        db_session.add(JobLead(
            id="availability-lead", discovery_run_id=run.id, user_id="owner", provider="test",
            source_url=job.source_url, normalized_url=job.source_url, job_posting_id=job.id,
            status="VERIFIED", discovered_at=datetime.now(UTC),
        ))
        db_session.commit()
        headers = {"X-User-ID": "owner"}
        library = client.get(f"/api/discovery/goals/{goal['id']}/library", headers=headers).json()
        response = client.get(f"/api/discovery/runs/{run.id}", headers=headers)
        assert response.status_code == 200, response.text
        actual = response.json()["result_matches"][0]
        saved = library["result_matches"][0]
        assert actual["filter_status"] == saved["filter_status"] == expected
        assert actual["checks"] == saved["checks"]
        # The current-run polling endpoint must agree with the detailed result,
        # including changed availability and personal requirement notices.
        compact = client.get(f"/api/discovery/runs/{run.id}?compact=true", headers=headers)
        assert compact.json()["result_matches"] == response.json()["result_matches"]
    assert SearchGoalService(db_session).snapshot("owner", query=goal["query"])[job.id]["filter_status"] == expected
    assert job.availability_status == availability


def test_library_does_not_label_saved_jobs_as_new_before_search(db_session):
    add_posting(db_session)
    with TestClient(app) as client:
        goal = create_goal(client)
    library = SearchGoalService(db_session).library("owner", goal["id"])
    assert library["counts"]["matched"] == 1
    assert library["latest_run_id"] is None and not library["updates"]


def test_changed_goal_keeps_saved_jobs_but_drops_old_run_progress_and_baseline(db_session):
    add_posting(db_session, city="北京")
    with TestClient(app) as client:
        goal = create_goal(client)
        db_session.add(DiscoveryRun(
            id="old-goal-run", user_id="owner", source="test", source_url=BASE.detail_url,
            search_goal_id=goal["id"], search_goal_version=1,
            goal_conditions=goal["conditions"], library_baseline={},
            status="SUCCEEDED", started_at=datetime.now(UTC),
        ))
        db_session.commit()
        changed = client.patch(
            f"/api/discovery/goals/{goal['id']}", headers={"X-User-ID": "owner"},
            json={"input_text": "2027届北京后端校招", "expected_version": 1},
        )
        assert changed.status_code == 200 and changed.json()["version"] == 2
        library = client.get(
            f"/api/discovery/goals/{goal['id']}/library", headers={"X-User-ID": "owner"}
        ).json()
    assert library["counts"]["matched"] == 1
    assert library["latest_run_id"] is None and not library["updates"]
    assert not library["lead_ids"]
    assert db_session.get(DiscoveryRun, "old-goal-run") is not None


def test_search_uses_saved_snapshot_and_reuses_running_execution(
    db_session, monkeypatch
):
    calls = []

    class Provider:
        source_url = "https://example.com/search"

        def build_search_plan(self):
            return DiscoverySearchPlan.model_validate(
                {
                    "allowed_source_ids": ["test"],
                    "routes": [
                        {
                            "source_id": "test",
                            "source_url": self.source_url,
                            "tool_sequence": ["web_search"],
                        }
                    ],
                    "budget": {"max_results": 20, "max_analysis": 0},
                    "stop_conditions": ["max_results_reached"],
                }
            )

    monkeypatch.setattr(
        discovery_api, "create_web_search_provider", lambda *a: Provider()
    )
    monkeypatch.setattr(
        discovery_api, "execute_web_search_in_worker", lambda **kw: calls.append(kw)
    )
    with TestClient(app) as client:
        goal = create_goal(client)
        path = f"/api/discovery/goals/{goal['id']}"
        headers = {"X-User-ID": "owner"}
        first = client.post(
            path + "/search", headers=headers, json={"expected_version": 1}
        )
        assert first.status_code == 202, first.text
        run = first.json()
        assert run["search_goal_id"] == goal["id"]
        assert run["goal_conditions"] == goal["conditions"]
        second = client.post(
            path + "/search", headers=headers, json={"expected_version": 1}
        )
        assert second.json()["id"] == run["id"] and len(calls) == 1
        assert calls[0]["query"] == goal["query"]
        client.patch(
            path,
            headers=headers,
            json={"input_text": "北京后端校招", "expected_version": 1},
        )
        db_session.expire_all()
        saved = db_session.get(DiscoveryRun, run["id"])
        assert (
            saved.goal_conditions == goal["conditions"]
            and saved.search_goal_version == 1
        )
        assert (
            client.post(
                path + "/search", headers=headers, json={"expected_version": 1}
            ).status_code
            == 409
        )


def test_manual_fields_accept_custom_role_and_location_without_model(db_session):
    with TestClient(app) as client:
        goal = create_goal(
            client,
            "找固件开发岗位",
            conditions=SearchGoalConditions(
                locations=["湛江"], roles=["固件开发"], job_types=["校招"]
            ).model_dump(),
        )
        assert goal["conditions"]["locations"] == ["湛江"]
        assert goal["condition_sources"]["roles"] == "用户修改"


def test_refresh_queue_is_bounded_and_skips_fresh_excluded_and_foreign_jobs(db_session):
    for index in range(10):
        add_posting(db_session, identifier=f"stale-{index}", age=8)
    add_posting(db_session, identifier="fresh")
    add_posting(db_session, identifier="excluded", city="北京", age=8)
    add_posting(db_session, user="foreign", identifier="foreign", age=8)
    conditions = SearchGoalConditions(
        locations=["上海"], roles=["后端"], job_types=["校招"]
    )
    queue = SearchGoalService(db_session).refresh_candidates(
        "owner", query=conditions_query(conditions), conditions=conditions.model_dump()
    )
    assert len(queue) == 3  # A single company cannot occupy the whole refresh batch.
    assert all("/stale-" in candidate.source_url for candidate in queue)


def test_refresh_filters_company_before_limit_and_rotates_oldest_observations(db_session):
    for index in range(9):
        add_posting(db_session, identifier=f"other-{index}", age=9)
    for index in range(4):
        job = add_posting(db_session, identifier=f"target-{index}", age=8)
        job.company = "目标公司"
        db_session.commit()
    service = SearchGoalService(db_session)
    conditions = SearchGoalConditions(locations=["上海"], roles=["后端"], job_types=["校招"])
    args = {"query": conditions_query(conditions), "conditions": conditions.model_dump(),
            "company_id": "目标公司", "source_group": lambda url, company: company}
    first = service.refresh_candidates("owner", **args)
    assert len(first) == 3 and all("target-" in c.source_url for c in first)
    for candidate in first:
        job = db_session.scalar(select(JobPosting).where(JobPosting.source_url == candidate.source_url))
        job.last_verified_at = datetime.now(UTC)
        job.availability_status = "UNKNOWN"
    db_session.commit()
    second = service.refresh_candidates("owner", **args)
    assert second[0].source_url.endswith("target-3")


def test_explicit_cohort_overrides_profile_and_no_limit_does_not_get_prefilled(
    db_session,
):
    db_session.add(
        UserProfile(
            user_id="owner",
            educations=[
                {
                    "id": "master",
                    "level": "master",
                    "major_raw": "机械",
                    "source_text": "预计2027年硕士毕业",
                    "graduation_year": 2027,
                    "graduation_year_kind": "expected",
                    "graduation_year_confirmed": True,
                }
            ],
        )
    )
    db_session.commit()
    with TestClient(app) as client:
        assert create_goal(client, "2028届上海后端校招")["conditions"][
            "graduation_years"
        ] == [2028]
        assert (
            create_goal(client, "不限届别，上海后端校招")["conditions"][
                "graduation_years"
            ]
            == []
        )
        assert create_goal(client, "上海后端校招")["conditions"][
            "graduation_years"
        ] == [2027]
        excluded = create_goal(client, "上海后端校招，不接受2027届")
        assert not excluded["conditions"]["graduation_years"]
        assert excluded["conditions"]["pending_conditions"]
