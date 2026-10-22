from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATE = "2026-09-06"

LIVE_RAW = ROOT / (
    "artifacts/evaluation/"
    "unified-jd-flat-atomic-v4-live-probe-raw-responses-v1-2026-09-06.json"
)
LIVE_REPORT = ROOT / (
    "artifacts/evaluation/"
    "unified-jd-flat-atomic-v4-live-probe-report-v1-2026-09-06.json"
)
COUNTERFACTUAL_REPORT = ROOT / (
    "artifacts/evaluation/"
    "unified-jd-flat-atomic-v4-role-counterfactual-v1-2026-09-06.json"
)
DEV20_RAW = ROOT / (
    "artifacts/evaluation/"
    "unified-jd-flat-atomic-v4-dev20-raw-v1-2026-09-05.json"
)
DEV20_REPORT = ROOT / (
    "artifacts/evaluation/"
    "unified-jd-flat-atomic-v4-dev20-report-v1-2026-09-05.json"
)
LIVE_SELECTION = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_live_probe_selection_v1_2026-09-06.json"
)
LIVE_PREREGISTRATION = ROOT / (
    "datasets/"
    "unified_jd_flat_atomic_v4_live_probe_preregistration_v1_2026-09-06.json"
)
V4_SOURCE_FREEZE = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_source_freeze_v1_2026-09-05.json"
)
LIVE_SOURCE_FREEZE = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_live_probe_source_freeze_v1_2026-09-06.json"
)
V4_DOMAIN = ROOT / "src/domain/unified_jd_flat_atomic_v4.py"
V4_COMPILER = ROOT / "src/services/unified_jd_flat_atomic_v4.py"
LIVE_EVALUATOR = ROOT / "src/evaluation/model_first_v4_live_probe.py"
DEFAULT_PARSER = ROOT / "src/services/unified_jd_parser.py"
CANONICALIZER = ROOT / "src/domain/unified_jd_canonicalizer.py"

PREREGISTRATION = ROOT / (
    "datasets/"
    "unified_jd_flat_atomic_v4_1_compatibility_preregistration_v1_2026-09-06.json"
)
PREREGISTRATION_FREEZE = ROOT / (
    "datasets/"
    "unified_jd_flat_atomic_v4_1_compatibility_preregistration_freeze_v1_2026-09-06.json"
)

IMPLEMENTATION_TARGETS = (
    ROOT / "src/services/unified_jd_flat_atomic_v4_compatibility.py",
    ROOT / "src/evaluation/model_first_v4_1_compatibility.py",
    ROOT / "scripts/evaluate_unified_jd_flat_atomic_v4_1_compatibility_gates.py",
    ROOT / "tests/test_unified_jd_flat_atomic_v4_compatibility.py",
)


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected object: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _reference(path: Path) -> dict[str, str]:
    return {"path": _relative(path), "sha256": _sha256(path)}


def _write_new(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as output:
        json.dump(value, output, ensure_ascii=False, indent=2)
        output.write("\n")


def _observed_basis() -> dict[str, Any]:
    live_raw = _load(LIVE_RAW)
    live_report = _load(LIVE_REPORT)
    counterfactual = _load(COUNTERFACTUAL_REPORT)
    dev20_raw = _load(DEV20_RAW)
    dev20_report = _load(DEV20_REPORT)

    live_atoms = [
        atom
        for record in live_raw["records"]
        for atom in record["raw_model_output"]["clause_atoms"]
    ]
    role_counts: dict[str, int] = {}
    for atom in live_atoms:
        role = atom.get("role")
        role_counts[str(role)] = role_counts.get(str(role), 0) + 1
    eligible = [
        atom
        for atom in live_atoms
        if atom.get("role") == "responsibility"
        and atom.get("category") == "responsibility"
        and atom.get("level") == "mention"
    ]
    responsibility_role_total = sum(
        atom.get("role") == "responsibility" for atom in live_atoms
    )
    dev20_atoms = [
        atom for record in dev20_raw["records"] for atom in record["clause_atoms"]
    ]
    basis = {
        "live_case_count": len(live_raw["records"]),
        "historical_live_model_call_count": live_raw["model_call_count"],
        "live_atom_count": len(live_atoms),
        "live_role_counts": role_counts,
        "eligible_alias_count": len(eligible),
        "responsibility_role_total": responsibility_role_total,
        "eligible_alias_case_count": sum(
            any(
                atom.get("role") == "responsibility"
                and atom.get("category") == "responsibility"
                and atom.get("level") == "mention"
                for atom in record["raw_model_output"]["clause_atoms"]
            )
            for record in live_raw["records"]
        ),
        "live_gate_passed": live_report["passed"],
        "live_target_gate_status": {
            name: live_report["gates"][name]["passed"]
            for name in (
                "G1-json-and-root-topology",
                "G5-granularity-noncollapse",
                "G6-fact-layer-compatibility",
            )
        },
        "counterfactual_changed_field_count": counterfactual["integrity"][
            "changed_field_count"
        ],
        "counterfactual_all_target_gates_recovered": counterfactual[
            "all_target_gates_recovered"
        ],
        "counterfactual_all_gates_passed": counterfactual["counterfactual"][
            "passed"
        ],
        "dev20_case_count": len(dev20_raw["records"]),
        "dev20_atom_count": len(dev20_atoms),
        "dev20_alias_count": sum(
            atom.get("role") == "responsibility" for atom in dev20_atoms
        ),
        "dev20_primary_item_count": sum(
            atom.get("role") == "item" for atom in dev20_atoms
        ),
        "dev20_example_item_count": sum(
            atom.get("role") == "example" for atom in dev20_atoms
        ),
        "dev20_gate_passed": dev20_report["passed"],
    }
    expected = {
        "live_case_count": 5,
        "historical_live_model_call_count": 5,
        "live_atom_count": 183,
        "live_role_counts": {"item": 155, "example": 10, "responsibility": 18},
        "eligible_alias_count": 18,
        "responsibility_role_total": 18,
        "eligible_alias_case_count": 1,
        "live_gate_passed": False,
        "live_target_gate_status": {
            "G1-json-and-root-topology": False,
            "G5-granularity-noncollapse": False,
            "G6-fact-layer-compatibility": False,
        },
        "counterfactual_changed_field_count": 18,
        "counterfactual_all_target_gates_recovered": True,
        "counterfactual_all_gates_passed": True,
        "dev20_case_count": 20,
        "dev20_atom_count": 427,
        "dev20_alias_count": 0,
        "dev20_primary_item_count": 394,
        "dev20_example_item_count": 33,
        "dev20_gate_passed": True,
    }
    if basis != expected:
        raise ValueError(f"observed compatibility basis changed: {basis!r}")
    return basis


def main() -> int:
    outputs = (PREREGISTRATION, PREREGISTRATION_FREEZE)
    existing_outputs = [str(path) for path in outputs if path.exists()]
    if existing_outputs:
        raise FileExistsError(f"preregistration already exists: {existing_outputs}")
    existing_targets = [str(path) for path in IMPLEMENTATION_TARGETS if path.exists()]
    if existing_targets:
        raise FileExistsError(
            f"implementation exists before preregistration: {existing_targets}"
        )

    input_paths = {
        "live_raw": LIVE_RAW,
        "live_report": LIVE_REPORT,
        "counterfactual_report": COUNTERFACTUAL_REPORT,
        "dev20_raw": DEV20_RAW,
        "dev20_report": DEV20_REPORT,
        "live_selection": LIVE_SELECTION,
        "live_preregistration": LIVE_PREREGISTRATION,
        "v4_source_freeze": V4_SOURCE_FREEZE,
        "live_source_freeze": LIVE_SOURCE_FREEZE,
        "v4_domain": V4_DOMAIN,
        "v4_compiler": V4_COMPILER,
        "live_evaluator": LIVE_EVALUATOR,
        "default_parser": DEFAULT_PARSER,
        "canonicalizer": CANONICALIZER,
    }
    missing = [str(path) for path in input_paths.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"missing preregistration inputs: {missing}")
    basis = _observed_basis()
    preregistration = {
        "preregistration_version": (
            "unified-jd-flat-atomic-v4.1-compatibility-preregistration-v1"
        ),
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "preregistered_after_revealed_probe_before_implementation",
        "objective": (
            "Implement one narrow wire-compatibility alias for responsibility atoms "
            "without changing frozen v4 semantics, parsers, canonicalizers, or gates."
        ),
        "evidence_status": (
            "The five-case live probe is revealed development evidence. This is an "
            "implementation regression, not a new blind causal experiment."
        ),
        "frozen_inputs": {
            name: _reference(path) for name, path in input_paths.items()
        },
        "observed_basis": basis,
        "intervention": {
            "activation": {
                "role": "responsibility",
                "category": "responsibility",
                "level": "mention",
            },
            "replacement": {"role": "item"},
            "allowed_changed_field": "role",
            "must_deep_copy_input": True,
            "must_emit_diagnostic": "normalized_responsibility_role_alias",
            "must_not_use": [
                "case or fixture identifiers",
                "job text patterns",
                "gold labels",
                "company, title, URL, or source origin",
                "model or network calls",
            ],
            "fail_closed": [
                "role=responsibility with a non-responsibility category",
                "role=responsibility with a non-mention level",
                "every other invalid role value",
            ],
        },
        "scope": {
            "new_model_calls_allowed": 0,
            "network_calls_allowed": 0,
            "frozen_v4_modification_allowed": False,
            "default_parser_modification_allowed": False,
            "canonicalizer_modification_allowed": False,
            "live_raw_overwrite_allowed": False,
            "dev20_raw_overwrite_allowed": False,
            "threshold_changes_allowed": False,
        },
        "acceptance_gates": {
            "G0-frozen-inputs-and-zero-calls": {
                "all_input_hashes_match": True,
                "new_model_call_count": 0,
                "network_call_count": 0,
            },
            "G1-exact-activation-and-audit": {
                "changed_field_count": 18,
                "changed_case_count": 1,
                "changed_fields": ["role"],
                "diagnostic_code": "normalized_responsibility_role_alias",
                "reverse_transform_restores_frozen_raw": True,
            },
            "G2-live-probe-recovery": {
                "all_original_G0_through_G7_must_pass": True,
                "schema_valid_case_count": 5,
                "aggregate_primary_atom_count": 173,
                "fact_compatible_case_count": 5,
            },
            "G3-dev20-exact-non-regression": {
                "activation_count": 0,
                "case_count": 20,
                "atom_count": 427,
                "primary_item_count": 394,
                "example_item_count": 33,
                "normalized_payloads_equal_inputs": True,
            },
            "G4-fail-closed-controls": {
                "eligible_alias_normalized": True,
                "valid_responsibility_item_unchanged": True,
                "responsibility_alias_with_skill_category_rejected": True,
                "responsibility_alias_with_required_level_rejected": True,
                "example_unchanged": True,
            },
            "G5-isolation-and-static-audit": {
                "frozen_v4_hashes_unchanged": True,
                "default_parser_hash_unchanged": True,
                "canonicalizer_hash_unchanged": True,
                "runtime_fixture_ids_forbidden": True,
                "runtime_model_network_and_canonicalizer_imports_forbidden": True,
            },
            "G6-tests": {
                "targeted_tests_must_pass": True,
                "full_suite_must_pass": True,
            },
        },
        "execution_protocol": {
            "source_freeze_before_gate_execution": True,
            "formal_gate_run_count": 1,
            "rerun_after_failure_allowed": False,
            "write_new_report_only": True,
            "all_gates_conjunctive": True,
        },
        "decision": {
            "on_pass": (
                "Keep v4.1 as an opt-in wire compatibility boundary. Treat the five "
                "revealed cases as development data; require a fresh holdout before a "
                "generalization claim."
            ),
            "on_fail": (
                "Do not activate v4.1. Preserve the failed report and diagnose offline."
            ),
        },
    }
    _write_new(PREREGISTRATION, preregistration)
    freeze = {
        "freeze_version": (
            "unified-jd-flat-atomic-v4.1-compatibility-preregistration-freeze-v1"
        ),
        "frozen_at": datetime.now(UTC).isoformat(),
        "status": "frozen_before_implementation",
        "artifacts": {
            "preregistration": _reference(PREREGISTRATION),
            "builder": _reference(Path(__file__).resolve()),
        },
        "frozen_inputs": preregistration["frozen_inputs"],
        "implementation_targets_existed_at_freeze": False,
        "new_model_call_count": 0,
        "network_call_count": 0,
    }
    _write_new(PREREGISTRATION_FREEZE, freeze)
    print(
        "v4.1 compatibility preregistered "
        f"eligible={basis['eligible_alias_count']} dev20={basis['dev20_atom_count']}"
    )
    print(f"preregistration={PREREGISTRATION}")
    print(f"freeze={PREREGISTRATION_FREEZE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
