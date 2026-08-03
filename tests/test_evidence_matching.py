from __future__ import annotations

import pytest

from src.domain.eligibility import (
    EligibilityCheck,
    EligibilityResult,
)
from src.domain.job import JobRequirement
from src.domain.matching import (
    EvidenceMatchModelOutput,
    EvidenceRecord,
    RequirementMatch,
)
from src.domain.models import EvidenceItem
from src.infrastructure.llm_client import FakeModelClient, ModelTimeoutError
from src.services.evidence_match_service import (
    EvidenceMatchFailure,
    EvidenceMatchService,
)
from src.services.evidence_matcher import EvidenceMatcher, EvidenceMatchError
from src.services.evidence_retriever import EvidenceRetriever
from src.services.evidence_validator import validate_requirement_match
from src.services.match_score import MatchScoreCalculator


def requirement(
    name: str = "RAG",
    category: str = "required_skill",
) -> JobRequirement:
    return JobRequirement(
        category=category,
        name=name,
        description=f"岗位要求具备 {name} 相关经验",
        mandatory=category == "required_skill",
    )


def evidence_records() -> list[EvidenceRecord]:
    return [
        EvidenceRecord(
            id="ev-rag",
            user_id="user-a",
            title="Memory-RAG",
            claim="实现 BM25 与向量检索融合，并加入 rerank，评测准确率为 92%。",
            skills=["RAG", "BM25", "Vector Search", "Reranker"],
            source="resume_project_1",
        ),
        EvidenceRecord(
            id="ev-python",
            user_id="user-a",
            title="JobFlow API",
            claim="使用 Python 和 FastAPI 实现后端接口。",
            skills=["Python", "FastAPI"],
            source="resume_project_2",
        ),
        EvidenceRecord(
            id="ev-other",
            user_id="user-b",
            title="Other RAG",
            claim="实现 RAG 系统。",
            skills=["RAG"],
            source="other_resume",
        ),
    ]


def valid_model_output() -> EvidenceMatchModelOutput:
    return EvidenceMatchModelOutput(
        support_level="supported",
        evidence_ids=["ev-rag"],
        explanation="在 Memory-RAG 项目中实现 BM25 与向量检索融合，使用 RAG。",
        claims=["BM25", "向量检索", "RAG"],
    )


def pass_eligibility() -> EligibilityResult:
    return EligibilityResult(
        eligible="pass",
        checks=[
            EligibilityCheck(
                rule_name="location",
                field="locations",
                result="pass",
                reason="地点匹配",
            ),
            EligibilityCheck(
                rule_name="job_type",
                field="job_type",
                result="pass",
                reason="岗位类型匹配",
            ),
        ],
    )


def test_retriever_filters_user_and_supports_skill_aliases() -> None:
    candidates = EvidenceRetriever.retrieve(
        "user-a",
        requirement("Retrieval-Augmented Generation"),
        evidence_records(),
    )

    assert [item.id for item in candidates] == ["ev-rag"]
    assert candidates[0].retrieval_score is not None


def test_retriever_is_stable_and_handles_empty_limit() -> None:
    records = evidence_records() + [evidence_records()[0]]
    first = EvidenceRetriever.retrieve("user-a", requirement("Python"), records)
    second = EvidenceRetriever.retrieve("user-a", requirement("Python"), records)

    assert [item.id for item in first] == ["ev-python"]
    assert first[0].model_dump() == second[0].model_dump()
    assert EvidenceRetriever.retrieve("user-a", requirement(), records, limit=0) == []


def test_validator_accepts_supported_match_with_traceable_facts() -> None:
    result = validate_requirement_match(
        user_id="user-a",
        requirement=requirement(),
        output=valid_model_output(),
        evidence=evidence_records(),
    )

    assert result.support_level == "supported"
    assert result.evidence_ids == ["ev-rag"]
    assert result.validation_status == "passed"
    assert result.validation_issues == []


@pytest.mark.parametrize(
    "output",
    [
        EvidenceMatchModelOutput(
            support_level="supported",
            evidence_ids=["ev-missing"],
            explanation="找到了相关经历。",
        ),
        EvidenceMatchModelOutput(
            support_level="supported",
            evidence_ids=["ev-other"],
            explanation="在 Other RAG 项目中实现 RAG。",
        ),
        EvidenceMatchModelOutput(
            support_level="supported",
            evidence_ids=["ev-rag"],
            explanation="在项目中处理了 1000 条数据。",
        ),
        EvidenceMatchModelOutput(
            support_level="unsupported",
            evidence_ids=[],
            explanation="用户已经掌握 RAG。",
        ),
    ],
)
def test_validator_downgrades_invalid_or_hallucinated_matches(
    output: EvidenceMatchModelOutput,
) -> None:
    result = validate_requirement_match(
        user_id="user-a",
        requirement=requirement(),
        output=output,
        evidence=evidence_records(),
    )

    assert result.support_level == "unsupported"
    assert result.evidence_ids == []
    assert result.validation_status == "failed"
    assert result.validation_issues
    assert "1000" not in result.explanation


def test_validator_requires_empty_evidence_for_unsupported() -> None:
    output = EvidenceMatchModelOutput(
        support_level="unsupported",
        evidence_ids=["ev-rag"],
        explanation="没有足够证据。",
    )

    result = validate_requirement_match(
        user_id="user-a",
        requirement=requirement(),
        output=output,
        evidence=evidence_records(),
    )

    assert result.support_level == "unsupported"
    assert result.evidence_ids == []
    assert result.validation_status == "failed"


@pytest.mark.asyncio
async def test_matcher_uses_fake_model_and_shared_client_boundary() -> None:
    client = FakeModelClient(output=valid_model_output().model_dump())
    matcher = EvidenceMatcher(client)

    result = await matcher.match(
        user_id="user-a",
        requirement=requirement(),
        evidence=evidence_records(),
    )

    assert result.support_level == "supported"
    assert client.last_request is not None
    assert client.last_request.schema_name == "requirement_match"


@pytest.mark.asyncio
async def test_matcher_returns_unsupported_without_calling_model_when_no_evidence() -> None:
    client = FakeModelClient(error=ModelTimeoutError("should not be called"))
    matcher = EvidenceMatcher(client)

    result = await matcher.match(
        user_id="user-a",
        requirement=requirement("Kubernetes"),
        evidence=evidence_records(),
    )

    assert result.support_level == "unsupported"
    assert result.validation_status == "passed"
    assert client.last_request is None


@pytest.mark.asyncio
async def test_matcher_rejects_invalid_model_output() -> None:
    client = FakeModelClient(
        output={
            "support_level": "supported",
            "evidence_ids": ["ev-rag"],
            "explanation": "valid",
            "unexpected": True,
        }
    )
    matcher = EvidenceMatcher(client)

    with pytest.raises(EvidenceMatchError) as error:
        await matcher.match(
            user_id="user-a",
            requirement=requirement(),
            evidence=evidence_records(),
        )

    assert error.value.code == "match_output_invalid"


@pytest.mark.asyncio
async def test_matcher_preserves_model_timeout() -> None:
    matcher = EvidenceMatcher(FakeModelClient(error=ModelTimeoutError("timeout")))

    with pytest.raises(EvidenceMatchError) as error:
        await matcher.match(
            user_id="user-a",
            requirement=requirement(),
            evidence=evidence_records(),
        )

    assert error.value.code == "model_timeout"


@pytest.mark.asyncio
async def test_match_service_records_validation_failure_as_agent_run(db_session) -> None:
    db_session.add(
        EvidenceItem(
            id="ev-rag",
            user_id="user-a",
            type="project",
            title="Memory-RAG",
            claim="实现 RAG 系统。",
            skills=["RAG"],
            source="resume",
        )
    )
    db_session.commit()
    matcher = EvidenceMatcher(
        FakeModelClient(
            output={
                "support_level": "supported",
                "evidence_ids": ["ev-missing"],
                "explanation": "有相关经历。",
            }
        )
    )

    execution = await EvidenceMatchService(db_session, matcher).match(
        user_id="user-a",
        requirement=requirement(),
        target_id="job_m6",
    )

    assert execution.match.support_level == "unsupported"
    assert execution.agent_run.status == "succeeded"
    assert execution.agent_run.validation_status == "failed"
    assert execution.agent_run.validation_result["status"] == "failed"


@pytest.mark.asyncio
async def test_match_service_records_model_failure(db_session) -> None:
    db_session.add(
        EvidenceItem(
            id="ev-rag",
            user_id="user-a",
            type="project",
            title="Memory-RAG",
            claim="实现 RAG 系统。",
            skills=["RAG"],
            source="resume",
        )
    )
    db_session.commit()
    matcher = EvidenceMatcher(FakeModelClient(error=ModelTimeoutError("timeout")))

    with pytest.raises(EvidenceMatchFailure) as error:
        await EvidenceMatchService(db_session, matcher).match(
            user_id="user-a",
            requirement=requirement(),
            target_id="job_m6",
        )

    assert error.value.code == "model_timeout"


def match_for(
    item: JobRequirement,
    level: str,
    evidence_ids: list[str] | None = None,
) -> RequirementMatch:
    return RequirementMatch(
        requirement=item,
        support_level=level,
        evidence_ids=evidence_ids or [],
        explanation="有可验证的证据。",
    )


def test_score_uses_deduplication_and_60_20_20_weights() -> None:
    required = requirement("RAG")
    duplicate_required = requirement(" rag ")
    preferred = requirement("Python", category="preferred_skill")
    score = MatchScoreCalculator.calculate(
        requirements=[required, duplicate_required, preferred],
        matches=[
            match_for(required, "supported", ["ev-rag"]),
            match_for(preferred, "partial", ["ev-python"]),
        ],
        eligibility=pass_eligibility(),
    )

    assert score.score == 90.0
    assert score.groups[0].denominator == 1
    assert score.groups[0].effective_weight == 0.6
    assert score.groups[1].effective_weight == 0.2
    assert score.groups[2].effective_weight == 0.2


def test_score_redistributes_weight_for_explicitly_absent_skill_group() -> None:
    score = MatchScoreCalculator.calculate(
        requirements=[requirement("RAG")],
        matches=[match_for(requirement("RAG"), "supported", ["ev-rag"])],
        eligibility=pass_eligibility(),
    )

    preferred_group = next(group for group in score.groups if group.group == "preferred_skill")
    required_group = next(group for group in score.groups if group.group == "required_skill")
    assert preferred_group.status == "not_applicable"
    assert required_group.effective_weight == 0.75
    assert score.score == 100.0


def test_score_does_not_treat_missing_requirements_as_not_applicable() -> None:
    score = MatchScoreCalculator.calculate(
        requirements=None,
        matches=[],
        eligibility=pass_eligibility(),
    )

    assert score.score is None
    assert score.recommendation == "insufficient_data"
    assert all(group.status == "insufficient_data" for group in score.groups[:2])


def test_score_keeps_numeric_score_but_requires_confirmation_for_unknown_eligibility() -> None:
    eligibility = EligibilityResult(
        eligible="unknown",
        checks=[
            EligibilityCheck(
                rule_name="location",
                field="locations",
                result="pass",
                reason="地点匹配",
            ),
            EligibilityCheck(
                rule_name="job_type",
                field="job_type",
                result="pass",
                reason="类型匹配",
            ),
            EligibilityCheck(
                rule_name="graduation_year",
                field="graduation_year",
                result="unknown",
                reason="缺少届别",
                missing_information=["补充毕业年份"],
            ),
        ],
    )
    score = MatchScoreCalculator.calculate(
        requirements=[requirement("RAG")],
        matches=[match_for(requirement("RAG"), "partial", ["ev-rag"])],
        eligibility=eligibility,
    )

    assert score.score == 62.5
    assert score.recommendation == "needs_confirmation"
    assert "补充毕业年份" in score.missing_information


def test_score_hard_eligibility_failure_is_not_recommended() -> None:
    eligibility = pass_eligibility().model_copy(update={"eligible": "fail"})
    score = MatchScoreCalculator.calculate(
        requirements=[requirement("RAG")],
        matches=[match_for(requirement("RAG"), "supported", ["ev-rag"])],
        eligibility=eligibility,
    )

    assert score.recommendation == "not_recommended"
