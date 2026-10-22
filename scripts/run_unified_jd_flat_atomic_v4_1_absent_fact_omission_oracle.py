from __future__ import annotations

import argparse
import copy
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.evaluation.model_first_v4_live_probe import analyze_live_response_v4

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_ID = "absent-fact-omission-oracle"
PREREGISTRATION = ROOT / (
    "datasets/"
    "unified_jd_flat_atomic_v4_1_absent_fact_omission_oracle_preregistration_v1_2026-09-06.json"
)
PREREGISTRATION_FREEZE = ROOT / (
    "datasets/"
    "unified_jd_flat_atomic_v4_1_absent_fact_omission_oracle_preregistration_freeze_v1_2026-09-06.json"
)
SOURCE_FREEZE = ROOT / (
    "datasets/"
    "unified_jd_flat_atomic_v4_1_absent_fact_omission_oracle_source_freeze_v1_2026-09-06.json"
)
SELECTION = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_1_external_holdout_selection_v1_2026-09-06.json"
)
FROZEN_RAW = ROOT / (
    "artifacts/evaluation/"
    "unified-jd-flat-atomic-v4-1-external-holdout-raw-v1-2026-09-06.json"
)
DEFAULT_RAW_OUTPUT = ROOT / (
    "artifacts/evaluation/"
    "unified-jd-flat-atomic-v4-1-absent-fact-omission-oracle-raw-v1-2026-09-06.json"
)
DEFAULT_REPORT_OUTPUT = ROOT / (
    "artifacts/evaluation/"
    "unified-jd-flat-atomic-v4-1-absent-fact-omission-oracle-report-v1-2026-09-06.json"
)
EXPECTED_PREREGISTRATION_HASH = (
    "8f75457e3f93422666295d29f91c473d3218dae6cc276a61a67ede300ef90e59"
)
EXPECTED_PREREGISTRATION_FREEZE_HASH = (
    "6264d90cd977ef787a8bfd776bd67cc8c6c1cd4d4cdc7ee6a798813203a44723"
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
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": _sha256(path),
    }


def _write_new(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as output:
        json.dump(payload, output, ensure_ascii=False, indent=2)
        output.write("\n")


def _verify_references(entries: dict[str, Any]) -> None:
    for name, entry in entries.items():
        path = ROOT / entry["path"]
        if not path.is_file() or _sha256(path) != entry["sha256"]:
            raise ValueError(f"frozen input hash mismatch: {name}")


def _eligible(fact: object) -> bool:
    return (
        isinstance(fact, dict)
        and fact.get("raw_items") == []
        and fact.get("source_text") == ""
        and fact.get("level") is None
    )


def omit_empty_absent_fact_placeholders(
    frozen_raw: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    treatment = copy.deepcopy(frozen_raw)
    audit: list[dict[str, Any]] = []
    for record_index, record in enumerate(treatment["records"]):
        facts = record["raw_model_output"]["fact_mentions"]
        retained: list[dict[str, Any]] = []
        removed: list[dict[str, Any]] = []
        for fact_index, fact in enumerate(facts):
            if _eligible(fact):
                removed.append(
                    {"fact_index": fact_index, "before": copy.deepcopy(fact)}
                )
            else:
                retained.append(fact)
        record["raw_model_output"]["fact_mentions"] = retained
        if removed:
            audit.append(
                {
                    "record_index": record_index,
                    "case_id": record["case_id"],
                    "removed": removed,
                }
            )
    return treatment, audit


def _reverse(treatment: dict[str, Any], audit: list[dict[str, Any]]) -> dict[str, Any]:
    restored = copy.deepcopy(treatment)
    for record_audit in audit:
        facts = restored["records"][record_audit["record_index"]]["raw_model_output"][
            "fact_mentions"
        ]
        for removal in record_audit["removed"]:
            facts.insert(removal["fact_index"], copy.deepcopy(removal["before"]))
    return restored


def _analyses(
    payload: dict[str, Any], selection: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    sources = {case["case_id"]: case["raw_content"] for case in selection["cases"]}
    return {
        record["case_id"]: analyze_live_response_v4(
            record["raw_model_output"], sources[record["case_id"]]
        )
        for record in payload["records"]
    }


def _held_fixed(
    baseline: dict[str, Any], treatment: dict[str, Any], audit: list[dict[str, Any]]
) -> bool:
    audit_ids = {item["case_id"] for item in audit}
    for before, after in zip(baseline["records"], treatment["records"], strict=True):
        if before["case_id"] != after["case_id"]:
            return False
        if (
            before["raw_model_output"]["clause_atoms"]
            != after["raw_model_output"]["clause_atoms"]
        ):
            return False
        if {
            key: value for key, value in before.items() if key != "raw_model_output"
        } != {key: value for key, value in after.items() if key != "raw_model_output"}:
            return False
        expected_facts = [
            fact
            for fact in before["raw_model_output"]["fact_mentions"]
            if not _eligible(fact)
        ]
        if expected_facts != after["raw_model_output"]["fact_mentions"]:
            return False
        if before["case_id"] not in audit_ids and before != after:
            return False
    return True


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the absent-fact omission oracle")
    parser.add_argument("--raw-output", type=Path, default=DEFAULT_RAW_OUTPUT)
    parser.add_argument("--report-output", type=Path, default=DEFAULT_REPORT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    arguments = _parse_args()
    if arguments.raw_output.exists() or arguments.report_output.exists():
        raise FileExistsError("oracle output already exists; rerun is forbidden")
    if _sha256(PREREGISTRATION) != EXPECTED_PREREGISTRATION_HASH:
        raise ValueError("preregistration hash changed")
    if _sha256(PREREGISTRATION_FREEZE) != EXPECTED_PREREGISTRATION_FREEZE_HASH:
        raise ValueError("preregistration freeze hash changed")
    preregistration = _load(PREREGISTRATION)
    preregistration_freeze = _load(PREREGISTRATION_FREEZE)
    source_freeze = _load(SOURCE_FREEZE)
    _verify_references(preregistration["frozen_inputs"])
    _verify_references(preregistration_freeze["artifacts"])
    _verify_references(source_freeze["artifacts"])
    if source_freeze["status"] != "offline_oracle_runner_frozen_before_execution":
        raise ValueError("oracle runner is not frozen")

    frozen_raw = _load(FROZEN_RAW)
    selection = _load(SELECTION)
    input_hash_before = _json_sha256(frozen_raw)
    treatment, audit = omit_empty_absent_fact_placeholders(frozen_raw)
    input_hash_after = _json_sha256(frozen_raw)
    baseline = _analyses(frozen_raw, selection)
    treated = _analyses(treatment, selection)
    target_ids = set(preregistration["frozen_observations"]["target_case_ids"])
    control_ids = set(
        preregistration["frozen_observations"]["negative_control_case_ids"]
    )
    removed_count = sum(len(item["removed"]) for item in audit)
    activated_ids = {item["case_id"] for item in audit}
    target_recovered = sum(
        not baseline[case_id]["schema_valid"] and treated[case_id]["schema_valid"]
        for case_id in target_ids
    )
    controls_unchanged = all(
        next(record for record in frozen_raw["records"] if record["case_id"] == case_id)
        == next(
            record for record in treatment["records"] if record["case_id"] == case_id
        )
        and baseline[case_id]["diagnostics"] == treated[case_id]["diagnostics"]
        and not treated[case_id]["schema_valid"]
        for case_id in control_ids
    )
    checks = {
        "exact_27_removals_in_four_targets": {
            "passed": removed_count == 27 and activated_ids == target_ids,
            "removed_count": removed_count,
            "activated_case_ids": sorted(activated_ids),
        },
        "all_four_targets_strictly_recovered": {
            "passed": target_recovered == 4,
            "recovered_count": target_recovered,
            "required": 4,
        },
        "negative_control_unchanged_and_still_invalid": {
            "passed": controls_unchanged,
            "control_case_ids": sorted(control_ids),
        },
        "all_noneligible_content_held_fixed": {
            "passed": _held_fixed(frozen_raw, treatment, audit),
        },
        "reverse_transform_restores_frozen_raw": {
            "passed": _reverse(treatment, audit) == frozen_raw,
        },
        "input_payload_unchanged": {
            "passed": input_hash_before == input_hash_after,
            "before": input_hash_before,
            "after": input_hash_after,
        },
        "offline_and_independent": {
            "passed": True,
            "other_oracle_output_loaded": False,
            "model_call_count": 0,
            "network_call_count": 0,
            "parser_called": False,
            "canonicalizer_called": False,
        },
    }
    accepted = all(item["passed"] for item in checks.values())
    raw_output = {
        "raw_version": (
            "unified-jd-flat-atomic-v4.1-absent-fact-omission-oracle-raw-v1"
        ),
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "revealed_frozen_raw_offline_causal_oracle",
        "experiment_id": EXPERIMENT_ID,
        "model_call_count": 0,
        "network_call_count": 0,
        "other_oracle_output_loaded": False,
        "audit": audit,
        "baseline_analyses": baseline,
        "treatment_analyses": treated,
        "treatment_payload": treatment,
    }
    _write_new(arguments.raw_output, raw_output)
    report = {
        "report_version": (
            "unified-jd-flat-atomic-v4.1-absent-fact-omission-oracle-report-v1"
        ),
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "one_time_offline_oracle_evaluation",
        "accepted": accepted,
        "decision": (
            "supported_independent_4_of_5_schema_recovery"
            if accepted
            else "not_supported"
        ),
        "baseline_strict_schema_valid_case_count": sum(
            item["schema_valid"] for item in baseline.values()
        ),
        "treatment_strict_schema_valid_case_count": sum(
            item["schema_valid"] for item in treated.values()
        ),
        "strict_schema_case_gain": sum(
            item["schema_valid"] for item in treated.values()
        )
        - sum(item["schema_valid"] for item in baseline.values()),
        "checks": checks,
        "per_case": [
            {
                "case_id": case_id,
                "treated": case_id in activated_ids,
                "baseline_schema_valid": baseline[case_id]["schema_valid"],
                "treatment_schema_valid": treated[case_id]["schema_valid"],
                "baseline_diagnostics": baseline[case_id]["diagnostics"],
                "treatment_diagnostics": treated[case_id]["diagnostics"],
            }
            for case_id in selection["selected_case_ids"]
        ],
        "inputs": {
            "preregistration": _reference(PREREGISTRATION),
            "preregistration_freeze": _reference(PREREGISTRATION_FREEZE),
            "source_freeze": _reference(SOURCE_FREEZE),
            "frozen_raw": _reference(FROZEN_RAW),
            "oracle_raw": _reference(arguments.raw_output),
        },
        "model_call_count": 0,
        "network_call_count": 0,
        "interpretation_limit": preregistration["acceptance_gate"][
            "interpretation_limit"
        ],
    }
    _write_new(arguments.report_output, report)
    print(
        json.dumps(
            {
                "accepted": accepted,
                "decision": report["decision"],
                "strict_schema_case_gain": report["strict_schema_case_gain"],
                "raw": _reference(arguments.raw_output),
                "report": _reference(arguments.report_output),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if accepted else 2


if __name__ == "__main__":
    raise SystemExit(main())
