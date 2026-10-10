"""Source-backed regressions for public jobs found in the user acceptance run."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from src.config import Settings
from src.infrastructure.llm_client import FakeModelClient
from src.services.discovery_matching import classify_discovery_job
from src.services.discovery_sources import JobStub
from src.services.job_role_review import (
    JobRoleReviewer,
    duty_passages,
    fingerprint,
    valid_review,
)

FIXTURES = Path(__file__).parent / "fixtures"
POOL = json.loads(
    (FIXTURES / "role_filter_e2e_20261010.json").read_text(encoding="utf-8")
)
QUERY = POOL["query"]
JOBS = {row["job"]["source_job_id"]: JobStub(**row["job"]) for row in POOL["jobs"]}
RELEVANT = [
    row["job"]["source_job_id"] for row in POOL["jobs"] if row["label"] == "relevant"
]


@pytest.mark.asyncio
@pytest.mark.parametrize("job_id", RELEVANT)
async def test_explicit_target_development_is_confirmed_without_spending_a_call(
    db_session, job_id
):
    job = JOBS[job_id]
    client = FakeModelClient()
    reviewer = JobRoleReviewer(Settings(_env_file=None), client=client)
    assert (
        await reviewer.review(
            job, query=QUERY, session=db_session, user_id="u", lead_id=job_id
        )
        is None
    )
    assert not client.requests
    match = classify_discovery_job(job, query=QUERY)
    assert match.filter_status == "matched"
    role = next(c for c in match.checks if c["field"] == "role")
    assert role["method"] == "local_duties"
    assert all(q in job.raw_content for q in role["evidence"])


@pytest.mark.parametrize("job_id", ["7681599148466571566", "7662376183711222058"])
def test_context_or_general_model_training_does_not_veto_supported_exclusion(job_id):
    job = JOBS[job_id]
    review = valid_review(
        {
            "fingerprint": fingerprint(job, QUERY),
            "decision": {
                "status": "excluded",
                "reason": "完整职责属于其他方向",
                "evidence": duty_passages(job)[:2],
            },
        },
        job,
        QUERY,
    )
    assert review["decision"]["status"] == "excluded"
    assert (
        classify_discovery_job(job, query=QUERY, role_review=review).filter_status
        == "excluded"
    )


@pytest.mark.parametrize(
    "job_id",
    [
        "7662375475701188905",
        "7671129480778139967",
        "7681715814722816307",
        "7667100326978537781",
    ],
)
def test_real_duty_or_recruitment_conflicts_remain_pending(job_id):
    assert classify_discovery_job(JOBS[job_id], query=QUERY).filter_status == "pending"


@pytest.mark.parametrize(
    "change,field,status",
    [
        ({"locations": ["北京"]}, "location", "excluded"),
        ({"job_type": "social"}, "job_type", "excluded"),
        ({"locations": []}, "location", "pending"),
    ],
)
def test_target_duties_cannot_override_other_filter_conditions(change, field, status):
    job = replace(JOBS["7671129598676125993"], **change)
    # Remove the corresponding authoritative header when testing missing data.
    if "locations" in change:
        job = replace(
            job,
            raw_content="\n".join(
                line
                for line in job.raw_content.splitlines()
                if not line.startswith("工作地点：")
            ),
        )
    if "job_type" in change:
        job = replace(
            job,
            raw_content=job.raw_content.replace(
                "招聘类型：校园招聘", "招聘类型：社会招聘"
            ).replace("2027届校园招聘计划", "社会招聘"),
        )
    match = classify_discovery_job(job, query=QUERY)
    assert next(c for c in match.checks if c["field"] == field)["status"] == status
    assert match.filter_status == status


def test_rag_query_cannot_borrow_agent_work_from_an_unrelated_mention():
    job = replace(
        JOBS[RELEVANT[0]],
        title="应用工程师",
        raw_content=(
            "岗位职责：\n基于Agent技术构建分析助手，同时跟进RAG行业动态。\n任职要求：\n熟悉Python。"
        ),
    )
    assert classify_discovery_job(job, query="上海RAG校招").filter_status == "pending"


@pytest.mark.parametrize("job_id", ["7667576106895689989", "7674927852634605877"])
def test_product_planning_and_design_tool_use_do_not_veto_model_exclusion(job_id):
    job = JOBS[job_id]
    review = valid_review(
        {
            "fingerprint": fingerprint(job, QUERY),
            "decision": {
                "status": "excluded",
                "reason": "实际工作是产品规划或体验设计",
                "evidence": duty_passages(job)[:2],
            },
        },
        job,
        QUERY,
    )
    assert review["decision"]["status"] == "excluded"
    assert (
        classify_discovery_job(job, query=QUERY, role_review=review).filter_status
        == "excluded"
    )


def test_product_title_cannot_hide_explicit_hands_on_agent_implementation():
    duty = "负责Agent系统的设计与研发，实现工具调用接口和执行状态管理，编写功能测试并验证业务交付。"
    job = replace(
        JOBS[RELEVANT[0]],
        title="AI产品经理",
        raw_content=("岗位职责：\n" + duty + "\n任职要求：\n熟悉Python。"),
    )
    review = valid_review(
        {
            "fingerprint": fingerprint(job, QUERY),
            "decision": {
                "status": "excluded",
                "reason": "标题是产品经理",
                "evidence": [duty],
            },
        },
        job,
        QUERY,
    )
    assert review["decision"]["status"] == "pending"
