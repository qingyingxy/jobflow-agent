"""Regressions for misleading eligibility, company state and heavy list payloads."""
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src.infrastructure.llm_client import FakeModelClient
from src.main import app
from src.services.body_review_queue import run_body_review_batch
from src.services.campaign_discovery import discovery_summary, enqueue_discovery
from src.services.campaign_job_presence import check_result
from src.services.campaign_service import company_card
from src.services.job_fact_understanding import cached_locations
from src.services.personal_requirements import personal_requirement_hints
from src.services.qualification_understanding import attach_qualifications
from src.services.result_status import enrich_result
from src.services.search_goal_service import SearchGoalService, posting_stub
from tests.test_body_review_queue import OUTPUT, SETTINGS, setup_queue
from tests.test_campaign_agent import SOURCE, action, page, reader
from tests.test_campaign_company_agent import Harness, step
from tests.test_campaign_company_agent import action as discovery_action
from tests.test_generic_personal_flow import clause
from tests.test_search_goals import add_posting


def test_source_conflict_cannot_become_personal_pass_or_failure(db_session):
    goal, _ = setup_queue(db_session)
    job = SearchGoalService(db_session).postings("owner")[0]
    strict, broad = "招聘项目：2027届博士生招聘", "任职要求：硕士或博士学位"
    job.raw_content += f"\n{strict}\n{broad}"
    job.recruitment_context = attach_qualifications(posting_stub(job), [
        {**clause(broad, "uncertain", ["master", "doctor"], scope="项目与正文学历不一致"),
         "conflicting_evidence": [strict]},
        clause(broad, degrees=["master", "doctor"]),
    ]).recruitment_context
    profile = SimpleNamespace(degree="硕士", educations=[])
    hints = personal_requirement_hints(job, profile)
    assert [h["status"] for h in hints] == ["source_conflict", "review"]
    assert hints[0]["conflicting_evidence"] == [strict]
    match = enrich_result({"review_status": "recommended", "filter_status": "matched", "checks": []},
                          job, profile, conditions=goal.conditions)
    assert match["review_status"] == "pending"
    assert not match["personal_gate_conflict"]
    assert match["result_status"]["personal"]["state"] == "source_conflict"


@pytest.mark.asyncio
async def test_location_checkpoint_survives_and_apis_agree_without_interview_city(db_session):
    _goal, factory = setup_queue(db_session)
    job = SearchGoalService(db_session).postings("owner")[0]
    job.locations = []
    job.raw_content += "\n工作城市：深圳市\n面试城市：上海市"
    db_session.commit()
    client = FakeModelClient(output={**OUTPUT, "work_locations": [
        {"value": "深圳市", "evidence": "工作城市：深圳市"}]})
    await run_body_review_batch(factory, settings=SETTINGS, client=client)
    db_session.expire_all()
    job = SearchGoalService(db_session).postings("owner")[0]
    assert job.locations == []  # No mutation of the source-review fingerprint.
    assert cached_locations(job) == ["深圳市"]
    assert cached_locations(replace(posting_stub(job), raw_content=job.raw_content + "更新")) is None
    with TestClient(app) as api:
        headers = {"X-User-ID": "owner"}
        assert api.get("/api/candidates", headers=headers).json()[0]["job"]["locations"] == ["深圳市"]
        assert api.get(f"/api/jobs/{job.id}", headers=headers).json()["locations"] == ["深圳市"]
    assert "面试城市" in client.requests[0].messages[0].content


@pytest.mark.asyncio
async def test_internship_report_replaces_old_formal_company_state(db_session):
    text = "2027/2028届优先，增长研发实习生"
    agent, _ = reader([action("read", SOURCE.career_url), action("report", SOURCE.career_url,
        status="internship_only", jobs=["增长研发实习生"], text=text)],
        {SOURCE.career_url: page(SOURCE.career_url, text)})
    result = await agent.check(SOURCE, 2027, {})
    check = result["cache"]["job_check"]
    assert check["status"] == "internship_only"
    assert check_result(result["found"], complete=True)["status"] == "internship_only"
    from src.domain.campaign import CampaignWatch
    watch = CampaignWatch(user_id="owner", company_id=SOURCE.id, year=2027,
                          status="ready", cache={"job_check": check})
    old = {"id": "old", "facts": {"directions": [], "entry": {"job_presence": "found", "url": SOURCE.career_url,
        "kind": "listing", "checked_at": (datetime.now(UTC)-timedelta(hours=1)).isoformat()}},
        "entry_url": SOURCE.career_url, "first_seen_at": check["checked_at"], "changed_at": check["checked_at"]}
    card = company_card(SOURCE, watch, [old], 2027)
    assert card["recruitment_status"] == "internship"
    assert card["job_titles"] == ["增长研发实习生"]


@pytest.mark.asyncio
async def test_budget_pause_resume_keeps_observed_evidence(db_session):
    task = enqueue_discovery(db_session, "owner", 2027)
    harness = Harness([discovery_action("search", query="2027 新公司")])
    await step(db_session, harness)
    db_session.refresh(task)
    state = deepcopy(task.state)
    state["planner"]["steps"] = 32
    task.state = state
    db_session.commit()
    await step(db_session, harness)
    db_session.refresh(task)
    assert (task.status, task.stage, task.error) == ("paused", "budget_limit", None)
    original_run = task.run_id
    summary = discovery_summary(db_session, "owner", 2027)
    assert summary["status"] == "paused" and summary["error"] is None
    # Old records get the same presentation without rewriting their evidence.
    task.status, task.stage = "blocked", "done"
    db_session.commit()
    assert discovery_summary(db_session, "owner", 2027)["stage"] == "budget_limit"
    resumed = enqueue_discovery(db_session, "owner", 2027)
    assert resumed.run_id == original_run and resumed.state["queries"] == state["queries"]
    assert resumed.state["planner"]["steps"] == 0


def test_compact_list_and_full_detail_keep_decisions_and_enforce_ownership(db_session):
    goal, _ = setup_queue(db_session)
    service = SearchGoalService(db_session)
    full = service.library("owner", goal.id, include_progress=False)
    compact = service.library("owner", goal.id, include_progress=False, compact=True)
    assert full["counts"] == compact["counts"]
    assert [m["job_posting_id"] for m in full["result_matches"]] == [m["job_posting_id"] for m in compact["result_matches"]]
    for match, short in zip(full["result_matches"], compact["result_matches"]):
        assert short["details_compact"] and short["result_status"] == match["result_status"]
        assert all(not c["evidence"] for c in short["checks"])
    job_id = full["result_matches"][0]["job_posting_id"]
    add_posting(db_session, user="foreign", identifier="foreign")
    with TestClient(app) as api:
        path = f"/api/discovery/goals/{goal.id}/jobs/"
        headers = {"X-User-ID": "owner"}
        response = api.get(path + job_id + f"?expected_version={goal.version}", headers=headers)
        assert response.status_code == 200 and response.json() == full["result_matches"][0]
        assert api.get(path + job_id + "?expected_version=999", headers=headers).status_code == 409
        assert api.get(path + "foreign?expected_version=1", headers=headers).status_code == 404
        assert api.get(path + job_id + "?expected_version=1", headers={"X-User-ID": "foreign"}).status_code == 404
