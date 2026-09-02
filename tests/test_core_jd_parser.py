from __future__ import annotations

import pytest

from src.domain.core_skill_semantics import CoreSkillClause
from src.domain.job import RawJobDocument
from src.infrastructure.llm_client import FakeModelClient
from src.services.core_jd_parser import (
    DEFAULT_CORE_PARSER_VERSION,
    DEFAULT_CORE_PROMPT_VERSION,
    CoreJDParser,
)

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

    assert result.fields.model_dump() == {
        "job_type": "campus",
        "locations": ["深圳"],
        "required_skills": ["Python", "RAG", "Agent"],
        "required_skill_groups": None,
        "preferred_skills": None,
        "skill_mentions": None,
    }
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
    assert "skill_clauses" in client.last_request.json_schema["properties"]
    assert "skill_mentions" not in client.last_request.json_schema["properties"]
    assert "required_skill_groups" not in client.last_request.json_schema["properties"]
    clause_schema = client.last_request.json_schema["$defs"]["CoreSkillClause"]
    assert clause_schema["properties"]["skills"]["type"] == "array"
    assert clause_schema["properties"]["relation"]["enum"] == ["all_of", "any_of"]
    assert clause_schema["properties"]["strength"]["enum"] == [
        "required",
        "preferred",
        "mention",
    ]
    assert "any_of" not in clause_schema["properties"]
    assert "优先、加分" in client.last_request.messages[0].content
    assert "最小语义条款" in client.last_request.messages[0].content
    assert "source_text 必须逐字" in client.last_request.messages[0].content
    assert "strength=mention" in client.last_request.messages[0].content
    assert "relation=all_of" in client.last_request.messages[0].content
    assert "relation=any_of" in client.last_request.messages[0].content
    assert "不得越过逗号或分号扩张" in client.last_request.messages[0].content
    assert "前端（React）" in client.last_request.messages[0].content
    assert "不遗漏并列技能" in client.last_request.messages[0].content
    assert "工程能力、论文复现、工程实现" in client.last_request.messages[0].content
    assert "至少一种/任一种" in client.last_request.messages[0].content
    assert "AI 项目或开源实践者加分" in client.last_request.messages[0].content
    assert "优化器与训练算法" in client.last_request.messages[0].content
    assert "需求分析、逻辑拆解" in client.last_request.messages[0].content
    assert "模型效果分析、训练策略诊断、数据问题诊断" in (
        client.last_request.messages[0].content
    )
    assert "编程基础扎实、工程能力良好" in client.last_request.messages[0].content
    assert "一个或多个" in client.last_request.messages[0].content
    assert "有实践或浓厚兴趣" in client.last_request.messages[0].content
    assert "examples" not in str(client.last_request.json_schema)
    assert result.prompt_version == DEFAULT_CORE_PROMPT_VERSION
    assert result.parser_version == DEFAULT_CORE_PARSER_VERSION


def test_core_skill_clause_uses_one_skill_array_and_explicit_relation() -> None:
    clause = CoreSkillClause(
        source_text="熟悉 Python",
        strength="required",
        relation="all_of",
        skills=["Python"],
    )

    assert clause.skills == ["Python"]
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

    assert result.fields.model_dump() == {
        "job_type": None,
        "locations": None,
        "required_skills": None,
        "required_skill_groups": None,
        "preferred_skills": None,
        "skill_mentions": None,
    }
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
                        "group_name": "开发领域",
                        "allow_other": False,
                    },
                    {
                        "source_text": "React",
                        "strength": "mention",
                        "relation": "all_of",
                        "skills": ["React"],
                    },
                    {
                        "source_text": "Flutter",
                        "strength": "mention",
                        "relation": "all_of",
                        "skills": ["Flutter"],
                    },
                    {
                        "source_text": "Go",
                        "strength": "mention",
                        "relation": "all_of",
                        "skills": ["Go"],
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
