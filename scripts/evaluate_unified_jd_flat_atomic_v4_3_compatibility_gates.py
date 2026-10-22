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
from typing import Any

from pydantic import ValidationError

from src.evaluation.model_first_v4_1_compatibility import (
    evaluate_live_probe_v4_1,
    normalize_live_probe_raw_responses_v4_1,
)
from src.evaluation.model_first_v4_2_compatibility import (
    normalize_raw_responses_v4_2,
)
from src.evaluation.model_first_v4_3_compatibility import (
    evaluate_live_probe_v4_3,
    normalize_raw_responses_v4_3,
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
    FlatAtomicV42CompatibilityDiagnostic,
    normalize_flat_atomic_v4_2_wire_output,
    restore_flat_atomic_v4_2_wire_output,
)
from src.services.unified_jd_flat_atomic_v4_3_compatibility import (
    normalize_flat_atomic_v4_3_wire_output,
    restore_flat_atomic_v4_3_wire_output,
)

ROOT = Path(__file__).resolve().parents[1]
PREREGISTRATION = ROOT / (
    "datasets/"
    "unified_jd_flat_atomic_v4_3_compatibility_preregistration_v1_2026-09-06.json"
)
PREREGISTRATION_FREEZE = ROOT / (
    "datasets/"
    "unified_jd_flat_atomic_v4_3_compatibility_preregistration_freeze_v1_2026-09-06.json"
)
SOURCE_FREEZE = ROOT / (
    "datasets/"
    "unified_jd_flat_atomic_v4_3_compatibility_source_freeze_v1_2026-09-06.json"
)
V4_2_SOURCE_FREEZE = ROOT / (
    "datasets/"
    "unified_jd_flat_atomic_v4_2_compatibility_source_freeze_v1_2026-09-06.json"
)
V4_1_SOURCE_FREEZE = ROOT / (
    "datasets/"
    "unified_jd_flat_atomic_v4_1_compatibility_source_freeze_v1_2026-09-06.json"
)
V4_2_TREATMENT = ROOT / (
    "artifacts/evaluation/"
    "unified-jd-flat-atomic-v4-2-compatibility-treated-raw-v1-2026-09-06.json"
)
V4_2_REPORT = ROOT / (
    "artifacts/evaluation/"
    "unified-jd-flat-atomic-v4-2-compatibility-report-v1-2026-09-06.json"
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
DEFAULT_TREATMENT_OUTPUT = ROOT / (
    "artifacts/evaluation/"
    "unified-jd-flat-atomic-v4-3-compatibility-treated-raw-v1-2026-09-06.json"
)
DEFAULT_REPORT_OUTPUT = ROOT / (
    "artifacts/evaluation/"
    "unified-jd-flat-atomic-v4-3-compatibility-report-v1-2026-09-06.json"
)
RUNTIME_ADAPTER = ROOT / ("src/services/unified_jd_flat_atomic_v4_3_compatibility.py")
EXPECTED_PREREGISTRATION_HASH = (
    "f224ac0d7925e580d9bf2a65e9ac3a1c23f1faed648f298e6e62cb83358e6723"
)
EXPECTED_PREREGISTRATION_FREEZE_HASH = (
    "bcb84c6bbfbf1cd985c17425e42ffc2c9df1e7bbbd9346c205fe0c18fdb97d2f"
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


def _diagnostics_from_dicts(
    values: list[dict[str, Any]],
) -> tuple[FlatAtomicV42CompatibilityDiagnostic, ...]:
    return tuple(FlatAtomicV42CompatibilityDiagnostic(**value) for value in values)


def _activation_counts(audit: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(
        diagnostic["code"] for record in audit for diagnostic in record["diagnostics"]
    )
    return {code: counts[code] for code in DIAGNOSTIC_CODES}


def _restore_envelope(
    baseline: dict[str, Any],
    treatment: dict[str, Any],
    audit: list[dict[str, Any]],
    *,
    use_v4_3: bool,
) -> dict[str, Any]:
    before_records = baseline["records"]
    after_records = treatment["records"]
    audit_by_index = {item["record_index"]: item for item in audit}
    per_case: dict[str, bool] = {}
    metadata_equal = len(before_records) == len(after_records)
    input_hash = _json_sha256(treatment)
    for index, (before_record, after_record) in enumerate(
        zip(before_records, after_records, strict=True)
    ):
        entry = audit_by_index.get(index)
        diagnostics = _diagnostics_from_dicts(
            entry["diagnostics"] if entry is not None else []
        )
        restore = (
            restore_flat_atomic_v4_3_wire_output
            if use_v4_3
            else restore_flat_atomic_v4_2_wire_output
        )
        try:
            restored_output = restore(after_record["raw_model_output"], diagnostics)
        except (TypeError, ValueError):
            restored_output = object()
        case_id = before_record["case_id"]
        per_case[case_id] = restored_output == before_record["raw_model_output"]
        metadata_equal = metadata_equal and (
            {
                key: value
                for key, value in before_record.items()
                if key != "raw_model_output"
            }
            == {
                key: value
                for key, value in after_record.items()
                if key != "raw_model_output"
            }
        )
    return {
        "passed": all(per_case.values()) and metadata_equal,
        "case_count": len(per_case),
        "exact_restoration_case_count": sum(per_case.values()),
        "metadata_equal": metadata_equal,
        "input_treatment_unchanged": input_hash == _json_sha256(treatment),
        "per_case": per_case,
    }


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


def _normalize_dev20(
    dev20: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    treated = copy.deepcopy(dev20)
    audit: list[dict[str, Any]] = []
    valid_count = 0
    atom_count = 0
    forward_equivalent = True
    reverse_count = 0
    input_hash = _json_sha256(dev20)
    for record_index, (before_record, after_record) in enumerate(
        zip(dev20["records"], treated["records"], strict=True)
    ):
        payload = {
            "fact_mentions": [],
            "clause_atoms": before_record["clause_atoms"],
        }
        v4_2 = normalize_flat_atomic_v4_2_wire_output(payload)
        v4_3 = normalize_flat_atomic_v4_3_wire_output(payload)
        forward_equivalent = forward_equivalent and v4_3 == v4_2
        after_record["clause_atoms"] = v4_3.output["clause_atoms"]
        if v4_3.diagnostics:
            audit.append(
                {
                    "record_index": record_index,
                    "case_id": before_record["case_id"],
                    "diagnostics": [item.as_dict() for item in v4_3.diagnostics],
                }
            )
        if (
            restore_flat_atomic_v4_3_wire_output(v4_3.output, v4_3.diagnostics)
            == payload
        ):
            reverse_count += 1
        try:
            UnifiedJDFlatAtomicLiveResponseV4.model_validate(v4_3.output)
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
        "forward_exactly_equals_v4_2": forward_equivalent,
        "exactly_equal_to_frozen_input": treated == dev20,
        "exact_reverse_restoration_case_count": reverse_count,
        "input_object_unchanged": input_hash == _json_sha256(dev20),
    }
    details["passed"] = (
        details["case_count"] == 20
        and atom_count == 427
        and valid_count == 20
        and sum(details["activation_counts"].values()) == 0
        and forward_equivalent
        and treated == dev20
        and reverse_count == 20
        and details["input_object_unchanged"]
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


def _empty_fact(field: str = "deadline", **updates: object) -> dict[str, Any]:
    value: dict[str, Any] = {
        "field": field,
        "raw_items": [],
        "level": None,
        "source_text": "",
    }
    value.update(updates)
    return value


def _valid_fact(field: str, text: str) -> dict[str, Any]:
    return {
        "field": field,
        "raw_items": [text],
        "level": None,
        "source_text": text,
    }


def _existing_control_fixtures() -> list[dict[str, Any]]:
    long_source = "x" * 241 + "target"
    return [
        {
            "name": "positive_role_alias",
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
            "raw": {"fact_mentions": [_empty_fact()], "clause_atoms": []},
        },
        {
            "name": "positive_long_evidence",
            "raw": {
                "fact_mentions": [],
                "clause_atoms": [_atom(source=long_source)],
            },
        },
        {
            "name": "positive_combined_pipeline",
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
            "raw": {
                "fact_mentions": [],
                "clause_atoms": [_atom(role="responsibility")],
            },
        },
        {
            "name": "negative_role_wrong_level",
            "raw": {
                "fact_mentions": [],
                "clause_atoms": [
                    _atom(role="responsibility", category="responsibility")
                ],
            },
        },
        {
            "name": "negative_empty_fact_nonnull_level",
            "raw": {
                "fact_mentions": [_empty_fact(level="required")],
                "clause_atoms": [],
            },
        },
        {
            "name": "negative_empty_items_nonempty_source",
            "raw": {
                "fact_mentions": [_empty_fact(source_text="deadline")],
                "clause_atoms": [],
            },
        },
        {
            "name": "negative_nonempty_items_empty_source",
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
            "raw": {
                "fact_mentions": [],
                "clause_atoms": [_atom(surface=None, source="x" * 241)],
            },
        },
        {
            "name": "negative_overlong_surface",
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
            "raw": {
                "fact_mentions": [],
                "clause_atoms": [_atom(source="x" * 241)],
            },
        },
        {
            "name": "negative_semantic_surface_divergence",
            "raw": {
                "fact_mentions": [],
                "clause_atoms": [
                    _atom(semantic="interpreted target", source=long_source)
                ],
            },
        },
    ]


def _existing_controls_gate(v4_2_report: dict[str, Any]) -> dict[str, Any]:
    frozen_controls = v4_2_report["gates"]["G5-fail-closed-controls"]
    frozen_names = [item["name"] for item in frozen_controls["per_control"]]
    fixtures = _existing_control_fixtures()
    per_control: list[dict[str, Any]] = []
    for fixture in fixtures:
        raw = fixture["raw"]
        v4_2 = normalize_flat_atomic_v4_2_wire_output(raw)
        v4_3 = normalize_flat_atomic_v4_3_wire_output(raw)
        restored = restore_flat_atomic_v4_3_wire_output(v4_3.output, v4_3.diagnostics)
        per_control.append(
            {
                "name": fixture["name"],
                "passed": v4_3 == v4_2 and restored == raw,
                "forward_output_equal": v4_3.output == v4_2.output,
                "diagnostics_equal": v4_3.diagnostics == v4_2.diagnostics,
                "reverse_restores_input": restored == raw,
            }
        )
    names = [item["name"] for item in fixtures]
    passed = (
        frozen_controls["passed"]
        and frozen_controls["control_count"] == 16
        and names == frozen_names
        and all(item["passed"] for item in per_control)
    )
    return {
        "passed": passed,
        "control_count": len(fixtures),
        "names_exactly_equal_frozen_v4_2_report": names == frozen_names,
        "frozen_v4_2_controls_passed": frozen_controls["passed"],
        "per_control": per_control,
    }


def _tail_control() -> dict[str, Any]:
    return {
        "fact_mentions": [
            _valid_fact("locations", "Remote"),
            _valid_fact("education_requirements", "Bachelor's degree"),
            *[
                _empty_fact(field)
                for field in (
                    "graduation_years",
                    "major_requirements",
                    "internship_duration_months",
                    "weekly_days",
                    "earliest_start_date",
                    "deadline",
                    "job_type",
                )
            ],
        ],
        "clause_atoms": [],
    }


def _tail_control_gate() -> tuple[dict[str, Any], dict[str, Any]]:
    raw = _tail_control()
    input_hash = _json_sha256(raw)
    v4_2 = normalize_flat_atomic_v4_2_wire_output(raw)
    v4_3 = normalize_flat_atomic_v4_3_wire_output(raw)
    v4_2_restored = restore_flat_atomic_v4_2_wire_output(v4_2.output, v4_2.diagnostics)
    v4_3_restored = restore_flat_atomic_v4_3_wire_output(v4_3.output, v4_3.diagnostics)
    indexes = [item.fact_index for item in v4_3.diagnostics]
    codes = [item.code for item in v4_3.diagnostics]
    details = {
        "passed": (
            v4_3 == v4_2
            and indexes == list(range(2, 9))
            and codes == [EMPTY_FACT_CODE] * 7
            and v4_3.output["fact_mentions"] == raw["fact_mentions"][:2]
            and v4_2_restored != raw
            and v4_3_restored == raw
            and input_hash == _json_sha256(raw)
        ),
        "activation_count": len(v4_3.diagnostics),
        "diagnostic_codes": codes,
        "diagnostic_fact_indices": indexes,
        "forward_output_and_diagnostics_equal_v4_2": v4_3 == v4_2,
        "v4_2_reverse_restores_input": v4_2_restored == raw,
        "v4_3_reverse_restores_input": v4_3_restored == raw,
        "input_object_unchanged": input_hash == _json_sha256(raw),
    }
    artifact = {
        "input": raw,
        "normalized_output": v4_3.output,
        "diagnostics": [item.as_dict() for item in v4_3.diagnostics],
        "v4_2_restored_output": v4_2_restored,
        "v4_3_restored_output": v4_3_restored,
    }
    return details, artifact


def _raises_without_mutation(
    output: object,
    diagnostics: tuple[FlatAtomicV42CompatibilityDiagnostic, ...],
) -> bool:
    frozen = copy.deepcopy(output)
    try:
        restore_flat_atomic_v4_3_wire_output(output, diagnostics)
    except (TypeError, ValueError):
        return output == frozen
    return False


def _fail_closed_gate() -> dict[str, Any]:
    role_raw = {
        "fact_mentions": [],
        "clause_atoms": [
            _atom(
                role="responsibility",
                category="responsibility",
                level="mention",
            )
        ],
    }
    role = normalize_flat_atomic_v4_3_wire_output(role_raw)
    singleton_raw = {"fact_mentions": [_empty_fact()], "clause_atoms": []}
    singleton = normalize_flat_atomic_v4_3_wire_output(singleton_raw)
    long_raw = {
        "fact_mentions": [],
        "clause_atoms": [_atom(source="x" * 241 + "target")],
    }
    long_result = normalize_flat_atomic_v4_3_wire_output(long_raw)
    combined_raw = {
        "fact_mentions": [_empty_fact()],
        "clause_atoms": [
            role_raw["clause_atoms"][0],
            long_raw["clause_atoms"][0],
        ],
    }
    combined = normalize_flat_atomic_v4_3_wire_output(combined_raw)
    tail = normalize_flat_atomic_v4_3_wire_output(_tail_control())

    mismatch = copy.deepcopy(role.output)
    mismatch["clause_atoms"][0]["role"] = "example"
    duplicate = list(tail.diagnostics)
    duplicate[1] = replace(
        duplicate[1],
        fact_index=duplicate[0].fact_index,
        path=duplicate[0].path,
    )
    checks = {
        "singleton_omission_restores": (
            restore_flat_atomic_v4_3_wire_output(
                singleton.output, singleton.diagnostics
            )
            == singleton_raw
        ),
        "role_only_restores": (
            restore_flat_atomic_v4_3_wire_output(role.output, role.diagnostics)
            == role_raw
        ),
        "long_only_restores": (
            restore_flat_atomic_v4_3_wire_output(
                long_result.output, long_result.diagnostics
            )
            == long_raw
        ),
        "combined_three_stage_restores": (
            restore_flat_atomic_v4_3_wire_output(combined.output, combined.diagnostics)
            == combined_raw
        ),
        "unknown_code_raises_without_mutation": _raises_without_mutation(
            role.output, (replace(role.diagnostics[0], code="unknown"),)
        ),
        "duplicate_omission_index_raises_without_mutation": (
            _raises_without_mutation(tail.output, tuple(duplicate))
        ),
        "wrong_pipeline_order_raises_without_mutation": _raises_without_mutation(
            role.output, (replace(role.diagnostics[0], pipeline_order=2),)
        ),
        "invalid_index_raises_without_mutation": _raises_without_mutation(
            role.output,
            (
                replace(
                    role.diagnostics[0],
                    atom_index=99,
                    path="clause_atoms[99].role",
                ),
            ),
        ),
        "output_mismatch_raises_without_mutation": _raises_without_mutation(
            mismatch, role.diagnostics
        ),
    }
    empty = {"fact_mentions": [], "clause_atoms": [_atom()]}
    empty_restored = restore_flat_atomic_v4_3_wire_output(empty, ())
    checks["empty_diagnostics_returns_equal_deep_copy"] = (
        empty_restored == empty
        and empty_restored is not empty
        and empty_restored["clause_atoms"] is not empty["clause_atoms"]
    )
    return {"passed": all(checks.values()), "checks": checks}


def _static_audit() -> dict[str, Any]:
    source = RUNTIME_ADAPTER.read_text(encoding="utf-8")
    tree = ast.parse(source)
    allowed_imports = {
        "__future__",
        "collections.abc",
        "copy",
        "src.services.unified_jd_flat_atomic_v4_2_compatibility",
    }
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imports.add(node.module)
    forbidden_text = re.compile(
        r"(?:api\.deepseek\.com|httpx|requests|urllib|socket|openai|"
        r"canonicalizer|unified_jd_parser|artifacts/evaluation|gold|"
        r"external-ashby-|campus-ai-|surface-holdout-|fixture_id)"
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
        description="Execute the frozen one-time v4.3 offline compatibility gates"
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
        raise FileExistsError("formal v4.3 artifacts already exist; rerun is forbidden")
    if _sha256(PREREGISTRATION) != EXPECTED_PREREGISTRATION_HASH:
        raise ValueError("v4.3 preregistration hash changed")
    if _sha256(PREREGISTRATION_FREEZE) != EXPECTED_PREREGISTRATION_FREEZE_HASH:
        raise ValueError("v4.3 preregistration freeze hash changed")

    preregistration = _load(PREREGISTRATION)
    preregistration_freeze = _load(PREREGISTRATION_FREEZE)
    source_freeze = _load(SOURCE_FREEZE)
    if source_freeze.get("status") != "frozen_before_formal_gate_execution":
        raise ValueError("v4.3 source is not frozen for formal execution")
    if source_freeze.get("preregistration_sha256") != _sha256(PREREGISTRATION):
        raise ValueError("source freeze points to another preregistration")
    _verify_references(preregistration["frozen_inputs"])
    _verify_references(preregistration_freeze["artifacts"])
    _verify_references(source_freeze["artifacts"])
    for transitive_freeze_path in (V4_2_SOURCE_FREEZE, V4_1_SOURCE_FREEZE):
        transitive_freeze = _load(transitive_freeze_path)
        _verify_references(transitive_freeze["artifacts"])
        if "frozen_inputs" in transitive_freeze:
            _verify_references(transitive_freeze["frozen_inputs"])

    v4_2_treatment = _load(V4_2_TREATMENT)
    v4_2_report = _load(V4_2_REPORT)

    external_raw = _load(EXTERNAL_RAW)
    external_selection = _load(EXTERNAL_SELECTION)
    external_input_hash = _json_sha256(external_raw)
    external_v4_2, external_v4_2_audit = normalize_raw_responses_v4_2(external_raw)
    external_v4_3, external_v4_3_audit = normalize_raw_responses_v4_3(external_raw)
    frozen_external = v4_2_treatment["external_revealed"]
    external_forward_equal = (
        external_v4_3 == external_v4_2 == frozen_external["normalized_raw"]
        and external_v4_3_audit == external_v4_2_audit == frozen_external["audit"]
    )
    external_counts = _activation_counts(external_v4_3_audit)
    external_v4_2_reverse = _restore_envelope(
        external_raw,
        external_v4_3,
        external_v4_3_audit,
        use_v4_3=False,
    )
    external_v4_3_reverse = _restore_envelope(
        external_raw,
        external_v4_3,
        external_v4_3_audit,
        use_v4_3=True,
    )
    omission_case_ids = {
        item["case_id"]
        for item in external_v4_3_audit
        if any(
            diagnostic["code"] == EMPTY_FACT_CODE for diagnostic in item["diagnostics"]
        )
    }
    long_case_ids = {
        item["case_id"]
        for item in external_v4_3_audit
        if any(
            diagnostic["code"] == LONG_EVIDENCE_CODE
            for diagnostic in item["diagnostics"]
        )
    }
    external_analyses = _strict_analyses(external_v4_3, external_selection)
    external_valid_count = sum(
        item["schema_valid"] for item in external_analyses.values()
    )
    external_anchor = _all_evidence_anchored(external_v4_3, external_selection)
    omission_reverse_count = sum(
        external_v4_3_reverse["per_case"][case_id] for case_id in omission_case_ids
    )
    long_reverse_count = sum(
        external_v4_3_reverse["per_case"][case_id] for case_id in long_case_ids
    )

    live_raw = _load(LIVE_RAW)
    live_input_hash = _json_sha256(live_raw)
    live_v4_2, live_v4_2_audit = normalize_raw_responses_v4_2(live_raw)
    live_v4_3, live_v4_3_audit = normalize_raw_responses_v4_3(live_raw)
    frozen_live = v4_2_treatment["v4_live_probe"]
    v4_1_live, _ = normalize_live_probe_raw_responses_v4_1(live_raw)
    live_forward_equal = (
        live_v4_3 == live_v4_2 == frozen_live["normalized_raw"] == v4_1_live
        and live_v4_3_audit == live_v4_2_audit == frozen_live["audit"]
    )
    live_counts = _activation_counts(live_v4_3_audit)
    live_reverse = _restore_envelope(
        live_raw, live_v4_3, live_v4_3_audit, use_v4_3=True
    )
    live_preregistration = _load(LIVE_PREREGISTRATION)
    v4_1_live_report = evaluate_live_probe_v4_1(
        _load(LIVE_SELECTION),
        live_preregistration,
        live_raw,
        frozen_inputs_valid=True,
        frozen_sources_valid=True,
    )
    v4_3_live_report = evaluate_live_probe_v4_3(
        _load(LIVE_SELECTION),
        live_preregistration,
        live_raw,
        frozen_inputs_valid=True,
        frozen_sources_valid=True,
    )
    live_gates_preserved = all(
        v4_3_live_report["gates"][name] == v4_1_live_report["gates"][name]
        for name in (
            "G1-json-and-root-topology",
            "G5-granularity-noncollapse",
            "G6-fact-layer-compatibility",
        )
    )

    dev20_raw = _load(DEV20_RAW)
    dev20_treated, dev20_audit, dev20_gate = _normalize_dev20(dev20_raw)
    dev20_frozen_equal = (
        dev20_treated == v4_2_treatment["v4_dev20"]["normalized_raw"]
        and dev20_audit == v4_2_treatment["v4_dev20"]["audit"]
    )
    dev20_gate["exactly_equals_frozen_v4_2_treatment"] = dev20_frozen_equal
    dev20_gate["passed"] = dev20_gate["passed"] and dev20_frozen_equal

    existing_controls = _existing_controls_gate(v4_2_report)
    tail_gate, tail_artifact = _tail_control_gate()
    fail_closed = _fail_closed_gate()
    static_audit = _static_audit()

    g1_passed = (
        external_forward_equal
        and live_forward_equal
        and dev20_gate["forward_exactly_equals_v4_2"]
        and dev20_frozen_equal
        and existing_controls["passed"]
        and tail_gate["forward_output_and_diagnostics_equal_v4_2"]
        and external_counts
        == {
            ROLE_ALIAS_CODE: 0,
            EMPTY_FACT_CODE: 27,
            LONG_EVIDENCE_CODE: 10,
        }
        and live_counts
        == {
            ROLE_ALIAS_CODE: 18,
            EMPTY_FACT_CODE: 0,
            LONG_EVIDENCE_CODE: 0,
        }
        and sum(dev20_gate["activation_counts"].values()) == 0
    )
    g2_passed = (
        external_forward_equal
        and len(external_v4_3["records"]) == 5
        and external_valid_count == 5
        and external_anchor
        and external_v4_3_reverse["exact_restoration_case_count"] == 5
        and omission_reverse_count == 4
        and long_reverse_count == 1
        and external_input_hash == _json_sha256(external_raw)
    )
    g3_passed = (
        live_forward_equal
        and live_counts
        == {
            ROLE_ALIAS_CODE: 18,
            EMPTY_FACT_CODE: 0,
            LONG_EVIDENCE_CODE: 0,
        }
        and live_reverse["exact_restoration_case_count"] == 5
        and live_gates_preserved
        and dev20_gate["passed"]
        and existing_controls["passed"]
        and live_input_hash == _json_sha256(live_raw)
    )
    sources_and_tests_passed = (
        arguments.targeted_tests_passed and arguments.full_suite_passed
    )
    gates = {
        "G0-frozen-inputs-source-isolation-and-zero-calls": {
            "passed": True,
            "all_frozen_and_transitive_hashes_valid": True,
            "source_freeze_valid": True,
            "new_model_call_count": 0,
            "network_call_count": 0,
            "default_parser_call_count": 0,
            "canonicalizer_call_count": 0,
            "new_holdout_loaded": False,
        },
        "G1-forward-byte-equivalence": {
            "passed": g1_passed,
            "external_output_and_audit_equal_v4_2": external_forward_equal,
            "external_activation_counts": external_counts,
            "live_output_and_audit_equal_v4_2_and_v4_1": live_forward_equal,
            "live_activation_counts": live_counts,
            "dev20_forward_equal_v4_2": dev20_gate["forward_exactly_equals_v4_2"],
            "dev20_total_activation_count": sum(
                dev20_gate["activation_counts"].values()
            ),
            "existing_16_controls_forward_equal_v4_2": existing_controls["passed"],
            "tail_control_forward_equal_v4_2": tail_gate[
                "forward_output_and_diagnostics_equal_v4_2"
            ],
        },
        "G2-external-revealed-reversibility-recovery": {
            "passed": g2_passed,
            "case_count": len(external_v4_3["records"]),
            "strict_schema_valid_case_count": external_valid_count,
            "required_strict_schema_valid_case_count": 5,
            "all_evidence_exactly_anchored": external_anchor,
            "v4_2_exact_reverse_restoration_case_count": external_v4_2_reverse[
                "exact_restoration_case_count"
            ],
            "v4_3_exact_reverse_restoration_case_count": external_v4_3_reverse[
                "exact_restoration_case_count"
            ],
            "required_exact_reverse_restoration_case_count": 5,
            "omission_case_count": len(omission_case_ids),
            "omission_reverse_restoration_case_count": omission_reverse_count,
            "long_evidence_case_count": len(long_case_ids),
            "long_evidence_reverse_restoration_case_count": long_reverse_count,
            "forward_treatment_exactly_equals_frozen_v4_2": external_forward_equal,
            "input_object_unchanged": external_input_hash == _json_sha256(external_raw),
        },
        "G3-legacy-zero-regression": {
            "passed": g3_passed,
            "live": {
                "case_count": len(live_v4_3["records"]),
                "output_exactly_equals_v4_1_and_v4_2": live_forward_equal,
                "exact_reverse_restoration_case_count": live_reverse[
                    "exact_restoration_case_count"
                ],
                "G1_G5_G6_exactly_preserved": live_gates_preserved,
                "input_object_unchanged": live_input_hash == _json_sha256(live_raw),
            },
            "dev20": dev20_gate,
            "existing_controls": existing_controls,
        },
        "G4-consecutive-tail-omission-control": tail_gate,
        "G5-fail-closed-reverse-controls": fail_closed,
        "G6-static-audit-and-tests": {
            "passed": static_audit["passed"] and sources_and_tests_passed,
            "static_audit": static_audit,
            "targeted_tests_passed": arguments.targeted_tests_passed,
            "full_suite_passed": arguments.full_suite_passed,
            "frozen_source_hashes_valid": True,
        },
    }
    passed = all(gate["passed"] for gate in gates.values())
    generated_at = datetime.now(UTC).isoformat()
    treatment = {
        "treatment_version": "unified-jd-flat-atomic-v4.3-compatibility-treated-raw-v1",
        "generated_at": generated_at,
        "status": "formal_one_time_frozen_offline_treatment",
        "model_call_count": 0,
        "network_call_count": 0,
        "new_holdout_loaded": False,
        "external_revealed": {
            "normalized_raw": external_v4_3,
            "audit": external_v4_3_audit,
        },
        "v4_live_probe": {
            "normalized_raw": live_v4_3,
            "audit": live_v4_3_audit,
        },
        "v4_dev20": {
            "normalized_raw": dev20_treated,
            "audit": dev20_audit,
        },
        "consecutive_tail_control": tail_artifact,
        "inputs": {
            "preregistration": _reference(PREREGISTRATION),
            "preregistration_freeze": _reference(PREREGISTRATION_FREEZE),
            "source_freeze": _reference(SOURCE_FREEZE),
            "v4_2_treatment": _reference(V4_2_TREATMENT),
            "external_raw": _reference(EXTERNAL_RAW),
            "live_raw": _reference(LIVE_RAW),
            "dev20_raw": _reference(DEV20_RAW),
        },
    }
    _write_new(arguments.treatment_output, treatment)
    report = {
        "report_version": "unified-jd-flat-atomic-v4.3-compatibility-report-v1",
        "generated_at": generated_at,
        "status": "formal_one_time_frozen_offline_gate_execution",
        "passed": passed,
        "decision": (
            "development_and_regression_gates_passed"
            if passed
            else "v4_3_rejected_keep_v4_1"
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
            "v4_2_treatment": _reference(V4_2_TREATMENT),
            "v4_2_report": _reference(V4_2_REPORT),
            "external_raw": _reference(EXTERNAL_RAW),
            "live_raw": _reference(LIVE_RAW),
            "dev20_raw": _reference(DEV20_RAW),
            "treatment": _reference(arguments.treatment_output),
        },
        "next_allowed_action": (
            "Freeze this report, then preregister a genuinely new independent "
            "public-job holdout and request separate transmission authorization."
            if passed
            else "Keep v4.1 and classify the frozen v4.3 failure offline."
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
