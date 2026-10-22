"""End-to-end guards and source-backed cohort consistency in both modes."""

from copy import deepcopy

import pytest

from src.domain.eligibility import (
    CandidateProfileInput,
    EligibilityInput,
    SearchPreferences,
)
from src.domain.graduation import classify_graduation_condition
from src.domain.job import RawJobDocument
from src.infrastructure.llm_client import FakeModelClient
from src.services.discovery_matching import classify_discovery_job
from src.services.discovery_sources import JobStub
from src.services.eligibility_checker import check_eligibility
from src.services.jd_parser import JDParserError
from src.services.product_jd_execution import ProductJDExecutionParser
from src.services.product_jd_runtime_guards import explicit_skill_alternatives


def degree_requirement():
    source = "本科及以上学历"
    return {
        "source_text": source,
        "level": "required",
        "relation": "all_of",
        "items": [source],
        "reason": "明确学历下限",
        "education": {
            "relation": "all_of",
            "branches": [
                {
                    "source_text": source,
                    "degree": {
                        "operator": "gte",
                        "level": "bachelor",
                        "source_text": source,
                    },
                    "major": {"mode": "not_specified"},
                    "scope": "application",
                    "scope_source_text": source,
                }
            ],
        },
    }


async def parse(mode, content, requirements, *, cohort=None, title=None):
    facts = {"graduation_years": cohort} if cohort else {}
    if mode == "single_call":
        outputs = [
            {"facts": facts, "requirements": requirements, "responsibilities": []}
        ]
    else:
        outputs = [
            {
                "facts": facts,
                "requirements": [
                    {"source_text": r["source_text"], "level": r["level"]}
                    for r in requirements
                ],
                "responsibilities": [],
            },
            {
                "decisions": [
                    {
                        "requirement_index": i,
                        **{
                            k: v
                            for k, v in r.items()
                            if k not in {"source_text", "level"}
                        },
                    }
                    for i, r in enumerate(requirements)
                ]
            },
        ]
    client = FakeModelClient(outputs=outputs)
    doc = RawJobDocument(
        raw_content=content, source_metadata={"title": title} if title else {}
    )
    parsed = await ProductJDExecutionParser(
        client, mode=mode, validation_retries=0
    ).parse(doc)
    assert len(client.requests) == (1 if mode == "single_call" else 2)
    for evidence in parsed.structured_jd.field_evidence or []:
        if evidence.source_kind == "body":
            assert (
                doc.raw_content[evidence.start_char : evidence.end_char]
                == evidence.source_text
            )
    return parsed.structured_jd


def qualify(job, year, *, level="bachelor"):
    profile = CandidateProfileInput(
        education_history_complete=True,
        educations=[
            {
                "level": level,
                "major_raw": "计算机",
                "graduation_year": year,
                "graduation_year_confirmed": True,
                "source_text": f"{level}，计算机，{year}届",
            }
        ],
    )
    return check_eligibility(
        EligibilityInput(job=job, profile=profile, preferences=SearchPreferences()),
        include_search_preferences=False,
    )


def discover(content, *, title="Agent开发工程师", year=2027):
    job = JobStub(
        source_id="test",
        source_job_id="1",
        title=title,
        company="测试",
        locations=[],
        job_type="campus",
        published_at=None,
        detail_url="https://example.com/position/1",
        raw_content=content,
    )
    result = classify_discovery_job(job, query=f"{year}届")
    return next(c for c in result.checks if c["field"] == "graduation_year")


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["single_call", "two_stage"])
@pytest.mark.parametrize(
    "source",
    [
        "熟悉AI语言模型的基本原理及相关专业名词，具备基础的Python能力",
        "了解至少一种 CI/CD 工具",
        "了解或对 Kubernetes/K8s、Docker、云平台、云原生技术有浓厚兴趣",
    ],
)
async def test_ordinary_skills_do_not_require_education_or_a_closed_choice(
    mode, source
):
    ordinary = {
        "source_text": source,
        "level": "required",
        "relation": "all_of",
        "items": [source],
        "reason": "单一普通能力条件",
        "education": None,
    }
    header = "2027届校园招聘计划"
    content = header + "\n任职要求\n本科及以上学历\n" + source
    job = await parse(
        mode,
        content,
        [degree_requirement(), ordinary],
        cohort={"values": [2027], "source_text": header},
    )
    assert job.requirements[1].education is None
    assert qualify(job, 2027).eligible == "pass"
    assert qualify(job, 2028).eligible == "fail"
    assert qualify(job, 2027, level="associate").eligible == "fail"


@pytest.mark.parametrize(
    "source,expected",
    [
        ("了解至少一种 CI/CD 工具", False),
        ("掌握至少一种 Kubernetes/K8s 工具", False),
        ("熟悉至少一门 Python/Go 编程语言", True),
        ("熟悉至少一种智能体框架(如LangChain/AutoGen等)", True),
        ("熟悉生成式算法或强化学习", True),
        ("了解或掌握Python", False),
        ("有高并发、系统的设计或实践经验", False),
        ("具有分布式系统的设计或者实践经历", False),
        ("有系统操作或使用经验", False),
        ("有系统理论或实践经验", False),
    ],
)
def test_slashes_and_predicate_choices_are_distinct_from_object_choices(
    source, expected
):
    assert explicit_skill_alternatives(source) is expected


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["single_call", "two_stage"])
@pytest.mark.parametrize(
    "header",
    [
        "2027届校园招聘计划",
        "2027届校园招聘-正式批",
        "2027届Seed大模型人才校招",
        "招聘项目：某公司2027届校园招聘计划",
        "27届校园招聘",
    ],
)
@pytest.mark.parametrize("omitted", [False, True])
async def test_discovery_and_qualification_share_header_semantics(
    mode, header, omitted
):
    content = header + "\n岗位职责\n开发Agent系统\n任职要求\n本科及以上学历"
    job = await parse(
        mode,
        content,
        [degree_requirement()],
        cohort=None if omitted else {"values": [2027], "source_text": header},
    )
    assert classify_graduation_condition(header) == "simple"
    assert discover(content)["status"] == "matched"
    assert discover(content, year=2028)["status"] == "excluded"
    assert qualify(job, 2027).eligible == "pass"
    assert qualify(job, 2028).eligible == "fail"
    assert job.graduation_source_text == header


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["single_call", "two_stage"])
@pytest.mark.parametrize(
    "clause",
    [
        "2027届获得本科及以上学历，计算机/数学等相关专业的优先",
        "2027 届本科及以上学历，计算机科学、软件工程等相关专业",
        "计算机或相关专业，2027届本科及以上学历",
        "计算机、数学等相关专业本科及以上学历，2027届毕业生",
        "2027届毕业本科及以上学历，计算机、软件工程等相关专业优先",
    ],
)
async def test_degree_cohort_and_major_preference_do_not_create_a_false_conflict(
    mode, clause
):
    header = "2027届Seed大模型人才校招"
    source = "2027届获得本科及以上学历"
    content = header + "\n任职要求\n1、" + clause + "\n" + source
    r = degree_requirement()
    r.update(source_text=source, items=[source])
    r["education"]["branches"][0].update(
        source_text=source,
        scope_source_text=source,
        graduation_years=[2027],
        graduation_source_text="2027届",
    )
    assert classify_graduation_condition(clause) == "simple"
    job = await parse(mode, content, [r])
    assert discover(content)["status"] == "matched"
    assert qualify(job, 2027).eligible == "pass"
    assert qualify(job, 2028).eligible == "fail"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["single_call", "two_stage"])
@pytest.mark.parametrize("header", ["2027校园招聘", "招聘项目：某公司2027校园招聘"])
@pytest.mark.parametrize("omitted", [False, True])
async def test_recruitment_year_alone_does_not_establish_a_graduation_cohort(
    mode, header, omitted
):
    content = header + "\n任职要求\n本科及以上学历"
    job = await parse(
        mode,
        content,
        [degree_requirement()],
        cohort=None if omitted else {"values": [2027], "source_text": header},
    )
    assert classify_graduation_condition(header) == "ambiguous"
    assert discover(content)["status"] == "pending"
    for year in [2027, 2028]:
        assert qualify(job, year).eligible == "unknown"
    assert qualify(job, 2027, level="associate").eligible == "fail"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["single_call", "two_stage"])
@pytest.mark.parametrize("omitted", [False, True])
async def test_conflicting_title_is_retained_without_executing_the_project_year(
    mode, omitted
):
    header, title = "2027届校园招聘", "Agent研发工程师-2028届实习"
    content = header + "\n岗位名称：" + title + "\n任职要求\n本科及以上学历"
    job = await parse(
        mode,
        content,
        [degree_requirement()],
        title=title,
        cohort=None if omitted else {"values": [2027], "source_text": header},
    )
    assert discover(content, title=title)["status"] == "pending"
    for year in [2027, 2028]:
        result = qualify(job, year)
        assert result.eligible == "unknown"
        assert (
            next(c for c in result.checks if c.field == "educations").result == "pass"
        )
    quotes = [
        e.source_text for e in job.field_evidence if e.field_path == "graduation_years"
    ]
    assert header in quotes and any(title in quote for quote in quotes)
    assert qualify(job, 2028, level="associate").eligible == "fail"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["single_call", "two_stage"])
async def test_metadata_title_can_flag_a_conflict_but_not_supply_a_hard_cohort(mode):
    title = "Agent开发工程师-2028届实习"
    source = "任职要求\n本科及以上学历\n负责Agent研发并验证软件功能"
    title_only = await parse(mode, source, [degree_requirement()], title=title)
    assert qualify(title_only, 2028).eligible == "unknown"
    header = "2027届校园招聘"
    job = await parse(mode, header + "\n" + source, [degree_requirement()], title=title)
    assert qualify(job, 2028).eligible == "unknown"
    assert any(
        e.source_text == title and e.source_kind == "metadata"
        for e in job.field_evidence
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["single_call", "two_stage"])
@pytest.mark.parametrize(
    "source",
    [
        "不面向2027届毕业生",
        "2027届以外的毕业生",
        "2027届以后毕业",
    ],
)
async def test_same_year_negation_and_open_ranges_do_not_validate_a_project_gate(
    mode, source
):
    header = "2027届校园招聘"
    content = header + "\n任职要求\n本科及以上学历\n" + source
    job = await parse(mode, content, [degree_requirement()])
    assert discover(content)["status"] == "pending"
    assert qualify(job, 2027).eligible == "unknown"
    assert qualify(job, 2027, level="associate").eligible == "fail"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["single_call", "two_stage"])
@pytest.mark.parametrize(
    "source",
    [
        "海外2027届校园招聘",
        "2027年9月至2028年8月毕业",
        "2027届校园招聘，且须海外学历",
    ],
)
async def test_qualifiers_are_not_removed_to_obtain_a_pass(mode, source):
    content = source + "\n任职要求\n本科及以上学历"
    job = await parse(
        mode,
        content,
        [degree_requirement()],
        cohort={"values": [2027], "source_text": source},
    )
    assert discover(content)["status"] == "pending"
    assert qualify(job, 2027).eligible == "unknown"
    assert qualify(job, 2027, level="associate").eligible == "fail"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["single_call", "two_stage"])
async def test_explicit_qualification_still_requires_structured_education(mode):
    r = degree_requirement()
    r["education"] = None
    with pytest.raises(JDParserError):
        await parse(mode, "2027届校园招聘\n任职要求\n本科及以上学历", [r])


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["single_call", "two_stage"])
async def test_listed_open_major_preference_is_valid_but_cannot_become_a_hard_gate(
    mode,
):
    source = "计算机、人工智能、系统工程、通讯工程、网络安全等专业优先"
    pref = deepcopy(degree_requirement())
    pref.update(source_text=source, level="preferred", items=[source])
    b = pref["education"]["branches"][0]
    b.update(
        source_text=source,
        scope_source_text=source,
        degree={"operator": "not_specified"},
        major={
            "mode": "related",
            "values": ["计算机", "人工智能", "系统工程", "通讯工程", "网络安全"],
            "source_text": source,
        },
    )
    job = await parse(
        mode, "2027届校园招聘\n本科及以上学历\n" + source, [degree_requirement(), pref]
    )
    assert not job.requirements[1].mandatory
    profile_result = qualify(job, 2027)
    assert profile_result.eligible == "pass"
