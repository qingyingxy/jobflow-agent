from __future__ import annotations

import copy

import pytest

from scripts.evaluate_unified_jd_flat_atomic_v4_2_compatibility_gates import (
    _control_gate,
    _static_audit,
)
from src.evaluation.model_first_v4_2_compatibility import (
    normalize_raw_responses_v4_2,
)
from src.evaluation.model_first_v4_live_probe import (
    UnifiedJDFlatAtomicLiveResponseV4,
)
from src.services.unified_jd_flat_atomic_v4_2_compatibility import (
    EMPTY_FACT_CODE,
    LONG_EVIDENCE_CODE,
    ROLE_ALIAS_CODE,
    normalize_flat_atomic_v4_2_wire_output,
    restore_flat_atomic_v4_2_wire_output,
)


def _atom(
    *,
    role: str = "item",
    category: str = "skill",
    level: str = "required",
    semantic_item: str = "target",
    surface_item: str | None = "target",
    source_text: str = "target",
) -> dict[str, object]:
    return {
        "role": role,
        "category": category,
        "level": level,
        "relation": "all_of",
        "semantic_item": semantic_item,
        "surface_item": surface_item,
        "source_text": source_text,
        "group_name": None,
        "allow_other": False,
        "qualifier": None,
    }


def _empty_fact(**updates: object) -> dict[str, object]:
    fact: dict[str, object] = {
        "field": "deadline",
        "raw_items": [],
        "level": None,
        "source_text": "",
    }
    fact.update(updates)
    return fact


def test_combined_pipeline_is_ordered_reversible_and_does_not_mutate() -> None:
    role_atom = _atom(
        role="responsibility",
        category="responsibility",
        level="mention",
    )
    long_atom = _atom(source_text="x" * 241 + "target")
    raw = {
        "fact_mentions": [_empty_fact()],
        "clause_atoms": [role_atom, long_atom],
    }
    frozen = copy.deepcopy(raw)

    result = normalize_flat_atomic_v4_2_wire_output(raw)

    assert raw == frozen
    assert result.output == {
        "fact_mentions": [],
        "clause_atoms": [
            {**role_atom, "role": "item"},
            {**long_atom, "source_text": "target"},
        ],
    }
    assert [item.code for item in result.diagnostics] == [
        ROLE_ALIAS_CODE,
        EMPTY_FACT_CODE,
        LONG_EVIDENCE_CODE,
    ]
    assert [item.pipeline_order for item in result.diagnostics] == [1, 2, 3]
    assert result.diagnostics[1].as_dict()["before"] == _empty_fact()
    assert (
        restore_flat_atomic_v4_2_wire_output(result.output, result.diagnostics) == raw
    )
    UnifiedJDFlatAtomicLiveResponseV4.model_validate(result.output)


def test_multiple_omissions_restore_original_fact_order() -> None:
    first = _empty_fact(field="locations")
    retained = {
        "field": "locations",
        "raw_items": ["Remote"],
        "level": None,
        "source_text": "Remote",
    }
    last = _empty_fact(field="deadline")
    raw = {
        "fact_mentions": [first, retained, last],
        "clause_atoms": [],
    }

    result = normalize_flat_atomic_v4_2_wire_output(raw)

    assert result.output["fact_mentions"] == [retained]
    assert [item.fact_index for item in result.diagnostics] == [0, 2]
    assert (
        restore_flat_atomic_v4_2_wire_output(result.output, result.diagnostics) == raw
    )


@pytest.mark.parametrize(
    "fact",
    [
        _empty_fact(level="required"),
        _empty_fact(source_text="deadline"),
        _empty_fact(raw_items=["2026-09-30"]),
    ],
)
def test_fact_near_misses_are_unchanged(fact: dict[str, object]) -> None:
    raw = {"fact_mentions": [fact], "clause_atoms": []}

    result = normalize_flat_atomic_v4_2_wire_output(raw)

    assert result.output == raw
    assert result.activation_count == 0


@pytest.mark.parametrize(
    "atom",
    [
        _atom(source_text="x" * 234 + "target"),
        _atom(surface_item=None, source_text="x" * 241),
        _atom(
            semantic_item="x" * 241,
            surface_item="x" * 241,
            source_text="x" * 241,
        ),
        _atom(source_text="x" * 241),
        _atom(
            semantic_item="interpreted target",
            source_text="x" * 241 + "target",
        ),
    ],
)
def test_long_evidence_near_misses_are_unchanged(
    atom: dict[str, object],
) -> None:
    raw = {"fact_mentions": [], "clause_atoms": [atom]}

    result = normalize_flat_atomic_v4_2_wire_output(raw)

    assert result.output == raw
    assert result.activation_count == 0


@pytest.mark.parametrize(
    "atom",
    [
        _atom(role="item", category="responsibility", level="mention"),
        _atom(role="example"),
        _atom(role="responsibility", category="skill", level="mention"),
        _atom(
            role="responsibility",
            category="responsibility",
            level="required",
        ),
    ],
)
def test_v4_1_role_controls_remain_unchanged(atom: dict[str, object]) -> None:
    raw = {"fact_mentions": [], "clause_atoms": [atom]}

    result = normalize_flat_atomic_v4_2_wire_output(raw)

    assert result.output == raw
    assert result.activation_count == 0


def test_existing_arrays_are_processed_independently() -> None:
    raw = {"fact_mentions": [_empty_fact()], "clause_atoms": "malformed"}

    result = normalize_flat_atomic_v4_2_wire_output(raw)

    assert result.output == {"fact_mentions": [], "clause_atoms": "malformed"}
    assert [item.code for item in result.diagnostics] == [EMPTY_FACT_CODE]
    assert (
        restore_flat_atomic_v4_2_wire_output(result.output, result.diagnostics) == raw
    )


def test_record_evaluator_preserves_envelope_and_returns_ordered_audit() -> None:
    raw = {
        "response_version": "frozen",
        "records": [
            {
                "case_id": "synthetic-positive",
                "model_call_count": 1,
                "raw_model_output": {
                    "fact_mentions": [_empty_fact()],
                    "clause_atoms": [
                        _atom(
                            role="responsibility",
                            category="responsibility",
                            level="mention",
                        )
                    ],
                },
            }
        ],
    }
    frozen = copy.deepcopy(raw)

    normalized, audit = normalize_raw_responses_v4_2(raw)

    assert raw == frozen
    assert normalized["response_version"] == "frozen"
    assert normalized["records"][0]["model_call_count"] == 1
    assert [item["code"] for item in audit[0]["diagnostics"]] == [
        ROLE_ALIAS_CODE,
        EMPTY_FACT_CODE,
    ]


def test_all_preregistered_synthetic_controls_pass() -> None:
    result = _control_gate()

    assert result["passed"] is True
    assert result["positive_control_count"] == 4
    assert result["negative_control_count"] == 12
    assert result["control_count"] == 16


def test_runtime_adapter_static_isolation_passes() -> None:
    result = _static_audit()

    assert result["passed"] is True
    assert result["violations"] == []
