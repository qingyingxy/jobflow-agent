from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATE = "2026-09-06"
PREREGISTRATION = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_4_generalization_holdout_"
    "preregistration_v1_2026-09-06.json"
)
PREREGISTRATION_FREEZE = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_4_generalization_holdout_"
    "preregistration_freeze_v1_2026-09-06.json"
)

V44_SOURCE_FREEZE = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_4_compatibility_source_freeze_"
    "v1_2026-09-06.json"
)
V44_REPORT = ROOT / (
    "artifacts/evaluation/unified-jd-flat-atomic-v4-4-compatibility-"
    "report-v1-2026-09-06.json"
)
V44_RECEIPT = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_4_compatibility_evaluation_"
    "receipt_v1_2026-09-06.json"
)
V44_ADAPTER = ROOT / "src/services/unified_jd_flat_atomic_v4_4_compatibility.py"
V44_EVALUATOR = ROOT / "src/evaluation/model_first_v4_4_compatibility.py"
REQUEST_CONTRACT = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_live_probe_preregistration_"
    "v1_2026-09-06.json"
)

FUTURE_PATHS = (
    ROOT
    / (
        "datasets/unified_jd_flat_atomic_v4_4_generalization_holdout_"
        "selection_v1_2026-09-06.json"
    ),
    ROOT
    / (
        "datasets/unified_jd_flat_atomic_v4_4_generalization_holdout_"
        "independence_receipt_v1_2026-09-06.json"
    ),
    ROOT
    / (
        "datasets/unified_jd_flat_atomic_v4_4_generalization_holdout_"
        "source_freeze_v1_2026-09-06.json"
    ),
    ROOT / "scripts/collect_unified_jd_flat_atomic_v4_4_generalization_holdout.py",
    ROOT / "scripts/run_unified_jd_flat_atomic_v4_4_generalization_holdout.py",
    ROOT / "src/evaluation/model_first_v4_4_generalization_holdout.py",
    ROOT / "tests/test_unified_jd_flat_atomic_v4_4_generalization_holdout.py",
    ROOT
    / (
        "artifacts/evaluation/unified-jd-flat-atomic-v4-4-generalization-"
        "holdout-requests-v1-2026-09-06.json"
    ),
    ROOT
    / (
        "artifacts/evaluation/unified-jd-flat-atomic-v4-4-generalization-"
        "holdout-raw-v1-2026-09-06.json"
    ),
    ROOT
    / (
        "artifacts/evaluation/unified-jd-flat-atomic-v4-4-generalization-"
        "holdout-report-v1-2026-09-06.json"
    ),
)

STRATA = [
    {
        "stratum": "C1-knowledge-positive",
        "case_count": 1,
        "source_only_predicate": (
            "A responsibility or qualification statement contains a case-insensitive "
            "whole-phrase match for 'knowledge of', 'knowledge in', or 'working "
            "knowledge'."
        ),
        "purpose": "Test category-vocabulary behavior near the knowledge cue.",
    },
    {
        "stratum": "C2-motivation-positive",
        "case_count": 1,
        "source_only_predicate": (
            "A responsibility or qualification statement contains a case-insensitive "
            "whole-word match for motivation, motivated, passion, curiosity, curious, "
            "drive, or enthusiasm."
        ),
        "purpose": "Test category-vocabulary behavior near attitude cues.",
    },
    {
        "stratum": "Z1-zero-lower-bound-positive",
        "case_count": 1,
        "source_only_predicate": (
            "A qualification statement contains an explicit 0-N years/months range "
            "with integer N greater than zero, using hyphen, en dash, em dash, or 'to'."
        ),
        "purpose": "Test the zero-lower-bound compatibility mechanism.",
    },
    {
        "stratum": "C0-formal-category-negative-control",
        "case_count": 1,
        "source_only_predicate": (
            "A responsibility or qualification statement explicitly uses skill, "
            "skills, capability, or capabilities and contains none of the registered "
            "C1/C2 cue phrases in that statement."
        ),
        "purpose": "Detect category alias over-activation on already formal language.",
    },
    {
        "stratum": "Z0-positive-lower-bound-negative-control",
        "case_count": 1,
        "source_only_predicate": (
            "A qualification statement contains a positive experience lower bound "
            "such as 1-N years, 2+ years, or minimum 1 year and contains no explicit "
            "0-N years/months range."
        ),
        "purpose": "Detect zero-lower-bound over-activation.",
    },
]


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


def _frozen_inputs() -> dict[str, dict[str, str]]:
    return {
        "v4_4_source_freeze": _reference(V44_SOURCE_FREEZE),
        "v4_4_formal_report": _reference(V44_REPORT),
        "v4_4_evaluation_receipt": _reference(V44_RECEIPT),
        "v4_4_compatibility_adapter": _reference(V44_ADAPTER),
        "v4_4_compatibility_evaluator": _reference(V44_EVALUATOR),
        "frozen_v4_request_contract": _reference(REQUEST_CONTRACT),
    }


def _preregistration() -> dict[str, Any]:
    report = _load(V44_REPORT)
    receipt = _load(V44_RECEIPT)
    if not report.get("accepted") or not all(
        gate.get("passed") for gate in report.get("gates", {}).values()
    ):
        raise ValueError("frozen v4.4 gates did not all pass")
    if receipt.get("formal_execution_count") != 1 or not receipt.get("accepted"):
        raise ValueError("frozen v4.4 execution receipt is not accepted")
    return {
        "preregistration_version": (
            "unified-jd-flat-atomic-v4.4-generalization-holdout-"
            "preregistration-v1"
        ),
        "date": DATE,
        "status": "preregistered_before_source_discovery_selection_and_model_calls",
        "objective": (
            "Test frozen v4.4 on five new public job bodies selected only from "
            "source-observable category and experience surface cues."
        ),
        "claim_boundary": (
            "This purposive five-job holdout can test cross-job and cross-delivery-"
            "surface behavior of the two frozen compatibility mechanisms. It cannot "
            "estimate population accuracy or justify broader ontology aliases."
        ),
        "frozen_inputs": _frozen_inputs(),
        "selection_protocol": {
            "case_count": 5,
            "strata": STRATA,
            "assignment": (
                "Select the first eligible repository-novel posting found for each "
                "stratum in the frozen query order; freeze its stratum assignment even "
                "if the body also matches another stratum."
            ),
            "frozen_query_order": [
                "site:myworkdayjobs.com AI engineer knowledge of",
                "site:jobs.workable.com AI engineer knowledge of",
                "site:jobs.lever.co AI engineer motivation curiosity passion",
                "site:job-boards.greenhouse.io AI engineer 0-3 years",
                "site:jobs.smartrecruiters.com AI engineer skills capabilities",
                "site:careers.* AI engineer 2+ years",
            ],
            "search_result_rule": (
                "Within each query, inspect results in displayed rank order and record "
                "every rejection reason before accepting the first eligible result."
            ),
            "eligibility": [
                "Publicly accessible complete English-language job body.",
                "AI/ML engineer or directly equivalent hands-on technical role.",
                "At least 1500 Unicode characters after deterministic normalization.",
                "Contains separately identifiable responsibilities and qualifications.",
                "Posting is open or publicly displayed at collection time.",
                "Unique company, source URL, and job body within this holdout.",
                "Not an AI-campus source and not an employer/job used in prior JSON data.",
            ],
            "delivery_surface_requirements": {
                "minimum_distinct_surface_count": 3,
                "minimum_surfaces_absent_from_revealed_independent_5": 1,
            },
            "forbidden_selection_inputs": [
                "model output or diagnostics",
                "v4.3 or v4.4 activation behavior",
                "strict-schema result",
                "gold labels",
                "manual preference after an eligible first result is found",
            ],
            "repository_novelty_audit": {
                "roots": ["datasets/**/*.json", "artifacts/evaluation/**/*.json"],
                "required_zero_matches": [
                    "source and retrieval URL",
                    "normalized complete body",
                    "company plus title co-occurrence",
                    "three deterministic 200-character body anchors",
                ],
            },
            "source_collection_network_access_allowed": True,
            "external_model_transmission_during_selection_allowed": False,
        },
        "source_freeze_requirements": {
            "selection_and_independence_receipt_written_before_runner_implementation": True,
            "complete_bodies_and_body_hashes_frozen": True,
            "cue spans_and_stratum_predicates_frozen": True,
            "discovery_queries_ranks_and_rejections_frozen": True,
            "source_statement_counts_frozen_before_predictions": True,
            "no_semantic_gold_labels_created": True,
        },
        "future_request_contract": {
            "destination_host": "api.deepseek.com",
            "external_transmission_authorized": False,
            "separate_explicit_authorization_required": True,
            "transmitted_content": "five complete public job bodies",
            "maximum_new_model_calls": 5,
            "maximum_calls_per_case": 1,
            "transport_retries": 0,
            "validation_retries": 0,
            "concurrency": 1,
            "request_artifact_before_first_call": True,
            "checkpoint_after_each_call": True,
            "stop_on_transport_failure": True,
            "continue_after_schema_failure": True,
            "overwrite_allowed": False,
        },
        "evaluation_protocol": {
            "same_frozen_raw_for_v4_3_baseline_and_v4_4_treatment": True,
            "v4_4_additional_model_calls": 0,
            "formal_execution_count": 1,
            "rerun_after_failure_allowed": False,
            "threshold_change_after_source_freeze_allowed": False,
            "frozen_v4_4_modification_allowed": False,
        },
        "acceptance_gates": {
            "G0-authorization-independence-and-budget": {
                "required_case_count": 5,
                "all_repository_novelty_checks_must_pass": True,
                "selection_must_postdate_v4_4_freeze_and_formal_pass": True,
                "explicit_full-body_authorization_required_before_calls": True,
                "maximum_new_model_calls": 5,
                "maximum_calls_per_case": 1,
                "retry_count": 0,
            },
            "G1-source-strata-and-capture": {
                "required_stratum_case_counts": {
                    item["stratum"]: item["case_count"] for item in STRATA
                },
                "minimum_distinct_delivery_surfaces": 3,
                "required_request_and_raw_record_count": 5,
                "request_body_hash_must_equal_frozen_selection_body_hash": True,
            },
            "G2-v4-4-strict-schema": {
                "required_v4_4_strict_schema_valid_case_count": 5,
                "baseline_v4_3_validity_reported_without_thresholding": True,
            },
            "G3-five-stage-intervention-integrity": {
                "allowed_diagnostic_codes": [
                    "normalized_responsibility_role_alias",
                    "omitted_empty_absent_fact_placeholder",
                    "normalized_long_self_sufficient_evidence",
                    "normalized_category_vocabulary_alias",
                    "normalized_zero_lower_bound_to_absent_minimum",
                ],
                "required_pipeline_order": [1, 2, 3, 4, 5],
                "v4_4_reverse_must_exactly_restore_all_raw_outputs": True,
                "unactivated_fields_must_be_unchanged": True,
                "other_repairs_allowed": False,
            },
            "G4-runtime-specificity-controls": {
                "C0_new_category_activation_count": 0,
                "Z0_new_zero_lower_bound_activation_count": 0,
                "unknown_category_fallback_allowed": False,
                "positive_minimum_to_null_allowed": False,
            },
            "G5-source-surface-and-granularity": {
                "required_source_text_localization_rate": 1.0,
                "required_nonnull_surface_localization_rate": 1.0,
                "per_case_primary_atom_floor": (
                    "Half the source-observable responsibility and qualification "
                    "statement count, rounded up and frozen before requests."
                ),
                "maximum_aggregate_primary_atom_count": 400,
            },
            "G6-isolation-and-preservation": {
                "all_frozen_hashes_must_match": True,
                "raw_responses_retained_on_failure": True,
                "default_parser_called": False,
                "canonicalizer_called": False,
                "v4_4_source_modified": False,
                "model_calls_outside_frozen_five_requests": 0,
            },
        },
        "decision_rule": {
            "confirmed_both_mechanisms_generalize": (
                "G0-G6 pass; both new v4.4 diagnostic codes activate at least once; "
                "every newly activated case is v4.3-invalid only for an eligible "
                "incompatibility and becomes v4.4-valid."
            ),
            "partial_mechanism_generalization": (
                "G0-G6 pass; exactly one new mechanism activates and restores all of "
                "its eligible invalid cases; the other positive stratum remains valid "
                "without needing its compatibility mechanism."
            ),
            "supported_non_regression_only": (
                "G0-G6 pass; no new mechanism activates and all five raw outputs are "
                "already strict-valid under v4.3."
            ),
            "failed": (
                "Any G0-G6 gate fails, an eligible activation does not restore strict "
                "validity, a negative control activates, or reverse replay is inexact."
            ),
        },
        "stop_condition": (
            "After preregistration, collect and freeze five source bodies only. Stop "
            "before creating or sending requests until separate user authorization."
        ),
    }


def main() -> int:
    outputs = (PREREGISTRATION, PREREGISTRATION_FREEZE)
    existing = [str(path) for path in outputs if path.exists()]
    if existing:
        raise FileExistsError(f"holdout preregistration already exists: {existing}")
    future = [str(path) for path in FUTURE_PATHS if path.exists()]
    if future:
        raise ValueError(f"post-preregistration artifact already exists: {future}")
    preregistration = _preregistration()
    _write_new(PREREGISTRATION, preregistration)
    freeze = {
        "freeze_version": (
            "unified-jd-flat-atomic-v4.4-generalization-holdout-"
            "preregistration-freeze-v1"
        ),
        "date": DATE,
        "status": "frozen_before_source_discovery_selection_and_model_calls",
        "artifacts": {
            "preregistration": _reference(PREREGISTRATION),
            "preregistration_builder": _reference(Path(__file__).resolve()),
        },
        "frozen_inputs": preregistration["frozen_inputs"],
        "selection_exists_at_freeze": False,
        "model_call_count_at_freeze": 0,
        "network_model_call_count_at_freeze": 0,
        "full_body_transmission_authorized_at_freeze": False,
        "strata_thresholds_and_decision_rule_frozen": True,
        "immutability": (
            "Any selection rule, stratum, threshold, budget, or decision change "
            "requires a new preregistration version."
        ),
    }
    _write_new(PREREGISTRATION_FREEZE, freeze)
    print(
        json.dumps(
            {
                "preregistration": _reference(PREREGISTRATION),
                "preregistration_freeze": _reference(PREREGISTRATION_FREEZE),
                "selection_exists_at_freeze": False,
                "model_call_count": 0,
                "external_model_transmission_authorized": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
