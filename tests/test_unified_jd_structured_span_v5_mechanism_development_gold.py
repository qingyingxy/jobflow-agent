from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SELECTION_PATH = (
    ROOT
    / "datasets"
    / "unified_jd_structured_span_v5_mechanism_development_selection_v1_2026-09-04.json"
)
LABELS_PATH = (
    ROOT
    / "datasets"
    / "unified_jd_structured_span_v5_mechanism_development_labels_v1_2026-09-04.json"
)
FREEZE_PATH = (
    ROOT
    / "datasets"
    / "unified_jd_structured_span_v5_mechanism_development_label_freeze_v1_2026-09-04.json"
)


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def spans(value: Any):
    if isinstance(value, dict):
        if {"text", "start", "end"} <= value.keys():
            yield value
        else:
            for nested in value.values():
                yield from spans(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from spans(nested)


def test_gold_is_frozen_revealed_development_and_matches_selection() -> None:
    selection = load(SELECTION_PATH)
    labels = load(LABELS_PATH)
    by_id = {fixture["id"]: fixture for fixture in selection["fixtures"]}

    assert labels["status"] == "two_pass_human_reviewed_revealed_development_frozen"
    assert labels["data_status"] == "revealed_development_not_holdout"
    assert labels["review"]["passes"] == 2
    assert labels["model_call_count"] == 0
    assert len(labels["fixtures"]) == 20
    assert len({fixture["job_id"] for fixture in labels["fixtures"]}) == 20
    assert labels["selection"]["sha256"] == sha256(SELECTION_PATH)

    for fixture in labels["fixtures"]:
        selected = by_id[fixture["id"]]
        assert fixture["job_id"] == selected["job_id"]
        assert fixture["category"] == selected["category"]
        assert fixture["source_section"] == selected["source_section"]
        assert fixture["source_text"] == selected["source_text"]


def test_every_structural_span_resolves_and_edges_are_well_formed() -> None:
    labels = load(LABELS_PATH)
    valid_roles = {"surface", "embedded", "example", "quantifier"}

    for fixture in labels["fixtures"]:
        source = fixture["source_text"]
        assert fixture["wrappers"]
        assert fixture["projection"]["surface_items"]
        for span in spans(
            {
                "wrappers": fixture["wrappers"],
                "connector_labels": fixture["connector_labels"],
                "coordinations": fixture["coordinations"],
                "shared_scopes": fixture["shared_scopes"],
                "example_attachments": fixture["example_attachments"],
            }
        ):
            assert 0 <= span["start"] < span["end"] <= len(source)
            assert source[span["start"] : span["end"]] == span["text"]

        member_spans = {
            (member["start"], member["end"], member["text"])
            for coordination in fixture["coordinations"]
            for member in coordination["member_spans"]
        }
        connector_roles = {
            (
                connector["span"]["start"],
                connector["span"]["end"],
                connector["span"]["text"],
            ): connector["role"]
            for connector in fixture["connector_labels"]
        }
        assert set(connector_roles.values()) <= valid_roles
        assert len(connector_roles) == len(fixture["connector_labels"])

        for coordination in fixture["coordinations"]:
            assert len(coordination["member_spans"]) >= 2
            assert len(coordination["connector_spans"]) == len(
                coordination["member_spans"]
            ) - 1
            for connector in coordination["connector_spans"]:
                key = (connector["start"], connector["end"], connector["text"])
                assert connector_roles[key] == coordination["role"]

        for shared_scope in fixture["shared_scopes"]:
            assert len(shared_scope["applies_to_member_spans"]) >= 2
            for member in shared_scope["applies_to_member_spans"]:
                assert (member["start"], member["end"], member["text"]) in member_spans

        for attachment in fixture["example_attachments"]:
            assert attachment["example_spans"]
            assert attachment["parent_span"]["text"] not in {"优先", "者优先"}
            for example in attachment["example_spans"]:
                assert example["text"] in fixture["projection"]["examples"]

        assert len(fixture["projection"]["surface_items"]) == len(
            set(fixture["projection"]["surface_items"])
        )
        assert len(fixture["projection"]["examples"]) == len(
            set(fixture["projection"]["examples"])
        )
        for value in (
            fixture["projection"]["surface_items"]
            + fixture["projection"]["examples"]
        ):
            assert value in source


def test_all_six_layers_and_connector_roles_have_real_coverage() -> None:
    fixtures = load(LABELS_PATH)["fixtures"]
    assert all(fixture["wrappers"] for fixture in fixtures)
    assert sum(bool(fixture["coordinations"]) for fixture in fixtures) == 20
    assert sum(bool(fixture["shared_scopes"]) for fixture in fixtures) >= 8
    assert sum(bool(fixture["example_attachments"]) for fixture in fixtures) >= 15
    assert {
        connector["role"]
        for fixture in fixtures
        for connector in fixture["connector_labels"]
    } == {"surface", "embedded", "example", "quantifier"}
    assert all(fixture["projection"]["surface_items"] for fixture in fixtures)

    assert Counter(fixture["development_stratum"] for fixture in fixtures) == {
        "E2-wrapper-boundary": 5,
        "E3-region-first-connector-role": 5,
        "E6-priority-tail-rejection": 5,
        "E7-prepositional-wrapper-before-example-split": 5,
    }


def test_e6_priority_tail_and_e7_leading_preposition_contrasts_are_frozen() -> None:
    by_id = {
        fixture["id"]: fixture for fixture in load(LABELS_PATH)["fixtures"]
    }
    explicit_ru = by_id["structured-v5-mechanism-dev-v1-011"]
    direct_open_list = by_id["structured-v5-mechanism-dev-v1-012"]

    assert [
        (
            item["cue_span"]["text"],
            item["parent_span"]["text"],
            [example["text"] for example in item["example_spans"]],
        )
        for item in explicit_ru["example_attachments"]
    ] == [
        (
            "如",
            "理工科、管理学及相关交叉学科",
            ["数学", "统计学", "运筹学", "信息管理", "商业分析", "计量经济学"],
        )
    ]
    assert direct_open_list["example_attachments"] == []
    assert direct_open_list["projection"] == {
        "surface_items": ["手配", "小家电", "外设产品", "摄影摄像"],
        "examples": [],
    }

    expected_first_examples = {
        "structured-v5-mechanism-dev-v1-016": "人机交互",
        "structured-v5-mechanism-dev-v1-017": "商业分析",
        "structured-v5-mechanism-dev-v1-018": "供应链计划",
        "structured-v5-mechanism-dev-v1-019": "系统分层",
        "structured-v5-mechanism-dev-v1-020": "外呼的销售策略",
    }
    for fixture_id, expected in expected_first_examples.items():
        fixture = by_id[fixture_id]
        assert fixture["example_attachments"][0]["example_spans"][0]["text"] == expected
        assert not expected.startswith("对")


def test_freeze_hashes_and_declared_counts_match() -> None:
    labels = load(LABELS_PATH)
    freeze = load(FREEZE_PATH)
    fixtures = labels["fixtures"]

    assert freeze["status"] == (
        "frozen_revealed_development_gold_before_v5_preregistration"
    )
    assert freeze["artifacts"]["selection"]["sha256"] == sha256(SELECTION_PATH)
    assert freeze["artifacts"]["labels"]["sha256"] == sha256(LABELS_PATH)
    assert freeze["freeze_checks"]["layer_annotation_counts"] == {
        "wrappers": sum(len(fixture["wrappers"]) for fixture in fixtures),
        "connector_labels": sum(
            len(fixture["connector_labels"]) for fixture in fixtures
        ),
        "coordinations": sum(len(fixture["coordinations"]) for fixture in fixtures),
        "shared_scopes": sum(len(fixture["shared_scopes"]) for fixture in fixtures),
        "example_attachments": sum(
            len(fixture["example_attachments"]) for fixture in fixtures
        ),
        "surface_projection_items": sum(
            len(fixture["projection"]["surface_items"]) for fixture in fixtures
        ),
        "example_projection_items": sum(
            len(fixture["projection"]["examples"]) for fixture in fixtures
        ),
    }
    assert freeze["freeze_checks"]["parser_run_count_during_labeling"] == 0
    assert freeze["freeze_checks"]["model_call_count"] == 0
