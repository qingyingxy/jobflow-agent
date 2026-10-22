from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PARSER_PATH = PROJECT_ROOT / "src/domain/unified_jd_structured_spans_v4.py"
RULES_FREEZE_PATH = (
    PROJECT_ROOT
    / "datasets/unified_jd_structured_span_rules_freeze_v4_2026-09-04.json"
)
E5_RAW_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-e5-example-attachment-three-toggle-raw-v1-2026-09-04.json"
)
BASELINE_RAW_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-corpus-external-raw-v1-2026-09-04.json"
)
SYNTHESIS_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-e1-e5-synthesis-v1-2026-09-04.json"
)
FINDINGS_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-e1-e5-synthesis-findings-v1-2026-09-04.md"
)
PREREGISTRATION_PATH = (
    PROJECT_ROOT
    / "datasets/unified_jd_structured_span_v4_residual_experiments_preregistration_v1-2026-09-04.json"
)

REPORT_PATHS = {
    "E1-dispatch-only": PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-e1-dispatch-only-report-v1-2026-09-04.json",
    "E2-wrapper-boundary-oracle": PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-e2-wrapper-oracle-report-v1-2026-09-04.json",
    "E3-region-first-connector-role-oracle": PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-e3-connector-role-oracle-report-v1-2026-09-04.json",
    "E4-scope-candidate-versus-application": PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-e4-scope-candidate-application-report-v1-2026-09-04.json",
    "E5-example-attachment-three-toggle": PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-e5-example-attachment-three-toggle-report-v1-2026-09-04.json",
}

EXPECTED_HASHES = {
    PARSER_PATH: "e09e056cab75e651937391ce5410e6df7c94477c85565abb1425bbe85cfcb094",
    RULES_FREEZE_PATH: (
        "6a8a1d9ccce7c1069a483c7cc387221164de52800a133308922d57ff75ad6a12"
    ),
    BASELINE_RAW_PATH: (
        "36b65c1df79d856c7507ae1357ed24c10b7a3e383bad79b9471b124f4999e058"
    ),
    E5_RAW_PATH: "8d38a34ee72aa969f2f04efdc139dc3d0c8c22b262286eb49902cc2ab7bec592",
    REPORT_PATHS["E1-dispatch-only"]: (
        "724209b4b81e8a88ea04518f557183b7519accb2e03c61e7eb1f06c68d6ed60f"
    ),
    REPORT_PATHS["E2-wrapper-boundary-oracle"]: (
        "84d53a7d11556cf32f4892e42ebed7a4e40979871ace1e35195786888e69db3c"
    ),
    REPORT_PATHS["E3-region-first-connector-role-oracle"]: (
        "5dc74e90c81330b03a17554caff7d5e147011ff59f9e76019d5502fe0b67a28b"
    ),
    REPORT_PATHS["E4-scope-candidate-versus-application"]: (
        "e8411116af4a3b759a3a41b243027476972954b0d33b44fac58b696f6552898c"
    ),
    REPORT_PATHS["E5-example-attachment-three-toggle"]: (
        "bd12b18f1d6e8e0299e5efb5cb91ec7705f6c6c3c12d687f9ee02a3da13683c8"
    ),
}

EXPECTED_DECISIONS = {
    "E1-dispatch-only": (False, 2, 3),
    "E2-wrapper-boundary-oracle": (True, 7, 4),
    "E3-region-first-connector-role-oracle": (True, 4, 4),
    "E4-scope-candidate-versus-application": (False, 3, 4),
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _relative(path: Path) -> str:
    return path.relative_to(PROJECT_ROOT).as_posix()


def _input(path: Path) -> dict[str, str]:
    return {"path": _relative(path), "sha256": _sha256(path)}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_bytes(
        (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    )


def _validate_inputs(reports: dict[str, dict[str, Any]]) -> None:
    for path, expected in EXPECTED_HASHES.items():
        actual = _sha256(path)
        if actual != expected:
            raise ValueError(f"frozen input hash mismatch for {path}: {actual} != {expected}")

    for experiment_id, (accepted, improved, required) in EXPECTED_DECISIONS.items():
        decision = reports[experiment_id]["decision"]
        observed = (
            decision["accepted"],
            decision["improved_target_count"],
            decision["required_improved_target_count"],
        )
        if observed != (accepted, improved, required):
            raise ValueError(f"decision drift for {experiment_id}: {observed}")

    e5 = reports["E5-example-attachment-three-toggle"]["decision"]
    expected_e5 = {
        "accepted": False,
        "toggle1_fixes_002_005_example_spans": True,
        "toggle2_discovers_019": True,
        "toggle2_controls_unchanged": False,
        "toggle2_control_changes": {
            "structured-corpus-external-v1-006": True,
            "structured-corpus-external-v1-018": False,
        },
        "toggle3_all_target_parents_exact": True,
        "toggle3_all_target_edges_exact": False,
    }
    for key, value in expected_e5.items():
        if e5[key] != value:
            raise ValueError(f"E5 decision drift for {key}: {e5[key]} != {value}")


def _experiment_summaries(
    reports: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    e1 = reports["E1-dispatch-only"]["decision"]
    e2 = reports["E2-wrapper-boundary-oracle"]["decision"]
    e3 = reports["E3-region-first-connector-role-oracle"]["decision"]
    e4 = reports["E4-scope-candidate-versus-application"]["decision"]
    e5 = reports["E5-example-attachment-three-toggle"]["decision"]
    return [
        {
            "order": 1,
            "experiment_id": "E1-dispatch-only",
            "decision": "rejected",
            "registered_gate": "at_least_3_of_5_targets_and_no_control_change",
            "observed": {
                "improved_targets": e1["improved_target_count"],
                "required_targets": e1["required_improved_target_count"],
                "controls_unchanged": all(e1["control_unchanged"].values()),
            },
            "disposition": "exclude_unconditional_category_builder_dispatch",
        },
        {
            "order": 2,
            "experiment_id": "E2-wrapper-boundary-oracle",
            "decision": "accepted",
            "registered_gate": "at_least_4_of_8_targets_and_no_control_regression",
            "observed": {
                "improved_targets": e2["improved_target_count"],
                "required_targets": e2["required_improved_target_count"],
                "no_control_regression": e2["no_control_regression"],
            },
            "disposition": "retain_wrapper_boundary_enforcement_candidate",
        },
        {
            "order": 3,
            "experiment_id": "E3-region-first-connector-role-oracle",
            "decision": "accepted",
            "registered_gate": "at_least_4_of_6_targets_and_no_control_regression",
            "observed": {
                "improved_targets": e3["improved_target_count"],
                "required_targets": e3["required_improved_target_count"],
                "no_control_regression": e3["no_control_regression"],
                "attachment_improved": e3["attachment_improved"],
            },
            "disposition": "retain_protected_region_first_connector_roles",
        },
        {
            "order": 4,
            "experiment_id": "E4-scope-candidate-versus-application",
            "decision": "rejected",
            "registered_gate": (
                "distinguish_017_020_avoid_016_and_improve_4_of_6_without_regression"
            ),
            "observed": {
                "pair_distinguished": e4["compatibility_distinguishes_017_020"],
                "singleton_avoided": e4["singleton_016_scope_avoided"],
                "improved_targets": e4["improved_target_count"],
                "required_targets": e4["required_improved_target_count"],
                "no_control_regression": e4["no_control_regression"],
            },
            "disposition": "exclude_compatibility_oracle_as_standalone_scope_mechanism",
        },
        {
            "order": 5,
            "experiment_id": "E5-example-attachment-three-toggle",
            "decision": "rejected",
            "registered_gate": "all_three_registered_toggle_checks_must_pass",
            "observed": {
                "toggle1_fixed_002_005": e5[
                    "toggle1_fixes_002_005_example_spans"
                ],
                "toggle2_discovered_019": e5["toggle2_discovers_019"],
                "toggle2_controls_unchanged": e5["toggle2_controls_unchanged"],
                "toggle3_all_parents_exact": e5[
                    "toggle3_all_target_parents_exact"
                ],
                "toggle3_all_edges_exact": e5["toggle3_all_target_edges_exact"],
            },
            "disposition": "exclude_all_e5_toggles_pending_residual_experiments",
        },
    ]


def build_synthesis(reports: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "synthesis_version": "unified-jd-structured-span-v4-e1-e5-synthesis-v1",
        "created_at": "2026-09-04",
        "scope": {
            "status": "revealed_development_causal_synthesis",
            "experiment_count": 5,
            "generalization_claim": False,
            "production_rule_claim": False,
            "threshold_selection_allowed": False,
            "v4_modified": False,
            "v5_implemented": False,
            "canonicalizer_work": False,
            "model_call_count": 0,
            "network_call_count": 0,
        },
        "inputs": {
            "frozen_v4_source": _input(PARSER_PATH),
            "rules_freeze": _input(RULES_FREEZE_PATH),
            "e5_final_raw": _input(E5_RAW_PATH),
            "experiment_reports": {
                experiment_id: _input(path)
                for experiment_id, path in REPORT_PATHS.items()
            },
        },
        "selection_rule": (
            "Retain a mechanism only when its experiment passed its frozen, "
            "per-fixture acceptance gate without a registered control regression. "
            "Partial sub-results from a rejected experiment remain diagnostic only."
        ),
        "experiment_summary": _experiment_summaries(reports),
        "retained_mechanisms": [
            {
                "experiment_id": "E2-wrapper-boundary-oracle",
                "mechanism": "wrapper_boundary_enforcement",
                "supported_claim": (
                    "Enforcing correct wrapper exclusion boundaries causally reduces "
                    "member or surface errors in 7/8 registered targets without "
                    "control regression."
                ),
                "production_boundary": (
                    "Use predicted wrapper regions in a future implementation; "
                    "never copy gold boundaries or treat the oracle as a ready rule."
                ),
            },
            {
                "experiment_id": "E3-region-first-connector-role-oracle",
                "mechanism": "protected_region_first_connector_role_assignment",
                "supported_claim": (
                    "Correct roles for connectors inside protected wrapper, predicate, "
                    "example, and quantifier regions independently improve member or "
                    "surface outcomes in 4/6 targets without control regression."
                ),
                "production_boundary": (
                    "The result supports region-first role assignment, not adding more "
                    "surface connectors; none-to-surface cases 001 and 003 regressed, "
                    "and attachment did not improve."
                ),
            },
        ],
        "rejected_mechanisms": [
            {
                "experiment_id": "E1-dispatch-only",
                "mechanism": "unconditional_category_builder_dispatch",
                "reason": "Only 2/5 targets improved; the frozen gate required 3/5.",
            },
            {
                "experiment_id": "E4-scope-candidate-versus-application",
                "mechanism": "revealed_member_head_compatibility_as_scope_rule",
                "reason": (
                    "Compatibility separated 017/020 and fixed 016, but improved only "
                    "3/6 targets; the frozen gate required 4/6."
                ),
            },
            {
                "experiment_id": "E5-example-attachment-three-toggle",
                "mechanism": "combined_cue_category_parent_attachment_toggles",
                "reason": (
                    "The category-neutral toggle falsely attached control 006, and "
                    "019 retained a leading preposition in its first example span."
                ),
            },
        ],
        "residual_mechanisms": [
            {
                "id": "R1-priority-tail-false-attachment",
                "source_experiment": "E5-example-attachment-three-toggle",
                "fixture_id": "structured-corpus-external-v1-006",
                "observation": (
                    "Category-neutral detection treats enumeration-closing deng followed "
                    "only by the preference marker youxian as an example attachment."
                ),
                "next_experiment": "E6-priority-tail-rejection",
            },
            {
                "id": "R2-prepositional-wrapper-in-example-member",
                "source_experiment": "E5-example-attachment-three-toggle",
                "fixture_id": "structured-corpus-external-v1-019",
                "observation": (
                    "The first example is 17:23 and includes leading dui; the exact "
                    "example boundary is 18:23."
                ),
                "next_experiment": "E7-prepositional-wrapper-before-example-split",
            },
        ],
        "next_action": {
            "preregistration_path": _relative(PREREGISTRATION_PATH),
            "experiment_ids": [
                "E6-priority-tail-rejection",
                "E7-prepositional-wrapper-before-example-split",
            ],
            "execution_allowed_after_freeze": True,
            "implementation_before_result": False,
        },
    }


def _e5_final_hashes(e5_raw: dict[str, Any]) -> dict[str, str]:
    return {
        record["id"]: _json_sha256(record["toggle3_parent_ranked"])
        for record in e5_raw["records"]
    }


def build_preregistration(
    synthesis_hash: str,
    e5_raw: dict[str, Any],
    baseline_raw: dict[str, Any],
) -> dict[str, Any]:
    baseline_by_id = {item["id"]: item for item in baseline_raw["records"]}
    return {
        "preregistration_version": (
            "unified-jd-structured-span-v4-residual-experiments-"
            "preregistration-v1"
        ),
        "created_at": "2026-09-04",
        "status": "frozen_before_execution",
        "scope": {
            "data_status": "revealed_development_only",
            "generalization_claim": False,
            "production_rule_claim": False,
            "threshold_selection_allowed": False,
            "v4_modification_allowed": False,
            "v5_implementation_allowed": False,
            "canonicalizer_work_allowed": False,
            "model_calls_allowed": False,
            "network_calls_allowed": False,
        },
        "inputs": {
            "synthesis": {
                "path": _relative(SYNTHESIS_PATH),
                "sha256": synthesis_hash,
            },
            "frozen_v4_source": _input(PARSER_PATH),
            "rules_freeze": _input(RULES_FREEZE_PATH),
            "e5_final_raw": _input(E5_RAW_PATH),
            "corpus_external_baseline_raw": _input(BASELINE_RAW_PATH),
        },
        "baseline_anchors": {
            "e5_arm": "toggle3_parent_ranked",
            "e5_final_arm_sha256_by_fixture": _e5_final_hashes(e5_raw),
            "additional_e7_control_009_record_sha256": _json_sha256(
                baseline_by_id["structured-corpus-external-v1-009"]
            ),
        },
        "global_guards": {
            "experiments_are_independent": True,
            "e7_must_not_include_e6_treatment": True,
            "single_changed_mechanism_per_experiment": True,
            "all_acceptance_criteria_are_conjunctive": True,
            "post_hoc_exception_or_threshold_tuning_forbidden": True,
            "record_raw_and_report_before_interpretation": True,
            "stop_after_e6_e7": (
                "Do not merge either residual mechanism into v5 until its own frozen "
                "gate has been evaluated."
            ),
        },
        "experiments": [
            {
                "order": 6,
                "id": "E6-priority-tail-rejection",
                "status": "preregistered_not_executed",
                "residual_id": "R1-priority-tail-false-attachment",
                "hypothesis": (
                    "Category-neutral attachment detection conflates enumeration "
                    "closure deng followed solely by a priority or preference operator "
                    "with a genuine example-to-parent attachment."
                ),
                "causal_question": (
                    "Does rejecting attachment eligibility only when the complete "
                    "right tail is a priority or preference operator remove the 006 "
                    "false attachment while preserving genuine attachments?"
                ),
                "baseline": {
                    "source": "E5 toggle3_parent_ranked arm",
                    "target_observation": {
                        "fixture_id": "structured-corpus-external-v1-006",
                        "cue_span": {"text": "等", "start": 32, "end": 33},
                        "right_tail_span": {"text": "优先", "start": 33, "end": 35},
                        "attachment_count": 1,
                        "gold_attachment_count": 0,
                    },
                },
                "intervention": (
                    "Change only attachment eligibility after category-neutral topology "
                    "detection: reject a candidate when its complete right tail is a "
                    "priority or preference operator."
                ),
                "single_changed_variable": "priority_tail_attachment_eligibility",
                "held_fixed": [
                    "category-neutral candidate detection",
                    "cue discovery and cue spans",
                    "example member splitting and spans",
                    "parent candidate generation and ranking",
                    "wrapper, connector, scope, and projection inputs",
                    "all retained attachment cue, parent, and member spans",
                ],
                "target_fixture_ids": ["structured-corpus-external-v1-006"],
                "control_fixture_ids": [
                    "structured-corpus-external-v1-002",
                    "structured-corpus-external-v1-005",
                    "structured-corpus-external-v1-019",
                    "structured-corpus-external-v1-018",
                ],
                "primary_outcomes": [
                    "006 false attachment count",
                    "006 false example-member count",
                    "006 false attachment-edge count",
                    "byte equality of every control final-arm payload",
                ],
                "acceptance_criteria": [
                    "006 has zero attachments, example members, example items, and attachment edges.",
                    "019 retains the E5-discovered attachment.",
                    "All four control final-arm payloads are byte-identical to their E5 baselines.",
                    "No cue, parent, or member span changes in any retained attachment.",
                ],
                "acceptance_gate": "accept_only_if_all_four_criteria_pass",
                "falsification": (
                    "Reject if 006 retains any false attachment output, 019 discovery "
                    "is lost, any control payload changes, or a retained span changes."
                ),
                "interpretation_limit": (
                    "This is single-case revealed-development causality, not evidence "
                    "for a production lexical blacklist or generalized priority rule."
                ),
            },
            {
                "order": 7,
                "id": "E7-prepositional-wrapper-before-example-split",
                "status": "preregistered_not_executed",
                "residual_id": "R2-prepositional-wrapper-in-example-member",
                "hypothesis": (
                    "019 includes leading dui in its first example because leading "
                    "prepositional-wrapper normalization occurs after example splitting."
                ),
                "causal_question": (
                    "Does moving only the leading prepositional-wrapper boundary before "
                    "example splitting make 019 exact without creating changes in clauses "
                    "where dui is a legitimate wrapper but no attachment exists?"
                ),
                "baseline": {
                    "source": (
                        "Independent reconstruction of the E5 toggle3_parent_ranked "
                        "state; E6 treatment is absent. Control 009 is added from the "
                        "frozen corpus-external baseline."
                    ),
                    "target_observation": {
                        "fixture_id": "structured-corpus-external-v1-019",
                        "first_example_before": {
                            "text": "对大模型评测",
                            "start": 17,
                            "end": 23,
                        },
                        "first_example_expected": {
                            "text": "大模型评测",
                            "start": 18,
                            "end": 23,
                        },
                        "cue_span": {"text": "等", "start": 33, "end": 34},
                        "parent_span": {"text": "领域", "start": 34, "end": 36},
                    },
                },
                "intervention": (
                    "Move only the leading prepositional-wrapper exclusion boundary "
                    "ahead of example-member splitting for the attachment-bearing region."
                ),
                "single_changed_variable": (
                    "leading_prepositional_wrapper_boundary_order_before_example_split"
                ),
                "held_fixed": [
                    "attachment existence and attachment count",
                    "cue discovery and cue span",
                    "parent candidates, ranking, and selected parent span",
                    "all non-leading example member spans",
                    "connector roles, shared scopes, and non-example projection",
                    "E6 priority-tail treatment is absent",
                ],
                "target_fixture_ids": ["structured-corpus-external-v1-019"],
                "control_fixture_ids": [
                    "structured-corpus-external-v1-002",
                    "structured-corpus-external-v1-005",
                    "structured-corpus-external-v1-006",
                    "structured-corpus-external-v1-009",
                    "structured-corpus-external-v1-018",
                ],
                "control_rationale": {
                    "structured-corpus-external-v1-009": (
                        "Starts with a legitimate dui prefix wrapper and has no example "
                        "attachment; it detects accidental global preposition stripping."
                    )
                },
                "primary_outcomes": [
                    "019 first-example exact boundary",
                    "019 example-member exactness",
                    "019 example projection exactness",
                    "019 attachment-edge exactness",
                    "control payload and attachment-count stability",
                ],
                "acceptance_criteria": [
                    "019 first example changes exactly from 17:23 to 18:23 and no other target span changes.",
                    "019 example members, example projection, and all attachment edges are exact.",
                    "019 cue 33:34 and parent 34:36 remain unchanged.",
                    "No control payload or attachment count changes, including control 009.",
                ],
                "acceptance_gate": "accept_only_if_all_four_criteria_pass",
                "falsification": (
                    "Reject if any change exceeds the single leading boundary, target "
                    "edges remain inexact, cue or parent moves, or any control changes."
                ),
                "interpretation_limit": (
                    "This tests operation ordering on one revealed target. Passing does "
                    "not establish a generalized prepositional-wrapper implementation."
                ),
            },
        ],
    }


def render_findings(synthesis: dict[str, Any]) -> str:
    lines = [
        "# E1-E5 causal synthesis and residual preregistration",
        "",
        "## Scope",
        "",
        "- Revealed development data only; no generalization or production-rule claim.",
        "- Frozen v4 and its rule manifest were neither executed nor modified.",
        "- No model, network, v5 implementation, threshold tuning, or canonicalizer work.",
        "- A mechanism is retained only if its complete frozen gate passed.",
        "",
        "## E1-E5 decisions",
        "",
        "| Experiment | Gate result | Decision | Consequence |",
        "|---|---:|---|---|",
        "| E1 dispatch-only | 2/5; required 3/5 | Rejected | Do not make category builders unconditional |",
        "| E2 wrapper-boundary oracle | 7/8; required 4/8 | Accepted | Retain wrapper-boundary enforcement candidate |",
        "| E3 connector-role oracle | 4/6; required 4/6 | Accepted | Retain protected-region-first role assignment |",
        "| E4 scope application | 3/6; required 4/6 | Rejected | Do not encode the compatibility oracle |",
        "| E5 attachment toggles | Two residual failures | Rejected | Retain none of the three toggles yet |",
        "",
        "## Retained mechanisms",
        "",
        "1. E2: resolve and enforce wrapper exclusion boundaries before member and surface construction. Gold boundaries remain an attribution oracle only.",
        "2. E3: classify connector roles after protecting wrapper, predicate, example, and quantifier regions. This is not permission to add more surface connectors.",
        "",
        "E3 improved surface-to-embedded/example/quantifier corrections, but the none-to-surface cases 001 and 003 regressed. Attachment edges did not improve, so attachment remains separate.",
        "",
        "## Explicit exclusions",
        "",
        "E1, E4, and E5 remain rejected. Useful sub-results inside E4 or E5 are diagnostic evidence, not retained v5 mechanisms.",
        "",
        "## E5 residuals",
        "",
        "- E6 isolates the 006 false attachment caused by enumeration-closing `等` followed only by `优先`.",
        "- E7 independently isolates 019's leading `对` boundary error by moving wrapper normalization before example splitting.",
        "",
        "The frozen preregistration is at `datasets/unified_jd_structured_span_v4_residual_experiments_preregistration_v1-2026-09-04.json`. E6 and E7 are independent; E7 must not inherit E6.",
        "",
    ]
    retained = [item["experiment_id"] for item in synthesis["retained_mechanisms"]]
    if retained != [
        "E2-wrapper-boundary-oracle",
        "E3-region-first-connector-role-oracle",
    ]:
        raise ValueError(f"unexpected retained mechanisms: {retained}")
    return "\n".join(lines)


def build_artifacts() -> tuple[dict[str, Any], dict[str, Any], str]:
    reports = {key: _load(path) for key, path in REPORT_PATHS.items()}
    _validate_inputs(reports)
    synthesis = build_synthesis(reports)
    findings = render_findings(synthesis)
    synthesis_bytes = (
        json.dumps(synthesis, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    synthesis_hash = hashlib.sha256(synthesis_bytes).hexdigest()
    preregistration = build_preregistration(
        synthesis_hash,
        _load(E5_RAW_PATH),
        _load(BASELINE_RAW_PATH),
    )
    return synthesis, preregistration, findings


def main() -> int:
    synthesis, preregistration, findings = build_artifacts()
    SYNTHESIS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _write_json(SYNTHESIS_PATH, synthesis)
    FINDINGS_PATH.write_bytes(findings.encode("utf-8"))
    _write_json(PREREGISTRATION_PATH, preregistration)
    print(
        "retained=E2,E3 rejected=E1,E4,E5 "
        "preregistered=E6-priority-tail-rejection,"
        "E7-prepositional-wrapper-before-example-split"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
