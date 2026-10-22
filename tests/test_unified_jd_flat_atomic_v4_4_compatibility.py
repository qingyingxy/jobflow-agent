from __future__ import annotations

import copy
from dataclasses import replace

import pytest

from scripts import evaluate_unified_jd_flat_atomic_v4_4_compatibility_gates as gates
from src.evaluation.model_first_v4_4_compatibility import (
    analyze_raw_responses_v4_4,
    normalize_raw_responses_v4_4,
)
from src.evaluation.model_first_v4_live_probe import analyze_live_response_v4
from src.services.unified_jd_flat_atomic_v4_2_compatibility import (
    EMPTY_FACT_CODE,
    LONG_EVIDENCE_CODE,
    ROLE_ALIAS_CODE,
)
from src.services.unified_jd_flat_atomic_v4_4_compatibility import (
    CATEGORY_ALIAS_CODE,
    ZERO_LOWER_BOUND_CODE,
    normalize_flat_atomic_v4_4_wire_output,
    restore_flat_atomic_v4_4_wire_output,
)


def _atom(
    *,
    role: str = "item",
    category: str = "skill",
    level: str = "required",
    semantic: str = "target",
    surface: str = "target",
    source: str = "target",
    qualifier: object = None,
) -> dict[str, object]:
    return {
        "role": role,
        "category": category,
        "level": level,
        "relation": "all_of",
        "semantic_item": semantic,
        "surface_item": surface,
        "source_text": source,
        "group_name": None,
        "allow_other": False,
        "qualifier": qualifier,
    }


def _empty_fact() -> dict[str, object]:
    return {
        "field": "deadline",
        "raw_items": [],
        "level": None,
        "source_text": "",
    }


def _zero_atom() -> dict[str, object]:
    return _atom(
        category="experience",
        semantic="AI development experience",
        surface="0–3 years of AI development experience",
        source="0–3 years of AI development experience",
        qualifier={
            "experience_type": "AI development",
            "minimum_months": 0,
            "domain": "AI",
        },
    )


def _response(*atoms: dict[str, object]) -> dict[str, object]:
    return {"fact_mentions": [], "clause_atoms": list(atoms)}


def test_category_aliases_are_exact_one_field_changes_and_reversible() -> None:
    raw = _response(_atom(category="knowledge"), _atom(category="motivation"))
    frozen = copy.deepcopy(raw)

    result = normalize_flat_atomic_v4_4_wire_output(raw)

    assert raw == frozen
    assert [atom["category"] for atom in result.output["clause_atoms"]] == [
        "skill",
        "capability",
    ]
    assert [item.as_dict() for item in result.diagnostics] == [
        {
            "path": "clause_atoms[0].category",
            "code": CATEGORY_ALIAS_CODE,
            "pipeline_order": 4,
            "before": "knowledge",
            "after": "skill",
            "atom_index": 0,
        },
        {
            "path": "clause_atoms[1].category",
            "code": CATEGORY_ALIAS_CODE,
            "pipeline_order": 4,
            "before": "motivation",
            "after": "capability",
            "atom_index": 1,
        },
    ]
    assert restore_flat_atomic_v4_4_wire_output(
        result.output, result.diagnostics
    ) == raw


def test_zero_lower_bound_is_one_field_change_and_reversible() -> None:
    raw = _response(_zero_atom())
    frozen = copy.deepcopy(raw)

    result = normalize_flat_atomic_v4_4_wire_output(raw)

    assert raw == frozen
    assert result.output["clause_atoms"][0]["qualifier"]["minimum_months"] is None
    assert [item.code for item in result.diagnostics] == [ZERO_LOWER_BOUND_CODE]
    assert result.diagnostics[0].pipeline_order == 5
    assert restore_flat_atomic_v4_4_wire_output(
        result.output, result.diagnostics
    ) == raw


def test_all_five_stages_compose_in_order_and_reverse_exactly() -> None:
    long_source = "x" * 241 + "target"
    raw = {
        "fact_mentions": [_empty_fact()],
        "clause_atoms": [
            _atom(
                role="responsibility",
                category="responsibility",
                level="mention",
            ),
            _atom(source=long_source),
            _atom(category="knowledge"),
            _zero_atom(),
        ],
    }
    frozen = copy.deepcopy(raw)

    result = normalize_flat_atomic_v4_4_wire_output(raw)

    assert [item.code for item in result.diagnostics] == [
        ROLE_ALIAS_CODE,
        EMPTY_FACT_CODE,
        LONG_EVIDENCE_CODE,
        CATEGORY_ALIAS_CODE,
        ZERO_LOWER_BOUND_CODE,
    ]
    assert [item.pipeline_order for item in result.diagnostics] == [1, 2, 3, 4, 5]
    assert restore_flat_atomic_v4_4_wire_output(
        result.output, result.diagnostics
    ) == raw
    assert raw == frozen


def test_runtime_guards_fail_closed_and_unknown_category_remains_invalid() -> None:
    wrong_category = _zero_atom()
    wrong_category["category"] = "skill"
    boolean_zero = _zero_atom()
    boolean_zero["qualifier"]["minimum_months"] = False
    wrong_topology = _zero_atom()
    del wrong_topology["qualifier"]["domain"]
    missing_pattern = _zero_atom()
    missing_pattern["source_text"] = "entry-level AI development experience"
    missing_pattern["surface_item"] = "AI development experience"
    unanchored = _zero_atom()
    unanchored["surface_item"] = "0–3 years elsewhere"
    positive = _zero_atom()
    positive["qualifier"]["minimum_months"] = 72
    exact_case = _atom(category="Knowledge")
    unknown = _atom(category="culture")
    raw = _response(
        wrong_category,
        boolean_zero,
        wrong_topology,
        missing_pattern,
        unanchored,
        positive,
        exact_case,
        unknown,
    )

    result = normalize_flat_atomic_v4_4_wire_output(raw)

    assert result.output == raw
    assert result.diagnostics == ()
    assert not analyze_live_response_v4(result.output, "target 0–3 years elsewhere")[
        "schema_valid"
    ]


def test_reverse_rejects_tampering_without_mutating_output() -> None:
    raw = _response(_atom(category="knowledge"), _zero_atom())
    result = normalize_flat_atomic_v4_4_wire_output(raw)
    cases = []

    wrong_order = list(result.diagnostics)
    wrong_order[0] = replace(wrong_order[0], pipeline_order=5)
    cases.append(tuple(wrong_order))
    wrong_path = list(result.diagnostics)
    wrong_path[1] = replace(wrong_path[1], path="clause_atoms[99].qualifier.minimum_months")
    cases.append(tuple(wrong_path))
    wrong_mapping = list(result.diagnostics)
    wrong_mapping[0] = replace(wrong_mapping[0], after="capability")
    cases.append(tuple(wrong_mapping))

    for diagnostics in cases:
        output = copy.deepcopy(result.output)
        frozen = copy.deepcopy(output)
        with pytest.raises((TypeError, ValueError)):
            restore_flat_atomic_v4_4_wire_output(output, diagnostics)
        assert output == frozen

    evidence_tampered = copy.deepcopy(result.output)
    evidence_tampered["clause_atoms"][1]["source_text"] = "different source"
    frozen_evidence = copy.deepcopy(evidence_tampered)
    with pytest.raises(ValueError, match="does not match output"):
        restore_flat_atomic_v4_4_wire_output(
            evidence_tampered,
            result.diagnostics,
        )
    assert evidence_tampered == frozen_evidence


def test_empty_diagnostics_return_an_equal_deep_copy() -> None:
    raw = _response(_atom())

    restored = restore_flat_atomic_v4_4_wire_output(raw, ())

    assert restored == raw
    assert restored is not raw
    assert restored["clause_atoms"] is not raw["clause_atoms"]


def test_envelope_evaluator_recovers_both_mechanisms_without_mutation() -> None:
    raw = {
        "response_version": "synthetic",
        "records": [
            {
                "case_id": "category",
                "raw_model_output": _response(_atom(category="knowledge")),
            },
            {"case_id": "zero", "raw_model_output": _response(_zero_atom())},
        ],
    }
    frozen = copy.deepcopy(raw)
    source_by_case = {
        "category": "target",
        "zero": "0–3 years of AI development experience",
    }

    normalized, audit = normalize_raw_responses_v4_4(raw)
    evaluation = analyze_raw_responses_v4_4(raw, source_by_case)

    assert raw == frozen
    assert len(audit) == 2
    assert normalized == evaluation["normalized_raw"]
    assert evaluation["strict_schema_valid_case_count"] == 2
    assert evaluation["activation_counts"] == {
        CATEGORY_ALIAS_CODE: 1,
        ZERO_LOWER_BOUND_CODE: 1,
    }
    assert evaluation["model_call_count"] == 0
    assert evaluation["network_call_count"] == 0


def test_registered_development_and_legacy_gates_pass() -> None:
    preregistration = gates._load(gates.PREREGISTRATION)

    development, _ = gates._development_gate(preregistration)
    dev20, _ = gates._dev20_gate()
    live, _ = gates._legacy_envelope_gate(
        gates.LIVE_RAW,
        gates.LIVE_SELECTION,
        required_strict_count=None,
    )
    external, _ = gates._legacy_envelope_gate(
        gates.EXTERNAL_RAW,
        gates.EXTERNAL_SELECTION,
        required_strict_count=5,
    )

    assert development["G1"]["passed"] is True
    assert development["G1"]["v4_4_strict_valid_case_count"] == 5
    assert development["G1"]["new_activation_counts"] == {
        CATEGORY_ALIAS_CODE: 2,
        ZERO_LOWER_BOUND_CODE: 1,
    }
    assert development["G2"]["passed"] is True
    assert development["G2"]["unchanged_atom_count"] == 101
    assert dev20["passed"] is True
    assert live["passed"] is True
    assert external["passed"] is True


def test_registered_controls_and_static_audit_pass() -> None:
    controls, _ = gates._controls_gate()
    static_audit = gates._static_audit()

    assert controls["passed"] is True
    assert controls["control_count"] == 14
    assert all(controls["fail_closed_checks"].values())
    assert static_audit["passed"] is True
    assert static_audit["violations"] == []
