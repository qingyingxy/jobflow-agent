from __future__ import annotations

import hashlib

from src.evaluation.model_first_v2 import (
    build_model_first_v2_replay,
    evaluate_model_first_v2,
)
from src.evaluation.unified_models import (
    UnifiedEvaluationManifest,
    UnifiedPredictionFile,
    UnifiedPredictionRecord,
)
from src.services.unified_jd_extraction import (
    compile_model_first_extraction_v2,
    compile_unified_extraction_v2,
)


def test_model_first_fact_compiler_preserves_model_items_without_backfill() -> None:
    source = "招聘项目：2027届校园招聘\n任职要求\n计算机、人工智能等相关专业优先"
    raw = {
        "fact_mentions": [
            {
                "field": "major_requirements",
                "raw_items": ["计算机、人工智能等相关专业"],
                "level": "preferred",
                "source_text": "计算机、人工智能等相关专业优先",
            }
        ],
        "clauses": [],
    }

    compatible = compile_unified_extraction_v2(raw, source)
    conservative = compile_model_first_extraction_v2(raw, source)

    assert compatible.output.facts.major_requirements == [
        "计算机",
        "人工智能",
        "相关专业",
    ]
    assert compatible.output.facts.graduation_years == [2027]
    assert conservative.output.facts.major_requirements == [
        "计算机、人工智能等相关专业"
    ]
    assert conservative.output.facts.graduation_years is None
    assert not any(
        item.code == "locally_backfilled_fact" for item in conservative.diagnostics
    )


def test_model_first_fact_compiler_does_not_parse_value_only_from_evidence() -> None:
    source = "招聘类型：校招"
    raw = {
        "fact_mentions": [
            {
                "field": "job_type",
                "raw_items": ["算法工程师"],
                "level": None,
                "source_text": source,
            }
        ],
        "clauses": [],
    }

    compatible = compile_unified_extraction_v2(raw, source)
    conservative = compile_model_first_extraction_v2(raw, source)

    assert compatible.output.facts.job_type == "campus"
    assert conservative.output.facts.job_type is None


def test_v2_projection_separates_model_surface_and_canonical_items() -> None:
    source = "岗位名称：数据分析工程师\n任职要求\n熟悉Python和R"
    raw = {
        "fact_mentions": [],
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
    manifest = _manifest(source)
    source_predictions = UnifiedPredictionFile(
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
                    "input_sha256": hashlib.sha256(source.encode()).hexdigest(),
                    "model_attempts": [{"raw_model_output": raw}],
                },
            )
        ],
    )

    replay, projection = build_model_first_v2_replay(manifest, source_predictions)

    assert replay.predictions[0].model_call_count == 0
    assert replay.predictions[0].diagnostics["source_model_call_count"] == 1
    items = projection.records[0].clauses[0].items
    assert items[0].model_item == items[0].surface_item == "Python"
    assert items[0].canonical_item == "Python"
    assert items[0].surface_start_char is not None
    assert items[1].model_item == "熟悉R"
    assert items[1].surface_status == "unmapped"
    assert items[1].surface_item is None
    assert items[1].canonical_item is None


def test_v2_evaluator_separates_label_disagreement_from_source_support() -> None:
    source = "岗位名称：算法工程师\n任职要求\n计算机、人工智能等相关专业优先"
    expected = {
        "facts": {
            "job_type": None,
            "locations": None,
            "graduation_years": None,
            "education_requirements": None,
            "major_requirements": ["计算机", "人工智能", "相关专业"],
            "internship_duration_months": None,
            "weekly_days": None,
            "earliest_start_date": None,
            "deadline": None,
            "evidence": [
                {
                    "field": "major_requirements",
                    "source_text": "计算机、人工智能等相关专业优先",
                }
            ],
        },
        "clauses": [],
    }
    raw = {
        "fact_mentions": [
            {
                "field": "major_requirements",
                "raw_items": ["计算机、人工智能等相关专业"],
                "level": "preferred",
                "source_text": "计算机、人工智能等相关专业优先",
            }
        ],
        "clauses": [],
    }
    manifest = _manifest(source, expected=expected, frozen=True)
    source_predictions = _source_predictions(source, raw)

    replay, projection = build_model_first_v2_replay(manifest, source_predictions)
    report = evaluate_model_first_v2(
        manifest,
        source_predictions,
        replay,
        projection,
    )

    assert report["hard_gate"]["passed"] is True
    assert report["facts"]["source_unsupported_critical_facts"]["count"] == 0
    disagreements = report["facts"]["human_label_disagreements"]
    assert disagreements["count"] == 1
    assert disagreements["items"][0]["unexpected_values"] == [
        "计算机、人工智能等相关专业"
    ]


def _source_predictions(source: str, raw: dict[str, object]) -> UnifiedPredictionFile:
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
                    "input_sha256": hashlib.sha256(source.encode()).hexdigest(),
                    "model_attempts": [{"raw_model_output": raw}],
                },
            )
        ],
    )


def _manifest(
    source: str,
    *,
    expected: dict[str, object] | None = None,
    frozen: bool = False,
) -> UnifiedEvaluationManifest:
    status = "frozen" if frozen else "pending"
    return UnifiedEvaluationManifest.model_validate(
        {
            "manifest_version": "model-first-v2-test",
            "dataset_version": "model-first-v2-test",
            "split": "dev",
            "purpose": "Synthetic model-first v2 test.",
            "source_policy": "Synthetic local test data only.",
            "annotation_guide_version": "test-guide",
            "label_status": status,
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
                    "raw_content": source,
                    "source_content_sha256": hashlib.sha256(
                        source.encode()
                    ).hexdigest(),
                    "annotation_status": status,
                    "expected": expected,
                    "coverage_tags": [],
                    "review_notes": [],
                }
            ],
        }
    )
