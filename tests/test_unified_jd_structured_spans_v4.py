from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest

from scripts.evaluate_unified_structured_span_v4_development import (
    evaluate_predictions,
    run_predictions,
)
from src.domain.unified_jd_structured_spans_v4 import (
    ParsedClause,
    extract_surface_items,
    parse_clause,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
GOLD_PATH = (
    PROJECT_ROOT
    / "datasets"
    / "unified_jd_structured_span_v4_development_gold_v1_2026-09-04.json"
)
V3_PATH = PROJECT_ROOT / "src" / "domain" / "unified_jd_structured_spans.py"
V3_FREEZE_PATH = (
    PROJECT_ROOT
    / "datasets"
    / "unified_jd_structured_span_rules_freeze_v3_2026-09-04.json"
)
V4_FREEZE_PATH = (
    PROJECT_ROOT
    / "datasets"
    / "unified_jd_structured_span_rules_freeze_v4_2026-09-04.json"
)
DEVELOPMENT_FIXTURES = (
    PROJECT_ROOT / "datasets" / "unified_jd_canonical_items_contract_v1.json",
    PROJECT_ROOT / "datasets" / "unified_jd_surface_holdout_labels_v1_2026-09-04.json",
    PROJECT_ROOT / "datasets" / "unified_jd_surface_holdout_labels_v2_2026-09-04.json",
)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _all_spans(value: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if {"text", "start", "end"} <= set(value):
            result.append(value)
        for child in value.values():
            result.extend(_all_spans(child))
    elif isinstance(value, list):
        for child in value:
            result.extend(_all_spans(child))
    return result


def _old_development_fixtures() -> list[dict[str, Any]]:
    return [
        fixture for path in DEVELOPMENT_FIXTURES for fixture in _load(path)["fixtures"]
    ]


def test_v3_parser_still_matches_its_freeze_hash() -> None:
    freeze = _load(V3_FREEZE_PATH)

    assert _sha256(V3_PATH) == freeze["parser"]["sha256"]
    assert freeze["parser"]["sha256"] == (
        "0ba56a1eafee24f9643cc5015c495e88201cf7652e2a278e305ff821319d863a"
    )


def test_v4_parser_and_evidence_match_their_freeze_hashes() -> None:
    freeze = _load(V4_FREEZE_PATH)

    assert freeze["status"] == "rules_frozen_pending_corpus_external_holdout"
    assert freeze["canonicalizer_decision"]["allowed"] is False
    for value in (
        freeze["parser"],
        freeze["development_evidence"]["gold"],
        freeze["development_evidence"]["v3_control_raw"],
        freeze["development_evidence"]["v3_control_report"],
        freeze["development_evidence"]["v4_treatment_raw"],
        freeze["development_evidence"]["v4_treatment_report"],
        freeze["development_evidence"]["causal_experiments"],
    ):
        assert _sha256(PROJECT_ROOT / value["path"]) == value["sha256"]
    causal = freeze["development_evidence"]["causal_experiments"]
    assert _sha256(PROJECT_ROOT / causal["findings_path"]) == causal["findings_sha256"]


def test_v4_development_gold_is_complete_and_source_anchored() -> None:
    gold = _load(GOLD_PATH)

    assert gold["status"] == "revealed_same_corpus_development_only"
    assert gold["generalization_claim"] is False
    assert gold["fixture_count"] == 20
    assert gold["revealed_failure_count"] == 17
    assert gold["control_count"] == 3
    for fixture in gold["fixtures"]:
        for span in _all_spans(fixture):
            assert fixture["source_text"][span["start"] : span["end"]] == span["text"]


@pytest.mark.parametrize(
    "fixture", _old_development_fixtures(), ids=lambda fixture: fixture["id"]
)
def test_v4_preserves_all_sixty_previous_development_projections(
    fixture: dict[str, Any],
) -> None:
    extraction = extract_surface_items(fixture["source_text"], fixture["category"])

    assert list(extraction.items) == fixture["surface_items"]
    assert list(extraction.examples) == (fixture["examples"] or [])


@pytest.mark.parametrize(
    "fixture", _load(GOLD_PATH)["fixtures"], ids=lambda fixture: fixture["id"]
)
def test_v4_matches_revealed_structural_development_projection(
    fixture: dict[str, Any],
) -> None:
    extraction = extract_surface_items(fixture["source_text"], fixture["category"])
    serialized = asdict(extraction.parsed_clause)

    assert list(extraction.items) == fixture["projection"]["surface_items"]
    assert list(extraction.examples) == fixture["projection"]["examples"]
    for span in _all_spans(serialized):
        assert fixture["source_text"][span["start"] : span["end"]] == span["text"]
    ParsedClause(
        **{
            name: getattr(extraction.parsed_clause, name)
            for name in extraction.parsed_clause.__dataclass_fields__
        }
    )


def test_v4_separates_embedded_coordination_from_projection() -> None:
    extraction = extract_surface_items(
        "工程能力强，能快速验证想法并落地到产品或平台中", "capability"
    )
    embedded = next(
        group
        for group in extraction.parsed_clause.coordinations
        if group.role == "embedded"
    )

    assert [item.span.text for item in embedded.members] == ["产品", "平台"]
    assert "落地到产品或平台中" in extraction.items
    assert "产品" not in extraction.items
    assert "平台" not in extraction.items


def test_v4_serializes_protected_quantifier_connectors() -> None:
    parsed = parse_clause(
        "精通Go、Python、C++等一种或多种编程语言，具备扎实的编程技能和算法设计能力",
        "skill",
    )

    assert [(item.span.text, item.role) for item in parsed.connector_labels].count(
        ("或", "quantifier")
    ) == 1


def test_v4_layer_metrics_are_independently_perfect_on_revealed_development() -> None:
    gold = _load(GOLD_PATH)
    report = evaluate_predictions(gold, run_predictions(gold, "v4"))

    assert report["structure_validation_errors"] == 0
    assert report["connector_classification"]["accuracy"] == 1.0
    assert report["coordination_members"]["f1"] == 1.0
    assert report["shared_scope_edges"]["f1"] == 1.0
    assert report["example_attachment_edges"]["f1"] == 1.0
    assert report["projection"]["surface_items"]["f1"] == 1.0
    assert report["projection"]["examples"]["f1"] == 1.0
