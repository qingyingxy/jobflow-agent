from __future__ import annotations

import pytest

from src.domain.core_skill_semantics import CoreSkillClause
from src.domain.job import RawJobDocument
from src.infrastructure.llm_client import FakeModelClient
from src.services.core_jd_parser import (
    CORE_MAX_OUTPUT_TOKENS,
    DEFAULT_CORE_PARSER_VERSION,
    DEFAULT_CORE_PROMPT_VERSION,
    CoreJDParser,
    index_source_clauses,
)
from src.services.jd_parser import JDParserError

CORE_RAW = (
    "示例公司 2027 校园招聘，岗位工作地点为深圳市。"
    "任职要求：熟悉 Python、RAG 和 Agent，具备良好的沟通能力。"
)


@pytest.mark.asyncio
async def test_core_parser_keeps_contract_small_and_builds_local_evidence() -> None:
    client = FakeModelClient(
        output={
            "job_type": "campus",
            "locations": ["深圳"],
            "required_skills": ["Python", "RAG", "Agent"],
            "unexpected_detail": "should be ignored by the core adapter",
        }
    )
    parser = CoreJDParser(client, validation_retries=0)

    result = await parser.parse(RawJobDocument(raw_content=CORE_RAW))

    assert result.fields.model_dump(exclude={"skill_concepts"}) == {
        "job_type": "campus",
        "locations": ["深圳"],
        "required_skills": ["Python", "RAG", "Agent"],
        "required_skill_groups": None,
        "preferred_skills": None,
        "skill_mentions": None,
    }
    assert [
        (item.skill_id, item.canonical_name, item.strength)
        for item in result.fields.skill_concepts or []
    ] == [
        ("skill:python", "Python", "required"),
        ("skill:rag", "RAG", "required"),
        ("skill:agent", "Agent", "required"),
    ]
    assert result.field_evidence
    assert all(item.source_text in CORE_RAW for item in result.field_evidence)
    assert {item.field_path for item in result.field_evidence} == {
        "job_type",
        "locations[0]",
        "required_skills[0]",
        "required_skills[1]",
        "required_skills[2]",
    }

    assert client.last_request is not None
    assert client.last_request.schema_name == "core_job_fields"
    assert "qualification_conditions" not in client.last_request.messages[0].content
    assert "requirements" not in client.last_request.messages[0].content
    assert "clauses" in client.last_request.json_schema["properties"]
    assert "skill_mentions" not in client.last_request.json_schema["properties"]
    assert "required_skill_groups" not in client.last_request.json_schema["properties"]
    clause_schema = client.last_request.json_schema["$defs"][
        "CompactIndexedCoreSkillClause"
    ]
    assert clause_schema["properties"]["skills"]["type"] == "array"
    assert clause_schema["properties"]["examples"]["anyOf"][0]["type"] == "array"
    assert clause_schema["properties"]["relation"]["enum"] == ["all_of", "any_of"]
    assert clause_schema["properties"]["level"]["enum"] == [
        "required",
        "preferred",
        "mention",
    ]
    assert clause_schema["properties"]["qualifier"]["anyOf"][0]["enum"] == [
        "project_experience",
        "internship_experience",
        "research_experience",
        "development_experience",
        "practical_experience",
        "open_source_experience",
    ]
    assert "any_of" not in clause_schema["properties"]
    assert "优先、加分" in client.last_request.messages[0].content
    assert "最小语义范围" in client.last_request.messages[0].content
    assert "id" in clause_schema["properties"]
    assert "source_text" not in clause_schema["properties"]
    assert "id 是 SC 编号" in client.last_request.messages[0].content
    assert '"id":"SC001","level":"required"' in (
        client.last_request.messages[0].content
    )
    assert "为 mention" in client.last_request.messages[0].content
    assert "relation=all_of" in client.last_request.messages[0].content
    assert "relation=any_of" in client.last_request.messages[0].content
    assert "共同 group" in client.last_request.messages[0].content
    assert "open 设为 true" in client.last_request.messages[0].content
    assert "group_name" not in client.last_request.messages[0].content
    assert "allow_other" not in client.last_request.messages[0].content
    assert "不要遗漏并列的分析、诊断、优化" in (
        client.last_request.messages[0].content
    )
    assert "project_experience" in client.last_request.messages[0].content
    assert "不生成标准技能名或技能 ID" in client.last_request.messages[0].content
    assert "preferred 和 mention 即使含‘或’也必须使用 all_of" in (
        client.last_request.messages[0].content
    )
    assert "上位方向之间任选时 skills 只放方向名称" in (
        client.last_request.messages[0].content
    )
    assert "不同经验类型拆成不同 clause" in client.last_request.messages[0].content
    assert "列出的具体名称中至少选一" in client.last_request.messages[0].content
    assert len(client.last_request.messages[0].content) < 1800
    assert "examples" in str(client.last_request.json_schema)
    assert "[SC001]" in client.last_request.messages[1].content
    assert "section=requirements" in client.last_request.messages[1].content
    assert client.last_request.max_output_tokens == CORE_MAX_OUTPUT_TOKENS
    assert result.prompt_version == DEFAULT_CORE_PROMPT_VERSION
    assert result.parser_version == DEFAULT_CORE_PARSER_VERSION


@pytest.mark.asyncio
async def test_core_parser_keeps_normalized_model_diagnostics() -> None:
    class DiagnosticClient(FakeModelClient):
        async def generate(self, request):  # type: ignore[no-untyped-def]
            response = await super().generate(request)
            return response.model_copy(
                update={
                    "diagnostics": {
                        "prompt_tokens": 80,
                        "completion_tokens": 12,
                        "reasoning_tokens": 0,
                        "reasoning_content_present": True,
                        "reasoning_content_length": 0,
                        "max_tokens": 4096,
                        "thinking_mode": "disabled",
                    }
                }
            )

    parser = CoreJDParser(
        DiagnosticClient(
                output={
                    "job_type": "campus",
                    "locations": ["深圳"],
                    "required_skills": ["Python"],
                }
        ),
        validation_retries=0,
    )

    result = await parser.parse(RawJobDocument(raw_content=CORE_RAW))

    assert result.model_diagnostics is not None
    assert result.model_diagnostics["prompt_tokens"] == 80
    assert result.model_diagnostics["completion_tokens"] == 12
    assert result.model_diagnostics["reasoning_tokens"] == 0
    assert result.model_diagnostics["reasoning_content_present"] is True
    assert result.model_diagnostics["reasoning_content_length"] == 0
    assert result.model_diagnostics["max_tokens"] == 4096
    assert result.model_diagnostics["thinking_mode"] == "disabled"


@pytest.mark.asyncio
async def test_core_parser_keeps_diagnostics_on_schema_failure() -> None:
    class DiagnosticClient(FakeModelClient):
        async def generate(self, request):  # type: ignore[no-untyped-def]
            response = await super().generate(request)
            return response.model_copy(
                update={
                    "diagnostics": {
                        "prompt_tokens": 80,
                        "completion_tokens": 12,
                        "reasoning_tokens": 0,
                        "reasoning_content_present": False,
                        "reasoning_content_length": 0,
                        "max_tokens": 4096,
                        "thinking_mode": "disabled",
                    }
                }
            )

    parser = CoreJDParser(
        DiagnosticClient(
            output={
                "clauses": [
                    {"id": "SC001", "level": "invalid", "skills": ["Python"]}
                ]
            }
        ),
        validation_retries=0,
    )

    with pytest.raises(JDParserError) as captured:
        await parser.parse(RawJobDocument(raw_content=CORE_RAW))

    diagnostics = captured.value.details["model_diagnostics"]
    assert diagnostics["prompt_tokens"] == 80
    assert diagnostics["completion_tokens"] == 12
    assert diagnostics["reasoning_tokens"] == 0
    assert diagnostics["max_tokens"] == 4096


def test_core_skill_clause_separates_scoped_skills_and_examples() -> None:
    clause = CoreSkillClause(
        source_text="熟悉编程语言，例如 Python",
        strength="required",
        relation="all_of",
        skills=["编程语言"],
        examples=["Python"],
    )

    assert clause.skills == ["编程语言"]
    assert clause.examples == ["Python"]
    assert clause.qualifier is None
    with pytest.raises(ValueError, match="at least two skills"):
        CoreSkillClause(
            source_text="熟悉 Python 或其他语言",
            strength="required",
            relation="any_of",
            skills=["Python"],
        )
    with pytest.raises(ValueError, match="group_name requires any_of relation"):
        CoreSkillClause(
            source_text="熟悉 Python",
            strength="required",
            relation="all_of",
            skills=["Python"],
            group_name="编程语言",
        )
    with pytest.raises(ValueError, match="allow_other requires any_of relation"):
        CoreSkillClause(
            source_text="熟悉 Python",
            strength="required",
            relation="all_of",
            skills=["Python"],
            allow_other=True,
        )
    with pytest.raises(ValueError, match="only valid for required"):
        CoreSkillClause(
            source_text="有 Python 或 Go 经验者优先",
            strength="preferred",
            relation="any_of",
            skills=["Python", "Go"],
            group_name="编程语言",
        )
    for invalid_skills in (None, "Python/Go"):
        with pytest.raises(ValueError):
            CoreSkillClause.model_validate(
                {
                    "source_text": "熟悉 Python/Go 中任一种",
                    "strength": "required",
                    "relation": "any_of",
                    "skills": invalid_skills,
                }
            )


@pytest.mark.asyncio
async def test_core_parser_routes_named_examples_to_mentions() -> None:
    source_text = "熟悉深度学习框架，例如 PyTorch、TensorFlow"
    parser = CoreJDParser(
        FakeModelClient(
            output={
                "skill_clauses": [
                    {
                        "source_text": source_text,
                        "strength": "required",
                        "relation": "all_of",
                        "skills": ["深度学习框架"],
                        "examples": ["PyTorch", "TensorFlow"],
                    }
                ]
            }
        ),
        validation_retries=0,
    )

    result = await parser.parse(RawJobDocument(raw_content=source_text))

    assert result.fields.required_skills == ["深度学习框架"]
    assert result.fields.required_skill_groups is None
    assert result.fields.skill_mentions == ["PyTorch", "TensorFlow"]
    strengths = {
        concept.canonical_name: concept.strength
        for concept in result.fields.skill_concepts or []
    }
    assert strengths == {
        "深度学习框架": "required",
        "PyTorch": "mention",
        "TensorFlow": "mention",
    }


@pytest.mark.asyncio
async def test_core_parser_examples_override_duplicate_scoped_skills() -> None:
    source_text = "任职要求：熟悉深度学习框架，例如 PyTorch 等主流工具"
    parser = CoreJDParser(
        FakeModelClient(
            output={
                "skill_clauses": [
                    {
                        "source_text": source_text,
                        "strength": "required",
                        "relation": "all_of",
                        "skills": ["深度学习框架", "PyTorch"],
                        "examples": ["PyTorch"],
                    }
                ]
            }
        ),
        validation_retries=0,
    )

    result = await parser.parse(RawJobDocument(raw_content=source_text))

    assert result.fields.required_skills == ["深度学习框架"]
    assert result.fields.skill_mentions == ["PyTorch"]


@pytest.mark.asyncio
async def test_core_parser_keeps_experience_as_structured_qualifier() -> None:
    raw_content = (
        "示例公司 2027 校园招聘，工作地点北京。"
        "任职要求：有 VLA 项目经验者优先。"
    )
    parser = CoreJDParser(
        FakeModelClient(
            output={
                "job_type": "campus",
                "locations": ["北京"],
                "skill_clauses": [
                    {
                        "source_text": "有 VLA 项目经验者优先",
                        "strength": "preferred",
                        "relation": "all_of",
                        "skills": ["VLA"],
                        "qualifier": "project_experience",
                    }
                ],
            }
        ),
        validation_retries=0,
    )

    result = await parser.parse(RawJobDocument(raw_content=raw_content))

    assert result.fields.preferred_skills == ["VLA"]
    assert result.fields.skill_concepts is not None
    concept = result.fields.skill_concepts[0]
    assert concept.skill_id == "skill:vla"
    assert concept.canonical_name == "VLA"
    assert concept.strength == "preferred"
    assert concept.qualifier == "project_experience"
    assert concept.source_text == "有 VLA 项目经验者优先"


@pytest.mark.asyncio
async def test_core_parser_preserves_null_when_source_has_no_core_signal() -> None:
    raw_content = "示例公司发布岗位信息，当前页面没有明确的类型、地点或技能要求。"
    parser = CoreJDParser(
        FakeModelClient(
            output={
                "job_type": None,
                "locations": None,
                "required_skills": None,
            }
        ),
        validation_retries=0,
    )

    result = await parser.parse(RawJobDocument(raw_content=raw_content))

    assert result.fields.model_dump(exclude={"skill_concepts"}) == {
        "job_type": None,
        "locations": None,
        "required_skills": None,
        "required_skill_groups": None,
        "preferred_skills": None,
        "skill_mentions": None,
    }
    assert result.fields.skill_concepts is None
    assert result.field_evidence == []


@pytest.mark.asyncio
async def test_core_parser_keeps_any_of_preferred_and_mentions_separate() -> None:
    raw_content = (
        "2027 校园招聘，工作地点上海。任职要求：掌握 Python；"
        "熟悉 Go，或 Java、C++、Rust 中任一种；"
        "至少掌握一种推理框架，如 TensorRT、vLLM 等；"
        "熟悉 CUDA、Triton 者优先；了解 RAG。"
    )
    parser = CoreJDParser(
        FakeModelClient(
            output={
                "job_type": "campus",
                "locations": ["上海"],
                "skill_clauses": [
                    {
                        "source_text": "掌握 Python",
                        "strength": "required",
                        "relation": "all_of",
                        "skills": ["Python"],
                    },
                    {
                        "source_text": "熟悉 Go，或 Java、C++、Rust 中任一种",
                        "strength": "required",
                        "relation": "any_of",
                        "skills": ["Go", "Java", "C++", "Rust"],
                        "group_name": "后端编程语言",
                        "allow_other": False,
                    },
                    {
                        "source_text": "至少掌握一种推理框架，如 TensorRT、vLLM 等",
                        "strength": "required",
                        "relation": "any_of",
                        "skills": ["TensorRT", "vLLM"],
                        "group_name": "大模型推理框架",
                        "allow_other": True,
                    },
                    {
                        "source_text": "熟悉 CUDA、Triton 者优先",
                        "strength": "preferred",
                        "relation": "all_of",
                        "skills": ["CUDA", "Triton"],
                    },
                    {
                        "source_text": "了解 RAG",
                        "strength": "mention",
                        "relation": "all_of",
                        "skills": ["RAG"],
                    },
                ],
            }
        ),
        validation_retries=0,
    )

    result = await parser.parse(RawJobDocument(raw_content=raw_content))

    assert result.fields.required_skills == ["Python"]
    assert [group.model_dump() for group in result.fields.required_skill_groups or []] == [
        {
            "name": "编程语言",
            "any_of": ["Go", "Java", "C++", "Rust"],
            "allow_other": False,
        },
        {
            "name": "推理框架",
            "any_of": ["TensorRT", "vLLM"],
            "allow_other": True,
        },
    ]
    assert result.fields.preferred_skills == ["CUDA", "Triton"]
    assert result.fields.skill_mentions == [
        "RAG",
        "Go",
        "Java",
        "C++",
        "Rust",
        "TensorRT",
        "vLLM",
    ]
    paths = {item.field_path for item in result.field_evidence}
    assert "preferred_skills[1]" in paths
    assert "skill_mentions[0]" in paths
    assert "required_skill_groups[1].any_of[1]" in paths


@pytest.mark.asyncio
async def test_core_parser_keeps_evidence_for_contextual_group_aliases() -> None:
    raw_content = (
        "2027 校园招聘。职位要求：熟悉操作系统、网络或数据库基础。"
    )
    parser = CoreJDParser(
        FakeModelClient(
            output={
                "job_type": "campus",
                "locations": None,
                "skill_clauses": [
                    {
                        "source_text": "熟悉操作系统、网络或数据库基础",
                        "strength": "required",
                        "relation": "any_of",
                        "skills": ["操作系统", "网络", "数据库"],
                        "group_name": "系统基础",
                        "allow_other": False,
                    }
                ],
            }
        ),
        validation_retries=0,
    )

    result = await parser.parse(RawJobDocument(raw_content=raw_content))

    assert result.fields.required_skill_groups is not None
    assert result.fields.required_skill_groups[0].any_of == [
        "操作系统",
        "计算机网络",
        "数据库",
    ]
    assert not result.warnings
    paths = {item.field_path for item in result.field_evidence}
    assert "required_skill_groups[0].any_of[1]" in paths


@pytest.mark.asyncio
async def test_core_parser_preserves_atomic_compound_skill_labels() -> None:
    raw_content = (
        "任职要求：熟悉 AI Coding 工具使用；有 AI Coding 项目者优先。"
    )
    parser = CoreJDParser(
        FakeModelClient(
            output={
                "skill_clauses": [
                    {
                        "source_text": "熟悉 AI Coding 工具使用",
                        "strength": "required",
                        "relation": "all_of",
                        "skills": ["AI Coding工具使用"],
                    },
                    {
                        "source_text": "有 AI Coding 项目者优先",
                        "strength": "preferred",
                        "relation": "all_of",
                        "skills": ["AI Coding项目"],
                    },
                ]
            }
        ),
        validation_retries=0,
    )

    result = await parser.parse(RawJobDocument(raw_content=raw_content))

    assert result.fields.required_skills == ["AI Coding工具使用"]
    assert result.fields.preferred_skills == ["AI Coding项目"]


@pytest.mark.asyncio
async def test_core_parser_collapses_shared_preferred_experience_suffixes() -> None:
    source_text = (
        "有 K8s 调度器、Volcano、Koordinator 相关项目、实习或开源经历优先"
    )
    parser = CoreJDParser(
        FakeModelClient(
            output={
                "skill_clauses": [
                    {
                        "source_text": source_text,
                        "strength": "preferred",
                        "relation": "all_of",
                        "skills": [
                            "K8s调度器项目",
                            "Volcano项目",
                            "Koordinator项目",
                            "K8s调度器实习",
                            "Volcano实习",
                            "Koordinator实习",
                            "K8s调度器开源经历",
                            "Volcano开源经历",
                            "Koordinator开源经历",
                        ],
                    }
                ]
            }
        ),
        validation_retries=0,
    )

    result = await parser.parse(RawJobDocument(raw_content=source_text))

    assert result.fields.preferred_skills == [
        "kube-scheduler",
        "Volcano",
        "Koordinator",
    ]


@pytest.mark.asyncio
async def test_core_parser_preserves_independent_preferred_project_conditions() -> None:
    source_text = "任职要求：有 AI 项目或开源实践者加分，其他条件未作说明"
    parser = CoreJDParser(
        FakeModelClient(
            output={
                "skill_clauses": [
                    {
                        "source_text": source_text,
                        "strength": "preferred",
                        "relation": "all_of",
                        "skills": ["AI项目", "开源实践"],
                    }
                ]
            }
        ),
        validation_retries=0,
    )

    result = await parser.parse(RawJobDocument(raw_content=source_text))

    assert result.fields.preferred_skills == ["AI项目", "开源实践"]


@pytest.mark.asyncio
async def test_core_parser_collapses_explicit_preferred_category_examples() -> None:
    source_text = "熟悉 Ansys、Abaqus、Nastran 等 CAE 工具者优先"
    parser = CoreJDParser(
        FakeModelClient(
            output={
                "skill_clauses": [
                    {
                        "source_text": source_text,
                        "strength": "preferred",
                        "relation": "all_of",
                        "skills": ["Ansys", "Abaqus", "Nastran"],
                    }
                ]
            }
        ),
        validation_retries=0,
    )

    result = await parser.parse(RawJobDocument(raw_content=source_text))

    assert result.fields.preferred_skills == ["CAE工具使用"]
    assert result.fields.skill_mentions == ["Ansys", "Abaqus", "Nastran"]


@pytest.mark.asyncio
async def test_core_parser_recovers_category_from_matching_source_sentence() -> None:
    raw_content = "熟悉 Ansys、Abaqus、Nastran 等 CAE 工具中的一种或多种者优先"
    parser = CoreJDParser(
        FakeModelClient(
            output={
                "skill_clauses": [
                    {
                        "source_text": "Ansys、Abaqus、Nastran",
                        "strength": "preferred",
                        "relation": "all_of",
                        "skills": ["Ansys", "Abaqus", "Nastran"],
                    }
                ]
            }
        ),
        validation_retries=0,
    )

    result = await parser.parse(RawJobDocument(raw_content=raw_content))

    assert result.fields.preferred_skills == ["CAE工具使用"]
    assert result.fields.skill_mentions == ["Ansys", "Abaqus", "Nastran"]


@pytest.mark.asyncio
async def test_core_parser_closes_explicitly_bounded_any_of_group() -> None:
    source_text = "熟悉 Go、Python、C++ 中至少一种语言"
    parser = CoreJDParser(
        FakeModelClient(
            output={
                "skill_clauses": [
                    {
                        "source_text": source_text,
                        "strength": "required",
                        "relation": "any_of",
                        "skills": ["Go", "Python", "C++"],
                        "group_name": "编程语言",
                        "allow_other": True,
                    }
                ]
            }
        ),
        validation_retries=0,
    )

    result = await parser.parse(RawJobDocument(raw_content=source_text))

    assert result.fields.required_skill_groups is not None
    assert result.fields.required_skill_groups[0].allow_other is False


@pytest.mark.asyncio
async def test_core_parser_collapses_explicit_required_category_examples() -> None:
    source_text = "熟悉 PyTorch、PaddlePaddle 等深度学习框架使用经验"
    parser = CoreJDParser(
        FakeModelClient(
            output={
                "skill_clauses": [
                    {
                        "source_text": source_text,
                        "strength": "required",
                        "relation": "all_of",
                        "skills": ["PyTorch", "PaddlePaddle"],
                    }
                ]
            }
        ),
        validation_retries=0,
    )

    result = await parser.parse(RawJobDocument(raw_content=source_text))

    assert result.fields.required_skills == ["深度学习框架"]
    assert result.fields.skill_mentions == ["PyTorch", "PaddlePaddle"]


@pytest.mark.asyncio
async def test_core_parser_splits_preferred_tool_capability_compounds() -> None:
    source_text = "具备 Python/MATLAB 等数据处理或仿真自动化能力者优先"
    parser = CoreJDParser(
        FakeModelClient(
            output={
                "skill_clauses": [
                    {
                        "source_text": source_text,
                        "strength": "preferred",
                        "relation": "all_of",
                        "skills": [
                            "Python数据处理",
                            "MATLAB数据处理",
                            "仿真自动化",
                        ],
                    }
                ]
            }
        ),
        validation_retries=0,
    )

    result = await parser.parse(RawJobDocument(raw_content=source_text))

    assert result.fields.preferred_skills == [
        "Python",
        "数据处理",
        "MATLAB",
        "仿真自动化",
    ]


@pytest.mark.asyncio
async def test_core_parser_collapses_shared_robotics_cae_contexts() -> None:
    source_text = (
        "有机器人关节/整机、复杂结构件、竞赛车队或工程项目CAE分析经验者优先"
    )
    parser = CoreJDParser(
        FakeModelClient(
            output={
                "skill_clauses": [
                    {
                        "source_text": source_text,
                        "strength": "preferred",
                        "relation": "all_of",
                        "skills": [
                            "机器人关节/整机CAE分析",
                            "复杂结构件CAE分析",
                            "竞赛车队CAE分析",
                            "工程项目CAE分析",
                        ],
                    }
                ]
            }
        ),
        validation_retries=0,
    )

    result = await parser.parse(RawJobDocument(raw_content=source_text))

    assert result.fields.preferred_skills == ["机器人CAE分析"]


@pytest.mark.asyncio
async def test_core_parser_drops_generic_practice_beside_specific_capability() -> None:
    source_text = "拥有大量 Prompt 实践和优化经验者优先"
    parser = CoreJDParser(
        FakeModelClient(
            output={
                "skill_clauses": [
                    {
                        "source_text": source_text,
                        "strength": "preferred",
                        "relation": "all_of",
                        "skills": ["Prompt实践", "Prompt优化"],
                    }
                ]
            }
        ),
        validation_retries=0,
    )

    result = await parser.parse(RawJobDocument(raw_content=source_text))

    assert result.fields.preferred_skills == ["Prompt优化"]


@pytest.mark.asyncio
async def test_core_parser_keeps_direct_project_while_collapsing_shared_tail() -> None:
    source_text = (
        "有具身智能项目经验者优先；有 Agent系统、RAG、多智能体等相关项目经验者优先"
    )
    parser = CoreJDParser(
        FakeModelClient(
            output={
                "skill_clauses": [
                    {
                        "source_text": "有具身智能项目经验者优先",
                        "strength": "preferred",
                        "relation": "all_of",
                        "skills": ["具身智能项目经验"],
                    },
                    {
                        "source_text": "有 Agent系统、RAG、多智能体等相关项目经验者优先",
                        "strength": "preferred",
                        "relation": "all_of",
                        "skills": [
                            "Agent系统项目经验",
                            "RAG项目经验",
                            "多智能体项目经验",
                        ],
                    },
                ]
            }
        ),
        validation_retries=0,
    )

    result = await parser.parse(RawJobDocument(raw_content=source_text))

    assert result.fields.preferred_skills == [
        "具身智能项目",
        "Agent系统",
        "RAG",
        "Multi-Agent",
    ]


@pytest.mark.asyncio
async def test_core_parser_drops_group_collapsed_to_one_canonical_option() -> None:
    raw_content = "任职要求：熟悉 Golang 或 Go 中任一种。"
    parser = CoreJDParser(
        FakeModelClient(
            output={
                "skill_clauses": [
                    {
                        "source_text": "熟悉 Golang 或 Go 中任一种",
                        "strength": "required",
                        "relation": "any_of",
                        "skills": ["Golang", "Go"],
                        "group_name": "编程语言",
                        "allow_other": False,
                    }
                ]
            }
        ),
        validation_retries=0,
    )

    result = await parser.parse(RawJobDocument(raw_content=raw_content))

    assert result.fields.required_skill_groups is None
    assert result.fields.required_skills is None
    assert result.fields.skill_mentions == ["Go"]


@pytest.mark.asyncio
async def test_core_parser_keeps_trailing_preferred_scope_stronger_than_weak_prefix() -> None:
    source_text = "了解 MCU、RTOS、Linux 驱动、通信协议或实时控制系统者优先"
    parser = CoreJDParser(
        FakeModelClient(
            output={
                "skill_clauses": [
                    {
                        "source_text": source_text,
                        "strength": "preferred",
                        "relation": "all_of",
                        "skills": [
                            "MCU",
                            "RTOS",
                            "Linux 驱动",
                            "通信协议",
                            "实时控制系统",
                        ],
                    }
                ]
            }
        ),
        validation_retries=0,
    )

    result = await parser.parse(RawJobDocument(raw_content=source_text))

    assert result.fields.preferred_skills == [
        "MCU",
        "RTOS",
        "Linux",
        "通信协议",
        "实时控制系统",
    ]
    assert result.fields.skill_mentions is None


@pytest.mark.asyncio
async def test_core_parser_routes_flat_mentions_without_reclassifying_them() -> None:
    raw_content = "任职要求：熟练使用 Isaac Sim、MuJoCo 等仿真环境。"
    parser = CoreJDParser(
        FakeModelClient(
            output={
                "skill_clauses": [
                    {
                        "source_text": "熟练使用 Isaac Sim、MuJoCo 等仿真环境",
                        "strength": "required",
                        "relation": "all_of",
                        "skills": ["机器人仿真平台"],
                    },
                    {
                        "source_text": "Isaac Sim、MuJoCo",
                        "strength": "mention",
                        "relation": "all_of",
                        "skills": ["Isaac Sim", "MuJoCo"],
                    },
                ],
            }
        ),
        validation_retries=0,
    )

    result = await parser.parse(RawJobDocument(raw_content=raw_content))

    assert result.fields.required_skills == ["机器人仿真平台"]
    assert result.fields.required_skill_groups is None
    assert result.fields.skill_mentions == ["Isaac Sim", "MuJoCo"]
    evidence_by_path = {item.field_path: item.source_text for item in result.field_evidence}
    assert evidence_by_path["required_skills[0]"] == (
        "熟练使用 Isaac Sim、MuJoCo 等仿真环境"
    )
    assert evidence_by_path["skill_mentions[0]"] == "Isaac Sim、MuJoCo"
    assert evidence_by_path["skill_mentions[1]"] == "Isaac Sim、MuJoCo"


@pytest.mark.asyncio
async def test_core_parser_compiles_strong_parallel_methods_from_one_clause() -> None:
    source_text = "具备扎实的控制理论基础，理解 PID、MPC、阻抗控制、力控和轨迹规划"
    parser = CoreJDParser(
        FakeModelClient(
            output={
                "skill_clauses": [
                    {
                        "source_text": source_text,
                        "strength": "required",
                        "relation": "all_of",
                        "skills": [
                            "控制理论",
                            "PID",
                            "MPC",
                            "阻抗控制",
                            "力控",
                            "轨迹规划",
                        ],
                    }
                ]
            }
        ),
        validation_retries=0,
    )

    result = await parser.parse(RawJobDocument(raw_content=source_text))

    assert result.fields.required_skills == [
        "控制理论",
        "PID",
        "MPC",
        "阻抗控制",
        "力控",
        "轨迹规划",
    ]
    assert result.fields.skill_mentions is None


@pytest.mark.asyncio
async def test_core_parser_compiles_weak_and_preferred_subclauses_separately() -> None:
    source_text = "了解 LLM/VLM 基本原理，有 Prompt Engineering 经验者优先"
    parser = CoreJDParser(
        FakeModelClient(
            output={
                "skill_clauses": [
                    {
                        "source_text": "了解 LLM/VLM 基本原理",
                        "strength": "mention",
                        "relation": "all_of",
                        "skills": ["LLM", "VLM"],
                    },
                    {
                        "source_text": "有 Prompt Engineering 经验者优先",
                        "strength": "preferred",
                        "relation": "all_of",
                        "skills": ["Prompt Engineering"],
                    },
                ]
            }
        ),
        validation_retries=0,
    )

    result = await parser.parse(RawJobDocument(raw_content=source_text))

    assert result.fields.required_skills is None
    assert result.fields.preferred_skills == ["Prompt Engineering"]
    assert result.fields.skill_mentions == ["LLM", "VLM"]


@pytest.mark.asyncio
async def test_core_parser_keeps_nested_alternatives_at_parent_level() -> None:
    source_text = (
        "具备前端（React）、客户端（Flutter）、服务端（Go）中至少一个领域的开发经验"
    )
    parser = CoreJDParser(
        FakeModelClient(
            output={
                "skill_clauses": [
                    {
                        "source_text": source_text,
                        "strength": "required",
                        "relation": "any_of",
                        "skills": ["前端开发", "客户端开发", "服务端开发"],
                        "examples": ["React", "Flutter", "Go"],
                        "group_name": "开发领域",
                        "allow_other": False,
                    },
                ]
            }
        ),
        validation_retries=0,
    )

    result = await parser.parse(RawJobDocument(raw_content=source_text))

    assert result.fields.required_skills is None
    assert [group.model_dump() for group in result.fields.required_skill_groups or []] == [
        {
            "name": "开发领域",
            "any_of": ["前端开发", "客户端开发", "服务端开发"],
            "allow_other": False,
        }
    ]
    assert result.fields.skill_mentions == [
        "React",
        "Flutter",
        "Go",
        "前端开发",
        "客户端开发",
        "服务端开发",
    ]


@pytest.mark.asyncio
async def test_core_parser_applies_shared_security_and_architecture_aliases() -> None:
    raw_content = (
        "招聘类型：应届生\n"
        "工作地点：深圳\n"
        "职位要求\n"
        "1、熟练掌握C/C++开发；"
        "2、在操作系统/编译器/CPU体系结构/汇编等某一方面有深入理解；"
        "3、有安全防护、加固、逆向工程项目经验的优先。"
    )
    parser = CoreJDParser(
        FakeModelClient(
            output={
                "job_type": "campus",
                "locations": ["深圳"],
                "skill_clauses": [
                    {
                        "source_text": "熟练掌握C/C++开发",
                        "strength": "required",
                        "relation": "all_of",
                        "skills": ["C", "C++"],
                    },
                    {
                        "source_text": (
                            "在操作系统/编译器/CPU体系结构/汇编等某一方面有深入理解"
                        ),
                        "strength": "required",
                        "relation": "any_of",
                        "skills": ["操作系统", "编译器", "CPU体系结构", "汇编"],
                        "group_name": "系统基础",
                        "allow_other": True,
                    },
                    {
                        "source_text": "有安全防护、加固、逆向工程项目经验的优先",
                        "strength": "preferred",
                        "relation": "all_of",
                        "skills": ["安全防护", "加固", "逆向工程"],
                    },
                ],
            }
        ),
        validation_retries=0,
    )

    result = await parser.parse(RawJobDocument(raw_content=raw_content))

    assert result.fields.required_skills == ["C++"]
    assert result.fields.required_skill_groups is not None
    assert result.fields.required_skill_groups[0].any_of == [
        "操作系统",
        "编译器",
        "CPU架构",
        "汇编",
    ]
    assert result.fields.preferred_skills == ["安全防护", "软件加固", "逆向工程"]


@pytest.mark.asyncio
async def test_core_parser_ignores_clause_without_exact_source_evidence() -> None:
    parser = CoreJDParser(
        FakeModelClient(
            output={
                "skill_clauses": [
                    {
                        "source_text": "精通 ImaginaryDB",
                        "strength": "required",
                        "relation": "all_of",
                        "skills": ["ImaginaryDB"],
                    }
                ]
            }
        ),
        validation_retries=0,
    )

    result = await parser.parse(
        RawJobDocument(
            raw_content="示例公司发布算法岗位，任职要求为熟悉 Python，其他要求未披露。"
        )
    )

    assert result.fields.required_skills is None
    assert result.field_evidence == []
    assert [warning.code for warning in result.warnings] == [
        "unsupported_clause_evidence"
    ]


@pytest.mark.asyncio
async def test_core_parser_drops_only_unverified_skills_and_returns_warnings() -> None:
    raw_content = (
        "示例公司校园招聘，工作地点北京。"
        "任职要求：熟悉 Python；有 CUDA 经验者优先。"
    )
    parser = CoreJDParser(
        FakeModelClient(
            output={
                "job_type": "campus",
                "locations": ["北京"],
                "required_skills": ["Python", "ImaginaryDB"],
                "preferred_skills": ["CUDA", "GhostRuntime"],
            }
        ),
        validation_retries=0,
    )

    result = await parser.parse(RawJobDocument(raw_content=raw_content))

    assert result.fields.required_skills == ["Python"]
    assert result.fields.preferred_skills == ["CUDA"]
    assert [warning.model_dump() for warning in result.warnings] == [
        {
            "code": "unsupported_field_value",
            "field_path": "required_skills[1]",
            "value": "ImaginaryDB",
            "message": "已删除无原文依据的技能值：ImaginaryDB",
        },
        {
            "code": "unsupported_field_value",
            "field_path": "preferred_skills[1]",
            "value": "GhostRuntime",
            "message": "已删除无原文依据的技能值：GhostRuntime",
        },
    ]


@pytest.mark.asyncio
async def test_core_parser_discards_model_job_type_without_source_evidence() -> None:
    raw_content = "示例公司发布算法岗位，工作内容是开发和测试，招聘类型未在正文中披露。"
    parser = CoreJDParser(
        FakeModelClient(
            output={
                "job_type": "campus",
                "locations": None,
                "required_skills": None,
            }
        ),
        validation_retries=0,
    )

    result = await parser.parse(RawJobDocument(raw_content=raw_content))

    assert result.fields.job_type is None
    assert result.field_evidence == []


@pytest.mark.asyncio
async def test_core_parser_accepts_job_title_metadata_as_traceable_evidence() -> None:
    parser = CoreJDParser(
        FakeModelClient(
            output={
                "job_type": "internship",
                "locations": None,
                "required_skills": None,
            }
        ),
        validation_retries=0,
    )

    result = await parser.parse(
        RawJobDocument(
            raw_content="岗位负责 AI 应用开发与测试，具体招聘类型请以页面标题为准。",
            source_metadata={"title": "AI 应用开发实习生"},
        )
    )

    assert result.fields.job_type == "internship"
    assert result.field_evidence[0].field_path == "job_type"
    assert result.field_evidence[0].source_kind == "metadata"


@pytest.mark.asyncio
async def test_core_parser_treats_graduate_recruitment_as_campus_evidence() -> None:
    parser = CoreJDParser(
        FakeModelClient(
            output={
                "job_type": "campus",
                "locations": ["北京"],
                "required_skills": None,
            }
        ),
        validation_retries=0,
    )

    result = await parser.parse(
        RawJobDocument(
            raw_content="招聘类型：应届生\n工作地点：北京市\n岗位职责：负责 AI 应用研发与测试。"
        )
    )

    assert result.fields.job_type == "campus"
    assert result.field_evidence[0].field_path == "job_type"
    assert result.field_evidence[0].source_text == "应届生"


@pytest.mark.asyncio
async def test_core_parser_prefers_explicit_location_header_over_model_output() -> None:
    parser = CoreJDParser(
        FakeModelClient(
            output={
                "job_type": "campus",
                "locations": ["深圳"],
                "skill_clauses": None,
            }
        ),
        validation_retries=0,
    )

    result = await parser.parse(
        RawJobDocument(
            raw_content=(
                "招聘类型：应届生\n"
                "工作地点：北京市/上海市\n"
                "岗位职责：负责系统研发。"
            )
        )
    )

    assert result.fields.locations == ["北京", "上海"]
    evidence = {
        item.field_path: item.source_text
        for item in result.field_evidence
        if item.field_path.startswith("locations[")
    }
    assert evidence == {"locations[0]": "北京市", "locations[1]": "上海市"}


@pytest.mark.asyncio
async def test_core_parser_prefers_explicit_internship_type_over_campus_text() -> None:
    parser = CoreJDParser(
        FakeModelClient(
            output={
                "job_type": "campus",
                "locations": ["北京"],
                "required_skills": None,
            }
        ),
        validation_retries=0,
    )

    result = await parser.parse(
        RawJobDocument(
            raw_content=(
                "岗位名称：后端研发实习生\n"
                "工作地点：北京\n"
                "招聘类型：实习生\n"
                "招聘项目：校园招聘/实习招聘\n"
                "职位要求：掌握数据结构与算法。"
            )
        )
    )

    assert result.fields.job_type == "internship"
    assert result.field_evidence[0].field_path == "job_type"
    assert result.field_evidence[0].source_text == "实习生"


@pytest.mark.asyncio
async def test_core_parser_accepts_graduate_as_explicit_campus_type() -> None:
    parser = CoreJDParser(
        FakeModelClient(
            output={
                "job_type": None,
                "locations": None,
                "required_skills": None,
            }
        ),
        validation_retries=0,
    )

    result = await parser.parse(
        RawJobDocument(
            raw_content=(
                "岗位名称：GUI Agent 研究\n"
                "招聘类型：应届毕业生\n"
                "课题要求：熟悉模型训练常见框架。"
            )
        )
    )

    assert result.fields.job_type == "campus"
    assert result.field_evidence[0].field_path == "job_type"
    assert result.field_evidence[0].source_text == "应届毕业生"


@pytest.mark.asyncio
async def test_core_parser_accepts_whitelisted_equivalent_skill_evidence() -> None:
    raw_content = (
        "招聘类型：应届生\n"
        "任职要求：熟悉半监督、自监督、主动学习、弱监督；"
        "具备 OOM 降级和 GPU 编程与优化经验，能够实现相关算法。"
    )
    parser = CoreJDParser(
        FakeModelClient(
            output={
                "job_type": "campus",
                "required_skills": [
                    "半监督学习",
                    "自监督学习",
                    "主动学习",
                    "弱监督学习",
                    "OOM降级",
                    "GPU编程与优化",
                    "算法实现",
                ],
            }
        ),
        validation_retries=0,
    )

    result = await parser.parse(RawJobDocument(raw_content=raw_content))

    assert result.fields.required_skills == [
        "半监督学习",
        "自监督学习",
        "主动学习",
        "弱监督学习",
        "OOM降级",
        "GPU编程与优化",
        "算法实现",
    ]
    assert result.warnings == ()
    assert len(result.field_evidence) == 8


@pytest.mark.asyncio
async def test_core_parser_accepts_category_evidence_from_named_members() -> None:
    raw_content = (
        "招聘类型：应届生\n"
        "任职要求：精通 TensorFlow、PyTorch 等主流深度学习工具。"
    )
    parser = CoreJDParser(
        FakeModelClient(output={"required_skills": ["深度学习框架"]}),
        validation_retries=0,
    )

    result = await parser.parse(RawJobDocument(raw_content=raw_content))

    assert result.fields.required_skills == ["深度学习框架"]
    assert result.warnings == ()
    skill_evidence = next(
        item for item in result.field_evidence if item.field_path == "required_skills[0]"
    )
    assert skill_evidence.source_text in {"TensorFlow", "PyTorch"}


@pytest.mark.asyncio
async def test_core_parser_does_not_accept_react_evidence_from_react_reasoning() -> None:
    parser = CoreJDParser(
        FakeModelClient(output={"required_skills": ["React"]}),
        validation_retries=0,
    )

    result = await parser.parse(
        RawJobDocument(raw_content="职位要求：深入理解 ReAct 推理范式。")
    )

    assert result.fields.required_skills is None
    assert [warning.value for warning in result.warnings] == ["React"]


def test_v33_indexes_requirement_predicates_with_stable_source_ids() -> None:
    clauses = index_source_clauses(
        "岗位名称：大模型算法工程师\n"
        "职位要求\n"
        "具备数据分析能力：能够分析模型效果，并能诊断训练策略和数据问题。\n"
        "加分项：有工业级基础大模型研发经验者优先。"
    )

    assert [(item.clause_id, item.section, item.text) for item in clauses] == [
        ("SC001", "unknown", "岗位名称：大模型算法工程师"),
        ("SC002", "requirements", "具备数据分析能力"),
        ("SC003", "requirements", "能够分析模型效果"),
        ("SC004", "requirements", "并能诊断训练策略和数据问题"),
        ("SC005", "preferred", "有工业级基础大模型研发经验者优先"),
    ]


@pytest.mark.asyncio
async def test_v34_accepts_compact_clauses_with_omitted_defaults() -> None:
    raw_content = "人工智能算法工程师职位要求\n熟练掌握 Python 编程语言"
    source_clause = index_source_clauses(raw_content)[0]
    client = FakeModelClient(
        output={
            "job_type": "campus",
            "clauses": [
                {
                    "id": source_clause.clause_id,
                    "level": "required",
                    "skills": ["Python"],
                }
            ],
        }
    )
    parser = CoreJDParser(client, validation_retries=0)

    result = await parser.parse(RawJobDocument(raw_content=raw_content))

    assert result.fields.required_skills == ["Python"]
    assert result.fields.required_skill_groups is None
    assert result.warnings == ()
    assert client.last_request is not None
    compact_schema = client.last_request.json_schema["$defs"][
        "CompactIndexedCoreSkillClause"
    ]
    assert compact_schema["required"] == ["id", "level", "skills"]
    assert compact_schema["properties"]["relation"]["default"] == "all_of"
    assert compact_schema["properties"]["open"]["default"] is False


@pytest.mark.asyncio
async def test_v34_normalizes_empty_examples_and_unambiguous_level_alias() -> None:
    raw_content = "人工智能算法工程师职位要求\n熟练掌握 Python 编程语言"
    source_clause = index_source_clauses(raw_content)[0]
    parser = CoreJDParser(
        FakeModelClient(
            output={
                "clauses": [
                    {
                        "id": source_clause.clause_id,
                        "requirement_type": "required",
                        "skills": ["Python"],
                        "examples": [],
                    }
                ]
            }
        ),
        validation_retries=0,
    )

    result = await parser.parse(RawJobDocument(raw_content=raw_content))

    assert result.fields.required_skills == ["Python"]
    assert result.fields.skill_mentions is None
    assert result.warnings == ()


@pytest.mark.asyncio
async def test_v36_recovers_empty_skills_and_unsupported_qualifiers() -> None:
    raw_content = (
        "职位要求\n"
        "熟悉 Python 并有实际使用经验\n"
        "了解深度学习框架，例如 PyTorch\n"
        "具备良好的沟通能力"
    )
    clauses_by_text = {
        clause.text: clause.clause_id for clause in index_source_clauses(raw_content)
    }
    parser = CoreJDParser(
        FakeModelClient(
            output={
                "clauses": [
                    {
                        "id": clauses_by_text["熟悉 Python 并有实际使用经验"],
                        "level": "required",
                        "skills": ["Python"],
                        "qualifier": "technical_experience",
                    },
                    {
                        "id": clauses_by_text["了解深度学习框架，例如 PyTorch"],
                        "level": "mention",
                        "skills": [],
                        "examples": ["PyTorch"],
                    },
                    {
                        "id": clauses_by_text["具备良好的沟通能力"],
                        "level": "required",
                        "skills": [],
                    },
                ]
            }
        ),
        validation_retries=0,
    )

    result = await parser.parse(RawJobDocument(raw_content=raw_content))

    assert result.fields.required_skills == ["Python"]
    assert result.fields.skill_mentions == ["PyTorch"]
    assert [warning.code for warning in result.warnings] == [
        "unsupported_field_value",
        "unsupported_field_value",
        "unsupported_field_value",
    ]
    assert result.warnings[0].field_path == "clauses[0].qualifier"
    assert result.warnings[1].field_path == "clauses[1].skills"
    assert result.warnings[2].field_path == "clauses[2].skills"


@pytest.mark.asyncio
async def test_v36_normalizes_supported_qualifier_alias() -> None:
    raw_content = "加分项\n有 Python 项目经验者优先"
    source_clause = index_source_clauses(raw_content)[0]
    parser = CoreJDParser(
        FakeModelClient(
            output={
                "clauses": [
                    {
                        "id": source_clause.clause_id,
                        "level": "preferred",
                        "skills": ["Python"],
                        "qualifier": "project experience",
                    }
                ]
            }
        ),
        validation_retries=0,
    )

    result = await parser.parse(RawJobDocument(raw_content=raw_content))

    assert result.fields.preferred_skills == ["Python"]
    assert result.fields.skill_concepts is not None
    assert result.fields.skill_concepts[0].qualifier == "project_experience"
    assert result.warnings == ()


@pytest.mark.asyncio
async def test_v36_enforces_explicit_section_and_weak_cue_strengths() -> None:
    raw_content = (
        "工作职责\n"
        "负责 Python 服务开发\n"
        "任职资格\n"
        "了解 RAG\n"
        "熟悉 Linux\n"
        "加分项\n"
        "有 Agent 项目经验者优先"
    )
    clauses_by_text = {
        clause.text: clause.clause_id for clause in index_source_clauses(raw_content)
    }
    parser = CoreJDParser(
        FakeModelClient(
            output={
                "clauses": [
                    {
                        "id": clauses_by_text["负责 Python 服务开发"],
                        "level": "required",
                        "skills": ["Python"],
                    },
                    {
                        "id": clauses_by_text["了解 RAG"],
                        "level": "required",
                        "skills": ["RAG"],
                    },
                    {
                        "id": clauses_by_text["熟悉 Linux"],
                        "level": "required",
                        "skills": ["Linux"],
                    },
                    {
                        "id": clauses_by_text["有 Agent 项目经验者优先"],
                        "level": "required",
                        "skills": ["Agent"],
                        "qualifier": "project_experience",
                    },
                ]
            }
        ),
        validation_retries=0,
    )

    result = await parser.parse(RawJobDocument(raw_content=raw_content))

    assert result.fields.required_skills == ["Linux"]
    assert result.fields.preferred_skills == ["Agent"]
    assert result.fields.skill_mentions == ["Python", "RAG"]
    assert len(result.warnings) == 3


def test_v37_indexes_common_qualification_headings_as_requirements() -> None:
    clauses = index_source_clauses(
        "工作职责\n"
        "负责 Python 服务开发\n"
        "任职资格\n"
        "熟悉 Linux\n"
        "职位资格：掌握 SQL\n"
        "岗位资格\n"
        "具备数据分析能力"
    )

    assert [(clause.section, clause.text) for clause in clauses] == [
        ("responsibilities", "负责 Python 服务开发"),
        ("requirements", "熟悉 Linux"),
        ("requirements", "掌握 SQL"),
        ("requirements", "具备数据分析能力"),
    ]


@pytest.mark.asyncio
async def test_v37_downgrades_non_required_any_of_to_plain_enumeration() -> None:
    raw_content = "加分项\n有 Python 或 Go 项目经验者优先"
    source_clause = index_source_clauses(raw_content)[0]
    parser = CoreJDParser(
        FakeModelClient(
            output={
                "clauses": [
                    {
                        "id": source_clause.clause_id,
                        "level": "required",
                        "relation": "any_of",
                        "skills": ["Python", "Go"],
                        "group": "编程语言",
                        "open": True,
                        "qualifier": "project_experience",
                    }
                ]
            }
        ),
        validation_retries=0,
    )

    result = await parser.parse(RawJobDocument(raw_content=raw_content))

    assert result.fields.required_skills is None
    assert result.fields.required_skill_groups is None
    assert result.fields.preferred_skills == ["Python", "Go"]
    assert result.fields.skill_concepts is not None
    assert all(concept.relation == "all_of" for concept in result.fields.skill_concepts)
    assert [warning.code for warning in result.warnings] == [
        "unsupported_field_value",
        "unsupported_any_of_relation",
    ]


@pytest.mark.asyncio
async def test_v38_downgrades_single_option_any_of_to_required_skill() -> None:
    raw_content = "岗位名称：Python 开发工程师\n任职要求\n熟悉 Python"
    source_clause = index_source_clauses(raw_content)[-1]
    parser = CoreJDParser(
        FakeModelClient(
            output={
                "clauses": [
                    {
                        "id": source_clause.clause_id,
                        "level": "required",
                        "relation": "any_of",
                        "skills": ["Python"],
                        "group": "编程语言",
                        "open": True,
                    }
                ]
            }
        ),
        validation_retries=0,
    )

    result = await parser.parse(RawJobDocument(raw_content=raw_content))

    assert result.fields.required_skills == ["Python"]
    assert result.fields.required_skill_groups is None
    assert [warning.code for warning in result.warnings] == [
        "unsupported_any_of_relation"
    ]


@pytest.mark.asyncio
async def test_v39_filters_generic_responsibility_actions() -> None:
    raw_content = (
        "工作职责\n"
        "负责产品需求讨论、系统开发和PyTorch模型训练"
    )
    source_clause = index_source_clauses(raw_content)[0]
    parser = CoreJDParser(
        FakeModelClient(
            output={
                "clauses": [
                    {
                        "id": source_clause.clause_id,
                        "level": "required",
                        "skills": ["产品需求", "系统开发", "PyTorch"],
                    }
                ]
            }
        ),
        validation_retries=0,
    )

    result = await parser.parse(RawJobDocument(raw_content=raw_content))

    assert result.fields.required_skills is None
    assert result.fields.skill_mentions == ["PyTorch"]
    assert any(
        warning.message == "职责条款中的纯动作、业务对象或结果词已从技能中删除"
        for warning in result.warnings
    )


@pytest.mark.asyncio
async def test_v39_keeps_deep_understanding_as_required() -> None:
    raw_content = "职位要求\n深入了解 PyTorch 等深度学习框架的运行原理"
    source_clause = index_source_clauses(raw_content)[0]
    parser = CoreJDParser(
        FakeModelClient(
            output={
                "clauses": [
                    {
                        "id": source_clause.clause_id,
                        "level": "required",
                        "skills": ["深度学习框架原理"],
                        "examples": ["PyTorch"],
                    }
                ]
            }
        ),
        validation_retries=0,
    )

    result = await parser.parse(RawJobDocument(raw_content=raw_content))

    assert result.fields.required_skills == ["深度学习框架原理"]
    assert result.fields.skill_mentions == ["PyTorch"]


@pytest.mark.asyncio
async def test_v39_recovers_direct_or_without_grouping_peer_requirements() -> None:
    raw_content = (
        "职位要求\n"
        "熟悉GPU体系结构，熟练掌握CUDA，熟练掌握C++或Python语言"
    )
    clauses = index_source_clauses(raw_content)
    assert [clause.text for clause in clauses] == [
        "熟悉GPU体系结构",
        "熟练掌握CUDA",
        "熟练掌握C++或Python语言",
    ]
    parser = CoreJDParser(
        FakeModelClient(
            output={
                "clauses": [
                    {
                        "id": clauses[0].clause_id,
                        "level": "required",
                        "skills": ["GPU体系结构"],
                    },
                    {
                        "id": clauses[1].clause_id,
                        "level": "required",
                        "skills": ["CUDA"],
                    },
                    {
                        "id": clauses[2].clause_id,
                        "level": "required",
                        "skills": ["C++", "Python"],
                    },
                ]
            }
        ),
        validation_retries=0,
    )

    result = await parser.parse(RawJobDocument(raw_content=raw_content))

    assert result.fields.required_skills == ["GPU体系结构", "CUDA"]
    assert result.fields.required_skill_groups is not None
    assert result.fields.required_skill_groups[0].model_dump() == {
        "name": "编程语言",
        "any_of": ["C++", "Python"],
        "allow_other": False,
    }


@pytest.mark.asyncio
async def test_v39_recovers_counted_parenthetical_any_of_examples() -> None:
    raw_content = (
        "职位要求\n"
        "熟悉至少一种主流开源推理引擎（如vLLM、SGLang、"
        "TensorRT-LLM等）的底层机制"
    )
    source_clause = index_source_clauses(raw_content)[0]
    parser = CoreJDParser(
        FakeModelClient(
            output={
                "clauses": [
                    {
                        "id": source_clause.clause_id,
                        "level": "required",
                        "relation": "any_of",
                        "skills": ["开源推理引擎"],
                        "examples": ["vLLM", "SGLang", "TensorRT-LLM"],
                        "group": "推理引擎",
                        "open": True,
                    }
                ]
            }
        ),
        validation_retries=0,
    )

    result = await parser.parse(RawJobDocument(raw_content=raw_content))

    assert result.fields.required_skills is None
    assert result.fields.required_skill_groups is not None
    assert result.fields.required_skill_groups[0].model_dump() == {
        "name": "推理框架",
        "any_of": ["vLLM", "SGLang", "TensorRT-LLM"],
        "allow_other": True,
    }


@pytest.mark.asyncio
async def test_v39_drops_qualifier_without_explicit_experience_scope() -> None:
    raw_content = "工作职责\n负责推理系统研发和模型算法研究"
    source_clause = index_source_clauses(raw_content)[0]
    parser = CoreJDParser(
        FakeModelClient(
            output={
                "clauses": [
                    {
                        "id": source_clause.clause_id,
                        "level": "mention",
                        "skills": ["推理系统"],
                        "qualifier": "development_experience",
                    }
                ]
            }
        ),
        validation_retries=0,
    )

    result = await parser.parse(RawJobDocument(raw_content=raw_content))

    assert result.fields.skill_concepts is not None
    assert result.fields.skill_concepts[0].qualifier is None
    assert any(
        warning.message == "原文没有对应的经验限定，已删除 qualifier"
        for warning in result.warnings
    )


@pytest.mark.asyncio
async def test_v39_keeps_source_backed_qualifier() -> None:
    raw_content = "职位要求\n具有Python服务端项目开发经验，能够独立完成开发工作"
    source_clause = index_source_clauses(raw_content)[0]
    parser = CoreJDParser(
        FakeModelClient(
            output={
                "clauses": [
                    {
                        "id": source_clause.clause_id,
                        "level": "required",
                        "skills": ["Python"],
                        "qualifier": "development_experience",
                    }
                ]
            }
        ),
        validation_retries=0,
    )

    result = await parser.parse(RawJobDocument(raw_content=raw_content))

    assert result.fields.skill_concepts is not None
    assert result.fields.skill_concepts[0].qualifier == "development_experience"


@pytest.mark.asyncio
async def test_v36_normalizes_province_qualified_explicit_locations() -> None:
    raw_content = (
        "招聘类型：校园招聘 全职\n"
        "工作地点：北京市、上海市、广东省·深圳市、浙江省·杭州市\n"
        "任职要求：熟悉 Python"
    )
    parser = CoreJDParser(
        FakeModelClient(
            output={
                "job_type": "campus",
                "locations": ["北京市", "上海市", "广东省·深圳市", "浙江省·杭州市"],
                "required_skills": ["Python"],
            }
        ),
        validation_retries=0,
    )

    result = await parser.parse(RawJobDocument(raw_content=raw_content))

    assert result.fields.locations == ["北京", "上海", "深圳", "杭州"]


@pytest.mark.asyncio
async def test_v33_resolves_indexed_clauses_and_covers_direct_abilities() -> None:
    raw_content = (
        "职位要求\n"
        "具备数据分析能力：能够分析模型效果，并能诊断训练策略和数据问题。"
    )
    clauses_by_text = {
        clause.text: clause.clause_id for clause in index_source_clauses(raw_content)
    }
    parser = CoreJDParser(
        FakeModelClient(
            output={
                "skill_clauses": [
                    {
                        "source_clause_id": clauses_by_text["具备数据分析能力"],
                        "strength": "required",
                        "relation": "all_of",
                        "skills": ["数据分析"],
                    },
                    {
                        "source_clause_id": clauses_by_text["能够分析模型效果"],
                        "strength": "required",
                        "relation": "all_of",
                        "skills": ["模型效果分析"],
                    },
                    {
                        "source_clause_id": clauses_by_text[
                            "并能诊断训练策略和数据问题"
                        ],
                        "strength": "required",
                        "relation": "all_of",
                        "skills": ["训练策略诊断", "数据问题诊断"],
                    },
                ]
            }
        ),
        validation_retries=0,
    )

    result = await parser.parse(RawJobDocument(raw_content=raw_content))

    assert result.fields.required_skills == [
        "数据分析",
        "模型效果分析",
        "训练策略诊断",
        "数据问题诊断",
    ]
    assert result.warnings == ()
    assert all(
        evidence.source_text in raw_content for evidence in result.field_evidence
    )


@pytest.mark.asyncio
async def test_v33_rejects_slash_examples_as_any_of_and_keeps_parent() -> None:
    raw_content = "职位要求\n有 PyTorch/PaddlePaddle 等深度学习框架使用经验"
    source_clause = index_source_clauses(raw_content)[0]
    parser = CoreJDParser(
        FakeModelClient(
            output={
                "skill_clauses": [
                    {
                        "source_clause_id": source_clause.clause_id,
                        "strength": "required",
                        "relation": "any_of",
                        "skills": ["PyTorch", "PaddlePaddle"],
                        "group_name": "深度学习框架",
                        "allow_other": True,
                    }
                ]
            }
        ),
        validation_retries=0,
    )

    result = await parser.parse(RawJobDocument(raw_content=raw_content))

    assert result.fields.required_skills == ["深度学习框架"]
    assert result.fields.required_skill_groups is None
    assert result.fields.skill_mentions == ["PyTorch", "PaddlePaddle"]
    assert [warning.code for warning in result.warnings] == [
        "unsupported_any_of_relation"
    ]


@pytest.mark.asyncio
async def test_v33_keeps_source_backed_explicit_any_of() -> None:
    raw_content = "职位要求\n熟悉 PyTorch 或 PaddlePaddle 中任一种"
    source_clause = index_source_clauses(raw_content)[0]
    parser = CoreJDParser(
        FakeModelClient(
            output={
                "skill_clauses": [
                    {
                        "source_clause_id": source_clause.clause_id,
                        "strength": "required",
                        "relation": "any_of",
                        "skills": ["PyTorch", "PaddlePaddle"],
                        "group_name": "深度学习框架",
                        "allow_other": False,
                    }
                ]
            }
        ),
        validation_retries=0,
    )

    result = await parser.parse(RawJobDocument(raw_content=raw_content))

    assert result.fields.required_skill_groups is not None
    assert result.fields.required_skill_groups[0].any_of == [
        "PyTorch",
        "PaddlePaddle",
    ]
    assert result.warnings == ()


@pytest.mark.asyncio
async def test_v33_warns_when_technical_requirement_clause_is_uncovered() -> None:
    raw_content = "职位要求\n熟练掌握 Python\n具备模型效果分析能力"
    clauses_by_text = {
        clause.text: clause.clause_id for clause in index_source_clauses(raw_content)
    }
    parser = CoreJDParser(
        FakeModelClient(
            output={
                "skill_clauses": [
                    {
                        "source_clause_id": clauses_by_text["熟练掌握 Python"],
                        "strength": "required",
                        "relation": "all_of",
                        "skills": ["Python"],
                    }
                ]
            }
        ),
        validation_retries=0,
    )

    result = await parser.parse(RawJobDocument(raw_content=raw_content))

    assert result.fields.required_skills == ["Python"]
    assert [(warning.code, warning.value) for warning in result.warnings] == [
        (
            "uncovered_requirement_clause",
            clauses_by_text["具备模型效果分析能力"],
        )
    ]


@pytest.mark.asyncio
async def test_v33_requests_one_targeted_repair_for_uncovered_clause() -> None:
    raw_content = "职位要求\n熟练掌握 Python\n具备模型效果分析能力"
    clauses_by_text = {
        clause.text: clause.clause_id for clause in index_source_clauses(raw_content)
    }
    client = FakeModelClient(
        output={
            "skill_clauses": [
                {
                    "source_clause_id": clauses_by_text["熟练掌握 Python"],
                    "strength": "required",
                    "relation": "all_of",
                    "skills": ["Python"],
                }
            ]
        }
    )
    parser = CoreJDParser(client, validation_retries=1)

    result = await parser.parse(RawJobDocument(raw_content=raw_content))

    assert client.last_request is not None
    assert len(client.last_request.messages) == 3
    assert clauses_by_text["具备模型效果分析能力"] in (
        client.last_request.messages[-1].content
    )
    assert [(warning.code, warning.value) for warning in result.warnings] == [
        (
            "uncovered_requirement_clause",
            clauses_by_text["具备模型效果分析能力"],
        )
    ]
