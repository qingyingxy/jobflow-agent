from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from src.evaluation.ai_campus_split import build_split_payload
from src.evaluation.models import EvaluationManifest

SOURCE_DATA = Path("artifacts/evaluation/m11-ai-campus-source-full-2026-08-31.json")
SOURCE_MANIFEST = Path(
    "artifacts/evaluation/m11-ai-campus-manifest-full-v4-strict-2026-08-31.json"
)
SPLIT_ARTIFACT = Path("datasets/ai_campus_remaining_51_split_v1_2026_09_02.json")
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
