from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from src.domain.unified_jd_flat_atomic_v4 import UnifiedJDFlatAtomicClauseV4
from src.evaluation.model_first_v4_1_compatibility import (
    evaluate_live_probe_v4_1,
    normalize_live_probe_raw_responses_v4_1,
)
from src.evaluation.model_first_v4_live_probe import (
    UnifiedJDFlatAtomicLiveResponseV4,
)
from src.services.unified_jd_flat_atomic_v4_compatibility import (
    normalize_flat_atomic_v4_wire_output,
)

ROOT = Path(__file__).resolve().parents[1]
DATE = "2026-09-06"
PREREGISTRATION = ROOT / (
    "datasets/"
    "unified_jd_flat_atomic_v4_1_compatibility_preregistration_v1_2026-09-06.json"
)
PREREGISTRATION_FREEZE = ROOT / (
    "datasets/"
    "unified_jd_flat_atomic_v4_1_compatibility_preregistration_freeze_v1_2026-09-06.json"
)
SOURCE_FREEZE = ROOT / (
    "datasets/"
    "unified_jd_flat_atomic_v4_1_compatibility_source_freeze_v1_2026-09-06.json"
)
LIVE_RAW = ROOT / (
    "artifacts/evaluation/"
    "unified-jd-flat-atomic-v4-live-probe-raw-responses-v1-2026-09-06.json"
)
LIVE_SELECTION = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_live_probe_selection_v1_2026-09-06.json"
)
LIVE_PREREGISTRATION = ROOT / (
    "datasets/"
    "unified_jd_flat_atomic_v4_live_probe_preregistration_v1_2026-09-06.json"
)
DEV20_RAW = ROOT / (
    "artifacts/evaluation/"
    "unified-jd-flat-atomic-v4-dev20-raw-v1-2026-09-05.json"
)
DEFAULT_OUTPUT = ROOT / (
    "artifacts/evaluation/"
    "unified-jd-flat-atomic-v4-1-compatibility-report-v1-2026-09-06.json"
)
RUNTIME_SOURCES = (
    ROOT / "src/services/unified_jd_flat_atomic_v4_compatibility.py",
    ROOT / "src/evaluation/model_first_v4_1_compatibility.py",
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


def _verify_references(entries: dict[str, Any]) -> None:
    for name, entry in entries.items():
        path = ROOT / entry["path"]
        if not path.is_file() or _sha256(path) != entry["sha256"]:
            raise ValueError(f"frozen artifact hash mismatch: {name}")


def _restore_live_roles(
    normalized: dict[str, Any], audit: list[dict[str, Any]]
) -> dict[str, Any]:
    restored = copy.deepcopy(normalized)
    records = restored["records"]
    for record_audit in audit:
        record = records[record_audit["record_index"]]
        for diagnostic in record_audit["diagnostics"]:
            record["raw_model_output"]["clause_atoms"][
                diagnostic["atom_index"]
            ]["role"] = diagnostic["before_role"]
    return restored


def _dev20_gate(dev20: dict[str, Any]) -> dict[str, Any]:
    activation_count = 0
    normalized_equal = True
    validated_atom_count = 0
    atoms: list[dict[str, Any]] = []
    for record in dev20["records"]:
        payload = {
            "fact_mentions": [],
            "clause_atoms": record["clause_atoms"],
        }
        result = normalize_flat_atomic_v4_wire_output(payload)
        activation_count += result.activation_count
        normalized_equal = normalized_equal and result.output == payload
        for atom in record["clause_atoms"]:
            UnifiedJDFlatAtomicClauseV4.model_validate(atom)
            validated_atom_count += 1
            atoms.append(atom)
    primary_count = sum(atom["role"] == "item" for atom in atoms)
    example_count = sum(atom["role"] == "example" for atom in atoms)
    passed = (
        len(dev20["records"]) == 20
        and len(atoms) == 427
        and validated_atom_count == 427
        and primary_count == 394
        and example_count == 33
        and activation_count == 0
        and normalized_equal
    )
    return {
        "passed": passed,
        "case_count": len(dev20["records"]),
        "atom_count": len(atoms),
        "validated_atom_count": validated_atom_count,
        "primary_item_count": primary_count,
        "example_item_count": example_count,
        "activation_count": activation_count,
        "normalized_payloads_equal_inputs": normalized_equal,
    }


def _control_atom(
    *, role: str, category: str = "responsibility", level: str = "mention"
) -> dict[str, Any]:
    return {
        "role": role,
        "category": category,
        "level": level,
        "relation": "all_of",
        "semantic_item": "design secure systems",
        "surface_item": "design secure systems",
        "source_text": "design secure systems",
        "group_name": None,
        "allow_other": False,
        "qualifier": None,
    }


def _control_result(
    *, role: str, category: str = "responsibility", level: str = "mention"
) -> tuple[object, int, bool]:
    raw = {
        "fact_mentions": [],
        "clause_atoms": [
            _control_atom(role=role, category=category, level=level)
        ],
    }
    result = normalize_flat_atomic_v4_wire_output(raw)
    try:
        UnifiedJDFlatAtomicLiveResponseV4.model_validate(result.output)
    except ValidationError:
        schema_valid = False
    else:
        schema_valid = True
    return result.output, result.activation_count, schema_valid


def _control_gate() -> dict[str, Any]:
    eligible_output, eligible_count, eligible_valid = _control_result(
        role="responsibility"
    )
    item_output, item_count, item_valid = _control_result(role="item")
    skill_output, skill_count, skill_valid = _control_result(
        role="responsibility", category="skill"
    )
    required_output, required_count, required_valid = _control_result(
        role="responsibility", level="required"
    )
    example_output, example_count, example_valid = _control_result(
        role="example", category="skill", level="required"
    )
    checks = {
        "eligible_alias_normalized": (
            eligible_output["clause_atoms"][0]["role"] == "item"
            and eligible_count == 1
            and eligible_valid
        ),
        "valid_responsibility_item_unchanged": (
            item_output["clause_atoms"][0]["role"] == "item"
            and item_count == 0
            and item_valid
        ),
        "responsibility_alias_with_skill_category_rejected": (
            skill_output["clause_atoms"][0]["role"] == "responsibility"
            and skill_count == 0
            and not skill_valid
        ),
        "responsibility_alias_with_required_level_rejected": (
            required_output["clause_atoms"][0]["role"] == "responsibility"
            and required_count == 0
            and not required_valid
        ),
        "example_unchanged": (
            example_output["clause_atoms"][0]["role"] == "example"
            and example_count == 0
            and example_valid
        ),
    }
    return {"passed": all(checks.values()), **checks}


def _static_audit() -> dict[str, Any]:
    forbidden_import = re.compile(
        r"(?m)^\s*(?:from|import)\s+"
        r"(?:httpx|requests|urllib|socket|openai|"
        r"src\.infrastructure\.llm_client|"
        r"src\.domain\.unified_jd_canonicalizer)\b"
    )
    fixture_id = re.compile(r"(?:campus-ai|structured-|surface-holdout)-\d+")
    violations: list[dict[str, str]] = []
    for path in RUNTIME_SOURCES:
        source = path.read_text(encoding="utf-8")
        if forbidden_import.search(source):
            violations.append(
                {"path": path.relative_to(ROOT).as_posix(), "code": "forbidden_import"}
            )
        if fixture_id.search(source):
            violations.append(
                {"path": path.relative_to(ROOT).as_posix(), "code": "fixture_id"}
            )
    return {
        "passed": not violations,
        "checked_paths": [path.relative_to(ROOT).as_posix() for path in RUNTIME_SOURCES],
        "violations": violations,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Execute frozen v4.1 responsibility-role compatibility gates"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--targeted-tests-passed", action="store_true")
    parser.add_argument("--full-suite-passed", action="store_true")
    return parser.parse_args()


def main() -> int:
    arguments = _parse_args()
    if arguments.output.exists():
        raise FileExistsError(f"formal report already exists: {arguments.output}")
    preregistration = _load(PREREGISTRATION)
    preregistration_freeze = _load(PREREGISTRATION_FREEZE)
    source_freeze = _load(SOURCE_FREEZE)
    if source_freeze.get("status") != "frozen_before_formal_gate_execution":
        raise ValueError("invalid source freeze status")
    if source_freeze.get("preregistration_sha256") != _sha256(PREREGISTRATION):
        raise ValueError("source freeze points to a different preregistration")
    _verify_references(preregistration["frozen_inputs"])
    _verify_references(preregistration_freeze["artifacts"])
    _verify_references(source_freeze["artifacts"])

    live_raw = _load(LIVE_RAW)
    normalized, audit = normalize_live_probe_raw_responses_v4_1(live_raw)
    diagnostics = [
        diagnostic
        for record in audit
        for diagnostic in record["diagnostics"]
    ]
    reverse_restores_raw = _restore_live_roles(normalized, audit) == live_raw
    exact_audit = (
        len(diagnostics) == 18
        and len(audit) == 1
        and all(
            item == {
                "path": f"clause_atoms[{item['atom_index']}].role",
                "atom_index": item["atom_index"],
                "code": "normalized_responsibility_role_alias",
                "before_role": "responsibility",
                "after_role": "item",
            }
            for item in diagnostics
        )
    )
    live = evaluate_live_probe_v4_1(
        _load(LIVE_SELECTION),
        _load(LIVE_PREREGISTRATION),
        live_raw,
        frozen_inputs_valid=True,
        frozen_sources_valid=True,
    )
    live_gates = live["gates"]
    g2_passed = (
        live["passed"]
        and all(gate["passed"] for gate in live_gates.values())
        and live_gates["G1-json-and-root-topology"]["schema_valid_case_count"] == 5
        and live_gates["G5-granularity-noncollapse"]["primary_atom_count"] == 173
        and live_gates["G6-fact-layer-compatibility"]["compatible_case_count"] == 5
    )
    static_audit = _static_audit()
    gates = {
        "G0-frozen-inputs-and-zero-calls": {
            "passed": True,
            "frozen_input_hashes_valid": True,
            "frozen_source_hashes_valid": True,
            "new_model_call_count": 0,
            "network_call_count": 0,
            "source_model_call_count": live_raw["model_call_count"],
        },
        "G1-exact-activation-and-audit": {
            "passed": exact_audit and reverse_restores_raw,
            "changed_field_count": len(diagnostics),
            "changed_record_count": len(audit),
            "diagnostic_codes": sorted({item["code"] for item in diagnostics}),
            "reverse_transform_restores_frozen_raw": reverse_restores_raw,
            "audit": audit,
        },
        "G2-live-probe-recovery": {
            "passed": g2_passed,
            "all_v4_gates_passed": all(
                gate["passed"] for gate in live_gates.values()
            ),
            "schema_valid_case_count": live_gates[
                "G1-json-and-root-topology"
            ]["schema_valid_case_count"],
            "aggregate_primary_atom_count": live_gates[
                "G5-granularity-noncollapse"
            ]["primary_atom_count"],
            "fact_compatible_case_count": live_gates[
                "G6-fact-layer-compatibility"
            ]["compatible_case_count"],
            "underlying_gates": live_gates,
        },
        "G3-dev20-exact-non-regression": _dev20_gate(_load(DEV20_RAW)),
        "G4-fail-closed-controls": _control_gate(),
        "G5-isolation-and-static-audit": {
            "passed": static_audit["passed"],
            "frozen_v4_and_dependencies_unchanged": True,
            "static_audit": static_audit,
        },
        "G6-tests": {
            "passed": (
                arguments.targeted_tests_passed and arguments.full_suite_passed
            ),
            "targeted_tests_passed": arguments.targeted_tests_passed,
            "full_suite_passed": arguments.full_suite_passed,
        },
    }
    report = {
        "report_version": (
            "unified-jd-flat-atomic-v4.1-compatibility-report-v1"
        ),
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "formal_one_time_frozen_gate_execution",
        "passed": all(gate["passed"] for gate in gates.values()),
        "new_model_call_count": 0,
        "network_call_count": 0,
        "source_model_call_count": live_raw["model_call_count"],
        "parser_modified": False,
        "canonicalizer_modified": False,
        "gates": gates,
        "inputs": {
            "preregistration": _reference(PREREGISTRATION),
            "preregistration_freeze": _reference(PREREGISTRATION_FREEZE),
            "source_freeze": _reference(SOURCE_FREEZE),
            "live_raw": _reference(LIVE_RAW),
            "dev20_raw": _reference(DEV20_RAW),
        },
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    with arguments.output.open("x", encoding="utf-8", newline="\n") as output:
        json.dump(report, output, ensure_ascii=False, indent=2)
        output.write("\n")
    print(
        json.dumps(
            {
                "output": _reference(arguments.output),
                "passed": report["passed"],
                "gates": {
                    name: result["passed"] for name, result in gates.items()
                },
                "new_model_call_count": 0,
                "network_call_count": 0,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
