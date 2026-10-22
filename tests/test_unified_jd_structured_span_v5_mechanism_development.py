from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES_PATH = (
    ROOT
    / "datasets"
    / "unified_jd_structured_span_v5_mechanism_development_sources_v1_2026-09-04.json"
)
SELECTION_PATH = (
    ROOT
    / "datasets"
    / "unified_jd_structured_span_v5_mechanism_development_selection_v1_2026-09-04.json"
)
RECEIPT_PATH = (
    ROOT
    / "datasets"
    / "unified_jd_structured_span_v5_mechanism_development_receipt_v1_2026-09-04.json"
)
FINDINGS_PATH = (
    ROOT
    / "artifacts"
    / "evaluation"
    / "unified-jd-structured-span-v5-mechanism-development-findings-v1-2026-09-04.md"
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_v5_mechanism_pool_is_revealed_development_not_holdout() -> None:
    sources = _load(SOURCES_PATH)
    selection = _load(SELECTION_PATH)
    receipt = _load(RECEIPT_PATH)

    assert sources["status"] == "revealed_mechanism_development_data"
    assert sources["holdout"] is False
    assert selection["usage_policy"] == {
        "eligible_for_v5_design": True,
        "eligible_for_v5_development_evaluation_after_full_gold": True,
        "eligible_for_generalization_claim": False,
        "eligible_as_v5_holdout": False,
        "full_structural_gold_complete": False,
        "next_step": (
            "Complete independent full span annotation for these clauses, then "
            "preregister and implement v5 against revealed development data only."
        ),
    }
    assert receipt["decision_boundary"]["v4_modified"] is False
    assert receipt["decision_boundary"]["v5_implemented"] is False
    assert receipt["decision_boundary"]["canonicalizer_allowed"] is False
    assert receipt["decision_boundary"]["this_is_holdout"] is False


def test_v5_mechanism_pool_has_twenty_complete_unique_social_jobs() -> None:
    sources = _load(SOURCES_PATH)
    jobs = sources["jobs"]

    assert len(jobs) == 20
    assert len({job["job_id"] for job in jobs}) == 20
    assert len({job["original_url"] for job in jobs}) == 20
    assert {job["company"] for job in jobs} == {"美团"}
    assert {job["source_job_type"] for job in jobs} == {"3"}
    assert {job["source_job_code"] for job in jobs} == {"1"}
    assert {job["recruitment_type"] for job in jobs} == {"社会招聘-正式"}

    for job in jobs:
        assert job["title"]
        assert job["job_duty"]
        assert job["job_requirement"]
        assert job["raw_content"].startswith(("部门介绍\n", "岗位职责\n"))
        assert "岗位职责\n" in job["raw_content"]
        assert "任职要求\n" in job["raw_content"]
        assert job["raw_content_length"] == len(job["raw_content"])
        assert job["raw_content_sha256"] == hashlib.sha256(
            job["raw_content"].encode("utf-8")
        ).hexdigest()


def test_v5_mechanism_selection_is_balanced_and_spans_resolve() -> None:
    sources = _load(SOURCES_PATH)
    selection = _load(SELECTION_PATH)
    by_id = {job["job_id"]: job for job in sources["jobs"]}
    fixtures = selection["fixtures"]

    assert len(fixtures) == 20
    assert len({fixture["job_id"] for fixture in fixtures}) == 20
    assert Counter(
        fixture["mechanism_annotation"]["mechanism_id"] for fixture in fixtures
    ) == {
        "E2-wrapper-boundary": 5,
        "E3-region-first-connector-role": 5,
        "E6-priority-tail-rejection": 5,
        "E7-prepositional-wrapper-before-example-split": 5,
    }

    for fixture in fixtures:
        job = by_id[fixture["job_id"]]
        source = (
            job["job_duty"]
            if fixture["source_field"] == "jobDuty"
            else job["job_requirement"]
        )
        clause = fixture["source_text"]
        section_span = fixture["clause_span_in_section"]
        raw_span = fixture["clause_span_in_raw_content"]
        assert source[section_span["start"] : section_span["end"]] == clause
        assert job["raw_content"][raw_span["start"] : raw_span["end"]] == clause
        assert fixture["raw_content_sha256"] == job["raw_content_sha256"]
        assert (
            fixture["mechanism_annotation"]["status"]
            == "preannotated_mechanism_triage_not_full_span_gold"
        )


def test_e6_has_two_targets_and_three_near_neighbor_controls() -> None:
    fixtures = _load(SELECTION_PATH)["fixtures"]
    e6 = [
        fixture
        for fixture in fixtures
        if fixture["mechanism_annotation"]["mechanism_id"]
        == "E6-priority-tail-rejection"
    ]
    roles = Counter(item["mechanism_annotation"]["role"] for item in e6)
    assert roles == {"target": 2, "matched_control": 3}

    for item in e6:
        behavior = item["mechanism_annotation"]["expected_behavior"]
        if item["mechanism_annotation"]["role"] == "target":
            assert behavior["priority_tail_only_after_deng"] is True
            assert behavior["attach_priority_as_parent"] is False
        else:
            assert behavior["priority_tail_only_after_deng"] is False


def test_receipt_hashes_match_frozen_artifacts() -> None:
    receipt = _load(RECEIPT_PATH)
    assert receipt["artifacts"]["sources"]["sha256"] == _sha256(SOURCES_PATH)
    assert receipt["artifacts"]["selection"]["sha256"] == _sha256(SELECTION_PATH)
    assert receipt["artifacts"]["findings"]["sha256"] == _sha256(FINDINGS_PATH)

    findings = FINDINGS_PATH.read_text(encoding="utf-8")
    assert "They are not a holdout" in findings
    assert "two natural terminal `等优先` targets" in findings
    assert "V5 and the canonicalizer were not implemented" in findings
