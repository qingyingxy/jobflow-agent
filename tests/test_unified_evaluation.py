from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from scripts.build_unified_annotation_batch import build_annotation_batch
from scripts.build_unified_dev50_draft import merge_annotation_batches
from scripts.build_unified_dev50_review_checklist import render_review_checklist
from scripts.build_unified_dev50_skeleton import (
    build_dev_skeleton,
    eligible_records,
    select_balanced_extras,
)
from src.domain.unified_jd import UnifiedJDModelOutput
from src.evaluation.run_unified import main as run_unified_main
from src.evaluation.unified_metrics import evaluate_unified_manifest
from src.evaluation.unified_models import (
    UnifiedEvaluationCase,
    UnifiedEvaluationManifest,
    UnifiedEvaluationSource,
    UnifiedEvaluationThresholds,
    UnifiedPredictionFile,
    UnifiedPredictionRecord,
)

SOURCE = (
    "招聘类型：实习生\n工作地点：上海市\n任职要求：熟悉 Python；有 RAG 项目经验者优先。"
)


def _output(
    *,
    required_level: str = "required",
    job_type: str = "internship",
    job_type_evidence: str = "招聘类型：实习生",
    clause_evidence: str = "任职要求：熟悉 Python",
) -> UnifiedJDModelOutput:
    return UnifiedJDModelOutput.model_validate(
        {
            "facts": {
                "job_type": job_type,
                "locations": ["上海"],
                "graduation_years": None,
                "education_requirements": None,
                "major_requirements": None,
                "internship_duration_months": None,
                "weekly_days": None,
                "earliest_start_date": None,
                "deadline": None,
                "evidence": [
                    {
                        "field": "job_type",
                        "source_text": job_type_evidence,
                    },
                    {
                        "field": "locations",
                        "source_text": "工作地点：上海市",
                    },
                ],
            },
            "clauses": [
                {
                    "category": "skill",
                    "level": required_level,
                    "items": ["Python"],
                    "source_text": clause_evidence,
                },
                {
                    "category": "experience",
                    "level": "preferred",
                    "items": ["RAG 项目经验"],
                    "qualifier": {
                        "experience_type": "project",
                        "domain": "RAG",
                    },
                    "source_text": "有 RAG 项目经验者优先",
                },
            ],
        }
    )


def _case(
    *,
    expected: UnifiedJDModelOutput | None = None,
    status: str = "frozen",
) -> UnifiedEvaluationCase:
    return UnifiedEvaluationCase(
        id="case-1",
        split="dev",
        source=UnifiedEvaluationSource(
            kind="synthetic_fixture",
            company="测试公司",
            title="测试岗位",
            source_url="https://example.test/jobs/1",
            authorization="test-only",
        ),
        raw_content=SOURCE,
        source_content_sha256=hashlib.sha256(SOURCE.encode("utf-8")).hexdigest(),
        annotation_status=status,
        expected=expected,
    )


def _manifest(
    expected: UnifiedJDModelOutput,
    **thresholds: object,
) -> UnifiedEvaluationManifest:
    return UnifiedEvaluationManifest(
        manifest_version="unified-test-v1",
        dataset_version="unified-test-data-v1",
        split="dev",
        purpose="test unified metrics",
        source_policy="synthetic test data only",
        annotation_guide_version="unified-jd-annotation-guide-v1",
        label_status="frozen",
        thresholds=UnifiedEvaluationThresholds(**thresholds),
        cases=[_case(expected=expected)],
    )


def test_pending_case_rejects_prefilled_expected() -> None:
    with pytest.raises(ValidationError, match="pending 样本不能预填 expected"):
        _case(expected=_output(), status="pending")


def test_draft_case_accepts_source_valid_expected_but_cannot_be_evaluated() -> None:
    draft_case = _case(expected=_output(), status="draft")
    manifest = UnifiedEvaluationManifest(
        manifest_version="draft-v1",
        dataset_version="draft-data-v1",
        split="dev",
        purpose="machine-assisted annotation draft",
        source_policy="test",
        annotation_guide_version="unified-jd-annotation-guide-v1",
        label_status="draft",
        cases=[draft_case],
    )

    with pytest.raises(ValueError, match="人工复核"):
        evaluate_unified_manifest(manifest, [])


def test_reviewed_case_requires_exact_source_hash_and_evidence() -> None:
    payload = _case(expected=_output()).model_dump(mode="json")
    payload["source_content_sha256"] = "0" * 64
    with pytest.raises(ValidationError, match="raw_content 不一致"):
        UnifiedEvaluationCase.model_validate(payload)

    payload = _case(expected=_output()).model_dump(mode="json")
    payload["expected"]["clauses"][0]["source_text"] = "原文不存在"
    with pytest.raises(ValidationError, match="无法在 JD 中定位"):
        UnifiedEvaluationCase.model_validate(payload)


def test_perfect_prediction_passes_all_unified_gates() -> None:
    expected = _output()
    manifest = _manifest(
        expected,
        schema_valid_rate_min=1,
        parse_success_rate_min=1,
        parse_success_count_min=1,
        facts_macro_f1_min=1,
        clause_type_relation_f1_min=1,
        required_clause_recall_min=1,
        required_preferred_confusion_count_max=0,
        unsupported_critical_fact_count_max=0,
        evidence_localization_rate_min=1,
        facts_value_macro_f1_min=1,
        evidence_span_character_f1_min=1,
        clause_category_f1_min=1,
        clause_level_f1_min=1,
        clause_relation_f1_min=1,
        canonical_items_f1_min=1,
    )
    prediction = UnifiedPredictionRecord(
        case_id="case-1",
        output=expected.model_dump(mode="json"),
    )

    report = evaluate_unified_manifest(manifest, [prediction])

    assert report["schema_valid_rate"] == 1.0
    assert report["parse_success_rate"] == 1.0
    assert report["facts"]["field_count"] == 9
    assert report["facts"]["macro_f1"] == 1.0
    assert report["clauses"]["all"]["f1"] == 1.0
    assert report["evaluation_version"] == "unified-jd-evaluator-v2"
    assert report["dimensions"]["facts"]["macro_f1"] == 1.0
    assert (
        report["dimensions"]["evidence_spans"]["all"]["character_coverage"]["f1"] == 1.0
    )
    assert report["dimensions"]["category"]["overall"]["f1"] == 1.0
    assert report["dimensions"]["level"]["overall"]["f1"] == 1.0
    assert report["dimensions"]["relation"]["overall"]["f1"] == 1.0
    assert report["dimensions"]["canonical_items"]["overall"]["f1"] == 1.0
    assert report["clauses"]["required"]["recall"] == 1.0
    assert report["required_preferred_confusions"]["total"] == 0
    assert report["evidence"]["localization_rate"] == 1.0
    assert report["gate"]["passed"] is True


def test_required_preferred_confusion_is_counted_separately() -> None:
    expected = _output(required_level="required")
    prediction = _output(required_level="preferred")
    manifest = _manifest(
        expected,
        clause_type_relation_f1_min=0.88,
        required_clause_recall_min=0.95,
        required_preferred_confusion_count_max=0,
    )

    report = evaluate_unified_manifest(
        manifest,
        [
            UnifiedPredictionRecord(
                case_id="case-1",
                output=prediction.model_dump(mode="json"),
            )
        ],
    )

    assert report["clauses"]["all"]["tp"] == 1
    assert report["clauses"]["all"]["fp"] == 1
    assert report["clauses"]["all"]["fn"] == 1
    assert report["clauses"]["required"]["recall"] == 0.0
    assert report["required_preferred_confusions"] == {
        "total": 1,
        "required_as_preferred": 1,
        "preferred_as_required": 0,
        "by_case": [
            {
                "case_id": "case-1",
                "required_as_preferred": 1,
                "preferred_as_required": 0,
            }
        ],
    }
    assert report["gate"]["passed"] is False
    assert len(report["gate"]["failure_reasons"]) == 3


def test_unlocated_evidence_is_schema_valid_but_not_parse_success() -> None:
    expected = _output()
    prediction = _output(
        job_type_evidence="不存在的岗位类型证据",
        clause_evidence="不存在的技能证据",
    )
    manifest = _manifest(expected)

    report = evaluate_unified_manifest(
        manifest,
        [
            UnifiedPredictionRecord(
                case_id="case-1",
                output=prediction.model_dump(mode="json"),
            )
        ],
    )

    assert report["schema_valid_count"] == 1
    assert report["parse_success_count"] == 0
    assert report["unsupported_critical_facts"] == {
        "count": 1,
        "items": [
            {
                "case_id": "case-1",
                "field": "job_type",
                "reasons": ["missing_locatable_evidence"],
                "unexpected_values": [],
            }
        ],
    }
    assert report["evidence"]["conclusion_count"] == 4
    assert report["evidence"]["localized_conclusion_count"] == 2
    assert report["evidence"]["localization_rate"] == 0.5
    assert report["facts"]["fields"]["job_type"]["fn"] == 1
    assert report["dimensions"]["facts"]["macro_f1"] == 1.0
    assert report["dimensions"]["category"]["overall"]["f1"] == 1.0
    assert report["dimensions"]["evidence_spans"]["all"]["exact"]["f1"] < 1.0


def test_evidence_span_reports_exact_overlap_and_character_coverage() -> None:
    expected = _output()
    prediction = _output(clause_evidence="熟悉 Python")

    report = evaluate_unified_manifest(
        _manifest(expected),
        [
            UnifiedPredictionRecord(
                case_id="case-1",
                output=prediction.model_dump(mode="json"),
            )
        ],
    )

    clause_spans = report["dimensions"]["evidence_spans"]["clause_evidence"]
    assert clause_spans["expected_count"] == 2
    assert clause_spans["predicted_count"] == 2
    assert clause_spans["exact"]["tp"] == 1
    assert clause_spans["exact"]["f1"] == 0.5
    assert clause_spans["overlap"]["tp"] == 2
    assert clause_spans["overlap"]["f1"] == 1.0
    assert 0.8 < clause_spans["character_coverage"]["f1"] < 1.0
    assert report["dimensions"]["category"]["span_aligned"]["accuracy"] == 1.0


def test_clause_dimensions_do_not_require_full_signature_match() -> None:
    expected_payload = _output().model_dump(mode="json")
    expected_payload["clauses"] = [
        {
            "category": "responsibility",
            "level": "mention",
            "items": ["Python"],
            "source_text": "任职要求：熟悉 Python",
        }
    ]
    prediction_payload = _output().model_dump(mode="json")
    prediction_payload["clauses"] = [
        {
            "category": "responsibility",
            "level": "mention",
            "items": ["任职要求：熟悉 Python"],
            "source_text": "任职要求：熟悉 Python",
        }
    ]
    expected = UnifiedJDModelOutput.model_validate(expected_payload)
    prediction = UnifiedJDModelOutput.model_validate(prediction_payload)

    report = evaluate_unified_manifest(
        _manifest(
            expected,
            evidence_span_character_f1_min=1,
            clause_category_f1_min=1,
            clause_level_f1_min=1,
            clause_relation_f1_min=1,
            canonical_items_f1_min=1,
        ),
        [
            UnifiedPredictionRecord(
                case_id="case-1",
                output=prediction.model_dump(mode="json"),
            )
        ],
    )

    assert report["clauses"]["all"]["f1"] == 0.0
    assert report["dimensions"]["evidence_spans"]["all"]["exact"]["f1"] == 1.0
    assert report["dimensions"]["category"]["overall"]["f1"] == 1.0
    assert report["dimensions"]["level"]["overall"]["f1"] == 1.0
    assert report["dimensions"]["relation"]["overall"]["f1"] == 1.0
    assert report["dimensions"]["canonical_items"]["overall"] == {
        "tp": 0,
        "fp": 1,
        "fn": 1,
        "precision": 0.0,
        "recall": 0.0,
        "f1": 0.0,
        "comparison_count": 1,
        "exact_match_accuracy": 0.0,
    }
    assert report["gate"]["passed"] is False
    assert report["gate"]["failure_reasons"] == ["canonical_items_f1=0.0 未满足 >= 1.0"]


def test_category_level_and_relation_have_independent_metrics() -> None:
    expected = _output()
    prediction_payload = expected.model_dump(mode="json")
    prediction_payload["clauses"][0]["category"] = "capability"
    prediction_payload["clauses"][0]["level"] = "preferred"
    prediction_payload["clauses"][0]["items"] = ["Python 编程"]
    prediction = UnifiedJDModelOutput.model_validate(prediction_payload)

    report = evaluate_unified_manifest(
        _manifest(expected),
        [
            UnifiedPredictionRecord(
                case_id="case-1",
                output=prediction.model_dump(mode="json"),
            )
        ],
    )

    assert report["dimensions"]["facts"]["macro_f1"] == 1.0
    assert report["dimensions"]["category"]["overall"]["f1"] == 0.5
    assert report["dimensions"]["category"]["span_aligned"]["accuracy"] == 0.5
    assert report["dimensions"]["level"]["overall"]["f1"] == 0.5
    assert report["dimensions"]["level"]["span_aligned"]["accuracy"] == 0.5
    assert report["dimensions"]["relation"]["overall"]["f1"] == 1.0
    assert report["dimensions"]["canonical_items"]["overall"]["f1"] == 0.5


def test_wrong_fact_value_is_unsupported_even_when_quote_exists() -> None:
    expected = _output()
    prediction = _output(job_type="full_time")

    report = evaluate_unified_manifest(
        _manifest(expected),
        [
            UnifiedPredictionRecord(
                case_id="case-1",
                output=prediction.model_dump(mode="json"),
            )
        ],
    )

    assert report["parse_success_rate"] == 1.0
    assert report["unsupported_critical_facts"] == {
        "count": 1,
        "items": [
            {
                "case_id": "case-1",
                "field": "job_type",
                "reasons": ["value_not_in_human_label"],
                "unexpected_values": ["full_time"],
            }
        ],
    }
    assert report["facts"]["fields"]["job_type"]["fp"] == 1
    assert report["facts"]["fields"]["job_type"]["fn"] == 1


def test_invalid_schema_and_missing_predictions_reduce_rates() -> None:
    expected = _output()
    case_two = _case(expected=expected).model_copy(update={"id": "case-2"})
    manifest = _manifest(expected).model_copy(
        update={"cases": [_case(expected=expected), case_two]}
    )

    report = evaluate_unified_manifest(
        manifest,
        [UnifiedPredictionRecord(case_id="case-1", output={"facts": {}})],
    )

    assert report["schema_valid_rate"] == 0.0
    assert report["parse_success_rate"] == 0.0
    assert report["missing_case_ids"] == ["case-2"]
    assert "case-1" in report["schema_errors"]


def test_pending_manifest_cannot_be_evaluated() -> None:
    pending_case = _case(expected=None, status="pending")
    manifest = UnifiedEvaluationManifest(
        manifest_version="pending-v1",
        dataset_version="pending-data-v1",
        split="dev",
        purpose="annotation skeleton",
        source_policy="test",
        annotation_guide_version="unified-jd-annotation-guide-v1",
        label_status="pending",
        cases=[pending_case],
    )

    with pytest.raises(ValueError, match="人工复核"):
        evaluate_unified_manifest(manifest, [])


def test_unified_cli_writes_machine_readable_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = _output()
    manifest_path = tmp_path / "manifest.json"
    prediction_path = tmp_path / "predictions.json"
    report_path = tmp_path / "report.json"
    manifest_path.write_text(
        _manifest(expected).model_dump_json(indent=2),
        encoding="utf-8",
    )
    prediction_path.write_text(
        UnifiedPredictionFile(
            prediction_version="test-prediction-v1",
            predictions=[
                UnifiedPredictionRecord(
                    case_id="case-1",
                    output=expected.model_dump(mode="json"),
                )
            ],
        ).model_dump_json(indent=2),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_unified",
            "--manifest",
            str(manifest_path),
            "--predictions",
            str(prediction_path),
            "--output",
            str(report_path),
        ],
    )

    assert run_unified_main() == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["prediction_version"] == "test-prediction-v1"
    assert report["run"]["model_api_called"] is False


def test_dev_skeleton_builder_does_not_copy_legacy_labels() -> None:
    records = [
        {
            "id": "case-a",
            "company": "A",
            "title": "岗位 A",
            "source_url": "https://example.test/a",
            "raw_content": SOURCE,
            "official_source": True,
            "enabled_for_parser_eval": True,
            "required_skills": ["不应复制"],
        },
        {
            "id": "case-b",
            "company": "B",
            "title": "岗位 B",
            "source_url": "https://example.test/b",
            "raw_content": SOURCE,
            "official_source": True,
            "enabled_for_parser_eval": True,
        },
    ]
    records_by_id = eligible_records(records)
    assert select_balanced_extras(
        records_by_id,
        anchor_ids=["case-a"],
        excluded_ids=set(),
        count=1,
    ) == ["case-b"]

    skeleton = build_dev_skeleton(["case-a"], records_by_id)
    assert skeleton["cases"][0]["expected"] is None
    assert skeleton["cases"][0]["annotation_status"] == "pending"
    assert "required_skills" not in json.dumps(skeleton, ensure_ascii=False)


def test_annotation_batch_stays_draft_and_validates_source_evidence() -> None:
    records = eligible_records(
        [
            {
                "id": "case-a",
                "company": "A",
                "title": "岗位 A",
                "source_url": "https://example.test/a",
                "raw_content": SOURCE,
                "official_source": True,
                "enabled_for_parser_eval": True,
            }
        ]
    )
    skeleton = build_dev_skeleton(["case-a"], records)
    labels = {
        "label_version": "draft-batch-v1",
        "dataset_version": "draft-data-v1",
        "annotation_status": "draft",
        "cases": {
            "case-a": {
                "expected": _output().model_dump(mode="json"),
                "coverage_tags": ["required", "preferred"],
            }
        },
    }

    manifest = build_annotation_batch(skeleton, labels)

    assert manifest.label_status == "draft"
    assert manifest.cases[0].annotation_status == "draft"
    with pytest.raises(ValueError, match="人工复核"):
        evaluate_unified_manifest(manifest, [])

    labels["cases"]["case-a"]["expected"]["clauses"][0]["source_text"] = "not in source"
    with pytest.raises(ValidationError, match="无法在 JD 中定位"):
        build_annotation_batch(skeleton, labels)


def test_dev50_draft_merge_requires_exact_unique_skeleton_coverage() -> None:
    records = eligible_records(
        [
            {
                "id": case_id,
                "company": case_id,
                "title": f"岗位 {case_id}",
                "source_url": f"https://example.test/{case_id}",
                "raw_content": SOURCE,
                "official_source": True,
                "enabled_for_parser_eval": True,
            }
            for case_id in ("case-a", "case-b")
        ]
    )
    skeleton = build_dev_skeleton(["case-a", "case-b"], records)

    def batch(case_id: str) -> dict[str, object]:
        return {
            "annotation_status": "draft",
            "source_skeleton_sha256": "skeleton-hash",
            "cases": {
                case_id: {
                    "expected": _output().model_dump(mode="json"),
                    "coverage_tags": ["required", "preferred"],
                }
            },
        }

    case_a = batch("case-a")
    case_b = batch("case-b")
    manifest = merge_annotation_batches(
        skeleton,
        [case_b, case_a],
        source_skeleton_sha256="skeleton-hash",
    )

    assert [case.id for case in manifest.cases] == ["case-a", "case-b"]
    assert manifest.label_status == "draft"
    with pytest.raises(ValueError, match="重复 case"):
        merge_annotation_batches(skeleton, [case_a, case_a, case_b])
    with pytest.raises(ValueError, match="缺少 case"):
        merge_annotation_batches(skeleton, [case_a])
    with pytest.raises(ValueError, match="skeleton hash 不匹配"):
        merge_annotation_batches(
            skeleton,
            [case_a, case_b],
            source_skeleton_sha256="different-hash",
        )


def test_review_checklist_keeps_draft_status_and_surfaces_risk() -> None:
    draft_case = _case(expected=_output(), status="draft").model_copy(
        update={
            "coverage_tags": ["mixed_strength"],
            "review_notes": ["学历条件冲突，必须人工裁决。"],
        }
    )
    manifest = UnifiedEvaluationManifest(
        manifest_version="draft-v1",
        dataset_version="draft-data-v1",
        split="dev",
        purpose="machine-assisted annotation draft",
        source_policy="test",
        annotation_guide_version="unified-jd-annotation-guide-v1",
        label_status="draft",
        cases=[draft_case],
    )

    rendered = render_review_checklist(
        manifest,
        source_path="draft.json",
        source_sha256="abc123",
    )

    assert "- [ ] 第一轮人工逐条复核完成" in rendered
    assert "## 高优先级：已知争议（1）" in rendered
    assert "### [ ] `case-1`" in rendered
    assert "学历条件冲突" in rendered
    assert "不会把 draft 自动升级为 human_reviewed" in rendered


def test_frozen_unified_split_has_no_overlap_or_label_leakage() -> None:
    payload = json.loads(
        Path("datasets/unified_jd_eval_split_v1_2026_09_03.json").read_text(
            encoding="utf-8"
        )
    )
    dev_ids = {item["id"] for item in payload["dev"]["cases"]}
    sealed_ids = {item["id"] for item in payload["sealed_blind"]["cases"]}
    rendered = json.dumps(payload, ensure_ascii=False)

    assert payload["status"] == "selection_frozen_labels_pending"
    assert len(dev_ids) == payload["dev"]["case_count"] == 50
    assert len(sealed_ids) == payload["sealed_blind"]["case_count"] == 30
    assert not dev_ids & sealed_ids
    assert len(payload["dev"]["distribution"]["companies"]) == 24
    assert "raw_content" not in rendered
    assert "expected" not in rendered
    assert "required_skills" not in rendered
