from __future__ import annotations

import copy

import pytest

from scripts.evaluate_unified_jd_flat_atomic_v4_role_counterfactual import (
    apply_responsibility_role_counterfactual,
)


def _raw(role: str, category: str = "responsibility") -> dict[str, object]:
    return {
        "records": [
            {
                "case_id": "case-1",
                "raw_model_output": {
                    "fact_mentions": [],
                    "clause_atoms": [
                        {
                            "role": role,
                            "category": category,
                            "semantic_item": "设计安全系统",
                        }
                    ],
                },
            }
        ]
    }


def test_counterfactual_changes_only_responsibility_role() -> None:
    source = _raw("responsibility")
    frozen_copy = copy.deepcopy(source)

    transformed, audit = apply_responsibility_role_counterfactual(source)

    assert source == frozen_copy
    atom = transformed["records"][0]["raw_model_output"]["clause_atoms"][0]
    assert atom == {
        "role": "item",
        "category": "responsibility",
        "semantic_item": "设计安全系统",
    }
    assert len(audit) == 1
    assert audit[0]["case_id"] == "case-1"
    assert audit[0]["atom_index"] == 0


def test_counterfactual_leaves_valid_item_role_unchanged() -> None:
    source = _raw("item")

    transformed, audit = apply_responsibility_role_counterfactual(source)

    assert transformed == source
    assert audit == []


def test_counterfactual_rejects_cross_category_role_normalization() -> None:
    source = _raw("responsibility", category="skill")

    with pytest.raises(ValueError, match="outside the responsibility category"):
        apply_responsibility_role_counterfactual(source)
