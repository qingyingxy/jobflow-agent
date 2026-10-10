"""Public failures plus mixed-duty controls: titles alone cannot settle scope."""

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

JOBS = [
    JobStub(**row)
    for row in json.loads(
        (
            Path(__file__).parent / "fixtures/role_boundary_failures_20261010.json"
        ).read_text(encoding="utf-8")
    )
]
AGENT_QUERY = (
    "2027届，上海的 AI Agent、RAG、大模型应用开发校招岗位，不考虑北京，不考虑社招"
)
BACKEND_QUERY = "2027届，上海的后端开发校招岗位，不考虑北京，不考虑社招"


def proposal(job, query, status, quote):
    return valid_review(
        {
            "fingerprint": fingerprint(job, query),
            "decision": {
                "status": status,
                "reason": "根据引用职责判断方向",
                "evidence": [quote],
            },
        },
        job,
        query,
    )


def test_product_framework_planning_cannot_pass_even_with_a_real_literal_quote():
    job = JOBS[0]
    quote = next(q for q in duty_passages(job) if "设计并优化RAG" in q)
    review = proposal(job, AGENT_QUERY, "matched", quote)
    assert review["decision"]["status"] == "pending"
    assert (
        classify_discovery_job(job, query=AGENT_QUERY, role_review=review).filter_status
        == "pending"
    )
    assert (
        proposal(job, AGENT_QUERY, "excluded", quote)["decision"]["status"]
        == "excluded"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("job", JOBS[1:], ids=lambda j: j.source_job_id)
async def test_complete_chip_duties_are_excluded_without_using_review_budget(
    db_session, job
):
    client = FakeModelClient()
    reviewer = JobRoleReviewer(Settings(_env_file=None), client=client)
    match = classify_discovery_job(job, query=BACKEND_QUERY)
    assert match.filter_status == "excluded"
    role = next(c for c in match.checks if c["field"] == "role")
    assert role["method"] == "local_domain"
    assert all(q in job.raw_content for q in role["evidence"])
    assert (
        await reviewer.review(
            job,
            query=BACKEND_QUERY,
            session=db_session,
            user_id="u",
            lead_id=job.source_job_id,
        )
        is None
    )
    assert not client.requests


@pytest.mark.parametrize("title", ["AI产品经理", "用户体验设计师", "product manager"])
def test_cross_function_title_with_actual_coding_can_pass(title):
    duty = "负责Agent系统的设计与研发，实现工具调用接口和任务执行引擎，编写功能测试并验证业务交付的可靠性。"
    job = replace(
        JOBS[0],
        title=title,
        raw_content="2027届校园招聘\n岗位职责：\n"
        + duty
        + "\n任职要求：\n熟悉Python。",
    )
    quote = duty.rstrip("。")
    assert (
        proposal(job, AGENT_QUERY, "matched", quote)["decision"]["status"] == "matched"
    )
    assert (
        proposal(job, AGENT_QUERY, "excluded", quote)["decision"]["status"] == "pending"
    )


def test_chip_title_with_explicit_software_service_work_is_not_excluded():
    job = JOBS[1]
    duty = "负责芯片设计平台后端服务的开发，实现任务管理API、数据存储和权限模块。"
    raw = job.raw_content.replace("任职要求：", duty + "\n任职要求：")
    assert (
        classify_discovery_job(
            replace(job, raw_content=raw), query=BACKEND_QUERY
        ).filter_status
        == "matched"
    )


def test_chip_agent_implementation_remains_in_scope_for_agent_query():
    job = JOBS[1]
    assert classify_discovery_job(job, query=AGENT_QUERY).filter_status == "matched"


@pytest.mark.parametrize(
    "duty",
    [
        "协同前后端团队推进接口方案设计，协调人员排期并管理产品发布计划。",
        "与后端团队紧密协作，参与业务方案讨论，整理需求和运营流程文档。",
        "配合后端的设计和实现，协调客户的验收工作，跟进合同交付和项目进度。",
    ],
)
def test_cooperating_with_software_team_does_not_prove_own_backend_work(duty):
    job = replace(
        JOBS[0],
        title="项目协调工程师",
        raw_content="岗位职责：\n" + duty + "\n任职要求：\n熟悉Python。",
    )
    assert classify_discovery_job(job, query=BACKEND_QUERY).filter_status == "pending"
    assert (
        proposal(job, BACKEND_QUERY, "matched", duty.rstrip("。"))["decision"]["status"]
        == "pending"
    )


def test_partial_chip_content_is_unknown_instead_of_excluded():
    job = replace(JOBS[1], raw_content="岗位职责：芯片后端设计")
    assert classify_discovery_job(job, query=BACKEND_QUERY).filter_status == "pending"


@pytest.mark.parametrize(
    "duty",
    [
        "参与后端和AI Agent方向的系统设计、开发和迭代，支持AI策略与模型的高效部署与服务化。",
        "参与后端服务的稳定性体系建设，包括性能调优、监控告警、容灾等，保障生产环境的高可用性。",
    ],
)
def test_participating_in_backend_development_is_not_a_team_handoff(duty):
    job = replace(
        JOBS[0],
        title="软件开发工程师",
        raw_content="2027届校园招聘\n岗位职责：\n"
        + duty
        + "\n任职要求：\n熟悉Python。",
    )
    assert classify_discovery_job(job, query=BACKEND_QUERY).filter_status == "matched"
    assert (
        proposal(job, BACKEND_QUERY, "matched", duty.rstrip("。"))["decision"]["status"]
        == "matched"
    )


def test_product_query_can_accept_product_planning_without_coding():
    job = JOBS[0]
    quote = next(q for q in duty_passages(job) if "设计并优化RAG" in q)
    assert (
        proposal(job, "上海AI产品校招", "matched", quote)["decision"]["status"]
        == "matched"
    )


@pytest.mark.parametrize(
    "duty",
    [
        "参与CNI插件研发与优化，开发容器网络故障定位与性能分析工具，探索eBPF内核态网络加速方案。",
        "负责Linux内核研发与网络协议栈优化，完善内核网络追踪与诊断工具，提升系统运行效率。",
    ],
)
def test_network_or_kernel_citation_alone_cannot_confirm_backend_service_work(duty):
    job = replace(
        JOBS[0],
        title="容器网络研发工程师",
        raw_content="2027届校园招聘\n岗位职责：\n" + duty + "\n任职要求：\n熟悉Go。",
    )
    quote = duty.rstrip("。")
    assert (
        proposal(job, BACKEND_QUERY, "matched", quote)["decision"]["status"]
        == "pending"
    )
    mixed = replace(
        job,
        raw_content=job.raw_content.replace(
            "任职要求：", "开发平台后端服务，实现任务管理API与权限接口。\n任职要求："
        ),
    )
    explicit = "开发平台后端服务，实现任务管理API与权限接口"
    assert (
        proposal(mixed, BACKEND_QUERY, "matched", explicit)["decision"]["status"]
        == "matched"
    )
