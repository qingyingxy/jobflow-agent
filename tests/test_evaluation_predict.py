from __future__ import annotations

import pytest

from src.domain.eligibility import CandidateProfileInput, SearchPreferences
from src.domain.matching import EvidenceRecord
from src.evaluation.models import (
    EvaluationCase,
    EvaluationInput,
    EvaluationManifest,
    ExpectedLabels,
    SourceMetadata,
)
from src.evaluation.predict import generate_predictions
from src.infrastructure.llm_client import FakeModelClient
from src.services.core_jd_parser import CoreJDParser
from src.services.evidence_matcher import EvidenceMatcher
from src.services.jd_parser import JDParser

RAW_CONTENT = "示例公司招聘 AI 应用开发实习生，熟悉 RAG，工作地点为北京。"


def make_manifest() -> EvaluationManifest:
    return EvaluationManifest(
        manifest_version="test-v1",
        dataset_version="test-data-v1",
        split="dev",
        purpose="test",
        source_policy="test",
        fields=["job_type", "locations", "required_skills"],
        cases=[
            EvaluationCase(
                id="case-1",
                split="dev",
                source=SourceMetadata(
                    kind="synthetic",
                    reference="test",
                    authorization="test-only",
                ),
                input=EvaluationInput(raw_content=RAW_CONTENT),
                candidate_evidence_ids=["ev-rag"],
                expected=ExpectedLabels(),
            )
        ],
    )


def valid_jd_output() -> dict[str, object]:
    return {
        "company": "示例公司",
        "title": "AI 应用开发实习生",
        "job_type": "internship",
        "locations": ["北京"],
        "required_skills": ["RAG"],
        "requirements": [
            {
                "category": "required_skill",
                "name": "RAG",
                "description": "熟悉 RAG",
                "mandatory": True,
                "evidence": [
                    {
                        "field_path": "requirements[0]",
                        "source_text": "熟悉 RAG",
                    }
                ],
            }
        ],
        "field_evidence": [
            {"field_path": "company", "source_text": "示例公司"},
            {"field_path": "title", "source_text": "AI 应用开发实习生"},
            {"field_path": "job_type", "source_text": "实习生"},
            {"field_path": "locations", "source_text": "北京"},
            {"field_path": "required_skills", "source_text": "熟悉 RAG"},
            {"field_path": "requirements[0]", "source_text": "熟悉 RAG"},
        ],
    }


@pytest.mark.asyncio
async def test_generate_predictions_reuses_parser_and_matcher_contracts() -> None:
    parser = JDParser(FakeModelClient(output=valid_jd_output()))
    matcher = EvidenceMatcher(
        FakeModelClient(
            output={
                "support_level": "supported",
                "evidence_ids": ["ev-rag"],
                "explanation": "证据支持 RAG 经历。",
                "claims": ["RAG"],
            }
        )
    )
    evidence = [
        EvidenceRecord(
            id="ev-rag",
            user_id="evaluation-user",
            title="RAG 项目",
            claim="实现 RAG 应用。",
            skills=["RAG"],
        )
    ]

    prediction_file = await generate_predictions(
        make_manifest(),
        parser=parser,
        matcher=matcher,
        evidence=evidence,
        profile=CandidateProfileInput(graduation_year=2027),
        preferences=SearchPreferences(
            preferred_locations=["北京"],
            job_types=["internship"],
        ),
    )

    prediction = prediction_file.predictions[0]
    assert prediction.fields == {
        "job_type": "internship",
        "locations": ["北京"],
        "required_skills": ["RAG"],
    }
    assert prediction.eligibility == "unknown"
    assert prediction.matches[0].requirement_key == "required_skill:rag"
    assert prediction.matches[0].evidence_ids == ["ev-rag"]
    assert prediction.failure_code is None
    assert prediction_file.prediction_version == "generated-test-data-v1"


@pytest.mark.asyncio
async def test_generate_predictions_reports_missing_raw_input_without_guessing() -> None:
    manifest = make_manifest()
    manifest.cases[0].input = EvaluationInput(
        source_url="https://example.invalid/job/timeout"
    )

    prediction_file = await generate_predictions(
        manifest,
        parser=JDParser(FakeModelClient()),
        matcher=EvidenceMatcher(FakeModelClient()),
        evidence=[],
    )

    prediction = prediction_file.predictions[0]
    assert prediction.failure_code == "input_not_available"
    assert prediction.fields == {}
    assert prediction.matches == []


@pytest.mark.asyncio
async def test_generate_predictions_parser_only_skips_user_context() -> None:
    prediction_file = await generate_predictions(
        make_manifest(),
        parser=JDParser(FakeModelClient(output=valid_jd_output())),
        matcher=EvidenceMatcher(
            FakeModelClient(
                error=AssertionError("parser-only evaluation must not call matcher")
            )
        ),
        evidence=[],
        parser_only=True,
    )

    prediction = prediction_file.predictions[0]
    assert prediction.fields == {
        "job_type": "internship",
        "locations": ["北京"],
        "required_skills": ["RAG"],
    }
    assert prediction.eligibility is None
    assert prediction.matches == []


@pytest.mark.asyncio
async def test_generate_predictions_supports_core_parser_mode() -> None:
    prediction_file = await generate_predictions(
        make_manifest(),
        parser=CoreJDParser(
            FakeModelClient(
                output={
                    "job_type": "internship",
                    "locations": ["北京"],
                    "required_skills": ["RAG"],
                }
            ),
            validation_retries=0,
        ),
        matcher=EvidenceMatcher(
            FakeModelClient(
                error=AssertionError("core parser mode must not call matcher")
            )
        ),
        evidence=[],
        parser_only=True,
        parser_mode="core",
    )

    prediction = prediction_file.predictions[0]
    assert prediction.fields == {
        "job_type": "internship",
        "locations": ["北京"],
        "required_skills": ["RAG"],
    }
    assert prediction.eligibility is None
    assert prediction.matches == []
    assert prediction.failure_code is None


@pytest.mark.asyncio
async def test_core_prediction_keeps_non_fatal_parser_warnings() -> None:
    prediction_file = await generate_predictions(
        make_manifest(),
        parser=CoreJDParser(
            FakeModelClient(
                output={
                    "job_type": "internship",
                    "locations": ["北京"],
                    "required_skills": ["RAG", "GhostSkill"],
                }
            ),
            validation_retries=0,
        ),
        matcher=EvidenceMatcher(FakeModelClient()),
        evidence=[],
        parser_only=True,
        parser_mode="core",
    )

    prediction = prediction_file.predictions[0]
    assert prediction.failure_code is None
    assert prediction.fields["required_skills"] == ["RAG"]
    assert len(prediction.warnings) == 1
    assert prediction.warnings[0].value == "GhostSkill"
