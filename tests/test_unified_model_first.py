from __future__ import annotations

import hashlib

import pytest

from scripts.build_unified_jd_model_first_v1_dev20 import (
    DEFAULT_SOURCE,
    SELECTED_CASE_IDS,
    build_manifest,
)
from scripts.run_unified_jd_model_first_v1 import generate_model_first_artifacts
from src.domain.job import RawJobDocument
from src.domain.unified_jd import UnifiedJDModelOutput
from src.domain.unified_jd_canonicalizer import canonicalize_item
from src.evaluation.model_first import evaluate_model_first_manifest
from src.evaluation.unified_models import UnifiedEvaluationManifest
from src.infrastructure.llm_client import (
    StructuredModelRequest,
    StructuredModelResponse,
)
from src.services.unified_jd_parser import (
    MODEL_FIRST_UNIFIED_PARSER_VERSION,
    MODEL_FIRST_UNIFIED_PROMPT_VERSION,
    UNIFIED_JD_MODEL_FIRST_SCHEMA_NAME,
    UnifiedJDParser,
)

SOURCE = "岗位职责\n负责数据分析。\n任职要求\n熟悉英语六级并能够阅读英文文档。"
EVIDENCE = "熟悉英语六级"


def _expected_output() -> UnifiedJDModelOutput:
    return UnifiedJDModelOutput.model_validate(
        {
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
            "clauses": [
                {
                    "category": "skill",
                    "fact_field": None,
                    "level": "required",
                    "relation": "all_of",
                    "items": ["CET-6"],
                    "examples": None,
                    "group_name": None,
                    "allow_other": False,
                    "qualifier": None,
                    "source_text": EVIDENCE,
                }
            ],
        }
    )


def _manifest() -> UnifiedEvaluationManifest:
    return UnifiedEvaluationManifest.model_validate(
        {
            "manifest_version": "model-first-test",
            "dataset_version": "model-first-test-v1",
            "split": "dev",
            "purpose": "Synthetic model-first test manifest.",
            "source_policy": "Synthetic local test data only.",
            "annotation_guide_version": "unified-jd-annotation-granularity-v2",
            "label_status": "frozen",
            "thresholds": {},
            "cases": [
                {
                    "id": "model-first-001",
                    "split": "dev",
                    "source": {
                        "kind": "synthetic_fixture",
                        "company": "Example",
                        "title": "Example role",
                        "source_url": "https://example.invalid/job/1",
                        "verified_at": None,
                        "authorization": "Synthetic local test fixture.",
                    },
                    "raw_content": SOURCE,
                    "source_content_sha256": hashlib.sha256(
                        SOURCE.encode("utf-8")
                    ).hexdigest(),
                    "annotation_status": "frozen",
                    "expected": _expected_output().model_dump(mode="json"),
                    "coverage_tags": [],
                    "review_notes": [],
                }
            ],
        }
    )


class SequenceModelClient:
    provider = "fake"
    model_name = "sequence-model"

    def __init__(self, outputs: list[dict[str, object]]) -> None:
        self.outputs = list(outputs)
        self.requests: list[StructuredModelRequest] = []

    async def generate(
        self, request: StructuredModelRequest
    ) -> StructuredModelResponse:
        self.requests.append(request)
        return StructuredModelResponse(
            output=self.outputs.pop(0),
            model=self.model_name,
            provider=self.provider,
        )


def test_model_first_request_sends_full_jd_without_evidence_line_structure() -> None:
    parser = UnifiedJDParser(SequenceModelClient([]), mode="model_first_v1")
    request = parser.build_request(
        RawJobDocument(
            source_url="https://example.invalid/job/1",
            source_type="test",
            raw_content=SOURCE,
        )
    )

    assert request.schema_name == UNIFIED_JD_MODEL_FIRST_SCHEMA_NAME
    assert request.prompt_version == MODEL_FIRST_UNIFIED_PROMPT_VERSION
    assert SOURCE in request.messages[-1].content
    assert "evidence_lines" not in request.messages[-1].content


def test_canonicalizer_is_conservative_and_auditable() -> None:
    aliased = canonicalize_item("英语六级")
    untouched = canonicalize_item("分布式系统设计")

    assert aliased.canonical_item == "CET-6"
    assert aliased.rule_ids == ["canonical.exact-alias"]
    assert untouched.canonical_item == "分布式系统设计"
    assert untouched.rule_ids == ["canonical.identity"]


@pytest.mark.asyncio
async def test_model_first_repairs_once_and_evaluates_canonical_items() -> None:
    invalid = {"fact_mentions": "invalid", "clauses": []}
    valid = {
        "fact_mentions": [],
        "clauses": [
            {
                "category": "skill",
                "level": "required",
                "relation": "all_of",
                "items": ["英语六级"],
                "examples": None,
                "group_name": None,
                "allow_other": False,
                "qualifier": None,
                "source_text": EVIDENCE,
            }
        ],
    }
    client = SequenceModelClient([invalid, valid])
    manifest = _manifest()

    predictions, canonical = await generate_model_first_artifacts(
        manifest,
        client=client,
    )
    report = evaluate_model_first_manifest(manifest, predictions, canonical)

    assert predictions.parser_version == MODEL_FIRST_UNIFIED_PARSER_VERSION
    assert predictions.predictions[0].model_call_count == 2
    assert predictions.predictions[0].failure_code is None
    attempts = predictions.predictions[0].diagnostics["model_attempts"]
    assert [attempt["raw_model_output"] for attempt in attempts] == [invalid, valid]
    assert len(client.requests) == 2
    assert "上一轮抽取结果无效" in client.requests[1].messages[-1].content
    mapping = canonical.records[0].projection.clauses[0].items[0]
    assert mapping.surface_item == "英语六级"
    assert mapping.canonical_item == "CET-6"
    assert report["hard_gate"]["passed"] is True
    assert report["primary_dimensions"]["canonical_items"]["overall"]["f1"] == 1.0


def test_dev20_is_a_frozen_subset_with_canonical_contract_coverage() -> None:
    source = UnifiedEvaluationManifest.model_validate_json(
        DEFAULT_SOURCE.read_text(encoding="utf-8")
    )

    manifest = build_manifest(source)

    assert tuple(case.id for case in manifest.cases) == SELECTED_CASE_IDS
    assert len(manifest.cases) == 20
    assert manifest.label_status == "frozen"
    assert {
        "campus-ai-011",
        "campus-ai-069",
        "campus-ai-072",
        "campus-ai-085",
        "campus-ai-091",
    }.issubset(SELECTED_CASE_IDS)
    assert all(case.annotation_status == "frozen" for case in manifest.cases)
