from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest

from scripts.evaluate_unified_jd_flat_atomic_v4_3_compatibility_gates import (
    _existing_controls_gate,
    _fail_closed_gate,
    _static_audit,
    _tail_control_gate,
)
from src.evaluation.model_first_v4_2_compatibility import (
    normalize_raw_responses_v4_2,
)
from src.evaluation.model_first_v4_3_compatibility import (
    normalize_raw_responses_v4_3,
)
from src.services.unified_jd_flat_atomic_v4_2_compatibility import (
    EMPTY_FACT_CODE,
    LONG_EVIDENCE_CODE,
    ROLE_ALIAS_CODE,
    normalize_flat_atomic_v4_2_wire_output,
    restore_flat_atomic_v4_2_wire_output,
)
from src.services.unified_jd_flat_atomic_v4_3_compatibility import (
    normalize_flat_atomic_v4_3_wire_output,
    restore_flat_atomic_v4_3_wire_output,
)

ROOT = Path(__file__).resolve().parents[1]
V4_2_REPORT = ROOT / (
    "artifacts/evaluation/"
    "unified-jd-flat-atomic-v4-2-compatibility-report-v1-2026-09-06.json"
)


def _atom(
    *,
    role: str = "item",
    category: str = "skill",
    level: str = "required",
    semantic: str = "target",
    surface: str | None = "target",
    source: str = "target",
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
        "qualifier": None,
    }


def _empty_fact(field: str = "deadline") -> dict[str, object]:
    return {
        "field": field,
        "raw_items": [],
        "level": None,
        "source_text": "",
    }


def _valid_fact(field: str, text: str) -> dict[str, object]:
    return {
        "field": field,
        "raw_items": [text],
        "level": None,
        "source_text": text,
    }


def _tail_control() -> dict[str, object]:
    return {
        "fact_mentions": [
            _valid_fact("locations", "Remote"),
            _valid_fact("education_requirements", "Bachelor's degree"),
            *[
                _empty_fact(field)
                for field in (
                    "graduation_years",
                    "major_requirements",
                    "internship_duration_months",
                    "weekly_days",
                    "earliest_start_date",
                    "deadline",
                    "job_type",
                )
            ],
        ],
        "clause_atoms": [],
    }


def test_forward_result_is_the_exact_v4_2_result() -> None:
    raw = {
        "fact_mentions": [_empty_fact()],
        "clause_atoms": [
            _atom(
                role="responsibility",
                category="responsibility",
                level="mention",
            ),
            _atom(source="x" * 241 + "target"),
        ],
    }
    frozen = copy.deepcopy(raw)

    v4_2 = normalize_flat_atomic_v4_2_wire_output(raw)
    v4_3 = normalize_flat_atomic_v4_3_wire_output(raw)

    assert raw == frozen
    assert v4_3 == v4_2
    assert v4_3.output == v4_2.output
    assert v4_3.diagnostics == v4_2.diagnostics
    assert [item.code for item in v4_3.diagnostics] == [
        ROLE_ALIAS_CODE,
        EMPTY_FACT_CODE,
        LONG_EVIDENCE_CODE,
    ]


def test_consecutive_tail_omissions_are_restored_in_original_order() -> None:
    raw = _tail_control()
    result = normalize_flat_atomic_v4_3_wire_output(raw)

    assert [item.fact_index for item in result.diagnostics] == list(range(2, 9))
    assert result.output["fact_mentions"] == raw["fact_mentions"][:2]
    assert (
        restore_flat_atomic_v4_2_wire_output(result.output, result.diagnostics) != raw
    )
    assert (
        restore_flat_atomic_v4_3_wire_output(result.output, result.diagnostics) == raw
    )


@pytest.mark.parametrize(
    "raw",
    [
        {"fact_mentions": [_empty_fact()], "clause_atoms": []},
        {
            "fact_mentions": [],
            "clause_atoms": [
                _atom(
                    role="responsibility",
                    category="responsibility",
                    level="mention",
                )
            ],
        },
        {
            "fact_mentions": [],
            "clause_atoms": [_atom(source="x" * 241 + "target")],
        },
        {
            "fact_mentions": [_empty_fact()],
            "clause_atoms": [
                _atom(
                    role="responsibility",
                    category="responsibility",
                    level="mention",
                ),
                _atom(source="x" * 241 + "target"),
            ],
        },
    ],
)
def test_registered_singleton_and_combined_treatments_reverse(
    raw: dict[str, object],
) -> None:
    result = normalize_flat_atomic_v4_3_wire_output(raw)

    assert (
        restore_flat_atomic_v4_3_wire_output(result.output, result.diagnostics) == raw
    )


def test_empty_diagnostics_return_an_equal_deep_copy() -> None:
    raw = {"fact_mentions": [], "clause_atoms": [_atom()]}

    restored = restore_flat_atomic_v4_3_wire_output(raw, ())

    assert restored == raw
    assert restored is not raw
    assert restored["clause_atoms"] is not raw["clause_atoms"]


def test_record_evaluator_is_forward_equivalent_and_nonmutating() -> None:
    raw = {
        "response_version": "synthetic",
        "records": [
            {
                "case_id": "synthetic-tail",
                "raw_model_output": _tail_control(),
            }
        ],
    }
    frozen = copy.deepcopy(raw)

    v4_2_output, v4_2_audit = normalize_raw_responses_v4_2(raw)
    v4_3_output, v4_3_audit = normalize_raw_responses_v4_3(raw)

    assert raw == frozen
    assert v4_3_output == v4_2_output
    assert v4_3_audit == v4_2_audit


def test_duplicate_omission_indices_fail_without_mutating_output() -> None:
    raw = _tail_control()
    result = normalize_flat_atomic_v4_3_wire_output(raw)
    diagnostics = list(result.diagnostics)
    diagnostics[1] = replace(
        diagnostics[1],
        fact_index=diagnostics[0].fact_index,
        path=diagnostics[0].path,
    )
    frozen_output = copy.deepcopy(result.output)

    with pytest.raises(ValueError, match="duplicate"):
        restore_flat_atomic_v4_3_wire_output(result.output, diagnostics)

    assert result.output == frozen_output


@pytest.mark.parametrize(
    "mutation",
    [
        lambda item: replace(item, code="unknown_code"),
        lambda item: replace(item, pipeline_order=2),
        lambda item: replace(item, atom_index=99, path="clause_atoms[99].role"),
    ],
)
def test_invalid_role_diagnostics_fail_without_mutating_output(mutation) -> None:
    raw = {
        "fact_mentions": [],
        "clause_atoms": [
            _atom(
                role="responsibility",
                category="responsibility",
                level="mention",
            )
        ],
    }
    result = normalize_flat_atomic_v4_3_wire_output(raw)
    diagnostic = mutation(result.diagnostics[0])
    frozen_output = copy.deepcopy(result.output)

    with pytest.raises(ValueError):
        restore_flat_atomic_v4_3_wire_output(result.output, (diagnostic,))

    assert result.output == frozen_output


def test_treatment_mismatch_fails_without_mutating_output() -> None:
    raw = {
        "fact_mentions": [],
        "clause_atoms": [
            _atom(
                role="responsibility",
                category="responsibility",
                level="mention",
            )
        ],
    }
    result = normalize_flat_atomic_v4_3_wire_output(raw)
    mismatched = copy.deepcopy(result.output)
    mismatched["clause_atoms"][0]["role"] = "example"
    frozen_output = copy.deepcopy(mismatched)

    with pytest.raises(ValueError, match="does not match output"):
        restore_flat_atomic_v4_3_wire_output(mismatched, result.diagnostics)

    assert mismatched == frozen_output


def test_registered_tail_gate_passes() -> None:
    result, _ = _tail_control_gate()

    assert result["passed"] is True
    assert result["diagnostic_fact_indices"] == list(range(2, 9))
    assert result["v4_2_reverse_restores_input"] is False
    assert result["v4_3_reverse_restores_input"] is True


def test_all_reverse_fail_closed_controls_pass() -> None:
    result = _fail_closed_gate()

    assert result["passed"] is True
    assert all(result["checks"].values())


def test_existing_controls_and_runtime_static_audit_pass() -> None:
    report = json.loads(V4_2_REPORT.read_text(encoding="utf-8"))
    controls = _existing_controls_gate(report)
    static_audit = _static_audit()

    assert controls["passed"] is True
    assert controls["control_count"] == 16
    assert controls["names_exactly_equal_frozen_v4_2_report"] is True
    assert static_audit["passed"] is True
    assert static_audit["violations"] == []
