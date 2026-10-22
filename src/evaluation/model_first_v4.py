from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.domain.unified_jd_flat_atomic_v4 import (
    UNIFIED_JD_FLAT_ATOMIC_V4_SCHEMA_VERSION,
    UnifiedJDFlatAtomicClausesV4,
    UnifiedJDFlatAtomicClauseV4,
    UnifiedJDGroupedClauseV4,
)
from src.services.unified_jd_flat_atomic_v4 import (
    UNIFIED_JD_FLAT_ATOMIC_V4_COMPILER_VERSION,
    compile_flat_atomic_clauses_v4,
)

MODEL_FIRST_V4_PROJECTION_VERSION = "unified-jd-flat-atomic-v4-projection-v1"
MODEL_FIRST_V4_EVALUATOR_VERSION = "unified-jd-flat-atomic-v4-evaluator-v1"


class FlatAtomicV4CaseRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1, max_length=80)
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    clause_atoms: list[UnifiedJDFlatAtomicClauseV4] = Field(default_factory=list)
    source_valid_clause_count: int = Field(ge=0)
    excluded_clause_indices: list[int] = Field(default_factory=list)
    model_call_count: Literal[0] = 0
    network_call_count: Literal[0] = 0


class FlatAtomicV4ProjectionFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    projection_version: Literal["unified-jd-flat-atomic-v4-projection-v1"] = (
        MODEL_FIRST_V4_PROJECTION_VERSION
    )
    schema_version: Literal["unified-jd-flat-atomic-v4"] = (
        UNIFIED_JD_FLAT_ATOMIC_V4_SCHEMA_VERSION
    )
    compiler_version: Literal["unified-jd-flat-atomic-grouping-compiler-v4"] = (
        UNIFIED_JD_FLAT_ATOMIC_V4_COMPILER_VERSION
    )
    dataset_version: str
    source_prediction_version: str
    source_prediction_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    v3_projection_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    facts_policy: Literal["frozen_v3_layers_by_reference"] = (
        "frozen_v3_layers_by_reference"
    )
    records: list[FlatAtomicV4CaseRecord]

    @model_validator(mode="after")
    def require_unique_cases(self) -> FlatAtomicV4ProjectionFile:
        ids = [record.case_id for record in self.records]
        if len(ids) != len(set(ids)):
            raise ValueError("flat atomic projection case ids must be unique")
        return self


def json_payload_sha256(value: Any) -> str:
    rendered = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def build_flat_atomic_v4_projection(
    manifest: dict[str, Any],
    predictions: dict[str, Any],
    v3_projection: dict[str, Any],
) -> FlatAtomicV4ProjectionFile:
    cases = _records_by_id(manifest, "cases", "id")
    prediction_records = _record_list(predictions, "predictions")
    projection_records = _records_by_id(v3_projection, "records", "case_id")
    expected_ids = list(cases)
    actual_ids = [record.get("case_id") for record in prediction_records]
    if actual_ids != expected_ids or list(projection_records) != expected_ids:
        raise ValueError("manifest, predictions, and V3 projection must align in order")

    records: list[FlatAtomicV4CaseRecord] = []
    for prediction in prediction_records:
        case_id = _required_text(prediction, "case_id")
        case = cases[case_id]
        source_content = _required_text(case, "raw_content")
        input_sha256 = hashlib.sha256(source_content.encode("utf-8")).hexdigest()
        if input_sha256 != case.get("source_content_sha256"):
            raise ValueError(f"manifest input hash mismatch: {case_id}")
        if prediction.get("failure_code") is not None:
            raise ValueError(f"frozen V1 prediction failed: {case_id}")
        if prediction.get("diagnostics", {}).get("input_sha256") != input_sha256:
            raise ValueError(f"prediction input hash mismatch: {case_id}")

        raw_output = _last_raw_model_output(prediction)
        raw_clauses = _record_list(raw_output, "clauses")
        projection_record = projection_records[case_id]
        if projection_record.get("input_sha256") != input_sha256:
            raise ValueError(f"V3 projection input hash mismatch: {case_id}")
        projected_clauses = _record_list(projection_record, "clauses")
        atoms: list[UnifiedJDFlatAtomicClauseV4] = []
        included_indices: set[int] = set()
        for projected_clause in projected_clauses:
            raw_index = projected_clause.get("raw_clause_index")
            if not isinstance(raw_index, int) or not 0 <= raw_index < len(raw_clauses):
                raise ValueError(f"invalid raw clause index: {case_id}")
            included_indices.add(raw_index)
            raw_clause = raw_clauses[raw_index]
            atoms.extend(_flatten_projected_clause(raw_clause, projected_clause))

        excluded_indices = [
            index for index in range(len(raw_clauses)) if index not in included_indices
        ]
        record = FlatAtomicV4CaseRecord(
            case_id=case_id,
            input_sha256=input_sha256,
            raw_output_sha256=json_payload_sha256(raw_output),
            clause_atoms=atoms,
            source_valid_clause_count=len(projected_clauses),
            excluded_clause_indices=excluded_indices,
        )
        compile_flat_atomic_clauses_v4(
            UnifiedJDFlatAtomicClausesV4(clause_atoms=record.clause_atoms),
            source_content,
        )
        records.append(record)

    return FlatAtomicV4ProjectionFile(
        dataset_version=_required_text(manifest, "dataset_version"),
        source_prediction_version=_required_text(predictions, "prediction_version"),
        source_prediction_payload_sha256=json_payload_sha256(predictions),
        v3_projection_payload_sha256=json_payload_sha256(v3_projection),
        records=records,
    )


def classify_nested_v3_without_repair(raw_output: dict[str, Any]) -> dict[str, Any]:
    """Measure direct flattenability without inferring any missing clause field."""

    raw_clauses = raw_output.get("clauses")
    if not isinstance(raw_clauses, list):
        return {
            "clause_count": 0,
            "accepted_clause_count": 0,
            "accepted_atom_count": 0,
            "nonrecoverable_clause_count": 0,
            "diagnostics": [
                {
                    "path": "clauses",
                    "code": "missing_clause_array",
                    "missing_fields": ["clauses"],
                }
            ],
        }

    required_clause_fields = (
        "category",
        "level",
        "relation",
        "source_text",
        "items",
    )
    diagnostics: list[dict[str, Any]] = []
    accepted_clause_count = 0
    accepted_atom_count = 0
    for index, clause in enumerate(raw_clauses):
        if not isinstance(clause, dict):
            diagnostics.append(
                {
                    "path": f"clauses[{index}]",
                    "code": "invalid_clause_object",
                    "missing_fields": list(required_clause_fields),
                }
            )
            continue
        missing = [field for field in required_clause_fields if field not in clause]
        items = clause.get("items")
        if not isinstance(items, list) or not items:
            if "items" not in missing:
                missing.append("items")
        elif any(
            not isinstance(item, dict)
            or "semantic_item" not in item
            or "surface_item" not in item
            for item in items
        ):
            missing.append("items[].semantic_item_or_surface_item")
        if missing:
            diagnostics.append(
                {
                    "path": f"clauses[{index}]",
                    "code": "nonrecoverable_missing_explicit_fields",
                    "missing_fields": missing,
                }
            )
            continue

        candidate_atoms = [
            {
                "role": "item",
                "category": clause["category"],
                "level": clause["level"],
                "relation": clause["relation"],
                "semantic_item": item["semantic_item"],
                "surface_item": item["surface_item"],
                "source_text": clause["source_text"],
                "group_name": clause.get("group_name"),
                "allow_other": clause.get("allow_other", False),
                "qualifier": clause.get("qualifier"),
            }
            for item in items
        ]
        try:
            validated = [
                UnifiedJDFlatAtomicClauseV4.model_validate(atom)
                for atom in candidate_atoms
            ]
        except ValueError as error:
            diagnostics.append(
                {
                    "path": f"clauses[{index}]",
                    "code": "nonrecoverable_invalid_explicit_fields",
                    "missing_fields": [],
                    "message": str(error),
                }
            )
            continue
        accepted_clause_count += 1
        accepted_atom_count += len(validated)

    return {
        "clause_count": len(raw_clauses),
        "accepted_clause_count": accepted_clause_count,
        "accepted_atom_count": accepted_atom_count,
        "nonrecoverable_clause_count": len(raw_clauses) - accepted_clause_count,
        "diagnostics": diagnostics,
    }


def audit_flat_atomic_v4_runtime_sources(paths: list[Path]) -> dict[str, Any]:
    forbidden_import = re.compile(
        r"(?m)^\s*(?:from|import)\s+"
        r"(?:httpx|requests|urllib|socket|openai|src\.infrastructure\.llm_client|"
        r"src\.domain\.unified_jd_canonicalizer)\b"
    )
    fixture_id = re.compile(r"(?:campus-ai|structured-|surface-holdout|canonical-v1)-")
    violations: list[dict[str, str]] = []
    for path in paths:
        source = path.read_text(encoding="utf-8")
        if forbidden_import.search(source):
            violations.append({"path": path.as_posix(), "code": "forbidden_import"})
        if fixture_id.search(source):
            violations.append({"path": path.as_posix(), "code": "fixture_id_literal"})
    return {
        "passed": not violations,
        "checked_paths": [path.as_posix() for path in paths],
        "violations": violations,
    }


def evaluate_flat_atomic_v4(
    manifest: dict[str, Any],
    predictions: dict[str, Any],
    v3_projection: dict[str, Any],
    v3_report: dict[str, Any],
    nested_v3_probe_raw: dict[str, Any],
    projection: FlatAtomicV4ProjectionFile,
    *,
    frozen_inputs_valid: bool,
    frozen_sources_valid: bool,
    static_audit: dict[str, Any],
    tests_passed: bool,
) -> dict[str, Any]:
    expected_projection = build_flat_atomic_v4_projection(
        manifest, predictions, v3_projection
    )
    deterministic_rebuild = projection == expected_projection
    cases = _records_by_id(manifest, "cases", "id")
    prediction_records = _records_by_id(predictions, "predictions", "case_id")
    projected_records = _records_by_id(v3_projection, "records", "case_id")

    round_trip_case_count = 0
    round_trip_clause_count = 0
    per_case: list[dict[str, Any]] = []
    for record in projection.records:
        source_content = _required_text(cases[record.case_id], "raw_content")
        actual = compile_flat_atomic_clauses_v4(
            UnifiedJDFlatAtomicClausesV4(clause_atoms=record.clause_atoms),
            source_content,
        )
        raw_output = _last_raw_model_output(prediction_records[record.case_id])
        raw_clauses = _record_list(raw_output, "clauses")
        expected = [
            _expected_clause(raw_clauses, clause)
            for clause in _record_list(projected_records[record.case_id], "clauses")
        ]
        exact = actual == expected
        round_trip_case_count += int(exact)
        round_trip_clause_count += len(actual) if exact else 0
        per_case.append(
            {
                "case_id": record.case_id,
                "atom_count": len(record.clause_atoms),
                "primary_item_count": sum(
                    atom.role == "item" for atom in record.clause_atoms
                ),
                "example_item_count": sum(
                    atom.role == "example" for atom in record.clause_atoms
                ),
                "compiled_clause_count": len(actual),
                "round_trip_exact": exact,
                "excluded_clause_indices": record.excluded_clause_indices,
            }
        )

    primary_atoms = [
        atom
        for record in projection.records
        for atom in record.clause_atoms
        if atom.role == "item"
    ]
    example_atoms = [
        atom
        for record in projection.records
        for atom in record.clause_atoms
        if atom.role == "example"
    ]
    surface_counts = Counter(
        "exact" if atom.surface_item is not None else "unmapped"
        for atom in primary_atoms
    )
    all_sources_exact = all(
        atom.source_text in _required_text(cases[record.case_id], "raw_content")
        for record in projection.records
        for atom in record.clause_atoms
    )
    all_surfaces_exact_or_null = all(
        atom.surface_item is None or atom.surface_item in atom.source_text
        for record in projection.records
        for atom in record.clause_atoms
    )
    case121_primary_count = next(
        item["primary_item_count"]
        for item in per_case
        if item["case_id"] == "campus-ai-121"
    )
    nested_raw_output = nested_v3_probe_raw.get("raw_model_output")
    if not isinstance(nested_raw_output, dict):
        raise TypeError("nested V3 probe is missing raw_model_output")
    nested_classification = classify_nested_v3_without_repair(nested_raw_output)

    derived_facts = v3_report["stages"]["derived"]
    fact_layers = v3_report["layers"]["facts"]
    fact_gate_exact = (
        derived_facts["facts"]["macro_f1"] == 0.9794292663857882
        and derived_facts["facts"]["fields"]["major_requirements"]["f1"]
        == 0.9743589743589742
        and fact_layers["raw_item_count"] == 155
        and fact_layers["exact_surface_count"] == 149
        and fact_layers["unmapped_surface_count"] == 6
        and derived_facts["hard_checks"]["no_source_unsupported_critical_facts"]
    )

    gates = {
        "G0-frozen-inputs-and-zero-calls": {
            "passed": frozen_inputs_valid
            and frozen_sources_valid
            and sum(record.model_call_count for record in projection.records) == 0
            and sum(record.network_call_count for record in projection.records) == 0,
            "frozen_inputs_valid": frozen_inputs_valid,
            "frozen_sources_valid": frozen_sources_valid,
            "model_call_count": 0,
            "network_call_count": 0,
        },
        "G1-contract-and-source-validity": {
            "passed": deterministic_rebuild
            and all_sources_exact
            and all_surfaces_exact_or_null
            and surface_counts["unmapped"] == 59,
            "deterministic_rebuild": deterministic_rebuild,
            "all_sources_exact": all_sources_exact,
            "all_surfaces_exact_or_null": all_surfaces_exact_or_null,
            "unmapped_primary_surface_count": surface_counts["unmapped"],
        },
        "G2-flat-group-round-trip": {
            "passed": round_trip_case_count == 20
            and round_trip_clause_count == 171
            and len(primary_atoms) == 394
            and len(example_atoms) == 33,
            "round_trip_exact_case_count": round_trip_case_count,
            "round_trip_exact_clause_count": round_trip_clause_count,
            "primary_item_count": len(primary_atoms),
            "example_item_count": len(example_atoms),
        },
        "G3-case121-granularity": {
            "passed": case121_primary_count == 22 and case121_primary_count != 8,
            "primary_item_count": case121_primary_count,
            "required": 22,
            "forbidden_collapsed_count": 8,
        },
        "G4-surface-accounting": {
            "passed": surface_counts["exact"] == 335
            and surface_counts["unmapped"] == 59,
            "exact_primary_surface_count": surface_counts["exact"],
            "unmapped_primary_surface_count": surface_counts["unmapped"],
        },
        "G5-invalid-nested-v3-fails-closed": {
            "passed": nested_classification["clause_count"] == 3
            and nested_classification["nonrecoverable_clause_count"] == 3
            and nested_classification["accepted_atom_count"] == 0
            and sum(
                "category" in item.get("missing_fields", [])
                for item in nested_classification["diagnostics"]
            )
            == 3,
            **nested_classification,
        },
        "G6-v3-facts-unchanged": {
            "passed": fact_gate_exact,
            "derived_facts_macro_f1": derived_facts["facts"]["macro_f1"],
            "derived_major_f1": derived_facts["facts"]["fields"][
                "major_requirements"
            ]["f1"],
            "fact_raw_item_count": fact_layers["raw_item_count"],
            "fact_exact_surface_count": fact_layers["exact_surface_count"],
            "fact_unmapped_surface_count": fact_layers["unmapped_surface_count"],
            "source_unsupported_critical_fact_count": 0
            if derived_facts["hard_checks"][
                "no_source_unsupported_critical_facts"
            ]
            else 1,
        },
        "G7-isolation-and-static-audit": {
            "passed": bool(static_audit.get("passed")) and tests_passed,
            "static_audit": static_audit,
            "tests_passed": tests_passed,
        },
    }
    return {
        "evaluation_version": MODEL_FIRST_V4_EVALUATOR_VERSION,
        "dataset_version": projection.dataset_version,
        "case_count": len(projection.records),
        "passed": all(gate["passed"] for gate in gates.values()),
        "model_api_called": False,
        "model_call_count": 0,
        "network_call_count": 0,
        "canonicalizer_called": False,
        "gates": gates,
        "per_case": per_case,
    }


def _flatten_projected_clause(
    raw_clause: dict[str, Any],
    projected_clause: dict[str, Any],
) -> list[UnifiedJDFlatAtomicClauseV4]:
    category = _required_text(projected_clause, "category")
    level = _required_text(projected_clause, "level")
    relation = _required_text(projected_clause, "relation")
    evidence = projected_clause.get("evidence")
    if not isinstance(evidence, dict):
        raise TypeError("projected clause evidence must be an object")
    source_text = _required_text(evidence, "source_text")
    for field, value in (
        ("category", category),
        ("level", level),
        ("relation", relation),
        ("source_text", source_text),
    ):
        if raw_clause.get(field, "all_of" if field == "relation" else None) != value:
            raise ValueError(f"raw and projected clause disagree on {field}")

    atoms: list[UnifiedJDFlatAtomicClauseV4] = []
    for role, field in (("item", "items"), ("example", "examples")):
        projected_items = projected_clause.get(field)
        if not isinstance(projected_items, list):
            raise TypeError(f"projected clause {field} must be a list")
        raw_items = raw_clause.get(field) or []
        if [item.get("raw_item") for item in projected_items] != raw_items:
            raise ValueError(f"raw and projected clause disagree on {field}")
        for item in projected_items:
            surface_status = item.get("surface_status")
            if surface_status not in {"exact", "unmapped"}:
                raise ValueError("unknown surface status")
            surface_item = item.get("surface_item") if surface_status == "exact" else None
            if surface_status == "unmapped" and item.get("surface_item") is not None:
                raise ValueError("unmapped projected item unexpectedly carries a surface")
            atoms.append(
                UnifiedJDFlatAtomicClauseV4(
                    role=role,
                    category=category,
                    level=level,
                    relation=relation,
                    semantic_item=_required_text(item, "raw_item"),
                    surface_item=surface_item,
                    source_text=source_text,
                    group_name=raw_clause.get("group_name"),
                    allow_other=bool(raw_clause.get("allow_other", False)),
                    qualifier=raw_clause.get("qualifier"),
                )
            )
    return atoms


def _expected_clause(
    raw_clauses: list[dict[str, Any]],
    projected_clause: dict[str, Any],
) -> UnifiedJDGroupedClauseV4:
    raw_index = projected_clause["raw_clause_index"]
    raw_clause = raw_clauses[raw_index]
    evidence = projected_clause["evidence"]
    return UnifiedJDGroupedClauseV4(
        category=projected_clause["category"],
        level=projected_clause["level"],
        relation=projected_clause["relation"],
        items=[item["raw_item"] for item in projected_clause["items"]],
        examples=[item["raw_item"] for item in projected_clause["examples"]] or None,
        group_name=raw_clause.get("group_name"),
        allow_other=bool(raw_clause.get("allow_other", False)),
        qualifier=raw_clause.get("qualifier"),
        source_text=evidence["source_text"],
    )


def _record_list(value: dict[str, Any], key: str) -> list[dict[str, Any]]:
    records = value.get(key)
    if not isinstance(records, list) or any(
        not isinstance(record, dict) for record in records
    ):
        raise TypeError(f"{key} must be a list of objects")
    return records


def _records_by_id(
    value: dict[str, Any],
    key: str,
    id_key: str,
) -> dict[str, dict[str, Any]]:
    records = _record_list(value, key)
    result: dict[str, dict[str, Any]] = {}
    for record in records:
        record_id = _required_text(record, id_key)
        if record_id in result:
            raise ValueError(f"duplicate {id_key}: {record_id}")
        result[record_id] = record
    return result


def _last_raw_model_output(prediction: dict[str, Any]) -> dict[str, Any]:
    diagnostics = prediction.get("diagnostics")
    attempts = diagnostics.get("model_attempts") if isinstance(diagnostics, dict) else None
    if not isinstance(attempts, list) or not attempts:
        raise ValueError(f"missing model attempts: {prediction.get('case_id')}")
    raw_output = attempts[-1].get("raw_model_output")
    if not isinstance(raw_output, dict):
        raise TypeError(f"missing raw model output: {prediction.get('case_id')}")
    return raw_output


def _required_text(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"missing non-empty {key}")
    return item
