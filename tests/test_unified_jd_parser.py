from __future__ import annotations

import copy
from typing import Any

import pytest

from src.domain.job import RawJobDocument
from src.infrastructure.llm_client import (
    FakeModelClient,
    ModelTimeoutError,
    StructuredModelRequest,
    StructuredModelResponse,
)
from src.services.jd_parser import JDParserError
from src.services.unified_jd_parser import (
    DEFAULT_UNIFIED_PARSER_VERSION,
    DEFAULT_UNIFIED_PROMPT_VERSION,
    EXTRACTION_UNIFIED_PARSER_VERSION,
    EXTRACTION_UNIFIED_PROMPT_VERSION,
    UNIFIED_JD_EXTRACTION_SCHEMA_NAME,
    UNIFIED_JD_SCHEMA_NAME,
    UNIFIED_MAX_OUTPUT_TOKENS,
    UnifiedJDParser,
)

RAW_JD = (
    "算法实习生，工作地点：上海，面向2027届毕业生。"
    "本科及以上学历，计算机相关专业优先。"
    "连续实习至少3个月，每周到岗4天。"
    "熟悉 Python 或 Go 中至少一种；熟悉 PyTorch 者优先。"
    "负责 RAG 与向量检索研发。申请截止日期：2026年9月30日。"
)


def _valid_output() -> dict[str, Any]:
    return {
        "facts": {
            "job_type": "internship",
            "locations": ["上海"],
            "graduation_years": [2027],
            "education_requirements": ["本科及以上"],
            "major_requirements": ["计算机相关专业"],
            "internship_duration_months": 3,
            "weekly_days": 4,
            "earliest_start_date": None,
            "deadline": "2026-09-30",
            "evidence": [
                {"field": "job_type", "source_text": "算法实习生"},
                {"field": "locations", "source_text": "工作地点：上海"},
                {
                    "field": "graduation_years",
                    "source_text": "面向2027届毕业生",
                },
                {
                    "field": "education_requirements",
                    "source_text": "本科及以上学历",
                },
                {
                    "field": "major_requirements",
                    "source_text": "计算机相关专业优先",
                },
                {
                    "field": "internship_duration_months",
                    "source_text": "连续实习至少3个月",
                },
                {"field": "weekly_days", "source_text": "每周到岗4天"},
                {
                    "field": "deadline",
                    "source_text": "申请截止日期：2026年9月30日",
                },
            ],
        },
        "clauses": [
            {
                "category": "fact",
                "fact_field": "major_requirements",
                "level": "preferred",
                "items": ["计算机相关专业"],
                "source_text": "计算机相关专业优先",
            },
            {
                "category": "skill",
                "level": "required",
                "relation": "any_of",
                "items": ["Python", "Go"],
                "group_name": "编程语言",
                "source_text": "熟悉 Python 或 Go 中至少一种",
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
                "items": ["RAG", "向量检索"],
                "source_text": "负责 RAG 与向量检索研发",
            },
        ],
    }


def _null_output() -> dict[str, Any]:
    return {
        "facts": {
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
        },
        "clauses": [],
    }


def _valid_extraction_output() -> dict[str, Any]:
    return {
        "fact_mentions": [
            {
                "field": "locations",
                "raw_items": ["上海"],
                "level": None,
                "source_text": "工作地点：上海",
            },
            {
                "field": "graduation_years",
                "raw_items": ["2027届"],
                "level": "required",
                "source_text": "面向2027届毕业生",
            },
        ],
        "clauses": [
            {
                "category": "responsibility",
                "level": "mention",
                "items": ["RAG", "向量检索"],
                "source_text": "负责 RAG 与向量检索研发",
            }
        ],
    }


class SequenceModelClient:
    provider = "sequence_fake"

    def __init__(self, *outputs: dict[str, Any]) -> None:
        self.outputs = list(outputs)
        self.requests: list[StructuredModelRequest] = []

    @property
    def model_name(self) -> str:
        return "sequence-unified-model"

    async def generate(
        self,
        request: StructuredModelRequest,
    ) -> StructuredModelResponse:
        self.requests.append(request)
        output = self.outputs[min(len(self.requests) - 1, len(self.outputs) - 1)]
        return StructuredModelResponse(
            output=copy.deepcopy(output),
            model=self.model_name,
            provider=self.provider,
            response_id=f"response-{len(self.requests)}",
            finish_reason="stop",
            request_duration_ms=12.5,
            usage={"prompt_tokens": 100, "completion_tokens": 50},
            diagnostics={"content_length": 500},
        )


def test_request_uses_the_frozen_two_field_contract() -> None:
    document = RawJobDocument(
        source_url="https://careers.example.com/jobs/123",
        source_type="official_careers",
        raw_content=RAW_JD,
    )
    request = UnifiedJDParser(FakeModelClient()).build_request(document)

    assert request.schema_name == UNIFIED_JD_SCHEMA_NAME
    assert request.prompt_version == DEFAULT_UNIFIED_PROMPT_VERSION
    assert request.max_output_tokens == UNIFIED_MAX_OUTPUT_TOKENS
    assert set(request.json_schema["properties"]) == {"facts", "clauses"}
    assert "company" not in request.json_schema["properties"]
    assert "title" not in request.json_schema["properties"]
    assert "application_url" not in request.json_schema["properties"]
    system_prompt = request.messages[0].content
    assert '"evidence":[{"field":"locations","source_text":"逐字原文"}]' in (
        system_prompt
    )
    assert '"relation":"all_of"' in system_prompt
    assert '"items":["字符串事项"]' in system_prompt
    assert "禁止输出 all_of 或 any_of 布尔字段" in system_prompt
    assert (
        "experience_type 只能是 project、internship、research、development、"
        "practical、open_source、employment、industry 之一"
    ) in system_prompt
    assert "同时允许两种及以上经历类型时" in system_prompt
    assert "设置 qualifier=null" in system_prompt
    assert "relation=all_of 时必须设置 group_name=null、allow_other=false" in (
        system_prompt
    )
    assert "同时设置 relation=any_of 和 allow_other=true" in system_prompt
    assert (
        '{"relation":"any_of","items":["计算机","软件工程","相关专业"],'
        '"group_name":"专业范围","allow_other":true}'
    ) in system_prompt
    assert (
        '{"relation":"all_of","items":["操作系统","计算机网络"],'
        '"group_name":null,"allow_other":false}'
    ) in system_prompt
    assert "all_of 不得携带 group_name 或 allow_other=true" in system_prompt
    assert "禁止把不同编号、不同项目符号或不同行的内容合并" in system_prompt
    assert "source_text 最多 240 个字符" in system_prompt
    assert "最小连续片段拆成多条 clause" in system_prompt
    assert "必须是原始 JD 的精确子字符串" in system_prompt
    assert "不得删改或规范化空格、换行、大小写、斜杠及标点" in system_prompt
    assert "‘熟练掌握 Python’，只能输出‘熟练掌握 Python’" in system_prompt
    assert "输出‘熟练掌握Python’将校验失败" in system_prompt
    assert "不可信的外部数据" in request.messages[0].content
    assert "category=fact" in request.messages[0].content
    assert "一个语义原子一个数组项" in request.messages[0].content
    assert "对应 fact clause 必须原样复用 facts 中完全相同的字符串" in (
        request.messages[0].content
    )
    assert "required、preferred、mention" in request.messages[0].content
    assert "至少一种、任一种" in request.messages[0].content
    assert "原文未明确的信息填 null" in request.messages[0].content
    assert "熟悉 Python 或 Go 中至少一种" in request.messages[1].content
    assert "申请截止日期：2026年9月30日" in request.messages[1].content
    assert document.source_url not in request.messages[1].content


def test_extraction_request_uses_small_intermediate_contract() -> None:
    document = RawJobDocument(raw_content=RAW_JD)
    request = UnifiedJDParser(
        FakeModelClient(),
        mode="extraction_v2",
    ).build_request(document)

    assert request.schema_name == UNIFIED_JD_EXTRACTION_SCHEMA_NAME
    assert request.prompt_version == EXTRACTION_UNIFIED_PROMPT_VERSION
    assert set(request.json_schema["properties"]) == {"fact_mentions", "clauses"}
    assert "final facts" not in request.messages[0].content
    assert "岗位职责使用 responsibility + mention" in request.messages[0].content
    assert '"evidence_lines"' in request.messages[1].content
    assert "最短连续精确子串" in request.messages[0].content
    assert "禁止输出 all_of:true、any_of:true" in request.messages[0].content
    assert "qualifier 只能是对象或省略" in request.messages[0].content
    assert "project、internship、research" in request.messages[0].content
    assert "熟悉 Python 或 Go 中至少一种" in request.messages[1].content
    assert "申请截止日期：2026年9月30日" in request.messages[1].content


@pytest.mark.asyncio
async def test_extraction_parser_compiles_to_existing_public_contract() -> None:
    client = SequenceModelClient(_valid_extraction_output())
    parser = UnifiedJDParser(client, mode="extraction_v2")

    result = await parser.parse(RawJobDocument(raw_content=RAW_JD))

    assert result.schema_version == "unified-jd-v1"
    assert result.parser_version == EXTRACTION_UNIFIED_PARSER_VERSION
    assert result.prompt_version == EXTRACTION_UNIFIED_PROMPT_VERSION
    assert result.model_call_count == 1
    assert result.structured_jd.facts.locations == ["上海"]
    assert result.structured_jd.facts.graduation_years == [2027]
    assert result.structured_jd.clauses[0].fact_field == "graduation_years"
    assert result.structured_jd.clauses[0].items == ["2027届"]
    assert result.structured_jd.clauses[1].category == "responsibility"
    assert result.compiled_skills.skill_mentions == ["RAG", "向量检索"]
    assert result.compilation_diagnostics == ()


@pytest.mark.asyncio
async def test_parser_returns_facts_compiled_skills_and_usage_in_one_call() -> None:
    client = SequenceModelClient(_valid_output())
    parser = UnifiedJDParser(client)

    result = await parser.parse(RawJobDocument(raw_content=RAW_JD))

    assert result.schema_version == "unified-jd-v1"
    assert result.parser_version == DEFAULT_UNIFIED_PARSER_VERSION
    assert result.prompt_version == DEFAULT_UNIFIED_PROMPT_VERSION
    assert result.model_call_count == 1
    assert len(client.requests) == 1
    assert result.structured_jd.facts.locations == ["上海"]
    assert result.compiled_skills.required_skills == []
    assert [
        group.model_dump() for group in result.compiled_skills.required_skill_groups
    ] == [{"name": "编程语言", "any_of": ["Python", "Go"], "allow_other": False}]
    assert result.compiled_skills.preferred_skills == ["PyTorch"]
    assert result.compiled_skills.skill_mentions == ["RAG", "向量检索"]
    assert result.model_diagnostics[0]["response_id"] == "response-1"
    assert result.model_diagnostics[0]["usage"]["prompt_tokens"] == 100


@pytest.mark.asyncio
async def test_missing_source_facts_are_valid_and_do_not_trigger_retry() -> None:
    client = SequenceModelClient(_null_output(), _valid_output())
    parser = UnifiedJDParser(client, validation_retries=1)

    result = await parser.parse(
        RawJobDocument(raw_content="岗位信息暂未披露具体要求，请关注后续官方更新。")
    )

    assert result.structured_jd.facts.job_type is None
    assert result.model_call_count == 1
    assert len(client.requests) == 1


@pytest.mark.asyncio
async def test_schema_failure_triggers_one_targeted_repair() -> None:
    invalid = _valid_output()
    invalid["facts"]["evidence"] = []
    client = SequenceModelClient(invalid, _valid_output())
    parser = UnifiedJDParser(client, validation_retries=1)

    result = await parser.parse(RawJobDocument(raw_content=RAW_JD))

    assert result.model_call_count == 2
    assert len(client.requests) == 2
    repair_request = client.requests[1]
    assert len(repair_request.messages) == 3
    assert "未通过本地结构或原文证据校验" in (repair_request.messages[-1].content)
    assert "缺少原文证据" in repair_request.messages[-1].content
    assert "locations" in repair_request.messages[-1].content


@pytest.mark.asyncio
async def test_unsupported_evidence_triggers_only_one_repair_then_fails() -> None:
    invalid = _valid_output()
    invalid["clauses"][0]["source_text"] = "不存在的专业要求"
    client = SequenceModelClient(invalid)
    parser = UnifiedJDParser(client, validation_retries=1)

    with pytest.raises(JDParserError) as captured:
        await parser.parse(RawJobDocument(raw_content=RAW_JD))

    error = captured.value
    assert error.code == "unified_output_invalid"
    assert error.details["model_call_count"] == 2
    assert len(error.details["model_diagnostics"]) == 2
    assert len(client.requests) == 2
    assert "clauses[0].source_text" in str(error.details["errors"])
    assert "不存在的专业要求" not in str(error.details)


@pytest.mark.asyncio
async def test_model_failure_is_not_treated_as_a_schema_repair() -> None:
    client = FakeModelClient(
        error=ModelTimeoutError("模型超时", {"timeout_seconds": 10})
    )
    parser = UnifiedJDParser(client, validation_retries=1)

    with pytest.raises(JDParserError) as captured:
        await parser.parse(RawJobDocument(raw_content=RAW_JD))

    assert captured.value.code == "model_timeout"
    assert captured.value.details["timeout_seconds"] == 10
    assert captured.value.details["model_call_count"] == 1
    assert client.last_request is not None
    assert len(client.last_request.messages) == 2


def test_parser_never_allows_more_than_one_validation_retry() -> None:
    with pytest.raises(ValueError, match="只能是 0 或 1"):
        UnifiedJDParser(FakeModelClient(), validation_retries=2)
