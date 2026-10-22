from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-corpus-external-raw-v1-2026-09-04.json"
)
REPORT_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-corpus-external-report-v1-2026-09-04.json"
)
RECEIPT_PATH = (
    PROJECT_ROOT
    / "datasets/unified_jd_structured_span_v4_corpus_external_evaluation_receipt_v1_2026-09-04.json"
)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _assert_spans_anchored(value: Any, source: str) -> None:
    if isinstance(value, dict):
        if {"text", "start", "end"} <= value.keys():
            assert source[value["start"] : value["end"]] == value["text"]
        for child in value.values():
            _assert_spans_anchored(child, source)
    elif isinstance(value, list):
        for child in value:
            _assert_spans_anchored(child, source)


def test_single_use_raw_predictions_are_complete_and_anchored() -> None:
    raw = _load(RAW_PATH)

    assert raw["v4_parser_run_count"] == 1
    assert raw["model_call_count"] == 0
    assert len(raw["records"]) == 20
    assert all(record["error"] is None for record in raw["records"])
    for record in raw["records"]:
        _assert_spans_anchored(record["parsed_clause"], record["source_text"])


def test_frozen_gate_failure_is_pinned() -> None:
    report = _load(REPORT_PATH)

    assert report["connector_classification"]["overall"]["accuracy"] == 0.7631578947368421
    assert report["coordination_members"]["overall"]["f1"] == 0.5172413793103449
    assert report["shared_scope_edges"]["overall"]["f1"] == 0.12765957446808512
    assert report["example_attachment_edges"]["overall"]["f1"] == 0.0
    assert report["surface_projection"]["overall"]["f1"] == 0.43283582089552236
    assert report["surface_projection"]["overall"]["exact_fixture_rate"] == 0.05
    assert report["unanchored_outputs"]["count"] == 0
    assert report["structure_validation_errors"] == 0
    assert report["gate"]["passed"] is False
    assert report["canonicalizer_decision"]["allowed"] is False


def test_evaluation_outputs_match_the_receipt() -> None:
    receipt = _load(RECEIPT_PATH)

    assert receipt["parser"]["run_count_on_holdout"] == 1
    assert receipt["gate_passed"] is False
    assert receipt["canonicalizer_allowed"] is False
    for output in receipt["outputs"].values():
        assert _sha256(PROJECT_ROOT / output["path"]) == output["sha256"]
