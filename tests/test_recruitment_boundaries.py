import json
from dataclasses import replace
from pathlib import Path

import pytest

from src.services.discovery_matching import classify_discovery_job
from src.services.discovery_sources import JobStub
from src.services.job_role_review import fingerprint, valid_review

QUERY = "2027届，上海的 AI Agent、RAG、大模型应用开发校招岗位，不考虑北京，不考虑社招"
BASE = JobStub(source_id="test", source_job_id="1", company="测试", title="Agent开发工程师",
               locations=["上海"], job_type="campus", published_at=None,
               detail_url="https://example.com/campus/position/1/detail",
               raw_content="2027届校园招聘\n岗位职责\n负责Agent系统的设计与研发。\n任职要求\n熟悉Python。")


def check(job, field, query=QUERY, **kwargs):
    return next(c for c in classify_discovery_job(job, query=query, **kwargs).checks if c["field"] == field)


@pytest.mark.parametrize("sentence,status", [
    ("2027届毕业，获得博士学位，人工智能、计算机相关专业优先", "matched"),
    ("2027届获得本科及以上学历，计算机科学或相关专业背景优先", "matched"),
    ("2026届毕业，获得硕士学位，专业不限", "excluded"),
    ("2027届毕业，获得博士学位，仅限海外毕业生", "pending"),
    ("2027届毕业，获得博士学位，毕业日期为2026年9月至2027年8月", "pending"),
    ("2027届毕业，获得博士学位，或满足其他条件", "pending"),
    ("2027年及以后毕业", "pending"),
])
def test_cohort_degree_forms_do_not_discard_extra_qualifications(sentence, status):
    job = replace(BASE, raw_content="岗位职责\n负责Agent系统研发。\n任职要求\n"+sentence)
    result = check(job, "graduation_year")
    assert result["status"] == status
    assert result["evidence"] == [sentence]


def test_title_year_is_not_an_eligibility_clause_and_cannot_hide_a_real_conflict():
    title = "Agent开发工程师-2027届"
    for prefix in ["", "岗位名称：", "职位名称："]:
        job = replace(BASE, title=title, raw_content=prefix+title+"\n"+BASE.raw_content)
        assert check(job, "graduation_year")["status"] == "matched"
    job = replace(job, raw_content=job.raw_content+"\n招聘对象：2026届毕业生")
    assert check(job, "graduation_year")["status"] == "pending"
    assert check(replace(job, raw_content="岗位名称："+title), "graduation_year")["status"] == "pending"


@pytest.mark.parametrize("sentence", [
    "实习内容涉及Agent系统开发和RAG应用落地。",
    "实习周期6个月以上，每周出勤不低于4天。",
    "能连续实习3个月以上。",
])
def test_campus_tag_and_explicit_internship_duties_are_pending(sentence):
    job = replace(BASE, raw_content=BASE.raw_content.replace("负责Agent系统的设计与研发。", sentence))
    result = check(job, "job_type")
    assert result["status"] == "pending"
    assert sentence.rstrip("。") in result["evidence"]
    assert classify_discovery_job(job, query=QUERY).filter_status == "pending"


@pytest.mark.parametrize("sentence", [
    "有Agent开发实习经验者优先。",
    "参与过实习项目或有开源项目贡献。",
    "评估实习生完成的代码并建设Agent应用。",
])
def test_past_experience_and_mentoring_do_not_change_current_job_type(sentence):
    assert check(replace(BASE, raw_content=BASE.raw_content+"\n"+sentence), "job_type")["status"] == "matched"


def test_internship_tag_and_formal_header_conflict_but_conversion_is_not_formal():
    job = replace(BASE, job_type="internship", raw_content="Agent开发工程师\n上海\n正式\n"+BASE.raw_content)
    assert check(job, "job_type", query="上海Agent实习")["status"] == "pending"
    job = replace(job, raw_content=BASE.raw_content+"\n实习表现优异可转正为全职工程师。")
    assert check(job, "job_type", query="上海Agent实习")["status"] == "matched"


@pytest.mark.parametrize("duties,query", [
    ("设计并实现Agent系统、攻击环境和安全评测Benchmark，推动研究成果应用于真实Agent产品。", QUERY),
    ("负责前端组件研发和交互界面开发，为业务提供前端工程能力，持续验证用户体验、性能和可维护性。", "上海前端校招"),
    ("参与后端服务设计与研发，建设高可用数据接口和业务系统，定期验证接口性能和生产环境稳定性。", "上海后端校招"),
])
def test_explicit_target_development_cannot_be_blanket_excluded(duties, query):
    job = replace(BASE, raw_content="岗位职责\n"+duties+"\n任职要求\n熟悉Python。")
    review = valid_review({"fingerprint":fingerprint(job,query), "decision":{
        "status":"excluded", "reason":"主要为其他方向", "evidence":[duties]}}, job, query)
    assert review["decision"]["status"] == "pending"
    assert review["exclusion_guard"] == "target_development_conflict"
    assert check(job,"role",query,role_review=review)["status"] == "pending"


@pytest.mark.parametrize("duties", [
    "负责训练框架的GPU算子研发与性能优化，Agent只是团队愿景，为持续训练任务提供高可靠计算服务。",
    "不负责Agent系统研发，仅负责数据库备份、监控和部署，持续提升数据库可用性及灾难恢复能力。",
])
def test_guard_does_not_promote_team_keyword_or_negated_duties(duties):
    job = replace(BASE, raw_content="岗位职责\n"+duties+"\n任职要求\n熟悉Python。")
    review = valid_review({"fingerprint":fingerprint(job,QUERY),"decision":{
        "status":"excluded","reason":"基础设施运维而非应用","evidence":[duties]}},job,QUERY)
    assert review["decision"]["status"] == "excluded"


def test_original_live_boundary_regressions_keep_literal_source_evidence():
    originals = json.loads((Path(__file__).parent/"fixtures/recruitment_boundaries.json").read_text(encoding="utf-8"))
    for original in originals:
        job = replace(BASE, **{k:v for k,v in original.items() if k!="source_url"}, detail_url=original["source_url"])
        if original["source_job_id"] == "7628612570617825589":
            assert check(job,"graduation_year")["status"] == "matched"
        elif original["source_job_id"] == "7667100326978537781":
            assert check(job,"job_type")["status"] == "pending"
        else:
            quote="设计并实现Agent系统、攻击环境、数据集和安全评测Benchmark"
            assert quote in job.raw_content
            result=valid_review({"fingerprint":fingerprint(job,QUERY),"decision":{
                "status":"excluded","reason":"安全研究而非Agent开发","evidence":[quote]}},job,QUERY)
            assert result["decision"]["status"] == "pending"
            assert all(q in job.raw_content for q in result["decision"]["evidence"])


def test_technical_keywords_in_a_product_role_need_review_when_model_unavailable():
    job = replace(BASE, title="AI产品经理（大模型方向）", raw_content=BASE.raw_content.replace(
        "负责Agent系统的设计与研发。", "规划RAG、Tools及智能体Agent开发框架，推进产品需求和跨部门协同落地。"))
    assert check(job,"role")["status"] == "pending"
    assert check(job,"role",query="上海产品经理校招")["status"] == "matched"


@pytest.mark.parametrize("title,duty,status", [
    ("AI全栈开发工程师（前后端）", "独立负责业务前后端全栈开发、技术方案设计和开发实现。", "excluded"),
    ("全栈工程师", "承担前端功能开发和后端系统建设，保障产品稳定性。", "excluded"),
    ("前端/后端开发工程师（任选其一）", "参与后端平台研发，按方向选择前端或后端工作。", "pending"),
    ("全栈工程师", "负责后端服务研发，与前端工程师协同完成接口联调。", "pending"),
    ("后端工程师", "负责后端服务开发，协同前端工程师交付业务功能。", "matched"),
])
def test_frontend_exclusion_distinguishes_mandatory_mixed_duties(title, duty, status):
    job = replace(BASE, title=title, raw_content="岗位职责\n"+duty+"\n任职要求\n熟悉Python。")
    result = check(job, "role", query="上海后端校招，不考虑前端")
    assert result['status'] == status
    assert all(q in job.raw_content or q == job.title for q in result['evidence'])


@pytest.mark.parametrize('flattened', [False, True])
def test_bulleted_team_context_cannot_prove_a_specific_agent_development_role(flattened):
    from src.services.job_role_review import duty_text
    intro="我们致力于建设面向AI训练、推理和Agent等场景的资源调度平台。"
    duty="- 参与Kubernetes调度、资源编排和集群稳定性建设，分析资源利用率和成本。"
    job=replace(BASE,title="资源调度研发实习生",raw_content="岗位职责\n"+intro+"\n"+duty+"\n任职要求\n熟悉Python。")
    if flattened:
        job=replace(job,raw_content=job.raw_content.replace('\n',' '))
    query="上海Agent或RAG实习"
    assert intro not in duty_text(job)
    assert check(job,'role',query)['status']=='pending'
    review=valid_review({'fingerprint':fingerprint(job,query),'decision':{'status':'matched','reason':'Agent资源平台','evidence':[duty]}},job,query)
    assert review['decision']['status']=='pending'
    assert review['match_guard']=='target_duty_evidence_missing'
