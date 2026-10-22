from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATE = "2026-09-04"
LABELS_PATH = (
    ROOT
    / "datasets"
    / "unified_jd_structured_span_v5_mechanism_development_labels_v1_2026-09-04.json"
)
LABEL_FREEZE_PATH = (
    ROOT
    / "datasets"
    / "unified_jd_structured_span_v5_mechanism_development_label_freeze_v1_2026-09-04.json"
)
BASELINE_RAW_PATH = (
    ROOT
    / "artifacts"
    / "evaluation"
    / "unified-jd-structured-span-v5-mechanism-development-v4-baseline-raw-v1-2026-09-04.json"
)
BASELINE_REPORT_PATH = (
    ROOT
    / "artifacts"
    / "evaluation"
    / "unified-jd-structured-span-v5-mechanism-development-v4-baseline-report-v1-2026-09-04.json"
)
E1_E5_SYNTHESIS_PATH = (
    ROOT
    / "artifacts"
    / "evaluation"
    / "unified-jd-structured-span-v4-e1-e5-synthesis-v1-2026-09-04.json"
)
E6_REPORT_PATH = (
    ROOT
    / "artifacts"
    / "evaluation"
    / "unified-jd-structured-span-v4-e6-priority-tail-rejection-report-v1-2026-09-04.json"
)
E7_REPORT_PATH = (
    ROOT
    / "artifacts"
    / "evaluation"
    / "unified-jd-structured-span-v4-e7-prepositional-wrapper-before-example-split-report-v1-2026-09-04.json"
)
V4_RULES_FREEZE_PATH = (
    ROOT
    / "datasets"
    / "unified_jd_structured_span_rules_freeze_v4_2026-09-04.json"
)
V4_PARSER_PATH = ROOT / "src" / "domain" / "unified_jd_structured_spans_v4.py"
LEGACY_DEVELOPMENT_GOLD_PATH = (
    ROOT
    / "datasets"
    / "unified_jd_structured_span_v4_development_gold_v1_2026-09-04.json"
)
LEGACY_DEVELOPMENT_REPORT_PATH = (
    ROOT
    / "artifacts"
    / "evaluation"
    / "unified-jd-structured-span-v4-development-v4-report-v1-2026-09-04.json"
)
REVEALED_EXTERNAL_PATH = (
    ROOT
    / "datasets"
    / "unified_jd_structured_span_v4_corpus_external_revealed_development_v1_2026-09-04.json"
)
REVEALED_EXTERNAL_V4_RAW_PATH = (
    ROOT
    / "artifacts"
    / "evaluation"
    / "unified-jd-structured-span-v4-corpus-external-raw-v1-2026-09-04.json"
)
OUTPUT_PATH = (
    ROOT
    / "datasets"
    / "unified_jd_structured_span_v5_preregistration_v1_2026-09-04.json"
)
FINDINGS_PATH = (
    ROOT
    / "artifacts"
    / "evaluation"
    / "unified-jd-structured-span-v5-preregistration-v1-2026-09-04.md"
)
FREEZE_PATH = (
    ROOT
    / "datasets"
    / "unified_jd_structured_span_v5_preregistration_freeze_v1_2026-09-04.json"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def relative(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def artifact(path: Path) -> dict[str, str]:
    return {"path": relative(path), "sha256": sha256(path)}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def build_preregistration(baseline: dict[str, Any]) -> dict[str, Any]:
    aggregate = baseline["baseline_metrics"]
    strata = baseline["strata"]
    legacy_rules = load(V4_RULES_FREEZE_PATH)
    external_gates = legacy_rules["corpus_external_holdout_protocol"]["gates"]
    return {
        "preregistration_version": "unified-jd-structured-span-v5-preregistration-v1",
        "created_at": DATE,
        "status": "frozen_before_v5_implementation",
        "scope": {
            "development_data_status": "revealed_mechanism_enriched_not_holdout",
            "generalization_claim": False,
            "threshold_selection_after_freeze_allowed": False,
            "fixture_specific_rules_allowed": False,
            "employer_or_title_specific_rules_allowed": False,
            "category_specific_patch_dispatch_allowed": False,
            "canonicalizer_work_allowed": False,
            "model_calls_allowed": False,
            "network_calls_allowed": False,
            "v4_modification_allowed": False,
            "v5_implementation_status": "not_started",
        },
        "inputs": {
            "development_labels": artifact(LABELS_PATH),
            "development_label_freeze": artifact(LABEL_FREEZE_PATH),
            "v4_baseline_raw": artifact(BASELINE_RAW_PATH),
            "v4_baseline_report": artifact(BASELINE_REPORT_PATH),
            "e1_e5_synthesis": artifact(E1_E5_SYNTHESIS_PATH),
            "e6_report": artifact(E6_REPORT_PATH),
            "e7_report": artifact(E7_REPORT_PATH),
            "v4_rules_freeze": artifact(V4_RULES_FREEZE_PATH),
            "frozen_v4_parser": artifact(V4_PARSER_PATH),
            "legacy_development_gold": artifact(LEGACY_DEVELOPMENT_GOLD_PATH),
            "legacy_development_v4_report": artifact(
                LEGACY_DEVELOPMENT_REPORT_PATH
            ),
            "revealed_external_development": artifact(REVEALED_EXTERNAL_PATH),
            "revealed_external_v4_raw": artifact(REVEALED_EXTERNAL_V4_RAW_PATH),
        },
        "causal_basis": {
            "retained_mechanisms": [
                {
                    "id": "E2-wrapper-boundary",
                    "evidence": "Gold wrapper exclusion boundaries improved member or surface outcomes in 7/8 preregistered targets with no control regression.",
                },
                {
                    "id": "E3-region-first-connector-role",
                    "evidence": "Region-first role correction improved downstream outcomes in 4/6 preregistered targets with no control regression.",
                },
                {
                    "id": "E6-priority-tail-rejection",
                    "evidence": "Preference-only right-tail rejection passed all four frozen criteria without changing retained controls.",
                },
                {
                    "id": "E7-prepositional-wrapper-before-example-split",
                    "evidence": "Moving the local prepositional boundary before example splitting passed all four frozen criteria without control changes.",
                },
            ],
            "excluded_mechanisms": [
                {
                    "id": "E1-category-neutral-dispatch",
                    "reason": "Rejected by its frozen gate; dispatch alone is not a v5 mechanism.",
                },
                {
                    "id": "E4-scope-candidate-versus-application",
                    "reason": "Rejected by its frozen gate; no new candidate-to-scope compatibility heuristic may be added.",
                },
                {
                    "id": "E5-example-attachment-three-toggle",
                    "reason": "The combined toggle family failed its frozen gate. Only the separately supported E6 and E7 residual mechanisms may be used.",
                },
            ],
        },
        "combined_v5_rule": {
            "name": "clause_local_region_graph_v5",
            "implementation_target": "src/domain/unified_jd_structured_spans_v5.py",
            "ordered_stages": [
                {
                    "order": 1,
                    "name": "protect_and_segment",
                    "rule": "Build clause-local top-level regions while protecting parenthetical and lexical spans; retain exact source offsets.",
                },
                {
                    "order": 2,
                    "name": "resolve_wrapper_boundaries",
                    "mechanism": "E2-wrapper-boundary",
                    "rule": "Discover prefix, suffix, and open-list wrapper marker/content spans before constructing coordination members. Wrapper markers are graph metadata and exclusion boundaries, not projected items.",
                },
                {
                    "order": 3,
                    "name": "form_attachment_regions",
                    "rule": "Identify parent-first regions introduced by explicit cues or protected parentheses and postposed 等+head regions. Keep direct open enumerations distinct from illustrative examples.",
                },
                {
                    "order": 4,
                    "name": "reject_preference_only_postposed_parent",
                    "mechanism": "E6-priority-tail-rejection",
                    "rule": "For a postposed attachment candidate created from 等, reject only that candidate when its complete right tail, after closing punctuation, is solely a priority/preference wrapper. Do not suppress an independent explicit 如 or parenthetical parent-first attachment, and do not turn a direct open surface list into examples.",
                },
                {
                    "order": 5,
                    "name": "exclude_local_prepositional_wrapper",
                    "mechanism": "E7-prepositional-wrapper-before-example-split",
                    "rule": "Inside an attachment-bearing region only, remove the already resolved leading prepositional wrapper marker from the example body before splitting members. Never strip 对 globally or from a lexical member.",
                },
                {
                    "order": 6,
                    "name": "classify_connectors_by_innermost_region",
                    "mechanism": "E3-region-first-connector-role",
                    "rule": "Assign connector roles from the innermost protected region before splitting: quantifier, example, embedded, then surface. A character is one connector label at one exact span; lexical punctuation remains protected rather than promoted.",
                },
                {
                    "order": 7,
                    "name": "construct_members_and_explicit_scopes",
                    "rule": "Split members using only connectors licensed for that region. Preserve nested outer-example and inner-embedded groups. Apply a shared scope only when an explicit source prefix, suffix, head, predicate, domain, result, or evidence span governs at least two annotated members.",
                    "e4_exclusion": "Do not add the rejected E4 candidate-versus-application compatibility heuristic.",
                },
                {
                    "order": 8,
                    "name": "project_from_graph",
                    "rule": "Project ordered source-anchored surface items and examples from the graph. Exclude wrappers and embedded-only members; do not canonicalize, paraphrase, or use fixture labels at runtime.",
                },
            ],
            "global_invariants": [
                "All spans are half-open exact slices of source_text.",
                "Every shared-scope target is an annotated coordination member.",
                "Every attachment has a non-priority source parent and at least one example.",
                "Every projected value occurs exactly in source_text.",
                "No stage reads fixture id, job id, employer, title, gold, or expected output.",
                "No category-specific dispatch is introduced to activate the combined stages.",
            ],
        },
        "evaluation_protocol": {
            "development_gate_timing": "Freeze the v5 source hash, then execute one full 20-fixture evaluation and one regression evaluation. Record raw output before computing the decision.",
            "all_criteria_conjunctive": True,
            "post_hoc_threshold_or_exception_changes_forbidden": True,
            "failure_policy": "If any criterion fails, keep v4 as the frozen reference, reveal the failed v5 output for diagnosis, and create a new preregistration version before another combined-rule attempt.",
        },
        "development_baseline": {
            "aggregate": aggregate,
            "strata": strata,
            "source": artifact(BASELINE_REPORT_PATH),
        },
        "development_acceptance_gates": {
            "G0-validity": [
                "structure_validation_error_count == 0",
                "unanchored_output_count == 0",
                "v4 source SHA-256 remains e09e056cab75e651937391ce5410e6df7c94477c85565abb1425bbe85cfcb094",
                "model_call_count == 0 and network_call_count == 0",
            ],
            "G1-aggregate-non-regression": {
                "wrapper_span_f1_min": aggregate["wrapper_span_f1"],
                "connector_classification_accuracy_min": aggregate[
                    "connector_classification_accuracy"
                ],
                "coordination_member_f1_min": aggregate["coordination_member_f1"],
                "shared_scope_edge_f1_min": aggregate["shared_scope_edge_f1"],
                "example_attachment_parent_f1_min": aggregate[
                    "example_attachment_parent_f1"
                ],
                "example_attachment_edge_f1_min": aggregate[
                    "example_attachment_edge_f1"
                ],
                "surface_projection_f1_min": aggregate["surface_projection_f1"],
                "example_projection_f1_min": aggregate["example_projection_f1"],
            },
            "G2-E2-wrapper-boundary": {
                "fixture_ids": [
                    f"structured-v5-mechanism-dev-v1-{index:03d}"
                    for index in range(1, 6)
                ],
                "required_improved_fixture_count": 3,
                "improvement_definition": "A fixture's combined missing+unexpected count across wrapper spans, coordination members, and surface projection is lower than its frozen v4 baseline.",
                "aggregate_requirements": {
                    "wrapper_span_f1_strictly_greater_than": strata[
                        "E2-wrapper-boundary"
                    ]["wrapper_span_f1"],
                    "at_least_one_downstream_strictly_improves": {
                        "coordination_member_f1_baseline": strata[
                            "E2-wrapper-boundary"
                        ]["coordination_member_f1"],
                        "surface_projection_f1_baseline": strata[
                            "E2-wrapper-boundary"
                        ]["surface_projection_f1"],
                    },
                },
            },
            "G3-E3-region-first-connector-role": {
                "fixture_ids": [
                    f"structured-v5-mechanism-dev-v1-{index:03d}"
                    for index in range(6, 11)
                ],
                "required_improved_fixture_count": 4,
                "improvement_definition": "A fixture's combined missing+unexpected count across connector labels, coordination members, attachment edges, and both projections is lower than its frozen v4 baseline.",
                "aggregate_requirements": {
                    "connector_classification_accuracy_strictly_greater_than": strata[
                        "E3-region-first-connector-role"
                    ]["connector_classification_accuracy"],
                    "coordination_member_f1_strictly_greater_than": strata[
                        "E3-region-first-connector-role"
                    ]["coordination_member_f1"],
                    "at_least_one_attachment_or_projection_metric_strictly_improves": {
                        "example_attachment_edge_f1_baseline": strata[
                            "E3-region-first-connector-role"
                        ]["example_attachment_edge_f1"],
                        "surface_projection_f1_baseline": strata[
                            "E3-region-first-connector-role"
                        ]["surface_projection_f1"],
                        "example_projection_f1_baseline": strata[
                            "E3-region-first-connector-role"
                        ]["example_projection_f1"],
                    },
                },
            },
            "G4-E6-priority-tail": {
                "target_011": [
                    "The only attachment is cue 如 -> parent 理工科、管理学及相关交叉学科 with the six frozen examples.",
                    "No 等 cue or 优先/者优先 span is an attachment parent.",
                ],
                "target_012": [
                    "attachment count == 0 and example projection is empty",
                    "surface projection is exactly 手配, 小家电, 外设产品, 摄影摄像",
                ],
                "matched_controls_013_015": "For every control, no primary-layer missing+unexpected count may exceed its frozen v4 baseline; every retained attachment parent, cue, and example span must match gold exactly.",
            },
            "G5-E7-prepositional-boundary": {
                "fixture_ids": [
                    f"structured-v5-mechanism-dev-v1-{index:03d}"
                    for index in range(16, 21)
                ],
                "first_example_spans": {
                    "structured-v5-mechanism-dev-v1-016": "人机交互",
                    "structured-v5-mechanism-dev-v1-017": "商业分析",
                    "structured-v5-mechanism-dev-v1-018": "供应链计划",
                    "structured-v5-mechanism-dev-v1-019": "系统分层",
                    "structured-v5-mechanism-dev-v1-020": "外呼的销售策略",
                },
                "requirements": [
                    "All five first-example spans are exact and none starts with 对.",
                    "All five attachment parents, example edges, and example projections are exact.",
                    "No non-attachment 对 wrapper elsewhere is globally stripped.",
                ],
            },
            "G6-regression": [
                "The 20-fixture legacy v4 development gold remains exact on all structural layers and both projections.",
                "On the 20 revealed corpus-external fixtures, no aggregate metric and no per-fixture primary-layer difference count is worse than the stored v4 baseline.",
                "The existing 60-case v4 projection regression remains 60/60 exact under v5.",
                "All existing structured-span tests plus new v5 tests pass.",
            ],
        },
        "post_development_protocol": {
            "on_pass": "Freeze v5 source and its development report, then collect and label a fresh corpus-external blind holdout with no job, URL, or source-text overlap with any revealed data.",
            "blind_holdout_gate": external_gates,
            "holdout_gate_origin": artifact(V4_RULES_FREEZE_PATH),
            "canonicalizer_unlock_condition": "Only a one-time pass of every unchanged blind-holdout gate unlocks canonicalizer implementation. A development pass alone never does.",
            "on_fail": "Do not canonicalize and do not weaken a threshold. Diagnose the frozen failure and preregister a new version before changing v5.",
        },
    }


def render(preregistration: dict[str, Any]) -> str:
    baseline = preregistration["development_baseline"]["aggregate"]
    return "\n".join(
        [
            "# Structured-span v5 preregistration",
            "",
            "## Decision boundary",
            "",
            "This preregistration is frozen before v5 implementation. The 20 Meituan clauses are revealed, mechanism-enriched development data and cannot support a generalization claim. V4 and the canonicalizer remain unchanged.",
            "",
            "## Combined rule",
            "",
            "V5 is one clause-local region graph pipeline: resolve wrapper boundaries, form attachment regions, reject only preference-only postposed parents, exclude a resolved local prepositional wrapper before example splitting, classify connectors by their innermost region, build members and explicit scopes, then project exact source spans.",
            "",
            "The rule may use only the supported E2, E3, E6, and E7 mechanisms. Rejected E1/E4 and the failed E5 toggle family are excluded. Fixture IDs, employer/title routing, gold lookup, and category-specific patch dispatch are forbidden.",
            "",
            "## Frozen v4 baseline",
            "",
            "| Metric | V4 baseline / v5 minimum |",
            "|---|---:|",
            f"| Wrapper-span F1 | {baseline['wrapper_span_f1']:.6f} |",
            f"| Connector accuracy | {baseline['connector_classification_accuracy']:.6f} |",
            f"| Coordination-member F1 | {baseline['coordination_member_f1']:.6f} |",
            f"| Shared-scope-edge F1 | {baseline['shared_scope_edge_f1']:.6f} |",
            f"| Attachment-parent F1 | {baseline['example_attachment_parent_f1']:.6f} |",
            f"| Attachment-edge F1 | {baseline['example_attachment_edge_f1']:.6f} |",
            f"| Surface-projection F1 | {baseline['surface_projection_f1']:.6f} |",
            f"| Example-projection F1 | {baseline['example_projection_f1']:.6f} |",
            "",
            "These aggregate floors are necessary but not sufficient. E2 requires improvement on at least 3/5 new targets; E3 requires improvement on at least 4/5. E6's two targets and three controls have explicit topology constraints. E7 requires all five first-example boundaries and all attachment/projection edges to be exact. Legacy and revealed-development regression gates are conjunctive.",
            "",
            "## After development",
            "",
            "A passing development run only permits freezing v5 and creating a fresh blind external holdout. It does not unlock canonicalization. Canonicalization remains blocked until v5 passes every unchanged external gate in one blind evaluation.",
            "",
        ]
    )


def main() -> int:
    label_freeze = load(LABEL_FREEZE_PATH)
    baseline = load(BASELINE_REPORT_PATH)
    synthesis = load(E1_E5_SYNTHESIS_PATH)
    e6 = load(E6_REPORT_PATH)
    e7 = load(E7_REPORT_PATH)

    if label_freeze["artifacts"]["labels"]["sha256"] != sha256(LABELS_PATH):
        raise ValueError("development labels changed after freeze")
    if baseline["inputs"]["labels"]["sha256"] != sha256(LABELS_PATH):
        raise ValueError("baseline does not use the frozen development labels")
    retained = {
        item["experiment_id"] for item in synthesis["retained_mechanisms"]
    }
    if retained != {
        "E2-wrapper-boundary-oracle",
        "E3-region-first-connector-role-oracle",
    }:
        raise ValueError(f"unexpected E1-E5 retained mechanisms: {retained}")
    if not e6["decision"]["accepted"] or not e7["decision"]["accepted"]:
        raise ValueError("E6 and E7 must pass their independent frozen gates")
    if (ROOT / "src" / "domain" / "unified_jd_structured_spans_v5.py").exists():
        raise ValueError("v5 already exists; preregistration must precede implementation")

    preregistration = build_preregistration(baseline)
    write_json(OUTPUT_PATH, preregistration)
    FINDINGS_PATH.write_text(render(preregistration), encoding="utf-8")
    freeze = {
        "freeze_version": "unified-jd-structured-span-v5-preregistration-freeze-v1",
        "frozen_at": DATE,
        "status": "frozen_before_v5_implementation",
        "artifacts": {
            "preregistration": artifact(OUTPUT_PATH),
            "findings": artifact(FINDINGS_PATH),
            "builder": artifact(Path(__file__).resolve()),
            "frozen_v4_parser": artifact(V4_PARSER_PATH),
        },
        "checks": {
            "labels_frozen_before_baseline": True,
            "baseline_recorded_before_thresholds": True,
            "only_e2_e3_e6_e7_retained": True,
            "e1_e4_e5_excluded": True,
            "all_gates_conjunctive": True,
            "threshold_tuning_after_freeze_allowed": False,
            "v5_existed_at_freeze": False,
            "canonicalizer_existed_at_freeze": False,
            "model_call_count": 0,
            "network_call_count": 0,
        },
        "immutability": "Any rule or threshold change requires a new preregistration and freeze version before another v5 implementation/evaluation cycle.",
        "next_allowed_action": "Implement only the frozen combined v5 rule, freeze its source hash, then execute the registered development and regression gates once.",
    }
    write_json(FREEZE_PATH, freeze)
    print(
        json.dumps(
            {
                "preregistration": str(OUTPUT_PATH),
                "preregistration_sha256": sha256(OUTPUT_PATH),
                "findings": str(FINDINGS_PATH),
                "freeze": str(FREEZE_PATH),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
