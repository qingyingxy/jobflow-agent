from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from src.domain.simplified_workflow import (
    ApplicationBoardStatus,
    ApplicationOutcome,
    ApplicationRecommendation,
    InitialJobSearchProfile,
    ResumeEvidence,
    ResumeSourceLocation,
)
from src.domain.unified_jd import (
    UNIFIED_JD_SCHEMA_VERSION,
    UnifiedJDClause,
    UnifiedJDModelOutput,
    UnifiedJobFacts,
    validate_unified_jd_evidence,
)
from src.services.unified_jd_compiler import compile_unified_skill_fields


def _facts(**updates: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "job_type": None,
        "locations": None,
        "graduation_years": None,
        "education_requirements": None,
        "major_requirements": None,
        "internship_duration_months": None,
        "weekly_days": None,
        "earliest_start_date": None,
        "deadline": None,
        "evidence": [],
    }
    payload.update(updates)
    return payload


def _output(*clauses: dict[str, object]) -> UnifiedJDModelOutput:
    return UnifiedJDModelOutput.model_validate(
        {"facts": _facts(), "clauses": list(clauses)}
    )


def test_unified_model_contract_has_only_facts_and_clauses() -> None:
    schema = UnifiedJDModelOutput.model_json_schema()

    assert UNIFIED_JD_SCHEMA_VERSION == "unified-jd-v1"
    assert set(schema["properties"]) == {"facts", "clauses"}
    assert set(schema["required"]) == {"facts", "clauses"}
    fact_schema = schema["$defs"]["UnifiedJobFacts"]
    assert set(fact_schema["required"]) == {
        "job_type",
        "locations",
        "graduation_years",
        "education_requirements",
        "major_requirements",
        "internship_duration_months",
        "weekly_days",
        "earliest_start_date",
        "deadline",
        "evidence",
    }


def test_populated_fact_requires_evidence_and_null_fact_rejects_evidence() -> None:
    with pytest.raises(ValidationError, match="locations"):
        UnifiedJobFacts.model_validate(_facts(locations=["上海"]))

    with pytest.raises(ValidationError, match="空事实不能携带原文证据"):
        UnifiedJobFacts.model_validate(
            _facts(
                evidence=[
                    {"field": "locations", "source_text": "工作地点：上海"}
                ]
            )
        )

    facts = UnifiedJobFacts.model_validate(
        _facts(
            job_type="campus",
            locations=[" 上海 ", "上海", "深圳"],
            graduation_years=[2027, 2026, 2027],
            evidence=[
                {"field": "job_type", "source_text": "2027届校园招聘"},
                {"field": "locations", "source_text": "上海、深圳"},
                {
                    "field": "graduation_years",
                    "source_text": "面向2026及2027届",
                },
            ],
        )
    )

    assert facts.locations == ["上海", "深圳"]
    assert facts.graduation_years == [2026, 2027]


def test_source_evidence_must_be_an_exact_jd_substring() -> None:
    source = "2027届校园招聘，工作地点：上海。要求熟悉 Python。"
    output = UnifiedJDModelOutput.model_validate(
        {
            "facts": _facts(
                job_type="campus",
                locations=["上海"],
                evidence=[
                    {"field": "job_type", "source_text": "2027届校园招聘"},
                    {"field": "locations", "source_text": "工作地点：上海"},
                ],
            ),
            "clauses": [
                {
                    "category": "skill",
                    "level": "required",
                    "items": ["Python"],
                    "source_text": "要求熟悉 Python",
                }
            ],
        }
    )

    validate_unified_jd_evidence(output, source)
    invalid = output.model_copy(deep=True)
    invalid.clauses[0].source_text = "熟练掌握 Python"
    with pytest.raises(ValueError, match=r"clauses\[0\]"):
        validate_unified_jd_evidence(invalid, source)


def test_any_of_requires_group_and_supports_open_groups_at_any_level() -> None:
    with pytest.raises(ValidationError, match="group_name"):
        UnifiedJDClause.model_validate(
            {
                "category": "skill",
                "level": "required",
                "relation": "any_of",
                "items": ["Python", "Go"],
                "source_text": "熟悉 Python 或 Go",
            }
        )

    preferred = UnifiedJDClause.model_validate(
        {
            "category": "skill",
            "level": "preferred",
            "relation": "any_of",
            "items": ["PyTorch", "TensorFlow"],
            "group_name": "深度学习框架",
            "allow_other": True,
            "source_text": "熟悉 PyTorch、TensorFlow 等框架者优先",
        }
    )

    assert preferred.relation == "any_of"
    assert preferred.allow_other is True


def test_all_of_rejects_group_metadata() -> None:
    with pytest.raises(ValidationError, match="group_name"):
        UnifiedJDClause.model_validate(
            {
                "category": "skill",
                "level": "required",
                "items": ["Python"],
                "group_name": "编程语言",
                "source_text": "熟悉 Python",
            }
        )
    with pytest.raises(ValidationError, match="allow_other"):
        UnifiedJDClause.model_validate(
            {
                "category": "skill",
                "level": "required",
                "items": ["Python"],
                "allow_other": True,
                "source_text": "熟悉 Python",
            }
        )


def test_experience_qualifier_stays_scoped_to_one_clause() -> None:
    clause = UnifiedJDClause.model_validate(
        {
            "category": "experience",
            "level": "preferred",
            "items": ["大模型应用开发"],
            "qualifier": {
                "experience_type": "project",
                "minimum_months": 6,
                "domain": "生成式 AI",
            },
            "source_text": "有半年以上生成式 AI 项目经验者优先",
        }
    )

    assert clause.qualifier is not None
    assert clause.qualifier.experience_type == "project"
    assert clause.qualifier.minimum_months == 6
    assert clause.qualifier.domain == "生成式 AI"

    with pytest.raises(ValidationError):
        UnifiedJDClause.model_validate(
            {
                "category": "experience",
                "level": "required",
                "items": ["Python"],
                "qualifier": {
                    "experience_type": "employment",
                    "minimum_months": 0,
                },
                "source_text": "需要 Python 工作经验",
            }
        )


def test_compiler_preserves_required_preferred_mention_and_examples() -> None:
    output = _output(
        {
            "category": "skill",
            "level": "required",
            "items": ["Python"],
            "source_text": "熟练掌握 Python",
        },
        {
            "category": "skill",
            "level": "preferred",
            "items": ["PyTorch"],
            "source_text": "熟悉 PyTorch 者优先",
        },
        {
            "category": "responsibility",
            "level": "mention",
            "items": ["RAG"],
            "examples": ["向量检索"],
            "source_text": "负责 RAG 与向量检索研发",
        },
    )

    compiled = compile_unified_skill_fields(output)

    assert compiled.required_skills == ["Python"]
    assert compiled.preferred_skills == ["PyTorch"]
    assert compiled.skill_mentions == ["RAG", "向量检索"]
    assert compiled.required_skill_groups == []


def test_required_any_of_compiles_to_group_instead_of_required_items() -> None:
    output = _output(
        {
            "category": "skill",
            "level": "required",
            "relation": "any_of",
            "items": ["Python", "Go"],
            "group_name": "编程语言",
            "allow_other": False,
            "source_text": "熟悉 Python 或 Go 中至少一种",
        }
    )

    compiled = compile_unified_skill_fields(output)

    assert compiled.required_skills == []
    assert [group.model_dump() for group in compiled.required_skill_groups] == [
        {"name": "编程语言", "any_of": ["Python", "Go"], "allow_other": False}
    ]
    assert compiled.as_legacy_fields() == {
        "required_skills": None,
        "required_skill_groups": [
            {
                "name": "编程语言",
                "any_of": ["Python", "Go"],
                "allow_other": False,
            }
        ],
        "preferred_skills": None,
        "skill_mentions": None,
    }


def test_preferred_any_of_keeps_clause_logic_but_flattens_legacy_view() -> None:
    output = _output(
        {
            "category": "skill",
            "level": "preferred",
            "relation": "any_of",
            "items": ["PyTorch", "TensorFlow"],
            "group_name": "深度学习框架",
            "allow_other": True,
            "source_text": "熟悉 PyTorch、TensorFlow 等框架者优先",
        }
    )

    compiled = compile_unified_skill_fields(output)

    assert output.clauses[0].relation == "any_of"
    assert output.clauses[0].allow_other is True
    assert compiled.preferred_skills == ["PyTorch", "TensorFlow"]


def test_compiler_does_not_turn_preferred_major_into_required_skill() -> None:
    output = UnifiedJDModelOutput.model_validate(
        {
            "facts": _facts(
                major_requirements=["计算机相关专业"],
                evidence=[
                    {
                        "field": "major_requirements",
                        "source_text": "计算机相关专业优先",
                    }
                ],
            ),
            "clauses": [
                {
                    "category": "fact",
                    "fact_field": "major_requirements",
                    "level": "preferred",
                    "items": ["计算机相关专业"],
                    "source_text": "计算机相关专业优先",
                }
            ],
        }
    )

    compiled = compile_unified_skill_fields(output)

    assert compiled.as_legacy_fields() == {
        "required_skills": None,
        "required_skill_groups": None,
        "preferred_skills": None,
        "skill_mentions": None,
    }


def test_fact_clause_requires_a_populated_fact_and_non_fact_rejects_fact_field() -> None:
    with pytest.raises(ValidationError, match="fact_field"):
        UnifiedJDClause.model_validate(
            {
                "category": "fact",
                "level": "preferred",
                "items": ["计算机相关专业"],
                "source_text": "计算机相关专业优先",
            }
        )
    with pytest.raises(ValidationError, match="只能用于 fact clause"):
        UnifiedJDClause.model_validate(
            {
                "category": "skill",
                "fact_field": "major_requirements",
                "level": "preferred",
                "items": ["Python"],
                "source_text": "熟悉 Python 者优先",
            }
        )
    with pytest.raises(ValidationError, match="引用了空事实"):
        _output(
            {
                "category": "fact",
                "fact_field": "weekly_days",
                "level": "required",
                "items": ["4"],
                "source_text": "每周到岗4天",
            }
        )


def test_compiler_applies_strength_precedence_without_duplicate_fields() -> None:
    output = _output(
        {
            "category": "skill",
            "level": "mention",
            "items": ["Python", "RAG"],
            "source_text": "使用 Python 开发 RAG 服务",
        },
        {
            "category": "skill",
            "level": "preferred",
            "items": ["RAG"],
            "source_text": "熟悉 RAG 者优先",
        },
        {
            "category": "skill",
            "level": "required",
            "items": ["Python"],
            "source_text": "熟练掌握 Python",
        },
    )

    compiled = compile_unified_skill_fields(output)

    assert compiled.required_skills == ["Python"]
    assert compiled.preferred_skills == ["RAG"]
    assert compiled.skill_mentions == []


def test_simplified_workflow_contracts_are_frozen() -> None:
    profile = InitialJobSearchProfile(
        target_direction="大模型算法",
        target_cities=["上海", "杭州", "上海"],
        accepts_remote=True,
        graduation_year=2027,
        target_job_type="campus",
    )
    evidence = ResumeEvidence(
        evidence_id="evidence_project_1",
        resume_version_id="resume_v1",
        experience_type="project",
        title="RAG 检索项目",
        organization="课程项目",
        date_text="2025.03-2025.06",
        source_text="实现混合检索与重排，将 Recall@5 提升至 92%。",
        skills=["RAG", "RAG", "向量检索"],
        location=ResumeSourceLocation(page_number=1, start_char=10, end_char=34),
    )

    assert profile.target_cities == ["上海", "杭州"]
    assert evidence.skills == ["RAG", "向量检索"]
    assert ApplicationRecommendation.RECOMMENDED.value == "recommended_application"
    assert ApplicationBoardStatus.TO_DECIDE.value == "to_decide"
    assert ApplicationOutcome.OFFERED.value == "offered"

    with pytest.raises(ValidationError):
        InitialJobSearchProfile(
            target_direction="算法",
            target_cities=["北京", "上海", "深圳", "杭州"],
            graduation_year=2027,
            target_job_type="campus",
        )
    with pytest.raises(ValidationError, match="必须同时提供"):
        ResumeSourceLocation(start_char=3)


def test_dates_use_iso_schema_values() -> None:
    facts = UnifiedJobFacts.model_validate(
        _facts(
            earliest_start_date="2026-10-01",
            deadline="2026-09-30",
            evidence=[
                {
                    "field": "earliest_start_date",
                    "source_text": "最早到岗时间为2026年10月1日",
                },
                {
                    "field": "deadline",
                    "source_text": "申请截止日期为2026年9月30日",
                },
            ],
        )
    )

    assert facts.earliest_start_date == date(2026, 10, 1)
    assert facts.deadline == date(2026, 9, 30)
