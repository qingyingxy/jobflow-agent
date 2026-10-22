from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts.build_unified_dev50_granularity_v2 import (
    DEFAULT_SOURCE,
    EXPECTED_SOURCE_SHA256,
    build_granularity_v2_manifest,
    write_granularity_v2_manifest,
)
from src.domain.unified_jd import validate_unified_fact_clause_granularity
from src.evaluation.unified_metrics import evaluate_unified_manifest
from src.evaluation.unified_models import (
    UnifiedEvaluationManifest,
    UnifiedPredictionRecord,
)


def _case_by_id(manifest: UnifiedEvaluationManifest, case_id: str):  # type: ignore[no-untyped-def]
    return next(case for case in manifest.cases if case.id == case_id)


def test_granularity_v2_is_derived_from_unchanged_frozen_v1() -> None:
    assert hashlib.sha256(DEFAULT_SOURCE.read_bytes()).hexdigest() == (
        EXPECTED_SOURCE_SHA256
    )
    source = UnifiedEvaluationManifest.model_validate_json(
        DEFAULT_SOURCE.read_text(encoding="utf-8")
    )

    revised, summary = build_granularity_v2_manifest()

    assert revised.label_status == "frozen"
    assert revised.dataset_version == "unified-jd-dev50-frozen-v2-2026-09-04"
    assert len(revised.cases) == 50
    assert summary["changed_case_count"] > 0
    for source_case, revised_case in zip(source.cases, revised.cases, strict=True):
        assert revised_case.raw_content == source_case.raw_content
        assert revised_case.source_content_sha256 == source_case.source_content_sha256
        assert revised_case.expected is not None
        assert source_case.expected is not None
        assert revised_case.expected.clauses == source_case.expected.clauses
        assert revised_case.expected.facts.evidence == source_case.expected.facts.evidence
        validate_unified_fact_clause_granularity(revised_case.expected)


def test_granularity_v2_atomizes_major_facts_from_reviewed_fact_clause() -> None:
    revised, _ = build_granularity_v2_manifest()
    case = _case_by_id(revised, "campus-ai-001")
    assert case.expected is not None

    assert case.expected.facts.major_requirements == [
        "数学",
        "计算机",
        "相关专业",
    ]


def test_granularity_validator_rejects_combined_fact_with_atomic_clause() -> None:
    revised, _ = build_granularity_v2_manifest()
    case = _case_by_id(revised, "campus-ai-001")
    assert case.expected is not None
    invalid = case.expected.model_copy(deep=True)
    invalid.facts.major_requirements = ["数学、计算机等相关专业"]

    with pytest.raises(ValueError, match="major_requirements"):
        validate_unified_fact_clause_granularity(invalid)


def test_granularity_v2_writer_creates_manifest_and_receipt(tmp_path: Path) -> None:
    output = tmp_path / "frozen-v2.json"
    receipt = tmp_path / "receipt-v2.json"

    manifest, summary = write_granularity_v2_manifest(
        output_path=output,
        receipt_path=receipt,
    )

    assert output.exists()
    assert receipt.exists()
    assert len(manifest.cases) == 50
    assert summary["changed_fields"]["major_requirements"]["case_count"] > 0


def test_v2_evaluation_reports_prediction_granularity_errors() -> None:
    manifest, _ = build_granularity_v2_manifest()
    one_case = manifest.model_copy(update={"cases": [manifest.cases[0]]})
    expected = one_case.cases[0].expected
    assert expected is not None
    invalid = expected.model_copy(deep=True)
    invalid.facts.major_requirements = ["数学、计算机或相关专业"]

    report = evaluate_unified_manifest(
        one_case,
        [
            UnifiedPredictionRecord(
                case_id=one_case.cases[0].id,
                output=invalid.model_dump(mode="json"),
            )
        ],
    )

    assert report["schema_valid_rate"] == 1.0
    assert report["parse_success_rate"] == 0.0
    assert one_case.cases[0].id in report["granularity_errors"]
