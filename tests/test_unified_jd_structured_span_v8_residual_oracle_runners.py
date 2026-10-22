from __future__ import annotations

from copy import deepcopy

import pytest

from scripts import run_unified_structured_span_v8_e10_component_bridge_oracle as e10
from scripts import (
    run_unified_structured_span_v8_e11_e7_veto_family_localization_oracle as e11,
)
from scripts import (
    run_unified_structured_span_v8_e12_s2_admission_control_oracle as e12,
)
from scripts import unified_structured_span_v8_residual_oracle_common as common


def _span(text: str, start: int, end: int) -> dict[str, object]:
    return {"text": text, "start": start, "end": end}


def _parsed_clause() -> dict[str, object]:
    source = "Know Python and SQL such as pandas"
    return {
        "source_text": source,
        "category": "skill",
        "protected_spans": [],
        "segments": [_span(source, 0, len(source))],
        "wrappers": [
            {
                "kind": "prefix",
                "marker_span": _span("Know", 0, 4),
                "content_span": _span("Python and SQL such as pandas", 5, 34),
            }
        ],
        "connector_labels": [{"span": _span("and", 12, 15), "role": "surface"}],
        "coordinations": [
            {
                "id": "coord-original",
                "role": "surface",
                "kind": "synthetic.surface",
                "connector_spans": [_span("and", 12, 15)],
                "members": [
                    {
                        "id": "member-python",
                        "span": _span("Python", 5, 11),
                        "segment_index": 0,
                    },
                    {
                        "id": "member-sql",
                        "span": _span("SQL", 16, 19),
                        "segment_index": 0,
                    },
                ],
            }
        ],
        "shared_scopes": [
            {
                "id": "scope-original",
                "kind": "prefix",
                "span": _span("Know", 0, 4),
                "applies_to_member_ids": ["member-python", "member-sql"],
            }
        ],
        "example_attachments": [
            {
                "id": "example-original-9",
                "cue_span": _span("such as", 20, 27),
                "parent_span": _span("SQL", 16, 19),
                "example_spans": [_span("pandas", 28, 34)],
                "segment_index": 0,
            }
        ],
        "item_candidates": [
            {
                "id": "candidate-python",
                "span": _span("Python", 5, 11),
                "segment_index": 0,
            },
            {
                "id": "candidate-sql",
                "span": _span("SQL", 16, 19),
                "segment_index": 0,
            },
        ],
        "rule_ids": ["synthetic.baseline"],
    }


def _record() -> dict[str, object]:
    return {
        "id": "synthetic-record",
        "items": ["Python", "SQL"],
        "examples": ["pandas"],
        "error": None,
        "rule_ids": ["synthetic.baseline"],
        "selector_trace": [],
        "parsed_clause": _parsed_clause(),
    }


def test_normalize_and_rebuild_preserve_attachment_payload() -> None:
    parsed = _parsed_clause()
    graph = common.normalize_graph(parsed)

    rebuilt = common.rebuild_graph(graph, ["synthetic.rebuild"])

    assert rebuilt["example_attachments"] == parsed["example_attachments"]
    assert rebuilt["shared_scopes"][0]["applies_to_member_ids"] == [
        "member-1",
        "member-2",
    ]


def test_component_envelope_replaces_only_overlapping_selected_nodes() -> None:
    baseline = common.normalize_graph(_parsed_clause())
    reference = deepcopy(baseline)
    reference["item_candidates"].append(
        {"span": _span("pandas", 28, 34), "segment_index": 0}
    )

    treatment = common.replace_nodes_in_envelopes(
        baseline,
        reference,
        families=("item_candidates",),
        envelopes=((28, 34),),
    )

    assert treatment["item_candidates"] == reference["item_candidates"]
    for family in set(common.GRAPH_FAMILIES) - {"item_candidates"}:
        assert treatment[family] == baseline[family]


def test_graph_validation_rejects_dangling_scope_reference() -> None:
    graph = common.normalize_graph(_parsed_clause())
    graph["shared_scopes"][0]["applies_to_spans"] = [_span("pandas", 28, 34)]

    with pytest.raises(ValueError, match="unknown member span"):
        common.validate_graph(graph)


def test_e12_full_graph_denial_changes_only_candidate_derived_families() -> None:
    baseline = _record()
    reference = deepcopy(baseline)
    reference["parsed_clause"]["item_candidates"].append(
        {
            "id": "candidate-pandas",
            "span": _span("pandas", 28, 34),
            "segment_index": 0,
        }
    )
    reference["items"].append("pandas")

    denied = e12._denied_record(baseline, reference, "legacy-20")
    before = common.full_snapshot(baseline)
    after = common.full_snapshot(denied)

    assert after["item_candidate_spans"] != before["item_candidate_spans"]
    assert after["surface_projection"] != before["surface_projection"]
    for family in set(common.EXACT_FAMILIES) - {
        "item_candidate_spans",
        "surface_projection",
        "example_projection",
    }:
        assert after[family] == before[family]


def test_e12_projection_only_denial_uses_frozen_reference_arm() -> None:
    baseline = {"id": "projection", "actual_items": ["A"]}
    reference = {"id": "projection", "actual_items": ["B"]}

    assert e12._denied_record(baseline, reference, "projection-60") is reference


def test_three_runner_sources_pass_offline_import_audit() -> None:
    audit = common.static_import_audit(
        (
            common.Path(common.__file__).resolve(),
            common.Path(e10.__file__).resolve(),
            common.Path(e11.__file__).resolve(),
            common.Path(e12.__file__).resolve(),
        )
    )

    assert audit == {
        "passed": True,
        "forbidden_imports": [],
        "dynamic_import_lines": [],
    }


def test_runner_output_names_are_pairwise_disjoint() -> None:
    output_sets = [set(module.OUTPUT_PATHS) for module in (e10, e11, e12)]

    assert all(
        left.isdisjoint(right)
        for index, left in enumerate(output_sets)
        for right in output_sets[index + 1 :]
    )
