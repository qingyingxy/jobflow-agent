from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from src.domain.runs import AgentRun
from src.evaluation.agent_runs import summarize_agent_runs
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
    expected_skill_mentions: list[str] | None = None,
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
            skill_mentions=expected_skill_mentions or [],
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

    assert fields["job_type"]["exact_match_accuracy"] == 1.0
    assert fields["job_type"]["precision"] == 1.0
    assert fields["job_type"]["recall"] == 1.0
    assert fields["locations"]["exact_match_accuracy"] == 0.0
    assert fields["locations"]["precision"] == 0.5
    assert fields["locations"]["recall"] == 1.0
    assert fields["required_skills"]["exact_match_accuracy"] == 0.0
    assert fields["required_skills"]["precision"] is None
    assert fields["required_skills"]["recall"] == 0.0
    assert report["successful_prediction_count"] == 1
    assert report["success_rate"] == 1.0
    assert report["timeout_count"] == 0
    assert report["timeout_rate"] == 0.0
    assert report["validated"]["supported_claim_count"] == 0


def test_skill_group_metric_ignores_display_name_and_any_of_option_order() -> None:
    case = make_case(
        expected_fields={
            "required_skill_groups": [
                {
                    "name": "推理框架",
                    "any_of": ["TensorRT", "vLLM"],
                    "allow_other": True,
                }
            ]
        }
    )
    manifest = EvaluationManifest(
        manifest_version="test-v1",
        dataset_version="test-data-v1",
        split="dev",
        purpose="test",
        source_policy="test",
        fields=["required_skill_groups"],
        cases=[case],
    )
    prediction = PredictionRecord(
        case_id=case.id,
        fields={
            "required_skill_groups": [
                {
                    "name": "大模型端侧推理工具",
                    "any_of": ["vllm", "TensorRT", "vLLM"],
                    "allow_other": True,
                }
            ]
        },
    )

    result = evaluate_manifest(manifest, [prediction])["validated"]["fields"]

    assert result["required_skill_groups"]["exact_match_accuracy"] == 1.0
    assert result["required_skill_groups"]["f1"] == 1.0


def test_skill_metrics_share_parser_ontology_for_aliases_and_categories() -> None:
    case = make_case(
        expected_fields={
            "required_skills": ["深度学习框架"],
            "required_skill_groups": [
                {
                    "name": "编程语言",
                    "any_of": ["TypeScript", "Go"],
                    "allow_other": False,
                }
            ],
        }
    )
    manifest = EvaluationManifest(
        manifest_version="test-v1",
        dataset_version="test-data-v1",
        split="dev",
        purpose="test",
        source_policy="test",
        fields=["required_skills", "required_skill_groups"],
        cases=[case],
    )
    prediction = PredictionRecord(
        case_id=case.id,
        fields={
            "required_skills": ["训练框架"],
            "required_skill_groups": [
                {
                    "name": "开发语言",
                    "any_of": ["TS", "Golang"],
                    "allow_other": False,
                }
            ],
        },
    )

    fields = evaluate_manifest(manifest, [prediction])["validated"]["fields"]

    assert fields["required_skills"]["f1"] == 1.0
    assert fields["required_skill_groups"]["f1"] == 1.0


def test_skill_detection_ignores_strength_but_strength_metric_does_not() -> None:
    case = make_case(
        expected_fields={
            "required_skills": ["Python"],
            "preferred_skills": ["CUDA"],
        },
        expected_skill_mentions=["Python", "CUDA", "RAG"],
    )
    manifest = EvaluationManifest(
        manifest_version="test-v1",
        dataset_version="test-data-v1",
        split="dev",
        purpose="test",
        source_policy="test",
        fields=["required_skills", "preferred_skills"],
        cases=[case],
    )
    prediction = PredictionRecord(
        case_id=case.id,
        fields={
            "required_skills": ["CUDA"],
            "preferred_skills": ["Python"],
            "skill_mentions": ["RAG"],
        },
    )

    metrics = evaluate_manifest(manifest, [prediction])["validated"]

    assert metrics["skill_detection"]["f1"] == 1.0
    assert metrics["skill_detection"]["exact_match_accuracy"] == 1.0
    assert metrics["skill_strength"]["classes"]["required"]["f1"] == 0.0
    assert metrics["skill_strength"]["classes"]["preferred"]["f1"] == 0.0
    assert metrics["skill_strength"]["classes"]["mention"]["f1"] == 1.0
    assert metrics["skill_strength"]["macro_f1"] == 1 / 3


def test_skill_metrics_fall_back_to_fields_and_exclude_group_options_from_strength() -> None:
    case = make_case(
        expected_fields={
            "required_skills": ["Python"],
            "required_skill_groups": [
                {
                    "name": "训练框架",
                    "any_of": ["PyTorch", "TensorFlow"],
                    "allow_other": False,
                }
            ],
            "preferred_skills": ["CUDA"],
        }
    )
    manifest = EvaluationManifest(
        manifest_version="test-v1",
        dataset_version="test-data-v1",
        split="dev",
        purpose="test",
        source_policy="test",
        fields=["required_skills", "required_skill_groups", "preferred_skills"],
        cases=[case],
    )
    prediction = PredictionRecord(
        case_id=case.id,
        fields={
            "required_skills": ["Python"],
            "required_skill_groups": [
                {
                    "name": "深度学习工具",
                    "any_of": ["tensorflow", "PyTorch"],
                    "allow_other": False,
                }
            ],
            "preferred_skills": ["CUDA"],
            "skill_mentions": ["PyTorch", "TensorFlow"],
        },
    )

    metrics = evaluate_manifest(manifest, [prediction])["validated"]

    assert metrics["skill_detection"]["tp"] == 4
    assert metrics["skill_detection"]["f1"] == 1.0
    assert metrics["skill_strength"]["classes"]["required"]["tp"] == 1
    assert metrics["skill_strength"]["classes"]["preferred"]["tp"] == 1
    assert metrics["skill_strength"]["classes"]["mention"]["tp"] == 0
    assert metrics["skill_strength"]["classes"]["mention"]["fp"] == 0


def test_any_of_relation_metric_splits_conditional_accuracy_and_false_positives() -> None:
    expected_group = {
        "name": "编程语言",
        "any_of": ["TypeScript", "Go"],
        "allow_other": False,
    }
    cases = [
        make_case(
            case_id="group-match",
            expected_fields={"required_skill_groups": [expected_group]},
        ),
        make_case(
            case_id="group-miss",
            expected_fields={"required_skill_groups": [expected_group]},
        ),
        make_case(case_id="false-positive"),
        make_case(case_id="true-negative"),
    ]
    manifest = EvaluationManifest(
        manifest_version="test-v1",
        dataset_version="test-data-v1",
        split="dev",
        purpose="test",
        source_policy="test",
        fields=["required_skill_groups"],
        cases=cases,
    )
    predictions = [
        PredictionRecord(
            case_id="group-match",
            fields={
                "required_skill_groups": [
                    {
                        "name": "开发语言",
                        "any_of": ["Golang", "TS"],
                        "allow_other": False,
                    }
                ]
            },
        ),
        PredictionRecord(case_id="group-miss"),
        PredictionRecord(
            case_id="false-positive",
            fields={
                "required_skill_groups": [
                    {
                        "name": "推理框架",
                        "any_of": ["TensorRT", "vLLM"],
                        "allow_other": True,
                    }
                ]
            },
        ),
        PredictionRecord(case_id="true-negative"),
    ]

    metric = evaluate_manifest(manifest, predictions)["validated"][
        "any_of_relations"
    ]

    assert metric == {
        "expected_positive_case_count": 2,
        "exact_match_case_count": 1,
        "conditional_exact_match_accuracy": 0.5,
        "expected_negative_case_count": 2,
        "false_positive_case_count": 1,
        "false_positive_case_rate": 0.5,
    }


def test_report_exposes_failure_codes_and_timeout_rate() -> None:
    cases = [make_case(case_id="case-success"), make_case(case_id="case-timeout")]
    manifest = EvaluationManifest(
        manifest_version="test-v1",
        dataset_version="test-data-v1",
        split="dev",
        purpose="test",
        source_policy="test",
        fields=["job_type"],
        cases=cases,
    )
    predictions = [
        PredictionRecord(
            case_id="case-success",
            warnings=[
                {
                    "code": "unsupported_field_value",
                    "field_path": "preferred_skills[0]",
                    "value": "GhostSkill",
                    "message": "已删除无原文依据的技能值：GhostSkill",
                }
            ],
        ),
        PredictionRecord(case_id="case-timeout", failure_code="model_timeout"),
    ]

    report = evaluate_manifest(manifest, predictions)

    assert report["successful_prediction_count"] == 1
    assert report["success_rate"] == 0.5
    assert report["failure_codes"] == {"model_timeout": 1}
    assert report["prediction_warning_count"] == 1
    assert report["warning_codes"] == {"unsupported_field_value": 1}
    assert report["timeout_count"] == 1
    assert report["timeout_rate"] == 0.5


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
    assert report["thresholds"]["false_accept_rate"]["passed"] is False
    assert report["thresholds"]["unsupported_claim_rate"]["passed"] is False


def test_agent_run_summary_is_scoped_and_does_not_expose_payloads(db_session) -> None:
    started_at = datetime.now(UTC)
    db_session.add_all(
        [
            AgentRun(
                id="run_eval_success",
                user_id="user-a",
                run_type="jd_parse",
                target_type="job_posting",
                target_id="job-1",
                status="succeeded",
                model="fake-model",
                prompt_version="prompt-v1",
                input_hash="a" * 64,
                output={"sensitive": "not included in summary"},
                validation_status="passed",
                validation_result={"status": "passed"},
                started_at=started_at,
                finished_at=started_at,
                duration_ms=12.5,
            ),
            AgentRun(
                id="run_eval_failure",
                user_id="user-a",
                run_type="evidence_match",
                target_type="job_requirement",
                target_id="job-1:0",
                status="failed",
                model="fake-model",
                prompt_version="prompt-v1",
                input_hash="b" * 64,
                validation_status="failed",
                validation_result={"status": "failed", "code": "model_timeout"},
                started_at=started_at,
                finished_at=started_at,
                duration_ms=25.0,
            ),
            AgentRun(
                id="run_other_user",
                user_id="user-b",
                run_type="jd_parse",
                target_type="job_posting",
                target_id="job-2",
                status="succeeded",
                model="other-model",
                prompt_version="prompt-v2",
                input_hash="c" * 64,
                validation_status="passed",
                validation_result={"status": "passed"},
                started_at=started_at,
                finished_at=started_at,
                duration_ms=5.0,
            ),
        ]
    )
    db_session.commit()

    summary = summarize_agent_runs(db_session, user_id="user-a")

    assert summary["count"] == 2
    assert summary["succeeded_count"] == 1
    assert summary["failed_count"] == 1
    assert summary["validation_failed_count"] == 1
    assert summary["run_types"] == {"evidence_match": 1, "jd_parse": 1}
    assert summary["failure_codes"] == {"model_timeout": 1}
    assert summary["duration_ms"]["average"] == 18.75
    assert "output" not in summary
