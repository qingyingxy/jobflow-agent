"""An exclusion must survive counterevidence review before hiding a job."""

from dataclasses import replace

import pytest

from src.config import Settings
from src.domain.search_goal import SearchGoalConditions
from src.infrastructure.llm_client import FakeModelClient
from src.services.discovery_matching import classify_discovery_job
from src.services.source_understanding import (
    SourceUnderstanding,
    checked_decisions,
    pending_review_fields,
)
from tests.test_ai_search_workflow import decision
from tests.test_search_goals import BASE

CONDITIONS = SearchGoalConditions(locations=["上海"], roles=["AI Agent", "AI产品"]).model_dump()
BODY = "研究工程师\n工作地点：上海\n负责模型数据生产与实验，研究Agent任务数据并构建评测系统，持续改进模型能力。"


def role(status="excluded", relation="unrelated", ids=None):
    return {**decision("role", status, [2] if ids is None else ids), "role_relation": relation,
            "diagnosis": "ambiguous" if status == "pending" else "supported"}


def runtime(outputs):
    return SourceUnderstanding(Settings(_env_file=None), client=FakeModelClient(outputs=outputs))


@pytest.mark.asyncio
@pytest.mark.parametrize("status,relation,expected", [
    ("pending", "adjacent", "pending"), ("matched", "direct", "matched"),
    ("excluded", "unrelated", "excluded"), ("excluded", None, "pending"),
])
async def test_exclusion_is_visible_until_source_bound_second_review(status, relation, expected):
    original = replace(BASE, raw_content=BODY)
    model = runtime([{"decisions": [decision("location", "matched", [1]), role()]},
                     {"decisions": [role(status, relation)]}])
    first = await model.review(original, query="上海 Agent AI产品", conditions=CONDITIONS)
    assert classify_discovery_job(first, query=None, conditions=CONDITIONS).filter_status == "pending"
    assert checked_decisions(first, CONDITIONS)["role"]["review_required"]
    assert pending_review_fields(first, query=None, conditions=CONDITIONS, primary=True) == ["role"]
    second = await model.review(first, query=None, conditions=CONDITIONS)
    assert classify_discovery_job(second, query=None, conditions=CONDITIONS).filter_status == expected
    assert not pending_review_fields(second, query=None, conditions=CONDITIONS, primary=True)
    assert second.raw_content == BODY
    assert checked_decisions(second, CONDITIONS)["location"]["status"] == "matched"
    record = second.recruitment_context["source_understanding"]
    assert record["role_exclusion_reviewed"] and record["initial_role_decision"]["status"] == "excluded"
    assert len(model.client.requests) == 2
    assert await model.review(second, query=None, conditions=CONDITIONS) is second
    assert not checked_decisions(replace(second, raw_content=BODY + "\n职责已更改"), CONDITIONS)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["excluded", "matched"])
async def test_adjacent_relation_cannot_be_hidden_or_promoted_as_direct(status):
    model = runtime([{"decisions": [decision("location", "matched", [1]), role(status, "adjacent")]}])
    result = await model.review(replace(BASE, raw_content=BODY), query=None, conditions=CONDITIONS)
    assert checked_decisions(result, CONDITIONS)["role"]["status"] == "pending"
    assert not pending_review_fields(result, query=None, conditions=CONDITIONS, primary=True)


@pytest.mark.asyncio
async def test_clear_city_conflict_survives_pending_direction_review():
    model = runtime([{"decisions": [decision("location", "excluded", [1]), role()]}])
    result = await model.review(replace(BASE, raw_content=BODY.replace("上海", "成都")), query=None, conditions=CONDITIONS)
    assert classify_discovery_job(result, query=None, conditions=CONDITIONS).filter_status == "excluded"


@pytest.mark.asyncio
@pytest.mark.parametrize("explicit", [False, True])
async def test_user_exclusion_requires_an_actual_excluded_role(explicit):
    conditions = {**CONDITIONS, "excluded_roles": ["市场营销"] if explicit else []}
    model = runtime([{"decisions": [decision("location", "matched", [1]), role()]},
                     {"decisions": [role(relation="explicit_exclusion")]}])
    first = await model.review(replace(BASE, raw_content=BODY), query=None, conditions=conditions)
    result = await model.review(first, query=None, conditions=conditions)
    assert checked_decisions(result, conditions)["role"]["status"] == ("excluded" if explicit else "pending")


@pytest.mark.asyncio
async def test_invalid_recheck_cannot_overwrite_saved_fields_or_hide_job():
    model = runtime([{"decisions": [decision("location", "matched", [1]), role()]},
                     {"decisions": [role(ids=[999])]}])
    first = await model.review(replace(BASE, raw_content=BODY), query=None, conditions=CONDITIONS)
    result = await model.review(first, query=None, conditions=CONDITIONS)
    assert result.recruitment_context["source_review_attempt"]["failures"] == 1
    assert checked_decisions(result, CONDITIONS)["location"]["status"] == "matched"
    assert checked_decisions(result, CONDITIONS)["role"]["review_required"]
    assert classify_discovery_job(result, query=None, conditions=CONDITIONS).filter_status == "pending"


@pytest.mark.asyncio
async def test_page_understanding_exclusion_enters_same_automatic_review(db_session):
    from src.domain.discovery import LeadProvider
    from src.services.job_lead_service import JobLeadService
    from src.services.search_goal_service import posting_stub
    from src.services.url_reader import FetchedResponse
    from tests.test_ai_search_workflow import QUERY, RAW, URL, page_output

    page = page_output()
    first_role = next(d for d in page["decisions"] if d["field"] == "role")
    first_role.update(status="excluded", role_relation="unrelated")
    client = FakeModelClient(output=page)
    model = SourceUnderstanding(Settings(_env_file=None), client=client, query=QUERY)
    service = JobLeadService(db_session, understanding=model)
    lead = service.create_lead(user_id="owner", provider=LeadProvider.EXTERNAL_AGENT, source_url=URL)

    class Reader:
        async def fetch(self, url):
            return FetchedResponse(requested_url=url, final_url=url, status_code=200,
                                   content_type="text/html", body=RAW.encode())

    verified = await service.verify_url(user_id="owner", lead_id=lead.id, reader=Reader(),
                                       official_hosts={"example.com"}, official_only=True)
    stub = posting_stub(verified.posting)
    checked = checked_decisions(stub, model.conditions)
    assert checked["role"]["status"] == "pending" and checked["role"]["review_required"]
    assert pending_review_fields(stub, query=QUERY, conditions=model.conditions, primary=True) == ["role"]
