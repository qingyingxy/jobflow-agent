from __future__ import annotations

import copy
from collections import Counter
from typing import Any

from src.evaluation.model_first_v4_live_probe import analyze_live_response_v4
from src.services.unified_jd_flat_atomic_v4_4_compatibility import (
    UNIFIED_JD_FLAT_ATOMIC_V4_4_COMPATIBILITY_VERSION,
    normalize_flat_atomic_v4_4_wire_output,
)

MODEL_FIRST_V4_4_COMPATIBILITY_EVALUATOR_VERSION = (
    "unified-jd-flat-atomic-v4.4-compatibility-evaluator-v1"
)


def normalize_raw_responses_v4_4(
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
        result = normalize_flat_atomic_v4_4_wire_output(record.get("raw_model_output"))
        record["raw_model_output"] = result.output
        if result.diagnostics:
            audit.append(
                {
                    "record_index": record_index,
                    "case_id": record.get("case_id"),
                    "diagnostics": [item.as_dict() for item in result.diagnostics],
                }
            )
    return normalized, audit


def analyze_raw_responses_v4_4(
    raw_responses: dict[str, Any],
    source_by_case: dict[str, str],
) -> dict[str, Any]:
    normalized, audit = normalize_raw_responses_v4_4(raw_responses)
    records = normalized["records"]
    analyses: dict[str, dict[str, Any]] = {}
    for record in records:
        case_id = record.get("case_id")
        if not isinstance(case_id, str) or case_id not in source_by_case:
            raise ValueError(f"missing source content for case: {case_id}")
        analyses[case_id] = analyze_live_response_v4(
            record["raw_model_output"],
            source_by_case[case_id],
        )
    codes = Counter(
        diagnostic["code"]
        for record in audit
        for diagnostic in record["diagnostics"]
    )
    return {
        "evaluation_version": MODEL_FIRST_V4_4_COMPATIBILITY_EVALUATOR_VERSION,
        "compatibility_version": UNIFIED_JD_FLAT_ATOMIC_V4_4_COMPATIBILITY_VERSION,
        "normalized_raw": normalized,
        "audit": audit,
        "activation_count": sum(codes.values()),
        "activation_counts": dict(codes),
        "analyses": analyses,
        "strict_schema_valid_case_count": sum(
            bool(item["schema_valid"]) for item in analyses.values()
        ),
        "model_call_count": 0,
        "network_call_count": 0,
        "default_parser_call_count": 0,
        "canonicalizer_call_count": 0,
    }
