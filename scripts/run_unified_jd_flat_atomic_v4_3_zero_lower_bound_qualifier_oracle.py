from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.evaluation.model_first_v4_3_zero_lower_bound_qualifier_oracle import (
    evaluate_zero_lower_bound_qualifier_pair,
)
from src.services.unified_jd_flat_atomic_v4_3_compatibility import (
    normalize_flat_atomic_v4_3_wire_output,
    restore_flat_atomic_v4_3_wire_output,
)
from src.services.unified_jd_flat_atomic_v4_3_zero_lower_bound_qualifier_oracle import (
    normalize_zero_lower_bound_qualifier,
    restore_zero_lower_bound_qualifier,
)

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_ID = "zero-lower-bound-qualifier-oracle-v1"
PREREGISTRATION = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_3_zero_lower_bound_qualifier_oracle_"
    "preregistration_v1_2026-09-06.json"
)
PREREGISTRATION_FREEZE = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_3_zero_lower_bound_qualifier_oracle_"
    "preregistration_freeze_v1_2026-09-06.json"
)
SOURCE_FREEZE = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_3_zero_lower_bound_qualifier_oracle_"
    "source_freeze_v1_2026-09-06.json"
)
FROZEN_RAW = ROOT / (
    "artifacts/evaluation/unified-jd-flat-atomic-v4-3-independent-holdout-"
    "raw-v1-2026-09-06.json"
)
SELECTION = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_3_independent_holdout_selection_"
    "v1_2026-09-06.json"
)
RAW_OUTPUT = ROOT / (
    "artifacts/evaluation/unified-jd-flat-atomic-v4-3-zero-lower-bound-"
    "qualifier-oracle-raw-v1-2026-09-06.json"
)
REPORT_OUTPUT = ROOT / (
    "artifacts/evaluation/unified-jd-flat-atomic-v4-3-zero-lower-bound-"
    "qualifier-oracle-report-v1-2026-09-06.json"
)
EXPECTED_PREREGISTRATION_HASH = (
    "799bb850a726d1e1645b7d542bbce95acbdb7722695dd12d95ac26c5b73f969a"
)
EXPECTED_PREREGISTRATION_FREEZE_HASH = (
    "a06cae5dcaa2dc813c84f948fca76551bbaf461777c91c3355e397a8d17f1579"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_sha256(value: object) -> str:
    rendered = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected object: {path}")
    return value


def _reference(path: Path) -> dict[str, str]:
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": _sha256(path)}


def _write_new(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as output:
        json.dump(payload, output, ensure_ascii=False, indent=2)
        output.write("\n")


def _verify_references(entries: dict[str, Any]) -> None:
    for name, entry in entries.items():
        path = (ROOT / entry["path"]).resolve()
        if ROOT.resolve() not in path.parents:
            raise ValueError(f"frozen input escapes workspace: {name}")
        if not path.is_file() or _sha256(path) != entry["sha256"]:
            raise ValueError(f"frozen input hash mismatch: {name}")


def _preflight() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if RAW_OUTPUT.exists() or REPORT_OUTPUT.exists():
        raise FileExistsError("one-time zero-lower-bound oracle output already exists")
    if _sha256(PREREGISTRATION) != EXPECTED_PREREGISTRATION_HASH:
        raise ValueError("zero-lower-bound preregistration hash changed")
    if _sha256(PREREGISTRATION_FREEZE) != EXPECTED_PREREGISTRATION_FREEZE_HASH:
        raise ValueError("zero-lower-bound preregistration freeze hash changed")
    preregistration = _load(PREREGISTRATION)
    preregistration_freeze = _load(PREREGISTRATION_FREEZE)
    source_freeze = _load(SOURCE_FREEZE)
    _verify_references(preregistration["frozen_inputs"])
    _verify_references(preregistration_freeze["artifacts"])
    _verify_references(source_freeze["artifacts"])
    if (
        source_freeze.get("status")
        != "offline_oracle_runner_frozen_before_execution"
        or source_freeze.get("experiment_id") != EXPERIMENT_ID
        or source_freeze.get("formal_execution_count_at_freeze") != 0
    ):
        raise ValueError("zero-lower-bound oracle source freeze is invalid")
    return preregistration, _load(FROZEN_RAW), _load(SELECTION)


def _changed_paths(before: object, after: object, prefix: str = "") -> list[str]:
    if isinstance(before, dict) and isinstance(after, dict):
        if set(before) != set(after):
            return [prefix or "response"]
        paths: list[str] = []
        for key in before:
            child = f"{prefix}.{key}" if prefix else str(key)
            paths.extend(_changed_paths(before[key], after[key], child))
        return paths
    if isinstance(before, list) and isinstance(after, list):
        if len(before) != len(after):
            return [prefix or "response"]
        paths = []
        for index, (left, right) in enumerate(zip(before, after, strict=True)):
            paths.extend(_changed_paths(left, right, f"{prefix}[{index}]"))
        return paths
    return [] if before == after else [prefix or "response"]


def _run(
    preregistration: dict[str, Any],
    frozen_raw: dict[str, Any],
    selection: dict[str, Any],
) -> dict[str, Any]:
    source_by_case = {
        case["case_id"]: case["raw_content"] for case in selection["cases"]
    }
    input_hash_before = _json_sha256(frozen_raw)
    records: list[dict[str, Any]] = []
    for record_index, record in enumerate(frozen_raw["records"]):
        case_id = record["case_id"]
        v4_3_result = normalize_flat_atomic_v4_3_wire_output(
            record["raw_model_output"]
        )
        oracle_result = normalize_zero_lower_bound_qualifier(
            v4_3_result.output,
            record_index=record_index,
        )
        analyses = evaluate_zero_lower_bound_qualifier_pair(
            v4_3_result.output,
            oracle_result.output,
            source_by_case[case_id],
        )
        oracle_restored = restore_zero_lower_bound_qualifier(
            oracle_result.output,
            oracle_result.diagnostics,
            record_index=record_index,
        )
        raw_restored = restore_flat_atomic_v4_3_wire_output(
            oracle_restored,
            v4_3_result.diagnostics,
        )
        records.append(
            {
                "record_index": record_index,
                "case_id": case_id,
                "v4_3_output": v4_3_result.output,
                "treatment_output": oracle_result.output,
                "v4_3_diagnostics": [
                    item.as_dict() for item in v4_3_result.diagnostics
                ],
                "oracle_diagnostics": [
                    item.as_dict() for item in oracle_result.diagnostics
                ],
                "baseline_analysis": analyses["baseline"],
                "treatment_analysis": analyses["treatment"],
                "changed_paths": _changed_paths(
                    v4_3_result.output,
                    oracle_result.output,
                ),
                "oracle_reverse_restores_v4_3_output": (
                    oracle_restored == v4_3_result.output
                ),
                "v4_3_reverse_restores_frozen_raw": (
                    raw_restored == record["raw_model_output"]
                ),
            }
        )
    return {
        "raw_version": (
            "unified-jd-flat-atomic-v4.3-zero-lower-bound-qualifier-"
            "oracle-raw-v1"
        ),
        "created_at": datetime.now(UTC).isoformat(),
        "status": "revealed_frozen_raw_offline_causal_oracle",
        "experiment_id": EXPERIMENT_ID,
        "baseline": "frozen_raw_with_frozen_v4_3_applied_once_per_response",
        "other_oracle_output_loaded": False,
        "category_vocabulary_admission_oracle_applied": False,
        "model_call_count": 0,
        "network_call_count": 0,
        "default_parser_call_count": 0,
        "canonicalizer_call_count": 0,
        "v4_3_forward_normalization_count": len(records),
        "input_payload_sha256_before": input_hash_before,
        "input_payload_sha256_after": _json_sha256(frozen_raw),
        "records": records,
        "registered_claim_boundary": preregistration["claim_boundary"],
    }


def _non_target_atom_count(records: list[dict[str, Any]]) -> tuple[int, bool]:
    count = 0
    unchanged = True
    for record in records:
        activated = {
            diagnostic["atom_index"] for diagnostic in record["oracle_diagnostics"]
        }
        before_atoms = record["v4_3_output"]["clause_atoms"]
        after_atoms = record["treatment_output"]["clause_atoms"]
        for atom_index, (before, after) in enumerate(
            zip(before_atoms, after_atoms, strict=True)
        ):
            if atom_index in activated:
                continue
            count += 1
            unchanged = unchanged and before == after
    return count, unchanged


def _report(
    preregistration: dict[str, Any],
    raw: dict[str, Any],
) -> dict[str, Any]:
    observations = preregistration["frozen_observations"]
    records = raw["records"]
    baseline_valid = {
        record["case_id"]: record["baseline_analysis"]["schema_valid"]
        for record in records
    }
    treatment_valid = {
        record["case_id"]: record["treatment_analysis"]["schema_valid"]
        for record in records
    }
    diagnostics = [
        {"case_id": record["case_id"], **diagnostic}
        for record in records
        for diagnostic in record["oracle_diagnostics"]
    ]
    observed_targets = [
        {
            "case_id": item["case_id"],
            "atom_index": item["atom_index"],
            "path": item["path"],
            "value": item["before"],
            "source_text": item["source_text"],
        }
        for item in diagnostics
    ]
    expected_targets = observations["zero_lower_bound_targets"]
    recovered = sorted(
        case_id
        for case_id in baseline_valid
        if not baseline_valid[case_id] and treatment_valid[case_id]
    )
    expected_recovered = sorted(
        preregistration["acceptance_gates"]["Z3-independent-target-recovery"][
            "required_recovered_case_ids"
        ]
    )
    remaining_invalid = sorted(
        case_id for case_id, valid in treatment_valid.items() if not valid
    )
    expected_remaining = sorted(
        preregistration["acceptance_gates"]["Z3-independent-target-recovery"][
            "remaining_invalid_case_ids"
        ]
    )
    remaining_diagnostics = [
        diagnostic
        for record in records
        if not record["treatment_analysis"]["schema_valid"]
        for diagnostic in record["treatment_analysis"]["diagnostics"]
    ]
    changed_paths = [
        {"case_id": record["case_id"], "path": path}
        for record in records
        for path in record["changed_paths"]
    ]
    non_target_count, non_targets_unchanged = _non_target_atom_count(records)
    input_unchanged = (
        raw["input_payload_sha256_before"] == raw["input_payload_sha256_after"]
    )
    reverse_exact = all(
        record["oracle_reverse_restores_v4_3_output"]
        and record["v4_3_reverse_restores_frozen_raw"]
        for record in records
    )
    v4_3_activation_count = sum(
        len(record["v4_3_diagnostics"]) for record in records
    )
    categories_before = [
        atom["category"]
        for record in records
        for atom in record["v4_3_output"]["clause_atoms"]
    ]
    categories_after = [
        atom["category"]
        for record in records
        for atom in record["treatment_output"]["clause_atoms"]
    ]
    positive_minimums = [
        atom["qualifier"]["minimum_months"]
        for record in records
        for atom in record["treatment_output"]["clause_atoms"]
        if isinstance(atom.get("qualifier"), dict)
        and type(atom["qualifier"].get("minimum_months")) is int
        and atom["qualifier"]["minimum_months"] > 0
    ]
    controls = preregistration["controls"]
    checks = {
        "Z0-frozen-inputs-isolation-and-zero-calls": {
            "passed": input_unchanged
            and raw["model_call_count"] == 0
            and raw["network_call_count"] == 0
            and raw["default_parser_call_count"] == 0
            and raw["canonicalizer_call_count"] == 0
            and not raw["other_oracle_output_loaded"]
            and not raw["category_vocabulary_admission_oracle_applied"]
            and raw["v4_3_forward_normalization_count"] == 5,
            "input_payload_unchanged": input_unchanged,
            "model_call_count": raw["model_call_count"],
            "network_call_count": raw["network_call_count"],
        },
        "Z1-activation-exactness": {
            "passed": observed_targets == expected_targets
            and all(item["after"] is None for item in diagnostics),
            "actual": diagnostics,
            "required": expected_targets,
        },
        "Z2-intervention-and-reversibility": {
            "passed": len(changed_paths) == 1
            and changed_paths[0]["path"]
            == expected_targets[0]["path"]
            and reverse_exact,
            "changed_paths": changed_paths,
            "reverse_exact": reverse_exact,
        },
        "Z3-independent-target-recovery": {
            "passed": baseline_valid == observations["v4_3_schema_valid_by_case"]
            and sum(baseline_valid.values()) == 2
            and sum(treatment_valid.values()) == 3
            and recovered == expected_recovered
            and remaining_invalid == expected_remaining
            and len(remaining_diagnostics) == 2
            and {item.get("code") for item in remaining_diagnostics}
            == {"literal_error"}
            and {item.get("path") for item in remaining_diagnostics}
            == {"clause_atoms.10.category", "clause_atoms.22.category"},
            "baseline_valid_by_case": baseline_valid,
            "treatment_valid_by_case": treatment_valid,
            "recovered_case_ids": recovered,
            "remaining_invalid_case_ids": remaining_invalid,
            "remaining_diagnostics": remaining_diagnostics,
        },
        "Z4-controls-and-non-regression": {
            "passed": positive_minimums == [72]
            and non_target_count == controls["other_atom_count"]
            and non_targets_unchanged
            and categories_before == categories_after
            and sorted(set(categories_after) - {"skill", "capability", "experience", "responsibility"})
            == sorted(controls["unsupported_category_values_must_remain"])
            and v4_3_activation_count
            == controls["frozen_v4_3_omission_activation_count_must_remain"]
            and reverse_exact,
            "positive_minimum_values": positive_minimums,
            "unchanged_non_target_atom_count": non_target_count,
            "non_target_atoms_unchanged": non_targets_unchanged,
            "category_values_unchanged": categories_before == categories_after,
            "v4_3_activation_count": v4_3_activation_count,
            "v4_3_and_oracle_reverse_exact": reverse_exact,
        },
    }
    accepted = all(item["passed"] for item in checks.values())
    return {
        "report_version": (
            "unified-jd-flat-atomic-v4.3-zero-lower-bound-qualifier-"
            "oracle-report-v1"
        ),
        "created_at": datetime.now(UTC).isoformat(),
        "status": "one_time_offline_oracle_evaluation",
        "experiment_id": EXPERIMENT_ID,
        "accepted": accepted,
        "decision": (
            "supported_independent_zero_lower_bound_mechanism"
            if accepted
            else "not_supported"
        ),
        "baseline_strict_schema_valid_case_count": sum(baseline_valid.values()),
        "oracle_strict_schema_valid_case_count": sum(treatment_valid.values()),
        "strict_schema_case_gain": sum(treatment_valid.values())
        - sum(baseline_valid.values()),
        "checks": checks,
        "model_call_count": 0,
        "network_call_count": 0,
        "v4_3_modified": False,
        "generalization_claim": False,
        "production_rule_claim": False,
        "claim_boundary": preregistration["claim_boundary"],
    }


def main() -> int:
    preregistration, frozen_raw, selection = _preflight()
    raw = _run(preregistration, frozen_raw, selection)
    report = _report(preregistration, raw)
    _write_new(RAW_OUTPUT, raw)
    report["inputs"] = {
        "preregistration": _reference(PREREGISTRATION),
        "preregistration_freeze": _reference(PREREGISTRATION_FREEZE),
        "source_freeze": _reference(SOURCE_FREEZE),
        "frozen_raw": _reference(FROZEN_RAW),
        "oracle_raw": _reference(RAW_OUTPUT),
    }
    _write_new(REPORT_OUTPUT, report)
    print(
        json.dumps(
            {
                "accepted": report["accepted"],
                "decision": report["decision"],
                "baseline_strict_schema_valid_case_count": report[
                    "baseline_strict_schema_valid_case_count"
                ],
                "oracle_strict_schema_valid_case_count": report[
                    "oracle_strict_schema_valid_case_count"
                ],
                "raw": _reference(RAW_OUTPUT),
                "report": _reference(REPORT_OUTPUT),
                "model_call_count": 0,
                "network_call_count": 0,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["accepted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
