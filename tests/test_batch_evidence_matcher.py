import json

import pytest

from src.domain.job import JobRequirement
from src.domain.matching import EvidenceRecord
from src.infrastructure.llm_client import FakeModelClient, ModelTimeoutError
from src.services.batch_evidence_matcher import BatchEvidenceMatcher


def requirement(text="熟悉 RAG", category="required_skill"):
    return JobRequirement(category=category, name=text, description=text)


def evidence(user="a", eid="ev_1", claim="完成混合检索和重排序，并对比检索效果。"):
    return EvidenceRecord(
        id=eid, user_id=user, title="问答助手", claim=claim, skills=["RAG"]
    )


def judgment(index=0, status="supported", eid="ev_1", quote="完成混合检索和重排序"):
    return {
        "requirement_index": index,
        "support_level": status,
        "explanation": "相关实现和评测支持该能力。",
        "citations": [{"evidence_id": eid, "quote": quote}],
        "missing": [],
    }


@pytest.mark.asyncio
async def test_one_batch_and_current_user_only_without_lexical_recall():
    client = FakeModelClient(output={"judgments": [judgment(), judgment(1)]})
    result = await BatchEvidenceMatcher(client).match(
        user_id="a",
        requirements=[requirement(), requirement("能够验证方案效果")],
        evidence=[evidence(), evidence("other", "ev_private", "另一个人的秘密项目")],
    )
    assert len(client.requests) == 1 and result.call_count == 1
    payload = json.loads(client.requests[0].messages[-1].content)
    assert len(payload["requirements"]) == 2
    assert [r["id"] for r in payload["evidence"]] == ["ev_1"]
    assert "秘密" not in client.requests[0].messages[-1].content
    assert [r.support_level for r in result.matches] == ["supported", "supported"]
    assert result.matches[0].item_checks[0].evidence_quotes == ["完成混合检索和重排序"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad",
    [
        judgment(eid="other"),
        judgment(quote="熟练掌握 RAG"),
        judgment(quote="问答助手"),
        judgment(quote="RAG"),
        {**judgment(), "citations": []},
    ],
)
async def test_invalid_citations_abstain_without_claiming_candidate_is_unqualified(bad):
    client = FakeModelClient(output={"judgments": [bad]})
    result = await BatchEvidenceMatcher(client).match(
        user_id="a", requirements=[requirement()], evidence=[evidence()]
    )
    match = result.matches[0]
    assert match.support_level == "needs_confirmation"
    assert match.validation_status == "failed"
    assert match.evidence_ids == []


@pytest.mark.asyncio
@pytest.mark.parametrize("rows", [[], [judgment(), judgment()], [judgment(2)]])
async def test_missing_duplicate_or_out_of_range_indices_do_not_silently_shift_results(
    rows,
):
    result = await BatchEvidenceMatcher(
        FakeModelClient(output={"judgments": rows})
    ).match(user_id="a", requirements=[requirement()], evidence=[evidence()])
    assert result.matches[0].validation_status == "failed"


@pytest.mark.asyncio
async def test_timeout_is_one_attempt_and_not_a_negative_qualification():
    client = FakeModelClient(error=ModelTimeoutError("timeout"))
    result = await BatchEvidenceMatcher(client).match(
        user_id="a", requirements=[requirement()], evidence=[evidence()]
    )
    assert result.error_code == "model_timeout"
    assert len(client.requests) == 1
    assert result.matches[0].support_level == "needs_confirmation"


@pytest.mark.asyncio
async def test_invalid_schema_and_individual_bad_quote_are_distinct():
    invalid = await BatchEvidenceMatcher(
        FakeModelClient(output={"judgments": "not a list"})
    ).match(user_id="a", requirements=[requirement()], evidence=[evidence()])
    assert invalid.error_code == "batch_output_invalid"
    partial = await BatchEvidenceMatcher(
        FakeModelClient(output={"judgments": [judgment(), judgment(1, quote="编造")]})
    ).match(
        user_id="a",
        requirements=[requirement(), requirement("沟通能力")],
        evidence=[evidence()],
    )
    assert partial.matches[0].validation_status == "passed"
    assert partial.matches[1].validation_status == "failed"


@pytest.mark.asyncio
async def test_no_evidence_means_no_call_and_hard_conditions_are_not_sent():
    client = FakeModelClient()
    matcher = BatchEvidenceMatcher(client)
    result = await matcher.match(user_id="a", requirements=[requirement()], evidence=[])
    assert (
        result.call_count == 0
        and result.matches[0].support_level == "needs_confirmation"
    )
    with pytest.raises(ValueError, match="资格检查"):
        await matcher.match(
            user_id="a",
            requirements=[requirement("硕士", "education")],
            evidence=[evidence()],
        )
    assert client.requests == []


@pytest.mark.asyncio
async def test_duplicate_evidence_ids_and_oversized_input_are_not_silently_truncated():
    matcher = BatchEvidenceMatcher(FakeModelClient())
    with pytest.raises(ValueError, match="不唯一"):
        await matcher.match(
            user_id="a", requirements=[requirement()], evidence=[evidence(), evidence()]
        )
    with pytest.raises(ValueError, match="文本预算"):
        await matcher.match(
            user_id="a",
            requirements=[requirement()],
            evidence=[evidence(claim="超长" * 31000)],
        )
