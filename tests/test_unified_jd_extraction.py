from __future__ import annotations

from src.domain.unified_jd import (
    UnifiedJDModelOutput,
    validate_unified_fact_clause_granularity,
    validate_unified_jd_evidence,
)
from src.services.unified_jd_extraction import (
    compile_unified_extraction_v2,
    extract_unified_jd_evidence_lines,
    split_unified_jd_sections,
)

SECTIONED_JD = """职位信息
工作地点：北京
岗位职责
1. 负责推荐模型开发
任职要求
1. 2027届本科及以上学历
2. 熟悉 Python 或 Go 中至少一种"""


def test_section_splitter_preserves_exact_spans_and_heading_context() -> None:
    sections = split_unified_jd_sections(SECTIONED_JD)

    assert [item.kind for item in sections] == [
        "metadata",
        "metadata",
        "responsibilities",
        "responsibilities",
        "requirements",
        "requirements",
        "requirements",
    ]
    assert sections[3].source_text == "1. 负责推荐模型开发"
    for section in sections:
        assert (
            SECTIONED_JD[section.start_char : section.end_char] == section.source_text
        )


def test_one_line_jd_is_not_misclassified_by_an_inline_metadata_label() -> None:
    source = "算法实习生，工作地点：上海。负责推荐系统研发，要求熟悉 Python。"

    sections = split_unified_jd_sections(source)

    assert len(sections) == 1
    assert sections[0].kind == "unknown"


def test_evidence_lines_preserve_exact_offsets_and_heading_context() -> None:
    lines = extract_unified_jd_evidence_lines(SECTIONED_JD)

    assert [(item.kind, item.source_text) for item in lines] == [
        ("metadata", "工作地点：北京"),
        ("responsibilities", "负责推荐模型开发"),
        ("requirements", "2027届本科及以上学历"),
        ("requirements", "熟悉 Python 或 Go 中至少一种"),
    ]
    for line in lines:
        assert SECTIONED_JD[line.start_char : line.end_char] == line.source_text


def test_evidence_lines_handle_inline_headings_and_numbered_items() -> None:
    source = (
        "职位描述：1. 分析需求；2. 设计方案。任职要求：1. 熟悉 Python；2. 有项目经验。"
    )

    lines = extract_unified_jd_evidence_lines(source)

    assert [(item.kind, item.source_text) for item in lines] == [
        ("responsibilities", "分析需求"),
        ("responsibilities", "设计方案"),
        ("requirements", "熟悉 Python"),
        ("requirements", "有项目经验"),
    ]


def test_evidence_lines_keep_title_hyphens_and_mark_preferred_section() -> None:
    source = (
        "岗位名称：大模型算法工程师 - 智能体方向\n"
        "任职要求\n"
        "1. 熟悉 Python\n"
        "加分项\n"
        "1. 有 RAG 项目经验"
    )

    lines = extract_unified_jd_evidence_lines(source)

    assert lines[0].source_text == "岗位名称：大模型算法工程师 - 智能体方向"
    assert [item.source_text for item in lines[1:]] == [
        "熟悉 Python",
        "有 RAG 项目经验",
    ]
    assert [item.level_hint for item in lines[1:]] == [None, "preferred"]


def test_evidence_lines_split_clear_requirement_category_changes_only() -> None:
    source = (
        "任职要求\n"
        "1. 编程基础扎实，熟悉至少一种主流语言\n"
        "2. 熟练掌握Python，有PyTorch使用经验\n"
        "3. 有大型项目参与经验，具备项目落地能力者优先\n"
        "4. 具备良好的用户洞察能力，能够将问题转化为产品方案\n"
        "5. 掌握常用统计模型，能独立进行数据分析"
    )

    lines = extract_unified_jd_evidence_lines(source)

    assert [item.source_text for item in lines] == [
        "编程基础扎实",
        "熟悉至少一种主流语言",
        "熟练掌握Python",
        "有PyTorch使用经验",
        "有大型项目参与经验",
        "具备项目落地能力者优先",
        "具备良好的用户洞察能力，能够将问题转化为产品方案",
        "掌握常用统计模型",
        "能独立进行数据分析",
    ]


def test_evidence_lines_split_only_multi_action_responsibilities() -> None:
    source = (
        "岗位职责\n"
        "1. 识别重复工作，设计自动化方案，协同工程团队落地\n"
        "2. 结合前沿技术，推动模型能力突破\n"
        "3. 负责需求分析，协同研发推动功能落地"
    )

    lines = extract_unified_jd_evidence_lines(source)

    assert [item.source_text for item in lines] == [
        "识别重复工作",
        "设计自动化方案",
        "协同工程团队落地",
        "结合前沿技术，推动模型能力突破",
        "负责需求分析，协同研发推动功能落地",
    ]


def test_evidence_lines_do_not_treat_intro_or_subheadings_as_duties() -> None:
    source = (
        "职位描述\n"
        "职位简介：\n"
        "我们具备完整技术栈。\n"
        "工作职责\n"
        "1. AI赋能与流程再造：\n"
        "- 负责模型研发"
    )

    lines = extract_unified_jd_evidence_lines(source)

    assert [(item.kind, item.source_text) for item in lines] == [
        ("unknown", "我们具备完整技术栈"),
        ("responsibilities", "负责模型研发"),
    ]


def test_compiler_builds_typed_facts_and_string_fact_clauses() -> None:
    raw_output = {
        "fact_mentions": [
            {
                "field": "graduation_years",
                "raw_items": ["2027届"],
                "level": "required",
                "source_text": "2027届本科及以上学历",
            },
            {
                "field": "education_requirements",
                "raw_items": ["本科及以上学历"],
                "level": "required",
                "source_text": "2027届本科及以上学历",
            },
        ],
        "clauses": [],
    }

    compiled = compile_unified_extraction_v2(raw_output, SECTIONED_JD)

    assert compiled.output.facts.graduation_years == [2027]
    assert compiled.output.facts.education_requirements == ["本科及以上学历"]
    year_clause = next(
        clause
        for clause in compiled.output.clauses
        if clause.fact_field == "graduation_years"
    )
    assert year_clause.items == ["2027届"]
    assert isinstance(year_clause.items[0], str)
    UnifiedJDModelOutput.model_validate(compiled.output.model_dump(mode="json"))
    validate_unified_fact_clause_granularity(compiled.output)
    validate_unified_jd_evidence(compiled.output, SECTIONED_JD)


def test_compiler_restores_graduation_clause_text_from_source() -> None:
    raw_output = {
        "fact_mentions": [
            {
                "field": "graduation_years",
                "raw_items": [2027],
                "level": "required",
                "source_text": "2027届本科及以上学历",
            }
        ],
        "clauses": [],
    }

    compiled = compile_unified_extraction_v2(raw_output, SECTIONED_JD)

    assert compiled.output.facts.graduation_years == [2027]
    assert compiled.output.clauses[0].items == ["2027届"]
    assert compiled.diagnostics[0].code == "recovered_fact_item_text"


def test_compiler_preserves_full_graduation_atom_from_model() -> None:
    source = "面向计算机相关专业2027届应届毕业生，要求熟悉 Python。"
    raw_output = {
        "fact_mentions": [
            {
                "field": "graduation_years",
                "raw_items": ["2027届应届毕业生"],
                "level": "required",
                "source_text": "计算机相关专业2027届应届毕业生",
            }
        ],
        "clauses": [],
    }

    compiled = compile_unified_extraction_v2(raw_output, source)

    assert compiled.output.facts.graduation_years == [2027]
    assert compiled.output.clauses[0].items == ["2027届应届毕业生"]


def test_compiler_treats_open_major_list_as_alternatives() -> None:
    source = "计算机、人工智能、数学、统计学等相关专业优先。"
    raw_output = {
        "fact_mentions": [
            {
                "field": "major_requirements",
                "raw_items": ["计算机", "人工智能", "数学", "统计学", "相关专业"],
                "level": "preferred",
                "source_text": "计算机、人工智能、数学、统计学等相关专业优先",
            }
        ],
        "clauses": [],
    }

    compiled = compile_unified_extraction_v2(raw_output, source)

    clause = compiled.output.clauses[0]
    assert clause.relation == "any_of"
    assert clause.group_name == "专业范围"
    assert clause.allow_other is True


def test_compiler_atomizes_combined_major_text_and_adds_open_scope() -> None:
    source = "任职要求\n1. 计算机、人工智能或相关专业的2027届应届毕业生"
    raw_output = {
        "fact_mentions": [
            {
                "field": "major_requirements",
                "raw_items": ["计算机、人工智能或相关专业"],
                "level": None,
                "source_text": "计算机、人工智能或相关专业",
            }
        ],
        "clauses": [],
    }

    compiled = compile_unified_extraction_v2(raw_output, source)

    assert compiled.output.facts.major_requirements == [
        "计算机",
        "人工智能",
        "相关专业",
    ]
    assert compiled.output.clauses[0].level == "required"
    assert compiled.output.clauses[0].relation == "any_of"


def test_compiler_normalizes_deterministic_fact_surface_forms() -> None:
    source = (
        "岗位名称：数据科学家-2027届\n"
        "工作地点：北京市\n"
        "任职要求\n"
        "1. 国内外著名高校硕士及以上学历，数据科学等相关专业优先。"
    )
    raw_output = {
        "fact_mentions": [
            {
                "field": "locations",
                "raw_items": ["北京市"],
                "level": None,
                "source_text": "工作地点：北京市",
            },
            {
                "field": "education_requirements",
                "raw_items": ["硕士及以上学历"],
                "level": "required",
                "source_text": (
                    "1. 国内外著名高校硕士及以上学历，数据科学等相关专业优先。"
                ),
            },
        ],
        "clauses": [],
    }

    compiled = compile_unified_extraction_v2(raw_output, source)

    assert compiled.output.facts.locations == ["北京"]
    assert compiled.output.facts.education_requirements == [
        "国内外著名高校硕士及以上学历"
    ]
    assert compiled.output.facts.graduation_years == [2027]
    assert any(item.code == "locally_backfilled_fact" for item in compiled.diagnostics)


def test_compiler_backfills_year_from_labeled_campus_project() -> None:
    source = (
        "岗位名称：算法工程师\n"
        "招聘项目：DJI 大疆2027“拓疆者”校园招聘\n"
        "任职要求\n硕士及以上学历"
    )

    compiled = compile_unified_extraction_v2(
        {"fact_mentions": [], "clauses": []},
        source,
    )

    assert compiled.output.facts.graduation_years == [2027]
    assert compiled.output.facts.evidence[0].source_text == (
        "招聘项目：DJI 大疆2027“拓疆者”校园招聘"
    )


def test_compiler_recovers_legacy_any_of_array() -> None:
    source = "至少一项有深入实践：VLA模型、端到端自动驾驶、机器人策略学习。"
    raw_output = {
        "fact_mentions": [],
        "clauses": [
            {
                "category": "experience",
                "level": "required",
                "items": ["至少一项有深入实践"],
                "any_of": ["VLA模型", "端到端自动驾驶", "机器人策略学习"],
                "group_name": "深入实践方向",
                "source_text": source,
            }
        ],
    }

    compiled = compile_unified_extraction_v2(raw_output, source)

    assert compiled.output.clauses[0].relation == "any_of"
    assert compiled.output.clauses[0].items == [
        "VLA模型",
        "端到端自动驾驶",
        "机器人策略学习",
    ]
    assert compiled.diagnostics[0].code == "recovered_clause_shape"


def test_compiler_recovers_boolean_relation_fields() -> None:
    source = "熟悉 Python；有 RAG 或 Agent 项目经验"
    raw_output = {
        "fact_mentions": [],
        "clauses": [
            {
                "category": "skill",
                "level": "required",
                "items": ["Python"],
                "all_of": True,
                "source_text": "熟悉 Python",
            },
            {
                "category": "experience",
                "level": "required",
                "items": ["RAG", "Agent"],
                "all_of": False,
                "any_of": True,
                "group_name": "项目经验",
                "source_text": "有 RAG 或 Agent 项目经验",
            },
        ],
    }

    compiled = compile_unified_extraction_v2(raw_output, source)

    assert [clause.relation for clause in compiled.output.clauses] == [
        "all_of",
        "any_of",
    ]
    assert [item.code for item in compiled.diagnostics] == [
        "recovered_clause_shape",
        "recovered_clause_shape",
    ]


def test_compiler_recovers_known_string_experience_qualifier() -> None:
    source = "有 AI 产品项目经验"
    raw_output = {
        "fact_mentions": [],
        "clauses": [
            {
                "category": "experience",
                "level": "preferred",
                "items": ["AI 产品"],
                "all_of": True,
                "qualifier": "项目经验",
                "source_text": source,
            }
        ],
    }

    compiled = compile_unified_extraction_v2(raw_output, source)

    assert compiled.output.clauses[0].qualifier is not None
    assert compiled.output.clauses[0].qualifier.experience_type == "project"
    assert compiled.diagnostics[0].code == "recovered_clause_shape"


def test_compiler_drops_ambiguous_string_qualifier_without_dropping_clause() -> None:
    source = "真实机器人环境上的端到端策略实战经验"
    raw_output = {
        "fact_mentions": [],
        "clauses": [
            {
                "category": "experience",
                "level": "preferred",
                "items": ["端到端策略实战经验"],
                "all_of": True,
                "qualifier": "真实机器人环境上的端到端策略实战经验",
                "source_text": source,
            }
        ],
    }

    compiled = compile_unified_extraction_v2(raw_output, source)

    assert len(compiled.output.clauses) == 1
    assert compiled.output.clauses[0].qualifier is None
    assert "字符串 qualifier 已舍弃" in compiled.diagnostics[0].message


def test_compiler_recovers_practical_experience_type_alias() -> None:
    source = "使用过多种 AI 工具"
    raw_output = {
        "fact_mentions": [],
        "clauses": [
            {
                "category": "experience",
                "level": "preferred",
                "items": ["AI 工具"],
                "relation": "all_of",
                "qualifier": {
                    "experience_type": "tool_usage",
                    "minimum_months": None,
                    "domain": "AI 工具",
                },
                "source_text": source,
            }
        ],
    }

    compiled = compile_unified_extraction_v2(raw_output, source)

    assert compiled.output.clauses[0].qualifier is not None
    assert compiled.output.clauses[0].qualifier.experience_type == "practical"
    assert "experience_type 别名" in compiled.diagnostics[0].message


def test_compiler_does_not_turn_neutral_metadata_into_required_clause() -> None:
    source = "工作地点：北京，岗位详情尚未公布，请关注后续官方更新。"
    raw_output = {
        "fact_mentions": [
            {
                "field": "locations",
                "raw_items": ["北京"],
                "level": "required",
                "source_text": "工作地点：北京",
            }
        ],
        "clauses": [],
    }

    compiled = compile_unified_extraction_v2(raw_output, source)

    assert compiled.output.facts.locations == ["北京"]
    assert not compiled.output.clauses
    assert [item.code for item in compiled.diagnostics] == [
        "implicit_metadata_level_dropped"
    ]


def test_compiler_reports_uncovered_semantic_evidence_lines() -> None:
    compiled = compile_unified_extraction_v2(
        {"fact_mentions": [], "clauses": []},
        SECTIONED_JD,
    )

    uncovered = [
        item for item in compiled.diagnostics if item.code.startswith("uncovered")
    ]
    assert [(item.code, item.path) for item in uncovered] == [
        ("uncovered_responsibility_evidence_line", "evidence_lines[1]"),
        ("uncovered_requirement_evidence_line", "evidence_lines[3]"),
    ]


def test_compiler_keeps_valid_duties_when_one_clause_is_invalid() -> None:
    raw_output = {
        "fact_mentions": [],
        "clauses": [
            {
                "category": "responsibility",
                "level": "required",
                "items": ["推荐模型开发"],
                "source_text": "负责推荐模型开发",
            },
            {
                "category": "skill",
                "level": "required",
                "relation": "any_of",
                "items": ["Python"],
                "group_name": "编程语言",
                "source_text": "熟悉 Python 或 Go 中至少一种",
            },
            {
                "category": "skill",
                "level": "required",
                "items": ["Rust"],
                "source_text": "不存在于正文的证据",
            },
            {
                "category": "fact",
                "level": "required",
                "items": ["非法类别"],
                "source_text": "任职要求",
            },
        ],
    }

    compiled = compile_unified_extraction_v2(raw_output, SECTIONED_JD)

    semantic_clauses = [
        clause for clause in compiled.output.clauses if clause.category != "fact"
    ]
    assert [clause.category for clause in semantic_clauses] == [
        "responsibility",
        "skill",
    ]
    assert semantic_clauses[0].level == "mention"
    assert semantic_clauses[1].relation == "all_of"
    assert [item.code for item in compiled.diagnostics] == [
        "recovered_clause_shape",
        "unsupported_evidence",
        "invalid_clause",
        "locally_backfilled_fact",
    ]


def test_compiler_isolates_bad_fact_evidence_without_losing_valid_facts() -> None:
    raw_output = {
        "fact_mentions": [
            {
                "field": "locations",
                "raw_items": ["北京"],
                "level": None,
                "source_text": "工作地点：北京",
            },
            {
                "field": "weekly_days",
                "raw_items": ["4天"],
                "level": "required",
                "source_text": "每周到岗四天",
            },
        ],
        "clauses": [],
    }

    compiled = compile_unified_extraction_v2(raw_output, SECTIONED_JD)

    assert compiled.output.facts.locations == ["北京"]
    assert compiled.output.facts.weekly_days is None
    assert compiled.diagnostics[0].code == "unsupported_evidence"
    assert compiled.diagnostics[0].path == "fact_mentions[1].source_text"
