from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.domain.eligibility import EligibilityCheck, EligibilityResult
from src.domain.job import JobRequirement, RawJobDocument
from src.domain.matching import EvidenceRecord
from src.domain.product_jd import (
    ProductJDModelOutput,
    ProductJobFacts,
    ProductRequirement,
    sanitize_product_jd_payload,
    validate_product_jd_output,
)
from src.infrastructure.llm_client import FakeModelClient
from src.services.jd_parser import JDParserError
from src.services.job_decision import build_job_decision
from src.services.local_evidence_matcher import (
    match_requirement_locally,
    match_requirements_locally,
)
from src.services.product_jd_parser import ProductJDParser

RAW_JD = (
    "某公司招聘2027届AI实习生，工作地点北京。本科及以上学历，计算机相关专业。"
    "要求熟悉 Python、Java 或 Go 中至少一种语言。熟悉 RAG 优先。"
    "负责大模型应用开发。"
)


def product_output() -> dict[str, object]:
    return {
        "facts": {
            "job_type": {"value": "internship", "source_text": "AI实习生"},
            "locations": {"values": ["北京"], "source_text": "工作地点北京"},
            "graduation_years": {"values": [2027], "source_text": "2027届"},
            "education_requirements": {
                "values": ["本科及以上"],
                "source_text": "本科及以上学历",
            },
            "major_requirements": {
                "values": ["计算机相关专业"],
                "source_text": "计算机相关专业",
            },
        },
        "requirements": [
            {
                "source_text": "要求熟悉 Python、Java 或 Go 中至少一种语言",
                "level": "required",
                "relation": "any_of",
                "items": ["Python", "Java", "Go"],
            },
            {
                "source_text": "熟悉 RAG 优先",
                "level": "preferred",
                "relation": "all_of",
                "items": ["RAG"],
            },
        ],
        "responsibilities": ["负责大模型应用开发"],
    }


def extraction_output() -> dict[str, object]:
    output = product_output()
    return {
        "facts": output["facts"],
        "requirements": [
            {
                "source_text": requirement["source_text"],
                "level": requirement["level"],
            }
            for requirement in output["requirements"]
        ],
        "responsibilities": output["responsibilities"],
    }


def relation_output() -> dict[str, object]:
    output = product_output()
    return {
        "decisions": [
            {
                "requirement_index": index,
                "relation": requirement["relation"],
                "items": requirement["items"],
                "reason": "根据完整原句判断条件关系。",
            }
            for index, requirement in enumerate(output["requirements"])
        ]
    }


def two_stage_client() -> FakeModelClient:
    return FakeModelClient(outputs=[extraction_output(), relation_output()])


def document() -> RawJobDocument:
    return RawJobDocument(
        source_url="https://example.com/jobs/1",
        source_type="manual_text",
        raw_content=RAW_JD,
        source_metadata={"company": "某公司", "title": "AI实习生"},
        retrieved_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_product_parser_uses_small_contract_and_compiles_storage_shape() -> None:
    client = two_stage_client()

    parsed = await ProductJDParser(client, validation_retries=0).parse(document())

    assert len(client.requests) == 2
    assert client.requests[0].schema_name == "product_job_extraction"
    assert client.requests[1].schema_name == "product_requirement_relations"
    system_prompt = client.requests[0].messages[0].content
    assert '"facts": {' in system_prompt
    assert '"level": "required|preferred"' in system_prompt
    assert "facts 必须是对象，不是数组" in system_prompt
    assert "‘欢迎’、‘鼓励’、‘期待’" in system_prompt
    assert "‘XX专业优先’和‘专业不限’" in system_prompt
    assert "本阶段不要判断 all_of、any_of" in system_prompt
    relation_prompt = client.requests[1].messages[0].content
    assert '"relation": "all_of|any_of|uncertain"' in relation_prompt
    assert "不要仅根据逗号、顿号、斜杠或‘或’字机械判断" in relation_prompt
    assert "每条 requirement 必须是一个可以独立判断是否满足的匹配单元" in system_prompt
    assert "同强度、同一能力主题的连续描述默认保留为一条" in system_prompt
    assert "两者完全独立。preferred 绝不等于 uncertain" in relation_prompt
    assert "单一条件一律使用 all_of，即使它是 preferred" in relation_prompt
    assert "all_of 和 uncertain 均使用完整 source_text 作为唯一 item" in relation_prompt
    assert "不能把同一经历的动作方式、认知程度或表达方式" in relation_prompt
    assert "了解或有边缘部署小型化LLM或相关AI模型的经验者优先" in relation_prompt
    assert "局部备选关系不会因为同句还有共享或相邻的共同条件" in relation_prompt
    assert "区分具体资格分支与宽泛领域了解" in relation_prompt
    assert parsed.structured_jd.job_type == "internship"
    assert parsed.structured_jd.locations == ["北京"]
    assert parsed.structured_jd.required_skill_groups[0].any_of == [
        "Python",
        "Java",
        "Go",
    ]
    assert parsed.structured_jd.requirements[0].relation == "any_of"
    assert parsed.structured_jd.requirements[0].relation_reason is not None
    assert parsed.structured_jd.responsibilities == ["负责大模型应用开发"]
    assert parsed.schema_version == "product-job-description-v2"
    assert parsed.parser_version == "product-jd-parser-v3"
    assert parsed.prompt_version == "product-jd-two-stage-v6"


@pytest.mark.asyncio
async def test_product_parser_does_not_override_api_relation_with_local_keywords() -> None:
    extraction = extraction_output()
    extraction["requirements"][0]["source_text"] = "要求熟悉 Python、Java、Go"
    judgment = relation_output()
    inferred_document = document().model_copy(
        update={
            "raw_content": RAW_JD.replace(
                "要求熟悉 Python、Java 或 Go 中至少一种语言",
                "要求熟悉 Python、Java、Go",
            )
        }
    )

    parsed = await ProductJDParser(
        FakeModelClient(outputs=[extraction, judgment]),
        validation_retries=0,
    ).parse(inferred_document)

    requirement = parsed.structured_jd.requirements[0]
    assert requirement.relation == "any_of"
    assert requirement.items == ["Python", "Java", "Go"]


@pytest.mark.asyncio
async def test_product_parser_rejects_incomplete_relation_judgment() -> None:
    client = FakeModelClient(
        outputs=[extraction_output(), {"decisions": [relation_output()["decisions"][0]]}]
    )

    with pytest.raises(JDParserError) as captured:
        await ProductJDParser(client, validation_retries=0).parse(document())

    assert captured.value.code == "product_jd_output_invalid"
    assert captured.value.details["stage"] == "relation_judgment"
    assert captured.value.details["model_call_count"] == 2


@pytest.mark.parametrize(
    "items",
    [
        ["Python"],
        ["Python 语言", "Java"],
        ["Python", "Python"],
        ["Python", ""],
    ],
)
def test_product_sanitizer_downgrades_unreliable_any_of(
    items: list[str],
) -> None:
    source_text = "要求熟悉 Python 或 Java"
    payload = {
        "facts": {},
        "requirements": [
            {
                "source_text": source_text,
                "level": "required",
                "relation": "any_of",
                "items": items,
            }
        ],
        "responsibilities": [],
    }

    sanitized = sanitize_product_jd_payload(payload, source_text)

    assert sanitized["requirements"] == [
        {
            "source_text": source_text,
            "level": "required",
            "relation": "all_of",
            "items": [source_text],
        }
    ]
    assert payload["requirements"][0]["relation"] == "any_of"


def test_product_sanitizer_replaces_rewritten_all_of_items() -> None:
    source_text = "要求熟悉 Python 和 SQL"
    payload = {
        "facts": {},
        "requirements": [
            {
                "source_text": source_text,
                "level": "required",
                "relation": "all_of",
                "items": ["Python 编程", "SQL"],
            }
        ],
        "responsibilities": [],
    }

    sanitized = sanitize_product_jd_payload(payload, source_text)

    assert sanitized["requirements"][0]["items"] == [source_text]


def test_product_sanitizer_drops_content_without_source_support() -> None:
    payload = product_output()
    payload["facts"]["job_type"]["source_text"] = "暑期实习"
    payload["requirements"].append(
        {
            "source_text": "要求五年工作经验",
            "level": "required",
            "relation": "all_of",
            "items": ["五年工作经验"],
        }
    )
    payload["responsibilities"].append("负责训练基础模型")

    sanitized = sanitize_product_jd_payload(payload, RAW_JD)

    assert sanitized["facts"]["job_type"] is None
    assert len(sanitized["requirements"]) == 2
    assert sanitized["responsibilities"] == ["负责大模型应用开发"]


def test_product_sanitizer_drops_fact_with_unsupported_value() -> None:
    payload = product_output()
    payload["facts"]["locations"]["values"] = ["上海"]

    sanitized = sanitize_product_jd_payload(payload, RAW_JD)

    assert sanitized["facts"]["locations"] is None


def test_product_validator_rejects_fact_value_without_source_support() -> None:
    payload = product_output()
    payload["facts"]["major_requirements"]["values"] = ["统计学"]
    output = ProductJDModelOutput.model_validate(payload)

    with pytest.raises(ValueError, match="facts.major_requirements.values"):
        validate_product_jd_output(output, RAW_JD)


@pytest.mark.parametrize(
    ("source_text", "items"),
    [
        ("熟悉至少一门主流编程语言，如 C#、C++、Python", ["C#", "C++", "Python"]),
        ("做过检测、OCR 或 VLM 中的至少一类模型", ["检测", "OCR", "VLM"]),
        ("至少熟悉 C++/Python 中的一种开发语言", ["C++", "Python"]),
        ("熟悉任意机器学习框架（TensorFlow、PyTorch）", ["TensorFlow", "PyTorch"]),
    ],
)
def test_product_validator_accepts_common_explicit_any_of_phrases(
    source_text: str,
    items: list[str],
) -> None:
    output = ProductJDModelOutput(
        facts=ProductJobFacts(),
        requirements=[
            ProductRequirement(
                source_text=source_text,
                level="required",
                relation="any_of",
                items=items,
            )
        ],
    )

    validate_product_jd_output(output, source_text)


@pytest.mark.asyncio
async def test_product_parser_accepts_no_explicit_requirements() -> None:
    output = extraction_output()
    output["requirements"] = []
    client = FakeModelClient(outputs=[output])

    parsed = await ProductJDParser(
        client,
        validation_retries=0,
    ).parse(document())

    assert len(client.requests) == 1
    assert parsed.structured_jd.requirements is None
    assert parsed.structured_jd.responsibilities == ["负责大模型应用开发"]


def test_local_matcher_supports_any_explicit_option_and_abstains_on_missing() -> None:
    requirements = [
        JobRequirement(
            category="required_skill",
            name="Python / Java / Go",
            description="至少熟悉一种语言",
            relation="any_of",
            items=["Python", "Java", "Go"],
        ),
        JobRequirement(
            category="preferred_skill",
            name="RAG",
            description="熟悉 RAG 优先",
            mandatory=False,
            items=["RAG"],
        ),
    ]
    evidence = [
        EvidenceRecord(
            id="evidence_python",
            user_id="user-a",
            title="后端项目",
            claim="使用 Python 开发接口服务。",
            skills=["Python"],
        )
    ]

    matches = match_requirements_locally(
        user_id="user-a",
        requirements=requirements,
        evidence=evidence,
    )

    assert matches[0].support_level == "supported"
    assert matches[0].evidence_ids == ["evidence_python"]
    assert matches[1].support_level == "needs_confirmation"
    assert matches[1].evidence_ids == []


def test_local_matcher_marks_incomplete_all_of_as_partial() -> None:
    requirement = JobRequirement(
        category="required_skill",
        name="Python + SQL",
        description="熟悉 Python 和 SQL",
        items=["Python", "SQL"],
    )
    evidence = [
        EvidenceRecord(
            id="evidence_python",
            user_id="user-a",
            title="后端项目",
            claim="使用 Python 开发接口服务。",
            skills=["Python"],
        )
    ]

    match = match_requirement_locally(
        user_id="user-a",
        requirement=requirement,
        evidence=evidence,
    )

    assert match.support_level == "partial"


def test_local_matcher_abstains_when_relation_is_uncertain() -> None:
    requirement = JobRequirement(
        category="required_skill",
        name="Python / SQL",
        description="熟悉 Python、SQL",
        relation="uncertain",
        items=["Python", "SQL"],
        relation_reason="原文无法说明是全部满足还是任选其一。",
    )
    evidence = [
        EvidenceRecord(
            id="evidence_python",
            user_id="user-a",
            title="后端项目",
            claim="使用 Python 开发接口服务。",
            skills=["Python"],
        )
    ]

    match = match_requirement_locally(
        user_id="user-a",
        requirement=requirement,
        evidence=evidence,
    )

    assert match.support_level == "needs_confirmation"
    assert match.evidence_ids == ["evidence_python"]


def test_decision_prefers_abstention_over_false_precision() -> None:
    eligibility = EligibilityResult(
        eligible="pass",
        checks=[
            EligibilityCheck(
                rule_name="job_type",
                field="job_type",
                result="pass",
                reason="岗位类型符合目标",
            )
        ],
    )
    requirement = JobRequirement(
        category="required_skill",
        name="RAG",
        description="熟悉 RAG",
    )
    match = match_requirement_locally(
        user_id="user-a",
        requirement=requirement,
        evidence=[],
    )

    decision = build_job_decision(eligibility=eligibility, matches=[match])

    assert decision.recommendation == "consider"
    assert decision.needs_confirmation == 1
