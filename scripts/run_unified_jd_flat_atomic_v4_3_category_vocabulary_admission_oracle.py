from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.evaluation.model_first_v4_3_category_vocabulary_admission_oracle import (
    FROZEN_CATEGORIES,
    analyze_category_vocabulary_admission,
    category_admission_diagnostics,
    schema_delta_is_category_only,
)
from src.evaluation.model_first_v4_live_probe import analyze_live_response_v4
from src.services.unified_jd_flat_atomic_v4_3_compatibility import (
    normalize_flat_atomic_v4_3_wire_output,
    restore_flat_atomic_v4_3_wire_output,
)

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_ID = "category-vocabulary-admission-oracle-v1"
PREREGISTRATION = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_3_category_vocabulary_admission_oracle_"
    "preregistration_v1_2026-09-06.json"
)
PREREGISTRATION_FREEZE = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_3_category_vocabulary_admission_oracle_"
    "preregistration_freeze_v1_2026-09-06.json"
)
SOURCE_FREEZE = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_3_category_vocabulary_admission_oracle_"
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
    "artifacts/evaluation/unified-jd-flat-atomic-v4-3-category-vocabulary-"
    "admission-oracle-raw-v1-2026-09-06.json"
)
REPORT_OUTPUT = ROOT / (
    "artifacts/evaluation/unified-jd-flat-atomic-v4-3-category-vocabulary-"
    "admission-oracle-report-v1-2026-09-06.json"
)
EXPECTED_PREREGISTRATION_HASH = (
    "0e4dec9018463d255224044517b4e6ff0c48c06bb28984a4559688340df81d90"
)
EXPECTED_PREREGISTRATION_FREEZE_HASH = (
    "f59256d262eedbdf10294bb4e190448a11dfba187957d30f73113eaf7ee36d94"
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
        raise FileExistsError("one-time category oracle output already exists")
    if _sha256(PREREGISTRATION) != EXPECTED_PREREGISTRATION_HASH:
        raise ValueError("category oracle preregistration hash changed")
    if _sha256(PREREGISTRATION_FREEZE) != EXPECTED_PREREGISTRATION_FREEZE_HASH:
        raise ValueError("category oracle preregistration freeze hash changed")
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
        raise ValueError("category oracle source freeze is invalid")
    return preregistration, _load(FROZEN_RAW), _load(SELECTION)


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
    category_counts: Counter[str] = Counter()
    for record_index, record in enumerate(frozen_raw["records"]):
        case_id = record["case_id"]
        result = normalize_flat_atomic_v4_3_wire_output(record["raw_model_output"])
        normalized_before_oracle = copy.deepcopy(result.output)
        baseline = analyze_live_response_v4(result.output, source_by_case[case_id])
        oracle = analyze_category_vocabulary_admission(
            result.output,
            source_by_case[case_id],
        )
        admissions = category_admission_diagnostics(
            result.output,
            record_index=record_index,
        )
        atoms = result.output.get("clause_atoms") if isinstance(result.output, dict) else None
        if not isinstance(atoms, list):
            raise TypeError(f"normalized clause atoms missing: {case_id}")
        category_counts.update(str(atom.get("category")) for atom in atoms)
        restored = restore_flat_atomic_v4_3_wire_output(
            result.output,
            result.diagnostics,
        )
        records.append(
            {
                "record_index": record_index,
                "case_id": case_id,
                "v4_3_output": result.output,
                "v4_3_diagnostics": [item.as_dict() for item in result.diagnostics],
                "baseline_analysis": baseline,
                "oracle_analysis": oracle,
                "admission_diagnostics": admissions,
                "output_unchanged_by_oracle": result.output == normalized_before_oracle,
                "v4_3_reverse_restores_frozen_raw": (
                    restored == record["raw_model_output"]
                ),
            }
        )
    return {
        "raw_version": (
            "unified-jd-flat-atomic-v4.3-category-vocabulary-admission-"
            "oracle-raw-v1"
        ),
        "created_at": datetime.now(UTC).isoformat(),
        "status": "revealed_frozen_raw_offline_causal_oracle",
        "experiment_id": EXPERIMENT_ID,
        "baseline": "frozen_raw_with_frozen_v4_3_applied_once_per_response",
        "temporary_validator_only": True,
        "payload_mutation_allowed": False,
        "other_oracle_output_loaded": False,
        "zero_lower_bound_oracle_applied": False,
        "model_call_count": 0,
        "network_call_count": 0,
        "default_parser_call_count": 0,
        "canonicalizer_call_count": 0,
        "v4_3_forward_normalization_count": len(records),
        "input_payload_sha256_before": input_hash_before,
        "input_payload_sha256_after": _json_sha256(frozen_raw),
        "schema_delta_category_only": schema_delta_is_category_only(),
        "category_counts": dict(category_counts),
        "records": records,
        "registered_claim_boundary": preregistration["claim_boundary"],
    }


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
    oracle_valid = {
        record["case_id"]: record["oracle_analysis"]["schema_valid"]
        for record in records
    }
    admissions = [
        {"case_id": record["case_id"], **diagnostic}
        for record in records
        for diagnostic in record["admission_diagnostics"]
    ]
    observed_targets = [
        {
            "case_id": item["case_id"],
            "atom_index": item["atom_index"],
            "path": item["path"],
            "value": item["category"],
        }
        for item in admissions
    ]
    expected_targets = observations["category_targets"]
    recovered = sorted(
        case_id
        for case_id in baseline_valid
        if not baseline_valid[case_id] and oracle_valid[case_id]
    )
    expected_recovered = sorted(
        preregistration["acceptance_gates"]["C3-independent-target-recovery"][
            "required_recovered_case_ids"
        ]
    )
    remaining_invalid = sorted(
        case_id for case_id, valid in oracle_valid.items() if not valid
    )
    expected_remaining = sorted(
        preregistration["acceptance_gates"]["C3-independent-target-recovery"][
            "remaining_invalid_case_ids"
        ]
    )
    remaining_diagnostics = [
        diagnostic
        for record in records
        if not record["oracle_analysis"]["schema_valid"]
        for diagnostic in record["oracle_analysis"]["diagnostics"]
    ]
    v4_3_activation_count = sum(
        len(record["v4_3_diagnostics"]) for record in records
    )
    all_outputs_unchanged = all(
        record["output_unchanged_by_oracle"] for record in records
    )
    reverse_exact = all(
        record["v4_3_reverse_restores_frozen_raw"] for record in records
    )
    input_unchanged = (
        raw["input_payload_sha256_before"] == raw["input_payload_sha256_after"]
    )
    controls = preregistration["controls"]
    in_vocabulary_count = sum(
        count
        for category, count in raw["category_counts"].items()
        if category in FROZEN_CATEGORIES
    )
    zero_minimums = [
        atom["qualifier"]["minimum_months"]
        for record in records
        for atom in record["v4_3_output"]["clause_atoms"]
        if isinstance(atom.get("qualifier"), dict)
        and atom["qualifier"].get("minimum_months") == 0
    ]
    positive_minimums = [
        atom["qualifier"]["minimum_months"]
        for record in records
        for atom in record["v4_3_output"]["clause_atoms"]
        if isinstance(atom.get("qualifier"), dict)
        and type(atom["qualifier"].get("minimum_months")) is int
        and atom["qualifier"]["minimum_months"] > 0
    ]
    checks = {
        "C0-frozen-inputs-isolation-and-zero-calls": {
            "passed": input_unchanged
            and raw["model_call_count"] == 0
            and raw["network_call_count"] == 0
            and raw["default_parser_call_count"] == 0
            and raw["canonicalizer_call_count"] == 0
            and not raw["other_oracle_output_loaded"]
            and not raw["zero_lower_bound_oracle_applied"]
            and raw["v4_3_forward_normalization_count"] == 5,
            "input_payload_unchanged": input_unchanged,
            "model_call_count": raw["model_call_count"],
            "network_call_count": raw["network_call_count"],
        },
        "C1-activation-exactness": {
            "passed": observed_targets == expected_targets
            and len({item["case_id"] for item in admissions}) == 2,
            "actual": observed_targets,
            "required": expected_targets,
        },
        "C2-schema-delta-and-preservation": {
            "passed": raw["schema_delta_category_only"] and all_outputs_unchanged,
            "schema_delta_category_only": raw["schema_delta_category_only"],
            "all_v4_3_outputs_unchanged": all_outputs_unchanged,
            "category_mapping_applied": False,
        },
        "C3-independent-target-recovery": {
            "passed": baseline_valid == observations["v4_3_schema_valid_by_case"]
            and sum(baseline_valid.values()) == 2
            and sum(oracle_valid.values()) == 4
            and recovered == expected_recovered
            and remaining_invalid == expected_remaining
            and len(remaining_diagnostics) == 1
            and remaining_diagnostics[0].get("path")
            == "clause_atoms.27.qualifier.minimum_months"
            and remaining_diagnostics[0].get("code") == "greater_than_equal",
            "baseline_valid_by_case": baseline_valid,
            "oracle_valid_by_case": oracle_valid,
            "recovered_case_ids": recovered,
            "remaining_invalid_case_ids": remaining_invalid,
            "remaining_diagnostics": remaining_diagnostics,
        },
        "C4-controls-and-non-regression": {
            "passed": in_vocabulary_count
            == controls["in_vocabulary_atom_count"]
            and oracle_valid["independent-lever-field-ai-robotics-ai-engineer"]
            and oracle_valid["independent-greenhouse-optiver-ai-engineer"]
            and zero_minimums == [0]
            and positive_minimums == [72]
            and v4_3_activation_count
            == controls["frozen_v4_3_omission_activation_count_must_remain"]
            and reverse_exact
            and all_outputs_unchanged,
            "unchanged_in_vocabulary_atom_count": in_vocabulary_count,
            "zero_minimum_values": zero_minimums,
            "positive_minimum_values": positive_minimums,
            "v4_3_activation_count": v4_3_activation_count,
            "v4_3_reverse_exact": reverse_exact,
        },
    }
    accepted = all(item["passed"] for item in checks.values())
    return {
        "report_version": (
            "unified-jd-flat-atomic-v4.3-category-vocabulary-admission-"
            "oracle-report-v1"
        ),
        "created_at": datetime.now(UTC).isoformat(),
        "status": "one_time_offline_oracle_evaluation",
        "experiment_id": EXPERIMENT_ID,
        "accepted": accepted,
        "decision": (
            "supported_independent_category_vocabulary_mechanism"
            if accepted
            else "not_supported"
        ),
        "baseline_strict_schema_valid_case_count": sum(baseline_valid.values()),
        "oracle_strict_schema_valid_case_count": sum(oracle_valid.values()),
        "strict_schema_case_gain": sum(oracle_valid.values())
        - sum(baseline_valid.values()),
        "checks": checks,
        "model_call_count": 0,
        "network_call_count": 0,
        "v4_3_modified": False,
        "generalization_claim": False,
        "production_mapping_claim": False,
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
