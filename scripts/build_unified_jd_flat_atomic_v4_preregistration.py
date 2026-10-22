from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATE = "2026-09-05"

MANIFEST_PATH = (
    ROOT / "artifacts/evaluation/unified-jd-model-first-v1-dev20-2026-09-05.json"
)
V1_PREDICTIONS_PATH = ROOT / (
    "artifacts/evaluation/"
    "unified-jd-model-first-v1-dev20-predictions-v1-2026-09-05.json"
)
V3_PROJECTION_PATH = ROOT / (
    "artifacts/evaluation/"
    "unified-jd-model-first-v3-dev20-layer-projection-2026-09-05.json"
)
V3_REPORT_PATH = ROOT / (
    "artifacts/evaluation/unified-jd-model-first-v3-dev20-report-2026-09-05.json"
)
V3_PROBE_RAW_PATH = ROOT / (
    "artifacts/evaluation/"
    "unified-jd-model-first-v3-surface-probe-case121-raw-response-2026-09-05.json"
)
V3_PROBE_ANALYSIS_PATH = ROOT / (
    "artifacts/evaluation/"
    "unified-jd-model-first-v3-surface-probe-case121-offline-analysis-2026-09-05.json"
)

PARSER_PATH = ROOT / "src/services/unified_jd_parser.py"
CANONICALIZER_PATH = ROOT / "src/domain/unified_jd_canonicalizer.py"
V3_DOMAIN_PATH = ROOT / "src/domain/unified_jd_extraction.py"
V3_COMPILER_PATH = ROOT / "src/services/unified_jd_extraction.py"
V3_EVALUATOR_PATH = ROOT / "src/evaluation/model_first_v3.py"

PREREGISTRATION_PATH = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_preregistration_v1_2026-09-05.json"
)
FREEZE_PATH = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_preregistration_freeze_v1_2026-09-05.json"
)

IMPLEMENTATION_TARGETS = (
    ROOT / "src/domain/unified_jd_flat_atomic_v4.py",
    ROOT / "src/services/unified_jd_flat_atomic_v4.py",
    ROOT / "src/evaluation/model_first_v4.py",
    ROOT / "scripts/replay_unified_jd_flat_atomic_v4.py",
    ROOT / "tests/test_unified_jd_flat_atomic_v4.py",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _input_entry(path: Path) -> dict[str, str]:
    return {"path": _relative(path), "sha256": _sha256(path)}


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected an object: {path}")
    return value


def _last_raw_output(prediction: dict[str, Any]) -> dict[str, Any]:
    attempts = prediction.get("diagnostics", {}).get("model_attempts")
    if not isinstance(attempts, list) or not attempts:
        raise ValueError(f"missing model attempts: {prediction.get('case_id')}")
    raw_output = attempts[-1].get("raw_model_output")
    if not isinstance(raw_output, dict):
        raise TypeError(f"missing raw model output: {prediction.get('case_id')}")
    return raw_output


def _observed_basis() -> dict[str, Any]:
    manifest = _load(MANIFEST_PATH)
    predictions = _load(V1_PREDICTIONS_PATH)
    projection = _load(V3_PROJECTION_PATH)
    report = _load(V3_REPORT_PATH)
    probe_raw = _load(V3_PROBE_RAW_PATH)
    probe_analysis = _load(V3_PROBE_ANALYSIS_PATH)

    prediction_records = predictions.get("predictions")
    projection_records = projection.get("records")
    if not isinstance(prediction_records, list) or not isinstance(
        projection_records, list
    ):
        raise TypeError("frozen V1 predictions and V3 projection require record lists")
    if len(manifest.get("cases", [])) != 20:
        raise ValueError("frozen development manifest must contain 20 cases")
    if len(prediction_records) != 20 or len(projection_records) != 20:
        raise ValueError("frozen prediction and projection files must contain 20 cases")

    valid_clause_count = sum(len(record["clauses"]) for record in projection_records)
    primary_item_count = sum(
        len(clause["items"])
        for record in projection_records
        for clause in record["clauses"]
    )
    example_item_count = sum(
        len(clause["examples"])
        for record in projection_records
        for clause in record["clauses"]
    )
    case121_item_count = sum(
        len(clause["items"])
        for record in projection_records
        if record["case_id"] == "campus-ai-121"
        for clause in record["clauses"]
    )
    projection_diagnostics = [
        diagnostic
        for record in projection_records
        for diagnostic in record.get("diagnostics", [])
    ]

    v1_model_calls = sum(
        int(record.get("model_call_count") or 0) for record in prediction_records
    )
    probe_model_calls = int(probe_raw.get("model_call_count") or 0)
    raw_clause_count = sum(
        len(_last_raw_output(record).get("clauses", []))
        for record in prediction_records
    )
    raw_primary_item_count = sum(
        len(clause.get("items") or [])
        for record in prediction_records
        for clause in _last_raw_output(record).get("clauses", [])
    )
    raw_probe_output = probe_raw.get("raw_model_output")
    if not isinstance(raw_probe_output, dict):
        raise TypeError("probe raw response is missing raw_model_output")
    raw_probe_clauses = raw_probe_output.get("clauses")
    if not isinstance(raw_probe_clauses, list):
        raise TypeError("probe raw response clauses must be a list")

    clause_layers = report["layers"]["clauses"]
    fact_layers = report["layers"]["facts"]
    derived_facts = report["stages"]["derived"]["facts"]
    derived_checks = report["stages"]["derived"]["hard_checks"]
    basis = {
        "development_case_count": len(manifest["cases"]),
        "v1_raw_clause_count_before_source_validation": raw_clause_count,
        "v1_raw_primary_item_count_before_source_validation": raw_primary_item_count,
        "source_valid_clause_count": valid_clause_count,
        "source_valid_primary_item_count": primary_item_count,
        "source_valid_example_item_count": example_item_count,
        "primary_exact_surface_count": clause_layers["exact_surface_count"],
        "primary_unmapped_surface_count": clause_layers["unmapped_surface_count"],
        "case121_source_valid_primary_item_count": case121_item_count,
        "v1_unlocated_clause_count": sum(
            diagnostic.get("code") == "unlocated_clause_source"
            for diagnostic in projection_diagnostics
        ),
        "fact_raw_item_count": fact_layers["raw_item_count"],
        "fact_exact_surface_count": fact_layers["exact_surface_count"],
        "fact_unmapped_surface_count": fact_layers["unmapped_surface_count"],
        "derived_facts_macro_f1": derived_facts["macro_f1"],
        "derived_major_f1": derived_facts["fields"]["major_requirements"]["f1"],
        "derived_fact_hard_checks": derived_checks,
        "nested_v3_probe_clause_count": len(raw_probe_clauses),
        "nested_v3_probe_clauses_missing_category": sum(
            "category" not in clause for clause in raw_probe_clauses
        ),
        "nested_v3_probe_schema_valid": probe_analysis["mechanism_checks"][
            "required_response_topology_was_followed"
        ],
        "consumed_model_call_count": v1_model_calls + probe_model_calls,
        "remaining_model_call_budget": 0,
    }
    expected = {
        "development_case_count": 20,
        "v1_raw_clause_count_before_source_validation": 174,
        "v1_raw_primary_item_count_before_source_validation": 403,
        "source_valid_clause_count": 171,
        "source_valid_primary_item_count": 394,
        "source_valid_example_item_count": 33,
        "primary_exact_surface_count": 335,
        "primary_unmapped_surface_count": 59,
        "case121_source_valid_primary_item_count": 22,
        "v1_unlocated_clause_count": 3,
        "fact_raw_item_count": 155,
        "fact_exact_surface_count": 149,
        "fact_unmapped_surface_count": 6,
        "nested_v3_probe_clause_count": 3,
        "nested_v3_probe_clauses_missing_category": 3,
        "nested_v3_probe_schema_valid": False,
        "consumed_model_call_count": 21,
        "remaining_model_call_budget": 0,
    }
    for key, value in expected.items():
        if basis[key] != value:
            raise ValueError(f"frozen observation changed for {key}: {basis[key]!r}")
    return basis


def _build_preregistration(basis: dict[str, Any]) -> dict[str, Any]:
    inputs = {
        "development_manifest": _input_entry(MANIFEST_PATH),
        "v1_predictions_with_raw_responses": _input_entry(V1_PREDICTIONS_PATH),
        "v3_layer_projection": _input_entry(V3_PROJECTION_PATH),
        "v3_layer_report": _input_entry(V3_REPORT_PATH),
        "nested_v3_case121_raw_response": _input_entry(V3_PROBE_RAW_PATH),
        "nested_v3_case121_offline_analysis": _input_entry(V3_PROBE_ANALYSIS_PATH),
        "default_parser": _input_entry(PARSER_PATH),
        "canonicalizer": _input_entry(CANONICALIZER_PATH),
        "v3_domain_contract": _input_entry(V3_DOMAIN_PATH),
        "v3_compiler": _input_entry(V3_COMPILER_PATH),
        "v3_evaluator": _input_entry(V3_EVALUATOR_PATH),
    }
    return {
        "preregistration_version": "unified-jd-flat-atomic-v4-preregistration-v1",
        "date": DATE,
        "status": "preregistered_before_implementation",
        "objective": (
            "Replace nested model-owned non-fact clauses with one flat record per "
            "semantic atom, while retaining the already validated V3 fact layers."
        ),
        "causal_claim_under_test": (
            "The remaining clause failure is chiefly a response-topology and "
            "granularity burden. A flat atomic contract can preserve every valid V1 "
            "semantic item and its observed surface status, after which a deterministic "
            "local compiler can reconstruct clause groups without semantic guessing."
        ),
        "frozen_inputs": inputs,
        "observed_basis": basis,
        "scope": {
            "model_calls_allowed": False,
            "network_calls_allowed": False,
            "canonicalizer_work_allowed": False,
            "nested_model_first_v3_activation_allowed": False,
            "default_parser_modification_allowed": False,
            "v1_v2_v3_artifact_overwrite_allowed": False,
            "facts_policy": (
                "Retain V3 raw, normalized, and derived fact layers byte-for-byte; "
                "this version changes only the non-fact clause contract."
            ),
        },
        "flat_atomic_contract": {
            "root_field": "clause_atoms",
            "one_record_per_semantic_atom": True,
            "fields": {
                "role": "item or example",
                "category": "required explicit semantic clause category",
                "level": "required explicit clause level",
                "relation": "required explicit all_of or any_of",
                "semantic_item": "one independently understandable semantic atom",
                "surface_item": (
                    "exact source substring or null when no exact surface is observed"
                ),
                "source_text": "one exact source evidence span",
                "group_name": "explicit any_of label, otherwise null",
                "allow_other": "explicit boolean",
                "qualifier": "explicit experience qualifier or null",
            },
            "prohibitions": [
                "nested clauses or nested item arrays",
                "multiple semantic atoms in one record",
                "category, level, or relation inference during compilation",
                "surface recovery from semantic text",
                "fact normalization or derivation inside the clause contract",
            ],
        },
        "deterministic_grouping_compiler": {
            "group_key_in_order": [
                "source_text",
                "category",
                "level",
                "relation",
                "group_name",
                "allow_other",
                "qualifier",
            ],
            "order_policy": (
                "Preserve first-seen group order and atom order; role determines items "
                "versus examples."
            ),
            "source_policy": (
                "source_text and every non-null surface_item must be exact substrings "
                "of the supplied JD; null surfaces stay unmapped."
            ),
            "forbidden_runtime_inputs": [
                "gold labels or expected outputs",
                "case or fixture identifiers",
                "company, title, URL, or source origin",
                "canonicalizer output",
                "model or network responses",
            ],
            "forbidden_repairs": [
                "cross-source_text merge",
                "missing category, level, or relation backfill",
                "semantic-to-surface guessing",
                "dropping or splitting semantic atoms",
            ],
        },
        "acceptance_gates": {
            "G0-frozen-inputs-and-zero-calls": {
                "requirements": [
                    "Every frozen input hash matches before execution.",
                    "Model call count and network call count are both zero.",
                    "All outputs use exclusive creation and no V1-V3 file changes.",
                ]
            },
            "G1-contract-and-source-validity": {
                "requirements": [
                    "Every emitted atom validates against the frozen flat schema.",
                    "Every source_text is an exact JD substring.",
                    "Every non-null surface_item is an exact source_text substring.",
                    "All 59 unmapped primary surfaces remain null and are not guessed.",
                ]
            },
            "G2-flat-group-round-trip": {
                "source_valid_clause_count": 171,
                "required_primary_item_count": 394,
                "required_example_item_count": 33,
                "requirement": (
                    "After flattening and grouping, category, level, relation, "
                    "source_text, group_name, allow_other, qualifier, items, and "
                    "examples exactly match every source-valid frozen V1 clause in order."
                ),
            },
            "G3-case121-granularity": {
                "case_id": "campus-ai-121",
                "required_primary_item_count": 22,
                "forbidden_collapsed_item_count": 8,
            },
            "G4-surface-accounting": {
                "primary_exact_surface_count": 335,
                "primary_unmapped_surface_count": 59,
                "requirement": (
                    "Surface status and values match the frozen V3 projection exactly; "
                    "unmapped values remain null."
                ),
            },
            "G5-invalid-nested-v3-fails-closed": {
                "probe_clause_count": 3,
                "required_missing_category_count": 3,
                "required_accepted_atom_count": 0,
                "requirement": (
                    "The invalid nested V3 response is classified nonrecoverable for "
                    "clause compilation; no category, source_text, level, or relation "
                    "may be guessed or inherited from fixture data."
                ),
            },
            "G6-v3-facts-unchanged": {
                "derived_facts_macro_f1": basis["derived_facts_macro_f1"],
                "derived_major_f1": basis["derived_major_f1"],
                "fact_raw_item_count": 155,
                "fact_exact_surface_count": 149,
                "fact_unmapped_surface_count": 6,
                "source_unsupported_critical_fact_count": 0,
            },
            "G7-isolation-and-static-audit": {
                "requirements": [
                    "Default parser and canonicalizer hashes remain frozen.",
                    "No v4 runtime module imports model clients, networking, or the canonicalizer.",
                    "No runtime branch reads case ids, job metadata, gold, or fixture paths.",
                    "Existing model-first V3 tests pass unchanged.",
                ]
            },
        },
        "evaluation_protocol": {
            "all_gates_conjunctive": True,
            "source_and_evaluator_freeze_before_gate_execution": True,
            "development_run_count": 1,
            "rerun_after_failure_allowed": False,
            "threshold_change_after_freeze_allowed": False,
            "raw_written_before_report": True,
            "write_new_outputs_only": True,
            "failure_policy": (
                "Keep failed raw and report; diagnose offline and preregister a new "
                "version without editing or rerunning v4."
            ),
        },
        "post_gate_protocol": {
            "on_pass": (
                "Keep v4 opt-in and connect it to a future model request only under a "
                "new preregistration; do not start canonicalizer work yet."
            ),
            "on_fail": "Retain the V1 clause path and the V3 facts-only result.",
        },
    }


def _write_new_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    with path.open("x", encoding="utf-8", newline="\n") as output:
        output.write(rendered)


def main() -> int:
    existing_outputs = [path for path in (PREREGISTRATION_PATH, FREEZE_PATH) if path.exists()]
    if existing_outputs:
        raise SystemExit(
            f"refusing to overwrite preregistration: {[str(path) for path in existing_outputs]}"
        )
    existing_targets = [path for path in IMPLEMENTATION_TARGETS if path.exists()]
    if existing_targets:
        raise SystemExit(
            "implementation must not exist before preregistration: "
            f"{[str(path) for path in existing_targets]}"
        )

    required_inputs = (
        MANIFEST_PATH,
        V1_PREDICTIONS_PATH,
        V3_PROJECTION_PATH,
        V3_REPORT_PATH,
        V3_PROBE_RAW_PATH,
        V3_PROBE_ANALYSIS_PATH,
        PARSER_PATH,
        CANONICALIZER_PATH,
        V3_DOMAIN_PATH,
        V3_COMPILER_PATH,
        V3_EVALUATOR_PATH,
    )
    missing = [path for path in required_inputs if not path.is_file()]
    if missing:
        raise SystemExit(f"missing preregistration inputs: {[str(path) for path in missing]}")

    basis = _observed_basis()
    preregistration = _build_preregistration(basis)
    _write_new_json(PREREGISTRATION_PATH, preregistration)
    freeze = {
        "freeze_version": "unified-jd-flat-atomic-v4-preregistration-freeze-v1",
        "frozen_at": datetime.now(UTC).isoformat(),
        "status": "frozen_before_implementation",
        "artifacts": {
            "preregistration": _input_entry(PREREGISTRATION_PATH),
            "builder": _input_entry(Path(__file__).resolve()),
        },
        "frozen_inputs": preregistration["frozen_inputs"],
        "checks": {
            "implementation_targets_existed_at_freeze": False,
            "model_call_count_available": 0,
            "network_call_count_available": 0,
            "historical_model_call_budget_consumed": basis[
                "consumed_model_call_count"
            ],
            "historical_model_call_budget_remaining": basis[
                "remaining_model_call_budget"
            ],
            "canonicalizer_allowed": False,
            "nested_model_first_v3_activation_allowed": False,
            "default_parser_modification_allowed": False,
        },
        "immutability": (
            "Any change to the atom schema, grouping key, source policy, gate, threshold, "
            "or frozen input requires a new preregistration before implementation."
        ),
        "next_allowed_action": (
            "Implement only the flat atomic v4 contract, deterministic compiler, offline "
            "evaluator, runner, and tests; freeze their source, then execute the gates once."
        ),
    }
    _write_new_json(FREEZE_PATH, freeze)
    print(
        "flat atomic v4 preregistered "
        f"cases={basis['development_case_count']} "
        f"items={basis['source_valid_primary_item_count']} "
        f"unmapped={basis['primary_unmapped_surface_count']} calls_available=0"
    )
    print(f"preregistration={PREREGISTRATION_PATH}")
    print(f"freeze={FREEZE_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
