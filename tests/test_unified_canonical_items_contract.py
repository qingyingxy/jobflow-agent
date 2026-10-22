from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from src.evaluation.unified_models import UnifiedEvaluationManifest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = PROJECT_ROOT / "datasets" / "unified_jd_canonical_items_contract_v1.json"
EXPECTED_CONTRACT_VERSION = "canonical-items-contract-v1"
EXPECTED_CATEGORIES = {
    "responsibility",
    "skill",
    "experience",
    "capability",
}


def _load_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _load_manifest(fixture: dict[str, Any]) -> UnifiedEvaluationManifest:
    manifest_path = PROJECT_ROOT / fixture["source_manifest"]["path"]
    return UnifiedEvaluationManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )


def _fixtures_by_id(fixture: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in fixture["fixtures"]}


def test_canonical_contract_fixture_has_frozen_provenance() -> None:
    fixture = _load_fixture()
    manifest_path = PROJECT_ROOT / fixture["source_manifest"]["path"]

    assert fixture["contract_version"] == EXPECTED_CONTRACT_VERSION
    assert fixture["schema_version"] == "unified-jd-v1"
    assert (
        hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        == (fixture["source_manifest"]["sha256"])
    )


def test_canonical_contract_fixture_has_balanced_reviewed_scope() -> None:
    fixture = _load_fixture()
    items = fixture["fixtures"]
    scope = fixture["scope"]

    assert len(items) == scope["fixture_count"] == 20
    assert len({item["id"] for item in items}) == len(items)
    assert Counter(item["category"] for item in items) == Counter(
        {category: scope["fixtures_per_category"] for category in EXPECTED_CATEGORIES}
    )
    assert set(scope["categories"]) == EXPECTED_CATEGORIES
    assert {item["case_id"] for item in items} == set(scope["case_ids"])


def test_canonical_contract_matches_frozen_clauses() -> None:
    fixture = _load_fixture()
    manifest = _load_manifest(fixture)
    cases_by_id = {case.id: case for case in manifest.cases}

    for item in fixture["fixtures"]:
        case = cases_by_id[item["case_id"]]
        assert case.expected is not None
        clause = case.expected.clauses[item["clause_index"]]

        assert item["source_text"] in case.raw_content
        assert item["category"] == clause.category
        assert item["level"] == clause.level
        assert item["source_text"] == clause.source_text
        assert item["canonical_items"] == clause.items
        assert item["examples"] == clause.examples
        assert item["relation"] == clause.relation
        assert item["group_name"] == clause.group_name
        assert item["allow_other"] == clause.allow_other


def test_canonical_contract_surface_mappings_are_complete_and_anchored() -> None:
    fixture = _load_fixture()

    for item in fixture["fixtures"]:
        source_text = item["source_text"]
        surface_items = item["surface_items"]
        canonical_items = item["canonical_items"]
        mappings = item["surface_to_canonical"]

        assert surface_items
        assert canonical_items
        assert len(surface_items) == len(set(surface_items))
        assert len(canonical_items) == len(
            {value.strip().casefold() for value in canonical_items}
        )
        assert len(mappings) == len(surface_items)
        assert Counter(mapping["surface_item"] for mapping in mappings) == Counter(
            surface_items
        )
        assert {mapping["canonical_item"] for mapping in mappings} == set(
            canonical_items
        )

        for mapping in mappings:
            assert mapping["surface_item"] in source_text
            assert mapping["support_text"] in source_text
            assert mapping["surface_item"] in mapping["support_text"]
        for example in item["examples"] or []:
            assert example in source_text
            assert example not in canonical_items


def test_canonical_contract_relation_applies_only_to_canonical_items() -> None:
    fixture = _load_fixture()

    for item in fixture["fixtures"]:
        if item["relation"] == "any_of":
            assert len(item["canonical_items"]) >= 2
            assert item["group_name"]
        else:
            assert item["relation"] == "all_of"
            assert item["group_name"] is None
            assert item["allow_other"] is False


def test_canonical_contract_encodes_examples_and_choices_differently() -> None:
    fixture = _load_fixture()
    items = _fixtures_by_id(fixture)

    language_choices = items["canonical-v1-skill-001"]
    language_examples = items["canonical-v1-skill-004"]
    tool_experience = items["canonical-v1-experience-004"]

    assert language_choices["relation"] == "any_of"
    assert language_choices["canonical_items"] == ["Java", "Python", "C++"]
    assert language_choices["examples"] is None

    assert language_examples["relation"] == "all_of"
    assert language_examples["canonical_items"] == ["编程语言"]
    assert language_examples["examples"] == ["Python", "R", "Matlab"]

    assert tool_experience["relation"] == "all_of"
    assert tool_experience["canonical_items"] == ["AI工具使用经验"]
    assert len(tool_experience["examples"]) == 6


def test_multi_item_responsibilities_do_not_copy_the_full_source_as_one_item() -> None:
    fixture = _load_fixture()
    responsibilities = [
        item for item in fixture["fixtures"] if item["category"] == "responsibility"
    ]

    assert len(responsibilities) == 5
    for item in responsibilities:
        assert len(item["canonical_items"]) >= 2
        assert item["surface_items"] != [item["source_text"]]
        assert item["source_text"] not in item["canonical_items"]
