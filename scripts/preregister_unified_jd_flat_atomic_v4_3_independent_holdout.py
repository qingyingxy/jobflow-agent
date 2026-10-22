from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SELECTION = ROOT / (
    "datasets/"
    "unified_jd_flat_atomic_v4_3_independent_holdout_selection_v1_2026-09-06.json"
)
INDEPENDENCE = ROOT / (
    "datasets/"
    "unified_jd_flat_atomic_v4_3_independent_holdout_independence_receipt_"
    "v1_2026-09-06.json"
)
PREREGISTRATION = ROOT / (
    "datasets/"
    "unified_jd_flat_atomic_v4_3_independent_holdout_preregistration_"
    "v1_2026-09-06.json"
)
FREEZE = ROOT / (
    "datasets/"
    "unified_jd_flat_atomic_v4_3_independent_holdout_preregistration_freeze_"
    "v1_2026-09-06.json"
)
COLLECTOR = ROOT / (
    "scripts/collect_unified_jd_flat_atomic_v4_3_independent_holdout.py"
)
BUILDER = Path(__file__).resolve()
V43_SOURCE_FREEZE = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_3_compatibility_source_freeze_"
    "v1_2026-09-06.json"
)
V43_REPORT = ROOT / (
    "artifacts/evaluation/unified-jd-flat-atomic-v4-3-compatibility-report-"
    "v1-2026-09-06.json"
)
V43_RECEIPT = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_3_compatibility_evaluation_receipt_"
    "v1_2026-09-06.json"
)
V42_SOURCE_FREEZE = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_2_compatibility_source_freeze_"
    "v1_2026-09-06.json"
)
V4_REQUEST_CONTRACT = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_live_probe_preregistration_"
    "v1_2026-09-06.json"
)
V43_ADAPTER = ROOT / "src/services/unified_jd_flat_atomic_v4_3_compatibility.py"
V43_EVALUATOR = ROOT / "src/evaluation/model_first_v4_3_compatibility.py"

CORE_STATEMENT_COUNTS = {
    "independent-lever-collate-ai-engineer": 11,
    "independent-lever-field-ai-robotics-ai-engineer": 19,
    "independent-greenhouse-simplifynext-ai-engineer-graduate": 25,
    "independent-greenhouse-optiver-ai-engineer": 14,
    "independent-smartrecruiters-bluescope-ai-engineer": 23,
}


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected object: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _reference(path: Path) -> dict[str, str]:
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": _sha256(path)}


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).replace("\u00a0", " ")
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    lines = [" ".join(line.split()) for line in value.split("\n")]
    return "\n".join(lines).strip().casefold()


def _iter_strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _iter_strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _iter_strings(item)


def _anchor_fragments(raw_content: str) -> list[str]:
    blocks = [
        " ".join(block.split())
        for block in re.split(r"\n\s*\n", raw_content)
        if len(" ".join(block.split())) >= 180
    ]
    if len(blocks) < 3:
        raise ValueError("each holdout body must expose three long source anchors")
    indexes = (0, len(blocks) // 2, len(blocks) - 1)
    anchors = [blocks[index][:200] for index in indexes]
    if len(set(anchors)) != 3:
        raise ValueError("source anchors must be distinct")
    return anchors


def _audit_independence(selection: dict[str, Any]) -> dict[str, Any]:
    excluded = {SELECTION.resolve(), INDEPENDENCE.resolve(), PREREGISTRATION.resolve(), FREEZE.resolve()}
    paths = sorted(
        path
        for base in (ROOT / "datasets", ROOT / "artifacts/evaluation")
        for path in base.rglob("*.json")
        if path.resolve() not in excluded
    )
    corpus: list[tuple[str, str, str]] = []
    string_count = 0
    for path in paths:
        value = json.loads(path.read_text(encoding="utf-8"))
        relative = path.relative_to(ROOT).as_posix()
        for item in _iter_strings(value):
            string_count += 1
            corpus.append((relative, item.casefold(), _normalize(item)))

    case_results: list[dict[str, Any]] = []
    for case in selection["cases"]:
        raw_content = case["raw_content"]
        normalized_body = _normalize(raw_content)
        source_url = case["source_url"].casefold()
        retrieval_url = case["retrieval_url"].casefold()
        company = case["company"].casefold()
        title = case["title"].casefold()
        case_id = case["case_id"].casefold()
        anchors = _anchor_fragments(raw_content)
        normalized_anchors = [_normalize(anchor) for anchor in anchors]
        url_paths: set[str] = set()
        retrieval_paths: set[str] = set()
        body_paths: set[str] = set()
        case_id_paths: set[str] = set()
        company_title_paths: set[str] = set()
        anchor_paths: list[set[str]] = [set() for _ in anchors]
        for path, folded, normalized in corpus:
            if source_url in folded:
                url_paths.add(path)
            if retrieval_url in folded:
                retrieval_paths.add(path)
            if len(normalized) >= len(normalized_body) and normalized_body in normalized:
                body_paths.add(path)
            if case_id in folded:
                case_id_paths.add(path)
            if company in folded and title in folded:
                company_title_paths.add(path)
            for index, anchor in enumerate(normalized_anchors):
                if anchor in normalized:
                    anchor_paths[index].add(path)
        case_results.append(
            {
                "case_id": case["case_id"],
                "source_url_match_paths": sorted(url_paths),
                "retrieval_url_match_paths": sorted(retrieval_paths),
                "normalized_full_body_match_paths": sorted(body_paths),
                "case_id_match_paths": sorted(case_id_paths),
                "company_title_cooccurrence_paths": sorted(company_title_paths),
                "anchor_fragments": [
                    {"text": anchor, "match_paths": sorted(anchor_paths[index])}
                    for index, anchor in enumerate(anchors)
                ],
            }
        )

    zero_matches = all(
        not result["source_url_match_paths"]
        and not result["retrieval_url_match_paths"]
        and not result["normalized_full_body_match_paths"]
        and not result["case_id_match_paths"]
        and not result["company_title_cooccurrence_paths"]
        and all(not anchor["match_paths"] for anchor in result["anchor_fragments"])
        for result in case_results
    )
    if not zero_matches:
        raise ValueError("selected holdout is not repository-independent")
    return {
        "roots": ["datasets/**/*.json", "artifacts/evaluation/**/*.json"],
        "new_holdout_artifacts_excluded_from_search": True,
        "json_files_scanned": len(paths),
        "string_values_scanned": string_count,
        "matching_policy": (
            "For each case, case-fold and NFKC-normalize prior JSON string values; "
            "require zero exact-substring matches for the public page URL, public "
            "retrieval URL, normalized full body, new case ID, company+title "
            "cooccurrence, and three deterministic 200-character long-paragraph "
            "anchors selected at the first, middle, and last eligible positions."
        ),
        "case_results": case_results,
        "all_repository_novelty_checks_passed": zero_matches,
    }


def _write_exclusive(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as output:
        json.dump(value, output, ensure_ascii=False, indent=2)
        output.write("\n")


def main() -> int:
    outputs = (INDEPENDENCE, PREREGISTRATION, FREEZE)
    existing = [str(path) for path in outputs if path.exists()]
    if existing:
        raise FileExistsError(f"preregistration outputs already exist: {existing}")
    required = (
        SELECTION,
        COLLECTOR,
        V43_SOURCE_FREEZE,
        V43_REPORT,
        V43_RECEIPT,
        V42_SOURCE_FREEZE,
        V4_REQUEST_CONTRACT,
        V43_ADAPTER,
        V43_EVALUATOR,
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"missing frozen input: {missing}")

    selection = _load(SELECTION)
    if selection.get("selected_case_count") != 5:
        raise ValueError("independent holdout must contain exactly five cases")
    if selection.get("collection_protocol", {}).get("external_model_transmission_performed") is not False:
        raise ValueError("selection must precede all external model transmission")
    v43_freeze = _load(V43_SOURCE_FREEZE)
    v43_receipt = _load(V43_RECEIPT)
    if v43_receipt.get("decision") != "development_and_regression_gates_passed":
        raise ValueError("v4.3 formal development gates did not pass")
    collected_at = datetime.fromisoformat(selection["collected_at"])
    v43_frozen_at = datetime.fromisoformat(v43_freeze["frozen_at"])
    v43_recorded_at = datetime.fromisoformat(v43_receipt["recorded_at"])
    if not collected_at > max(v43_frozen_at, v43_recorded_at):
        raise ValueError("selection does not postdate the v4.3 freeze and receipt")

    audit = _audit_independence(selection)
    independence = {
        "receipt_version": (
            "unified-jd-flat-atomic-v4.3-independent-holdout-"
            "independence-receipt-v1"
        ),
        "date": "2026-09-06",
        "status": "frozen_before_preregistration_runner_and_model_calls",
        "selection": _reference(SELECTION),
        "audit": audit,
        "temporal_independence": {
            "v4_3_source_freeze_precedes_collection": True,
            "v4_3_formal_gate_report_and_receipt_precede_collection": True,
            "used_for_v4_v4_1_v4_2_or_v4_3_development": False,
            "labels_available_during_selection": False,
            "predictions_available_during_selection": False,
        },
        "surface_independence": {
            "company_count": 5,
            "country_or_region_count": 4,
            "ats_or_delivery_surface_count": 4,
            "all_prior_external_holdout_ats_reused": False,
            "prior_external_holdout_was_ashby_only": True,
            "new_holdout_contains_ashby": False,
        },
        "claim_boundary": (
            "This establishes repository-level novelty, temporal separation from "
            "v4.3 development, and broader ATS/delivery-surface coverage than the "
            "revealed Ashby holdout. Selection is purposive rather than random and "
            "remains limited to public English-language AI-engineering job bodies."
        ),
    }
    _write_exclusive(INDEPENDENCE, independence)

    minimums = {
        case_id: math.ceil(count / 2)
        for case_id, count in CORE_STATEMENT_COUNTS.items()
    }
    frozen_inputs = {
        "selection": _reference(SELECTION),
        "independence_receipt": _reference(INDEPENDENCE),
        "collector": _reference(COLLECTOR),
        "v4_3_source_freeze": _reference(V43_SOURCE_FREEZE),
        "v4_3_formal_report": _reference(V43_REPORT),
        "v4_3_evaluation_receipt": _reference(V43_RECEIPT),
        "v4_2_source_freeze": _reference(V42_SOURCE_FREEZE),
        "frozen_v4_request_contract": _reference(V4_REQUEST_CONTRACT),
        "v4_3_compatibility_adapter": _reference(V43_ADAPTER),
        "v4_3_compatibility_evaluator": _reference(V43_EVALUATOR),
    }
    preregistration = {
        "preregistration_version": (
            "unified-jd-flat-atomic-v4.3-independent-holdout-"
            "preregistration-v1"
        ),
        "date": "2026-09-06",
        "status": "preregistered_before_runner_implementation_and_model_calls",
        "objective": (
            "Run one genuinely independent five-job holdout to test whether the "
            "already frozen v4.3 compatibility layer generalizes beyond all "
            "development, revealed, live-probe, and prior external-response data."
        ),
        "primary_causal_question": (
            "On new cross-surface public job bodies, do the same three observable "
            "wire incompatibilities recur, and does frozen v4.3 alone restore exact "
            "strict-schema validity while remaining reversible and source anchored?"
        ),
        "claim_boundary": independence["claim_boundary"],
        "frozen_inputs": frozen_inputs,
        "selection": {
            "case_count": 5,
            "case_ids": selection["selected_case_ids"],
            "ats_or_delivery_surfaces": selection["collection_protocol"][
                "ats_or_delivery_surfaces"
            ],
            "repository_novelty_checks_passed": True,
            "labels_used_for_selection": False,
            "prior_predictions_used_for_selection": False,
            "collected_after_v4_3_freeze_and_formal_pass": True,
        },
        "request_contract": {
            "source": "frozen_inputs.frozen_v4_request_contract",
            "reuse_system_prompt_byte_for_byte": True,
            "reuse_user_prompt_template_byte_for_byte": True,
            "reuse_json_schema_byte_for_byte": True,
            "reuse_max_output_tokens": 8192,
            "thinking_mode": "disabled",
            "gold_labels_expected_values_or_diagnostics_in_requests": False,
        },
        "execution_protocol": {
            "destination_host": "api.deepseek.com",
            "external_transmission_authorized": False,
            "separate_explicit_authorization_required_before_execution": True,
            "transmitted_content": "the five complete public job bodies",
            "maximum_new_model_calls": 5,
            "maximum_calls_per_case": 1,
            "transport_retries": 0,
            "validation_retries": 0,
            "concurrency": 1,
            "request_artifact_written_before_first_call": True,
            "raw_response_checkpoint_written_after_each_call": True,
            "stop_on_transport_failure": True,
            "continue_after_schema_failure": True,
            "overwrite_existing_outputs": False,
            "v4_v4_1_v4_2_or_v4_3_source_modification_allowed": False,
            "default_parser_allowed": False,
            "canonicalizer_allowed": False,
        },
        "acceptance_gates": {
            "G0-authorization-independence-and-budget": {
                "required_case_count": 5,
                "all_repository_novelty_checks_must_pass": True,
                "explicit_destination_and_full-body_authorization_required": True,
                "maximum_new_model_calls": 5,
                "maximum_calls_per_case": 1,
                "transport_retries": 0,
                "validation_retries": 0,
            },
            "G1-raw-capture-completeness": {
                "required_request_count": 5,
                "required_raw_record_count": 5,
                "required_unique_case_id_count": 5,
                "request_body_hash_must_equal_selection_body_hash": True,
                "request_artifact_precedes_first_call": True,
                "checkpoint_after_each_successful_call": True,
            },
            "G2-v4-3-strict-schema-restoration": {
                "required_v4_3_schema_valid_case_count": 5,
                "baseline_v4_validity_reported_without_thresholding": True,
                "requirement": (
                    "After only frozen v4.3 forward normalization, all five outputs "
                    "validate with exact root and field topology."
                ),
            },
            "G3-compatibility-intervention-integrity": {
                "allowed_diagnostic_codes": [
                    "normalized_responsibility_role_alias",
                    "omitted_empty_absent_fact_placeholder",
                    "normalized_long_self_sufficient_evidence",
                ],
                "forward_output_and_ordered_diagnostics_must_equal_frozen_v4_2": True,
                "v4_3_reverse_must_exactly_restore_every_raw_output": True,
                "unactivated_records_must_be_byte_equivalent": True,
                "other_repairs_allowed": False,
            },
            "G4-source-and-surface-anchoring": {
                "required_source_text_localization_rate": 1.0,
                "required_nonnull_surface_localization_rate": 1.0,
                "minimum_nonnull_primary_surface_rate": 0.8,
                "unmapped_surface_repair_allowed": False,
            },
            "G5-granularity-noncollapse": {
                "floor_basis": (
                    "Before responses exist, manually count source responsibility "
                    "and qualification statements under explicit role headings; "
                    "require at least half as many primary atoms, rounded up."
                ),
                "source_observable_core_statement_counts": CORE_STATEMENT_COUNTS,
                "per_case_minimums": minimums,
                "minimum_aggregate_primary_atom_count": sum(minimums.values()),
                "maximum_aggregate_primary_atom_count": 400,
                "response_or_gold_used_to_set_thresholds": False,
            },
            "G6-fact-layer-compatibility": {
                "required_compatible_case_count": 5,
                "source_unsupported_critical_fact_count": 0,
            },
            "G7-source-isolation-and-preservation": {
                "all_frozen_input_and_source_hashes_must_match": True,
                "raw_responses_retained_on_any_failure": True,
                "gold_unavailable_to_requests": True,
                "default_parser_called": False,
                "canonicalizer_called": False,
                "frozen_compatibility_sources_modified": False,
            },
            "G8-generalization-decision": {
                "confirmed": (
                    "G0-G7 all pass; at least one frozen v4.3 mechanism activates; "
                    "every activated record is baseline-invalid specifically because "
                    "of eligible incompatibilities and becomes valid after v4.3."
                ),
                "supported_non_regression_only": (
                    "G0-G7 all pass; no v4.3 mechanism activates; all five baseline "
                    "outputs are already strict-valid and v4.3 changes nothing."
                ),
                "failed": (
                    "Any G0-G7 gate fails, any activated case remains invalid, any "
                    "ineligible field changes, or any reverse replay is inexact."
                ),
            },
        },
        "evaluation_protocol": {
            "baseline_and_v4_3_scored_from_same_raw": True,
            "baseline_model_calls": 5,
            "v4_3_additional_model_calls": 0,
            "all_activation_and_non_decision_diagnostics_reported": True,
            "formal_execution_count": 1,
            "rerun_after_failure_allowed": False,
            "threshold_change_after_freeze_allowed": False,
            "raw_written_before_report": True,
            "write_new_outputs_only": True,
            "failure_policy": (
                "Retain requests, checkpoints, raw responses, and report; diagnose "
                "offline only; do not edit v4.3 or rerun this holdout."
            ),
        },
        "next_allowed_action": (
            "Implement and freeze a dedicated runner, evaluator, and focused tests "
            "without modifying v4-v4.3; obtain separate explicit authorization "
            "naming api.deepseek.com, all five full bodies, the five-call maximum, "
            "one call per job, and zero retries before any transmission."
        ),
    }
    _write_exclusive(PREREGISTRATION, preregistration)

    freeze = {
        "freeze_version": (
            "unified-jd-flat-atomic-v4.3-independent-holdout-"
            "preregistration-freeze-v1"
        ),
        "date": "2026-09-06",
        "status": "frozen_before_runner_implementation_and_model_calls",
        "artifacts": {
            "selection": _reference(SELECTION),
            "independence_receipt": _reference(INDEPENDENCE),
            "preregistration": _reference(PREREGISTRATION),
            "collector": _reference(COLLECTOR),
            "preregistration_builder": _reference(BUILDER),
        },
        "frozen_inputs": frozen_inputs,
        "decision_rule_frozen": True,
        "thresholds_frozen": True,
        "request_contract_frozen": True,
        "selected_full_body_hashes_frozen": {
            case["case_id"]: {
                "source_content_sha256": case["source_content_sha256"],
                "normalized_content_sha256": case["normalized_content_sha256"],
            }
            for case in selection["cases"]
        },
        "external_transmission_authorized_at_freeze": False,
        "model_call_count_at_freeze": 0,
        "deepseek_call_count_at_freeze": 0,
        "immutability": (
            "Any selection, body, request, threshold, outcome rule, v4.3 mechanism, "
            "or frozen hash change requires a new experiment version."
        ),
    }
    _write_exclusive(FREEZE, freeze)
    print(
        json.dumps(
            {
                "selection": _reference(SELECTION),
                "independence_receipt": _reference(INDEPENDENCE),
                "preregistration": _reference(PREREGISTRATION),
                "preregistration_freeze": _reference(FREEZE),
                "repository_novelty_checks_passed": True,
                "model_call_count": 0,
                "deepseek_call_count": 0,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
