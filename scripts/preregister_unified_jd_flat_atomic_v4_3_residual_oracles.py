from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from src.evaluation.model_first_v4_live_probe import analyze_live_response_v4
from src.services.unified_jd_flat_atomic_v4_3_compatibility import (
    normalize_flat_atomic_v4_3_wire_output,
)

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / (
    "artifacts/evaluation/unified-jd-flat-atomic-v4-3-independent-holdout-"
    "raw-v1-2026-09-06.json"
)
REPORT = ROOT / (
    "artifacts/evaluation/unified-jd-flat-atomic-v4-3-independent-holdout-"
    "report-v1-2026-09-06.json"
)
SELECTION = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_3_independent_holdout_selection_"
    "v1_2026-09-06.json"
)
HOLDOUT_SOURCE_FREEZE = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_3_independent_holdout_source_freeze_"
    "v1_2026-09-06.json"
)
HOLDOUT_RECEIPT = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_3_independent_holdout_evaluation_"
    "receipt_v1_2026-09-06.json"
)
V43_ADAPTER = ROOT / "src/services/unified_jd_flat_atomic_v4_3_compatibility.py"
V4_SCHEMA = ROOT / "src/domain/unified_jd_flat_atomic_v4.py"
V4_EVALUATOR = ROOT / "src/evaluation/model_first_v4_live_probe.py"
BUILDER = Path(__file__).resolve()

CATEGORY_PREREGISTRATION = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_3_category_vocabulary_admission_oracle_"
    "preregistration_v1_2026-09-06.json"
)
CATEGORY_FREEZE = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_3_category_vocabulary_admission_oracle_"
    "preregistration_freeze_v1_2026-09-06.json"
)
ZERO_PREREGISTRATION = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_3_zero_lower_bound_qualifier_oracle_"
    "preregistration_v1_2026-09-06.json"
)
ZERO_FREEZE = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_3_zero_lower_bound_qualifier_oracle_"
    "preregistration_freeze_v1_2026-09-06.json"
)

ALLOWED_CATEGORIES = {"skill", "capability", "experience", "responsibility"}
EXPECTED_CATEGORY_TARGETS = [
    {
        "case_id": "independent-lever-collate-ai-engineer",
        "atom_index": 10,
        "path": "clause_atoms[10].category",
        "value": "motivation",
    },
    {
        "case_id": "independent-smartrecruiters-bluescope-ai-engineer",
        "atom_index": 22,
        "path": "clause_atoms[22].category",
        "value": "knowledge",
    },
]
EXPECTED_ZERO_TARGETS = [
    {
        "case_id": "independent-greenhouse-simplifynext-ai-engineer-graduate",
        "atom_index": 27,
        "path": "clause_atoms[27].qualifier.minimum_months",
        "value": 0,
        "source_text": (
            "• 0–3 years of AI development experience "
            "(Fresh graduates are welcome to apply)"
        ),
    }
]


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected object: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _reference(path: Path) -> dict[str, str]:
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": _sha256(path)}


def _write_new(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as output:
        json.dump(value, output, ensure_ascii=False, indent=2)
        output.write("\n")


def _frozen_observations(
    raw: dict[str, Any], selection: dict[str, Any]
) -> dict[str, Any]:
    source_by_case = {
        case["case_id"]: case["raw_content"] for case in selection["cases"]
    }
    category_targets: list[dict[str, Any]] = []
    zero_targets: list[dict[str, Any]] = []
    positive_minimum_controls: list[dict[str, Any]] = []
    v43_diagnostic_counts: Counter[str] = Counter()
    v43_activations_by_case: dict[str, int] = {}
    category_counts: Counter[str] = Counter()
    atom_count = 0
    schema_valid_by_case: dict[str, bool] = {}
    schema_diagnostics_by_case: dict[str, list[dict[str, Any]]] = {}
    for record in raw["records"]:
        case_id = record["case_id"]
        result = normalize_flat_atomic_v4_3_wire_output(
            record.get("raw_model_output")
        )
        diagnostics = [item.as_dict() for item in result.diagnostics]
        v43_diagnostic_counts.update(item["code"] for item in diagnostics)
        v43_activations_by_case[case_id] = len(diagnostics)
        analysis = analyze_live_response_v4(
            result.output, source_by_case[case_id]
        )
        schema_valid_by_case[case_id] = analysis["schema_valid"]
        schema_diagnostics_by_case[case_id] = analysis["diagnostics"]
        if not isinstance(result.output, dict) or not isinstance(
            result.output.get("clause_atoms"), list
        ):
            raise TypeError(f"v4.3 output lacks clause atoms: {case_id}")
        for atom_index, atom in enumerate(result.output["clause_atoms"]):
            if not isinstance(atom, dict):
                raise TypeError(f"atom must be an object: {case_id}[{atom_index}]")
            atom_count += 1
            category = atom.get("category")
            category_counts.update([str(category)])
            if category not in ALLOWED_CATEGORIES:
                category_targets.append(
                    {
                        "case_id": case_id,
                        "atom_index": atom_index,
                        "path": f"clause_atoms[{atom_index}].category",
                        "value": category,
                    }
                )
            qualifier = atom.get("qualifier")
            if not isinstance(qualifier, dict):
                continue
            minimum = qualifier.get("minimum_months")
            if minimum == 0 and not isinstance(minimum, bool):
                zero_targets.append(
                    {
                        "case_id": case_id,
                        "atom_index": atom_index,
                        "path": (
                            f"clause_atoms[{atom_index}].qualifier.minimum_months"
                        ),
                        "value": minimum,
                        "source_text": atom.get("source_text"),
                    }
                )
            elif isinstance(minimum, int) and not isinstance(minimum, bool):
                positive_minimum_controls.append(
                    {
                        "case_id": case_id,
                        "atom_index": atom_index,
                        "minimum_months": minimum,
                        "source_text": atom.get("source_text"),
                    }
                )
    if category_targets != EXPECTED_CATEGORY_TARGETS:
        raise ValueError(f"unexpected category targets: {category_targets}")
    if zero_targets != EXPECTED_ZERO_TARGETS:
        raise ValueError(f"unexpected zero-bound targets: {zero_targets}")
    expected_validity = {
        "independent-lever-collate-ai-engineer": False,
        "independent-lever-field-ai-robotics-ai-engineer": True,
        "independent-greenhouse-simplifynext-ai-engineer-graduate": False,
        "independent-greenhouse-optiver-ai-engineer": True,
        "independent-smartrecruiters-bluescope-ai-engineer": False,
    }
    if schema_valid_by_case != expected_validity:
        raise ValueError(f"unexpected v4.3 validity: {schema_valid_by_case}")
    if atom_count != 104 or sum(category_counts.values()) != 104:
        raise ValueError("unexpected frozen atom count")
    if category_counts != Counter(
        {
            "skill": 48,
            "responsibility": 27,
            "experience": 24,
            "capability": 3,
            "motivation": 1,
            "knowledge": 1,
        }
    ):
        raise ValueError(f"unexpected category distribution: {category_counts}")
    if positive_minimum_controls != [
        {
            "case_id": "independent-greenhouse-optiver-ai-engineer",
            "atom_index": 7,
            "minimum_months": 72,
            "source_text": (
                "Minimum of 6 years professional experience in developing "
                "python applications"
            ),
        }
    ]:
        raise ValueError(
            f"unexpected positive minimum controls: {positive_minimum_controls}"
        )
    return {
        "source_model_call_count": raw["model_call_count"],
        "new_model_call_count": 0,
        "case_count": len(raw["records"]),
        "v4_3_strict_schema_valid_case_count": sum(schema_valid_by_case.values()),
        "v4_3_schema_valid_by_case": schema_valid_by_case,
        "v4_3_schema_diagnostics_by_case": schema_diagnostics_by_case,
        "v4_3_activation_count": sum(v43_diagnostic_counts.values()),
        "v4_3_activation_counts": dict(v43_diagnostic_counts),
        "v4_3_activations_by_case": v43_activations_by_case,
        "atom_count": atom_count,
        "category_counts": dict(category_counts),
        "in_vocabulary_category_control_count": atom_count - len(category_targets),
        "category_targets": category_targets,
        "zero_lower_bound_targets": zero_targets,
        "positive_minimum_controls": positive_minimum_controls,
    }


def _common_frozen_inputs() -> dict[str, dict[str, str]]:
    return {
        "selection": _reference(SELECTION),
        "frozen_raw": _reference(RAW),
        "formal_report": _reference(REPORT),
        "formal_evaluation_receipt": _reference(HOLDOUT_RECEIPT),
        "independent_holdout_source_freeze": _reference(HOLDOUT_SOURCE_FREEZE),
        "frozen_v4_3_adapter": _reference(V43_ADAPTER),
        "frozen_v4_schema": _reference(V4_SCHEMA),
        "frozen_v4_evaluator": _reference(V4_EVALUATOR),
    }


def _category_preregistration(
    observations: dict[str, Any], frozen_inputs: dict[str, dict[str, str]]
) -> dict[str, Any]:
    return {
        "preregistration_version": (
            "unified-jd-flat-atomic-v4.3-category-vocabulary-admission-"
            "oracle-preregistration-v1"
        ),
        "date": "2026-09-06",
        "status": "preregistered_before_oracle_implementation_and_execution",
        "objective": (
            "Measure whether the two residual category literal errors are caused "
            "solely by closure of the frozen category vocabulary."
        ),
        "claim_boundary": (
            "This is a schema-admission oracle on five revealed frozen responses. "
            "It may establish that vocabulary closure causes the two target errors; "
            "it cannot choose a production canonical mapping, justify adding new "
            "domain categories, or establish generalization."
        ),
        "frozen_inputs": frozen_inputs,
        "frozen_observations": observations,
        "independence": {
            "starting_point": (
                "Deep-copy each original frozen raw output and apply frozen v4.3 "
                "forward normalization exactly once."
            ),
            "other_new_oracle_treatments_applied": [],
            "zero_lower_bound_qualifier_oracle_applied": False,
            "model_calls_allowed": False,
            "network_calls_allowed": False,
        },
        "oracle_contract": {
            "oracle_id": "category-vocabulary-admission-oracle-v1",
            "runtime_activation_predicate": {
                "path_shape": "clause_atoms[i].category on an object atom",
                "current_category_not_in_frozen_vocabulary": True,
                "exact_admitted_tokens": ["knowledge", "motivation"],
                "case_id_fixture_id_or_gold_allowed": False,
            },
            "intervention": (
                "Validate the v4.3 output against an oracle schema identical to "
                "the frozen v4 schema except that the category literal union also "
                "admits knowledge and motivation. Do not mutate or canonicalize "
                "the raw or v4.3-normalized output."
            ),
            "schema_delta": {
                "allowed": (
                    "Only add knowledge and motivation to the category enum used "
                    "by the temporary oracle validator."
                ),
                "root_fields_changed": False,
                "atom_fields_changed": False,
                "other_enum_or_constraint_changes_allowed": False,
            },
            "diagnostic_code": "oracle_admitted_category_vocabulary_token",
            "diagnostic_fields": [
                "record_index",
                "atom_index",
                "path",
                "category",
            ],
            "input_or_output_mutation_allowed": False,
        },
        "controls": {
            "in_vocabulary_atom_count": 102,
            "in_vocabulary_categories": {
                "skill": 48,
                "responsibility": 27,
                "experience": 24,
                "capability": 3,
            },
            "target_count": 2,
            "expected_target_values": ["motivation", "knowledge"],
            "zero_lower_bound_residual_must_remain": True,
            "frozen_v4_3_omission_activation_count_must_remain": 11,
            "positive_minimum_72_must_remain_unchanged": True,
        },
        "acceptance_gates": {
            "C0-frozen-inputs-isolation-and-zero-calls": {
                "requirements": [
                    "Every frozen input and source hash matches.",
                    "Model and network call counts are zero.",
                    "No v4-v4.3 source, raw response, report, or threshold changes.",
                    "Default parser and canonicalizer calls are zero.",
                ]
            },
            "C1-activation-exactness": {
                "required_activation_count": 2,
                "required_tokens": ["motivation", "knowledge"],
                "required_case_count": 2,
                "all_other_atoms_must_not_activate": True,
                "runtime_may_not_reference_case_or_fixture_ids": True,
            },
            "C2-schema-delta-and-preservation": {
                "temporary_category_enum_additions": ["knowledge", "motivation"],
                "all_other_schema_bytes_or_semantics_must_match": True,
                "raw_and_v4_3_outputs_must_remain_byte_equivalent": True,
                "category_mapping_allowed": False,
            },
            "C3-independent-target-recovery": {
                "baseline_v4_3_strict_valid_case_count": 2,
                "required_oracle_valid_case_count": 4,
                "required_recovered_case_ids": [
                    "independent-lever-collate-ai-engineer",
                    "independent-smartrecruiters-bluescope-ai-engineer",
                ],
                "remaining_invalid_case_ids": [
                    "independent-greenhouse-simplifynext-ai-engineer-graduate"
                ],
                "remaining_error_must_be_only": (
                    "clause_atoms[27].qualifier.minimum_months=0"
                ),
            },
            "C4-controls-and-non-regression": {
                "required_unchanged_in_vocabulary_atom_count": 102,
                "FieldAI_and_Optiver_validity_must_remain_true": True,
                "source_and_surface_values_must_remain_unchanged": True,
                "v4_3_diagnostics_and_reverse_replay_must_remain_unchanged": True,
                "zero_lower_bound_or_qualifier_changes_allowed": False,
            },
            "C5-causal-decision": {
                "supported": (
                    "C0-C4 pass and both category-only target records recover under "
                    "the enum-only oracle without output mutation or control change."
                ),
                "rejected": (
                    "Any target remains invalid, any non-target activates or changes, "
                    "or any schema property beyond the category enum differs."
                ),
            },
        },
        "execution_protocol": {
            "dedicated_runner_required": True,
            "runner_shared_with_zero_lower_bound_oracle": False,
            "source_and_tests_frozen_before_execution": True,
            "formal_execution_count": 1,
            "rerun_after_failure_allowed": False,
            "threshold_change_after_freeze_allowed": False,
            "write_new_artifacts_only": True,
        },
        "next_allowed_action": (
            "Implement only the category admission oracle evaluator, runner, and "
            "focused tests; freeze their sources; then execute once offline."
        ),
    }


def _zero_preregistration(
    observations: dict[str, Any], frozen_inputs: dict[str, dict[str, str]]
) -> dict[str, Any]:
    return {
        "preregistration_version": (
            "unified-jd-flat-atomic-v4.3-zero-lower-bound-qualifier-"
            "oracle-preregistration-v1"
        ),
        "date": "2026-09-06",
        "status": "preregistered_before_oracle_implementation_and_execution",
        "objective": (
            "Measure whether treating an explicit zero lower bound as absence of a "
            "positive minimum independently removes the remaining SimplifyNext "
            "qualifier schema error."
        ),
        "claim_boundary": (
            "This is a reversible compatibility oracle on five revealed frozen "
            "responses. It may establish the causal effect of zero-to-null minimum "
            "normalization; it cannot establish generalization or authorize a v4.3 "
            "change."
        ),
        "frozen_inputs": frozen_inputs,
        "frozen_observations": observations,
        "independence": {
            "starting_point": (
                "Deep-copy each original frozen raw output and apply frozen v4.3 "
                "forward normalization exactly once."
            ),
            "other_new_oracle_treatments_applied": [],
            "category_vocabulary_admission_oracle_applied": False,
            "model_calls_allowed": False,
            "network_calls_allowed": False,
        },
        "oracle_contract": {
            "oracle_id": "zero-lower-bound-qualifier-oracle-v1",
            "runtime_activation_predicate": {
                "path_shape": "clause_atoms[i].qualifier.minimum_months",
                "atom_category": "experience",
                "minimum_months_exact_integer": 0,
                "boolean_zero_disallowed": True,
                "qualifier_topology_exact": [
                    "experience_type",
                    "minimum_months",
                    "domain",
                ],
                "surface_item_must_be_exact_source_substring": True,
                "source_or_surface_pattern": (
                    "(?<!\\d)0\\s*(?:-|–|—|to)\\s*\\d+\\s*"
                    "(?:years?|yrs?|months?)\\b"
                ),
                "case_id_fixture_id_or_gold_allowed": False,
            },
            "intervention": {
                "operation": "Set only qualifier.minimum_months from 0 to null.",
                "before": 0,
                "after": None,
                "preserve_qualifier_object": True,
                "preserve_experience_type_and_domain": True,
            },
            "diagnostic_code": "normalized_zero_lower_bound_to_absent_minimum",
            "diagnostic_fields": [
                "record_index",
                "atom_index",
                "path",
                "before",
                "after",
                "source_text",
            ],
            "reverse_replay": (
                "Require the diagnostic path to resolve, the current value to be "
                "null, and all frozen activation evidence to match; then restore 0."
            ),
            "input_mutation_allowed": False,
        },
        "controls": {
            "target_count": 1,
            "positive_minimum_control": {
                "minimum_months": 72,
                "required_unchanged": True,
            },
            "other_atom_count": 103,
            "unsupported_category_values_must_remain": [
                "motivation",
                "knowledge",
            ],
            "frozen_v4_3_omission_activation_count_must_remain": 11,
        },
        "acceptance_gates": {
            "Z0-frozen-inputs-isolation-and-zero-calls": {
                "requirements": [
                    "Every frozen input and source hash matches.",
                    "Model and network call counts are zero.",
                    "No v4-v4.3 source, raw response, report, or threshold changes.",
                    "Default parser and canonicalizer calls are zero.",
                ]
            },
            "Z1-activation-exactness": {
                "required_activation_count": 1,
                "required_before": 0,
                "required_after": None,
                "required_source_pattern_match": True,
                "all_other_qualifiers_and_atoms_must_not_activate": True,
                "runtime_may_not_reference_case_or_fixture_ids": True,
            },
            "Z2-intervention-and-reversibility": {
                "allowed_changed_path": (
                    "clause_atoms[i].qualifier.minimum_months"
                ),
                "allowed_change": "integer 0 to null",
                "exact_changed_field_count": 1,
                "reverse_must_restore_v4_3_input_exactly": True,
                "reverse_then_v4_3_reverse_must_restore_frozen_raw": True,
                "input_mutation_allowed": False,
            },
            "Z3-independent-target-recovery": {
                "baseline_v4_3_strict_valid_case_count": 2,
                "required_oracle_valid_case_count": 3,
                "required_recovered_case_ids": [
                    "independent-greenhouse-simplifynext-ai-engineer-graduate"
                ],
                "remaining_invalid_case_ids": [
                    "independent-lever-collate-ai-engineer",
                    "independent-smartrecruiters-bluescope-ai-engineer",
                ],
                "remaining_errors_must_be_only": [
                    "category=motivation",
                    "category=knowledge",
                ],
            },
            "Z4-controls-and-non-regression": {
                "positive_minimum_72_must_remain_unchanged": True,
                "required_unchanged_non_target_atom_count": 103,
                "category_values_must_remain_unchanged": True,
                "source_surface_semantic_and_qualifier_context_unchanged": True,
                "v4_3_diagnostics_and_reverse_replay_must_remain_unchanged": True,
                "category_admission_or_mapping_allowed": False,
            },
            "Z5-causal-decision": {
                "supported": (
                    "Z0-Z4 pass and the sole eligible zero-bound target recovers "
                    "under the one-field reversible treatment with zero control change."
                ),
                "rejected": (
                    "The target remains invalid, another value activates or changes, "
                    "reverse replay is inexact, or a category residual changes."
                ),
            },
        },
        "execution_protocol": {
            "dedicated_runner_required": True,
            "runner_shared_with_category_admission_oracle": False,
            "source_and_tests_frozen_before_execution": True,
            "formal_execution_count": 1,
            "rerun_after_failure_allowed": False,
            "threshold_change_after_freeze_allowed": False,
            "write_new_artifacts_only": True,
        },
        "next_allowed_action": (
            "Implement only the zero-lower-bound qualifier oracle adapter, evaluator, "
            "runner, and focused tests; freeze their sources; then execute once offline."
        ),
    }


def _freeze(
    *, preregistration: Path, freeze_path: Path, freeze_version: str
) -> None:
    preregistration_value = _load(preregistration)
    freeze = {
        "freeze_version": freeze_version,
        "date": "2026-09-06",
        "status": "frozen_before_oracle_implementation_and_execution",
        "artifacts": {
            "preregistration": _reference(preregistration),
            "preregistration_builder": _reference(BUILDER),
        },
        "frozen_inputs": preregistration_value["frozen_inputs"],
        "oracle_contract_frozen": True,
        "activation_predicate_frozen": True,
        "controls_and_thresholds_frozen": True,
        "formal_execution_count_at_freeze": 0,
        "new_model_call_count_at_freeze": 0,
        "network_call_count_at_freeze": 0,
        "v4_3_modification_allowed": False,
        "cross_oracle_treatment_accumulation_allowed": False,
        "immutability": (
            "Any input, activation predicate, intervention, control, threshold, "
            "decision rule, or v4.3 change requires a new oracle version."
        ),
    }
    _write_new(freeze_path, freeze)


def main() -> int:
    outputs = (
        CATEGORY_PREREGISTRATION,
        CATEGORY_FREEZE,
        ZERO_PREREGISTRATION,
        ZERO_FREEZE,
    )
    existing = [str(path) for path in outputs if path.exists()]
    if existing:
        raise FileExistsError(f"oracle preregistration already exists: {existing}")
    required = (
        RAW,
        REPORT,
        SELECTION,
        HOLDOUT_SOURCE_FREEZE,
        HOLDOUT_RECEIPT,
        V43_ADAPTER,
        V4_SCHEMA,
        V4_EVALUATOR,
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"missing frozen oracle input: {missing}")
    report = _load(REPORT)
    receipt = _load(HOLDOUT_RECEIPT)
    raw = _load(RAW)
    selection = _load(SELECTION)
    if report.get("decision") != "failed" or receipt.get("decision") != "failed":
        raise ValueError("the frozen holdout failure must be retained")
    if raw.get("model_call_count") != 5 or len(raw.get("records", [])) != 5:
        raise ValueError("expected exactly five frozen source responses")
    if any(record.get("failure_code") is not None for record in raw["records"]):
        raise ValueError("offline oracles require five successful source responses")
    observations = _frozen_observations(raw, selection)
    frozen_inputs = _common_frozen_inputs()

    _write_new(
        CATEGORY_PREREGISTRATION,
        _category_preregistration(observations, frozen_inputs),
    )
    _freeze(
        preregistration=CATEGORY_PREREGISTRATION,
        freeze_path=CATEGORY_FREEZE,
        freeze_version=(
            "unified-jd-flat-atomic-v4.3-category-vocabulary-admission-"
            "oracle-preregistration-freeze-v1"
        ),
    )
    _write_new(
        ZERO_PREREGISTRATION,
        _zero_preregistration(observations, frozen_inputs),
    )
    _freeze(
        preregistration=ZERO_PREREGISTRATION,
        freeze_path=ZERO_FREEZE,
        freeze_version=(
            "unified-jd-flat-atomic-v4.3-zero-lower-bound-qualifier-"
            "oracle-preregistration-freeze-v1"
        ),
    )
    print(
        json.dumps(
            {
                "category_preregistration": _reference(CATEGORY_PREREGISTRATION),
                "category_freeze": _reference(CATEGORY_FREEZE),
                "zero_preregistration": _reference(ZERO_PREREGISTRATION),
                "zero_freeze": _reference(ZERO_FREEZE),
                "new_model_call_count": 0,
                "network_call_count": 0,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
