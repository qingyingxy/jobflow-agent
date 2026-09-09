from src.domain.skill_normalizer import (
    build_skill_source_map,
    extract_skill_matches,
    normalize_atomic_skill_values,
    normalize_core_fields,
    normalize_skill_category,
    normalize_skill_concepts,
    normalize_skill_fields,
    normalize_skill_groups,
    normalize_skill_values,
    skill_category_for,
    skill_id_for,
)


def test_extract_skill_matches_distinguishes_react_from_react_reasoning() -> None:
    frontend = {match.canonical for match in extract_skill_matches("熟悉 React 开发")}
    reasoning = {
        match.canonical
        for match in extract_skill_matches("深入理解 ReAct、CoT 等推理范式")
    }

    assert "React" in frontend
    assert "React" not in reasoning


def test_shared_ontology_normalizes_categories_and_short_aliases() -> None:
    assert normalize_skill_values(
        ["训练框架", "TS", "图像生成项目经验", "CPU体系结构"]
    ) == [
        "深度学习框架",
        "TypeScript",
        "图像生成",
        "CPU架构",
    ]
    assert normalize_skill_category("开源推理引擎") == "推理框架"


def test_skill_concepts_use_stable_ids_for_surface_aliases() -> None:
    variants = [
        "HTTP",
        "HTTP协议",
        "大模型API调用",
        "LLM API",
        "工程实现能力",
        "工程实现",
    ]

    identities = {
        value: [item.skill_id for item in normalize_skill_concepts(value)]
        for value in variants
    }

    assert identities["HTTP"] == identities["HTTP协议"] == ["skill:http"]
    assert identities["大模型API调用"] == identities["LLM API"] == [
        "skill:llm-api"
    ]
    assert identities["工程实现能力"] == identities["工程实现"] == [
        "skill:工程实现"
    ]
    assert skill_id_for("C++") == "skill:c-plus-plus"


def test_skill_concepts_split_compounds_and_legacy_qualifiers() -> None:
    compound = normalize_skill_concepts("LLM/VLM")
    legacy = normalize_skill_concepts("VLA项目")

    assert [(item.skill_id, item.canonical_name) for item in compound] == [
        ("skill:llm", "LLM"),
        ("skill:vlm", "VLM"),
    ]
    assert len(legacy) == 1
    assert legacy[0].skill_id == "skill:vla"
    assert legacy[0].canonical_name == "VLA"
    assert legacy[0].qualifier == "project_experience"


def test_security_hardening_alias_requires_software_context_in_source_text() -> None:
    security = {
        match.canonical
        for match in extract_skill_matches("有安全防护、加固、逆向工程项目经验")
    }
    mechanical = {
        match.canonical for match in extract_skill_matches("负责结构加固与可靠性设计")
    }

    assert "软件加固" in security
    assert "软件加固" not in mechanical
    assert normalize_skill_values(
        ["加固"],
        source_text="有安全防护、加固、逆向工程项目经验",
    ) == ["软件加固"]
    assert normalize_skill_values(
        ["加固"],
        source_text="负责结构加固与可靠性设计",
    ) == ["加固"]


def test_c_and_cpp_collapse_only_for_grouped_source_alias() -> None:
    assert normalize_skill_values(
        ["C", "C++"],
        source_text="熟练掌握 C/C++ 开发",
    ) == ["C++"]
    assert normalize_skill_values(
        ["C", "C++"],
        source_text="熟悉 C、C++ 两种语言",
    ) == ["C", "C++"]


def test_skill_source_map_supports_categories_from_concrete_members() -> None:
    sources = build_skill_source_map(
        "职位要求：精通 TensorFlow、PyTorch 等主流框架，熟悉大模型的 API 使用。"
    )

    assert sources["深度学习框架"] in {"TensorFlow", "PyTorch"}
    assert sources["LLM API"] == "大模型的 API"


def test_extract_skill_matches_normalizes_v5_source_aliases() -> None:
    source = (
        "熟悉提示词工程和大模型 API，具备 Agent 系统研发经验；"
        "掌握模型量化、剪枝、蒸馏、稀疏化；"
        "熟悉 3D 视觉和推理加速框架；"
        "有生产级 Agent 平台、工具调用 Agent 与数据 Pipeline 经验。"
    )

    labels = {match.canonical for match in extract_skill_matches(source)}

    assert {
        "Prompt Engineering",
        "LLM API",
        "Agent系统研发",
        "模型剪枝",
        "模型蒸馏",
        "模型稀疏化",
        "3D视觉",
        "推理框架",
        "生产级Agent平台",
        "工具调用Agent",
        "数据Pipeline",
    } <= labels


def test_extract_skill_matches_preserves_specific_agent_options() -> None:
    labels = {
        match.canonical
        for match in extract_skill_matches(
            "多工具调用或 Coding/Search/Productivity Agent 经验"
        )
    }

    assert labels == {
        "多工具调用",
        "Coding Agent",
        "Search Agent",
        "Productivity Agent",
    }


def test_extract_skill_matches_prefers_specific_composite_terms() -> None:
    labels = [
        match.canonical
        for match in extract_skill_matches(
            "Diffusion Policy、OpenVLA、Driving World Model、神经渲染"
        )
    ]

    assert labels == [
        "Diffusion Policy",
        "OpenVLA",
        "Driving World Model",
        "神经渲染",
    ]


def test_normalize_skill_values_splits_grouped_technical_terms() -> None:
    values = normalize_skill_values(
        [
            "代码能力与C/C++/Python",
            "RAG、Agent、Prompt Engineering",
            "结构化思维与逻辑清晰",
        ]
    )

    assert values == [
        "编程能力",
        "C++",
        "Python",
        "RAG",
        "Agent",
        "Prompt Engineering",
    ]


def test_skill_categories_and_any_of_groups_share_one_mapping() -> None:
    assert normalize_skill_category("后端编程语言") == "编程语言"
    assert normalize_skill_category("大模型推理框架") == "推理框架"
    assert skill_category_for("LangGraph") == "Agent框架"
    assert skill_category_for("TensorRT-LLM") == "推理框架"

    groups = normalize_skill_groups(
        [
            {
                "name": "后端编程语言",
                "any_of": ["Go / Java / C++ / Rust"],
                "allow_other": False,
            },
            {
                "name": "大模型推理框架",
                "any_of": ["TensorRT / vLLM"],
                "allow_other": True,
            },
        ]
    )

    assert groups == [
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


def test_normalize_core_fields_preserves_requirement_classes() -> None:
    normalized = normalize_core_fields(
        {
            "job_type": "campus",
            "locations": ["上海市"],
            "required_skills": ["Python", "Go"],
            "required_skill_groups": [
                {
                    "name": "后端编程语言",
                    "any_of": ["Go", "Java"],
                    "allow_other": False,
                }
            ],
            "preferred_skills": ["CUDA"],
            "skill_mentions": ["RAG"],
        },
        source_content=(
            "任职要求：掌握 Python，熟悉 Go 或 Java；CUDA 优先；了解 RAG。"
        ),
    )

    assert normalized["required_skills"] == ["Python"]
    assert normalized["preferred_skills"] == ["CUDA"]
    assert normalized["skill_mentions"] == ["RAG", "Go", "Java"]
    assert normalized["required_skill_groups"] == [
        {
            "name": "编程语言",
            "any_of": ["Go", "Java"],
            "allow_other": False,
        }
    ]


def test_normalize_core_fields_collapses_plain_platform_enumeration() -> None:
    normalized = normalize_core_fields(
        {
            "required_skills": [
                "数据结构",
                "算法",
                "Isaac Sim",
                "MuJoCo",
                "Genesis",
            ]
        },
        source_content=(
            "职位要求：掌握数据结构与算法；"
            "熟练使用 Isaac Sim、MuJoCo、Genesis 等仿真环境。"
        ),
    )

    assert normalized["required_skills"] == [
        "数据结构与算法",
        "机器人仿真平台",
    ]
    assert normalized["required_skill_groups"] is None
    assert normalized["skill_mentions"] == ["Isaac Sim", "MuJoCo", "Genesis"]


def test_normalize_core_fields_flattens_non_alternative_language_group() -> None:
    normalized = normalize_core_fields(
        {
            "required_skill_groups": [
                {
                    "name": "编程语言",
                    "any_of": ["C++", "Python"],
                    "allow_other": True,
                }
            ]
        },
        source_content="职位要求：熟练使用 C++、Python，熟悉 Eigen、NumPy。",
    )

    assert normalized["required_skills"] == ["C++", "Python"]
    assert normalized["required_skill_groups"] is None


def test_normalize_core_fields_limits_alternative_signal_to_comma_segment() -> None:
    normalized = normalize_core_fields(
        {
            "required_skill_groups": [
                {
                    "name": "编程语言",
                    "any_of": ["C++", "Python"],
                    "allow_other": True,
                }
            ]
        },
        source_content=(
            "任职要求：扎实的 C++/CUDA/Python 工程能力，"
            "熟悉至少一种主流推理框架（TensorRT/vLLM）。"
        ),
    )

    assert normalized["required_skills"] == ["C++", "Python"]
    assert normalized["required_skill_groups"] is None


def test_normalize_core_fields_trims_unrelated_skill_before_local_alternative() -> None:
    normalized = normalize_core_fields(
        {
            "required_skill_groups": [
                {
                    "name": "编程语言",
                    "any_of": ["Python", "Go", "Rust"],
                    "allow_other": False,
                }
            ]
        },
        source_content="职位要求：掌握 Python，熟悉 Go 或 Rust 任一种。",
    )

    assert normalized["required_skills"] == ["Python"]
    assert normalized["required_skill_groups"] == [
        {
            "name": "编程语言",
            "any_of": ["Go", "Rust"],
            "allow_other": False,
        }
    ]
    assert normalized["skill_mentions"] == ["Go", "Rust"]


def test_normalize_core_fields_keeps_comma_bridged_or_options_together() -> None:
    normalized = normalize_core_fields(
        {
            "required_skill_groups": [
                {
                    "name": "编程语言",
                    "any_of": ["Go", "Java", "C++", "Rust"],
                    "allow_other": False,
                }
            ]
        },
        source_content="职位要求：熟悉 Go，或 Java、C++、Rust 中任一种。",
    )

    assert normalized["required_skills"] is None
    assert normalized["required_skill_groups"] == [
        {
            "name": "编程语言",
            "any_of": ["Go", "Java", "C++", "Rust"],
            "allow_other": False,
        }
    ]


def test_normalize_core_fields_demotes_inline_preferred_group() -> None:
    normalized = normalize_core_fields(
        {
            "required_skills": ["Python"],
            "required_skill_groups": [
                {
                    "name": "Agent框架",
                    "any_of": ["LangChain", "LangGraph", "AutoGen"],
                    "allow_other": True,
                }
            ],
        },
        source_content=(
            "职位要求：掌握 Python；"
            "熟悉 LangChain/LangGraph/AutoGen 等其中一种技术栈者优先。"
        ),
    )

    assert normalized["required_skills"] == ["Python"]
    assert normalized["required_skill_groups"] is None
    assert normalized["preferred_skills"] == ["Agent框架"]


def test_normalize_core_fields_does_not_reinfer_group_from_preferred_mentions() -> None:
    normalized = normalize_core_fields(
        {
            "required_skills": ["Python"],
            "skill_mentions": ["LangChain", "LangGraph", "AutoGen"],
        },
        source_content=(
            "职位要求：掌握 Python；"
            "熟悉 LangChain/LangGraph/AutoGen 等其中一种技术栈者优先。"
        ),
    )

    assert normalized["required_skills"] == ["Python"]
    assert normalized["required_skill_groups"] is None
    assert normalized["preferred_skills"] is None
    assert normalized["skill_mentions"] == ["LangChain", "LangGraph", "AutoGen"]


def test_normalize_core_fields_recovers_language_group_with_local_signal() -> None:
    normalized = normalize_core_fields(
        {
            "required_skills": ["Python", "C++"],
        },
        source_content=(
            "课题要求：熟练掌握 Python、C/C++ 等至少一种编程语言，"
            "熟悉任务规划与工具调用。"
        ),
    )

    assert normalized["required_skills"] is None
    assert normalized["required_skill_groups"] == [
        {
            "name": "编程语言",
            "any_of": ["Python", "C++"],
            "allow_other": True,
        }
    ]
    assert normalized["skill_mentions"] == ["Python", "C++"]


def test_normalize_core_fields_collapses_model_platform_group_without_or() -> None:
    normalized = normalize_core_fields(
        {
            "required_skill_groups": [
                {
                    "name": "机器人仿真平台",
                    "any_of": ["MuJoCo", "PyBullet", "Isaac Gym"],
                    "allow_other": True,
                }
            ]
        },
        source_content=(
            "职位要求：熟悉与仿真环境（MuJoCo、PyBullet、Isaac Gym等）交互。"
        ),
    )

    assert normalized["required_skills"] == ["机器人仿真平台"]
    assert normalized["required_skill_groups"] is None
    assert normalized["skill_mentions"] == ["MuJoCo", "PyBullet", "Isaac Gym"]


def test_normalize_core_fields_opens_mainstream_parenthetical_group() -> None:
    normalized = normalize_core_fields(
        {
            "required_skill_groups": [
                {
                    "name": "推理框架",
                    "any_of": ["TensorRT", "vLLM"],
                    "allow_other": False,
                }
            ]
        },
        source_content=(
            "职位要求：熟悉至少一种主流推理框架（TensorRT、vLLM）。"
        ),
    )

    assert normalized["required_skill_groups"] == [
        {
            "name": "推理框架",
            "any_of": ["TensorRT", "vLLM"],
            "allow_other": True,
        }
    ]


def test_normalize_core_fields_promotes_required_skill_before_bonus_clause() -> None:
    normalized = normalize_core_fields(
        {
            "preferred_skills": ["Python", "FastAPI"],
        },
        source_content=(
            "职位要求：有 Python 后端开发经验，熟悉 FastAPI 者优先。"
        ),
    )

    assert normalized["required_skills"] == ["Python"]
    assert normalized["preferred_skills"] == ["FastAPI"]


def test_normalize_core_fields_preserves_concrete_inline_bonus_technologies() -> None:
    normalized = normalize_core_fields(
        {
            "required_skills": ["Python"],
            "preferred_skills": ["Web框架", "低代码平台"],
        },
        source_content=(
            "职位要求：有 Python 后端开发经验，熟悉 FastAPI/Flask/Django 等 Web框架的优先；"
            "熟练使用 Coze/Dify 等低代码平台，有完整项目经验的优先。"
        ),
    )

    assert normalized["required_skills"] == ["Python"]
    assert normalized["preferred_skills"] == [
        "FastAPI",
        "Flask",
        "Django",
        "Coze",
        "Dify",
    ]


def test_normalize_core_fields_does_not_recover_unselected_bonus_section() -> None:
    normalized = normalize_core_fields(
        {
            "required_skills": ["CUDA"],
            "required_skill_groups": [
                {
                    "name": "推理框架",
                    "any_of": ["TVM", "vLLM"],
                    "allow_other": True,
                }
            ],
            "preferred_skills": [],
        },
        source_content=(
            "任职要求：熟悉至少一种主流推理框架（TVM/vLLM）。\n"
            "加分项\n"
            "熟悉 PagedAttention/FlashAttention/Speculative Decoding/KV-Cache 优化；\n"
            "有自定义 GPU/NPU 算子开发或编译器（TVM/Triton/MLIR）二次开发经验。"
        ),
    )

    assert normalized["preferred_skills"] is None


def test_normalize_core_fields_recovers_only_explicit_bonus_capabilities() -> None:
    normalized = normalize_core_fields(
        {
            "preferred_skills": [
                "大模型应用",
                "VLM",
                "Robot Foundation Model",
                "OpenVLA",
            ],
        },
        source_content=(
            "职位要求：掌握 Python。\n"
            "加分项\n"
            "有完整的 Agent、大模型应用或复杂软件系统项目经验；\n"
            "有智能体评测相关项目经历；\n"
            "有 VLA/VLM、World Model/Robot Foundation Model 相关经验。"
        ),
    )

    assert normalized["preferred_skills"] == [
        "大模型应用",
        "VLM",
        "Robot Foundation Model",
        "OpenVLA",
        "Agent项目",
        "Agent评测",
        "World Model",
        "VLA",
    ]


def test_normalize_core_fields_recovers_world_model_capability_not_examples() -> None:
    normalized = normalize_core_fields(
        {"preferred_skills": ["开源框架贡献"]},
        source_content=(
            "职位要求：掌握 PyTorch。\n"
            "加分项\n"
            "复现或主导过 Sora/Cosmos 等世界模型类工作；\n"
            "熟悉 Nerfstudio 等开源框架并有核心贡献。"
        ),
    )

    assert normalized["preferred_skills"] == ["开源框架贡献", "世界模型复现"]
    assert normalized["skill_mentions"] is None


def test_normalize_core_fields_infers_environment_tool_group() -> None:
    normalized = normalize_core_fields(
        {
            "required_skills": ["Linux", "Conda", "Docker", "训练环境"],
        },
        source_content=(
            "职位要求\n【必须要求】\n"
            "熟悉 Linux、Git、conda/docker 和服务器训练环境。"
        ),
    )

    assert normalized["required_skills"] == ["Linux", "训练环境"]
    assert normalized["required_skill_groups"] == [
        {
            "name": "环境管理工具",
            "any_of": ["Conda", "Docker"],
            "allow_other": False,
        }
    ]
    assert normalized["skill_mentions"] == ["Conda", "Docker"]


def test_normalize_core_fields_recovers_explicit_tactile_alternative_group() -> None:
    normalized = normalize_core_fields(
        {
            "required_skills": ["实验设计"],
            "required_skill_groups": [
                {
                    "name": "深度学习框架",
                    "any_of": ["PyTorch"],
                    "allow_other": True,
                }
            ],
        },
        source_content=(
            "职位要求\n【必须要求】\n"
            "熟悉 PyTorch 或其他深度学习框架。\n"
            "对机器人触觉感知或接触操作有基本理解。"
        ),
    )

    assert normalized["required_skill_groups"] == [
        {
            "name": "深度学习框架",
            "any_of": ["PyTorch"],
            "allow_other": True,
        },
        {
            "name": "触觉/接触基础",
            "any_of": ["触觉感知", "接触操作"],
            "allow_other": False,
        },
    ]
    assert normalized["skill_mentions"] == ["PyTorch", "触觉感知", "接触操作"]


def test_normalize_core_fields_recovers_experiment_result_and_demotes_concepts() -> None:
    normalized = normalize_core_fields(
        {
            "required_skills": [
                "实验设计",
                "baseline",
                "control group",
                "变量控制",
                "指标对比",
            ],
        },
        source_content=(
            "职位要求\n【必须要求】\n"
            "能够设计基本的 ablation 实验，理解 baseline、control group、"
            "变量控制和指标对比。能够分析训练及真机实验结果。"
        ),
    )

    assert normalized["required_skills"] == ["实验设计", "实验结果分析"]
    assert normalized["skill_mentions"] == [
        "baseline",
        "control group",
        "变量控制",
        "指标对比",
    ]


def test_normalize_core_fields_collapses_evaluation_pipeline_and_deployment_alias() -> None:
    normalized = normalize_core_fields(
        {
            "required_skills": [
                "重建",
                "生成",
                "评测",
                "真机部署",
            ],
        },
        source_content=(
            "任职要求：能独立完成‘重建-生成-评测’链路；"
            "具备真实机器人项目经验，能够完成真机部署。"
        ),
    )

    assert normalized["required_skills"] == ["机器人部署", "模型评测"]


def test_normalize_core_fields_demotes_low_strength_requirements() -> None:
    normalized = normalize_core_fields(
        {
            "required_skills": [
                "编程基础",
                "Prompt Engineering",
                "结构化输出",
                "Tool Calling",
                "多轮对话",
                "Agent",
                "任务规划",
            ],
        },
        source_content=(
            "职位要求\n"
            "具备扎实的编程基础。\n"
            "了解大模型应用开发，对提示词设计、结构化输出、工具调用、"
            "多轮对话等基本机制有一定理解。\n"
            "了解 Agent 的基本组成，对任务规划等概念有基础认知。"
        ),
    )

    assert normalized["required_skills"] == ["编程基础"]
    assert normalized["skill_mentions"] == [
        "Prompt Engineering",
        "结构化输出",
        "Tool Calling",
        "多轮对话",
        "Agent",
        "任务规划",
    ]


def test_normalize_core_fields_rejects_or_outside_skill_options() -> None:
    normalized = normalize_core_fields(
        {
            "required_skill_groups": [
                {
                    "name": "AI 相关领域",
                    "any_of": ["计算机视觉", "NLP", "LLM", "机器人"],
                    "allow_other": True,
                }
            ]
        },
        source_content=(
            "职位要求：具有计算机视觉、自然语言处理、大模型、机器人等相关"
            "研究或工程经验。"
        ),
    )

    assert normalized["required_skill_groups"] is None
    assert normalized["skill_mentions"] == ["计算机视觉", "NLP", "LLM", "机器人"]


def test_normalize_core_fields_keeps_group_signaled_by_preceding_heading() -> None:
    normalized = normalize_core_fields(
        {
            "required_skill_groups": [
                {
                    "name": "具身算法方向",
                    "any_of": [
                        "具身策略/VLA/Robot Policy",
                        "Sensorimotor/灵巧操作",
                        "System 0/高频控制",
                    ],
                    "allow_other": False,
                }
            ]
        },
        source_content=(
            "职位要求\n"
            "以下方向满足其中一项或多项即可：\n"
            "1. 具身策略 / VLA / Robot Policy：研究策略学习。\n"
            "2. Sensorimotor / 灵巧操作：研究触觉反馈。\n"
            "3. System 0 / 高频控制：研究实时控制。"
        ),
    )

    assert normalized["required_skill_groups"] is not None
    assert normalized["required_skill_groups"][0]["name"] == "具身算法方向"


def test_low_strength_clause_is_not_overridden_by_inline_bonus() -> None:
    normalized = normalize_core_fields(
        {"required_skills": ["Context Engineering"]},
        source_content=(
            "职位要求\n"
            "对上下文管理有基础认知。\n"
            "6. 加分项：有完整 Agent 项目经验；有上下文优化相关实践经验。"
        ),
    )

    assert normalized["required_skills"] is None
    assert normalized["skill_mentions"] == ["Context Engineering"]


def test_normalize_core_fields_demotes_bonus_examples_and_non_skills() -> None:
    normalized = normalize_core_fields(
        {
            "preferred_skills": [
                "世界模型复现",
                "Sora",
                "Cosmos",
                "开源框架贡献",
                "Nerfstudio",
                "在 CVPR 发表论文",
            ],
        },
        source_content=(
            "职位要求：掌握 PyTorch。\n"
            "加分项\n"
            "复现或主导过 Sora/Cosmos 等世界模型类工作；\n"
            "熟悉 Nerfstudio 等开源框架并有核心贡献；\n"
            "在 CVPR 发表论文。"
        ),
    )

    assert normalized["preferred_skills"] == ["世界模型复现", "开源框架贡献"]
    assert normalized["skill_mentions"] == ["Sora", "Cosmos", "Nerfstudio"]


def test_normalize_core_fields_keeps_act_out_of_tactile_device_clause() -> None:
    normalized = normalize_core_fields(
        {"preferred_skills": ["ACT", "GelSight", "机器人数据采集系统"]},
        source_content=(
            "职位要求：熟悉 PyTorch。\n"
            "加分项\n"
            "熟悉 GelSight 等 tactile 设备；\n"
            "有 ACT、LeRobot 等策略训练经验；\n"
            "有机器人数据采集系统或实验报告写作经验。"
        ),
    )

    assert normalized["preferred_skills"] == ["ACT", "机器人数据采集"]
    assert normalized["skill_mentions"] == ["GelSight"]


def test_normalize_core_fields_merges_bonus_composites_and_drops_parents() -> None:
    normalized = normalize_core_fields(
        {
            "preferred_skills": [
                "Agent",
                "Agent项目",
                "LLM",
                "大模型应用",
                "力觉",
                "触觉",
            ]
        },
        source_content=(
            "职位要求：掌握 Python。\n"
            "加分项\n"
            "有完整 Agent 项目或大模型应用经验；\n"
            "有灵巧手、力觉/触觉相关经验。"
        ),
    )

    assert normalized["preferred_skills"] == [
        "Agent项目",
        "大模型应用",
        "力觉/触觉",
    ]


def test_normalize_core_fields_promotes_explicit_understanding_requirement() -> None:
    normalized = normalize_core_fields(
        {
            "required_skills": ["CUDA"],
            "skill_mentions": ["Transformer", "Diffusion", "VLM"],
        },
        source_content=(
            "任职要求：掌握 CUDA；理解 Transformer、Diffusion、VLM 模型结构与典型推理瓶颈。"
        ),
    )

    assert normalized["required_skills"] == [
        "CUDA",
        "Transformer",
        "Diffusion",
        "VLM",
    ]
    assert normalized["skill_mentions"] is None


def test_normalize_core_fields_recovers_strong_agent_requirements_generically() -> None:
    normalized = normalize_core_fields(
        {
            "required_skills": [
                "LLM",
                "Agent",
                "数据分析",
                "实验设计",
                "Bad Case 定位",
                "Python",
            ],
            "preferred_skills": [
                "Redis",
                "数据库",
                "PostgreSQL",
                "消息队列",
                "分布式系统",
                "云原生",
                "LangGraph",
                "LangChain",
                "LlamaIndex",
                "OpenClaw",
                "Hermes",
                "Pi",
                "Agent Harness",
            ],
            "skill_mentions": [
                "Context Engineering",
                "Tool Calling",
                "Planning",
                "Memory",
                "RAG",
                "Skill",
            ],
        },
        source_content=(
            "职位要求\n"
            "对 LLM Agent 的基本运行机制有深入理解，熟悉 Agent Runtime、"
            "Context Engineering、Tool Calling、Planning、Memory、RAG、Skill 等核心技术。\n"
            "能够独立设计和实现 Agent 的评测与优化体系，具备较强的数据分析、"
            "实验设计及 Bad Case 定位能力。\n"
            "具备 Python 编程能力，熟悉常见 Agent / LLM 技术栈；"
            "具备 Redis、向量数据库、PostgreSQL、消息队列、分布式系统或云原生开发经验者优先。\n"
            "有 LangGraph、LangChain、LlamaIndex、OpenClaw、Hermes、Pi 或"
            "自研 Agent Harness / Runtime 等项目实践经验者优先。\n"
            "有生产级 Agent 平台或复杂 AI 系统经验者优先。"
        ),
    )

    assert set(normalized["required_skills"] or []) == {
        "LLM Agent",
        "Agent Runtime",
        "Context Engineering",
        "Tool Calling",
        "Planning",
        "Memory",
        "RAG",
        "Skill",
        "Agent评测",
        "数据分析",
        "实验设计",
        "Bad Case 定位",
        "Python",
    }
    assert set(normalized["preferred_skills"] or []) == {
        "Redis",
        "向量数据库",
        "PostgreSQL",
        "消息队列",
        "分布式系统",
        "云原生开发",
        "LangGraph",
        "LangChain",
        "LlamaIndex",
        "OpenClaw",
        "Hermes",
        "Pi",
        "Agent Harness",
        "生产级Agent平台",
    }


def test_normalize_core_fields_promotes_same_semantics_across_jds() -> None:
    normalized = normalize_core_fields(
        {"skill_mentions": ["RAG", "Memory", "Tool Calling"]},
        source_content=(
            "任职要求：熟练掌握 RAG、Memory 与 Tool Calling，并能用于业务系统。"
        ),
    )

    assert normalized["required_skills"] == ["RAG", "Memory", "Tool Calling"]
    assert normalized["skill_mentions"] is None


def test_normalize_core_fields_keeps_mixed_strength_scopes_idempotent() -> None:
    source_content = (
        "任职要求：熟悉主流大模型的 API 调用和 Prompt Engineering，了解 RAG。"
    )
    first = normalize_core_fields(
        {
            "required_skills": ["LLM API"],
            "skill_mentions": ["Prompt Engineering", "RAG"],
        },
        source_content=source_content,
    )
    second = normalize_core_fields(first, source_content=source_content)

    assert first == second
    assert first["required_skills"] == ["LLM API", "Prompt Engineering"]
    assert first["skill_mentions"] == ["RAG"]


def test_normalize_core_fields_does_not_promote_weak_agent_requirements() -> None:
    normalized = normalize_core_fields(
        {"skill_mentions": ["Context Engineering", "Planning"]},
        source_content=(
            "职位要求：了解 Context Engineering；对 Planning 有基础认知。"
        ),
    )

    assert normalized["required_skills"] is None
    assert normalized["skill_mentions"] == ["Context Engineering", "Planning"]


def test_normalize_core_fields_does_not_promote_bonus_skills() -> None:
    normalized = normalize_core_fields(
        {
            "required_skills": ["Python"],
            "skill_mentions": ["RAG", "Memory"],
        },
        source_content=(
            "职位要求：掌握 Python。\n"
            "加分项：熟悉 RAG、Memory。"
        ),
    )

    assert normalized["required_skills"] == ["Python"]
    assert normalized["skill_mentions"] == ["RAG", "Memory"]


def test_normalize_core_fields_keeps_strong_alternatives_in_any_of() -> None:
    normalized = normalize_core_fields(
        {
            "required_skill_groups": [
                {
                    "name": "检索或记忆能力",
                    "any_of": ["RAG", "Memory"],
                    "allow_other": False,
                }
            ],
            "skill_mentions": ["RAG", "Memory"],
        },
        source_content="职位要求：熟悉 RAG 或 Memory 至少一种。",
    )

    assert normalized["required_skills"] is None
    assert normalized["required_skill_groups"] == [
        {
            "name": "检索或记忆能力",
            "any_of": ["RAG", "Memory"],
            "allow_other": False,
        }
    ]
    assert normalized["skill_mentions"] == ["RAG", "Memory"]


def test_normalize_core_fields_keeps_open_ended_examples_as_mentions() -> None:
    normalized = normalize_core_fields(
        {
            "required_skills": ["Agent"],
            "skill_mentions": ["RAG", "Memory"],
        },
        source_content=(
            "职位要求：掌握 Agent 核心技术，包括但不限于 RAG、Memory。"
        ),
    )

    assert normalized["required_skills"] == ["Agent"]
    assert normalized["skill_mentions"] == ["RAG", "Memory"]


def test_normalize_core_fields_prefers_mandatory_occurrence_over_bonus() -> None:
    normalized = normalize_core_fields(
        {
            "required_skills": ["数据结构", "算法"],
            "preferred_skills": ["Agent", "Kubernetes"],
        },
        source_content=(
            "职位要求：掌握数据结构与算法；实际使用并开发过 AI Agent 产品。\n"
            "加分项\n有 Agent 应用开发经验；熟悉 Kubernetes 者优先。"
        ),
    )

    assert normalized["required_skills"] == ["数据结构与算法", "Agent"]
    assert normalized["preferred_skills"] == ["Kubernetes"]


def test_normalize_core_fields_demotes_markdown_bonus_only_skills() -> None:
    normalized = normalize_core_fields(
        {
            "required_skills": ["Python", "ROS", "VLA", "机器人Agent"],
        },
        source_content=(
            "职位要求：熟练使用 Python，具备 Agent 项目经验。\n"
            "## 加分项\n"
            "熟悉 ROS，具备 VLA 或机器人 Agent 相关经验。"
        ),
    )

    assert normalized["required_skills"] == ["Python"]
    assert normalized["preferred_skills"] == ["ROS", "VLA", "机器人Agent"]


def test_normalize_core_fields_repairs_robotics_aliases_and_bonus_skill() -> None:
    normalized = normalize_core_fields(
        {
            "required_skills": [
                "MDP建模",
                "运动学",
                "动力学",
                "数值计算方法",
                "科学计算库",
            ],
            "skill_mentions": ["Eigen", "NumPy"],
        },
        source_content=(
            "职位要求\n"
            "熟悉MDP建模；熟悉机器人学与传统运控（运控规划、运动学、动力学等）。\n"
            "掌握最优化与数值计算方法；熟悉Eigen、NumPy等科学计算库。\n"
            "优先条件\n"
            "具有复杂多体系统的强化学习运动控制经验者优先。"
        ),
    )

    assert normalized["required_skills"] == [
        "MDP",
        "机器人运动学",
        "机器人动力学",
        "数值计算",
        "Eigen",
        "NumPy",
    ]
    assert normalized["preferred_skills"] == ["复杂多体系统强化学习运动控制"]
    assert normalized["skill_mentions"] is None


def test_normalize_core_fields_recovers_robotics_foundation_group_and_loop() -> None:
    normalized = normalize_core_fields(
        {
            "required_skills": [
                "机器学习",
                "深度学习",
                "Python",
                "C++",
                "PyTorch",
            ],
            "required_skill_groups": [
                {
                    "name": "机器人学或控制理论",
                    "any_of": ["机器人学", "控制理论"],
                    "allow_other": False,
                }
            ],
            "preferred_skills": [
                "Robot Foundation Model",
                "大规模机器人策略训练",
                "双臂协作",
                "World Model",
                "VLA",
            ],
            "skill_mentions": ["机器人部署", "机器人学", "控制理论"],
        },
        source_content=(
            "职位要求\n"
            "具备扎实的机器学习、深度学习、机器人学或控制理论基础。\n"
            "熟练掌握 Python / C++ / PyTorch。\n"
            "有真实机器人项目经验，能够完成从算法研究、模型训练到真机部署"
            "和问题定位的完整闭环。\n"
            "加分项：\n"
            "有VLA、World Model、Robot Foundation Model或大规模机器人策略训练经验。\n"
            "有大规模真实机器人数据采集、训练和评测经验。\n"
            "有灵巧手、力觉/触觉、双臂协作或Contact-rich manipulation经验。"
        ),
    )

    assert normalized["required_skills"] == [
        "Python",
        "C++",
        "PyTorch",
        "机器人部署",
        "问题定位",
    ]
    assert normalized["required_skill_groups"] == [
        {
            "name": "机器人算法基础",
            "any_of": ["机器学习", "深度学习", "机器人学", "控制理论"],
            "allow_other": False,
        }
    ]
    assert {
        "VLA",
        "World Model",
        "Robot Foundation Model",
        "大规模机器人策略训练",
        "大规模机器人数据",
        "灵巧手",
        "力觉/触觉",
        "双臂协作",
        "Contact-rich Manipulation",
    } == set(normalized["preferred_skills"] or [])


def test_normalize_core_fields_recovers_embodied_agent_terms_and_groups() -> None:
    normalized = normalize_core_fields(
        {
            "required_skills": ["LLM", "Agent", "Prompt Engineering", "Tool Calling"],
            "required_skill_groups": [
                {
                    "name": "任务与运动规划相关方向",
                    "any_of": [
                        "任务与运动规划 TAMP",
                        "符号推理",
                        "几何推理",
                        "Learning-based Planning",
                    ],
                    "allow_other": False,
                },
                {
                    "name": "具身 Agent 相关经验",
                    "any_of": [
                        "机器人部署",
                        "完整具身Agent项目",
                        "Agent项目",
                        "LeRobot",
                    ],
                    "allow_other": False,
                },
            ],
        },
        source_content=(
            "职位要求\n"
            "深入理解 LLM Agent 架构，具备 Prompt Engineering、Function Calling、"
            "Tool Use、Agent Workflow 工程经验。\n"
            "掌握任务与运动规划 TAMP、符号推理、几何推理或 "
            "Learning-based Planning 至少一个方向。\n"
            "有从任务定义、环境交互到真实机器人部署的完整具身 Agent 项目经验，"
            "或参与过 LeRobot、Open X-Embodiment、GR00T、Meta-World、CALVIN 等开源项目。"
        ),
    )

    assert normalized["required_skills"] == [
        "LLM Agent",
        "Prompt Engineering",
        "Tool Calling",
        "Agent Workflow",
        "具身Agent",
    ]
    assert normalized["required_skill_groups"] == [
        {
            "name": "任务与运动规划方向",
            "any_of": ["TAMP", "符号推理", "几何推理", "Learning-based Planning"],
            "allow_other": False,
        },
        {
            "name": "具身Agent项目经历",
            "any_of": [
                "完整具身Agent项目",
                "LeRobot",
                "Open X-Embodiment",
                "GR00T",
                "Meta-World",
                "CALVIN",
            ],
            "allow_other": False,
        },
    ]


def test_normalize_core_fields_recovers_agentic_rl_requirements() -> None:
    normalized = normalize_core_fields(
        {
            "required_skills": [
                "大规模训练",
                "低延迟推理系统",
                "分布式架构设计",
            ],
            "required_skill_groups": [
                {
                    "name": "编程语言",
                    "any_of": ["Python", "C++", "Rust"],
                    "allow_other": False,
                },
                {
                    "name": "智能体相关方向",
                    "any_of": ["强化学习", "Tool Calling", "工具调用Agent", "Agent"],
                    "allow_other": False,
                },
            ],
            "skill_mentions": [
                "强化学习",
                "策略梯度",
                "Actor-Critic",
                "Self-Play",
                "MARL",
                "系统编程",
            ],
        },
        source_content=(
            "职位要求\n"
            "精通强化学习，包括策略梯度、Actor-Critic、Self-Play、Meta-RL、MARL。\n"
            "具备千卡级训练与低延迟推理系统的落地经验。\n"
            "具备 Python、C++ 或 Rust 系统级编程与分布式架构设计能力。\n"
            "有 Agentic RL、工具调用 Agent 或多智能体系统的发表或上线记录。\n"
            "有代码沙箱、程序合成、仿真器安全相关经验者优先。"
        ),
    )

    assert set(normalized["required_skills"] or []) == {
        "强化学习",
        "策略梯度",
        "Actor-Critic",
        "Self-Play",
        "Meta-RL",
        "MARL",
        "大规模训练",
        "低延迟推理",
        "系统编程",
        "分布式架构",
    }
    assert normalized["required_skill_groups"] == [
        {
            "name": "编程语言",
            "any_of": ["Python", "C++", "Rust"],
            "allow_other": False,
        },
        {
            "name": "Agent系统经历",
            "any_of": ["Agentic RL", "工具调用Agent", "多智能体系统"],
            "allow_other": False,
        },
    ]


def test_normalize_skill_fields_keeps_requirements_as_source_of_truth() -> None:
    payload = {
        "required_skills": ["RAG、Agent、Prompt Engineering"],
        "requirements": [
            {
                "category": "required_skill",
                "name": "RAG、Agent、Prompt Engineering",
                "description": "熟悉 RAG、Agent、Prompt Engineering",
                "mandatory": True,
                "evidence": [
                    {
                        "field_path": "requirements[0]",
                        "source_text": "熟悉 RAG、Agent、Prompt Engineering",
                    }
                ],
            }
        ],
    }

    normalized = normalize_skill_fields(payload)

    assert normalized["required_skills"] == [
        "RAG",
        "Agent",
        "Prompt Engineering",
    ]
    assert [item["name"] for item in normalized["requirements"]] == [
        "RAG",
        "Agent",
        "Prompt Engineering",
    ]


def test_normalize_skill_fields_does_not_promote_requirement_description() -> None:
    payload = {
        "requirements": [
            {
                "category": "required_skill",
                "name": "Agent",
                "description": "具备 AI 系统调优与集成能力，可进行模型调参",
                "mandatory": True,
                "evidence": [
                    {
                        "field_path": "requirements[0]",
                        "source_text": "熟悉 Agent",
                    }
                ],
            }
        ],
    }

    normalized = normalize_skill_fields(payload)

    assert normalized["required_skills"] == ["Agent"]


def test_normalize_skill_fields_recovers_explicit_source_skills() -> None:
    source = (
        "AI能力要求：理解 AI 能力的边界与应用潜力，能够设计以 AI 为核心或 "
        "AI 增强型的产品 / 方案；熟悉行业主流 AI 产品、技术趋势与最佳实践。"
    )

    normalized = normalize_skill_fields(
        {
            "required_skills": ["AI产品/方案设计"],
            "field_evidence": [
                {"field_path": "required_skills", "source_text": "产品 / 方案"}
            ],
        },
        source_content=source,
    )

    assert normalized["required_skills"] == [
        "AI能力边界理解",
        "AI产品/方案设计",
        "AI产品技术趋势",
        "AI产品最佳实践",
    ]


def test_normalize_skill_values_canonicalizes_cross_language_aliases() -> None:
    assert normalize_skill_values(
        [
            "JS",
            "Golang",
            "工具/函数调用",
            "扩散模型",
            "模仿学习",
            "大语言模型相关技术",
            "世界模型 + 策略",
            "自动化标注",
            "检测",
        ]
    ) == [
        "JavaScript",
        "Go",
        "Tool Calling",
        "Diffusion",
        "Imitation Learning",
        "LLM",
        "World Model",
        "自动标注",
        "目标检测",
    ]


def test_atomic_skill_normalization_preserves_distinct_compound_labels() -> None:
    assert normalize_atomic_skill_values(
        [
            "AI Coding工具使用",
            "AI Coding项目",
            "工业级基础大模型研发",
            "BC",
        ]
    ) == [
        "AI Coding工具使用",
        "AI Coding项目",
        "工业级基础大模型研发",
        "Behavior Cloning",
    ]


def test_atomic_skill_normalization_preserves_semantic_qualifiers() -> None:
    assert normalize_atomic_skill_values(
        ["多模态大模型", "多模态模型", "模仿学习", "世界模型", "C/C++"]
    ) == [
        "多模态大模型",
        "多模态模型",
        "Imitation Learning",
        "World Model",
        "C++",
    ]


def test_atomic_skill_normalization_applies_domain_safe_aliases() -> None:
    assert normalize_atomic_skill_values(
        [
            "大模型",
            "微调",
            "AI相关项目",
            "数据提质",
            "多Agent",
            "工具调用",
            "分布式机器学习经验",
            "微调方法",
            "电生理信号相关项目经历",
            "ROS框架",
            "Physical AI/具身智能安全",
            "Physical AI/具身智能安全开源项目",
            "SRC漏洞",
        ]
    ) == [
        "LLM",
        "模型微调",
        "AI项目",
        "数据质量",
        "Multi-Agent",
        "Tool Calling",
        "分布式机器学习",
        "电生理信号项目",
        "ROS",
        "Physical AI安全",
        "Physical AI安全开源项目",
        "漏洞挖掘",
    ]


def test_system_group_normalizes_network_without_global_aliasing() -> None:
    assert normalize_skill_groups(
        [
            {
                "name": "系统基础",
                "any_of": ["操作系统", "网络", "数据库"],
                "allow_other": False,
            }
        ]
    ) == [
        {
            "name": "系统基础",
            "any_of": ["操作系统", "计算机网络", "数据库"],
            "allow_other": False,
        }
    ]
    assert normalize_atomic_skill_values(["网络"]) == ["网络"]

    assert normalize_skill_groups(
        [
            {
                "name": "计算机基础",
                "any_of": ["操作系统", "网络", "数据库"],
                "allow_other": False,
            }
        ]
    )[0]["any_of"] == ["操作系统", "计算机网络", "数据库"]


def test_atomic_skill_normalization_uses_concise_equivalent_names() -> None:
    assert normalize_atomic_skill_values(
        [
            "机器学习理论",
            "Transformer架构",
            "Multi-Agent系统搭建实践经验",
            "Kubernetes基础原理",
            "在离线混部",
            "有限元方法",
        ]
    ) == [
        "机器学习",
        "Transformer",
        "Multi-Agent系统搭建",
        "Kubernetes",
        "在线离线混部",
        "有限元",
    ]


def test_cae_category_keeps_upper_category_distinct_from_examples() -> None:
    assert normalize_atomic_skill_values(["CAE工具使用"]) == ["CAE工具使用"]
    assert normalize_atomic_skill_values(["Ansys", "Abaqus"]) == [
        "Ansys",
        "Abaqus",
    ]


def test_atomic_skill_normalization_strips_evidence_suffix_from_known_skill() -> None:
    assert normalize_atomic_skill_values(
        ["LangChain经验", "全栈开发经验", "Garak经历"]
    ) == ["LangChain", "全栈开发", "Garak"]


def test_atomic_skill_normalization_uses_source_backed_model_prefixes() -> None:
    assert normalize_atomic_skill_values(
        ["量化", "剪枝", "蒸馏"],
        source_text="熟悉量化、剪枝、蒸馏等模型小型化技术",
    ) == ["模型量化", "模型剪枝", "模型蒸馏"]


def test_atomic_skill_normalization_aligns_group_option_spacing() -> None:
    assert normalize_atomic_skill_values(["Agent 应用"]) == ["Agent应用"]


def test_atomic_skill_normalization_aligns_mechanical_analysis_names() -> None:
    assert normalize_atomic_skill_values(
        ["结构件疲劳", "结构件失效模式"]
    ) == ["疲劳分析", "失效分析"]


def test_extract_skill_matches_does_not_quantize_mechanical_lightweight_design() -> None:
    labels = {
        match.canonical
        for match in extract_skill_matches(
            "有复杂装配设计、轻量化设计或真实样机闭环经验。"
        )
    }

    assert "模型量化" not in labels


def test_normalize_core_fields_recovers_wrapped_alternatives_from_mentions() -> None:
    normalized = normalize_core_fields(
        {
            "required_skills": ["数据结构与算法"],
            "skill_mentions": [
                "C++",
                "Python",
                "TensorFlow",
                "PyTorch",
                "MNN",
            ],
        },
        source_content=(
            "任职要求\n"
            "至少熟悉 C++/Python 中的一种开发语言，熟悉数据结构与算法；\n"
            "熟悉任意机器学习推理训练框架（TensorFlow, PyTorch, MNN等）。"
        ),
    )

    assert normalized["required_skills"] == ["数据结构与算法"]
    assert normalized["required_skill_groups"] == [
        {
            "name": "编程语言",
            "any_of": ["C++", "Python"],
            "allow_other": False,
        },
        {
            "name": "机器学习推理训练框架",
            "any_of": ["TensorFlow", "PyTorch", "MNN"],
            "allow_other": True,
        },
    ]


def test_normalize_core_fields_recovers_one_or_more_mixed_stack_options() -> None:
    normalized = normalize_core_fields(
        {
            "skill_mentions": ["React", "NodeJS", "Golang"],
        },
        source_content=(
            "职位要求：熟悉 React、NodeJS、Golang 等主流技术栈中的一种或多种。"
        ),
    )

    assert normalized["required_skills"] is None
    assert normalized["required_skill_groups"] == [
        {
            "name": "主流技术栈",
            "any_of": ["React", "Node.js", "Go"],
            "allow_other": True,
        }
    ]
    assert normalized["skill_mentions"] == ["React", "Node.js", "Go"]


def test_normalize_core_fields_aligns_group_name_and_drops_with_examples() -> None:
    normalized = normalize_core_fields(
        {
            "required_skill_groups": [
                {
                    "name": "编程语言",
                    "any_of": ["MATLAB/Simulink", "Python", "NumPy"],
                    "allow_other": False,
                }
            ],
        },
        source_content=(
            "职位要求：熟悉至少一种主流仿真工具"
            "（如 MATLAB/Simulink, Python with Scipy/NumPy）。"
        ),
    )

    assert normalized["required_skill_groups"] == [
        {
            "name": "仿真工具",
            "any_of": ["MATLAB", "Simulink", "Python"],
            "allow_other": True,
        }
    ]


def test_normalize_core_fields_recovers_explicit_bonus_capabilities() -> None:
    normalized = normalize_core_fields(
        {"preferred_skills": []},
        source_content=(
            "任职要求：掌握 Python。\n"
            "加分项\n"
            "有 AI/大模型产品相关实习经历者优先；\n"
            "对主流开源框架有深入了解，并有实质性贡献；\n"
            "有万卡规模训练系统或大规模 RLHF/RLVR 工程的实战经验。"
        ),
    )

    assert normalized["preferred_skills"] == [
        "AI产品实践",
        "开源框架贡献",
        "大规模训练",
        "RLHF",
        "RLVR",
    ]
