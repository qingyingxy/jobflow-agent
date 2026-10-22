from __future__ import annotations

import argparse
import copy
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.evaluation.model_first_v4_live_probe import evaluate_live_probe_v4

ROOT = Path(__file__).resolve().parents[1]
DATE = "2026-09-06"

DEFAULT_SELECTION = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_live_probe_selection_v1_2026-09-06.json"
)
DEFAULT_PREREGISTRATION = ROOT / (
    "datasets/"
    "unified_jd_flat_atomic_v4_live_probe_preregistration_v1_2026-09-06.json"
)
DEFAULT_RAW_RESPONSES = ROOT / (
    "artifacts/evaluation/"
    "unified-jd-flat-atomic-v4-live-probe-raw-responses-v1-2026-09-06.json"
)
DEFAULT_LIVE_REPORT = ROOT / (
    "artifacts/evaluation/"
    "unified-jd-flat-atomic-v4-live-probe-report-v1-2026-09-06.json"
)
DEFAULT_OUTPUT = ROOT / (
    "artifacts/evaluation/"
    "unified-jd-flat-atomic-v4-role-counterfactual-v1-2026-09-06.json"
)

TARGET_GATES = (
    "G1-json-and-root-topology",
    "G5-granularity-noncollapse",
    "G6-fact-layer-compatibility",
)


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _payload_sha256(value: object) -> str:
    rendered = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _reference(path: Path) -> dict[str, str]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": _sha256(path),
    }


def apply_responsibility_role_counterfactual(
    raw_responses: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    transformed = copy.deepcopy(raw_responses)
    records = transformed.get("records")
    if not isinstance(records, list):
        raise TypeError("raw response records must be a list")

    audit: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("case_id"), str):
            raise TypeError("raw response record requires case_id")
        raw_output = record.get("raw_model_output")
        if raw_output is None:
            continue
        if not isinstance(raw_output, dict):
            raise TypeError("raw_model_output must be an object or null")
        atoms = raw_output.get("clause_atoms")
        if not isinstance(atoms, list):
            continue
        for atom_index, atom in enumerate(atoms):
            if not isinstance(atom, dict) or atom.get("role") != "responsibility":
                continue
            if atom.get("category") != "responsibility":
                raise ValueError(
                    "refusing to normalize responsibility role outside the "
                    f"responsibility category: {record['case_id']}[{atom_index}]"
                )
            audit.append(
                {
                    "case_id": record["case_id"],
                    "atom_index": atom_index,
                    "category": atom["category"],
                    "before_role": "responsibility",
                    "after_role": "item",
                    "semantic_item_sha256": hashlib.sha256(
                        str(atom.get("semantic_item", "")).encode("utf-8")
                    ).hexdigest(),
                }
            )
            atom["role"] = "item"
    return transformed, audit


def _restore_intervention(
    transformed: dict[str, Any], audit: list[dict[str, Any]]
) -> dict[str, Any]:
    restored = copy.deepcopy(transformed)
    records = {
        record["case_id"]: record
        for record in restored["records"]
        if isinstance(record, dict) and isinstance(record.get("case_id"), str)
    }
    for item in audit:
        records[item["case_id"]]["raw_model_output"]["clause_atoms"][
            item["atom_index"]
        ]["role"] = item["before_role"]
    return restored


def _evaluate(
    selection: dict[str, Any],
    preregistration: dict[str, Any],
    raw_responses: dict[str, Any],
) -> dict[str, Any]:
    return evaluate_live_probe_v4(
        selection,
        preregistration,
        raw_responses,
        authorization_confirmed=True,
        destination_valid=True,
        frozen_inputs_valid=True,
        frozen_sources_valid=True,
        gold_unavailable_to_requests=True,
    )


def _assert_baseline_reproduced(
    baseline: dict[str, Any], live_report: dict[str, Any]
) -> None:
    for key, value in baseline.items():
        if live_report.get(key) != value:
            raise ValueError(f"offline baseline differs from live report at {key}")


def _case_snapshot(report: dict[str, Any]) -> list[dict[str, Any]]:
    fields = (
        "case_id",
        "schema_valid",
        "atom_count",
        "primary_atom_count",
        "example_atom_count",
        "source_text_count",
        "located_source_text_count",
        "nonnull_primary_surface_count",
        "located_nonnull_primary_surface_count",
        "separated_pair_count",
        "fact_layer_compatible",
    )
    return [
        {field: item[field] for field in fields}
        for item in report["per_case"]
    ]


def build_counterfactual_report(
    selection: dict[str, Any],
    preregistration: dict[str, Any],
    raw_responses: dict[str, Any],
    live_report: dict[str, Any],
) -> dict[str, Any]:
    baseline = _evaluate(selection, preregistration, raw_responses)
    _assert_baseline_reproduced(baseline, live_report)
    transformed, audit = apply_responsibility_role_counterfactual(raw_responses)
    if not audit:
        raise ValueError("counterfactual found no responsibility role values")
    restored = _restore_intervention(transformed, audit)
    if restored != raw_responses:
        raise ValueError("counterfactual changed fields outside the audited role values")
    counterfactual = _evaluate(selection, preregistration, transformed)

    target_results = {
        gate_name: {
            "baseline": baseline["gates"][gate_name],
            "counterfactual": counterfactual["gates"][gate_name],
            "recovered": (
                not baseline["gates"][gate_name]["passed"]
                and counterfactual["gates"][gate_name]["passed"]
            ),
        }
        for gate_name in TARGET_GATES
    }
    return {
        "report_version": (
            "unified-jd-flat-atomic-v4-role-counterfactual-v1"
        ),
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "offline_counterfactual_from_frozen_raw",
        "method": {
            "frozen_raw_only": True,
            "offline_network_call_count": 0,
            "new_model_call_count": 0,
            "source_model_call_count": raw_responses.get("model_call_count"),
            "parser_executed": False,
            "canonicalizer_executed": False,
            "gold_used": False,
            "evaluator": "evaluate_live_probe_v4",
            "intervention": (
                "For every atom with role=responsibility and "
                "category=responsibility, replace role with item."
            ),
            "treatment_fields": ["records[*].raw_model_output.clause_atoms[*].role"],
            "threshold_or_gate_changes": False,
        },
        "integrity": {
            "baseline_reproduces_live_report": True,
            "reverse_transform_restores_frozen_raw": True,
            "changed_field_count": len(audit),
            "changed_case_ids": sorted({item["case_id"] for item in audit}),
            "transformed_payload_sha256": _payload_sha256(transformed),
            "audit": audit,
        },
        "target_gates": target_results,
        "all_target_gates_recovered": all(
            item["recovered"] for item in target_results.values()
        ),
        "baseline": {
            "passed": baseline["passed"],
            "gates": baseline["gates"],
            "per_case": _case_snapshot(baseline),
        },
        "counterfactual": {
            "passed": counterfactual["passed"],
            "gates": counterfactual["gates"],
            "per_case": _case_snapshot(counterfactual),
        },
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate the responsibility-role counterfactual from frozen raw"
    )
    parser.add_argument("--selection", type=Path, default=DEFAULT_SELECTION)
    parser.add_argument("--preregistration", type=Path, default=DEFAULT_PREREGISTRATION)
    parser.add_argument("--raw-responses", type=Path, default=DEFAULT_RAW_RESPONSES)
    parser.add_argument("--live-report", type=Path, default=DEFAULT_LIVE_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    arguments = _parse_args()
    if arguments.output.exists():
        raise FileExistsError(f"counterfactual report already exists: {arguments.output}")
    raw_sha256_before = _sha256(arguments.raw_responses)
    report = build_counterfactual_report(
        _load(arguments.selection),
        _load(arguments.preregistration),
        _load(arguments.raw_responses),
        _load(arguments.live_report),
    )
    raw_sha256_after = _sha256(arguments.raw_responses)
    if raw_sha256_after != raw_sha256_before:
        raise ValueError("frozen raw changed during offline evaluation")
    report["inputs"] = {
        "selection": _reference(arguments.selection),
        "preregistration": _reference(arguments.preregistration),
        "frozen_raw_responses": _reference(arguments.raw_responses),
        "live_report": _reference(arguments.live_report),
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    with arguments.output.open("x", encoding="utf-8", newline="\n") as output:
        json.dump(report, output, ensure_ascii=False, indent=2)
        output.write("\n")
    print(
        json.dumps(
            {
                "output": _reference(arguments.output),
                "changed_field_count": report["integrity"]["changed_field_count"],
                "target_gates": {
                    name: result["counterfactual"]["passed"]
                    for name, result in report["target_gates"].items()
                },
                "all_target_gates_recovered": report[
                    "all_target_gates_recovered"
                ],
                "all_counterfactual_gates_passed": report["counterfactual"][
                    "passed"
                ],
                "new_model_call_count": 0,
                "offline_network_call_count": 0,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["all_target_gates_recovered"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
