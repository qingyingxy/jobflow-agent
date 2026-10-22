from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PARSER_PATH = PROJECT_ROOT / "src/domain/unified_jd_structured_spans_v4.py"
RULES_FREEZE_PATH = (
    PROJECT_ROOT
    / "datasets/unified_jd_structured_span_rules_freeze_v4_2026-09-04.json"
)
BASELINE_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-corpus-external-raw-v1-2026-09-04.json"
)
RAW_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-e5-example-attachment-three-toggle-raw-v1-2026-09-04.json"
)
REPORT_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-e5-example-attachment-three-toggle-report-v1-2026-09-04.json"
)
FINDINGS_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-e5-example-attachment-three-toggle-findings-v1-2026-09-04.md"
)

PARSER_SHA256 = "e09e056cab75e651937391ce5410e6df7c94477c85565abb1425bbe85cfcb094"
RULES_FREEZE_SHA256 = (
    "6a8a1d9ccce7c1069a483c7cc387221164de52800a133308922d57ff75ad6a12"
)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _span_key(span: dict[str, Any]) -> tuple[int, int, str]:
    return (span["start"], span["end"], span["text"])


def _attachment_keys(arm: dict[str, Any]) -> Counter[tuple[Any, ...]]:
    return Counter(
        (
            _span_key(item["cue_span"]),
            _span_key(item["parent_span"]),
            tuple(_span_key(span) for span in item["example_spans"]),
        )
        for item in arm["attachments"]
    )


def _stored_attachment_keys(record: dict[str, Any]) -> Counter[tuple[Any, ...]]:
    return Counter(
        (
            _span_key(item["cue_span"]),
            _span_key(item["parent_span"]),
            tuple(_span_key(span) for span in item["example_spans"]),
        )
        for item in record["parsed_clause"]["example_attachments"]
    )


def test_e5_reuses_frozen_raw_and_only_calls_the_detection_helper() -> None:
    raw = _load(RAW_PATH)
    freeze = _load(RULES_FREEZE_PATH)

    assert raw["status"] == "revealed_development_causal_experiment"
    assert raw["experiment_id"] == "E5-example-attachment-three-toggle"
    assert raw["arms"] == [
        "baseline",
        "toggle1_cue_stripped",
        "toggle2_category_neutral",
        "toggle3_parent_ranked",
    ]
    assert raw["baseline_reused"] is True
    assert raw["v4_full_parser_executed"] is False
    assert raw["frozen_detection_helper_reused"] is True
    assert raw["fixture_count"] == 5
    assert raw["model_call_count"] == 0
    assert raw["network_call_count"] == 0
    assert raw["frozen_v4_source"] == {
        "path": "src/domain/unified_jd_structured_spans_v4.py",
        "sha256_before": PARSER_SHA256,
        "sha256_after": PARSER_SHA256,
        "modified": False,
    }
    assert _sha256(PARSER_PATH) == PARSER_SHA256
    assert _sha256(RULES_FREEZE_PATH) == RULES_FREEZE_SHA256
    assert freeze["parser"]["sha256"] == PARSER_SHA256


def test_e5_baseline_reconstruction_matches_stored_raw() -> None:
    raw = _load(RAW_PATH)
    baseline_by_id = {item["id"]: item for item in _load(BASELINE_PATH)["records"]}

    for record in raw["records"]:
        stored = baseline_by_id[record["id"]]
        arm = record["baseline"]
        assert arm["example_items"] == stored["examples"]
        assert _attachment_keys(arm) == _stored_attachment_keys(stored)
        assert Counter(map(_span_key, arm["example_members"])) == Counter(
            _span_key(span)
            for item in stored["parsed_clause"]["example_attachments"]
            for span in item["example_spans"]
        )


def test_toggle1_changes_only_the_two_registered_example_boundaries() -> None:
    raw = _load(RAW_PATH)
    report = _load(REPORT_PATH)
    records = {item["id"]: item for item in raw["records"]}

    assert report["changed_fixture_ids"]["toggle1"] == [
        "structured-corpus-external-v1-002",
        "structured-corpus-external-v1-005",
    ]
    assert report["decision"]["toggle1_fixes_002_005_example_spans"] is True
    assert records["structured-corpus-external-v1-002"][
        "toggle1_cue_stripped"
    ]["example_members"][0]["start"] == 17
    assert records["structured-corpus-external-v1-005"][
        "toggle1_cue_stripped"
    ]["example_members"][0]["start"] == 27
    for fixture_id in (
        "structured-corpus-external-v1-002",
        "structured-corpus-external-v1-005",
    ):
        before = records[fixture_id]["baseline"]["attachments"][0]
        after = records[fixture_id]["toggle1_cue_stripped"]["attachments"][0]
        assert after["cue_span"] == before["cue_span"]
        assert after["parent_span"] == before["parent_span"]


def test_toggle2_exposes_the_category_neutral_control_regression() -> None:
    raw = _load(RAW_PATH)
    report = _load(REPORT_PATH)
    records = {item["id"]: item for item in raw["records"]}

    assert set(report["changed_fixture_ids"]["toggle2"]) == {
        "structured-corpus-external-v1-006",
        "structured-corpus-external-v1-019",
    }
    assert report["decision"]["toggle2_discovers_019"] is True
    assert report["decision"]["toggle2_controls_unchanged"] is False
    assert report["decision"]["toggle2_control_changes"] == {
        "structured-corpus-external-v1-006": True,
        "structured-corpus-external-v1-018": False,
    }
    case_006 = records["structured-corpus-external-v1-006"]
    false_attachment = case_006["toggle2_category_neutral"]["attachments"][0]
    assert false_attachment["cue_span"]["text"] == "\u7b49"
    assert false_attachment["parent_span"]["text"] == "\u4f18\u5148"
    assert records["structured-corpus-external-v1-018"][
        "toggle2_category_neutral"
    ]["attachments"] == []


def test_toggle3_fixes_parents_but_leaves_the_unregistered_boundary_error() -> None:
    raw = _load(RAW_PATH)
    report = _load(REPORT_PATH)
    records = {item["id"]: item for item in raw["records"]}
    target = report["aggregate"]["targets"]

    for record in raw["records"]:
        before = record["toggle2_category_neutral"]
        after = record["toggle3_parent_ranked"]
        assert after["example_members"] == before["example_members"]
        assert after["example_items"] == before["example_items"]
        assert [item["cue_span"] for item in after["attachments"]] == [
            item["cue_span"] for item in before["attachments"]
        ]

    assert report["decision"]["toggle3_all_target_parents_exact"] is True
    assert report["decision"]["toggle3_all_target_edges_exact"] is False
    assert target["toggle3_parent_ranked"]["attachment_parents"]["f1"] == 1.0
    assert target["toggle3_parent_ranked"]["attachment_edges"]["f1"] == pytest.approx(
        10 / 11
    )
    assert target["toggle3_parent_ranked"]["example_projection"]["f1"] == pytest.approx(
        10 / 11
    )
    case_019 = records["structured-corpus-external-v1-019"]
    final_attachment = case_019["toggle3_parent_ranked"]["attachments"][0]
    assert final_attachment["parent_span"]["text"] == "\u9886\u57df"
    assert final_attachment["example_spans"][0]["text"].startswith("\u5bf9")


def test_e5_is_rejected_without_post_hoc_exceptions() -> None:
    report = _load(REPORT_PATH)
    findings = FINDINGS_PATH.read_text(encoding="utf-8")

    assert report["decision"]["accepted"] is False
    assert "Decision: **rejected**" in findings
    assert "No post-hoc priority-tail exception" in findings
    assert "also creates a false attachment for control 006" in findings
    assert "first example still contains the leading preposition" in findings
    assert "Add no E5 mechanism to v5" in findings
