from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.domain.unified_jd_surface_items_v2 import extract_surface_items

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEVELOPMENT_FIXTURES = (
    PROJECT_ROOT / "datasets" / "unified_jd_canonical_items_contract_v1.json",
    PROJECT_ROOT / "datasets" / "unified_jd_surface_holdout_labels_v1_2026-09-04.json",
)


def _development_items() -> list[dict[str, Any]]:
    return [
        item
        for path in DEVELOPMENT_FIXTURES
        for item in json.loads(path.read_text(encoding="utf-8"))["fixtures"]
    ]


@pytest.mark.parametrize("item", _development_items(), ids=lambda item: item["id"])
def test_v2_surface_grammar_fits_forty_development_fixtures(
    item: dict[str, Any],
) -> None:
    extraction = extract_surface_items(item["source_text"], item["category"])

    assert list(extraction.items) == item["surface_items"]
    assert list(extraction.examples) == (item["examples"] or [])
    assert extraction.rule_ids
    assert all(value in item["source_text"] for value in extraction.items)
    assert all(value in item["source_text"] for value in extraction.examples)


def test_v2_surface_grammar_rejects_empty_source() -> None:
    with pytest.raises(ValueError, match="source_text"):
        extract_surface_items(" ", "skill")
