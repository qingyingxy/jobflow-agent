import pytest

from src.domain.job import JobRequirement
from src.domain.matching import EvidenceRecord
from src.services.local_evidence_matcher import match_requirement_locally


def match(description, claim, *, items=None, relation="all_of", skills=None):
    return match_requirement_locally(
        user_id="a",
        requirement=JobRequirement(
            category="required_skill",
            name="Python",
            description=description,
            items=items,
            relation=relation,
        ),
        evidence=[
            EvidenceRecord(
                id="ev_test",
                user_id="a",
                title="Python 项目",
                claim=claim,
                skills=skills or ["Python"],
            )
        ],
    )


@pytest.mark.parametrize(
    "description",
    [
        "熟练掌握 Python，并有三年线上系统开发经验",
        "三年 Python 开发经验",
        "精通 Python",
        "独立负责 Python 平台架构",
        "使用 Python 将延迟降低 50%",
    ],
)
def test_keyword_cannot_discharge_qualifiers(description):
    result = match(description, "使用 Python 写过课程脚本", items=["Python"])
    assert result.support_level == "partial"
    assert result.item_checks[0].unresolved
    assert result.item_checks[0].evidence_quotes == ["使用 Python 写过课程脚本"]


@pytest.mark.parametrize(
    "description,claim",
    [
        ("三年 Python 开发经验", "五年 Python 开发经验"),
        ("三年 Python 开发经验", "36个月 Python 开发经验"),
        (
            "熟练掌握 Python，并有三年线上系统开发经验",
            "熟练掌握 Python，有五年线上系统开发经验",
        ),
        ("熟悉 Python", "精通 Python"),
        ("独立负责 Python 平台架构", "独立负责 Python 平台架构"),
        ("使用 Python 将延迟降低 50%", "使用 Python 将延迟降低 50%"),
        ("Python", "使用 Python 写过课程脚本"),
    ],
)
def test_explicit_bound_evidence_passes_without_model_or_confirmation(
    description, claim
):
    assert match(description, claim).support_level == "supported"


@pytest.mark.parametrize(
    "claim",
    [
        "没有 Python 开发经验",
        "计划学习 Python",
        "岗位要求精通 Python",
        "团队成员精通 Python",
        "未掌握 Python",
        "Pythonic 项目",
        "使用 Java 写课程脚本",
    ],
)
def test_tags_negation_plans_and_other_subjects_are_not_proof(claim):
    assert match("Python", claim).support_level != "supported"


@pytest.mark.parametrize(
    "claim",
    [
        "使用 Python 半年，Java 五年开发经验",
        "精通 Java，使用 Python 写脚本",
        "三年 Java 开发经验；使用 Python 写过脚本",
        "不足三年 Python 开发经验",
        "最多三年 Python 开发经验",
        "约三年 Python 开发经验",
        "近三年 Python 开发经验",
    ],
)
def test_does_not_borrow_qualifiers_from_other_subjects(claim):
    assert match("三年 Python 开发经验", claim).support_level != "supported"


def test_or_retains_shared_proficiency_and_mandatory_suffix():
    kwargs = {"items": ["Python", "Java"], "relation": "any_of"}
    description = "熟悉 Python 或 Java，并且能够实现论文算法"
    assert (
        match(description, "使用 Python 写课程脚本", **kwargs).support_level
        == "partial"
    )
    assert (
        match(description, "熟悉 Python，并且能够实现论文算法", **kwargs).support_level
        == "supported"
    )
    assert match(description, "熟悉 Python", **kwargs).support_level == "partial"


def test_ambiguous_or_cannot_turn_partial_label_into_full_support():
    result = match(
        "熟悉 Python，或者有 Java 开发经验",
        "使用 Python 写脚本",
        items=["Python", "Java"],
        relation="any_of",
    )
    assert result.support_level == "needs_confirmation"


def test_does_not_borrow_other_users_evidence_or_combine_years():
    requirement = JobRequirement(
        category="required_skill", name="Python", description="三年 Python 开发经验"
    )
    records = [
        EvidenceRecord(id=f"ev_{i}", user_id=user, title="项目", claim=claim)
        for i, (user, claim) in enumerate(
            [
                ("a", "两年 Python 开发经验"),
                ("a", "两年 Python 开发经验"),
                ("b", "五年 Python 开发经验"),
            ]
        )
    ]
    result = match_requirement_locally(
        user_id="a", requirement=requirement, evidence=records
    )
    assert result.support_level == "partial"
    assert "ev_2" not in result.evidence_ids


def test_shared_proficiency_and_language_wrapper_keep_meaning():
    kwargs = {"items": ["Python", "Java"], "relation": "any_of"}
    assert (
        match(
            "熟悉 Python 或 Java 中至少一种语言", "精通 Python", **kwargs
        ).support_level
        == "supported"
    )
    assert (
        match(
            "熟悉 Python 和 Java", "精通 Python，Java 基础", items=["Python", "Java"]
        ).support_level
        != "supported"
    )


def test_independent_all_of_conditions_can_use_distinct_records():
    requirement = JobRequirement(
        category="required_skill",
        name="Python 和 Java",
        description="熟悉 Python 和 Java",
        items=["Python", "Java"],
    )
    records = [
        EvidenceRecord(id=f"ev_{i}", user_id="a", title="技能", claim=claim)
        for i, claim in enumerate(["精通 Python", "熟悉 Java"])
    ]
    result = match_requirement_locally(
        user_id="a", requirement=requirement, evidence=records
    )
    assert result.support_level == "supported"
    assert result.evidence_ids == ["ev_0", "ev_1"]
