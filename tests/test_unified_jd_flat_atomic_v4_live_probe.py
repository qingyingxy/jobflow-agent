from __future__ import annotations

import asyncio
import json
from pathlib import Path

from scripts.run_unified_jd_flat_atomic_v4_live_probe import (
    build_live_probe_requests,
    execute_live_probe,
)
from src.evaluation.model_first_v4_live_probe import (
    analyze_live_response_v4,
    evaluate_live_probe_v4,
)
from src.infrastructure.llm_client import FakeModelClient

ROOT = Path(__file__).resolve().parents[1]
SELECTION = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_live_probe_selection_v1_2026-09-06.json"
)
PREREGISTRATION = ROOT / (
    "datasets/"
    "unified_jd_flat_atomic_v4_live_probe_preregistration_v1_2026-09-06.json"
)


def _valid_output(source_text: str) -> dict[str, object]:
    return {
        "fact_mentions": [],
        "clause_atoms": [
            {
                "role": "item",
                "category": "skill",
                "level": "required",
                "relation": "all_of",
                "semantic_item": f"掌握 {source_text}",
                "surface_item": source_text,
                "source_text": source_text,
                "group_name": None,
                "allow_other": False,
                "qualifier": None,
            }
        ],
    }


def test_request_builder_uses_frozen_prompt_and_all_five_full_bodies() -> None:
    selection = _load(SELECTION)
    preregistration = _load(PREREGISTRATION)

    requests = build_live_probe_requests(selection, preregistration)

    assert len(requests) == 5
    assert [item[0] for item in requests] == selection["selected_case_ids"]
    for case, (_, input_sha256, request) in zip(
        selection["cases"], requests, strict=True
    ):
        assert input_sha256 == case["source_content_sha256"]
        assert case["raw_content"] in request.messages[-1].content
        assert request.max_output_tokens == 8192
        assert request.prompt_version == (
            "unified-jd-flat-atomic-v4-live-probe-prompt-v1"
        )
        assert "expected" not in request.messages[-1].content


def test_shape_validation_rejects_nested_or_implicit_fields() -> None:
    nested = {
        "fact_mentions": [],
        "clauses": [
            {
                "category": "skill",
                "level": "required",
                "relation": "all_of",
                "items": ["Python"],
                "source_text": "Python",
            }
        ],
    }
    implicit = {
        "fact_mentions": [],
        "clause_atoms": [
            {
                "category": "skill",
                "level": "required",
                "relation": "all_of",
                "semantic_item": "Python",
                "surface_item": "Python",
                "source_text": "Python",
            }
        ],
    }

    assert analyze_live_response_v4(nested, "Python")["schema_valid"] is False
    analysis = analyze_live_response_v4(implicit, "Python")
    assert analysis["schema_valid"] is False
    assert analysis["atom_fields_exact"] is False


def test_shape_validation_keeps_semantic_and_surface_separate() -> None:
    output = _valid_output("Python")

    analysis = analyze_live_response_v4(output, "熟悉 Python")

    assert analysis["schema_valid"] is True
    assert analysis["primary_atom_count"] == 1
    assert analysis["separated_pair_count"] == 1
    assert analysis["located_nonnull_primary_surface_count"] == 1
    assert analysis["fact_layer_compatible"] is True


def test_fake_execution_never_exceeds_one_call_per_case_or_five_total() -> None:
    selection = _load(SELECTION)
    preregistration = _load(PREREGISTRATION)
    requests = build_live_probe_requests(selection, preregistration)
    client = FakeModelClient(output=_valid_output("岗位"))

    raw = asyncio.run(execute_live_probe(requests, client))

    assert raw["model_call_count"] == 5
    assert len(raw["records"]) == 5
    assert all(record["model_call_count"] == 1 for record in raw["records"])
    assert len({record["case_id"] for record in raw["records"]}) == 5


def test_evaluator_reports_preregistered_granularity_failure_without_repair() -> None:
    selection = _load(SELECTION)
    preregistration = _load(PREREGISTRATION)
    requests = build_live_probe_requests(selection, preregistration)
    records = [
        {
            "case_id": case_id,
            "model_call_count": 1,
            "failure_code": None,
            "raw_model_output": _valid_output(
                next(
                    line.strip()
                    for line in case["raw_content"].splitlines()
                    if line.strip()
                )
            ),
        }
        for case, (case_id, _, _) in zip(
            selection["cases"], requests, strict=True
        )
    ]

    report = evaluate_live_probe_v4(
        selection,
        preregistration,
        {"records": records},
        authorization_confirmed=True,
        destination_valid=True,
        frozen_inputs_valid=True,
        frozen_sources_valid=True,
        gold_unavailable_to_requests=True,
    )

    assert report["passed"] is False
    assert report["gates"]["G0-authorization-destination-and-budget"][
        "passed"
    ]
    assert report["gates"]["G1-json-and-root-topology"]["passed"]
    assert report["gates"]["G5-granularity-noncollapse"]["passed"] is False
    assert report["model_call_count"] == 5


def _load(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value
