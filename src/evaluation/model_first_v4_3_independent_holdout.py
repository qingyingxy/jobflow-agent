from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from datetime import datetime
from typing import Any

from src.evaluation.model_first_v4_live_probe import evaluate_live_probe_v4
from src.services.unified_jd_flat_atomic_v4_2_compatibility import (
    DIAGNOSTIC_CODES,
    EMPTY_FACT_CODE,
    normalize_flat_atomic_v4_2_wire_output,
)
from src.services.unified_jd_flat_atomic_v4_3_compatibility import (
    normalize_flat_atomic_v4_3_wire_output,
    restore_flat_atomic_v4_3_wire_output,
)

INDEPENDENT_HOLDOUT_EVALUATOR_VERSION = (
    "unified-jd-flat-atomic-v4.3-independent-holdout-evaluator-v1"
)


def evaluate_independent_holdout_v4_3(
    selection: dict[str, Any],
    preregistration: dict[str, Any],
    requests_artifact: dict[str, Any],
    checkpoint: dict[str, Any],
    raw_responses: dict[str, Any],
    *,
    authorization_confirmed: bool,
    destination_valid: bool,
    independence_valid: bool,
    frozen_inputs_valid: bool,
    frozen_sources_valid: bool,
    gold_unavailable_to_requests: bool,
    raw_responses_retained: bool,
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
    normalized_raw, compatibility = _normalize_and_audit(raw_responses)
    normalized = evaluate_live_probe_v4(
        selection,
        preregistration,
        normalized_raw,
        authorization_confirmed=authorization_confirmed,
        destination_valid=destination_valid,
        frozen_inputs_valid=frozen_inputs_valid,
        frozen_sources_valid=frozen_sources_valid,
        gold_unavailable_to_requests=gold_unavailable_to_requests,
    )

    selected_ids = selection["selected_case_ids"]
    raw_records = _record_map(raw_responses)
    normalized_records = _record_map(normalized_raw)
    baseline_cases = {item["case_id"]: item for item in baseline["per_case"]}
    normalized_cases = {item["case_id"]: item for item in normalized["per_case"]}
    audit_by_case = {
        item["case_id"]: item
        for item in compatibility["per_case"]
        if item["diagnostics"]
    }
    activated_case_ids = [
        case_id for case_id in selected_ids if case_id in audit_by_case
    ]
    unactivated_case_ids = [
        case_id for case_id in selected_ids if case_id not in audit_by_case
    ]
    activated_errors_eligible = all(
        _baseline_errors_explained(
            baseline_cases[case_id], audit_by_case[case_id]["diagnostics"]
        )
        for case_id in activated_case_ids
    )
    activated_recovered = all(
        not baseline_cases[case_id]["schema_valid"]
        and normalized_cases[case_id]["schema_valid"]
        for case_id in activated_case_ids
    )
    unactivated_equal = all(
        raw_records[case_id].get("raw_model_output")
        == normalized_records[case_id].get("raw_model_output")
        for case_id in unactivated_case_ids
    )

    total_calls = sum(
        int(raw_records.get(case_id, {}).get("model_call_count") or 0)
        for case_id in selected_ids
    )
    exact_case_set = set(raw_records) == set(selected_ids)
    one_call_each = exact_case_set and all(
        raw_records[case_id].get("model_call_count") == 1 for case_id in selected_ids
    )
    request_check = _request_integrity(
        selection, requests_artifact, raw_responses
    )
    checkpoint_check = _checkpoint_integrity(checkpoint, raw_responses)
    standard_gates = normalized["gates"]
    gates = {
        "G0-authorization-independence-and-budget": {
            "passed": (
                authorization_confirmed
                and destination_valid
                and independence_valid
                and total_calls == 5
                and one_call_each
            ),
            "authorization_confirmed": authorization_confirmed,
            "destination_valid": destination_valid,
            "independence_valid": independence_valid,
            "model_call_count": total_calls,
            "required_model_call_count": 5,
            "maximum_model_call_count": 5,
            "one_call_each": one_call_each,
            "exact_case_set": exact_case_set,
        },
        "G1-raw-capture-completeness": {
            "passed": request_check["passed"] and checkpoint_check["passed"],
            "request_artifact": request_check,
            "checkpoint": checkpoint_check,
        },
        "G2-v4-3-strict-schema-restoration": {
            "passed": standard_gates["G1-json-and-root-topology"]["passed"],
            "baseline_schema_valid_case_count": baseline["gates"][
                "G1-json-and-root-topology"
            ]["schema_valid_case_count"],
            "v4_3_schema_valid_case_count": standard_gates[
                "G1-json-and-root-topology"
            ]["schema_valid_case_count"],
            "required_v4_3_schema_valid_case_count": 5,
        },
        "G3-compatibility-intervention-integrity": {
            "passed": (
                compatibility["allowed_codes_only"]
                and compatibility["forward_exactly_equals_v4_2"]
                and compatibility["reverse_exactly_restores_raw"]
                and unactivated_equal
            ),
            **compatibility,
            "unactivated_records_equal": unactivated_equal,
        },
        "G4-source-and-surface-anchoring": standard_gates[
            "G3-source-and-surface-anchoring"
        ],
        "G5-granularity-noncollapse": standard_gates[
            "G5-granularity-noncollapse"
        ],
        "G6-fact-layer-compatibility": standard_gates[
            "G6-fact-layer-compatibility"
        ],
        "G7-source-isolation-and-preservation": {
            "passed": (
                frozen_inputs_valid
                and frozen_sources_valid
                and gold_unavailable_to_requests
                and raw_responses_retained
            ),
            "frozen_inputs_valid": frozen_inputs_valid,
            "frozen_sources_valid": frozen_sources_valid,
            "gold_unavailable_to_requests": gold_unavailable_to_requests,
            "raw_responses_retained": raw_responses_retained,
            "canonicalizer_called": False,
            "default_parser_called": False,
            "new_model_calls_for_v4_3": 0,
        },
    }
    base_passed = all(gate["passed"] for gate in gates.values())
    activation_count = compatibility["activation_count"]
    confirmed = (
        base_passed
        and activation_count > 0
        and activated_errors_eligible
        and activated_recovered
    )
    supported_non_regression_only = (
        base_passed
        and activation_count == 0
        and baseline["gates"]["G1-json-and-root-topology"]["passed"]
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
        "activation_counts": compatibility["activation_counts"],
        "activated_case_count": len(activated_case_ids),
        "activated_case_ids": activated_case_ids,
        "activated_cases_have_only_eligible_incompatibilities": (
            activated_errors_eligible
        ),
        "activated_cases_recovered": activated_recovered,
        "baseline_schema_valid_case_count": baseline["gates"][
            "G1-json-and-root-topology"
        ]["schema_valid_case_count"],
        "v4_3_schema_valid_case_count": standard_gates[
            "G1-json-and-root-topology"
        ]["schema_valid_case_count"],
    }
    gates["G8-generalization-decision"] = causal_gate
    return {
        "evaluation_version": INDEPENDENT_HOLDOUT_EVALUATOR_VERSION,
        "case_count": len(selected_ids),
        "passed": causal_gate["passed"],
        "decision": decision,
        "failed_gates": [name for name, gate in gates.items() if not gate["passed"]],
        "model_call_count": total_calls,
        "network_call_count": total_calls,
        "new_model_calls_for_v4_3": 0,
        "canonicalizer_called": False,
        "default_parser_called": False,
        "gates": gates,
        "baseline_v4": baseline,
        "v4_3": normalized,
    }


def _normalize_and_audit(raw_responses: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    normalized = copy.deepcopy(raw_responses)
    records = normalized.get("records")
    raw_records = raw_responses.get("records")
    if not isinstance(records, list) or not isinstance(raw_records, list):
        raise TypeError("raw response records must be a list")
    per_case: list[dict[str, Any]] = []
    forward_equal = True
    reverse_equal = True
    codes: Counter[str] = Counter()
    for record_index, (record, raw_record) in enumerate(zip(records, raw_records, strict=True)):
        if not isinstance(record, dict) or not isinstance(raw_record, dict):
            raise TypeError(f"raw response record must be an object: {record_index}")
        raw_output = raw_record.get("raw_model_output")
        v43 = normalize_flat_atomic_v4_3_wire_output(raw_output)
        v42 = normalize_flat_atomic_v4_2_wire_output(raw_output)
        diagnostics = [item.as_dict() for item in v43.diagnostics]
        v42_diagnostics = [item.as_dict() for item in v42.diagnostics]
        case_forward_equal = v43.output == v42.output and diagnostics == v42_diagnostics
        case_reverse_equal = (
            restore_flat_atomic_v4_3_wire_output(v43.output, v43.diagnostics)
            == raw_output
        )
        forward_equal = forward_equal and case_forward_equal
        reverse_equal = reverse_equal and case_reverse_equal
        codes.update(item["code"] for item in diagnostics)
        record["raw_model_output"] = v43.output
        per_case.append(
            {
                "record_index": record_index,
                "case_id": record.get("case_id"),
                "activation_count": len(diagnostics),
                "forward_exactly_equals_v4_2": case_forward_equal,
                "reverse_exactly_restores_raw": case_reverse_equal,
                "diagnostics": diagnostics,
            }
        )
    return normalized, {
        "allowed_codes_only": set(codes).issubset(DIAGNOSTIC_CODES),
        "forward_exactly_equals_v4_2": forward_equal,
        "reverse_exactly_restores_raw": reverse_equal,
        "activation_count": sum(codes.values()),
        "activation_counts": dict(codes),
        "activated_record_count": sum(bool(item["diagnostics"]) for item in per_case),
        "per_case": per_case,
    }


def _request_integrity(
    selection: dict[str, Any],
    requests_artifact: dict[str, Any],
    raw_responses: dict[str, Any],
) -> dict[str, Any]:
    selected_ids = selection["selected_case_ids"]
    cases = {case["case_id"]: case for case in selection["cases"]}
    entries = requests_artifact.get("requests")
    records = raw_responses.get("records")
    if not isinstance(entries, list) or not isinstance(records, list):
        return {"passed": False, "reason": "requests_or_records_not_array"}
    request_ids = [entry.get("case_id") for entry in entries if isinstance(entry, dict)]
    exact_order = request_ids == selected_ids and len(entries) == len(selected_ids)
    body_hashes_match = True
    request_hashes_match = True
    full_bodies_present_once = True
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("case_id") not in cases:
            body_hashes_match = False
            request_hashes_match = False
            full_bodies_present_once = False
            continue
        case = cases[entry["case_id"]]
        request = entry.get("request")
        body_hashes_match = body_hashes_match and (
            entry.get("input_sha256") == case.get("source_content_sha256")
            and _text_sha256(case["raw_content"]) == entry.get("input_sha256")
        )
        request_hashes_match = request_hashes_match and (
            _payload_sha256(request) == entry.get("request_sha256")
        )
        messages = request.get("messages") if isinstance(request, dict) else None
        user_text = "\n".join(
            message.get("content", "")
            for message in messages or []
            if isinstance(message, dict) and message.get("role") == "user"
        )
        full_bodies_present_once = full_bodies_present_once and (
            user_text.count(case["raw_content"]) == 1
        )
    artifact_precedes_first_call = False
    try:
        written_at = datetime.fromisoformat(requests_artifact["written_at"])
        starts = [
            datetime.fromisoformat(record["started_at"])
            for record in records
            if isinstance(record, dict)
        ]
        artifact_precedes_first_call = bool(starts) and written_at <= min(starts)
    except (KeyError, TypeError, ValueError):
        pass
    destination_and_budget = (
        requests_artifact.get("destination_host") == "api.deepseek.com"
        and requests_artifact.get("maximum_new_model_calls") == 5
        and requests_artifact.get("maximum_calls_per_case") == 1
        and requests_artifact.get("transport_retries") == 0
        and requests_artifact.get("validation_retries") == 0
    )
    passed = all(
        (
            exact_order,
            body_hashes_match,
            request_hashes_match,
            full_bodies_present_once,
            artifact_precedes_first_call,
            destination_and_budget,
        )
    )
    return {
        "passed": passed,
        "request_count": len(entries),
        "required_request_count": 5,
        "exact_selection_order": exact_order,
        "body_hashes_match": body_hashes_match,
        "request_hashes_match": request_hashes_match,
        "full_bodies_present_once": full_bodies_present_once,
        "request_artifact_precedes_first_call": artifact_precedes_first_call,
        "destination_and_budget_match": destination_and_budget,
    }


def _checkpoint_integrity(
    checkpoint: dict[str, Any], raw_responses: dict[str, Any]
) -> dict[str, Any]:
    records = checkpoint.get("records")
    raw_records = raw_responses.get("records")
    history = checkpoint.get("history")
    if (
        not isinstance(records, list)
        or not isinstance(raw_records, list)
        or not isinstance(history, list)
    ):
        return {"passed": False, "reason": "checkpoint_shape_invalid"}
    records_equal = records == raw_records
    counts_exact = [item.get("record_count") for item in history] == list(
        range(1, len(records) + 1)
    )
    prefix_hashes_match = counts_exact and all(
        item.get("records_sha256") == _payload_sha256(records[:index])
        for index, item in enumerate(history, start=1)
    )
    call_count_match = (
        checkpoint.get("model_call_count") == len(records)
        and checkpoint.get("checkpoint_write_count") == len(history)
        and raw_responses.get("model_call_count") == len(raw_records)
    )
    passed = records_equal and counts_exact and prefix_hashes_match and call_count_match
    return {
        "passed": passed,
        "records_equal_raw": records_equal,
        "checkpoint_write_count": len(history),
        "required_checkpoint_write_count": len(records),
        "history_counts_exact": counts_exact,
        "prefix_hashes_match": prefix_hashes_match,
        "call_count_match": call_count_match,
    }


def _baseline_errors_explained(
    baseline_case: dict[str, Any], diagnostics: list[dict[str, Any]]
) -> bool:
    allowed_exact: set[str] = set()
    allowed_prefixes: list[str] = []
    for diagnostic in diagnostics:
        path = diagnostic["path"].replace("[", ".").replace("]", "")
        if diagnostic["code"] == EMPTY_FACT_CODE:
            allowed_prefixes.append(path + ".")
        else:
            allowed_exact.add(path)
    baseline_diagnostics = baseline_case.get("diagnostics")
    return bool(baseline_diagnostics) and all(
        diagnostic.get("path") in allowed_exact
        or any(
            str(diagnostic.get("path", "")).startswith(prefix)
            for prefix in allowed_prefixes
        )
        for diagnostic in baseline_diagnostics
    )


def _record_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    records = payload.get("records")
    if not isinstance(records, list):
        raise TypeError("raw response records must be a list")
    result: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("case_id"), str):
            raise TypeError("raw response record requires case_id")
        if record["case_id"] in result:
            raise ValueError(f"duplicate raw response case_id: {record['case_id']}")
        result[record["case_id"]] = record
    return result


def _payload_sha256(value: object) -> str:
    rendered = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
