from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
import re
from collections import Counter
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, get_args

from pydantic import ValidationError

from src.domain.unified_jd_extraction import SemanticClauseCategory
from src.evaluation.model_first_v4_3_compatibility import (
    normalize_raw_responses_v4_3,
)
from src.evaluation.model_first_v4_4_compatibility import (
    analyze_raw_responses_v4_4,
    normalize_raw_responses_v4_4,
)
from src.evaluation.model_first_v4_live_probe import (
    UnifiedJDFlatAtomicLiveResponseV4,
    analyze_live_response_v4,
)
from src.services.unified_jd_flat_atomic_v4_2_compatibility import (
    EMPTY_FACT_CODE,
    LONG_EVIDENCE_CODE,
    ROLE_ALIAS_CODE,
)
from src.services.unified_jd_flat_atomic_v4_3_compatibility import (
    normalize_flat_atomic_v4_3_wire_output,
)
from src.services.unified_jd_flat_atomic_v4_4_compatibility import (
    CATEGORY_ALIAS_CODE,
    CATEGORY_ALIASES,
    ZERO_LOWER_BOUND_CODE,
    FlatAtomicV44CompatibilityDiagnostic,
    normalize_flat_atomic_v4_4_wire_output,
    restore_flat_atomic_v4_4_wire_output,
)

ROOT = Path(__file__).resolve().parents[1]
DATE = "2026-09-06"
PREREGISTRATION = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_4_compatibility_preregistration_"
    "v1_2026-09-06.json"
)
PREREGISTRATION_FREEZE = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_4_compatibility_preregistration_"
    "freeze_v1_2026-09-06.json"
)
SOURCE_FREEZE = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_4_compatibility_source_freeze_"
    "v1_2026-09-06.json"
)

DEVELOPMENT_RAW = ROOT / (
    "artifacts/evaluation/unified-jd-flat-atomic-v4-3-independent-holdout-"
    "raw-v1-2026-09-06.json"
)
DEVELOPMENT_SELECTION = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_3_independent_holdout_selection_"
    "v1_2026-09-06.json"
)
DEV20_RAW = ROOT / (
    "artifacts/evaluation/unified-jd-flat-atomic-v4-dev20-raw-v1-2026-09-05.json"
)
LIVE_RAW = ROOT / (
    "artifacts/evaluation/unified-jd-flat-atomic-v4-live-probe-"
    "raw-responses-v1-2026-09-06.json"
)
LIVE_SELECTION = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_live_probe_selection_v1_2026-09-06.json"
)
EXTERNAL_RAW = ROOT / (
    "artifacts/evaluation/unified-jd-flat-atomic-v4-1-external-holdout-"
    "raw-v1-2026-09-06.json"
)
EXTERNAL_SELECTION = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_1_external_holdout_selection_"
    "v1_2026-09-06.json"
)
RUNTIME_ADAPTER = ROOT / (
    "src/services/unified_jd_flat_atomic_v4_4_compatibility.py"
)

DEFAULT_TREATMENT_OUTPUT = ROOT / (
    "artifacts/evaluation/unified-jd-flat-atomic-v4-4-compatibility-"
    "treated-raw-v1-2026-09-06.json"
)
DEFAULT_REPORT_OUTPUT = ROOT / (
    "artifacts/evaluation/unified-jd-flat-atomic-v4-4-compatibility-"
    "report-v1-2026-09-06.json"
)
DEFAULT_RECEIPT_OUTPUT = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_4_compatibility_evaluation_"
    "receipt_v1_2026-09-06.json"
)

EXPECTED_PREREGISTRATION_HASH = (
    "51289285026f2cbebca8e5b012a920bc7f4a7d1f39378ceda7cebef56b0267a7"
)
EXPECTED_PREREGISTRATION_FREEZE_HASH = (
    "23ad4b949e5e5679b108cf47b701564349c482367ab4068c37d368860c5397ac"
)
NEW_CODES = {CATEGORY_ALIAS_CODE, ZERO_LOWER_BOUND_CODE}
FORMAL_CATEGORIES = {"skill", "capability", "experience", "responsibility"}


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


def _selection_sources(selection: dict[str, Any]) -> dict[str, str]:
    return {case["case_id"]: case["raw_content"] for case in selection["cases"]}


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


def _new_diagnostics(result: Any) -> list[FlatAtomicV44CompatibilityDiagnostic]:
    diagnostics = result.diagnostics
    return [
        item
        for item in diagnostics
        if isinstance(item, FlatAtomicV44CompatibilityDiagnostic)
    ]


def _development_gate(
    preregistration: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    raw = _load(DEVELOPMENT_RAW)
    sources = _selection_sources(_load(DEVELOPMENT_SELECTION))
    input_hash = _json_sha256(raw)
    normalized, audit = normalize_raw_responses_v4_4(raw)
    evaluation = analyze_raw_responses_v4_4(raw, sources)
    expected = preregistration["acceptance_gates"]
    baseline_valid: dict[str, bool] = {}
    treatment_valid: dict[str, bool] = {}
    changed: list[dict[str, Any]] = []
    new_counts: Counter[str] = Counter()
    carried_counts: Counter[str] = Counter()
    reverse_count = 0
    unchanged_atom_count = 0
    non_targets_unchanged = True
    facts_unchanged = True

    for record in raw["records"]:
        case_id = record["case_id"]
        v4_3 = normalize_flat_atomic_v4_3_wire_output(record["raw_model_output"])
        v4_4 = normalize_flat_atomic_v4_4_wire_output(record["raw_model_output"])
        baseline_valid[case_id] = bool(
            analyze_live_response_v4(v4_3.output, sources[case_id])["schema_valid"]
        )
        treatment_valid[case_id] = bool(
            analyze_live_response_v4(v4_4.output, sources[case_id])["schema_valid"]
        )
        new_items = _new_diagnostics(v4_4)
        new_counts.update(item.code for item in new_items)
        carried_counts.update(
            item.code for item in v4_4.diagnostics if item.code not in NEW_CODES
        )
        target_indexes = {item.atom_index for item in new_items}
        before_atoms = v4_3.output["clause_atoms"]
        after_atoms = v4_4.output["clause_atoms"]
        for atom_index, (before, after) in enumerate(
            zip(before_atoms, after_atoms, strict=True)
        ):
            atom_paths = _changed_paths(before, after)
            if atom_index not in target_indexes:
                unchanged_atom_count += 1
                non_targets_unchanged = non_targets_unchanged and not atom_paths
        facts_unchanged = (
            facts_unchanged
            and v4_3.output["fact_mentions"] == v4_4.output["fact_mentions"]
        )
        for item in new_items:
            changed.append(
                {
                    "case_id": case_id,
                    "path": item.path,
                    "before": item.before,
                    "after": item.after,
                }
            )
        if (
            restore_flat_atomic_v4_4_wire_output(v4_4.output, v4_4.diagnostics)
            == record["raw_model_output"]
        ):
            reverse_count += 1

    expected_paths = expected["G1-revealed-development-strict-recovery"][
        "required_changed_paths"
    ]
    path_key = lambda item: (item["case_id"], item["path"])
    changed_exact = sorted(changed, key=path_key) == sorted(
        expected_paths, key=path_key
    )
    g1 = {
        "passed": (
            sum(baseline_valid.values()) == 2
            and treatment_valid
            == {case_id: True for case_id in baseline_valid}
            and sum(new_counts.values()) == 3
            and new_counts[CATEGORY_ALIAS_CODE] == 2
            and new_counts[ZERO_LOWER_BOUND_CODE] == 1
            and sum(carried_counts.values()) == 11
            and changed_exact
        ),
        "baseline_strict_valid_case_count": sum(baseline_valid.values()),
        "v4_4_strict_valid_case_count": sum(treatment_valid.values()),
        "baseline_valid_by_case": baseline_valid,
        "v4_4_valid_by_case": treatment_valid,
        "new_activation_counts": dict(new_counts),
        "carried_v4_3_activation_counts": dict(carried_counts),
        "changed_paths": sorted(changed, key=path_key),
        "changed_paths_exactly_registered": changed_exact,
    }
    g2 = {
        "passed": (
            reverse_count == 5
            and unchanged_atom_count == 101
            and non_targets_unchanged
            and facts_unchanged
            and input_hash == _json_sha256(raw)
        ),
        "exact_raw_restoration_case_count": reverse_count,
        "unchanged_atom_count": unchanged_atom_count,
        "non_target_atoms_unchanged": non_targets_unchanged,
        "fact_mentions_unchanged_from_v4_3": facts_unchanged,
        "input_object_unchanged": input_hash == _json_sha256(raw),
    }
    details = {
        "G1": g1,
        "G2": g2,
        "normalized_raw": normalized,
        "audit": audit,
        "evaluation": {
            key: value
            for key, value in evaluation.items()
            if key not in {"normalized_raw", "audit"}
        },
    }
    artifact = {"normalized_raw": normalized, "audit": audit}
    return details, artifact


def _legacy_envelope_gate(
    raw_path: Path,
    selection_path: Path,
    *,
    required_strict_count: int | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    raw = _load(raw_path)
    input_hash = _json_sha256(raw)
    v4_3, v4_3_audit = normalize_raw_responses_v4_3(raw)
    v4_4, v4_4_audit = normalize_raw_responses_v4_4(raw)
    sources = _selection_sources(_load(selection_path))
    evaluation = analyze_raw_responses_v4_4(raw, sources)
    new_counts = Counter(
        item["code"]
        for record in v4_4_audit
        for item in record["diagnostics"]
        if item["code"] in NEW_CODES
    )
    reverse_count = 0
    for record in raw["records"]:
        result = normalize_flat_atomic_v4_4_wire_output(record["raw_model_output"])
        if (
            restore_flat_atomic_v4_4_wire_output(result.output, result.diagnostics)
            == record["raw_model_output"]
        ):
            reverse_count += 1
    strict_count = evaluation["strict_schema_valid_case_count"]
    passed = (
        v4_4 == v4_3
        and v4_4_audit == v4_3_audit
        and sum(new_counts.values()) == 0
        and reverse_count == len(raw["records"])
        and input_hash == _json_sha256(raw)
        and (required_strict_count is None or strict_count == required_strict_count)
    )
    details = {
        "passed": passed,
        "case_count": len(raw["records"]),
        "new_activation_counts": dict(new_counts),
        "output_equal_v4_3": v4_4 == v4_3,
        "audit_equal_v4_3": v4_4_audit == v4_3_audit,
        "strict_schema_valid_case_count": strict_count,
        "exact_reverse_case_count": reverse_count,
        "input_object_unchanged": input_hash == _json_sha256(raw),
    }
    return details, {"normalized_raw": v4_4, "audit": v4_4_audit}


def _dev20_gate() -> tuple[dict[str, Any], dict[str, Any]]:
    raw = _load(DEV20_RAW)
    treated = copy.deepcopy(raw)
    input_hash = _json_sha256(raw)
    new_counts: Counter[str] = Counter()
    strict_count = 0
    reverse_count = 0
    atom_count = 0
    equal_v4_3 = True
    audit: list[dict[str, Any]] = []
    for record_index, (before_record, after_record) in enumerate(
        zip(raw["records"], treated["records"], strict=True)
    ):
        payload = {
            "fact_mentions": [],
            "clause_atoms": before_record["clause_atoms"],
        }
        v4_3 = normalize_flat_atomic_v4_3_wire_output(payload)
        v4_4 = normalize_flat_atomic_v4_4_wire_output(payload)
        after_record["clause_atoms"] = v4_4.output["clause_atoms"]
        new_items = _new_diagnostics(v4_4)
        new_counts.update(item.code for item in new_items)
        equal_v4_3 = equal_v4_3 and v4_4.output == v4_3.output
        if v4_4.diagnostics:
            audit.append(
                {
                    "record_index": record_index,
                    "case_id": before_record["case_id"],
                    "diagnostics": [item.as_dict() for item in v4_4.diagnostics],
                }
            )
        try:
            UnifiedJDFlatAtomicLiveResponseV4.model_validate(v4_4.output)
        except ValidationError:
            pass
        else:
            strict_count += 1
        if restore_flat_atomic_v4_4_wire_output(
            v4_4.output, v4_4.diagnostics
        ) == payload:
            reverse_count += 1
        atom_count += len(v4_4.output["clause_atoms"])
    passed = (
        len(raw["records"]) == 20
        and atom_count == 427
        and strict_count == 20
        and sum(new_counts.values()) == 0
        and equal_v4_3
        and treated == raw
        and reverse_count == 20
        and input_hash == _json_sha256(raw)
    )
    details = {
        "passed": passed,
        "case_count": len(raw["records"]),
        "atom_count": atom_count,
        "new_activation_counts": dict(new_counts),
        "output_equal_v4_3": equal_v4_3,
        "output_equal_frozen_raw": treated == raw,
        "strict_schema_valid_case_count": strict_count,
        "exact_reverse_case_count": reverse_count,
        "input_object_unchanged": input_hash == _json_sha256(raw),
    }
    return details, {"normalized_raw": treated, "audit": audit}


def _atom(
    *,
    role: str = "item",
    category: str = "skill",
    level: str = "required",
    source: str = "target",
    surface: str = "target",
    qualifier: object = None,
) -> dict[str, object]:
    return {
        "role": role,
        "category": category,
        "level": level,
        "relation": "all_of",
        "semantic_item": surface,
        "surface_item": surface,
        "source_text": source,
        "group_name": None,
        "allow_other": False,
        "qualifier": qualifier,
    }


def _zero_atom() -> dict[str, object]:
    source = "0-3 years of AI development experience"
    return _atom(
        category="experience",
        source=source,
        surface=source,
        qualifier={
            "experience_type": "AI development",
            "minimum_months": 0,
            "domain": "AI",
        },
    )


def _empty_fact() -> dict[str, object]:
    return {
        "field": "deadline",
        "raw_items": [],
        "level": None,
        "source_text": "",
    }


def _control_fixtures() -> list[dict[str, Any]]:
    knowledge_source = "Knowledge of cloud platforms"
    motivation_source = "Strong motivation to learn"
    combined = {
        "fact_mentions": [_empty_fact()],
        "clause_atoms": [
            _atom(
                role="responsibility",
                category="responsibility",
                level="mention",
            ),
            _atom(source="x" * 241 + "target"),
            _atom(category="motivation"),
            _zero_atom(),
        ],
    }
    boolean_zero = _zero_atom()
    boolean_zero["qualifier"]["minimum_months"] = False
    wrong_category = _zero_atom()
    wrong_category["category"] = "skill"
    wrong_topology = _zero_atom()
    del wrong_topology["qualifier"]["domain"]
    missing_pattern = _zero_atom()
    missing_pattern["source_text"] = "entry-level AI experience"
    missing_pattern["surface_item"] = "AI experience"
    unanchored = _zero_atom()
    unanchored["surface_item"] = "0-3 years elsewhere"
    positive = _zero_atom()
    positive["qualifier"]["minimum_months"] = 72
    return [
        {
            "name": "knowledge-to-skill",
            "raw": {"fact_mentions": [], "clause_atoms": [_atom(category="knowledge")]},
            "expected": [CATEGORY_ALIAS_CODE],
        },
        {
            "name": "motivation-to-capability",
            "raw": {"fact_mentions": [], "clause_atoms": [_atom(category="motivation")]},
            "expected": [CATEGORY_ALIAS_CODE],
        },
        {
            "name": "explicit-0-to-3-years-to-null",
            "raw": {"fact_mentions": [], "clause_atoms": [_zero_atom()]},
            "expected": [ZERO_LOWER_BOUND_CODE],
        },
        {
            "name": "combined-category-and-zero-with-frozen-v4.3",
            "raw": combined,
            "expected": [
                ROLE_ALIAS_CODE,
                EMPTY_FACT_CODE,
                LONG_EVIDENCE_CODE,
                CATEGORY_ALIAS_CODE,
                ZERO_LOWER_BOUND_CODE,
            ],
        },
        {
            "name": "already-skill-knowledge-source",
            "raw": {
                "fact_mentions": [],
                "clause_atoms": [
                    _atom(category="skill", source=knowledge_source, surface=knowledge_source)
                ],
            },
            "expected": [],
        },
        {
            "name": "already-capability-motivation-source",
            "raw": {
                "fact_mentions": [],
                "clause_atoms": [
                    _atom(
                        category="capability",
                        source=motivation_source,
                        surface=motivation_source,
                    )
                ],
            },
            "expected": [],
        },
        {
            "name": "unknown-category",
            "raw": {"fact_mentions": [], "clause_atoms": [_atom(category="culture")]},
            "expected": [],
        },
        {
            "name": "category-alias-case-mismatch",
            "raw": {"fact_mentions": [], "clause_atoms": [_atom(category="Knowledge")]},
            "expected": [],
        },
        {
            "name": "boolean-zero",
            "raw": {"fact_mentions": [], "clause_atoms": [boolean_zero]},
            "expected": [],
        },
        {
            "name": "zero-wrong-category",
            "raw": {"fact_mentions": [], "clause_atoms": [wrong_category]},
            "expected": [],
        },
        {
            "name": "zero-wrong-qualifier-topology",
            "raw": {"fact_mentions": [], "clause_atoms": [wrong_topology]},
            "expected": [],
        },
        {
            "name": "zero-without-range-pattern",
            "raw": {"fact_mentions": [], "clause_atoms": [missing_pattern]},
            "expected": [],
        },
        {
            "name": "zero-unanchored-surface",
            "raw": {"fact_mentions": [], "clause_atoms": [unanchored]},
            "expected": [],
        },
        {
            "name": "positive-minimum-72",
            "raw": {"fact_mentions": [], "clause_atoms": [positive]},
            "expected": [],
        },
    ]


def _raises_without_mutation(output: object, diagnostics: object) -> bool:
    frozen = copy.deepcopy(output)
    try:
        restore_flat_atomic_v4_4_wire_output(output, diagnostics)
    except (TypeError, ValueError):
        return output == frozen
    return False


def _controls_gate() -> tuple[dict[str, Any], dict[str, Any]]:
    per_control: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []
    for fixture in _control_fixtures():
        raw = fixture["raw"]
        frozen = copy.deepcopy(raw)
        result = normalize_flat_atomic_v4_4_wire_output(raw)
        codes = [item.code for item in result.diagnostics]
        reversed_output = restore_flat_atomic_v4_4_wire_output(
            result.output, result.diagnostics
        )
        passed = (
            codes == fixture["expected"]
            and reversed_output == raw
            and raw == frozen
        )
        if fixture["name"] == "unknown-category":
            unknown_invalid = False
            try:
                UnifiedJDFlatAtomicLiveResponseV4.model_validate(result.output)
            except ValidationError:
                unknown_invalid = True
            passed = passed and unknown_invalid
        per_control.append(
            {
                "name": fixture["name"],
                "passed": passed,
                "diagnostic_codes": codes,
                "expected_diagnostic_codes": fixture["expected"],
                "reverse_restores_input": reversed_output == raw,
                "input_object_unchanged": raw == frozen,
            }
        )
        artifacts.append(
            {
                "name": fixture["name"],
                "input": raw,
                "output": result.output,
                "diagnostics": [item.as_dict() for item in result.diagnostics],
                "restored": reversed_output,
            }
        )

    category = normalize_flat_atomic_v4_4_wire_output(
        {"fact_mentions": [], "clause_atoms": [_atom(category="knowledge")]}
    )
    zero = normalize_flat_atomic_v4_4_wire_output(
        {"fact_mentions": [], "clause_atoms": [_zero_atom()]}
    )
    mismatched = copy.deepcopy(category.output)
    mismatched["clause_atoms"][0]["category"] = "capability"
    duplicate = (*category.diagnostics, category.diagnostics[0])
    fail_closed_checks = {
        "unknown_code": _raises_without_mutation(
            category.output,
            (replace(category.diagnostics[0], code="unknown"),),
        ),
        "wrong_pipeline_order": _raises_without_mutation(
            category.output,
            (replace(category.diagnostics[0], pipeline_order=5),),
        ),
        "duplicate_target": _raises_without_mutation(category.output, duplicate),
        "category_output_mismatch": _raises_without_mutation(
            mismatched, category.diagnostics
        ),
        "zero_evidence_mismatch": _raises_without_mutation(
            zero.output,
            (
                replace(
                    zero.diagnostics[0],
                    source_text="different source",
                ),
            ),
        ),
    }
    empty = {"fact_mentions": [], "clause_atoms": [_atom()]}
    empty_restored = restore_flat_atomic_v4_4_wire_output(empty, ())
    fail_closed_checks["empty_diagnostics_equal_deep_copy"] = (
        empty_restored == empty
        and empty_restored is not empty
        and empty_restored["clause_atoms"] is not empty["clause_atoms"]
    )
    details = {
        "passed": all(item["passed"] for item in per_control)
        and all(fail_closed_checks.values()),
        "control_count": len(per_control),
        "control_names": [item["name"] for item in per_control],
        "per_control": per_control,
        "fail_closed_checks": fail_closed_checks,
    }
    return details, {"controls": artifacts}


def _static_audit() -> dict[str, Any]:
    source = RUNTIME_ADAPTER.read_text(encoding="utf-8")
    tree = ast.parse(source)
    allowed_imports = {
        "__future__",
        "collections.abc",
        "copy",
        "dataclasses",
        "re",
        "typing",
        "src.services.unified_jd_flat_atomic_v4_3_compatibility",
    }
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imports.add(node.module)
    forbidden = re.compile(
        r"(?:api\.deepseek\.com|httpx|requests|urllib|socket|openai|"
        r"canonicalizer|unified_jd_parser|artifacts/evaluation|fixture_id|"
        r"case_id|gold)"
    )
    violations = sorted(imports - allowed_imports)
    if forbidden.search(source):
        violations.append("forbidden_runtime_text")
    return {
        "passed": not violations,
        "checked_path": RUNTIME_ADAPTER.relative_to(ROOT).as_posix(),
        "imports": sorted(imports),
        "violations": violations,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Execute the frozen one-time v4.4 offline compatibility gates"
    )
    parser.add_argument("--treatment-output", type=Path, default=DEFAULT_TREATMENT_OUTPUT)
    parser.add_argument("--report-output", type=Path, default=DEFAULT_REPORT_OUTPUT)
    parser.add_argument("--receipt-output", type=Path, default=DEFAULT_RECEIPT_OUTPUT)
    parser.add_argument("--targeted-tests-passed", action="store_true")
    parser.add_argument("--full-suite-passed", action="store_true")
    return parser.parse_args()


def _preflight(arguments: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    outputs = (
        arguments.treatment_output,
        arguments.report_output,
        arguments.receipt_output,
    )
    if any(path.exists() for path in outputs):
        raise FileExistsError("formal v4.4 artifacts already exist; rerun is forbidden")
    if _sha256(PREREGISTRATION) != EXPECTED_PREREGISTRATION_HASH:
        raise ValueError("v4.4 preregistration hash changed")
    if _sha256(PREREGISTRATION_FREEZE) != EXPECTED_PREREGISTRATION_FREEZE_HASH:
        raise ValueError("v4.4 preregistration freeze hash changed")
    preregistration = _load(PREREGISTRATION)
    preregistration_freeze = _load(PREREGISTRATION_FREEZE)
    source_freeze = _load(SOURCE_FREEZE)
    _verify_references(preregistration["frozen_inputs"])
    _verify_references(preregistration_freeze["artifacts"])
    _verify_references(source_freeze["artifacts"])
    if (
        source_freeze.get("status") != "frozen_before_formal_gate_execution"
        or source_freeze.get("preregistration_sha256")
        != EXPECTED_PREREGISTRATION_HASH
        or source_freeze.get("preregistration_freeze_sha256")
        != EXPECTED_PREREGISTRATION_FREEZE_HASH
    ):
        raise ValueError("v4.4 source freeze is invalid")
    return preregistration, source_freeze


def main() -> int:
    arguments = _parse_args()
    preregistration, source_freeze = _preflight(arguments)
    development, development_artifact = _development_gate(preregistration)
    dev20, dev20_artifact = _dev20_gate()
    live, live_artifact = _legacy_envelope_gate(
        LIVE_RAW,
        LIVE_SELECTION,
        required_strict_count=None,
    )
    external, external_artifact = _legacy_envelope_gate(
        EXTERNAL_RAW,
        EXTERNAL_SELECTION,
        required_strict_count=5,
    )
    controls, controls_artifact = _controls_gate()
    static_audit = _static_audit()

    g0 = {
        "passed": True,
        "all_frozen_hashes_valid": True,
        "source_freeze_valid": True,
        "model_call_count": 0,
        "network_call_count": 0,
        "default_parser_call_count": 0,
        "canonicalizer_call_count": 0,
        "new_holdout_loaded": False,
    }
    g3 = {
        "passed": dev20["passed"] and live["passed"] and external["passed"],
        "legacy_dev20": dev20,
        "legacy_live_probe": live,
        "legacy_external_holdout": external,
    }
    g5 = {
        "passed": (
            CATEGORY_ALIASES == {"knowledge": "skill", "motivation": "capability"}
            and set(get_args(SemanticClauseCategory)) == FORMAL_CATEGORIES
            and preregistration["frozen_observations"]["category_policy_evidence"][
                "knowledge_to_skill_same_batch_analog_count"
            ]
            == 3
            and preregistration["acceptance_gates"][
                "G5-category-policy-and-schema-stability"
            ]["motivation_to_capability_human_control_count"]
            == 1
            and development["G1"]["changed_paths_exactly_registered"]
        ),
        "mapping": CATEGORY_ALIASES,
        "formal_category_vocabulary": sorted(get_args(SemanticClauseCategory)),
        "formal_enum_unchanged": set(get_args(SemanticClauseCategory))
        == FORMAL_CATEGORIES,
        "unknown_category_still_invalid": next(
            item
            for item in controls["per_control"]
            if item["name"] == "unknown-category"
        )["passed"],
        "canonical_items_and_evidence_unchanged": development["G1"][
            "changed_paths_exactly_registered"
        ],
    }
    tests_passed = (
        arguments.targeted_tests_passed and arguments.full_suite_passed
    )
    g6 = {
        "passed": static_audit["passed"] and tests_passed,
        "static_audit": static_audit,
        "targeted_tests_passed": arguments.targeted_tests_passed,
        "full_suite_passed": arguments.full_suite_passed,
        "frozen_source_hashes_valid": True,
    }
    gates = {
        "G0-frozen-inputs-source-isolation-and-zero-calls": g0,
        "G1-revealed-development-strict-recovery": development["G1"],
        "G2-exact-reversibility-and-held-fixed": development["G2"],
        "G3-legacy-zero-regression": g3,
        "G4-fail-closed-controls": controls,
        "G5-category-policy-and-schema-stability": g5,
        "G6-static-audit-and-tests": g6,
    }
    passed = all(gate["passed"] for gate in gates.values())
    generated_at = datetime.now(UTC).isoformat()
    treatment = {
        "treatment_version": "unified-jd-flat-atomic-v4.4-compatibility-treated-raw-v1",
        "generated_at": generated_at,
        "status": "formal_one_time_frozen_offline_treatment",
        "model_call_count": 0,
        "network_call_count": 0,
        "new_holdout_loaded": False,
        "revealed_independent_5": development_artifact,
        "legacy_dev20": dev20_artifact,
        "legacy_live_probe": live_artifact,
        "legacy_external_holdout": external_artifact,
        "controls": controls_artifact,
    }
    _write_new(arguments.treatment_output, treatment)
    report = {
        "report_version": "unified-jd-flat-atomic-v4.4-compatibility-report-v1",
        "generated_at": generated_at,
        "status": "formal_one_time_frozen_offline_gate_evaluation",
        "accepted": passed,
        "decision": (
            "development_qualified_v4_4_candidate" if passed else "gate_failure"
        ),
        "gates": gates,
        "model_call_count": 0,
        "network_call_count": 0,
        "v4_3_modified": False,
        "generalization_claim": False,
        "schema_ontology_expansion_claim": False,
        "claim_boundary": preregistration["claim_boundary"],
        "inputs": {
            "preregistration": _reference(PREREGISTRATION),
            "preregistration_freeze": _reference(PREREGISTRATION_FREEZE),
            "source_freeze": _reference(SOURCE_FREEZE),
            "treatment": _reference(arguments.treatment_output),
        },
    }
    _write_new(arguments.report_output, report)
    receipt = {
        "receipt_version": "unified-jd-flat-atomic-v4.4-compatibility-evaluation-receipt-v1",
        "generated_at": generated_at,
        "status": "formal_execution_complete",
        "formal_execution_count": 1,
        "accepted": passed,
        "source_freeze": _reference(SOURCE_FREEZE),
        "treatment": _reference(arguments.treatment_output),
        "report": _reference(arguments.report_output),
        "model_call_count": 0,
        "network_call_count": 0,
        "new_holdout_loaded": False,
        "source_freeze_verification": source_freeze["pre_freeze_verification"],
    }
    _write_new(arguments.receipt_output, receipt)
    print(
        json.dumps(
            {
                "accepted": passed,
                "decision": report["decision"],
                "development_strict_valid": development["G1"][
                    "v4_4_strict_valid_case_count"
                ],
                "new_activation_counts": development["G1"][
                    "new_activation_counts"
                ],
                "legacy_zero_regression": g3["passed"],
                "treatment": _reference(arguments.treatment_output),
                "report": _reference(arguments.report_output),
                "receipt": _reference(arguments.receipt_output),
                "model_call_count": 0,
                "network_call_count": 0,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
