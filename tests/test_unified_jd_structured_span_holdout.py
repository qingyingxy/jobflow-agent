from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FREEZE_PATH = (
    PROJECT_ROOT
    / "datasets"
    / "unified_jd_structured_span_external_holdout_label_freeze_v1_2026-09-04.json"
)
RAW_PATH = (
    PROJECT_ROOT
    / "artifacts"
    / "evaluation"
    / "unified-jd-structured-span-external-holdout-raw-v1-2026-09-04.json"
)
REPORT_PATH = (
    PROJECT_ROOT
    / "artifacts"
    / "evaluation"
    / "unified-jd-structured-span-external-holdout-report-v1-2026-09-04.json"
)
RECEIPT_PATH = (
    PROJECT_ROOT
    / "datasets"
    / "unified_jd_structured_span_external_holdout_evaluation_receipt_v1_2026-09-04.json"
)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _assert_serialized_spans_are_anchored(value: Any, source_text: str) -> None:
    if isinstance(value, dict):
        if {"text", "start", "end"} <= value.keys():
            assert source_text[value["start"] : value["end"]] == value["text"]
        for child in value.values():
            _assert_serialized_spans_are_anchored(child, source_text)
    elif isinstance(value, list):
        for child in value:
            _assert_serialized_spans_are_anchored(child, source_text)


def test_external_holdout_inputs_match_their_freeze_receipt() -> None:
    freeze = _load(FREEZE_PATH)

    for key in ("selection", "labels"):
        path = PROJECT_ROOT / freeze[key]["path"]
        assert _sha256(path) == freeze[key]["sha256"]
    parser_path = PROJECT_ROOT / freeze["parser"]["path"]
    assert _sha256(parser_path) == freeze["parser"]["sha256"]


def test_external_holdout_is_balanced_and_source_anchored() -> None:
    freeze = _load(FREEZE_PATH)
    selection = _load(PROJECT_ROOT / freeze["selection"]["path"])
    labels = _load(PROJECT_ROOT / freeze["labels"]["path"])

    assert len(selection["fixtures"]) == 20
    assert len({item["case_id"] for item in selection["fixtures"]}) == 20
    assert Counter(item["category"] for item in labels["fixtures"]) == Counter(
        {"responsibility": 5, "skill": 5, "experience": 5, "capability": 5}
    )
    for item in labels["fixtures"]:
        assert all(value in item["source_text"] for value in item["surface_items"])
        assert all(value in item["source_text"] for value in (item["examples"] or []))


def test_raw_external_holdout_preserves_exact_structured_spans() -> None:
    raw = _load(RAW_PATH)

    assert len(raw["records"]) == 20
    assert all(record["error"] is None for record in raw["records"])
    for record in raw["records"]:
        _assert_serialized_spans_are_anchored(
            record["parsed_clause"], record["source_text"]
        )


def test_failed_external_gate_blocks_canonicalizer() -> None:
    report = _load(REPORT_PATH)

    assert report["surface_items"]["overall"]["f1"] == 0.35772357723577236
    assert report["surface_items"]["overall"]["exact_set_rate"] == 0.15
    assert report["examples"]["overall"]["f1"] == 0.0
    assert report["unanchored_outputs"]["count"] == 0
    assert report["structure_validation_errors"] == 0
    assert report["gate"]["passed"] is False
    assert report["canonicalizer_decision"]["allowed"] is False


def test_external_holdout_outputs_match_evaluation_receipt() -> None:
    receipt = _load(RECEIPT_PATH)

    for output in receipt["outputs"].values():
        assert _sha256(PROJECT_ROOT / output["path"]) == output["sha256"]
    assert receipt["gate_passed"] is False
    assert receipt["canonicalizer_allowed"] is False
