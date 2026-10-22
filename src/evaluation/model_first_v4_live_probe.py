from __future__ import annotations

from collections import Counter
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from src.domain.unified_jd import validate_unified_jd_evidence
from src.domain.unified_jd_extraction import UnifiedFactMentionV2
from src.domain.unified_jd_flat_atomic_v4 import UnifiedJDFlatAtomicClauseV4
from src.services.unified_jd_extraction import (
    compile_model_first_normalized_extraction_v3,
    compile_unified_extraction_v2,
)

LIVE_PROBE_RESPONSE_SCHEMA_VERSION = "unified-jd-flat-atomic-v4-live-response-v1"
LIVE_PROBE_EVALUATOR_VERSION = "unified-jd-flat-atomic-v4-live-evaluator-v1"

FACT_FIELDS = {"field", "raw_items", "level", "source_text"}
ATOM_FIELDS = {
    "role",
    "category",
    "level",
    "relation",
    "semantic_item",
    "surface_item",
    "source_text",
    "group_name",
    "allow_other",
    "qualifier",
}
ROOT_FIELDS = {"fact_mentions", "clause_atoms"}


class UnifiedJDFlatAtomicLiveResponseV4(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fact_mentions: list[UnifiedFactMentionV2]
    clause_atoms: list[UnifiedJDFlatAtomicClauseV4]


def analyze_live_response_v4(
    raw_output: object,
    source_content: str,
) -> dict[str, Any]:
    diagnostics: list[dict[str, Any]] = []
    if not isinstance(raw_output, dict):
        return _invalid_analysis("response", "root_not_object")

    root_keys_exact = set(raw_output) == ROOT_FIELDS
    if not root_keys_exact:
        diagnostics.append(
            {
                "path": "response",
                "code": "root_fields_not_exact",
                "actual": sorted(raw_output),
                "expected": sorted(ROOT_FIELDS),
            }
        )
    raw_facts = raw_output.get("fact_mentions")
    raw_atoms = raw_output.get("clause_atoms")
    fact_array_valid = isinstance(raw_facts, list)
    atom_array_valid = isinstance(raw_atoms, list)
    if not fact_array_valid:
        diagnostics.append({"path": "fact_mentions", "code": "not_array"})
        raw_facts = []
    if not atom_array_valid:
        diagnostics.append({"path": "clause_atoms", "code": "not_array"})
        raw_atoms = []

    fact_fields_exact = True
    for index, fact in enumerate(raw_facts):
        if not isinstance(fact, dict) or set(fact) != FACT_FIELDS:
            fact_fields_exact = False
            diagnostics.append(
                {
                    "path": f"fact_mentions[{index}]",
                    "code": "fact_fields_not_exact",
                    "actual": sorted(fact) if isinstance(fact, dict) else None,
                    "expected": sorted(FACT_FIELDS),
                }
            )

    atom_fields_exact = True
    no_nested_clause_fields = True
    for index, atom in enumerate(raw_atoms):
        if not isinstance(atom, dict) or set(atom) != ATOM_FIELDS:
            atom_fields_exact = False
            diagnostics.append(
                {
                    "path": f"clause_atoms[{index}]",
                    "code": "atom_fields_not_exact",
                    "actual": sorted(atom) if isinstance(atom, dict) else None,
                    "expected": sorted(ATOM_FIELDS),
                }
            )
        if isinstance(atom, dict) and any(
            key in atom for key in ("items", "examples", "clauses")
        ):
            no_nested_clause_fields = False

    parsed: UnifiedJDFlatAtomicLiveResponseV4 | None = None
    try:
        parsed = UnifiedJDFlatAtomicLiveResponseV4.model_validate(raw_output)
    except ValidationError as error:
        diagnostics.extend(
            {
                "path": ".".join(str(part) for part in item["loc"]),
                "code": item["type"],
                "message": item["msg"],
            }
            for item in error.errors()
        )

    schema_valid = bool(
        root_keys_exact
        and fact_array_valid
        and atom_array_valid
        and fact_fields_exact
        and atom_fields_exact
        and no_nested_clause_fields
        and parsed is not None
    )
    if parsed is None:
        return {
            "schema_valid": False,
            "root_keys_exact": root_keys_exact,
            "fact_fields_exact": fact_fields_exact,
            "atom_fields_exact": atom_fields_exact,
            "no_nested_clause_fields": no_nested_clause_fields,
            "fact_mention_count": len(raw_facts),
            "atom_count": len(raw_atoms),
            "primary_atom_count": 0,
            "example_atom_count": 0,
            "source_text_count": 0,
            "located_source_text_count": 0,
            "nonnull_primary_surface_count": 0,
            "located_nonnull_primary_surface_count": 0,
            "separated_pair_count": 0,
            "has_separated_pair": False,
            "fact_layer_compatible": False,
            "fact_compilation_diagnostics": [],
            "diagnostics": diagnostics,
        }

    atoms = parsed.clause_atoms
    primary_atoms = [atom for atom in atoms if atom.role == "item"]
    example_atoms = [atom for atom in atoms if atom.role == "example"]
    source_texts = [mention.source_text for mention in parsed.fact_mentions]
    source_texts.extend(atom.source_text for atom in atoms)
    located_source_count = sum(text in source_content for text in source_texts)
    nonnull_primary = [atom for atom in primary_atoms if atom.surface_item is not None]
    located_nonnull = sum(
        atom.surface_item in atom.source_text
        for atom in nonnull_primary
        if atom.surface_item is not None
    )
    separated = sum(
        atom.surface_item is not None and atom.semantic_item != atom.surface_item
        for atom in primary_atoms
    )
    fact_compatible, fact_diagnostics = _fact_layer_compatibility(
        parsed.fact_mentions,
        source_content,
    )
    return {
        "schema_valid": schema_valid,
        "root_keys_exact": root_keys_exact,
        "fact_fields_exact": fact_fields_exact,
        "atom_fields_exact": atom_fields_exact,
        "no_nested_clause_fields": no_nested_clause_fields,
        "fact_mention_count": len(parsed.fact_mentions),
        "atom_count": len(atoms),
        "primary_atom_count": len(primary_atoms),
        "example_atom_count": len(example_atoms),
        "source_text_count": len(source_texts),
        "located_source_text_count": located_source_count,
        "nonnull_primary_surface_count": len(nonnull_primary),
        "located_nonnull_primary_surface_count": located_nonnull,
        "separated_pair_count": separated,
        "has_separated_pair": separated > 0,
        "fact_layer_compatible": fact_compatible,
        "fact_compilation_diagnostics": fact_diagnostics,
        "diagnostics": diagnostics,
    }


def evaluate_live_probe_v4(
    selection: dict[str, Any],
    preregistration: dict[str, Any],
    raw_responses: dict[str, Any],
    *,
    authorization_confirmed: bool,
    destination_valid: bool,
    frozen_inputs_valid: bool,
    frozen_sources_valid: bool,
    gold_unavailable_to_requests: bool,
) -> dict[str, Any]:
    selection_cases = _case_map(selection)
    selected_ids = selection["selected_case_ids"]
    response_records = raw_responses.get("records")
    if not isinstance(response_records, list):
        raise TypeError("raw response records must be a list")
    records_by_id: dict[str, dict[str, Any]] = {}
    duplicate_case_ids: list[str] = []
    for record in response_records:
        if not isinstance(record, dict) or not isinstance(record.get("case_id"), str):
            raise TypeError("raw response record requires a case_id")
        case_id = record["case_id"]
        if case_id in records_by_id:
            duplicate_case_ids.append(case_id)
        records_by_id[case_id] = record

    per_case: list[dict[str, Any]] = []
    for case_id in selected_ids:
        case = selection_cases[case_id]
        record = records_by_id.get(case_id)
        if record is None:
            analysis = _invalid_analysis("response", "missing_response_record")
            call_count = 0
            failure_code = "not_attempted"
        else:
            analysis = analyze_live_response_v4(
                record.get("raw_model_output"),
                case["raw_content"],
            )
            call_count = int(record.get("model_call_count") or 0)
            failure_code = record.get("failure_code")
        per_case.append(
            {
                "case_id": case_id,
                "call_count": call_count,
                "failure_code": failure_code,
                **analysis,
            }
        )

    total_calls = sum(item["call_count"] for item in per_case)
    schema_valid_count = sum(item["schema_valid"] for item in per_case)
    shape_valid_count = sum(
        item["atom_fields_exact"] and item["no_nested_clause_fields"]
        for item in per_case
    )
    source_total = sum(item["source_text_count"] for item in per_case)
    source_located = sum(item["located_source_text_count"] for item in per_case)
    surface_total = sum(item["nonnull_primary_surface_count"] for item in per_case)
    surface_located = sum(
        item["located_nonnull_primary_surface_count"] for item in per_case
    )
    primary_total = sum(item["primary_atom_count"] for item in per_case)
    separated_total = sum(item["separated_pair_count"] for item in per_case)
    separated_cases = sum(item["has_separated_pair"] for item in per_case)
    fact_compatible_count = sum(item["fact_layer_compatible"] for item in per_case)
    nonnull_surface_rate = surface_total / primary_total if primary_total else 0.0
    source_localization_rate = source_located / source_total if source_total else 0.0
    surface_localization_rate = surface_located / surface_total if surface_total else 0.0

    per_case_minimums = preregistration["acceptance_gates"][
        "G5-granularity-noncollapse"
    ]["per_case_minimums"]
    per_case_granularity = {
        item["case_id"]: {
            "actual": item["primary_atom_count"],
            "minimum": per_case_minimums[item["case_id"]],
            "passed": item["primary_atom_count"]
            >= per_case_minimums[item["case_id"]],
        }
        for item in per_case
    }
    granularity_gate = preregistration["acceptance_gates"][
        "G5-granularity-noncollapse"
    ]
    minimum_total = granularity_gate["minimum_aggregate_primary_atom_count"]
    maximum_total = granularity_gate["maximum_aggregate_primary_atom_count"]

    gates = {
        "G0-authorization-destination-and-budget": {
            "passed": authorization_confirmed
            and destination_valid
            and not duplicate_case_ids
            and total_calls <= 5
            and all(item["call_count"] <= 1 for item in per_case),
            "authorization_confirmed": authorization_confirmed,
            "destination_valid": destination_valid,
            "model_call_count": total_calls,
            "maximum_model_call_count": 5,
            "duplicate_case_ids": duplicate_case_ids,
        },
        "G1-json-and-root-topology": {
            "passed": schema_valid_count == 5,
            "schema_valid_case_count": schema_valid_count,
            "required": 5,
        },
        "G2-flat-atom-shape": {
            "passed": shape_valid_count == 5,
            "shape_valid_case_count": shape_valid_count,
            "required": 5,
        },
        "G3-source-and-surface-anchoring": {
            "passed": source_localization_rate == 1.0
            and surface_localization_rate == 1.0
            and nonnull_surface_rate >= 0.80,
            "source_text_localization_rate": source_localization_rate,
            "nonnull_surface_localization_rate": surface_localization_rate,
            "nonnull_primary_surface_rate": nonnull_surface_rate,
            "minimum_nonnull_primary_surface_rate": 0.80,
        },
        "G4-semantic-surface-separation": {
            "passed": separated_total >= 5 and separated_cases >= 2,
            "separated_pair_count": separated_total,
            "minimum_separated_pair_count": 5,
            "cases_with_a_separated_pair": separated_cases,
            "minimum_cases_with_a_separated_pair": 2,
        },
        "G5-granularity-noncollapse": {
            "passed": minimum_total <= primary_total <= maximum_total
            and all(item["passed"] for item in per_case_granularity.values()),
            "primary_atom_count": primary_total,
            "minimum_aggregate_primary_atom_count": minimum_total,
            "maximum_aggregate_primary_atom_count": maximum_total,
            "per_case": per_case_granularity,
        },
        "G6-fact-layer-compatibility": {
            "passed": fact_compatible_count == 5,
            "compatible_case_count": fact_compatible_count,
            "required": 5,
        },
        "G7-isolation-and-preservation": {
            "passed": frozen_inputs_valid
            and frozen_sources_valid
            and gold_unavailable_to_requests,
            "frozen_inputs_valid": frozen_inputs_valid,
            "frozen_sources_valid": frozen_sources_valid,
            "gold_unavailable_to_requests": gold_unavailable_to_requests,
            "canonicalizer_called": False,
            "default_parser_called": False,
        },
    }
    return {
        "evaluation_version": LIVE_PROBE_EVALUATOR_VERSION,
        "response_schema_version": LIVE_PROBE_RESPONSE_SCHEMA_VERSION,
        "case_count": len(selected_ids),
        "passed": all(gate["passed"] for gate in gates.values()),
        "model_call_count": total_calls,
        "network_call_count": total_calls,
        "canonicalizer_called": False,
        "default_parser_called": False,
        "gates": gates,
        "failure_codes": dict(
            Counter(
                item["failure_code"]
                for item in per_case
                if item["failure_code"] is not None
            )
        ),
        "per_case": per_case,
    }


def _fact_layer_compatibility(
    fact_mentions: list[UnifiedFactMentionV2],
    source_content: str,
) -> tuple[bool, list[dict[str, Any]]]:
    payload = {
        "fact_mentions": [item.model_dump(mode="json") for item in fact_mentions],
        "clauses": [],
    }
    diagnostics: list[dict[str, Any]] = []
    try:
        normalized = compile_model_first_normalized_extraction_v3(
            payload, source_content
        )
        derived = compile_unified_extraction_v2(payload, source_content)
        validate_unified_jd_evidence(normalized.output, source_content)
        validate_unified_jd_evidence(derived.output, source_content)
    except (TypeError, ValueError, ValidationError) as error:
        return False, [{"code": "fact_compilation_failed", "message": str(error)}]
    for stage, compilation in (("normalized", normalized), ("derived", derived)):
        for item in compilation.diagnostics:
            diagnostic = {"stage": stage, **item.as_dict()}
            diagnostics.append(diagnostic)
    unsupported = [
        item for item in diagnostics if item["code"] == "unsupported_evidence"
    ]
    return not unsupported, diagnostics


def _case_map(selection: dict[str, Any]) -> dict[str, dict[str, Any]]:
    cases = selection.get("cases")
    if not isinstance(cases, list):
        raise TypeError("selection cases must be a list")
    result: dict[str, dict[str, Any]] = {}
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("case_id"), str):
            raise TypeError("selection case requires case_id")
        result[case["case_id"]] = case
    if list(result) != selection.get("selected_case_ids"):
        raise ValueError("selection case order does not match selected_case_ids")
    return result


def _invalid_analysis(path: str, code: str) -> dict[str, Any]:
    return {
        "schema_valid": False,
        "root_keys_exact": False,
        "fact_fields_exact": False,
        "atom_fields_exact": False,
        "no_nested_clause_fields": False,
        "fact_mention_count": 0,
        "atom_count": 0,
        "primary_atom_count": 0,
        "example_atom_count": 0,
        "source_text_count": 0,
        "located_source_text_count": 0,
        "nonnull_primary_surface_count": 0,
        "located_nonnull_primary_surface_count": 0,
        "separated_pair_count": 0,
        "has_separated_pair": False,
        "fact_layer_compatible": False,
        "fact_compilation_diagnostics": [],
        "diagnostics": [{"path": path, "code": code}],
    }
