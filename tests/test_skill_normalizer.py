from src.domain.skill_normalizer import normalize_skill_fields, normalize_skill_values


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
