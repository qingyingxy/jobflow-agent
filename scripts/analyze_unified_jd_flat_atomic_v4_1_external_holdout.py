from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from src.domain.unified_jd_extraction import UnifiedFactMentionV2
from src.domain.unified_jd_flat_atomic_v4 import UnifiedJDFlatAtomicClauseV4
from src.evaluation.model_first_v4_1_compatibility import (
    normalize_live_probe_raw_responses_v4_1,
)
from src.evaluation.model_first_v4_live_probe import analyze_live_response_v4

ROOT = Path(__file__).resolve().parents[1]
SELECTION = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_1_external_holdout_selection_v1_2026-09-06.json"
)
PREREGISTRATION = ROOT / (
    "datasets/"
    "unified_jd_flat_atomic_v4_1_external_holdout_preregistration_v1_2026-09-06.json"
)
SOURCE_FREEZE = ROOT / (
    "datasets/"
    "unified_jd_flat_atomic_v4_1_external_holdout_source_freeze_v1_2026-09-06.json"
)
REQUESTS = ROOT / (
    "artifacts/evaluation/"
    "unified-jd-flat-atomic-v4-1-external-holdout-requests-v1-2026-09-06.json"
)
RAW = ROOT / (
    "artifacts/evaluation/"
    "unified-jd-flat-atomic-v4-1-external-holdout-raw-v1-2026-09-06.json"
)
FORMAL_REPORT = ROOT / (
    "artifacts/evaluation/"
    "unified-jd-flat-atomic-v4-1-external-holdout-report-v1-2026-09-06.json"
)
DEFAULT_OUTPUT = ROOT / (
    "artifacts/evaluation/"
    "unified-jd-flat-atomic-v4-1-external-holdout-offline-diagnosis-v1-2026-09-06.json"
)


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected object: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _reference(path: Path) -> dict[str, str]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": _sha256(path),
    }


def _validation_errors(model: type[Any], payload: object) -> list[dict[str, str]]:
    try:
        model.model_validate(payload)
    except ValidationError as error:
        return [
            {
                "path": ".".join(str(part) for part in item["loc"]),
                "code": item["type"],
                "message": item["msg"],
            }
            for item in error.errors()
        ]
    return []


def _analyze_case(
    case: dict[str, Any],
    record: dict[str, Any],
    minimum_primary_atoms: int,
) -> dict[str, Any]:
    source = case["raw_content"]
    output = record["raw_model_output"]
    raw_facts = output["fact_mentions"]
    raw_atoms = output["clause_atoms"]

    valid_facts: list[dict[str, Any]] = []
    invalid_fact_diagnostics: list[dict[str, Any]] = []
    for index, fact in enumerate(raw_facts):
        errors = _validation_errors(UnifiedFactMentionV2, fact)
        if errors:
            invalid_fact_diagnostics.append(
                {"index": index, "field": fact.get("field"), "errors": errors}
            )
        else:
            valid_facts.append(fact)

    valid_atoms: list[dict[str, Any]] = []
    invalid_atom_diagnostics: list[dict[str, Any]] = []
    for index, atom in enumerate(raw_atoms):
        errors = _validation_errors(UnifiedJDFlatAtomicClauseV4, atom)
        if errors:
            invalid_atom_diagnostics.append(
                {
                    "index": index,
                    "role": atom.get("role"),
                    "category": atom.get("category"),
                    "source_text_length": len(atom.get("source_text") or ""),
                    "errors": errors,
                }
            )
        else:
            valid_atoms.append(atom)

    fact_component = analyze_live_response_v4(
        {"fact_mentions": valid_facts, "clause_atoms": []}, source
    )
    atom_component = analyze_live_response_v4(
        {"fact_mentions": [], "clause_atoms": valid_atoms}, source
    )
    primary_count = atom_component["primary_atom_count"]
    empty_placeholders = [
        fact["field"]
        for fact in raw_facts
        if fact.get("raw_items") == [] and fact.get("source_text") == ""
    ]
    return {
        "case_id": case["case_id"],
        "raw_fact_count": len(raw_facts),
        "valid_fact_count": len(valid_facts),
        "invalid_fact_count": len(invalid_fact_diagnostics),
        "empty_absent_fact_placeholder_count": len(empty_placeholders),
        "empty_absent_fact_placeholder_fields": empty_placeholders,
        "invalid_fact_diagnostics": invalid_fact_diagnostics,
        "raw_atom_count": len(raw_atoms),
        "valid_atom_count": len(valid_atoms),
        "invalid_atom_count": len(invalid_atom_diagnostics),
        "invalid_atom_diagnostics": invalid_atom_diagnostics,
        "role_counts": dict(Counter(atom.get("role") for atom in raw_atoms)),
        "all_roles_in_frozen_v4_vocabulary": all(
            atom.get("role") in {"item", "example"} for atom in raw_atoms
        ),
        "eligible_responsibility_alias_count": sum(
            atom.get("role") == "responsibility"
            and atom.get("category") == "responsibility"
            and atom.get("level") == "mention"
            for atom in raw_atoms
        ),
        "valid_primary_atom_count": primary_count,
        "minimum_primary_atom_count": minimum_primary_atoms,
        "direct_granularity_floor_passed": primary_count >= minimum_primary_atoms,
        "valid_example_atom_count": atom_component["example_atom_count"],
        "direct_atom_source_localization_rate": (
            atom_component["located_source_text_count"]
            / atom_component["source_text_count"]
            if atom_component["source_text_count"]
            else 0.0
        ),
        "direct_nonnull_surface_localization_rate": (
            atom_component["located_nonnull_primary_surface_count"]
            / atom_component["nonnull_primary_surface_count"]
            if atom_component["nonnull_primary_surface_count"]
            else 0.0
        ),
        "direct_nonnull_primary_surface_rate": (
            atom_component["nonnull_primary_surface_count"] / primary_count
            if primary_count
            else 0.0
        ),
        "direct_separated_pair_count": atom_component["separated_pair_count"],
        "valid_fact_component_compatible": fact_component["fact_layer_compatible"],
        "valid_fact_source_localization_rate": (
            fact_component["located_source_text_count"]
            / fact_component["source_text_count"]
            if fact_component["source_text_count"]
            else 1.0
        ),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Post-hoc component diagnosis of the frozen v4.1 external holdout"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    arguments = _parse_args()
    if arguments.output.exists():
        raise FileExistsError(f"offline diagnosis already exists: {arguments.output}")
    selection = _load(SELECTION)
    preregistration = _load(PREREGISTRATION)
    _load(SOURCE_FREEZE)
    requests = _load(REQUESTS)
    raw = _load(RAW)
    formal_report = _load(FORMAL_REPORT)

    cases = {case["case_id"]: case for case in selection["cases"]}
    records = {record["case_id"]: record for record in raw["records"]}
    minimums = preregistration["acceptance_gates"]["G5-granularity-noncollapse"][
        "per_case_minimums"
    ]
    per_case = [
        _analyze_case(cases[case_id], records[case_id], minimums[case_id])
        for case_id in selection["selected_case_ids"]
    ]
    normalized_raw, audit = normalize_live_probe_raw_responses_v4_1(raw)
    activation_count = sum(len(item["diagnostics"]) for item in audit)
    aggregate_valid_primary = sum(item["valid_primary_atom_count"] for item in per_case)
    aggregate_invalid_facts = sum(item["invalid_fact_count"] for item in per_case)
    aggregate_invalid_atoms = sum(item["invalid_atom_count"] for item in per_case)
    aggregate_separated = sum(item["direct_separated_pair_count"] for item in per_case)
    request_text = json.dumps(requests, ensure_ascii=False).lower()
    sentinel_matches = {
        "gold": request_text.count("gold"),
        "expected": request_text.count("expected"),
    }
    diagnosis = {
        "diagnosis_version": (
            "unified-jd-flat-atomic-v4.1-external-holdout-offline-diagnosis-v1"
        ),
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "post_hoc_offline_diagnosis_of_frozen_raw",
        "formal_decision_unchanged": formal_report["decision"],
        "formal_report_passed_unchanged": formal_report["passed"],
        "model_call_count": 0,
        "network_call_count": 0,
        "source_model_call_count": raw["model_call_count"],
        "compatibility_mechanism": {
            "activation_count": activation_count,
            "activated_case_count": len(audit),
            "normalized_raw_equals_frozen_raw": normalized_raw == raw,
            "finding": (
                "not_observed_non_regressive"
                if activation_count == 0 and normalized_raw == raw
                else "observed_or_mutating"
            ),
            "claim": (
                "The responsibility-role alias did not recur, so this holdout cannot "
                "confirm cross-corpus activation generalization. The frozen v4.1 "
                "adapter also made no changes and introduced no regression."
            ),
        },
        "strict_contract_failures": {
            "invalid_fact_count": aggregate_invalid_facts,
            "affected_fact_case_count": sum(
                item["invalid_fact_count"] > 0 for item in per_case
            ),
            "empty_absent_fact_placeholder_count": sum(
                item["empty_absent_fact_placeholder_count"] for item in per_case
            ),
            "invalid_atom_count": aggregate_invalid_atoms,
            "affected_atom_case_count": sum(
                item["invalid_atom_count"] > 0 for item in per_case
            ),
            "root_and_exact_field_topology_case_count": sum(
                formal_case["root_keys_exact"]
                and formal_case["fact_fields_exact"]
                and formal_case["atom_fields_exact"]
                and formal_case["no_nested_clause_fields"]
                for formal_case in formal_report["baseline_v4"]["per_case"]
            ),
            "finding": (
                "Four cases emitted empty placeholder fact mentions for absent fields; "
                "Atira emitted ten otherwise shaped responsibility atoms whose exact "
                "source_text exceeded the schema's 240-character maximum."
            ),
        },
        "direct_component_diagnostics_not_gate_rescoring": {
            "warning": (
                "These metrics bypass only the invalid records to reveal the failure "
                "location. They do not replace or retroactively pass the frozen gates."
            ),
            "aggregate_valid_primary_atom_count": aggregate_valid_primary,
            "frozen_minimum_aggregate_primary_atom_count": preregistration[
                "acceptance_gates"
            ]["G5-granularity-noncollapse"]["minimum_aggregate_primary_atom_count"],
            "all_per_case_granularity_floors_passed": all(
                item["direct_granularity_floor_passed"] for item in per_case
            ),
            "aggregate_separated_pair_count": aggregate_separated,
            "all_valid_atom_sources_located": all(
                item["direct_atom_source_localization_rate"] == 1.0 for item in per_case
            ),
            "all_valid_nonnull_surfaces_located": all(
                item["direct_nonnull_surface_localization_rate"] == 1.0
                for item in per_case
            ),
            "all_valid_fact_components_compatible": all(
                item["valid_fact_component_compatible"] for item in per_case
            ),
        },
        "g7_sentinel_diagnostic": {
            "sentinel_matches": sentinel_matches,
            "gold_token_present": sentinel_matches["gold"] > 0,
            "expected_token_present": sentinel_matches["expected"] > 0,
            "known_source_phrase": "These expected base pay ranges",
            "finding": (
                "The request-artifact substring sentinel treated the ordinary word "
                "'expected' inside the Airwallex job body as leakage. This is an "
                "evaluator instrumentation false positive, not evidence that gold or "
                "expected outputs were sent to the model."
            ),
        },
        "per_case": per_case,
        "inputs": {
            "selection": _reference(SELECTION),
            "preregistration": _reference(PREREGISTRATION),
            "source_freeze": _reference(SOURCE_FREEZE),
            "requests": _reference(REQUESTS),
            "raw": _reference(RAW),
            "formal_report": _reference(FORMAL_REPORT),
        },
        "next_step": (
            "Do not rerun or modify v4.1. Treat absent-fact serialization and long "
            "source-span representation as two new mechanisms; preregister separate "
            "offline oracles on these frozen raw responses before proposing a new "
            "request contract."
        ),
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    with arguments.output.open("x", encoding="utf-8", newline="\n") as output:
        json.dump(diagnosis, output, ensure_ascii=False, indent=2)
        output.write("\n")
    print(
        json.dumps(
            {
                "output": _reference(arguments.output),
                "formal_decision": diagnosis["formal_decision_unchanged"],
                "compatibility_finding": diagnosis["compatibility_mechanism"][
                    "finding"
                ],
                "invalid_fact_count": aggregate_invalid_facts,
                "invalid_atom_count": aggregate_invalid_atoms,
                "aggregate_valid_primary_atom_count": aggregate_valid_primary,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
