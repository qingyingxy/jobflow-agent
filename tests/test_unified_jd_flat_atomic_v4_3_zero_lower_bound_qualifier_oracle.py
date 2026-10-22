from __future__ import annotations

from copy import deepcopy

import pytest

from src.evaluation.model_first_v4_3_zero_lower_bound_qualifier_oracle import (
    evaluate_zero_lower_bound_qualifier_pair,
)
from src.services.unified_jd_flat_atomic_v4_3_zero_lower_bound_qualifier_oracle import (
    normalize_zero_lower_bound_qualifier,
    restore_zero_lower_bound_qualifier,
)


def _atom() -> dict[str, object]:
    return {
        "role": "item",
        "category": "experience",
        "level": "required",
        "relation": "all_of",
        "semantic_item": "AI development experience",
        "surface_item": "0–3 years of AI development experience",
        "source_text": "0–3 years of AI development experience",
        "group_name": None,
        "allow_other": False,
        "qualifier": {
            "experience_type": "AI development",
            "minimum_months": 0,
            "domain": "AI",
        },
    }


def _response(*atoms: dict[str, object]) -> dict[str, object]:
    return {"fact_mentions": [], "clause_atoms": list(atoms)}


def test_zero_lower_bound_treatment_is_one_field_and_exactly_reversible() -> None:
    payload = _response(_atom())
    before = deepcopy(payload)

    result = normalize_zero_lower_bound_qualifier(payload, record_index=2)

    assert payload == before
    assert result.output["clause_atoms"][0]["qualifier"]["minimum_months"] is None
    assert [item.as_dict() for item in result.diagnostics] == [
        {
            "record_index": 2,
            "atom_index": 0,
            "path": "clause_atoms[0].qualifier.minimum_months",
            "before": 0,
            "after": None,
            "source_text": "0–3 years of AI development experience",
        }
    ]
    assert (
        restore_zero_lower_bound_qualifier(
            result.output,
            result.diagnostics,
            record_index=2,
        )
        == payload
    )


def test_zero_lower_bound_activation_requires_every_runtime_guard() -> None:
    wrong_category = _atom()
    wrong_category["category"] = "skill"
    boolean_zero = _atom()
    boolean_zero["qualifier"]["minimum_months"] = False
    wrong_topology = _atom()
    del wrong_topology["qualifier"]["domain"]
    missing_pattern = _atom()
    missing_pattern["source_text"] = "entry-level AI development experience"
    missing_pattern["surface_item"] = "AI development experience"
    unanchored_surface = _atom()
    unanchored_surface["surface_item"] = "0–3 years elsewhere"
    payload = _response(
        wrong_category,
        boolean_zero,
        wrong_topology,
        missing_pattern,
        unanchored_surface,
    )

    result = normalize_zero_lower_bound_qualifier(payload, record_index=0)

    assert result.diagnostics == ()
    assert result.output == payload


def test_zero_lower_bound_treatment_recovers_the_unchanged_strict_schema() -> None:
    payload = _response(_atom())
    result = normalize_zero_lower_bound_qualifier(payload, record_index=0)

    analyses = evaluate_zero_lower_bound_qualifier_pair(
        payload,
        result.output,
        payload["clause_atoms"][0]["source_text"],
    )

    assert not analyses["baseline"]["schema_valid"]
    assert analyses["treatment"]["schema_valid"]


def test_zero_lower_bound_reverse_rejects_tampered_evidence() -> None:
    payload = _response(_atom())
    result = normalize_zero_lower_bound_qualifier(payload, record_index=1)
    tampered = deepcopy(result.output)
    tampered["clause_atoms"][0]["source_text"] = "different source"

    with pytest.raises(ValueError, match="does not match output"):
        restore_zero_lower_bound_qualifier(
            tampered,
            result.diagnostics,
            record_index=1,
        )
