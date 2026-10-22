"""Runtime regressions for choice repair, evidence and preference boundaries."""

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
from src.services.eligibility_checker import check_eligibility
from src.services.jd_parser import JDParserError
from src.services.product_jd_execution import ProductJDExecutionParser
from src.services.product_jd_runtime_guards import explicit_skill_alternatives


def requirement(
    source, relation="all_of", items=None, *, level="required", education=None
):
    return {
        "source_text": source,
        "level": level,
        "relation": relation,
        "items": items or ([] if education else [source]),
        "reason": "按原文判断",
        "education": education,
    }


def inline(*requirements, cohort=None):
    return {
        "facts": {"graduation_years": cohort} if cohort else {},
        "requirements": list(requirements),
        "responsibilities": [],
    }


def document(source):
    return RawJobDocument(raw_content="某公司校园招聘。任职资格：" + source)


def education(source, *, major=None, years=None, year_quote=None):
    return {
        "relation": "all_of",
        "branches": [
            {
                "source_text": source,
                "degree": {
                    "operator": "gte",
                    "level": "bachelor",
                    "source_text": "本科及以上学历",
                },
                "major": major or {"mode": "not_specified"},
                "scope": "application",
                "scope_source_text": source,
                "graduation_years": years,
                "graduation_source_text": year_quote,
            }
        ],
    }


def candidate(year, major="机械"):
    return CandidateProfileInput(
        education_history_complete=True,
        educations=[
            {
                "level": "bachelor",
                "major_raw": major,
                "graduation_year": year,
                "source_text": f"本科{major}，{year}届",
            }
        ],
    )


def eligibility(parsed, year):
    return check_eligibility(
        EligibilityInput(
            job=parsed.structured_jd,
            profile=candidate(year),
            preferences=SearchPreferences(),
        ),
        include_search_preferences=False,
    ).eligible


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("招聘项目：2027届应届生校园招聘", "simple"),
        ("招聘项目：2028届校园招聘", "simple"),
        ("招聘项目：小鹏汽车2027届校园招聘", "simple"),
        ("招聘项目：它石智航2027校园招聘", "ambiguous"),
        ("招聘项目：某公司海外2027届校园招聘", "qualified"),
        ("招聘项目：非2027届校园招聘", "ambiguous"),
        ("招聘项目：硕士2027届校园招聘", "ambiguous"),
        ("招聘对象：27届毕业生", "simple"),
        ("面向27届毕业生", "simple"),
        ("届别：2027届、2028届", "simple"),
        ("招聘项目：海外2027届校园招聘", "qualified"),
        ("招聘项目：2027届校园招聘，且须海外学历", "qualified"),
        ("招聘项目：2027届以外的校园招聘", "ambiguous"),
        ("不面向27届毕业生", "ambiguous"),
        ("2027年9月至2028年8月毕业", "qualified"),
        ("招聘项目：99届校园招聘", "ambiguous"),
        ("招聘项目：27校园招聘", "ambiguous"),
    ],
)
def test_cohort_headers_keep_restrictive_context(source, expected):
    assert classify_graduation_condition(source) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["single_call", "two_stage"])
async def test_header_cohort_binds_degree_and_preserves_exact_quote(mode):
    header, source = "招聘项目：2027届应届生校园招聘", "本科及以上学历"
    cohort = {"values": [2027], "source_text": header}
    condition = education(source)
    r = requirement(source, education=condition)
    if mode == "single_call":
        outputs = [inline(r, cohort=cohort)]
    else:
        outputs = [
            {
                "facts": {"graduation_years": cohort},
                "requirements": [{"source_text": source, "level": "required"}],
            },
            {
                "decisions": [
                    {
                        "requirement_index": 0,
                        "relation": "all_of",
                        "items": [source],
                        "reason": "硬学历",
                        "education": condition,
                    }
                ]
            },
        ]
    doc = RawJobDocument(raw_content=header + "。任职要求：" + source)
    parsed = await ProductJDExecutionParser(
        FakeModelClient(outputs=outputs), mode=mode
    ).parse(doc)
    assert parsed.structured_jd.graduation_source_text == header
    assert eligibility(parsed, 2027) == "pass"
    assert eligibility(parsed, 2028) == "fail"
    for evidence in parsed.structured_jd.field_evidence:
        assert (
            doc.raw_content[evidence.start_char : evidence.end_char]
            == evidence.source_text
        )


@pytest.mark.asyncio
async def test_abbreviated_cohort_is_normalized_without_rewriting_evidence():
    source = "27届本科及以上学历"
    r = requirement(
        source, education=education(source, years=[2027], year_quote="27届")
    )
    parsed = await ProductJDExecutionParser(
        FakeModelClient(output=inline(r)), mode="single_call"
    ).parse(document(source))
    assert (
        parsed.structured_jd.requirements[0]
        .education.branches[0]
        .graduation_source_text
        == "27届"
    )
    assert eligibility(parsed, 2027) == "pass"
    assert eligibility(parsed, 2028) == "fail"


@pytest.mark.asyncio
async def test_company_header_cohort_can_bind_an_application_masters_degree():
    header, source = "招聘项目：小鹏汽车2027届校园招聘", "27届硕士及其以上学历"
    condition = {
        "relation": "all_of",
        "branches": [
            {
                "source_text": source,
                "degree": {
                    "operator": "gte",
                    "level": "master",
                    "source_text": "硕士及其以上学历",
                },
                "major": {"mode": "not_specified"},
                "scope": "application",
                "scope_source_text": source,
            }
        ],
    }
    output = inline(
        requirement(source, education=condition),
        cohort={"values": [2027], "source_text": header},
    )
    parsed = await ProductJDExecutionParser(
        FakeModelClient(output=output), mode="single_call"
    ).parse(document(header + "。" + source))
    for year, expected in [(2027, "pass"), (2028, "fail")]:
        profile = CandidateProfileInput(
            education_history_complete=True,
            educations=[
                {
                    "level": "master",
                    "major_raw": "金融",
                    "graduation_year": year,
                    "source_text": f"金融硕士{year}届",
                }
            ],
        )
        assert (
            check_eligibility(
                EligibilityInput(
                    job=parsed.structured_jd,
                    profile=profile,
                    preferences=SearchPreferences(),
                ),
                include_search_preferences=False,
            ).eligible
            == expected
        )


@pytest.mark.asyncio
async def test_wrong_year_in_a_valid_quote_cannot_pass():
    output = inline(cohort={"values": [2028], "source_text": "27届校园招聘"})
    with pytest.raises(JDParserError):
        await ProductJDExecutionParser(
            FakeModelClient(output=output), mode="single_call", validation_retries=0
        ).parse(document("27届校园招聘"))


@pytest.mark.parametrize(
    ("source", "is_choice"),
    [
        ("有大模型工程化或AI应用开发实习经历者优先", True),
        ("具备基础软硬件测试、数据分析或机器人系统理解能力", True),
        ("熟悉Adams、MATLAB/Simulink、Ansys Motion或其他仿真工具者优先", True),
        ("有训练或应用经验加分", True),
        ("熟悉Python、Java等至少一门语言", True),
        ("熟悉Python、Java等语言", False),
        ("了解游戏研发流程、游戏引擎、内容生产、自动化测试或项目协作", False),
        ("有大模型训练、NLP或相关方向研究/项目经历者优先", False),
        ("有自己的思考或实践", False),
        ("有复现或参与过某项工作的经历", False),
        ("能够分析或解释时间序列", False),
        ("有相关科研或项目经验者优先", False),
        ("具备扎实的机器学习、深度学习、机器人学或控制理论基础", False),
        ("具备扎实的编程基础，熟悉至少一门主流编程语言，能够独立完成模块开发", False),
        ("3. 熟悉Python、Java等至少一门语言", True),
    ],
)
def test_bounded_relation_guard_does_not_treat_every_or_as_a_choice(source, is_choice):
    assert explicit_skill_alternatives(source) is is_choice


@pytest.mark.asyncio
async def test_explicit_choice_triggers_localized_model_repair():
    source = "有大模型工程化或AI应用开发实习经历者优先"
    bad = requirement(source, level="preferred")
    good = requirement(
        source, "any_of", ["大模型工程化", "AI应用开发实习经历"], level="preferred"
    )
    client = FakeModelClient(
        outputs=[
            inline(bad),
            {"repaired_requirements": [{"requirement_index": 0, "requirement": good}]},
        ]
    )
    parsed = await ProductJDExecutionParser(client, mode="single_call").parse(
        RawJobDocument(raw_content=source)
    )
    assert [r.schema_name for r in client.requests] == [
        "product_job_inline",
        "product_requirement_repair",
    ]
    assert parsed.structured_jd.requirements[0].relation == "any_of"
    assert parsed.diagnostics["attempts"][0]["repair_indices"] == [0]


@pytest.mark.asyncio
async def test_unsplit_common_requirement_requests_full_reextraction():
    left, right = "熟悉生成式算法或强化学习", "能够实现论文算法"
    source = left + "，并且" + right
    client = FakeModelClient(
        outputs=[
            inline(requirement(source)),
            inline(
                requirement(left, "any_of", ["生成式算法", "强化学习"]),
                requirement(right),
            ),
        ]
    )
    parsed = await ProductJDExecutionParser(client, mode="single_call").parse(
        RawJobDocument(raw_content=source)
    )
    assert [r.schema_name for r in client.requests] == [
        "product_job_inline",
        "product_job_inline",
    ]
    assert [r.relation for r in parsed.structured_jd.requirements] == [
        "any_of",
        "all_of",
    ]
    assert parsed.diagnostics["attempts"][0]["repair_scope"] == "full_output"


@pytest.mark.asyncio
@pytest.mark.parametrize("tamper", ["common", "unchanged", "weaken"])
async def test_full_boundary_repair_cannot_delete_or_weaken_known_conditions(tamper):
    left, right, other = (
        "熟悉生成式算法或强化学习",
        "能够实现论文算法",
        "具备Python开发能力",
    )
    initial = inline(requirement(left + "，并且" + right), requirement(other))
    repaired = [
        requirement(left, "any_of", ["生成式算法", "强化学习"]),
        requirement(right),
        requirement(other),
    ]
    if tamper == "common":
        del repaired[1]
    elif tamper == "unchanged":
        del repaired[2]
    else:
        repaired[1]["level"] = "preferred"
    client = FakeModelClient(outputs=[initial, inline(*repaired)])
    with pytest.raises(JDParserError, match="未通过结构或原文证据校验"):
        await ProductJDExecutionParser(client, mode="single_call").parse(
            document(left + "，并且" + right + "；" + other)
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["single_call", "two_stage"])
async def test_hard_degree_and_preferred_major_are_reextracted_separately(mode):
    left, right = "2027届获得本科及以上学历", "计算机相关专业优先"
    source = left + "，" + right
    hard = requirement(
        left, education=education(left, years=[2027], year_quote="2027届")
    )
    preference = requirement(
        right,
        level="preferred",
        education={
            "relation": "all_of",
            "branches": [
                {
                    "source_text": right,
                    "degree": {"operator": "not_specified"},
                    "major": {
                        "mode": "related",
                        "values": ["计算机"],
                        "source_text": right,
                    },
                    "scope": "application",
                    "scope_source_text": source,
                }
            ],
        },
    )
    if mode == "single_call":
        bad = requirement(
            source,
            education=education(
                source,
                major={"mode": "related", "values": ["计算机"], "source_text": right},
                years=[2027],
                year_quote="2027届",
            ),
        )
        outputs = [inline(bad), inline(hard, preference)]
    else:
        outputs = [
            {
                "facts": {},
                "requirements": [{"source_text": source, "level": "required"}],
            },
            {
                "facts": {},
                "requirements": [
                    {k: r[k] for k in ("source_text", "level")}
                    for r in (hard, preference)
                ],
            },
            {
                "decisions": [
                    {
                        "requirement_index": i,
                        **{
                            k: r[k]
                            for k in ("relation", "items", "reason", "education")
                        },
                        "items": [r["source_text"]],
                    }
                    for i, r in enumerate((hard, preference))
                ]
            },
        ]
    client = FakeModelClient(outputs=outputs)
    parsed = await ProductJDExecutionParser(client, mode=mode).parse(
        RawJobDocument(raw_content=source)
    )
    assert eligibility(parsed, 2027) == "pass"
    assert eligibility(parsed, 2028) == "fail"
    assert [r.mandatory for r in parsed.structured_jd.requirements] == [True, False]


@pytest.mark.asyncio
async def test_repair_exhaustion_never_publishes_an_incorrect_choice():
    source = "熟悉生成式算法或强化学习"
    bad = requirement(source)
    client = FakeModelClient(
        outputs=[
            inline(bad),
            {
                "repaired_requirements": [
                    {"requirement_index": 0, "requirement": deepcopy(bad)}
                ]
            },
        ]
    )
    with pytest.raises(JDParserError) as caught:
        await ProductJDExecutionParser(client, mode="single_call").parse(
            document(source)
        )
    assert caught.value.details["model_call_count"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "header", ["招聘项目：某公司2027届校园招聘", "本岗位面向2027届毕业生"]
)
async def test_batch_label_and_qualified_body_preserve_both_sources(header):
    source = "2027届以后本科及以上学历，在读学生"
    condition = education(source)
    condition["branches"][0].update(
        status="enrolled", unresolved=True, graduation_source_text="2027届以后"
    )
    output = inline(
        requirement(source, education=condition),
        cohort={"values": [2027], "source_text": header},
    )
    parsed = await ProductJDExecutionParser(
        FakeModelClient(output=output), mode="single_call"
    ).parse(document(header + "。" + source))
    profile = candidate(2028)
    profile.educations[0].status = "enrolled"
    result = check_eligibility(
        EligibilityInput(
            job=parsed.structured_jd, profile=profile, preferences=SearchPreferences()
        ),
        include_search_preferences=False,
    )
    assert result.eligible == ("unknown" if "招聘项目" in header else "fail")
    if "招聘项目" in header:
        assert parsed.structured_jd.graduation_condition_kind == "qualified"
        assert {
            e.source_text
            for e in parsed.structured_jd.field_evidence
            if e.field_path == "graduation_years"
        } == {header, source, "2027届以后"}
    # Known violations remain decisive even if the cohort itself is unresolved.
    profile.educations[0].status = "graduated"
    assert (
        check_eligibility(
            EligibilityInput(
                job=parsed.structured_jd,
                profile=profile,
                preferences=SearchPreferences(),
            ),
            include_search_preferences=False,
        ).eligible
        == "fail"
    )


@pytest.mark.asyncio
async def test_preference_split_cannot_weaken_the_original_hard_degree():
    left, right = "本科及以上学历", "计算机相关专业优先"
    source = left + "，" + right
    initial = inline(requirement(source))
    repaired = inline(
        requirement(left, level="preferred", education=education(left)),
        requirement(
            right,
            level="preferred",
            education={
                "relation": "all_of",
                "branches": [
                    {
                        "source_text": right,
                        "degree": {"operator": "not_specified"},
                        "major": {
                            "mode": "related",
                            "values": ["计算机"],
                            "source_text": right,
                        },
                        "scope": "application",
                        "scope_source_text": source,
                    }
                ],
            },
        ),
    )
    with pytest.raises(JDParserError):
        await ProductJDExecutionParser(
            FakeModelClient(outputs=[initial, repaired]), mode="single_call"
        ).parse(document(source))
