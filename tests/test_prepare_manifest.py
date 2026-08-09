from __future__ import annotations

from src.evaluation.models import (
    EvaluationCase,
    EvaluationInput,
    EvaluationManifest,
    ExpectedLabels,
    SourceMetadata,
)
from src.evaluation.prepare_manifest import prepare_strict_manifest


def make_manifest() -> EvaluationManifest:
    cases = []
    for case_id in ("keep", "drop"):
        cases.append(
            EvaluationCase(
                id=case_id,
                split="eval",
                source=SourceMetadata(
                    kind="real_public_source",
                    reference=f"https://example.com/{case_id}",
                    authorization="test",
                ),
                input=EvaluationInput(
                    raw_content="岗位名称：AI 工程师\n任职要求：熟悉 Python。",
                    source_url=f"https://example.com/{case_id}",
                    scenario="test",
                ),
                expected=ExpectedLabels(
                    fields={
                        "job_type": "campus",
                        "locations": ["北京"],
                        "required_skills": ["Python"],
                    },
                    skill_mentions=["Python"],
                ),
            )
        )
    return EvaluationManifest(
        manifest_version="test-v1",
        dataset_version="test-v1",
        split="eval",
        purpose="test",
        source_policy="test",
        fields=["job_type", "locations", "required_skills"],
        cases=cases,
    )


def test_prepare_strict_manifest_excludes_cases_and_metadata_fields() -> None:
    manifest, review = prepare_strict_manifest(
        make_manifest().model_dump(),
        {
            "source_record_count": 2,
            "cases": [
                {
                    "id": "keep",
                    "company": "示例公司",
                    "review_required": False,
                    "review_reasons": [],
                    "source_flags": ["招聘类型来自外部元数据"],
                },
                {
                    "id": "drop",
                    "company": "示例公司",
                    "review_required": True,
                    "review_reasons": ["需要人工复核"],
                    "source_flags": [],
                },
            ],
        },
        exclude_review_required=True,
        exclude_metadata_only_fields=True,
    )

    assert [case.id for case in manifest.cases] == ["keep"]
    assert "job_type" not in manifest.cases[0].expected.fields
    assert manifest.cases[0].expected.fields["locations"] == ["北京"]
    assert manifest.cases[0].expected.skill_mentions == ["Python"]
    assert review["excluded_case_count"] == 1
    assert review["excluded_field_counts"] == {"job_type": 1}
    assert review["field_labeled_case_count"]["job_type"] == 0
