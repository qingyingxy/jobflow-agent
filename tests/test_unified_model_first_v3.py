from __future__ import annotations

import hashlib

import pytest

from src.domain.job import RawJobDocument
from src.evaluation.model_first_v3 import (
    build_model_first_v3_replay,
    evaluate_model_first_v3,
)
from src.evaluation.model_first_v3_probe import analyze_v3_surface_probe
from src.evaluation.predict_unified import generate_unified_predictions
from src.evaluation.unified_models import (
    UnifiedEvaluationManifest,
    UnifiedPredictionFile,
    UnifiedPredictionRecord,
)
from src.infrastructure.llm_client import FakeModelClient
from src.services.unified_jd_extraction import (
    compile_model_first_extraction_v3,
    compile_model_first_normalized_extraction_v3,
    compile_unified_extraction_v2,
    normalize_model_first_fact_item_v3,
)
from src.services.unified_jd_parser import (
    MODEL_FIRST_V3_UNIFIED_PARSER_VERSION,
    MODEL_FIRST_V3_UNIFIED_PROMPT_VERSION,
    UNIFIED_JD_MODEL_FIRST_V3_SCHEMA_NAME,
    UnifiedJDParser,
)

SOURCE = "招聘项目：2027届校园招聘\n任职要求\n计算机等相关专业优先\n熟悉Python和R"
RAW_OUTPUT = {
    "fact_mentions": [
        {
            "field": "major_requirements",
            "raw_items": ["计算机"],
            "level": "preferred",
            "source_text": "计算机等相关专业优先",
        }
    ],
    "clauses": [
        {
            "category": "skill",
            "level": "required",
            "relation": "all_of",
            "items": ["Python", "熟悉R"],
            "examples": None,
            "group_name": None,
            "allow_other": False,
            "qualifier": None,
            "source_text": "熟悉Python和R",
        }
    ],
}
V3_OUTPUT = {
    "fact_mentions": [
        {
            "field": "major_requirements",
            "items": [{"raw_item": "计算机", "surface_item": "计算机"}],
            "level": "preferred",
            "source_text": "计算机等相关专业优先",
        }
    ],
    "clauses": [
        {
            "category": "skill",
            "level": "required",
            "relation": "all_of",
            "items": [
                {"semantic_item": "Python", "surface_item": "Python"},
                {"semantic_item": "熟悉R", "surface_item": "R"},
            ],
            "examples": None,
            "group_name": None,
            "allow_other": False,
            "qualifier": None,
            "source_text": "熟悉Python和R",
        }
    ],
}


def test_v3_normalization_consumes_raw_item_only() -> None:
    location = normalize_model_first_fact_item_v3("locations", "北京市")
    major = normalize_model_first_fact_item_v3(
        "major_requirements", "计算机、人工智能等相关专业"
    )
    invalid = normalize_model_first_fact_item_v3("job_type", "算法工程师")

    assert location.values == ("北京",)
    assert location.rule_ids == ("fact.normalize.location-city-suffix",)
    assert major.values == ("计算机", "人工智能", "相关专业")
    assert major.rule_ids == ("fact.normalize.major-atomization",)
    assert invalid.values == ()
    assert invalid.rule_ids == ()
    assert invalid.error is not None


def test_v3_normalized_compiler_does_not_expand_from_source_or_backfill() -> None:
    normalized = compile_model_first_normalized_extraction_v3(RAW_OUTPUT, SOURCE)
    derived = compile_unified_extraction_v2(RAW_OUTPUT, SOURCE)

    assert normalized.output.facts.major_requirements == ["计算机"]
    assert normalized.output.facts.graduation_years is None
    assert derived.output.facts.major_requirements == ["计算机", "相关专业"]
    assert derived.output.facts.graduation_years == [2027]


def test_v3_live_contract_validates_surface_items_before_compilation() -> None:
    compiled = compile_model_first_extraction_v3(V3_OUTPUT, SOURCE)
    invalid = {
        **V3_OUTPUT,
        "clauses": [
            {
                **V3_OUTPUT["clauses"][0],
                "items": [
                    {"semantic_item": "Python", "surface_item": "Python"},
                    {"semantic_item": "熟悉R", "surface_item": "熟悉R"},
                ],
            }
        ],
    }

    assert compiled.output.clauses[-1].items == ["Python", "熟悉R"]
    with pytest.raises(ValueError, match="surface_item"):
        compile_model_first_extraction_v3(invalid, SOURCE)


def test_v3_request_uses_full_jd_and_paired_item_schema() -> None:
    parser = UnifiedJDParser(FakeModelClient(), mode="model_first_v3")
    request = parser.build_request(
        RawJobDocument(
            source_url="https://example.invalid/job/1",
            source_type="test",
            raw_content=SOURCE,
        )
    )

    assert request.schema_name == UNIFIED_JD_MODEL_FIRST_V3_SCHEMA_NAME
    assert request.prompt_version == MODEL_FIRST_V3_UNIFIED_PROMPT_VERSION
    assert SOURCE in request.messages[-1].content
    assert "surface_item" in request.messages[0].content
    assert "semantic_item" in request.messages[0].content


@pytest.mark.asyncio
async def test_v3_prediction_path_preserves_raw_paired_response() -> None:
    manifest = _manifest()
    client = FakeModelClient(output=V3_OUTPUT)

    predictions = await generate_unified_predictions(
        manifest,
        client=client,
        parser_mode="model_first_v3",
        max_model_calls=1,
    )

    assert predictions.parser_version == MODEL_FIRST_V3_UNIFIED_PARSER_VERSION
    prediction = predictions.predictions[0]
    assert prediction.failure_code is None
    assert prediction.model_call_count == 1
    assert prediction.output["clauses"][-1]["items"] == ["Python", "熟悉R"]
    assert prediction.diagnostics["raw_model_output"] == V3_OUTPUT


def test_v3_probe_analysis_does_not_repair_observed_invalid_topology() -> None:
    observed = {
        "fact_mentions": [
            {
                "fact": "major_requirements",
                "raw_item": "计算机",
                "surface_item": "计算机",
                "source_text": "计算机等相关专业优先",
            }
        ],
        "clauses": [
            {
                "level": "required",
                "items": [
                    {
                        "semantic_item": "熟悉Python和R",
                        "surface_item": "熟悉Python和R",
                        "source_text": "熟悉Python和R",
                    }
                ],
            }
        ],
    }
    expected = _manifest().cases[0].expected
    assert expected is not None

    analysis = analyze_v3_surface_probe(
        raw_output=observed,
        raw_content=SOURCE,
        baseline_surface={
            "semantic_item_count": 2,
            "exact_surface_count": 1,
            "unmapped_surface_count": 1,
            "exact_surface_rate": 0.5,
        },
        expected=expected,
    )

    assert (
        analysis["mechanism_checks"][
            "all_observed_surfaces_are_exact_full_jd_substrings"
        ]
        is True
    )
    assert (
        analysis["mechanism_checks"][
            "semantic_and_surface_values_were_actually_separated"
        ]
        is False
    )
    assert (
        analysis["mechanism_checks"]["required_response_topology_was_followed"] is False
    )
    assert analysis["granularity"]["observed_v3_item_count"] == 1


def test_v3_projection_separates_all_layers_and_provenance() -> None:
    manifest = _manifest()
    source_predictions = _source_predictions()

    raw, normalized, derived, projection = build_model_first_v3_replay(
        manifest, source_predictions
    )

    assert all(
        prediction.model_call_count == 0
        for replay in (raw, normalized, derived)
        for prediction in replay.predictions
    )
    record = projection.records[0]
    fact_item = record.fact_mentions[0].items[0]
    assert fact_item.raw_item == "计算机"
    assert fact_item.surface_status == "exact"
    assert fact_item.normalized_values == ["计算机"]
    assert fact_item.normalization_status == "identity"

    fields = {item.field: item for item in record.fact_fields}
    assert fields["major_requirements"].derivation_status == "transformed"
    assert fields["major_requirements"].derivation_rule_ids == [
        "fact.derive.major-open-scope"
    ]
    assert fields["graduation_years"].derivation_status == "backfilled"
    assert fields["graduation_years"].derivation_rule_ids == [
        "fact.derive.local-source-backfill"
    ]

    clause_items = record.clauses[0].items
    assert clause_items[0].surface_status == "exact"
    assert clause_items[1].surface_status == "unmapped"
    assert clause_items[1].normalized_item == "熟悉R"
    assert clause_items[1].derived_items == []


def test_v3_evaluator_reports_independent_stage_contribution() -> None:
    manifest = _manifest()
    source_predictions = _source_predictions()
    raw, normalized, derived, projection = build_model_first_v3_replay(
        manifest, source_predictions
    )

    report = evaluate_model_first_v3(
        manifest,
        source_predictions,
        raw,
        normalized,
        derived,
        projection,
    )

    assert report["model_api_called"] is False
    assert report["hard_gate"]["passed"] is True
    assert (
        report["stages"]["derived"]["facts"]["macro_f1"]
        > report["stages"]["normalized"]["facts"]["macro_f1"]
    )
    assert report["layers"]["clauses"]["unmapped_surface_count"] == 1
    assert report["layers"]["clauses"]["derived_item_count"] == 0


def _manifest() -> UnifiedEvaluationManifest:
    expected = compile_unified_extraction_v2(RAW_OUTPUT, SOURCE).output
    return UnifiedEvaluationManifest.model_validate(
        {
            "manifest_version": "model-first-v3-test",
            "dataset_version": "model-first-v3-test",
            "split": "dev",
            "purpose": "Synthetic layered model-first test.",
            "source_policy": "Synthetic local test data only.",
            "annotation_guide_version": "test-guide",
            "label_status": "frozen",
            "thresholds": {},
            "cases": [
                {
                    "id": "case-1",
                    "split": "dev",
                    "source": {
                        "kind": "synthetic_fixture",
                        "company": "Example",
                        "title": "Example",
                        "source_url": "https://example.invalid/job/1",
                        "verified_at": None,
                        "authorization": "Synthetic fixture.",
                    },
                    "raw_content": SOURCE,
                    "source_content_sha256": hashlib.sha256(
                        SOURCE.encode()
                    ).hexdigest(),
                    "annotation_status": "frozen",
                    "expected": expected.model_dump(mode="json"),
                    "coverage_tags": [],
                    "review_notes": [],
                }
            ],
        }
    )


def _source_predictions() -> UnifiedPredictionFile:
    return UnifiedPredictionFile(
        prediction_version="source-v1",
        parser_version="source-parser-v1",
        prompt_version="source-prompt-v1",
        model="test-model",
        predictions=[
            UnifiedPredictionRecord(
                case_id="case-1",
                output={},
                model_call_count=1,
                diagnostics={
                    "input_sha256": hashlib.sha256(SOURCE.encode()).hexdigest(),
                    "model_attempts": [{"raw_model_output": RAW_OUTPUT}],
                },
            )
        ],
    )
