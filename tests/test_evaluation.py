from __future__ import annotations

import json
from pathlib import Path

from src.evaluation.metrics import evaluate_manifest, validate_prediction
from src.evaluation.models import (
    EvaluationCase,
    EvaluationInput,
    EvaluationManifest,
    ExpectedLabels,
    PredictionFile,
    PredictionMatch,
    PredictionRecord,
    SourceMetadata,
)


def make_case(
    *,
    case_id: str = "case-1",
    expected_fields: dict[str, object] | None = None,
    expected_evidence: dict[str, list[str]] | None = None,
    candidate_evidence_ids: list[str] | None = None,
) -> EvaluationCase:
    return EvaluationCase(
        id=case_id,
        split="dev",
        source=SourceMetadata(
            kind="synthetic",
            reference="test",
            authorization="test-only",
        ),
        input=EvaluationInput(raw_content="这是一个长度足够的评测岗位文本，用于测试指标。"),
        candidate_evidence_ids=candidate_evidence_ids or [],
        expected=ExpectedLabels(
            fields=expected_fields or {},
            eligibility="unknown",
            evidence=expected_evidence or {},
        ),
    )


def test_m11_manifest_is_versioned_and_covers_failure_tags() -> None:
    path = Path("datasets/m11_evaluation_manifest.json")
    manifest = EvaluationManifest.model_validate_json(path.read_text(encoding="utf-8"))

    assert manifest.manifest_version == "m11-evaluation-v1"
    assert manifest.dataset_version.startswith("m11-dev-")
    tags = {tag for case in manifest.cases for tag in case.expected.tags}
    assert {"unknown", "no_evidence", "reader_failure", "invalid_model_output"} <= tags


def test_validator_removes_unknown_evidence_and_downgrades_claim() -> None:
    case = make_case(
        expected_evidence={"required_skill:RAG": ["ev-rag"]},
        candidate_evidence_ids=["ev-rag"],
    )
    prediction = PredictionRecord(
        case_id=case.id,
        matches=[
            PredictionMatch(
                requirement_key="required_skill:RAG",
                support_level="supported",
                evidence_ids=["ev-ghost"],
            )
        ],
    )

    validated = validate_prediction(prediction, case)

    assert validated.matches[0].support_level == "unsupported"
    assert validated.matches[0].evidence_ids == []
    assert validated.matches[0].validation_issues


def test_field_metrics_use_set_precision_recall_and_null_semantics() -> None:
    case = make_case(
        expected_fields={
            "job_type": "internship",
            "locations": ["上海"],
            "required_skills": ["Python"],
        }
    )
    manifest = EvaluationManifest(
        manifest_version="test-v1",
        dataset_version="test-data-v1",
        split="dev",
        purpose="test",
        source_policy="test",
        fields=["job_type", "locations", "required_skills"],
        cases=[case],
    )
    prediction = PredictionRecord(
        case_id=case.id,
        fields={
            "job_type": "internship",
            "locations": ["上海", "北京"],
            "required_skills": [],
        },
        eligibility="unknown",
    )

    report = evaluate_manifest(manifest, [prediction])
    fields = report["validated"]["fields"]

    assert fields["job_type"]["precision"] == 1.0
    assert fields["job_type"]["recall"] == 1.0
    assert fields["locations"]["precision"] == 0.5
    assert fields["locations"]["recall"] == 1.0
    assert fields["required_skills"]["precision"] is None
    assert fields["required_skills"]["recall"] == 0.0


def test_report_separates_raw_output_from_validated_output() -> None:
    case = make_case(
        expected_fields={"required_skills": ["RAG"]},
        expected_evidence={"required_skill:RAG": ["ev-rag"]},
        candidate_evidence_ids=["ev-rag"],
    )
    manifest = EvaluationManifest(
        manifest_version="test-v1",
        dataset_version="test-data-v1",
        split="dev",
        purpose="test",
        source_policy="test",
        fields=["required_skills"],
        cases=[case],
    )
    prediction = PredictionRecord(
        case_id=case.id,
        fields={"required_skills": ["RAG"]},
        eligibility="unknown",
        matches=[
            PredictionMatch(
                requirement_key="required_skill:RAG",
                support_level="supported",
                evidence_ids=["ev-ghost"],
            )
        ],
    )

    report = evaluate_manifest(manifest, [prediction])

    assert report["raw"]["unsupported_claim_rate"] == 1.0
    assert report["validated"]["unsupported_claim_rate"] == 0.0
    assert report["validated"]["failure_accuracy"] is None
    assert report["validator"]["downgraded_matches"] == 1
    assert report["validator"]["removed_evidence_ids"] == 1


def test_sample_prediction_file_is_valid_json() -> None:
    payload = json.loads(
        Path("datasets/m11_sample_predictions.json").read_text(encoding="utf-8")
    )
    assert payload["prediction_version"] == "m11-sample-predictions-v1"
    assert len(payload["predictions"]) == 12


def test_sample_evaluation_keeps_fixture_failures_visible() -> None:
    manifest = EvaluationManifest.model_validate_json(
        Path("datasets/m11_evaluation_manifest.json").read_text(encoding="utf-8")
    )
    prediction_file = PredictionFile.model_validate_json(
        Path("datasets/m11_sample_predictions.json").read_text(encoding="utf-8")
    )

    report = evaluate_manifest(manifest, prediction_file.predictions)

    assert report["validated"]["failure_accuracy"] == 1.0
    assert report["validated"]["false_accept_rate"] == 1.0
    assert report["validated"]["unsupported_claim_rate"] > 0
    assert report["thresholds"]["unsupported_claim_rate"]["passed"] is False
