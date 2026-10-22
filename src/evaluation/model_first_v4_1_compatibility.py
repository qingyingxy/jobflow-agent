from __future__ import annotations

import copy
from typing import Any

from src.evaluation.model_first_v4_live_probe import evaluate_live_probe_v4
from src.services.unified_jd_flat_atomic_v4_compatibility import (
    UNIFIED_JD_FLAT_ATOMIC_V4_COMPATIBILITY_VERSION,
    normalize_flat_atomic_v4_wire_output,
)

MODEL_FIRST_V4_1_COMPATIBILITY_EVALUATOR_VERSION = (
    "unified-jd-flat-atomic-v4.1-compatibility-evaluator-v1"
)


def normalize_live_probe_raw_responses_v4_1(
    raw_responses: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    normalized = copy.deepcopy(raw_responses)
    records = normalized.get("records")
    if not isinstance(records, list):
        raise TypeError("raw response records must be a list")

    audit: list[dict[str, Any]] = []
    for record_index, record in enumerate(records):
        if not isinstance(record, dict):
            raise TypeError(f"raw response record must be an object: {record_index}")
        result = normalize_flat_atomic_v4_wire_output(
            record.get("raw_model_output")
        )
        record["raw_model_output"] = result.output
        if result.diagnostics:
            audit.append(
                {
                    "record_index": record_index,
                    "case_id": record.get("case_id"),
                    "diagnostics": [
                        item.as_dict() for item in result.diagnostics
                    ],
                }
            )
    return normalized, audit


def evaluate_live_probe_v4_1(
    selection: dict[str, Any],
    preregistration: dict[str, Any],
    raw_responses: dict[str, Any],
    *,
    frozen_inputs_valid: bool,
    frozen_sources_valid: bool,
) -> dict[str, Any]:
    normalized, audit = normalize_live_probe_raw_responses_v4_1(raw_responses)
    report = evaluate_live_probe_v4(
        selection,
        preregistration,
        normalized,
        authorization_confirmed=True,
        destination_valid=True,
        frozen_inputs_valid=frozen_inputs_valid,
        frozen_sources_valid=frozen_sources_valid,
        gold_unavailable_to_requests=True,
    )
    report["evaluation_version"] = (
        MODEL_FIRST_V4_1_COMPATIBILITY_EVALUATOR_VERSION
    )
    report["compatibility"] = {
        "version": UNIFIED_JD_FLAT_ATOMIC_V4_COMPATIBILITY_VERSION,
        "activation_count": sum(
            len(record["diagnostics"]) for record in audit
        ),
        "activated_record_count": len(audit),
        "audit": audit,
    }
    report["new_model_call_count"] = 0
    report["offline_network_call_count"] = 0
    report["source_model_call_count"] = raw_responses.get("model_call_count")
    return report
