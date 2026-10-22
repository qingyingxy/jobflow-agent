from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts.evaluate_unified_surface_items import build_report
from src.domain.unified_jd_surface_items import extract_surface_items

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = PROJECT_ROOT / "datasets" / "unified_jd_canonical_items_contract_v1.json"


def _load_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("source_text", "category", "expected_items"),
    [
        (
            "熟悉 Python 或 Go",
            "skill",
            ("Python", "Go"),
        ),
        (
            "有搜索、推荐或广告相关项目经验",
            "experience",
            ("搜索", "推荐", "广告"),
        ),
        (
            "具备需求分析与项目推进能力",
            "capability",
            ("需求分析", "项目推进"),
        ),
        (
            "设计基于规则引擎或机器学习的解决方案",
            "responsibility",
            ("规则引擎", "机器学习"),
        ),
    ],
)
def test_surface_prototype_uses_grammar_rules_on_unseen_text(
    source_text: str,
    category: str,
    expected_items: tuple[str, ...],
) -> None:
    extraction = extract_surface_items(source_text, category)  # type: ignore[arg-type]

    assert extraction.items == expected_items
    assert extraction.rule_ids


def test_surface_prototype_outputs_only_anchored_items_and_examples() -> None:
    fixture = _load_fixture()

    for item in fixture["fixtures"]:
        extraction = extract_surface_items(item["source_text"], item["category"])
        assert all(value in item["source_text"] for value in extraction.items)
        assert all(value in item["source_text"] for value in extraction.examples)


def test_surface_prototype_replay_records_dev_fit_and_alias_ambiguity() -> None:
    fixture = _load_fixture()
    report = build_report(fixture, FIXTURE_PATH)

    assert report["model_call_count"] == 0
    assert report["evaluation_scope"]["type"] == "development_contract_fit"
    assert report["evaluation_scope"]["generalization_claim"] is False
    assert report["evaluation_scope"]["production_wiring"] is False
    assert report["surface_items"]["overall"] == {
        "tp": 66,
        "fp": 0,
        "fn": 0,
        "precision": 1.0,
        "recall": 1.0,
        "f1": 1.0,
        "comparison_count": 20,
        "exact_set_count": 20,
        "exact_set_rate": 1.0,
    }
    assert report["examples"]["overall"]["exact_set_count"] == 19
    assert report["examples"]["overall"]["precision"] == pytest.approx(17 / 18)
    assert report["failure_counts"] == {
        "surface_item_failures": 0,
        "example_failures": 1,
    }

    failures = [record for record in report["records"] if not record["examples_exact"]]
    assert [record["id"] for record in failures] == ["canonical-v1-responsibility-001"]
    assert failures[0]["predicted_examples"] == ["LLM", "SFT", "RLHF"]
    assert failures[0]["missing_examples"] == []
    assert failures[0]["unexpected_examples"] == ["LLM"]


def test_surface_prototype_rejects_empty_source() -> None:
    with pytest.raises(ValueError, match="source_text"):
        extract_surface_items("  ", "skill")
