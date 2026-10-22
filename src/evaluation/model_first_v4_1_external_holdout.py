from __future__ import annotations

import copy
from typing import Any

from src.evaluation.model_first_v4_1_compatibility import (
    evaluate_live_probe_v4_1,
    normalize_live_probe_raw_responses_v4_1,
)
from src.evaluation.model_first_v4_live_probe import evaluate_live_probe_v4

EXTERNAL_HOLDOUT_EVALUATOR_VERSION = (
    "unified-jd-flat-atomic-v4.1-external-holdout-evaluator-v1"
)


def evaluate_external_holdout_v4_1(
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
    baseline = evaluate_live_probe_v4(
        selection,
        preregistration,
        raw_responses,
        authorization_confirmed=authorization_confirmed,
        destination_valid=destination_valid,
        frozen_inputs_valid=frozen_inputs_valid,
        frozen_sources_valid=frozen_sources_valid,
        gold_unavailable_to_requests=gold_unavailable_to_requests,
    )
    normalized_raw, audit = normalize_live_probe_raw_responses_v4_1(raw_responses)
    normalized = evaluate_live_probe_v4_1(
        selection,
        preregistration,
        raw_responses,
        frozen_inputs_valid=frozen_inputs_valid,
        frozen_sources_valid=frozen_sources_valid,
    )

    selected_ids = selection["selected_case_ids"]
    raw_records = _record_map(raw_responses)
    normalized_records = _record_map(normalized_raw)
    baseline_cases = {item["case_id"]: item for item in baseline["per_case"]}
    normalized_cases = {item["case_id"]: item for item in normalized["per_case"]}
    audit_by_case = {item["case_id"]: item for item in audit}
    activated_case_ids = [
        case_id for case_id in selected_ids if case_id in audit_by_case
    ]
    unactivated_case_ids = [
        case_id for case_id in selected_ids if case_id not in audit_by_case
    ]

    exact_audit = _audit_is_exact(
        raw_records,
        normalized_records,
        audit,
    )
    reverse_restores_raw = _reverse_transform(normalized_raw, audit) == raw_responses
    unactivated_equal = all(
        raw_records[case_id]["raw_model_output"]
        == normalized_records[case_id]["raw_model_output"]
        for case_id in unactivated_case_ids
    )
    activated_alias_only = all(
        _has_only_alias_schema_errors(
            baseline_cases[case_id],
            audit_by_case[case_id],
        )
        for case_id in activated_case_ids
    )
    activated_recovered = all(
        not baseline_cases[case_id]["schema_valid"]
        and normalized_cases[case_id]["schema_valid"]
        for case_id in activated_case_ids
    )

    total_calls = sum(
        int(raw_records.get(case_id, {}).get("model_call_count") or 0)
        for case_id in selected_ids
    )
    exact_case_set = set(raw_records) == set(selected_ids)
    one_call_each = exact_case_set and all(
        raw_records[case_id].get("model_call_count") == 1 for case_id in selected_ids
    )
    standard_gates = normalized["gates"]
    gates = {
        "G0-authorization-destination-and-budget": {
            "passed": (
                authorization_confirmed
                and destination_valid
                and total_calls == 5
                and one_call_each
            ),
            "authorization_confirmed": authorization_confirmed,
            "destination_valid": destination_valid,
            "model_call_count": total_calls,
            "required_model_call_count": 5,
            "maximum_model_call_count": 5,
            "one_call_each": one_call_each,
            "exact_case_set": exact_case_set,
        },
        "G1-json-and-root-topology": standard_gates["G1-json-and-root-topology"],
        "G2-compatibility-intervention-integrity": {
            "passed": exact_audit and reverse_restores_raw and unactivated_equal,
            "exact_allowed_changes_only": exact_audit,
            "reverse_transform_restores_raw": reverse_restores_raw,
            "unactivated_records_equal": unactivated_equal,
            "activation_count": sum(len(item["diagnostics"]) for item in audit),
            "activated_case_ids": activated_case_ids,
            "audit": audit,
        },
        "G3-source-and-surface-anchoring": standard_gates[
            "G3-source-and-surface-anchoring"
        ],
        "G4-semantic-surface-separation": standard_gates[
            "G4-semantic-surface-separation"
        ],
        "G5-granularity-noncollapse": standard_gates["G5-granularity-noncollapse"],
        "G6-fact-layer-compatibility": standard_gates["G6-fact-layer-compatibility"],
        "G7-isolation-and-preservation": {
            **standard_gates["G7-isolation-and-preservation"],
            "passed": (
                standard_gates["G7-isolation-and-preservation"]["passed"]
                and gold_unavailable_to_requests
            ),
        },
    }
    base_passed = all(gate["passed"] for gate in gates.values())
    activation_count = gates["G2-compatibility-intervention-integrity"][
        "activation_count"
    ]
    confirmed = (
        base_passed
        and activation_count > 0
        and activated_alias_only
        and activated_recovered
    )
    supported_non_regression_only = (
        base_passed
        and activation_count == 0
        and baseline["passed"]
        and normalized_raw == raw_responses
    )
    if confirmed:
        decision = "confirmed"
    elif supported_non_regression_only:
        decision = "supported_non_regression_only"
    else:
        decision = "failed"

    causal_gate = {
        "passed": decision in {"confirmed", "supported_non_regression_only"},
        "decision": decision,
        "activation_count": activation_count,
        "activated_case_count": len(activated_case_ids),
        "activated_case_ids": activated_case_ids,
        "activated_cases_have_only_eligible_alias_errors": activated_alias_only,
        "activated_cases_recovered": activated_recovered,
        "baseline_schema_valid_case_count": baseline["gates"][
            "G1-json-and-root-topology"
        ]["schema_valid_case_count"],
        "v4_1_schema_valid_case_count": normalized["gates"][
            "G1-json-and-root-topology"
        ]["schema_valid_case_count"],
    }
    gates["G8-causal-generalization-decision"] = causal_gate
    failed_gates = [name for name, gate in gates.items() if not gate["passed"]]
    return {
        "evaluation_version": EXTERNAL_HOLDOUT_EVALUATOR_VERSION,
        "case_count": len(selected_ids),
        "passed": causal_gate["passed"],
        "decision": decision,
        "failed_gates": failed_gates,
        "model_call_count": total_calls,
        "network_call_count": total_calls,
        "new_model_calls_for_v4_1": 0,
        "gates": gates,
        "baseline_v4": baseline,
        "v4_1": normalized,
    }


def _record_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    records = payload.get("records")
    if not isinstance(records, list):
        raise TypeError("raw response records must be a list")
    result: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("case_id"), str):
            raise TypeError("raw response record requires case_id")
        case_id = record["case_id"]
        if case_id in result:
            raise ValueError(f"duplicate raw response case_id: {case_id}")
        result[case_id] = record
    return result


def _audit_is_exact(
    raw_records: dict[str, dict[str, Any]],
    normalized_records: dict[str, dict[str, Any]],
    audit: list[dict[str, Any]],
) -> bool:
    for record_audit in audit:
        case_id = record_audit.get("case_id")
        if case_id not in raw_records or case_id not in normalized_records:
            return False
        raw_output = raw_records[case_id].get("raw_model_output")
        normalized_output = normalized_records[case_id].get("raw_model_output")
        if not isinstance(raw_output, dict) or not isinstance(normalized_output, dict):
            return False
        raw_atoms = raw_output.get("clause_atoms")
        normalized_atoms = normalized_output.get("clause_atoms")
        if not isinstance(raw_atoms, list) or not isinstance(normalized_atoms, list):
            return False
        for diagnostic in record_audit.get("diagnostics", []):
            index = diagnostic.get("atom_index")
            if not isinstance(index, int) or index >= len(raw_atoms):
                return False
            raw_atom = raw_atoms[index]
            normalized_atom = normalized_atoms[index]
            expected = {
                "path": f"clause_atoms[{index}].role",
                "atom_index": index,
                "code": "normalized_responsibility_role_alias",
                "before_role": "responsibility",
                "after_role": "item",
            }
            if diagnostic != expected:
                return False
            if not isinstance(raw_atom, dict) or not isinstance(normalized_atom, dict):
                return False
            if not (
                raw_atom.get("role") == "responsibility"
                and raw_atom.get("category") == "responsibility"
                and raw_atom.get("level") == "mention"
                and normalized_atom.get("role") == "item"
            ):
                return False
            expected_atom = {**raw_atom, "role": "item"}
            if normalized_atom != expected_atom:
                return False
    return True


def _reverse_transform(
    normalized_raw: dict[str, Any],
    audit: list[dict[str, Any]],
) -> dict[str, Any]:
    restored = copy.deepcopy(normalized_raw)
    records = restored["records"]
    for record_audit in audit:
        record = records[record_audit["record_index"]]
        for diagnostic in record_audit["diagnostics"]:
            record["raw_model_output"]["clause_atoms"][diagnostic["atom_index"]][
                "role"
            ] = diagnostic["before_role"]
    return restored


def _has_only_alias_schema_errors(
    baseline_case: dict[str, Any],
    case_audit: dict[str, Any],
) -> bool:
    expected_paths = {
        diagnostic["path"].replace("[", ".").replace("]", "")
        for diagnostic in case_audit["diagnostics"]
    }
    diagnostics = baseline_case.get("diagnostics", [])
    return bool(diagnostics) and all(
        diagnostic.get("path") in expected_paths
        and diagnostic.get("code") == "literal_error"
        for diagnostic in diagnostics
    )
