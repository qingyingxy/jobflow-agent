from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from src.evaluation.model_first_v4_live_probe import analyze_live_response_v4
from src.services.unified_jd_flat_atomic_v4_3_compatibility import (
    normalize_flat_atomic_v4_3_wire_output,
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

V4_3_ADAPTER = ROOT / "src/services/unified_jd_flat_atomic_v4_3_compatibility.py"
V4_3_SOURCE_FREEZE = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_3_compatibility_source_freeze_"
    "v1_2026-09-06.json"
)
V4_3_REPORT = ROOT / (
    "artifacts/evaluation/unified-jd-flat-atomic-v4-3-compatibility-"
    "report-v1-2026-09-06.json"
)

INDEPENDENT_RAW = ROOT / (
    "artifacts/evaluation/unified-jd-flat-atomic-v4-3-independent-holdout-"
    "raw-v1-2026-09-06.json"
)
INDEPENDENT_SELECTION = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_3_independent_holdout_selection_"
    "v1_2026-09-06.json"
)
INDEPENDENT_REPORT = ROOT / (
    "artifacts/evaluation/unified-jd-flat-atomic-v4-3-independent-holdout-"
    "report-v1-2026-09-06.json"
)
INDEPENDENT_RECEIPT = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_3_independent_holdout_evaluation_"
    "receipt_v1_2026-09-06.json"
)

CATEGORY_ORACLE_PREREGISTRATION = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_3_category_vocabulary_admission_oracle_"
    "preregistration_v1_2026-09-06.json"
)
CATEGORY_ORACLE_SOURCE_FREEZE = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_3_category_vocabulary_admission_oracle_"
    "source_freeze_v1_2026-09-06.json"
)
CATEGORY_ORACLE_REPORT = ROOT / (
    "artifacts/evaluation/unified-jd-flat-atomic-v4-3-category-vocabulary-"
    "admission-oracle-report-v1-2026-09-06.json"
)
ZERO_ORACLE_PREREGISTRATION = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_3_zero_lower_bound_qualifier_oracle_"
    "preregistration_v1_2026-09-06.json"
)
ZERO_ORACLE_SOURCE_FREEZE = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_3_zero_lower_bound_qualifier_oracle_"
    "source_freeze_v1_2026-09-06.json"
)
ZERO_ORACLE_REPORT = ROOT / (
    "artifacts/evaluation/unified-jd-flat-atomic-v4-3-zero-lower-bound-"
    "qualifier-oracle-report-v1-2026-09-06.json"
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
HUMAN_CATEGORY_REFERENCE = ROOT / (
    "datasets/unified_jd_structured_span_v4_corpus_external_labels_"
    "v1_2026-09-04.json"
)

FUTURE_IMPLEMENTATION_PATHS = (
    ROOT / "src/services/unified_jd_flat_atomic_v4_4_compatibility.py",
    ROOT / "src/evaluation/model_first_v4_4_compatibility.py",
    ROOT / "scripts/evaluate_unified_jd_flat_atomic_v4_4_compatibility_gates.py",
    ROOT / "tests/test_unified_jd_flat_atomic_v4_4_compatibility.py",
    ROOT / "datasets/unified_jd_flat_atomic_v4_4_compatibility_source_freeze_v1_2026-09-06.json",
)

ALIASES = {"knowledge": "skill", "motivation": "capability"}
ZERO_PATTERN = re.compile(
    r"(?<!\d)0\s*(?:-|–|—|to)\s*\d+\s*(?:years?|yrs?|months?)\b",
    flags=re.IGNORECASE,
)
QUALIFIER_FIELDS = {"experience_type", "minimum_months", "domain"}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected object: {path}")
    return value


def _reference(path: Path) -> dict[str, str]:
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": _sha256(path)}


def _write_new(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as output:
        json.dump(payload, output, ensure_ascii=False, indent=2)
        output.write("\n")


def _atoms(record: dict[str, Any]) -> list[dict[str, Any]]:
    output = record.get("raw_model_output")
    values = output.get("clause_atoms") if isinstance(output, dict) else None
    if values is None:
        values = record.get("clause_atoms")
    if not isinstance(values, list) or not all(isinstance(atom, dict) for atom in values):
        raise TypeError("frozen record does not contain object clause atoms")
    return values


def _zero_eligible(atom: dict[str, Any]) -> bool:
    qualifier = atom.get("qualifier")
    source = atom.get("source_text")
    surface = atom.get("surface_item")
    return bool(
        atom.get("category") == "experience"
        and isinstance(qualifier, dict)
        and set(qualifier) == QUALIFIER_FIELDS
        and type(qualifier.get("minimum_months")) is int
        and qualifier["minimum_months"] == 0
        and isinstance(source, str)
        and isinstance(surface, str)
        and surface in source
        and (ZERO_PATTERN.search(source) or ZERO_PATTERN.search(surface))
    )


def _candidate_observations(
    raw: dict[str, Any],
    *,
    cohort: str,
) -> dict[str, Any]:
    category_candidates: list[dict[str, Any]] = []
    zero_candidates: list[dict[str, Any]] = []
    atom_count = 0
    for record_index, record in enumerate(raw["records"]):
        for atom_index, atom in enumerate(_atoms(record)):
            atom_count += 1
            category = atom.get("category")
            if category in ALIASES:
                category_candidates.append(
                    {
                        "record_index": record_index,
                        "case_id": record["case_id"],
                        "atom_index": atom_index,
                        "path": f"clause_atoms[{atom_index}].category",
                        "before": category,
                        "after": ALIASES[category],
                    }
                )
            if _zero_eligible(atom):
                zero_candidates.append(
                    {
                        "record_index": record_index,
                        "case_id": record["case_id"],
                        "atom_index": atom_index,
                        "path": (
                            f"clause_atoms[{atom_index}].qualifier.minimum_months"
                        ),
                        "before": 0,
                        "after": None,
                        "source_text": atom["source_text"],
                    }
                )
    return {
        "cohort": cohort,
        "record_count": len(raw["records"]),
        "atom_count": atom_count,
        "category_alias_candidates": category_candidates,
        "zero_lower_bound_candidates": zero_candidates,
        "new_candidate_count": len(category_candidates) + len(zero_candidates),
    }


def _development_observations(
    raw: dict[str, Any], selection: dict[str, Any]
) -> dict[str, Any]:
    source_by_case = {
        case["case_id"]: case["raw_content"] for case in selection["cases"]
    }
    baseline_valid: dict[str, bool] = {}
    v4_3_counts: Counter[str] = Counter()
    for record in raw["records"]:
        result = normalize_flat_atomic_v4_3_wire_output(record["raw_model_output"])
        v4_3_counts.update(item.code for item in result.diagnostics)
        baseline_valid[record["case_id"]] = analyze_live_response_v4(
            result.output,
            source_by_case[record["case_id"]],
        )["schema_valid"]
    candidates = _candidate_observations(raw, cohort="revealed-independent-5")
    expected_categories = [
        {
            "record_index": 0,
            "case_id": "independent-lever-collate-ai-engineer",
            "atom_index": 10,
            "path": "clause_atoms[10].category",
            "before": "motivation",
            "after": "capability",
        },
        {
            "record_index": 4,
            "case_id": "independent-smartrecruiters-bluescope-ai-engineer",
            "atom_index": 22,
            "path": "clause_atoms[22].category",
            "before": "knowledge",
            "after": "skill",
        },
    ]
    expected_zero = [
        {
            "record_index": 2,
            "case_id": "independent-greenhouse-simplifynext-ai-engineer-graduate",
            "atom_index": 27,
            "path": "clause_atoms[27].qualifier.minimum_months",
            "before": 0,
            "after": None,
            "source_text": (
                "• 0–3 years of AI development experience "
                "(Fresh graduates are welcome to apply)"
            ),
        }
    ]
    if candidates["category_alias_candidates"] != expected_categories:
        raise ValueError("development category alias candidates changed")
    if candidates["zero_lower_bound_candidates"] != expected_zero:
        raise ValueError("development zero-lower-bound candidates changed")
    if sum(baseline_valid.values()) != 2 or sum(v4_3_counts.values()) != 11:
        raise ValueError("development v4.3 baseline changed")
    candidates.update(
        {
            "v4_3_strict_valid_case_count": sum(baseline_valid.values()),
            "v4_3_valid_by_case": baseline_valid,
            "v4_3_activation_counts": dict(v4_3_counts),
        }
    )
    return candidates


def _policy_evidence(raw: dict[str, Any], human: dict[str, Any]) -> dict[str, Any]:
    knowledge_skill_controls: list[dict[str, Any]] = []
    seen_statements: set[tuple[str, str]] = set()
    for record in raw["records"]:
        for atom_index, atom in enumerate(_atoms(record)):
            source_text = atom.get("source_text")
            statement = (record["case_id"], source_text)
            if (
                atom.get("category") == "skill"
                and isinstance(source_text, str)
                and "knowledge of" in source_text.casefold()
                and statement not in seen_statements
            ):
                seen_statements.add(statement)
                knowledge_skill_controls.append(
                    {
                        "case_id": record["case_id"],
                        "atom_index": atom_index,
                        "category": atom["category"],
                        "source_text": source_text,
                    }
                )
    human_control = next(
        item
        for item in human["fixtures"]
        if item["id"] == "structured-corpus-external-v1-019"
    )
    if len(knowledge_skill_controls) != 3:
        raise ValueError("knowledge-to-skill analog controls changed")
    if human_control["category"] != "capability" or "探索欲" not in human_control[
        "source_text"
    ]:
        raise ValueError("motivation-to-capability human control changed")
    return {
        "knowledge_to_skill_same_batch_analog_count": len(knowledge_skill_controls),
        "knowledge_to_skill_same_batch_analogs": knowledge_skill_controls,
        "motivation_to_capability_human_control": {
            "id": human_control["id"],
            "category": human_control["category"],
            "source_text": human_control["source_text"],
            "annotation_status": human_control["annotation_status"],
        },
        "policy_limit": (
            "These analogs justify a frozen compatibility alias policy; they do not "
            "establish a new universal category ontology."
        ),
    }


def _inputs() -> dict[str, dict[str, str]]:
    return {
        "frozen_v4_3_adapter": _reference(V4_3_ADAPTER),
        "frozen_v4_3_source_freeze": _reference(V4_3_SOURCE_FREEZE),
        "frozen_v4_3_report": _reference(V4_3_REPORT),
        "revealed_independent_raw": _reference(INDEPENDENT_RAW),
        "revealed_independent_selection": _reference(INDEPENDENT_SELECTION),
        "revealed_independent_report": _reference(INDEPENDENT_REPORT),
        "revealed_independent_receipt": _reference(INDEPENDENT_RECEIPT),
        "category_oracle_preregistration": _reference(
            CATEGORY_ORACLE_PREREGISTRATION
        ),
        "category_oracle_source_freeze": _reference(CATEGORY_ORACLE_SOURCE_FREEZE),
        "category_oracle_report": _reference(CATEGORY_ORACLE_REPORT),
        "zero_oracle_preregistration": _reference(ZERO_ORACLE_PREREGISTRATION),
        "zero_oracle_source_freeze": _reference(ZERO_ORACLE_SOURCE_FREEZE),
        "zero_oracle_report": _reference(ZERO_ORACLE_REPORT),
        "legacy_dev20_raw": _reference(DEV20_RAW),
        "legacy_live_raw": _reference(LIVE_RAW),
        "legacy_live_selection": _reference(LIVE_SELECTION),
        "legacy_external_raw": _reference(EXTERNAL_RAW),
        "legacy_external_selection": _reference(EXTERNAL_SELECTION),
        "human_category_reference": _reference(HUMAN_CATEGORY_REFERENCE),
    }


def _preregistration() -> dict[str, Any]:
    independent_raw = _load(INDEPENDENT_RAW)
    development = _development_observations(
        independent_raw,
        _load(INDEPENDENT_SELECTION),
    )
    regression = {
        "legacy_dev20": _candidate_observations(
            _load(DEV20_RAW), cohort="legacy-dev20"
        ),
        "legacy_live_probe": _candidate_observations(
            _load(LIVE_RAW), cohort="legacy-live-probe"
        ),
        "legacy_external_holdout": _candidate_observations(
            _load(EXTERNAL_RAW), cohort="legacy-external-holdout"
        ),
    }
    if any(item["new_candidate_count"] for item in regression.values()):
        raise ValueError("legacy regression contains a new v4.4 activation candidate")
    category_report = _load(CATEGORY_ORACLE_REPORT)
    zero_report = _load(ZERO_ORACLE_REPORT)
    if not category_report.get("accepted") or not zero_report.get("accepted"):
        raise ValueError("both independent causal oracles must be accepted")
    return {
        "preregistration_version": (
            "unified-jd-flat-atomic-v4.4-compatibility-preregistration-v1"
        ),
        "date": DATE,
        "status": "preregistered_before_v4_4_implementation_and_execution",
        "objective": (
            "Compose only the two independently supported residual mechanisms after "
            "frozen v4.3, while converting category vocabulary variants into the "
            "existing four-category contract instead of widening it."
        ),
        "claim_boundary": (
            "v4.4 is a revealed-development compatibility candidate. A full offline "
            "pass establishes deterministic recovery and legacy non-regression only; "
            "it does not establish external generalization or authorize a schema "
            "ontology expansion."
        ),
        "frozen_inputs": _inputs(),
        "frozen_observations": {
            "development": development,
            "regression": regression,
            "category_policy_evidence": _policy_evidence(
                independent_raw,
                _load(HUMAN_CATEGORY_REFERENCE),
            ),
            "independent_oracle_results": {
                "category": {
                    "accepted": category_report["accepted"],
                    "baseline_valid": category_report[
                        "baseline_strict_schema_valid_case_count"
                    ],
                    "oracle_valid": category_report[
                        "oracle_strict_schema_valid_case_count"
                    ],
                },
                "zero_lower_bound": {
                    "accepted": zero_report["accepted"],
                    "baseline_valid": zero_report[
                        "baseline_strict_schema_valid_case_count"
                    ],
                    "oracle_valid": zero_report[
                        "oracle_strict_schema_valid_case_count"
                    ],
                },
            },
        },
        "runtime_contract": {
            "version": "unified-jd-flat-atomic-v4.4-compatibility-v1",
            "pipeline": [
                {
                    "order": "1-3",
                    "mechanism": "frozen-v4.3-forward-unchanged",
                    "source": _reference(V4_3_ADAPTER),
                },
                {
                    "order": 4,
                    "mechanism": "category-literal-alias",
                    "activation": (
                        "An object clause atom has category exactly knowledge or "
                        "motivation. No case, fixture, gold, source-text, or position "
                        "identifier may participate."
                    ),
                    "mapping": ALIASES,
                    "diagnostic_code": "normalized_category_vocabulary_alias",
                    "only_changed_field": "clause_atoms[i].category",
                },
                {
                    "order": 5,
                    "mechanism": "zero-lower-bound-to-absent-minimum",
                    "activation": {
                        "category": "experience",
                        "qualifier_fields_exact": sorted(QUALIFIER_FIELDS),
                        "minimum_months_exact_integer": 0,
                        "boolean_zero_disallowed": True,
                        "surface_item_exact_source_substring": True,
                        "source_or_surface_pattern": ZERO_PATTERN.pattern,
                        "case_fixture_gold_ids_allowed": False,
                    },
                    "intervention": "minimum_months: 0 -> null",
                    "diagnostic_code": (
                        "normalized_zero_lower_bound_to_absent_minimum"
                    ),
                    "only_changed_field": (
                        "clause_atoms[i].qualifier.minimum_months"
                    ),
                },
            ],
            "formal_category_vocabulary": [
                "skill",
                "capability",
                "experience",
                "responsibility",
            ],
            "formal_schema_widening_allowed": False,
            "unknown_category_fallback_allowed": False,
            "input_mutation_allowed": False,
            "reverse_order": [5, 4, 3, 2, 1],
            "reverse_must_replay_exactly": True,
            "maximum_months_added": False,
        },
        "acceptance_gates": {
            "G0-frozen-inputs-source-isolation-and-zero-calls": {
                "requirements": [
                    "All preregistered and source-freeze hashes match.",
                    "Model, network, parser, and canonicalizer call counts are zero.",
                    "No v4-v4.3 source, frozen raw, report, oracle, or threshold changes.",
                    "No new holdout is loaded."
                ]
            },
            "G1-revealed-development-strict-recovery": {
                "baseline_strict_valid_case_count": 2,
                "required_v4_4_strict_valid_case_count": 5,
                "required_new_activation_count": 3,
                "required_category_alias_activation_count": 2,
                "required_zero_lower_bound_activation_count": 1,
                "required_carried_v4_3_activation_count": 11,
                "required_changed_field_count": 3,
                "required_changed_paths": [
                    {
                        "case_id": item["case_id"],
                        "path": item["path"],
                        "before": item["before"],
                        "after": item["after"],
                    }
                    for item in [
                        *development["category_alias_candidates"],
                        *development["zero_lower_bound_candidates"],
                    ]
                ],
            },
            "G2-exact-reversibility-and-held-fixed": {
                "required_exact_v4_4_reverse_case_count": 5,
                "required_exact_raw_restoration_case_count": 5,
                "required_unchanged_atom_count": 101,
                "facts_metadata_order_and_all_other_atom_fields_unchanged": True,
                "forward_and_reverse_input_mutation_allowed": False,
            },
            "G3-legacy-zero-regression": {
                "cohorts": {
                    "legacy_dev20": {
                        "case_count": 20,
                        "atom_count": 427,
                        "required_new_activation_count": 0,
                        "required_output_equal_v4_3": True,
                        "required_strict_valid_case_count": 20,
                    },
                    "legacy_live_probe": {
                        "case_count": 5,
                        "required_new_activation_count": 0,
                        "required_output_equal_v4_3": True,
                        "required_exact_reverse_case_count": 5,
                    },
                    "legacy_external_holdout": {
                        "case_count": 5,
                        "required_new_activation_count": 0,
                        "required_output_equal_v4_3": True,
                        "required_strict_valid_case_count": 5,
                        "required_exact_reverse_case_count": 5,
                    },
                }
            },
            "G4-fail-closed-controls": {
                "positive_controls": [
                    "knowledge-to-skill",
                    "motivation-to-capability",
                    "explicit-0-to-3-years-to-null",
                    "combined-category-and-zero-with-frozen-v4.3",
                ],
                "negative_controls": [
                    "already-skill-knowledge-source",
                    "already-capability-motivation-source",
                    "unknown-category",
                    "category-alias-case-mismatch",
                    "boolean-zero",
                    "zero-wrong-category",
                    "zero-wrong-qualifier-topology",
                    "zero-without-range-pattern",
                    "zero-unanchored-surface",
                    "positive-minimum-72",
                ],
                "tampered_diagnostics_must_raise_without_mutation": True,
                "empty_diagnostics_must_return_equal_deep_copy": True,
            },
            "G5-category-policy-and-schema-stability": {
                "required_mapping": ALIASES,
                "formal_category_enum_unchanged": True,
                "knowledge_to_skill_same_batch_analog_count": 3,
                "motivation_to_capability_human_control_count": 1,
                "unknown_category_still_invalid": True,
                "canonical_items_and_evidence_must_not_change": True,
            },
            "G6-static-audit-and-tests": {
                "runtime_allowed_imports": [
                    "standard library",
                    "frozen v4.3 compatibility symbols",
                ],
                "forbidden_runtime_dependencies": [
                    "network or model clients",
                    "parser or canonicalizer",
                    "artifact paths",
                    "case, fixture, or gold identifiers",
                ],
                "focused_and_related_tests_pass_before_source_freeze": True,
                "full_suite_pass_before_source_freeze": True,
                "frozen_source_hashes_match_during_formal_execution": True,
            },
        },
        "execution_protocol": {
            "all_gates_conjunctive": True,
            "source_and_tests_frozen_before_formal_execution": True,
            "formal_execution_count": 1,
            "rerun_after_failure_allowed": False,
            "threshold_or_control_change_after_freeze_allowed": False,
            "write_new_artifacts_only": True,
            "model_calls_allowed": False,
            "network_calls_allowed": False,
        },
        "post_gate_protocol": {
            "on_full_pass": [
                "Freeze v4.4 as a development-qualified candidate.",
                "Do not modify v4.3 or claim generalization.",
                "Preregister a new source-only independent holdout enriched for category and zero-bound surface cues.",
                "Request separate authorization before any full-body transmission.",
            ],
            "on_any_failure": [
                "Do not modify or rerun v4.4.",
                "Retain failed artifacts and diagnose only from frozen inputs.",
                "Do not load or call a new holdout.",
            ],
        },
        "next_allowed_action": (
            "Implement only the v4.4 adapter, evaluator, controls, focused tests, "
            "and one-time gate runner; pass tests; freeze source hashes; then execute "
            "the offline gates once."
        ),
    }


def main() -> int:
    outputs = (PREREGISTRATION, PREREGISTRATION_FREEZE)
    existing = [str(path) for path in outputs if path.exists()]
    if existing:
        raise FileExistsError(f"v4.4 preregistration already exists: {existing}")
    future = [str(path) for path in FUTURE_IMPLEMENTATION_PATHS if path.exists()]
    if future:
        raise ValueError(f"v4.4 implementation exists before preregistration: {future}")
    preregistration = _preregistration()
    _write_new(PREREGISTRATION, preregistration)
    freeze = {
        "freeze_version": (
            "unified-jd-flat-atomic-v4.4-compatibility-preregistration-freeze-v1"
        ),
        "date": DATE,
        "status": "frozen_before_v4_4_implementation_and_execution",
        "artifacts": {
            "preregistration": _reference(PREREGISTRATION),
            "preregistration_builder": _reference(Path(__file__).resolve()),
        },
        "frozen_inputs": preregistration["frozen_inputs"],
        "runtime_contract_frozen": True,
        "controls_and_thresholds_frozen": True,
        "formal_execution_count_at_freeze": 0,
        "new_model_call_count_at_freeze": 0,
        "network_call_count_at_freeze": 0,
        "v4_3_modification_allowed": False,
        "immutability": (
            "Any input, mapping, activation predicate, order, control, threshold, "
            "or decision change requires a new preregistration version."
        ),
    }
    _write_new(PREREGISTRATION_FREEZE, freeze)
    print(
        json.dumps(
            {
                "preregistration": _reference(PREREGISTRATION),
                "preregistration_freeze": _reference(PREREGISTRATION_FREEZE),
                "implementation_target_count_at_freeze": 0,
                "formal_execution_count_at_freeze": 0,
                "model_call_count": 0,
                "network_call_count": 0,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
