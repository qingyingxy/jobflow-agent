from dataclasses import replace

import pytest

from src.services.discovery_sources import JobStub
from src.services.job_role_review import fingerprint, local_duty_evidence, valid_review


@pytest.mark.parametrize("duty,expected", [
    ("负责Agent通用编排能力沉淀，基于LangChain等框架，设计并实现Agent编排方案，沉淀可复用的通用Agent工具与能力组件。", "matched"),
    ("负责设计并实现智能体协作组件，完成工具调用和业务系统的集成测试。", "matched"),
    ("负责研发Agent工作流，完成规划、记忆与工具调用模块的实现。", "matched"),
    ("负责基于Agent框架设计项目交付方案，协调客户验收和跟进项目进度。", "pending"),
    ("熟悉Agent编排方案的实现经验优先，负责客户沟通与方案宣讲。", "pending"),
    ("不负责Agent编排方案实现，仅参与数据标注和项目协调。", "pending"),
    ("负责Agent训练数据的生产和运营，通过代码与Prompt完成数据分析及Agent搭建任务，构建训练集和评测集。", "pending"),
    ("编写Agent开发文档与使用指南，沉淀可复用的技术方案。", "pending"),
])
def test_mixed_titles_need_actual_target_implementation(duty, expected):
    job = JobStub("unseen", "1", "任意公司", "Agent设计交付", ["上海"], "campus", None,
                  "https://unknown.example/jobs/1", "官网职能分类：产品运营\n岗位职责\n" + duty + "\n任职要求\n计算机相关专业。")
    query = "岗位方向：ai agent、rag；招聘类型：校招"
    review = {"fingerprint": fingerprint(job, query), "decision": {
        "status": "matched", "reason": "职责包含目标实现", "evidence": [duty]}}
    result = valid_review(review, job, query)
    assert result["decision"]["status"] == expected
    # Company identity cannot alter the same duty's interpretation.
    assert valid_review(review, replace(job, company="另一家公司"), query)["decision"]["status"] == expected


@pytest.mark.parametrize('duty', [
    '编写Agent开发文档与使用指南，沉淀可复用的技术方案。',
    '负责设计Agent系统的开发文档和操作指南。',
    '负责设计RAG系统使用指南和技术文档。',
    '负责优化Agent系统开发文档。',
])
def test_documentation_is_not_implementation_even_with_engineer_title(duty):
    query = 'ai agent / rag 校招'
    job = JobStub('unseen', '1', '任意公司', 'Agent开发工程师', ['上海'], 'campus', None,
                  'https://unknown.example/jobs/1', '岗位职责\n' + duty + '\n任职要求\n计算机专业。')
    assert local_duty_evidence(job, query) == []
    review = {'fingerprint': fingerprint(job, query), 'decision': {
        'status': 'matched', 'reason': '职责涉及Agent', 'evidence': [duty]}}
    assert valid_review(review, job, query)['decision']['status'] == 'pending'


@pytest.mark.parametrize('development', [
    '参与公司Agent产品的功能开发，包括工具调用、工作流编排、记忆管理等核心模块',
    '开发Agent应用并编写使用文档',
])
def test_product_development_quote_wins_over_documentation(development):
    documentation = '编写Agent开发文档与使用指南，沉淀可复用的技术方案'
    job = JobStub('unseen', '1', '任意公司', 'Agent开发工程师', ['上海'], 'campus', None,
                  'https://unknown.example/jobs/1', f'岗位职责\n{development}；\n{documentation}。\n任职要求\n计算机专业。')
    assert local_duty_evidence(job, 'ai agent / rag 校招') == [development]
