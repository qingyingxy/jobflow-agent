"""Behavior regressions for inline parsing, shared evidence and bounded repair."""

from copy import deepcopy

import pytest

from src.domain.education import (
    EducationCondition,
    degree_levels,
    validate_condition_grounding,
)
from src.domain.eligibility import (
    CandidateProfileInput,
    EligibilityInput,
    SearchPreferences,
)
from src.domain.job import RawJobDocument
from src.infrastructure.llm_client import FakeModelClient
from src.services.education_evaluator import evaluate_education
from src.services.eligibility_checker import check_eligibility
from src.services.jd_parser import JDParserError
from src.services.product_jd_execution import ProductJDExecutionParser


def branch(source, level="master", major=None):
    label = {"master": "硕士", "doctor": "博士", "bachelor": "本科"}[level]
    return {
        "source_text": source,
        "degree": {"operator": "eq", "level": level, "source_text": label},
        "major": major or {"mode": "not_specified"},
        "scope": "application",
        "scope_source_text": source,
    }


def requirement(source, *, education=None, relation="all_of", items=None):
    return {
        "source_text": source,
        "level": "required",
        "relation": relation,
        "items": items if items is not None else ([] if education else [source]),
        "reason": "按原文资格要求解释",
        "education": education,
    }


def inline(*requirements):
    return {"facts": {}, "requirements": list(requirements), "responsibilities": []}


def document(source):
    return RawJobDocument(
        raw_content="某公司招聘工程师。任职资格："
        + source
        + "。欢迎符合条件的候选人投递。"
    )


@pytest.mark.parametrize(
    ("text", "levels"),
    [
        ("RoboMaster 电控竞赛", set()),
        ("Robomaster/Robocon", set()),
        ("masterpiece 项目", set()),
        ("Master degree", {"master"}),
        ("Master's degree in Computer Science", {"master"}),
        ("Bachelor of Engineering", {"bachelor"}),
        ("硕士或博士", {"master", "doctor"}),
    ],
)
def test_english_degree_aliases_have_word_boundaries(text, levels):
    assert degree_levels(text) == levels


@pytest.mark.asyncio
async def test_competition_experience_is_not_a_missing_masters_requirement():
    source = "有RoboMaster电控或硬件调试经验者优先"
    r = requirement(source, relation="any_of", items=["RoboMaster电控", "硬件调试"])
    r["level"] = "preferred"
    client = FakeModelClient(output=inline(r))
    parsed = await ProductJDExecutionParser(client, mode="single_call").parse(
        document(source)
    )
    assert len(client.requests) == 1
    assert parsed.structured_jd.requirements[0].education is None


@pytest.mark.asyncio
async def test_shared_major_evidence_preserves_both_degree_paths():
    source = "计算机相关专业的硕士或博士"
    major = {"mode": "related", "values": ["计算机"], "source_text": "计算机相关专业"}
    condition = {
        "relation": "any_of",
        "branches": [branch(source, level, major) for level in ("master", "doctor")],
    }
    client = FakeModelClient(
        output=inline(requirement(source, education=condition, relation="any_of"))
    )
    parsed = await ProductJDExecutionParser(client, mode="single_call").parse(
        document(source)
    )
    r = parsed.structured_jd.requirements[0]
    assert r.items == ["硕士", "博士"]
    assert [b.source_text for b in r.education.branches] == [source, source]
    for level in ("master", "doctor"):
        profile = CandidateProfileInput(
            educations=[
                {
                    "level": level,
                    "major_raw": "计算机",
                    "source_text": f"{level} 计算机",
                }
            ]
        )
        assert evaluate_education(r.education, profile).result == "pass"
    for e in r.evidence:
        assert document(source).raw_content[e.start_char : e.end_char] == e.source_text


def test_repeated_predicates_are_not_distinct_alternatives():
    source = "硕士学历"
    b = branch(source)
    with pytest.raises(ValueError, match="不同的资格谓词"):
        EducationCondition(relation="any_of", branches=[b, deepcopy(b)])


@pytest.mark.parametrize(
    ("status", "source", "valid"),
    [
        ("graduated", "2027届获得本科及以上学历", False),
        ("graduated", "预计2027年毕业的本科生", False),
        ("graduated", "本科未毕业", False),
        ("graduated", "已经取得本科学位", True),
        ("enrolled", "本科在读", True),
        ("enrolled", "本科非在读", False),
        ("any", "2027届获得本科及以上学历", True),
    ],
)
def test_current_status_is_separate_from_future_graduation(status, source, valid):
    b = branch(source, "bachelor")
    b["status"] = status
    condition = EducationCondition(relation="all_of", branches=[b])
    if valid:
        validate_condition_grounding(condition, source)
    else:
        with pytest.raises(ValueError, match="当前毕业或在读状态"):
            validate_condition_grounding(condition, source)


@pytest.mark.asyncio
@pytest.mark.parametrize("duplicate_global", [False, True])
async def test_future_cohort_does_not_exclude_an_enrolled_candidate(duplicate_global):
    source = "2027届获得本科及以上学历"
    b = branch(source, "bachelor")
    b.update(graduation_years=[2027], graduation_source_text="2027届", status="any")
    b["degree"].update(operator="gte", source_text="本科及以上")
    output = inline(
        requirement(source, education={"relation": "all_of", "branches": [b]})
    )
    if duplicate_global:
        output["facts"] = {
            "graduation_years": {"values": [2027], "source_text": source}
        }
    parsed = await ProductJDExecutionParser(
        FakeModelClient(output=output),
        mode="single_call",
    ).parse(document(source))
    profile = CandidateProfileInput(
        educations=[
            {
                "level": "bachelor",
                "major_raw": "机械",
                "source_text": "本科机械，预计2027年毕业，在读",
                "graduation_year": 2027,
                "graduation_source_text": "预计2027年毕业",
                "graduation_year_kind": "expected",
                "status": "enrolled",
            }
        ]
    )
    assert (
        evaluate_education(
            parsed.structured_jd.requirements[0].education, profile
        ).result
        == "pass"
    )
    assert parsed.structured_jd.graduation_years is None
    assert (
        check_eligibility(
            EligibilityInput(
                profile=profile,
                job=parsed.structured_jd,
                preferences=SearchPreferences(),
            ),
            include_search_preferences=False,
        ).eligible
        == "pass"
    )


@pytest.mark.asyncio
async def test_global_cohort_is_not_borrowed_by_historical_education():
    source = "硕士学历，且本科专业为软件工程"
    global_source = "本岗位面向2028届毕业生"
    app = branch(source)
    app["source_text"] = "硕士学历"
    app.update(graduation_years=[2028], graduation_source_text=global_source)
    historic = branch(
        source,
        "bachelor",
        {"mode": "exact", "values": ["软件工程"], "source_text": "软件工程"},
    )
    historic["scope"] = "historical"
    historic["source_text"] = "本科专业为软件工程"
    condition = {"relation": "all_of", "branches": [app, historic]}
    output = inline(requirement(source, education=condition))
    output["facts"] = {
        "graduation_years": {"values": [2028], "source_text": global_source}
    }
    raw = document(global_source + "。任职要求：" + source)
    parsed = await ProductJDExecutionParser(
        FakeModelClient(output=output), mode="single_call"
    ).parse(raw)
    assert parsed.structured_jd.graduation_years == [2028]
    assert all(
        b.graduation_years is None
        for b in parsed.structured_jd.requirements[0].education.branches
    )
    for year, expected in [(2028, "pass"), (2027, "fail")]:
        profile = CandidateProfileInput(
            education_history_complete=True,
            educations=[
                {
                    "level": "bachelor",
                    "major_raw": "软件工程",
                    "graduation_year": 2024,
                    "source_text": "本科软件工程2024毕业",
                },
                {
                    "level": "master",
                    "major_raw": "金融",
                    "graduation_year": year,
                    "source_text": f"硕士金融{year}预计毕业",
                },
            ],
        )
        result = check_eligibility(
            EligibilityInput(
                profile=profile,
                job=parsed.structured_jd,
                preferences=SearchPreferences(),
            ),
            include_search_preferences=False,
        )
        assert result.eligible == expected
    # A historical branch cannot borrow the same global cohort.
    invalid = deepcopy(output)
    invalid["requirements"][0]["education"]["branches"][1].update(
        graduation_years=[2028], graduation_source_text=global_source
    )
    with pytest.raises(JDParserError):
        await ProductJDExecutionParser(
            FakeModelClient(output=invalid), mode="single_call", validation_retries=0
        ).parse(raw)


@pytest.mark.asyncio
async def test_cohort_deduplication_keeps_unsupported_geographic_limits():
    source = "海外2027届获得本科及以上学历"
    b = branch(source, "bachelor")
    b.update(graduation_years=[2027], graduation_source_text="2027届", unresolved=True)
    b["degree"].update(operator="gte", source_text="本科及以上")
    output = inline(
        requirement(source, education={"relation": "all_of", "branches": [b]})
    )
    output["facts"] = {"graduation_years": {"values": [2027], "source_text": source}}
    parsed = await ProductJDExecutionParser(
        FakeModelClient(output=output), mode="single_call"
    ).parse(document(source))
    assert parsed.structured_jd.graduation_years == [2027]
    assert parsed.structured_jd.graduation_condition_kind == "qualified"


def test_open_major_and_year_ranges_cannot_be_silently_narrowed():
    source = "2027届以后硕士，计算机、数学等专业"
    b = branch(
        source,
        major={
            "mode": "exact",
            "values": ["计算机", "数学"],
            "source_text": "计算机、数学等专业",
        },
    )
    condition = EducationCondition(relation="all_of", branches=[b])
    with pytest.raises(ValueError, match="开放专业范围"):
        validate_condition_grounding(condition, source)
    b["major"] = {"mode": "unknown", "source_text": "计算机、数学等专业"}
    b.update(
        graduation_years=[2027], graduation_source_text="2027届以后", unresolved=True
    )
    with pytest.raises(ValueError, match="年份区间"):
        validate_condition_grounding(
            EducationCondition(relation="all_of", branches=[b]), source
        )
    b["graduation_years"] = None
    condition = EducationCondition(relation="all_of", branches=[b])
    validate_condition_grounding(condition, source)
    assert (
        evaluate_education(
            condition,
            CandidateProfileInput(
                educations=[
                    {
                        "level": "master",
                        "major_raw": "计算机",
                        "source_text": "硕士计算机",
                    }
                ]
            ),
        ).result
        == "unknown"
    )


@pytest.mark.asyncio
async def test_repair_changes_only_invalid_requirements_and_retains_facts():
    s1, s2, s3 = "硕士学历", "本科在读", "熟悉Python"
    good1 = requirement(s1, education={"relation": "all_of", "branches": [branch(s1)]})
    good2 = requirement(
        s2, education={"relation": "all_of", "branches": [branch(s2, "bachelor")]}
    )
    bad1, bad2 = deepcopy(good1), deepcopy(good2)
    bad1["education"]["branches"][0]["scope_source_text"] = "没有出现的范围"
    bad2["education"] = None
    initial = inline(bad1, bad2, requirement(s3))
    initial["facts"] = {"locations": {"values": ["上海"], "source_text": "地点：上海"}}
    repair = {
        "repaired_requirements": [
            {"requirement_index": 0, "requirement": good1},
            {"requirement_index": 1, "requirement": good2},
        ]
    }
    client = FakeModelClient(outputs=[initial, repair])
    parsed = await ProductJDExecutionParser(client, mode="single_call").parse(
        document(f"地点：上海。{s1}；{s2}；{s3}")
    )
    assert [r.schema_name for r in client.requests] == [
        "product_job_inline",
        "product_requirement_repair",
    ]
    assert parsed.structured_jd.locations == ["上海"]
    assert parsed.structured_jd.requirements[2].description == s3
    assert parsed.diagnostics["attempts"][0]["repair_indices"] == [0, 1]


@pytest.mark.asyncio
@pytest.mark.parametrize("tamper", ["source", "level", "missing", "extra", "duplicate"])
async def test_repair_cannot_delete_rewrite_or_weaken_a_requirement(tamper):
    source = "硕士学历"
    good = requirement(
        source, education={"relation": "all_of", "branches": [branch(source)]}
    )
    bad = deepcopy(good)
    bad["education"] = None
    repair = {
        "repaired_requirements": [
            {"requirement_index": 0, "requirement": deepcopy(good)}
        ]
    }
    entries = repair["repaired_requirements"]
    if tamper == "source":
        entries[0]["requirement"]["source_text"] = "硕士"
    elif tamper == "level":
        entries[0]["requirement"]["level"] = "preferred"
    elif tamper == "missing":
        entries.clear()
    elif tamper == "extra":
        entries.append({"requirement_index": 1, "requirement": good})
    else:
        entries.append(deepcopy(entries[0]))
    client = FakeModelClient(outputs=[inline(bad), repair])
    with pytest.raises(JDParserError):
        await ProductJDExecutionParser(client, mode="single_call").parse(
            document(source)
        )
    assert len(client.requests) == 2


@pytest.mark.asyncio
async def test_shared_branch_cannot_borrow_evidence_from_another_requirement():
    source = "硕士学历"
    b = branch(
        "计算机专业硕士学历",
        major={"mode": "exact", "values": ["计算机"], "source_text": "计算机专业"},
    )
    value = inline(
        requirement(source, education={"relation": "all_of", "branches": [b]})
    )
    with pytest.raises(JDParserError):
        await ProductJDExecutionParser(
            FakeModelClient(output=value), mode="single_call", validation_retries=0
        ).parse(document(source + "；另一个岗位计算机专业硕士学历"))
