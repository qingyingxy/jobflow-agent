from dataclasses import replace
from types import SimpleNamespace

import pytest

from src.services.discovery_matching import classify_discovery_job
from src.services.discovery_sources import JobStub
from src.services.search_planner import build_agent_search_tasks, build_search_tasks

BASE = JobStub(
    source_id="fixture",
    source_job_id="1",
    company="示例公司",
    title="后端开发工程师",
    locations=["上海"],
    job_type="campus",
    published_at=None,
    detail_url="https://example.com/jobs/1",
    raw_content="负责后端服务开发，参与前端团队协作。",
)


@pytest.mark.parametrize(
    "query,changes,reason",
    [
        (
            "只考虑上海，不考虑北京，后端校招",
            {"locations": ["北京"]},
            "excluded_location",
        ),
        ("北京不要，上海后端校招", {"locations": ["北京"]}, "excluded_location"),
        ("不接受北京、杭州，后端校招", {"locations": ["杭州"]}, "excluded_location"),
        ("上海校招，不要实习", {"job_type": "internship"}, "excluded_job_type"),
        ("不考虑社招，上海实习", {"job_type": "full_time"}, "excluded_job_type"),
        ("上海校招，不考虑前端", {"title": "前端开发工程师"}, "excluded_role"),
        ("上海校招，不考虑 AI", {"title": "AI 应用工程师"}, "excluded_role"),
        (
            "backend campus except Beijing",
            {"locations": ["beijing"]},
            "excluded_location",
        ),
    ],
)
def test_explicit_exclusion_cannot_be_strict(query, changes, reason):
    result = classify_discovery_job(replace(BASE, **changes), query=query)
    assert result.match_tier == "expanded"
    assert reason in result.mismatch_reasons


@pytest.mark.parametrize(
    "query,locations",
    [
        ("只考虑上海，不考虑北京，后端校招", ["上海"]),
        ("只考虑上海，不考虑北京，后端校招", ["北京", "上海"]),
        ("上海后端校招，不考虑前端", ["上海"]),
        ("上海校招，不考虑 AI", ["上海"]),
        ("不排除上海，后端校招", ["上海"]),
        ("上海优先，杭州也接受，后端校招", ["杭州"]),
    ],
)
def test_allowed_alternative_and_team_mentions_stay_available(query, locations):
    assert (
        classify_discovery_job(
            replace(BASE, locations=locations), query=query
        ).match_tier
        == "strict"
    )


@pytest.mark.parametrize("builder", [build_search_tasks, build_agent_search_tasks])
def test_every_followup_preserves_exclusions_and_does_not_expand_denied_role(builder):
    query = "2027届上海后端校招，不考虑北京、不接受实习、不要前端"
    tasks = builder(
        query, [SimpleNamespace(company="示例", career_url="https://example.com/jobs")]
    )
    assert all(query in task.query for task in tasks)
    assert not any("frontend" in task.query for task in tasks)
    assert len({t.query for t in tasks}) == len(tasks)
