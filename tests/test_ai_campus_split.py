from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from src.domain.skill_normalizer import (
    normalize_atomic_skill_values,
    normalize_skill_group,
)
from src.evaluation.ai_campus_split import build_split_payload
from src.evaluation.models import EvaluationManifest

SOURCE_DATA = Path("artifacts/evaluation/m11-ai-campus-source-full-2026-08-31.json")
SOURCE_MANIFEST = Path(
    "artifacts/evaluation/m11-ai-campus-manifest-full-v4-strict-2026-08-31.json"
)
SPLIT_ARTIFACT = Path("datasets/ai_campus_remaining_51_split_v1_2026_09_02.json")
V31_DEV_SELECTION = Path(
    "datasets/ai_campus_v31_dev15_selection_2026_09_02.json"
)
V32_DEV_SELECTION = Path(
    "datasets/ai_campus_v32_dev3_selection_2026_09_02.json"
)
V33_DEV_SELECTION = Path(
    "datasets/ai_campus_v33_dev5_selection_2026_09_02.json"
)
DEV_LABELS = Path(
    "datasets/ai_campus_label_overrides_v14_remaining51_dev21_reviewed.json"
)
DEV_FREEZE = Path("datasets/ai_campus_dev21_label_freeze_v1_2026_09_02.json")
DEV_STRICT_MANIFEST = Path(
    "artifacts/evaluation/"
    "m11-ai-campus-manifest-core-v20-label-v14-remaining51-dev21-strict-"
    "2026-09-02.json"
)
DEV_STRICT_REVIEW = Path(
    "artifacts/evaluation/"
    "m11-ai-campus-review-core-v20-label-v14-remaining51-dev21-strict-"
    "2026-09-02.json"
)
HOLDOUT_LABELS = Path(
    "datasets/ai_campus_label_overrides_v15_remaining51_holdout30_reviewed.json"
)
HOLDOUT_FREEZE = Path(
    "datasets/ai_campus_holdout30_label_freeze_v1_2026_09_02.json"
)
HOLDOUT_STRICT_MANIFEST = Path(
    "artifacts/evaluation/"
    "m11-ai-campus-manifest-core-v28-label-v15-remaining51-holdout30-strict-"
    "2026-09-02.json"
)
HOLDOUT_STRICT_REVIEW = Path(
    "artifacts/evaluation/"
    "m11-ai-campus-review-core-v28-label-v15-remaining51-holdout30-strict-"
    "2026-09-02.json"
)


def test_remaining_51_split_is_reproducible_and_complete() -> None:
    expected = json.loads(SPLIT_ARTIFACT.read_text(encoding="utf-8"))
    regenerated = build_split_payload(SOURCE_DATA, SOURCE_MANIFEST)

    assert regenerated == expected
    dev_ids = set(expected["dev"]["case_ids"])
    holdout_ids = set(expected["sealed_holdout"]["case_ids"])
    candidate_ids = set(expected["candidate_case_ids"])
    assert len(dev_ids) == 21
    assert len(holdout_ids) == 30
    assert not dev_ids & holdout_ids
    assert dev_ids | holdout_ids == candidate_ids
    assert len(candidate_ids) == 51


def test_remaining_51_split_preserves_company_and_internship_coverage() -> None:
    payload = json.loads(SPLIT_ARTIFACT.read_text(encoding="utf-8"))
    records = json.loads(SOURCE_DATA.read_text(encoding="utf-8"))
    records_by_id = {record["id"]: record for record in records}
    candidate_ids = payload["candidate_case_ids"]
    dev_ids = set(payload["dev"]["case_ids"])
    holdout_ids = set(payload["sealed_holdout"]["case_ids"])
    company_counts = Counter(
        records_by_id[case_id]["company"] for case_id in candidate_ids
    )

    for company, count in company_counts.items():
        if count < 2:
            continue
        assert any(records_by_id[case_id]["company"] == company for case_id in dev_ids)
        assert any(
            records_by_id[case_id]["company"] == company for case_id in holdout_ids
        )

    assert payload["dev"]["recruitment_type_counts"]["实习生"] > 0
    assert payload["sealed_holdout"]["recruitment_type_counts"]["实习生"] > 0


def test_v31_dev15_selection_uses_only_non_blind_dev_cases() -> None:
    split = json.loads(SPLIT_ARTIFACT.read_text(encoding="utf-8"))
    selection = json.loads(V31_DEV_SELECTION.read_text(encoding="utf-8"))

    selected_ids = [case["id"] for case in selection["cases"]]
    bucket_ids = [
        case_id
        for case_ids in selection["buckets"].values()
        for case_id in case_ids
    ]
    dev_ids = set(split["dev"]["case_ids"])
    holdout_ids = set(split["sealed_holdout"]["case_ids"])

    assert selection["status"] == "development_not_holdout"
    assert selection["case_count"] == 15
    assert len(selected_ids) == len(set(selected_ids)) == 15
    assert set(selected_ids) == set(bucket_ids)
    assert set(selected_ids) <= dev_ids
    assert not set(selected_ids) & holdout_ids
    assert selection["blind_data_policy"] == {
        "blind8_included": False,
        "blind8_prediction_reuse": False,
        "note": "No blind-8 JD or prediction may be used for v31 tuning or replay.",
    }
    assert all(case["coverage"] for case in selection["cases"])


def test_v32_dev3_selection_uses_new_non_blind_dev_cases() -> None:
    split = json.loads(SPLIT_ARTIFACT.read_text(encoding="utf-8"))
    v31 = json.loads(V31_DEV_SELECTION.read_text(encoding="utf-8"))
    v32 = json.loads(V32_DEV_SELECTION.read_text(encoding="utf-8"))

    selected_ids = {case["id"] for case in v32["cases"]}
    v31_api_ids = set(v31["buckets"]["v30_regression"])

    assert v32["status"] in {"authorized_not_run", "completed_once"}
    assert v32["case_count"] == len(selected_ids) == 3
    assert selected_ids <= set(split["dev"]["case_ids"])
    assert not selected_ids & set(split["sealed_holdout"]["case_ids"])
    assert not selected_ids & v31_api_ids
    assert v32["blind8_included"] is False
    assert v32["api_policy"]["authorized"] is True
    assert all(case["coverage"] for case in v32["cases"])


def test_v33_dev5_selection_records_one_authorized_non_blind_run() -> None:
    split = json.loads(SPLIT_ARTIFACT.read_text(encoding="utf-8"))
    v31 = json.loads(V31_DEV_SELECTION.read_text(encoding="utf-8"))
    v32 = json.loads(V32_DEV_SELECTION.read_text(encoding="utf-8"))
    v33 = json.loads(V33_DEV_SELECTION.read_text(encoding="utf-8"))

    selected_ids = {case["id"] for case in v33["cases"]}
    v31_ids = {case["id"] for case in v31["cases"]}
    v32_ids = {case["id"] for case in v32["cases"]}

    assert v33["status"] == "completed_once"
    assert v33["case_count"] == len(selected_ids) == 5
    assert selected_ids <= set(split["dev"]["case_ids"])
    assert not selected_ids & set(split["sealed_holdout"]["case_ids"])
    assert not selected_ids & v31_ids
    assert not selected_ids & v32_ids
    assert v33["blind_data_policy"] == {
        "blind8_included": False,
        "sealed_holdout_included": False,
        "prediction_reuse": False,
    }
    assert v33["proposed_api_policy"]["authorized"] is True
    assert v33["proposed_api_policy"]["run_count"] == 1
    assert v33["execution_result"] == {
        "completed_at": "2026-09-02T15:00:47.034387+00:00",
        "run_count": 1,
        "rerun_performed": False,
        "generation_duration_ms": 1179437.7,
        "successful_case_count": 1,
        "successful_case_ids": ["campus-ai-142"],
        "failure_count": 4,
        "failure_counts": {
            "model_timeout": 2,
            "structured_output_invalid": 2,
        },
    }
    artifact_keys = (
        ("manifest_path", "manifest_sha256"),
        ("review_path", "review_sha256"),
        ("predictions_path", "predictions_sha256"),
        ("checkpoint_path", "checkpoint_sha256"),
        ("full_report_path", "full_report_sha256"),
        ("successful_only_report_path", "successful_only_report_sha256"),
    )
    for path_key, hash_key in artifact_keys:
        path = Path(v33["local_artifacts"][path_key])
        assert hashlib.sha256(path.read_bytes()).hexdigest() == v33[
            "local_artifacts"
        ][hash_key]
    assert v33["local_artifacts"]["review_required_count"] == 0
    assert all(case["coverage"] for case in v33["cases"])


def test_dev21_labels_are_frozen_against_the_fixed_split() -> None:
    split = json.loads(SPLIT_ARTIFACT.read_text(encoding="utf-8"))
    labels = json.loads(DEV_LABELS.read_text(encoding="utf-8"))
    manifest = EvaluationManifest.model_validate_json(
        DEV_STRICT_MANIFEST.read_text(encoding="utf-8")
    )
    review = json.loads(DEV_STRICT_REVIEW.read_text(encoding="utf-8"))

    dev_ids = set(split["dev"]["case_ids"])
    assert labels["label_status"] == "human_reviewed_remaining51_dev21_v1_frozen"
    assert labels["annotation_guide_version"] == "ai-campus-annotation-guide-v1"
    assert set(labels["case_ids"]) == dev_ids
    assert set(labels["cases"]) == dev_ids
    assert {case.id for case in manifest.cases} == dev_ids
    assert manifest.split == "dev"
    assert review["included_case_count"] == 21
    assert review["review_required_count"] == 0
    assert review["excluded_field_counts"] == {"job_type": 1, "locations": 1}

    cases_by_id = {case.id: case for case in manifest.cases}
    assert "job_type" not in cases_by_id["campus-ai-008"].expected.fields
    assert "locations" not in cases_by_id["campus-ai-037"].expected.fields


def test_dev21_skill_labels_are_traceable_and_strength_sets_do_not_overlap() -> None:
    manifest = EvaluationManifest.model_validate_json(
        DEV_STRICT_MANIFEST.read_text(encoding="utf-8")
    )

    for case in manifest.cases:
        fields = case.expected.fields
        required = set(fields["required_skills"])
        preferred = set(fields["preferred_skills"])
        groups = fields["required_skill_groups"]
        group_options = {
            option for group in groups for option in group["any_of"]
        }
        mentions = set(case.expected.skill_mentions)

        assert all(len(group["any_of"]) >= 2 for group in groups)
        assert not required & preferred
        assert not required & group_options
        assert not preferred & group_options
        assert required | preferred | group_options <= mentions


def test_dev21_freeze_hashes_match_the_frozen_files() -> None:
    freeze = json.loads(DEV_FREEZE.read_text(encoding="utf-8"))

    assert freeze["case_count"] == 21
    assert freeze["prediction_status"] == "not_generated"
    assert freeze["sealed_holdout_prediction_status"] == "not_generated_or_viewed"
    for frozen_file in freeze["files"].values():
        path = Path(frozen_file["path"])
        assert hashlib.sha256(path.read_bytes()).hexdigest() == frozen_file["sha256"]


def test_holdout30_labels_are_frozen_against_the_fixed_split() -> None:
    split = json.loads(SPLIT_ARTIFACT.read_text(encoding="utf-8"))
    labels = json.loads(HOLDOUT_LABELS.read_text(encoding="utf-8"))
    manifest = EvaluationManifest.model_validate_json(
        HOLDOUT_STRICT_MANIFEST.read_text(encoding="utf-8")
    )
    review = json.loads(HOLDOUT_STRICT_REVIEW.read_text(encoding="utf-8"))

    holdout_ids = set(split["sealed_holdout"]["case_ids"])
    assert labels["label_status"] == "human_reviewed_remaining51_holdout30_v1_frozen"
    assert labels["annotation_guide_version"] == "ai-campus-annotation-guide-v1"
    assert set(labels["case_ids"]) == holdout_ids
    assert set(labels["cases"]) == holdout_ids
    assert {case.id for case in manifest.cases} == holdout_ids
    assert manifest.split == "eval"
    assert review["included_case_count"] == 30
    assert review["review_required_count"] == 0
    assert review["excluded_field_counts"] == {"job_type": 2, "locations": 3}
    assert review["field_labeled_case_count"] == {
        "job_type": 28,
        "locations": 27,
        "required_skills": 30,
        "required_skill_groups": 30,
        "preferred_skills": 30,
    }

    cases_by_id = {case.id: case for case in manifest.cases}
    for case_id in ("campus-ai-005", "campus-ai-007"):
        assert "job_type" not in cases_by_id[case_id].expected.fields
    for case_id in ("campus-ai-022", "campus-ai-028", "campus-ai-039"):
        assert "locations" not in cases_by_id[case_id].expected.fields
    assert cases_by_id["campus-ai-060"].expected.fields["job_type"] == "campus"


def test_holdout30_skill_labels_are_normalized_traceable_and_disjoint() -> None:
    manifest = EvaluationManifest.model_validate_json(
        HOLDOUT_STRICT_MANIFEST.read_text(encoding="utf-8")
    )

    for case in manifest.cases:
        fields = case.expected.fields
        required = set(normalize_atomic_skill_values(fields["required_skills"]))
        preferred = set(normalize_atomic_skill_values(fields["preferred_skills"]))
        groups = [
            normalize_skill_group(group, options_are_atomic=True)
            for group in fields["required_skill_groups"]
        ]
        assert all(group is not None for group in groups)
        normalized_groups = [group for group in groups if group is not None]
        group_options = {
            option for group in normalized_groups for option in group["any_of"]
        }
        mentions = set(
            normalize_atomic_skill_values(case.expected.skill_mentions)
        )

        assert all(len(group["any_of"]) >= 2 for group in normalized_groups)
        assert not required & preferred
        assert not required & group_options
        assert not preferred & group_options
        assert required | preferred | group_options <= mentions


def test_holdout30_freeze_hashes_match_before_prediction() -> None:
    freeze = json.loads(HOLDOUT_FREEZE.read_text(encoding="utf-8"))

    assert freeze["case_count"] == 30
    assert freeze["prediction_status"] == "not_generated"
    assert freeze["parser_version"] == "jd-core-parser-v28"
    assert freeze["prompt_version"] == "jd-core-parser-prompt-v18"
    assert freeze["schema_version"] == "core-job-fields-v6"
    assert freeze["skill_ontology_version"] == "skill-ontology-v3"
    for frozen_file in freeze["files"].values():
        path = Path(frozen_file["path"])
        assert hashlib.sha256(path.read_bytes()).hexdigest() == frozen_file["sha256"]
