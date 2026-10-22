from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = (
    PROJECT_ROOT
    / "datasets/unified_jd_structured_span_v4_corpus_external_revealed_development_v1_2026-09-04.json"
)
RECEIPT_PATH = (
    PROJECT_ROOT
    / "datasets/unified_jd_structured_span_v4_corpus_external_reveal_receipt_v1_2026-09-04.json"
)

FROZEN_HASHES = {
    "src/domain/unified_jd_structured_spans_v4.py": (
        "e09e056cab75e651937391ce5410e6df7c94477c85565abb1425bbe85cfcb094"
    ),
    "datasets/unified_jd_structured_span_rules_freeze_v4_2026-09-04.json": (
        "6a8a1d9ccce7c1069a483c7cc387221164de52800a133308922d57ff75ad6a12"
    ),
    "datasets/unified_jd_structured_span_v4_corpus_external_sources_v1_2026-09-04.json": (
        "1e693bd69642511ffa005b2bc33489b68a4a1ef99abb3c65b8615862c0eb5b29"
    ),
    "datasets/unified_jd_structured_span_v4_corpus_external_selection_v1_2026-09-04.json": (
        "3061f49377ef937325743c1e1afc14e9651215f36dfad6b8c02771bd99b5661a"
    ),
    "datasets/unified_jd_structured_span_v4_corpus_external_labels_v1_2026-09-04.json": (
        "64823eb502b5219254a0376808a234e056b2964fe85cd00c30d898b821a79b54"
    ),
    "datasets/unified_jd_structured_span_v4_corpus_external_label_freeze_v1_2026-09-04.json": (
        "c2e08912e26dcfa693959b25a4d4bcf6e357a55995c056cd245ca6fb9ebe599d"
    ),
    "artifacts/evaluation/unified-jd-structured-span-v4-corpus-external-raw-v1-2026-09-04.json": (
        "36b65c1df79d856c7507ae1357ed24c10b7a3e383bad79b9471b124f4999e058"
    ),
    "artifacts/evaluation/unified-jd-structured-span-v4-corpus-external-report-v1-2026-09-04.json": (
        "5a0d53f1d55f7d62c52506c907b2231826f1f2753f653bb97880e1e7ac373dfc"
    ),
}

DIFFERENCE_LAYERS = {
    "wrappers",
    "coordination_members",
    "shared_scope_edges",
    "example_attachment_parents",
    "example_attachment_edges",
    "surface_projection",
    "example_projection",
}


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_v4_and_single_use_evaluation_remain_byte_frozen() -> None:
    for relative_path, expected_hash in FROZEN_HASHES.items():
        assert _sha256(PROJECT_ROOT / relative_path) == expected_hash


def test_revealed_dataset_contains_complete_joined_development_records() -> None:
    dataset = _load(DATASET_PATH)
    source_corpus = _load(
        PROJECT_ROOT
        / "datasets/unified_jd_structured_span_v4_corpus_external_sources_v1_2026-09-04.json"
    )
    source_by_job_id = {job["job_id"]: job for job in source_corpus["jobs"]}

    assert dataset["status"] == "revealed_corpus_external_development_only"
    assert dataset["former_holdout_status"] == "consumed_single_use_failed_gate"
    assert dataset["fixture_count"] == 20
    assert dataset["unique_job_count"] == 20
    assert Counter(item["category"] for item in dataset["fixtures"]) == {
        "responsibility": 5,
        "skill": 5,
        "experience": 5,
        "capability": 5,
    }

    for fixture in dataset["fixtures"]:
        assert fixture["job_provenance"] == source_by_job_id[fixture["job_id"]]
        assert fixture["job_provenance"]["raw_content"]
        assert fixture["selected_clause"]["source_text"] == fixture["gold"][
            "source_text"
        ]
        assert fixture["v4_prediction"]["source_text"] == fixture["gold"][
            "source_text"
        ]
        assert set(fixture["evaluation_differences"]) == DIFFERENCE_LAYERS
        for difference in fixture["evaluation_differences"].values():
            assert difference["exact"] is (
                not difference["missing"] and not difference["unexpected"]
            )


def test_reveal_receipt_permanently_excludes_holdout_reuse() -> None:
    dataset = _load(DATASET_PATH)
    receipt = _load(RECEIPT_PATH)

    assert receipt["status"] == "revealed_corpus_external_development_only"
    assert receipt["former_holdout_status"] == "consumed_single_use_failed_gate"
    assert receipt["revealed_development"]["sha256"] == _sha256(DATASET_PATH)
    assert receipt["revealed_development"]["fixture_count"] == len(
        dataset["fixtures"]
    )
    assert receipt["frozen_v4_assurance"] == {
        "parser_modified": False,
        "rules_freeze_modified": False,
        "parser_imported_or_executed_during_reveal": False,
        "additional_v4_runs_on_former_holdout": 0,
        "total_v4_runs_on_former_holdout": 1,
    }
    assert receipt["usage_policy"]["eligible_for"] == [
        "v5_diagnosis",
        "v5_development",
    ]
    assert set(receipt["usage_policy"]["ineligible_for"]) >= {
        "v4_retest",
        "v5_holdout",
        "future_holdout",
        "generalization_claim",
        "threshold_selection",
    }
    assert receipt["usage_policy"]["generalization_claim"] is False
    assert receipt["usage_policy"]["holdout_reuse_prohibited"] is True
