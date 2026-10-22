from __future__ import annotations

from copy import deepcopy

from src.evaluation.model_first_v4_3_category_vocabulary_admission_oracle import (
    analyze_category_vocabulary_admission,
    category_admission_diagnostics,
    schema_delta_is_category_only,
)
from src.evaluation.model_first_v4_live_probe import analyze_live_response_v4


def _atom(category: str) -> dict[str, object]:
    return {
        "role": "item",
        "category": category,
        "level": "required",
        "relation": "all_of",
        "semantic_item": "machine learning",
        "surface_item": "machine learning",
        "source_text": "machine learning",
        "group_name": None,
        "allow_other": False,
        "qualifier": None,
    }


def _response(*atoms: dict[str, object]) -> dict[str, object]:
    return {"fact_mentions": [], "clause_atoms": list(atoms)}


def test_oracle_admits_only_registered_category_literals_without_mutation() -> None:
    payload = _response(_atom("motivation"), _atom("knowledge"), _atom("skill"))
    before = deepcopy(payload)

    baseline = analyze_live_response_v4(payload, "machine learning")
    oracle = analyze_category_vocabulary_admission(payload, "machine learning")
    diagnostics = category_admission_diagnostics(payload, record_index=3)

    assert not baseline["schema_valid"]
    assert oracle["schema_valid"]
    assert diagnostics == [
        {
            "record_index": 3,
            "atom_index": 0,
            "path": "clause_atoms[0].category",
            "category": "motivation",
        },
        {
            "record_index": 3,
            "atom_index": 1,
            "path": "clause_atoms[1].category",
            "category": "knowledge",
        },
    ]
    assert payload == before


def test_oracle_rejects_unregistered_category_and_keeps_other_constraints() -> None:
    unknown = _response(_atom("culture"))
    zero_bound_atom = _atom("experience")
    zero_bound_atom["qualifier"] = {
        "experience_type": "professional",
        "minimum_months": 0,
        "domain": None,
    }
    zero_bound = _response(zero_bound_atom)

    unknown_analysis = analyze_category_vocabulary_admission(
        unknown, "machine learning"
    )
    zero_analysis = analyze_category_vocabulary_admission(
        zero_bound, "machine learning"
    )

    assert not unknown_analysis["schema_valid"]
    assert [item["code"] for item in unknown_analysis["diagnostics"]] == [
        "literal_error"
    ]
    assert category_admission_diagnostics(unknown, record_index=0) == []
    assert not zero_analysis["schema_valid"]
    assert [item["code"] for item in zero_analysis["diagnostics"]] == [
        "greater_than_equal"
    ]


def test_oracle_schema_delta_is_only_the_category_enum() -> None:
    assert schema_delta_is_category_only()
