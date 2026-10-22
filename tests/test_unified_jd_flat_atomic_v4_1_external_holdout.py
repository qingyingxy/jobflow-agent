from __future__ import annotations

from typing import Any

import pytest

from scripts.run_unified_jd_flat_atomic_v4_1_external_holdout import main
from src.evaluation.model_first_v4_1_external_holdout import (
    evaluate_external_holdout_v4_1,
)

CASE_IDS = [f"external-case-{index}" for index in range(5)]


def _selection() -> dict[str, Any]:
    return {
        "selected_case_ids": CASE_IDS,
        "cases": [
            {"case_id": case_id, "raw_content": "Build systems"} for case_id in CASE_IDS
        ],
    }


def _preregistration() -> dict[str, Any]:
    return {
        "acceptance_gates": {
            "G5-granularity-noncollapse": {
                "per_case_minimums": {case_id: 1 for case_id in CASE_IDS},
                "minimum_aggregate_primary_atom_count": 5,
                "maximum_aggregate_primary_atom_count": 10,
            }
        }
    }


def _atom(*, role: str, category: str = "responsibility") -> dict[str, Any]:
    return {
        "role": role,
        "category": category,
        "level": "mention",
        "relation": "all_of",
        "semantic_item": "build reliable systems",
        "surface_item": "Build systems",
        "source_text": "Build systems",
        "group_name": None,
        "allow_other": False,
        "qualifier": None,
    }


def _raw(
    *, first_role: str = "item", first_category: str = "responsibility"
) -> dict[str, Any]:
    records = []
    for index, case_id in enumerate(CASE_IDS):
        records.append(
            {
                "case_id": case_id,
                "model_call_count": 1,
                "failure_code": None,
                "raw_model_output": {
                    "fact_mentions": [],
                    "clause_atoms": [
                        _atom(
                            role=first_role if index == 0 else "item",
                            category=first_category if index == 0 else "responsibility",
                        )
                    ],
                },
            }
        )
    return {"model_call_count": 5, "records": records}


def _evaluate(raw: dict[str, Any]) -> dict[str, Any]:
    return evaluate_external_holdout_v4_1(
        _selection(),
        _preregistration(),
        raw,
        authorization_confirmed=True,
        destination_valid=True,
        frozen_inputs_valid=True,
        frozen_sources_valid=True,
        gold_unavailable_to_requests=True,
    )


def test_external_holdout_confirms_eligible_alias_recovery() -> None:
    report = _evaluate(_raw(first_role="responsibility"))

    assert report["passed"] is True
    assert report["decision"] == "confirmed"
    assert report["gates"]["G8-causal-generalization-decision"] == {
        "passed": True,
        "decision": "confirmed",
        "activation_count": 1,
        "activated_case_count": 1,
        "activated_case_ids": ["external-case-0"],
        "activated_cases_have_only_eligible_alias_errors": True,
        "activated_cases_recovered": True,
        "baseline_schema_valid_case_count": 4,
        "v4_1_schema_valid_case_count": 5,
    }


def test_external_holdout_reports_non_regression_when_alias_is_absent() -> None:
    report = _evaluate(_raw())

    assert report["passed"] is True
    assert report["decision"] == "supported_non_regression_only"
    assert (
        report["gates"]["G2-compatibility-intervention-integrity"]["activation_count"]
        == 0
    )


def test_external_holdout_fails_closed_for_ineligible_alias() -> None:
    report = _evaluate(_raw(first_role="responsibility", first_category="skill"))

    assert report["passed"] is False
    assert report["decision"] == "failed"
    assert report["gates"]["G1-json-and-root-topology"]["passed"] is False
    assert (
        report["gates"]["G2-compatibility-intervention-integrity"]["activation_count"]
        == 0
    )


def test_external_holdout_runner_requires_explicit_transmission_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["run_unified_jd_flat_atomic_v4_1_external_holdout.py"],
    )

    with pytest.raises(SystemExit, match="explicit authorization"):
        main()
