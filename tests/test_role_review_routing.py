"""Regression coverage for source extraction and scarce model-call routing."""

from dataclasses import replace

import pytest

from src.config import Settings
from src.infrastructure.llm_client import FakeModelClient
from src.services.discovery_matching import classify_discovery_job
from src.services.discovery_sources import JobStub
from src.services.job_role_review import JobRoleReviewer, duty_text

QUERY = "上海Agent或RAG实习，不考虑北京和社招"
DUTY = "负责Agent系统的设计与研发，建设工具调用、工作流编排和执行结果校验机制。"
BASE = JobStub(
    source_id="test", source_job_id="1", company="示例", title="系统研发实习生",
    locations=["上海"], job_type="internship", published_at=None,
    detail_url="https://example.com/1",
    raw_content="岗位职责：\n日常实习：为符合岗位要求的同学提供项目实践机会。\n"
    + "1、" + DUTY + "\n任职要求：\n熟悉Python。",
)


@pytest.mark.parametrize("flattened", [False, True])
@pytest.mark.parametrize("label", ["岗位要求", "职位要求", "任职要求"])
def test_requirement_phrase_in_intro_does_not_truncate_real_duties(flattened, label):
    job = replace(BASE, raw_content=BASE.raw_content.replace("符合岗位要求", "符合" + label))
    if flattened:
        job = replace(job, raw_content=job.raw_content.replace("\n", " "))
    assert DUTY in duty_text(job)
    assert "Python" not in duty_text(job)
    assert "日常实习" not in duty_text(job)
    result = classify_discovery_job(job, query=QUERY)
    assert result.filter_status == "matched"
    assert next(c for c in result.checks if c["field"] == "role")["method"] == "local_duties"


@pytest.mark.asyncio
async def test_local_confirmation_saves_model_budget_for_ambiguous_job(db_session):
    duty = "负责工业设备现场调试和可靠性实验，整理实验数据及故障分析报告，跟进项目验收和客户交付。"
    unclear = replace(BASE, detail_url="https://example.com/2", title="技术实习生",
                      raw_content="岗位职责：\n" + duty + "\n任职要求：\n熟悉Python。")
    client = FakeModelClient(output={"status": "excluded", "reason": "设备调试不属于目标方向", "evidence_ids": [0]})
    events = []
    reviewer = JobRoleReviewer(Settings(_env_file=None, web_search_role_review_max_calls=1),
                               client=client, on_event=lambda kind, data: events.append(data))
    assert await reviewer.review(BASE, query=QUERY, session=db_session, user_id="u", lead_id="1") is None
    assert not client.requests
    review = await reviewer.review(unclear, query=QUERY, session=db_session, user_id="u", lead_id="2")
    assert review["decision"]["status"] == "excluded"
    assert reviewer.calls == 1
    assert events[0]["method"] == "local_duties"
    assert len(client.requests) == 1


@pytest.mark.asyncio
async def test_explicit_role_exclusion_does_not_spend_a_model_call(db_session):
    job = replace(BASE, title="前端实习生", raw_content=BASE.raw_content.replace(DUTY,
        "负责前端页面和交互组件的开发与维护，跟进性能优化、功能交付及产品迭代。"))
    client = FakeModelClient()
    reviewer = JobRoleReviewer(Settings(_env_file=None), client=client)
    assert await reviewer.review(job, query="上海后端实习，不考虑前端", session=db_session, user_id="u", lead_id="1") is None
    assert not client.requests


@pytest.mark.asyncio
@pytest.mark.parametrize("title,duty", [
    ("Agent实习生", "支持Agent应用的售前方案设计，配合销售团队开展需求访谈和方案介绍，持续跟进合同审批。"),
    ("AI资源实习生", "开发服务于Agent场景的GPU资源调度平台，优化算力利用率和基础集群稳定性。"),
    ("AI产品实习生", "负责Agent系统需求规划和产品路线图设计，协调开发团队排期，跟进产品上线。"),
    ("系统实习生", "不负责Agent系统研发，仅负责数据库备份、监控和部署，保障数据可靠性。"),
    ("系统实习生", "负责数据库研发和备份机制建设，任职要求为熟悉Agent开发工具及行业前沿技术。"),
])
async def test_weak_or_conflicting_role_evidence_still_uses_model(db_session, title, duty):
    job = replace(BASE, title=title, raw_content="岗位职责：\n" + duty
                  + "\n定期整理项目进度与交付记录，参与跨团队工作沟通。\n任职要求：\n熟悉Python。")
    client = FakeModelClient(output={"status": "pending", "reason": "需确认具体工作边界", "evidence": []})
    reviewer = JobRoleReviewer(Settings(_env_file=None), client=client)
    result = await reviewer.review(job, query=QUERY, session=db_session, user_id="u", lead_id="1")
    assert result["decision"]["status"] == "pending"
    assert len(client.requests) == 1


@pytest.mark.asyncio
async def test_local_role_confirmation_keeps_other_filters_pending(db_session):
    job = replace(BASE, locations=[])
    reviewer = JobRoleReviewer(Settings(_env_file=None), client=FakeModelClient())
    assert await reviewer.review(job, query=QUERY, session=db_session, user_id="u", lead_id="1") is None
    match = classify_discovery_job(job, query=QUERY)
    assert match.filter_status == "pending"
    assert next(c for c in match.checks if c["field"] == "location")["status"] == "pending"


def test_supported_model_conflict_is_not_overridden_by_local_confirmation():
    from src.services.job_role_review import fingerprint

    review = {"fingerprint": fingerprint(BASE, QUERY), "decision": {
        "status": "excluded", "reason": "模型判断为其他方向", "evidence": [DUTY],
    }}
    assert classify_discovery_job(BASE, query=QUERY, role_review=review).filter_status == "pending"


@pytest.mark.parametrize("duty", [
    "探索将LLM和AI Agent能力引入性能分析链路，实现trace自动解读和根因定位等智能化功能。",
    "基于企业知识图谱，协助探索RAG和Agent的落地新范式，构建信息检索和关联分析机制。",
    "研究Agent工具选择与任务规划算法，开发智能体评测闭环并优化执行策略。",
])
def test_model_citations_can_confirm_actual_research_or_application_tasks(duty):
    from src.services.job_role_review import fingerprint, valid_review

    job = replace(BASE, raw_content="岗位职责：\n" + duty + "\n任职要求：\n熟悉Python。")
    review = valid_review({"fingerprint": fingerprint(job, QUERY), "decision": {
        "status": "matched", "reason": "实际职责包含目标方向研究与应用", "evidence": [duty],
    }}, job, QUERY)
    assert review["decision"]["status"] == "matched"


def test_model_must_cite_target_task_rather_than_unrelated_duty():
    from src.services.job_role_review import fingerprint, valid_review

    other = "负责历史工单数据清理与业务报表整理，跟进团队内部需求记录和日常运营流程。"
    job = replace(BASE, raw_content="岗位职责：\n" + DUTY + "\n" + other + "\n任职要求：\n熟悉Python。")
    review = valid_review({"fingerprint": fingerprint(job, QUERY), "decision": {
        "status": "matched", "reason": "方向相关", "evidence": [other],
    }}, job, QUERY)
    assert review["decision"]["status"] == "pending"


def test_auxiliary_agent_implementation_cannot_be_blanket_excluded():
    from src.services.job_role_review import fingerprint, valid_review

    duty = "探索将LLM和AI Agent能力引入性能分析链路，实现trace自动解读和根因定位等智能化功能。"
    job = replace(BASE, raw_content="岗位职责：\n" + duty + "\n任职要求：\n熟悉Python。")
    review = valid_review({"fingerprint": fingerprint(job, QUERY), "decision": {
        "status": "excluded", "reason": "Agent只是其他工作的辅助功能", "evidence": [duty],
    }}, job, QUERY)
    assert review["decision"]["status"] == "pending"
    assert review["exclusion_guard"] == "target_task_conflict"
    assert review["decision"]["evidence"] == [duty.rstrip("。")]


def test_agent_research_conflict_guard_does_not_widen_other_query_scopes():
    from src.services.job_role_review import fingerprint, valid_review

    duty = "参与大语言模型预训练研究，围绕推理和agent等能力，构建训练数据和优化模型效果。"
    job = replace(BASE, raw_content="岗位职责：\n" + duty + "\n任职要求：\n熟悉Python。")
    query = "上海后端开发实习"
    review = valid_review({"fingerprint": fingerprint(job, query), "decision": {
        "status": "excluded", "reason": "训练研究未承担后端工作", "evidence": [duty],
    }}, job, query)
    assert review["decision"]["status"] == "excluded"


def test_narrow_application_scope_cannot_pass_on_observability_context_when_budget_ends():
    job = replace(BASE, title="可观测平台研发实习生", raw_content="岗位职责：\n"
        "参与面向大模型训练、推理和Agent场景的可观测平台建设。\n"
        "参与指标、日志、Trace等数据采集和分析链路开发，建设硬件与存储的统一观测能力。\n"
        "任职要求：\n熟悉Python。")
    query = "上海Agent、RAG、大模型应用开发实习"
    assert classify_discovery_job(job, query=query).filter_status == "pending"


def test_official_backend_title_conflicting_with_model_exclusion_stays_pending():
    from src.services.job_role_review import fingerprint, valid_review

    duty = "负责多模态大模型服务部署、推理优化、工程提效与应用落地，保障系统高可用和低成本。"
    job = replace(BASE, title="多模态大模型后端开发实习生",
                  raw_content="岗位职责：\n" + duty + "\n任职要求：\n熟悉Python。")
    query = "上海后端开发实习"
    review = valid_review({"fingerprint": fingerprint(job, query), "decision": {
        "status": "excluded", "reason": "未体现后端研发职责", "evidence": [duty],
    }}, job, query)
    assert review["decision"]["status"] == "pending"
    assert review["exclusion_guard"] == "engineering_title_conflict"


def test_generic_agent_exploration_and_efficiency_goal_cannot_prove_implementation():
    from src.services.job_role_review import fingerprint, valid_review

    duty = "探索AI Coding、Agent与工程平台结合，提升研发、排障、发布和运维自动化水平。"
    job = replace(BASE, title="云原生DevOps实习生", raw_content="岗位职责：\n" + duty
                  + "\n建设发布系统与配置管理工具链。\n任职要求：\n熟悉Python。")
    query = "上海Agent、RAG、大模型应用开发实习"
    review = valid_review({"fingerprint": fingerprint(job, query), "decision": {
        "status": "matched", "reason": "Agent与平台结合", "evidence": [duty],
    }}, job, query)
    assert review["decision"]["status"] == "pending"


def test_generic_model_capability_research_does_not_prove_agent_implementation():
    from src.services.job_role_review import fingerprint, valid_review

    duty = "参与模型能力研究，围绕代码、数学和agent等关键能力方向，推进模型能力提升。"
    job = replace(BASE, raw_content="岗位职责：\n" + duty + "\n任职要求：\n熟悉Python。")
    review = valid_review({"fingerprint": fingerprint(job, QUERY), "decision": {
        "status": "matched", "reason": "研究中提到了Agent", "evidence": [duty],
    }}, job, QUERY)
    assert review["decision"]["status"] == "pending"
