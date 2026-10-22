"""An unknown education relation must not hide an independently proven floor."""

import pytest

from src.domain.education import EducationCondition
from src.domain.eligibility import CandidateProfileInput
from src.services.education_evaluator import evaluate_education


def uncertain(source, *, level="doctor", quote="博士", scope="application"):
    return EducationCondition(
        relation="uncertain",
        branches=[
            {
                "source_text": source,
                "degree": {"operator": "eq", "level": level, "source_text": quote},
                "major": {"mode": "not_specified"},
                "scope": scope,
                "scope_source_text": source if scope != "unknown" else None,
                "status": "unknown",
                "unresolved": True,
            }
        ],
    )


def profile(*levels, complete=True):
    return CandidateProfileInput(
        education_history_complete=complete,
        educations=[
            {"level": level, "source_text": f"已确认教育经历：{level}"}
            for level in levels
        ],
    )


@pytest.mark.parametrize(
    ("source", "level", "quote", "candidate"),
    [
        ("博士学历，在读或已毕业均可", "doctor", "博士", "master"),
        ("硕士学历，在读或已毕业均可", "master", "硕士", "bachelor"),
        ("本科及以上学历，毕业时间需确认", "bachelor", "本科", "associate"),
        (
            "Individuals who are completing or have recently completed a PhD degree",
            "doctor",
            "PhD degree",
            "master",
        ),
        (
            "Individuals who are completing or recently completed a PhD",
            "doctor",
            "PhD",
            "master",
        ),
        (
            "Individuals who are completing or have recently completed a Master's degree",
            "master",
            "Master's degree",
            "bachelor",
        ),
    ],
)
def test_below_explicit_floor_fails_even_if_status_and_relation_are_unknown(
    source, level, quote, candidate
):
    result = evaluate_education(
        uncertain(source, level=level, quote=quote), profile(candidate)
    )
    assert result.result == "fail"
    assert "共同最低学历" in result.reason
    assert result.evidence[0].level == candidate


@pytest.mark.parametrize(
    "candidate",
    [
        profile("master", complete=False),
        profile("master", "unknown"),
        profile("master", "doctor"),
        profile("doctor"),
        profile(complete=False),
    ],
)
def test_missing_or_sufficient_degree_does_not_turn_uncertainty_into_a_decision(
    candidate,
):
    result = evaluate_education(uncertain("要求博士学历，其他限定待确认"), candidate)
    assert result.result == "unknown"


@pytest.mark.parametrize(
    "source",
    [
        "博士学历或同等研究经验",
        "博士学历或有三年研究经验",
        "博士学历或发表过高水平论文",
        "博士学历或在竞赛中获奖",
        "博士学历优先",
        "博士学历要求对优秀者可放宽",
        "不要求博士学历",
        "学历不限，博士学历优先",
        "不限制学历，博士可以报名",
        "PhD or equivalent practical experience",
        "PhD or a proven track record in research",
        "PhD preferred",
        "PhD not required",
        "PhD unnecessary",
        "PhD or exceptional candidates",
        "Candidates without a PhD can apply",
    ],
)
def test_alternative_qualification_or_relaxation_keeps_unknown(source):
    english = "PhD" in source
    result = evaluate_education(
        uncertain(source, quote="PhD" if english else "博士"), profile("master")
    )
    assert result.result == "unknown"


def test_unparsed_lower_degree_in_shared_source_cannot_be_silently_excluded():
    condition = uncertain("本科或硕士，具体条件待确认", level="master", quote="硕士")
    assert evaluate_education(condition, profile("bachelor")).result == "unknown"
    assert evaluate_education(condition, profile("associate")).result == "fail"


def test_unknown_scope_and_unknown_degree_path_cannot_prove_a_floor():
    condition = uncertain("要求博士学历", scope="unknown")
    assert evaluate_education(condition, profile("master")).result == "unknown"
    condition = uncertain("博士或其他资格")
    payload = condition.model_dump()
    branch = {
        **payload["branches"][0],
        "degree": {"operator": "unknown", "source_text": "其他资格"},
        "scope": "unknown",
        "scope_source_text": None,
    }
    payload["branches"].append(branch)
    condition = EducationCondition.model_validate(payload)
    assert evaluate_education(condition, profile("master")).result == "unknown"


def test_known_flexible_masters_path_still_passes():
    condition = EducationCondition.model_validate(
        {
            "relation": "any_of",
            "branches": [
                {
                    "source_text": "本科要求计算机相关专业",
                    "degree": {
                        "operator": "eq",
                        "level": "bachelor",
                        "source_text": "本科",
                    },
                    "major": {
                        "mode": "related",
                        "values": ["计算机"],
                        "source_text": "计算机相关专业",
                    },
                    "scope": "application",
                    "scope_source_text": "本科要求计算机相关专业，硕士不限专业",
                },
                {
                    "source_text": "硕士不限专业",
                    "degree": {
                        "operator": "eq",
                        "level": "master",
                        "source_text": "硕士",
                    },
                    "major": {"mode": "any", "source_text": "不限专业"},
                    "scope": "application",
                    "scope_source_text": "本科要求计算机相关专业，硕士不限专业",
                },
            ],
        }
    )
    candidate = CandidateProfileInput(
        education_history_complete=True,
        educations=[
            {"level": "bachelor", "major_raw": "机械", "source_text": "本科机械"},
            {"level": "master", "major_raw": "金融", "source_text": "硕士金融"},
        ],
    )
    assert evaluate_education(condition, candidate).result == "pass"
