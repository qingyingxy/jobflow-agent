from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.domain.unified_jd_flat_atomic_v4 import (
    UnifiedJDFlatAtomicClausesV4,
    UnifiedJDFlatAtomicClauseV4,
)
from src.evaluation.model_first_v4 import (
    audit_flat_atomic_v4_runtime_sources,
    build_flat_atomic_v4_projection,
    classify_nested_v3_without_repair,
    evaluate_flat_atomic_v4,
)
from src.services.unified_jd_flat_atomic_v4 import compile_flat_atomic_clauses_v4

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts/evaluation"


def _atom(**updates: object) -> dict[str, object]:
    value: dict[str, object] = {
        "role": "item",
        "category": "skill",
        "level": "required",
        "relation": "all_of",
        "semantic_item": "熟悉 Python",
        "surface_item": "Python",
        "source_text": "熟悉 Python 和 R",
        "group_name": None,
        "allow_other": False,
        "qualifier": None,
    }
    value.update(updates)
    return value


def test_contract_requires_explicit_structure_and_exact_or_null_surface() -> None:
    exact = UnifiedJDFlatAtomicClauseV4.model_validate(_atom())
    unmapped = UnifiedJDFlatAtomicClauseV4.model_validate(
        _atom(semantic_item="熟悉 R", surface_item=None)
    )

    assert exact.surface_item == "Python"
    assert unmapped.surface_item is None
    with pytest.raises(ValidationError):
        UnifiedJDFlatAtomicClauseV4.model_validate(
            _atom(surface_item="Java")
        )
    with pytest.raises(ValidationError):
        UnifiedJDFlatAtomicClauseV4.model_validate(
            {key: value for key, value in _atom().items() if key != "category"}
        )


def test_grouping_uses_only_explicit_metadata_and_preserves_roles() -> None:
    output = UnifiedJDFlatAtomicClausesV4.model_validate(
        {
            "clause_atoms": [
                _atom(),
                _atom(semantic_item="熟悉 R", surface_item="R"),
                _atom(
                    role="example",
                    semantic_item="例如 Python",
                    surface_item="Python",
                ),
                _atom(
                    semantic_item="理解 SQL",
                    surface_item="SQL",
                    source_text="理解 SQL",
                ),
            ]
        }
    )

    clauses = compile_flat_atomic_clauses_v4(
        output,
        "熟悉 Python 和 R；理解 SQL",
    )

    assert len(clauses) == 2
    assert clauses[0].items == ["熟悉 Python", "熟悉 R"]
    assert clauses[0].examples == ["例如 Python"]
    assert clauses[1].items == ["理解 SQL"]


def test_grouping_rejects_unlocated_source_and_incomplete_any_of() -> None:
    with pytest.raises(ValueError, match="精确子串"):
        compile_flat_atomic_clauses_v4(
            {"clause_atoms": [_atom(source_text="不存在的证据", surface_item=None)]},
            "熟悉 Python 和 R",
        )
    with pytest.raises(ValidationError, match="any_of"):
        compile_flat_atomic_clauses_v4(
            {
                "clause_atoms": [
                    _atom(
                        relation="any_of",
                        group_name="编程语言",
                    )
                ]
            },
            "熟悉 Python 和 R",
        )


def test_nested_probe_fails_closed_without_category_or_clause_source() -> None:
    classification = classify_nested_v3_without_repair(
        {
            "clauses": [
                {
                    "level": "required",
                    "relation": "all_of",
                    "items": [
                        {
                            "semantic_item": "熟悉 Python",
                            "surface_item": "Python",
                            "source_text": "熟悉 Python",
                        }
                    ],
                }
            ]
        }
    )

    assert classification["accepted_atom_count"] == 0
    assert classification["nonrecoverable_clause_count"] == 1
    assert classification["diagnostics"][0]["missing_fields"] == [
        "category",
        "source_text",
    ]


def test_frozen_dev20_projection_and_all_offline_gates() -> None:
    manifest = _load("unified-jd-model-first-v1-dev20-2026-09-05.json")
    predictions = _load(
        "unified-jd-model-first-v1-dev20-predictions-v1-2026-09-05.json"
    )
    v3_projection = _load(
        "unified-jd-model-first-v3-dev20-layer-projection-2026-09-05.json"
    )
    v3_report = _load("unified-jd-model-first-v3-dev20-report-2026-09-05.json")
    nested_probe = _load(
        "unified-jd-model-first-v3-surface-probe-case121-raw-response-2026-09-05.json"
    )
    projection = build_flat_atomic_v4_projection(
        manifest,
        predictions,
        v3_projection,
    )
    static_audit = audit_flat_atomic_v4_runtime_sources(
        [
            ROOT / "src/domain/unified_jd_flat_atomic_v4.py",
            ROOT / "src/services/unified_jd_flat_atomic_v4.py",
        ]
    )

    report = evaluate_flat_atomic_v4(
        manifest,
        predictions,
        v3_projection,
        v3_report,
        nested_probe,
        projection,
        frozen_inputs_valid=True,
        frozen_sources_valid=True,
        static_audit=static_audit,
        tests_passed=True,
    )

    assert report["passed"] is True
    assert all(gate["passed"] for gate in report["gates"].values())
    assert report["gates"]["G2-flat-group-round-trip"]["primary_item_count"] == 394
    assert report["gates"]["G3-case121-granularity"]["primary_item_count"] == 22
    assert report["gates"]["G4-surface-accounting"] == {
        "passed": True,
        "exact_primary_surface_count": 335,
        "unmapped_primary_surface_count": 59,
    }
    assert report["gates"]["G5-invalid-nested-v3-fails-closed"][
        "accepted_atom_count"
    ] == 0


def _load(name: str) -> dict[str, object]:
    value = json.loads((ARTIFACTS / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value
