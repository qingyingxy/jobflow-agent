"""Behavioral coverage for the shared automatic/manual analysis runtime."""

import asyncio
import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from src.config import Settings
from src.domain.discovery import DiscoveryRun
from src.domain.education import EducationRecord
from src.domain.eligibility import EligibilityCheck, EligibilityResult
from src.domain.job import JobRequirement
from src.domain.matching import EvidenceRecord, RequirementMatch
from src.domain.models import EvidenceItem
from src.domain.runs import AgentRun
from src.infrastructure.llm_client import FakeModelClient, ModelTimeoutError
from src.services import official_search_service as automatic
from src.services.analysis_runtime import create_analysis_service
from src.services.jd_analysis_service import JDAnalysisFailure
from src.services.job_decision import build_job_decision
from src.services.job_service import JobImportService
from src.services.match_score import calculate_match_score
from src.services.profile_service import ProfileService
from src.services.semantic_evidence_matcher import (
    SemanticEvidenceMatcher,
    sentence_catalog,
)

CLAUSE = "本科要求计算机相关专业，硕士不限专业"
CAPABILITY = "熟悉 Python 或 Java 中至少一种语言"
EXTRACTION = {
    "facts": {},
    "requirements": [
        {"source_text": CLAUSE, "level": "required"},
        {"source_text": CAPABILITY, "level": "required"},
    ],
    "responsibilities": [],
}
RELATIONS = {
    "decisions": [
        {
            "requirement_index": 0,
            "relation": "any_of",
            "items": CLAUSE.split("，"),
            "reason": "学历任选一个分支",
            "education": {
                "relation": "any_of",
                "branches": [
                    {
                        "source_text": "本科要求计算机相关专业",
                        "degree": {
                            "operator": "eq",
                            "level": "bachelor",
                            "source_text": "本科",
                        },
                        "major": {
                            "mode": "related",
                            "values": ["计算机"],
                            "source_text": "计算机相关专业",
                        },
                    },
                    {
                        "source_text": "硕士不限专业",
                        "degree": {
                            "operator": "eq",
                            "level": "master",
                            "source_text": "硕士",
                        },
                        "major": {"mode": "any", "source_text": "不限专业"},
                    },
                ],
            },
        },
        {
            "requirement_index": 1,
            "relation": "any_of",
            "items": ["Python", "Java"],
            "reason": "至少一种",
        },
    ]
}


class ScenarioClient(FakeModelClient):
    fail_matching = False
    on_matching = None

    async def generate(self, request):
        if request.schema_name == "product_job_extraction":
            self.output = EXTRACTION
        elif request.schema_name == "product_requirement_relations":
            self.output = RELATIONS
        elif request.schema_name == "product_job_combined":
            self.output = {"extraction": EXTRACTION, "relations": RELATIONS}
        elif request.schema_name == "campus_semantic_matches":
            if self.fail_matching:
                self.requests.append(request)
                raise ModelTimeoutError("synthetic timeout")
            payload = json.loads(request.messages[-1].content)
            assert len(payload["requirements"]) == 1  # education stays local
            assert payload["requirements"][0]["description"] == CAPABILITY
            sentence = payload["evidence"][0]["sentences"][0]
            self.output = {
                "judgments": [
                    {
                        "requirement_index": 0,
                        "support_level": "supported",
                        "explanation": "项目中的 Python 服务开发支持语言要求。",
                        "citations": [sentence["id"]],
                        "missing": [],
                    }
                ]
            }
            if self.on_matching:
                self.on_matching()
        else:
            raise AssertionError(request.schema_name)
        return await super().generate(request)


def setup_job(session):
    job = JobImportService(session).import_text(
        raw_content=f"招聘开发工程师。任职要求：{CLAUSE}。{CAPABILITY}。",
        company="合成测试公司",
        title="开发工程师",
        source_type="manual_text",
        source_url=None,
    )
    ProfileService(session).upsert(
        "u",
        {
            "educations": [
                EducationRecord(
                    id="b", level="bachelor", major_raw="机械", source_text="本科机械"
                ).model_dump(mode="json"),
                EducationRecord(
                    id="m", level="master", major_raw="金融", source_text="硕士金融"
                ).model_dump(mode="json"),
            ]
        },
    )
    session.add(
        EvidenceItem(
            id="fact",
            user_id="u",
            type="project",
            title="服务项目",
            claim="使用 Python 开发服务；完成接口测试。",
            skills=["Python"],
            source="manual",
        )
    )
    session.commit()
    return job


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,parse_calls", [("two_stage", 2), ("single_call", 1)])
async def test_automatic_and_manual_share_education_semantics_and_cache(
    db_session, monkeypatch, mode, parse_calls
):
    job = setup_job(db_session)
    settings = Settings(
        _env_file=None, product_parse_mode=mode, evidence_matching_mode="semantic"
    )
    client = ScenarioClient()
    factory = lambda settings: client
    monkeypatch.setattr(automatic, "get_settings", lambda: settings)
    monkeypatch.setattr(automatic, "create_structured_model_client", factory)
    run = DiscoveryRun(
        id="search",
        user_id="u",
        source="fixture",
        source_url="https://example.com/jobs",
        max_results=5,
        status="RUNNING",
        started_at=datetime.now(UTC),
    )
    db_session.add(run)
    db_session.commit()
    await automatic.analyze_discovery_jobs(
        db_session, run_id=run.id, user_id="u", job_ids=[job.id]
    )
    assert run.analysis_completed_count == 1
    assert run.analysis_failure_count == 0
    service = create_analysis_service(
        db_session, settings=settings, client_factory=factory
    )
    saved = service.latest(user_id="u", job_id=job.id)
    result = await service.analyze(user_id="u", job_id=job.id)
    assert result.analysis.id == saved.analysis.id
    assert [m["support_level"] for m in result.analysis.matches] == [
        "supported",
        "supported",
    ]
    assert result.analysis.matches[0]["education_evidence"][0]["id"] == "m"
    assert result.analysis.matches[1]["item_checks"][0]["evidence_quotes"] == [
        "使用 Python 开发服务；完成接口测试。"
    ]
    assert len(client.requests) == parse_calls + 1
    assert sum(r.schema_name == "campus_semantic_matches" for r in client.requests) == 1
    other = await service.analyze(user_id="other", job_id=job.id)
    assert all(not m["evidence_ids"] for m in other.analysis.matches)
    assert other.analysis.matches[1]["support_level"] == "needs_confirmation"


@pytest.mark.asyncio
async def test_matching_failure_preserves_qualification_and_can_retry(db_session):
    job = setup_job(db_session)
    client = ScenarioClient()
    client.fail_matching = True
    service = create_analysis_service(
        db_session,
        settings=Settings(_env_file=None, evidence_matching_mode="semantic"),
        client_factory=lambda _: client,
    )
    failed = await service.analyze(user_id="u", job_id=job.id)
    assert failed.analysis.matches[0]["support_level"] == "supported"
    assert failed.analysis.matches[1]["support_level"] == "needs_confirmation"
    assert failed.analysis.score["score"] is None
    client.fail_matching = False
    recovered = await service.analyze(user_id="u", job_id=job.id)
    assert recovered.analysis.matches[1]["support_level"] == "supported"
    assert len(client.requests) == 4  # 2 parse, 1 timeout, 1 matching retry
    runs = db_session.scalars(
        select(AgentRun).where(AgentRun.run_type == "evidence_match")
    ).all()
    assert {r.status for r in runs} == {"failed", "succeeded"}


@pytest.mark.asyncio
async def test_changed_facts_recompute_and_concurrent_edit_does_not_publish_stale_analysis(
    db_session,
):
    job = setup_job(db_session)
    client = ScenarioClient()
    service = create_analysis_service(
        db_session,
        settings=Settings(_env_file=None, evidence_matching_mode="semantic"),
        client_factory=lambda _: client,
    )
    first = await service.analyze(user_id="u", job_id=job.id)
    evidence = db_session.get(EvidenceItem, "fact")
    evidence.claim = "使用 Python 开发另一服务。"
    db_session.commit()
    second = await service.analyze(user_id="u", job_id=job.id)
    assert second.analysis.id != first.analysis.id
    assert len(client.requests) == 4
    evidence.claim = "使用 Python 编写接口。"
    db_session.commit()

    def edit_during_call():
        evidence.claim = "用户在等待期间纠正了经历。"
        db_session.commit()

    client.on_matching = edit_during_call
    with pytest.raises(JDAnalysisFailure, match="资料或岗位已更新"):
        await service.analyze(user_id="u", job_id=job.id)


@pytest.mark.asyncio
async def test_invalid_sentence_reference_only_downgrades_affected_row():
    requirement = JobRequirement(
        category="required_skill",
        name="Python",
        description="熟悉 Python",
        mandatory=True,
    )
    evidence = EvidenceRecord(
        id="a", user_id="u", title="项目", claim="使用 Python 开发服务；完成测试。"
    )
    other = EvidenceRecord(id="b", user_id="other", title="其他人", claim="使用 Java。")
    ref = next(iter(sentence_catalog([evidence])))
    foreign = next(iter(sentence_catalog([other])))
    client = FakeModelClient(
        output={
            "judgments": [
                {
                    "requirement_index": i,
                    "support_level": "supported",
                    "explanation": "支持",
                    "citations": [cite],
                }
                for i, cite in enumerate([ref, foreign])
            ]
        }
    )
    result = await SemanticEvidenceMatcher(client).match(
        user_id="u", requirements=[requirement, requirement], evidence=[evidence, other]
    )
    assert [m.support_level for m in result.matches] == [
        "supported",
        "needs_confirmation",
    ]
    assert "其他人" not in client.requests[0].messages[-1].content
    assert result.matches[0].item_checks[0].evidence_quotes == [evidence.claim]


@pytest.mark.asyncio
async def test_timeout_cancels_model_and_missing_evidence_skips_call():
    cancelled = asyncio.Event()

    class Slow(FakeModelClient):
        async def generate(self, request):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    matcher = SemanticEvidenceMatcher(Slow(), timeout_seconds=0.01)
    req = JobRequirement(
        category="required_skill", name="Python", description="熟悉 Python"
    )
    no_facts = await matcher.match(user_id="u", requirements=[req], evidence=[])
    assert no_facts.call_count == 0
    result = await matcher.match(
        user_id="u",
        requirements=[req],
        evidence=[
            EvidenceRecord(id="a", user_id="u", title="项目", claim="使用 Python")
        ],
    )
    assert result.error_code == "matching_timeout"
    assert result.matches[0].support_level == "needs_confirmation"
    assert cancelled.is_set()


def test_incomplete_matching_is_not_presented_as_completed_recommendation():
    req = JobRequirement(
        category="required_skill",
        name="Python",
        description="熟悉 Python",
        mandatory=True,
    )
    match = RequirementMatch(
        requirement=req,
        support_level="needs_confirmation",
        explanation="分析超时",
        validation_status="failed",
    )
    eligibility = EligibilityResult(
        eligible="pass",
        checks=[
            EligibilityCheck(
                rule_name="education",
                field="educations",
                result="pass",
                reason="学历条件通过",
            )
        ],
    )
    decision = build_job_decision(eligibility=eligibility, matches=[match])
    score = calculate_match_score(
        requirements=[req], matches=[match], eligibility=eligibility
    )
    assert decision.recommendation == "insufficient_information"
    assert score.recommendation == "insufficient_data"
    assert score.score is None


@pytest.mark.asyncio
async def test_local_default_never_sends_experience_for_matching(db_session):
    job = setup_job(db_session)
    client = ScenarioClient()
    service = create_analysis_service(
        db_session, settings=Settings(_env_file=None), client_factory=lambda _: client
    )
    result = await service.analyze(user_id="u", job_id=job.id)
    assert result.analysis.matches[0]["support_level"] == "supported"
    assert all(r.schema_name != "campus_semantic_matches" for r in client.requests)
    assert all(
        "使用 Python 开发服务；完成接口测试。" not in m.content
        for r in client.requests
        for m in r.messages
    )
