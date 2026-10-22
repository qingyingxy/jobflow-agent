from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from src.evaluation.model_first_v4_1_compatibility import (
    evaluate_live_probe_v4_1,
    normalize_live_probe_raw_responses_v4_1,
)
from src.evaluation.model_first_v4_2_compatibility import (
    evaluate_live_probe_v4_2,
    normalize_raw_responses_v4_2,
)
from src.evaluation.model_first_v4_live_probe import (
    UnifiedJDFlatAtomicLiveResponseV4,
    analyze_live_response_v4,
)
from src.services.unified_jd_flat_atomic_v4_2_compatibility import (
    DIAGNOSTIC_CODES,
    EMPTY_FACT_CODE,
    LONG_EVIDENCE_CODE,
    ROLE_ALIAS_CODE,
    normalize_flat_atomic_v4_2_wire_output,
    restore_flat_atomic_v4_2_wire_output,
)

ROOT = Path(__file__).resolve().parents[1]
PREREGISTRATION = ROOT / (
    "datasets/"
    "unified_jd_flat_atomic_v4_2_compatibility_preregistration_v1_2026-09-06.json"
)
PREREGISTRATION_FREEZE = ROOT / (
    "datasets/"
    "unified_jd_flat_atomic_v4_2_compatibility_preregistration_freeze_v1_2026-09-06.json"
)
SOURCE_FREEZE = ROOT / (
    "datasets/"
    "unified_jd_flat_atomic_v4_2_compatibility_source_freeze_v1_2026-09-06.json"
)
EXTERNAL_RAW = ROOT / (
    "artifacts/evaluation/"
    "unified-jd-flat-atomic-v4-1-external-holdout-raw-v1-2026-09-06.json"
)
EXTERNAL_SELECTION = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_1_external_holdout_selection_v1_2026-09-06.json"
)
EXTERNAL_PREREGISTRATION = ROOT / (
    "datasets/"
    "unified_jd_flat_atomic_v4_1_external_holdout_preregistration_v1_2026-09-06.json"
)
LIVE_RAW = ROOT / (
    "artifacts/evaluation/"
    "unified-jd-flat-atomic-v4-live-probe-raw-responses-v1-2026-09-06.json"
)
LIVE_SELECTION = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_live_probe_selection_v1_2026-09-06.json"
)
LIVE_PREREGISTRATION = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_live_probe_preregistration_v1_2026-09-06.json"
)
DEV20_RAW = ROOT / (
    "artifacts/evaluation/unified-jd-flat-atomic-v4-dev20-raw-v1-2026-09-05.json"
)
V4_1_SOURCE_FREEZE = ROOT / (
    "datasets/"
    "unified_jd_flat_atomic_v4_1_compatibility_source_freeze_v1_2026-09-06.json"
)
DEFAULT_TREATMENT_OUTPUT = ROOT / (
    "artifacts/evaluation/"
    "unified-jd-flat-atomic-v4-2-compatibility-treated-raw-v1-2026-09-06.json"
)
DEFAULT_REPORT_OUTPUT = ROOT / (
    "artifacts/evaluation/"
    "unified-jd-flat-atomic-v4-2-compatibility-report-v1-2026-09-06.json"
)
RUNTIME_ADAPTER = ROOT / ("src/services/unified_jd_flat_atomic_v4_2_compatibility.py")
EXPECTED_PREREGISTRATION_HASH = (
    "30666ee67adfc5448c6b3cc5b9b8bc8ed01cbb6476c95e78ce582620f47e8b2b"
)
EXPECTED_PREREGISTRATION_FREEZE_HASH = (
    "fa1ef9abc1154ea527ae1e55784cb69b1acb2217bf11e84dbab40908110b2a17"
)


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected object: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_sha256(value: object) -> str:
    rendered = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _reference(path: Path) -> dict[str, str]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": _sha256(path),
    }


def _write_new(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as output:
        json.dump(value, output, ensure_ascii=False, indent=2)
        output.write("\n")


def _verify_references(entries: dict[str, Any]) -> None:
    for name, entry in entries.items():
        path = ROOT / entry["path"]
        if not path.is_file() or _sha256(path) != entry["sha256"]:
            raise ValueError(f"frozen artifact hash mismatch: {name}")


def _activation_counts(audit: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(
        diagnostic["code"] for record in audit for diagnostic in record["diagnostics"]
    )
    return {code: counts[code] for code in DIAGNOSTIC_CODES}


def _is_empty_fact(fact: object) -> bool:
    return (
        isinstance(fact, dict)
        and isinstance(fact.get("raw_items"), list)
        and not fact["raw_items"]
        and fact.get("source_text") == ""
        and fact.get("level") is None
    )


def _is_long_evidence(atom: object) -> bool:
    if not isinstance(atom, dict):
        return False
    source = atom.get("source_text")
    surface = atom.get("surface_item")
    return (
        isinstance(source, str)
        and len(source) > 240
        and isinstance(surface, str)
        and 0 < len(surface) <= 240
        and surface in source
        and atom.get("semantic_item") == surface
    )


def _audit_integrity(
    baseline: dict[str, Any],
    treatment: dict[str, Any],
    audit: list[dict[str, Any]],
) -> dict[str, Any]:
    before_records = baseline.get("records")
    after_records = treatment.get("records")
    if not isinstance(before_records, list) or not isinstance(after_records, list):
        return {"passed": False, "reason": "records_not_lists"}
    if len(before_records) != len(after_records):
        return {"passed": False, "reason": "record_count_changed"}

    audit_by_index: dict[int, dict[str, Any]] = {}
    exact = True
    order_valid = True
    reverse_valid = True
    unactivated_equal = True
    for entry in audit:
        index = entry.get("record_index")
        if not isinstance(index, int) or index in audit_by_index:
            exact = False
            continue
        audit_by_index[index] = entry

    for record_index, (before_record, after_record) in enumerate(
        zip(before_records, after_records, strict=True)
    ):
        if not isinstance(before_record, dict) or not isinstance(after_record, dict):
            exact = False
            continue
        entry = audit_by_index.get(record_index)
        if entry is None:
            unactivated_equal = unactivated_equal and before_record == after_record
            continue
        if entry.get("case_id") != before_record.get("case_id"):
            exact = False
        if {
            key: value
            for key, value in before_record.items()
            if key != "raw_model_output"
        } != {
            key: value
            for key, value in after_record.items()
            if key != "raw_model_output"
        }:
            exact = False
        before_output = before_record.get("raw_model_output")
        after_output = after_record.get("raw_model_output")
        diagnostics = entry.get("diagnostics")
        if not isinstance(diagnostics, list):
            exact = False
            continue
        expected, item_exact, item_order = _apply_diagnostics_for_check(
            before_output, diagnostics
        )
        exact = exact and item_exact and expected == after_output
        order_valid = order_valid and item_order
        reverse_valid = reverse_valid and (
            _reverse_dict_diagnostics(after_output, diagnostics) == before_output
        )

    exact = exact and set(audit_by_index).issubset(range(len(before_records)))
    return {
        "passed": exact and order_valid and reverse_valid and unactivated_equal,
        "exact_allowed_changes_only": exact,
        "diagnostic_pipeline_order_valid": order_valid,
        "reverse_transform_restores_input": reverse_valid,
        "unactivated_records_equal_input": unactivated_equal,
    }


def _apply_diagnostics_for_check(
    raw_output: object, diagnostics: list[dict[str, Any]]
) -> tuple[object, bool, bool]:
    expected = copy.deepcopy(raw_output)
    if not isinstance(expected, dict):
        return expected, False, False
    exact = True
    orders = [item.get("pipeline_order") for item in diagnostics]
    order_valid = orders == sorted(orders) and all(
        order in (1, 2, 3) for order in orders
    )

    role_items = [item for item in diagnostics if item.get("code") == ROLE_ALIAS_CODE]
    fact_items = [item for item in diagnostics if item.get("code") == EMPTY_FACT_CODE]
    long_items = [
        item for item in diagnostics if item.get("code") == LONG_EVIDENCE_CODE
    ]
    if len(role_items) + len(fact_items) + len(long_items) != len(diagnostics):
        exact = False

    atoms = expected.get("clause_atoms")
    for item in role_items:
        index = item.get("atom_index")
        exact = exact and set(item) == {
            "path",
            "code",
            "pipeline_order",
            "before",
            "after",
            "atom_index",
        }
        if (
            not isinstance(atoms, list)
            or not isinstance(index, int)
            or index < 0
            or index >= len(atoms)
            or not isinstance(atoms[index], dict)
        ):
            exact = False
            continue
        atom = atoms[index]
        eligible = (
            atom.get("role") == "responsibility"
            and atom.get("category") == "responsibility"
            and atom.get("level") == "mention"
        )
        exact = (
            exact
            and eligible
            and item
            == {
                "path": f"clause_atoms[{index}].role",
                "code": ROLE_ALIAS_CODE,
                "pipeline_order": 1,
                "before": "responsibility",
                "after": "item",
                "atom_index": index,
            }
        )
        atom["role"] = "item"

    facts = expected.get("fact_mentions")
    removed_indexes: list[int] = []
    for item in fact_items:
        index = item.get("fact_index")
        exact = exact and set(item) == {
            "path",
            "code",
            "pipeline_order",
            "before",
            "after",
            "fact_index",
        }
        if (
            not isinstance(facts, list)
            or not isinstance(index, int)
            or index < 0
            or index >= len(facts)
        ):
            exact = False
            continue
        exact = (
            exact
            and _is_empty_fact(facts[index])
            and item
            == {
                "path": f"fact_mentions[{index}]",
                "code": EMPTY_FACT_CODE,
                "pipeline_order": 2,
                "before": facts[index],
                "after": None,
                "fact_index": index,
            }
        )
        removed_indexes.append(index)
    if isinstance(facts, list):
        for index in sorted(removed_indexes, reverse=True):
            del facts[index]

    for item in long_items:
        index = item.get("atom_index")
        exact = exact and set(item) == {
            "path",
            "code",
            "pipeline_order",
            "before",
            "after",
            "atom_index",
        }
        if (
            not isinstance(atoms, list)
            or not isinstance(index, int)
            or index < 0
            or index >= len(atoms)
            or not isinstance(atoms[index], dict)
        ):
            exact = False
            continue
        atom = atoms[index]
        before = atom.get("source_text")
        after = atom.get("surface_item")
        exact = (
            exact
            and _is_long_evidence(atom)
            and item
            == {
                "path": f"clause_atoms[{index}].source_text",
                "code": LONG_EVIDENCE_CODE,
                "pipeline_order": 3,
                "before": before,
                "after": after,
                "atom_index": index,
            }
        )
        atom["source_text"] = after

    return expected, exact, order_valid


def _reverse_dict_diagnostics(
    treated_output: object, diagnostics: list[dict[str, Any]]
) -> object:
    restored = copy.deepcopy(treated_output)
    if not isinstance(restored, dict):
        return object()
    for item in reversed(diagnostics):
        code = item.get("code")
        if code == LONG_EVIDENCE_CODE:
            restored["clause_atoms"][item["atom_index"]]["source_text"] = copy.deepcopy(
                item["before"]
            )
        elif code == EMPTY_FACT_CODE:
            restored["fact_mentions"].insert(
                item["fact_index"], copy.deepcopy(item["before"])
            )
        elif code == ROLE_ALIAS_CODE:
            restored["clause_atoms"][item["atom_index"]]["role"] = copy.deepcopy(
                item["before"]
            )
        else:
            return object()
    return restored


def _selection_sources(selection: dict[str, Any]) -> dict[str, str]:
    return {case["case_id"]: case["raw_content"] for case in selection["cases"]}


def _strict_analyses(
    raw: dict[str, Any], selection: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    sources = _selection_sources(selection)
    return {
        record["case_id"]: analyze_live_response_v4(
            record["raw_model_output"], sources[record["case_id"]]
        )
        for record in raw["records"]
    }


def _all_evidence_anchored(treated: dict[str, Any], selection: dict[str, Any]) -> bool:
    sources = _selection_sources(selection)
    for record in treated["records"]:
        body = sources[record["case_id"]]
        output = record["raw_model_output"]
        for fact in output["fact_mentions"]:
            if fact["source_text"] not in body:
                return False
        for atom in output["clause_atoms"]:
            if atom["source_text"] not in body:
                return False
            surface = atom.get("surface_item")
            if surface is not None and (
                surface not in atom["source_text"] or surface not in body
            ):
                return False
    return True


def _activation_case_sets(
    audit: list[dict[str, Any]],
) -> dict[str, set[str]]:
    result = {code: set() for code in DIAGNOSTIC_CODES}
    for record in audit:
        for diagnostic in record["diagnostics"]:
            result[diagnostic["code"]].add(record["case_id"])
    return result


def _normalize_dev20(
    dev20: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    treated = copy.deepcopy(dev20)
    audit: list[dict[str, Any]] = []
    valid_count = 0
    atom_count = 0
    reversible = True
    for record_index, (before_record, after_record) in enumerate(
        zip(dev20["records"], treated["records"], strict=True)
    ):
        payload = {
            "fact_mentions": [],
            "clause_atoms": before_record["clause_atoms"],
        }
        result = normalize_flat_atomic_v4_2_wire_output(payload)
        after_record["clause_atoms"] = result.output["clause_atoms"]
        if result.diagnostics:
            audit.append(
                {
                    "record_index": record_index,
                    "case_id": before_record["case_id"],
                    "diagnostics": [item.as_dict() for item in result.diagnostics],
                }
            )
        reversible = reversible and (
            restore_flat_atomic_v4_2_wire_output(result.output, result.diagnostics)
            == payload
        )
        try:
            UnifiedJDFlatAtomicLiveResponseV4.model_validate(result.output)
        except ValidationError:
            pass
        else:
            valid_count += 1
        atom_count += len(after_record["clause_atoms"])
    details = {
        "case_count": len(treated["records"]),
        "atom_count": atom_count,
        "strict_schema_valid_case_count": valid_count,
        "activation_counts": _activation_counts(audit),
        "exactly_equal_to_frozen_input": treated == dev20,
        "reverse_transform_restores_input": reversible,
    }
    details["passed"] = (
        details["case_count"] == 20
        and atom_count == 427
        and valid_count == 20
        and sum(details["activation_counts"].values()) == 0
        and treated == dev20
        and reversible
    )
    return treated, audit, details


def _atom(
    *,
    role: str = "item",
    category: str = "skill",
    level: str = "required",
    semantic: str = "target",
    surface: str | None = "target",
    source: str = "target",
) -> dict[str, Any]:
    return {
        "role": role,
        "category": category,
        "level": level,
        "relation": "all_of",
        "semantic_item": semantic,
        "surface_item": surface,
        "source_text": source,
        "group_name": None,
        "allow_other": False,
        "qualifier": None,
    }


def _empty_fact(**updates: object) -> dict[str, Any]:
    value: dict[str, Any] = {
        "field": "deadline",
        "raw_items": [],
        "level": None,
        "source_text": "",
    }
    value.update(updates)
    return value


def _schema_valid(payload: object) -> bool:
    try:
        UnifiedJDFlatAtomicLiveResponseV4.model_validate(payload)
    except ValidationError:
        return False
    return True


def _control_gate() -> dict[str, Any]:
    long_source = "x" * 241 + "target"
    fixtures: list[dict[str, Any]] = [
        {
            "name": "positive_role_alias",
            "positive": True,
            "codes": [ROLE_ALIAS_CODE],
            "raw": {
                "fact_mentions": [],
                "clause_atoms": [
                    _atom(
                        role="responsibility",
                        category="responsibility",
                        level="mention",
                    )
                ],
            },
        },
        {
            "name": "positive_empty_fact_omission",
            "positive": True,
            "codes": [EMPTY_FACT_CODE],
            "raw": {"fact_mentions": [_empty_fact()], "clause_atoms": []},
        },
        {
            "name": "positive_long_evidence",
            "positive": True,
            "codes": [LONG_EVIDENCE_CODE],
            "raw": {
                "fact_mentions": [],
                "clause_atoms": [_atom(source=long_source)],
            },
        },
        {
            "name": "positive_combined_pipeline",
            "positive": True,
            "codes": [ROLE_ALIAS_CODE, EMPTY_FACT_CODE, LONG_EVIDENCE_CODE],
            "raw": {
                "fact_mentions": [_empty_fact()],
                "clause_atoms": [
                    _atom(
                        role="responsibility",
                        category="responsibility",
                        level="mention",
                    ),
                    _atom(source=long_source),
                ],
            },
        },
        {
            "name": "negative_valid_item",
            "raw": {"fact_mentions": [], "clause_atoms": [_atom()]},
        },
        {
            "name": "negative_valid_example",
            "raw": {
                "fact_mentions": [],
                "clause_atoms": [_atom(role="example")],
            },
        },
        {
            "name": "negative_role_wrong_category",
            "invalid": True,
            "raw": {
                "fact_mentions": [],
                "clause_atoms": [_atom(role="responsibility")],
            },
        },
        {
            "name": "negative_role_wrong_level",
            "invalid": True,
            "raw": {
                "fact_mentions": [],
                "clause_atoms": [
                    _atom(role="responsibility", category="responsibility")
                ],
            },
        },
        {
            "name": "negative_empty_fact_nonnull_level",
            "invalid": True,
            "raw": {
                "fact_mentions": [_empty_fact(level="required")],
                "clause_atoms": [],
            },
        },
        {
            "name": "negative_empty_items_nonempty_source",
            "invalid": True,
            "raw": {
                "fact_mentions": [_empty_fact(source_text="deadline")],
                "clause_atoms": [],
            },
        },
        {
            "name": "negative_nonempty_items_empty_source",
            "invalid": True,
            "raw": {
                "fact_mentions": [_empty_fact(raw_items=["2026-09-30"])],
                "clause_atoms": [],
            },
        },
        {
            "name": "negative_source_exactly_240",
            "raw": {
                "fact_mentions": [],
                "clause_atoms": [_atom(source="x" * 234 + "target")],
            },
        },
        {
            "name": "negative_long_null_surface",
            "invalid": True,
            "raw": {
                "fact_mentions": [],
                "clause_atoms": [_atom(surface=None, source="x" * 241)],
            },
        },
        {
            "name": "negative_overlong_surface",
            "invalid": True,
            "raw": {
                "fact_mentions": [],
                "clause_atoms": [
                    _atom(
                        semantic="x" * 241,
                        surface="x" * 241,
                        source="x" * 241,
                    )
                ],
            },
        },
        {
            "name": "negative_unanchored_surface",
            "invalid": True,
            "raw": {
                "fact_mentions": [],
                "clause_atoms": [_atom(source="x" * 241)],
            },
        },
        {
            "name": "negative_semantic_surface_divergence",
            "invalid": True,
            "raw": {
                "fact_mentions": [],
                "clause_atoms": [
                    _atom(semantic="interpreted target", source=long_source)
                ],
            },
        },
    ]

    per_control: list[dict[str, Any]] = []
    for fixture in fixtures:
        raw = fixture["raw"]
        result = normalize_flat_atomic_v4_2_wire_output(raw)
        actual_codes = [item.code for item in result.diagnostics]
        expected_codes = fixture.get("codes", [])
        reversible = (
            restore_flat_atomic_v4_2_wire_output(result.output, result.diagnostics)
            == raw
        )
        if fixture.get("positive"):
            passed = actual_codes == expected_codes and _schema_valid(result.output)
        else:
            passed = actual_codes == [] and result.output == raw
            if fixture.get("invalid"):
                passed = passed and not _schema_valid(result.output)
        passed = passed and reversible
        per_control.append(
            {
                "name": fixture["name"],
                "passed": passed,
                "activation_codes": actual_codes,
                "schema_valid_after": _schema_valid(result.output),
                "byte_equivalent_to_input": result.output == raw,
                "reverse_transform_restores_input": reversible,
            }
        )
    return {
        "passed": all(item["passed"] for item in per_control),
        "control_count": len(per_control),
        "positive_control_count": sum(item.get("positive", False) for item in fixtures),
        "negative_control_count": sum(
            not item.get("positive", False) for item in fixtures
        ),
        "per_control": per_control,
    }


def _static_audit() -> dict[str, Any]:
    source = RUNTIME_ADAPTER.read_text(encoding="utf-8")
    tree = ast.parse(source)
    allowed_imports = {
        "__future__",
        "collections.abc",
        "copy",
        "dataclasses",
        "typing",
        "src.services.unified_jd_flat_atomic_v4_compatibility",
    }
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imports.add(node.module)
    forbidden_text = re.compile(
        r"(?:api\.deepseek\.com|httpx|requests|urllib|socket|openai|"
        r"canonicalizer|unified_jd_parser|artifacts/evaluation|"
        r"external-ashby-|campus-ai-|surface-holdout-)"
    )
    violations = sorted(imports - allowed_imports)
    if forbidden_text.search(source):
        violations.append("forbidden_runtime_text")
    return {
        "passed": not violations,
        "checked_path": RUNTIME_ADAPTER.relative_to(ROOT).as_posix(),
        "imports": sorted(imports),
        "violations": violations,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Execute the frozen one-time v4.2 offline compatibility gates"
    )
    parser.add_argument(
        "--treatment-output", type=Path, default=DEFAULT_TREATMENT_OUTPUT
    )
    parser.add_argument("--report-output", type=Path, default=DEFAULT_REPORT_OUTPUT)
    parser.add_argument("--targeted-tests-passed", action="store_true")
    parser.add_argument("--full-suite-passed", action="store_true")
    return parser.parse_args()


def main() -> int:
    arguments = _parse_args()
    if arguments.treatment_output.exists() or arguments.report_output.exists():
        raise FileExistsError("formal v4.2 artifacts already exist; rerun is forbidden")
    if _sha256(PREREGISTRATION) != EXPECTED_PREREGISTRATION_HASH:
        raise ValueError("v4.2 preregistration hash changed")
    if _sha256(PREREGISTRATION_FREEZE) != EXPECTED_PREREGISTRATION_FREEZE_HASH:
        raise ValueError("v4.2 preregistration freeze hash changed")

    preregistration = _load(PREREGISTRATION)
    preregistration_freeze = _load(PREREGISTRATION_FREEZE)
    source_freeze = _load(SOURCE_FREEZE)
    if source_freeze.get("status") != "frozen_before_formal_gate_execution":
        raise ValueError("v4.2 source is not frozen for formal execution")
    if source_freeze.get("preregistration_sha256") != _sha256(PREREGISTRATION):
        raise ValueError("source freeze points to another preregistration")
    _verify_references(preregistration["frozen_inputs"])
    _verify_references(preregistration_freeze["artifacts"])
    _verify_references(source_freeze["artifacts"])
    v4_1_source_freeze = _load(V4_1_SOURCE_FREEZE)
    _verify_references(v4_1_source_freeze["artifacts"])
    _verify_references(v4_1_source_freeze["frozen_inputs"])

    external_raw = _load(EXTERNAL_RAW)
    external_selection = _load(EXTERNAL_SELECTION)
    external_hash_before = _json_sha256(external_raw)
    external_treated, external_audit = normalize_raw_responses_v4_2(external_raw)
    external_input_unchanged = external_hash_before == _json_sha256(external_raw)
    external_integrity = _audit_integrity(
        external_raw, external_treated, external_audit
    )
    external_baseline = _strict_analyses(external_raw, external_selection)
    external_after = _strict_analyses(external_treated, external_selection)
    external_report = evaluate_live_probe_v4_2(
        external_selection,
        _load(EXTERNAL_PREREGISTRATION),
        external_raw,
        frozen_inputs_valid=True,
        frozen_sources_valid=True,
    )
    external_counts = _activation_counts(external_audit)
    external_sets = _activation_case_sets(external_audit)
    selected_external_ids = set(external_selection["selected_case_ids"])
    omission_ids = external_sets[EMPTY_FACT_CODE]
    long_ids = external_sets[LONG_EVIDENCE_CODE]
    partition_valid = (
        not external_sets[ROLE_ALIAS_CODE]
        and len(omission_ids) == 4
        and len(long_ids) == 1
        and omission_ids.isdisjoint(long_ids)
        and omission_ids | long_ids == selected_external_ids
    )
    external_valid_count = sum(item["schema_valid"] for item in external_after.values())
    external_gate_passed = (
        len(external_raw["records"]) == 5
        and sum(item["schema_valid"] for item in external_baseline.values()) == 0
        and external_valid_count == 5
        and external_counts
        == {
            ROLE_ALIAS_CODE: 0,
            EMPTY_FACT_CODE: 27,
            LONG_EVIDENCE_CODE: 10,
        }
        and partition_valid
        and _all_evidence_anchored(external_treated, external_selection)
        and external_integrity["passed"]
        and external_input_unchanged
    )

    live_raw = _load(LIVE_RAW)
    live_hash_before = _json_sha256(live_raw)
    live_treated, live_audit = normalize_raw_responses_v4_2(live_raw)
    v4_1_live_output, _ = normalize_live_probe_raw_responses_v4_1(live_raw)
    v4_1_live_report = evaluate_live_probe_v4_1(
        _load(LIVE_SELECTION),
        _load(LIVE_PREREGISTRATION),
        live_raw,
        frozen_inputs_valid=True,
        frozen_sources_valid=True,
    )
    v4_2_live_report = evaluate_live_probe_v4_2(
        _load(LIVE_SELECTION),
        _load(LIVE_PREREGISTRATION),
        live_raw,
        frozen_inputs_valid=True,
        frozen_sources_valid=True,
    )
    live_counts = _activation_counts(live_audit)
    live_integrity = _audit_integrity(live_raw, live_treated, live_audit)
    preserved_live_gates = all(
        v4_2_live_report["gates"][name] == v4_1_live_report["gates"][name]
        for name in (
            "G1-json-and-root-topology",
            "G5-granularity-noncollapse",
            "G6-fact-layer-compatibility",
        )
    )
    live_gate_passed = (
        len(live_raw["records"]) == 5
        and live_treated == v4_1_live_output
        and live_counts
        == {
            ROLE_ALIAS_CODE: 18,
            EMPTY_FACT_CODE: 0,
            LONG_EVIDENCE_CODE: 0,
        }
        and v4_2_live_report["gates"]["G1-json-and-root-topology"][
            "schema_valid_case_count"
        ]
        == 5
        and preserved_live_gates
        and live_integrity["passed"]
        and live_hash_before == _json_sha256(live_raw)
    )

    dev20_raw = _load(DEV20_RAW)
    dev20_hash_before = _json_sha256(dev20_raw)
    dev20_treated, dev20_audit, dev20_gate = _normalize_dev20(dev20_raw)
    dev20_input_unchanged = dev20_hash_before == _json_sha256(dev20_raw)
    dev20_gate["input_object_unchanged"] = dev20_input_unchanged
    dev20_gate["passed"] = dev20_gate["passed"] and dev20_input_unchanged

    controls = _control_gate()
    static_audit = _static_audit()
    combined_codes = next(
        item["activation_codes"]
        for item in controls["per_control"]
        if item["name"] == "positive_combined_pipeline"
    )
    diagnostic_codes = sorted(
        {
            diagnostic["code"]
            for audit in (external_audit, live_audit, dev20_audit)
            for record in audit
            for diagnostic in record["diagnostics"]
        }
    )
    g1_passed = (
        external_integrity["passed"]
        and live_integrity["passed"]
        and dev20_gate["reverse_transform_restores_input"]
        and external_input_unchanged
        and live_hash_before == _json_sha256(live_raw)
        and dev20_input_unchanged
        and diagnostic_codes == sorted(DIAGNOSTIC_CODES)
        and combined_codes == list(DIAGNOSTIC_CODES)
    )

    sources_and_tests_passed = (
        arguments.targeted_tests_passed and arguments.full_suite_passed
    )
    gates = {
        "G0-frozen-inputs-and-zero-calls": {
            "passed": True,
            "all_frozen_hashes_valid": True,
            "source_freeze_valid": True,
            "new_model_call_count": 0,
            "network_call_count": 0,
            "new_holdout_loaded": False,
        },
        "G1-contract-pipeline-and-reversibility": {
            "passed": g1_passed,
            "diagnostic_codes": diagnostic_codes,
            "combined_control_pipeline_codes": combined_codes,
            "external_integrity": external_integrity,
            "live_integrity": live_integrity,
            "dev20_reverse_transform_restores_input": dev20_gate[
                "reverse_transform_restores_input"
            ],
            "all_input_objects_unchanged": (
                external_input_unchanged
                and live_hash_before == _json_sha256(live_raw)
                and dev20_input_unchanged
            ),
        },
        "G2-external-revealed-5-of-5-recovery": {
            "passed": external_gate_passed,
            "case_count": len(external_raw["records"]),
            "baseline_strict_schema_valid_case_count": sum(
                item["schema_valid"] for item in external_baseline.values()
            ),
            "strict_schema_valid_case_count": external_valid_count,
            "required": 5,
            "activation_counts": external_counts,
            "omission_activation_case_count": len(omission_ids),
            "long_evidence_activation_case_count": len(long_ids),
            "target_partition_disjoint_and_complete": partition_valid,
            "all_evidence_exactly_anchored": _all_evidence_anchored(
                external_treated, external_selection
            ),
            "all_registered_external_evaluator_gates_passed": external_report["passed"],
        },
        "G3-v4-live-probe-v4_1-exact-preservation": {
            "passed": live_gate_passed,
            "case_count": len(live_raw["records"]),
            "strict_schema_valid_case_count": v4_2_live_report["gates"][
                "G1-json-and-root-topology"
            ]["schema_valid_case_count"],
            "activation_counts": live_counts,
            "output_exactly_equals_frozen_v4_1_normalization": (
                live_treated == v4_1_live_output
            ),
            "G1_G5_G6_exactly_preserved": preserved_live_gates,
        },
        "G4-dev20-exact-zero-regression": dev20_gate,
        "G5-fail-closed-controls": controls,
        "G6-isolation-static-audit-and-tests": {
            "passed": static_audit["passed"] and sources_and_tests_passed,
            "frozen_v4_and_v4_1_sources_unchanged": True,
            "static_audit": static_audit,
            "targeted_tests_passed": arguments.targeted_tests_passed,
            "full_suite_passed": arguments.full_suite_passed,
        },
    }
    passed = all(gate["passed"] for gate in gates.values())
    generated_at = datetime.now(UTC).isoformat()
    treatment = {
        "treatment_version": "unified-jd-flat-atomic-v4.2-compatibility-treated-raw-v1",
        "generated_at": generated_at,
        "status": "formal_one_time_frozen_offline_treatment",
        "model_call_count": 0,
        "network_call_count": 0,
        "new_holdout_loaded": False,
        "external_revealed": {
            "normalized_raw": external_treated,
            "audit": external_audit,
        },
        "v4_live_probe": {
            "normalized_raw": live_treated,
            "audit": live_audit,
        },
        "v4_dev20": {
            "normalized_raw": dev20_treated,
            "audit": dev20_audit,
        },
        "inputs": {
            "preregistration": _reference(PREREGISTRATION),
            "preregistration_freeze": _reference(PREREGISTRATION_FREEZE),
            "source_freeze": _reference(SOURCE_FREEZE),
            "external_raw": _reference(EXTERNAL_RAW),
            "live_raw": _reference(LIVE_RAW),
            "dev20_raw": _reference(DEV20_RAW),
        },
    }
    _write_new(arguments.treatment_output, treatment)
    report = {
        "report_version": "unified-jd-flat-atomic-v4.2-compatibility-report-v1",
        "generated_at": generated_at,
        "status": "formal_one_time_frozen_offline_gate_execution",
        "passed": passed,
        "decision": (
            "development_and_regression_gates_passed"
            if passed
            else "v4_2_rejected_keep_v4_1"
        ),
        "new_model_call_count": 0,
        "network_call_count": 0,
        "new_holdout_loaded": False,
        "parser_modified_or_called": False,
        "canonicalizer_modified_or_called": False,
        "gates": gates,
        "inputs": {
            "preregistration": _reference(PREREGISTRATION),
            "preregistration_freeze": _reference(PREREGISTRATION_FREEZE),
            "source_freeze": _reference(SOURCE_FREEZE),
            "external_raw": _reference(EXTERNAL_RAW),
            "live_raw": _reference(LIVE_RAW),
            "dev20_raw": _reference(DEV20_RAW),
            "treatment": _reference(arguments.treatment_output),
        },
        "next_allowed_action": (
            "Freeze this report, then preregister and separately authorize a new "
            "independent public-job holdout."
            if passed
            else "Keep v4.1, retain this failure, and diagnose frozen inputs only."
        ),
    }
    _write_new(arguments.report_output, report)
    print(
        json.dumps(
            {
                "passed": passed,
                "decision": report["decision"],
                "gates": {name: gate["passed"] for name, gate in gates.items()},
                "treatment": _reference(arguments.treatment_output),
                "report": _reference(arguments.report_output),
                "new_model_call_count": 0,
                "network_call_count": 0,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
