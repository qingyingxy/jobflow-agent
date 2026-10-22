from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.evaluation.model_first_v4_1_compatibility import (
    evaluate_live_probe_v4_1,
)
from src.evaluation.model_first_v4_live_probe import (
    UnifiedJDFlatAtomicLiveResponseV4,
)
from src.services.unified_jd_flat_atomic_v4_compatibility import (
    normalize_flat_atomic_v4_wire_output,
)

ROOT = Path(__file__).resolve().parents[1]
LIVE_RAW = ROOT / (
    "artifacts/evaluation/"
    "unified-jd-flat-atomic-v4-live-probe-raw-responses-v1-2026-09-06.json"
)
LIVE_SELECTION = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_live_probe_selection_v1_2026-09-06.json"
)
LIVE_PREREGISTRATION = ROOT / (
    "datasets/"
    "unified_jd_flat_atomic_v4_live_probe_preregistration_v1_2026-09-06.json"
)
DEV20_RAW = ROOT / (
    "artifacts/evaluation/"
    "unified-jd-flat-atomic-v4-dev20-raw-v1-2026-09-05.json"
)


def _atom(
    *, role: str, category: str = "responsibility", level: str = "mention"
) -> dict[str, object]:
    return {
        "role": role,
        "category": category,
        "level": level,
        "relation": "all_of",
        "semantic_item": "设计安全系统",
        "surface_item": "设计安全系统",
        "source_text": "设计安全系统",
        "group_name": None,
        "allow_other": False,
        "qualifier": None,
    }


def _response(atom: dict[str, object]) -> dict[str, object]:
    return {"fact_mentions": [], "clause_atoms": [atom]}


def _load(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_exact_responsibility_alias_is_normalized_on_a_copy() -> None:
    raw = _response(_atom(role="responsibility"))
    frozen_copy = copy.deepcopy(raw)

    result = normalize_flat_atomic_v4_wire_output(raw)

    assert raw == frozen_copy
    assert result.output["clause_atoms"][0]["role"] == "item"
    assert result.activation_count == 1
    assert result.diagnostics[0].as_dict() == {
        "path": "clause_atoms[0].role",
        "atom_index": 0,
        "code": "normalized_responsibility_role_alias",
        "before_role": "responsibility",
        "after_role": "item",
    }
    UnifiedJDFlatAtomicLiveResponseV4.model_validate(result.output)


@pytest.mark.parametrize(
    ("category", "level"),
    (("skill", "mention"), ("responsibility", "required")),
)
def test_near_miss_responsibility_aliases_remain_invalid(
    category: str, level: str
) -> None:
    raw = _response(
        _atom(role="responsibility", category=category, level=level)
    )

    result = normalize_flat_atomic_v4_wire_output(raw)

    assert result.output == raw
    assert result.activation_count == 0
    with pytest.raises(ValidationError):
        UnifiedJDFlatAtomicLiveResponseV4.model_validate(result.output)


@pytest.mark.parametrize(
    ("role", "category", "level"),
    (("item", "responsibility", "mention"), ("example", "skill", "required")),
)
def test_existing_valid_roles_are_unchanged(
    role: str, category: str, level: str
) -> None:
    raw = _response(_atom(role=role, category=category, level=level))

    result = normalize_flat_atomic_v4_wire_output(raw)

    assert result.output == raw
    assert result.activation_count == 0
    UnifiedJDFlatAtomicLiveResponseV4.model_validate(result.output)


def test_frozen_live_probe_recovers_all_gates_without_new_calls() -> None:
    report = evaluate_live_probe_v4_1(
        _load(LIVE_SELECTION),
        _load(LIVE_PREREGISTRATION),
        _load(LIVE_RAW),
        frozen_inputs_valid=True,
        frozen_sources_valid=True,
    )

    assert report["passed"] is True
    assert all(gate["passed"] for gate in report["gates"].values())
    assert report["compatibility"]["activation_count"] == 18
    assert report["compatibility"]["activated_record_count"] == 1
    assert report["gates"]["G1-json-and-root-topology"][
        "schema_valid_case_count"
    ] == 5
    assert report["gates"]["G5-granularity-noncollapse"][
        "primary_atom_count"
    ] == 173
    assert report["gates"]["G6-fact-layer-compatibility"][
        "compatible_case_count"
    ] == 5
    assert report["new_model_call_count"] == 0
    assert report["offline_network_call_count"] == 0


def test_dev20_atoms_have_zero_compatibility_activations() -> None:
    dev20 = _load(DEV20_RAW)
    atoms = [
        atom for record in dev20["records"] for atom in record["clause_atoms"]
    ]
    payload = {"fact_mentions": [], "clause_atoms": atoms}

    result = normalize_flat_atomic_v4_wire_output(payload)

    assert result.output == payload
    assert result.activation_count == 0
    assert len(atoms) == 427
