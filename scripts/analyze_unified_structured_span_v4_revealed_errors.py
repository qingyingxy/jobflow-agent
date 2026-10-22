from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = (
    PROJECT_ROOT
    / "datasets/unified_jd_structured_span_v4_corpus_external_revealed_development_v1_2026-09-04.json"
)
REVEAL_RECEIPT_PATH = (
    PROJECT_ROOT
    / "datasets/unified_jd_structured_span_v4_corpus_external_reveal_receipt_v1_2026-09-04.json"
)
PARSER_PATH = PROJECT_ROOT / "src/domain/unified_jd_structured_spans_v4.py"
OUTPUT_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-revealed-error-analysis-v1-2026-09-04.json"
)
FINDINGS_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-revealed-error-analysis-v1-2026-09-04.md"
)

EXPECTED_DATASET_SHA256 = (
    "965263881ff85bca636aa6ab87adaca24d74183fa13400709133323a3a6d5b73"
)
EXPECTED_REVEAL_RECEIPT_SHA256 = (
    "5b2d652de5f01d2d74cac0a1837fc308d4dec05992d4d911d1eafbdf4f30db1b"
)
EXPECTED_PARSER_SHA256 = (
    "e09e056cab75e651937391ce5410e6df7c94477c85565abb1425bbe85cfcb094"
)

DIFFERENCE_LAYERS = (
    "wrappers",
    "coordination_members",
    "shared_scope_edges",
    "example_attachment_parents",
    "example_attachment_edges",
    "surface_projection",
    "example_projection",
)

COUNTEREXAMPLE_SPECS = (
    {
        "id": "P1-same-example-shape-different-parent-direction",
        "fixture_ids": [
            "structured-corpus-external-v1-002",
            "structured-corpus-external-v1-005",
        ],
        "controlled_contrast": (
            "Both clauses contain an introductory example list followed by deng, "
            "but 002 has a right-local compound parent while 005 refers back to the "
            "preceding segment."
        ),
        "inference": (
            "A fixed rule that always selects text immediately to the right of deng "
            "cannot recover both parent attachments."
        ),
    },
    {
        "id": "P2-same-ability-ending-different-scope",
        "fixture_ids": [
            "structured-corpus-external-v1-017",
            "structured-corpus-external-v1-020",
        ],
        "controlled_contrast": (
            "Both clauses have ju-bei + evaluative modifier + X connector Y neng-li. "
            "In 017 neng-li belongs only to Y; in 020 it is shared by X and Y."
        ),
        "inference": (
            "Punctuation and the final token alone do not determine shared scope; "
            "member-head compatibility is required."
        ),
    },
    {
        "id": "P3-same-connector-different-role",
        "fixture_ids": [
            "structured-corpus-external-v1-001",
            "structured-corpus-external-v1-007",
        ],
        "controlled_contrast": (
            "The connector yu is a surface split in 001 but embedded inside a "
            "discovery predicate in 007."
        ),
        "inference": (
            "Connector text cannot determine role before wrapper and predicate "
            "regions are known."
        ),
    },
    {
        "id": "P4-alternative-versus-quantifier",
        "fixture_ids": [
            "structured-corpus-external-v1-011",
            "structured-corpus-external-v1-018",
        ],
        "controlled_contrast": (
            "Slashes in 011 enumerate job domains, while huo in yi-ge-huo-duo-ge "
            "in 018 is internal to a quantifier."
        ),
        "inference": (
            "Alternative markers need protected quantifier context before surface "
            "coordination scanning."
        ),
    },
    {
        "id": "P5-same-example-topology-different-category",
        "fixture_ids": [
            "structured-corpus-external-v1-002",
            "structured-corpus-external-v1-019",
        ],
        "controlled_contrast": (
            "Both contain A, B, C + deng + nominal parent, but 002 is a "
            "responsibility and 019 is a capability."
        ),
        "inference": (
            "Example attachment is clause-local topology and must not be disabled "
            "by category."
        ),
    },
)

EXPERIMENT_SPECS = (
    {
        "order": 1,
        "id": "E1-dispatch-only",
        "hypothesis": (
            "Most external failures are hidden by conditional category upgrade "
            "gates before v4 structural stages can run."
        ),
        "intervention": (
            "Force entry into the existing category-specific v4 builder for the "
            "target clauses. Hold every builder rule and projection rule fixed."
        ),
        "target_fixture_ids": [
            "structured-corpus-external-v1-004",
            "structured-corpus-external-v1-006",
            "structured-corpus-external-v1-008",
            "structured-corpus-external-v1-011",
            "structured-corpus-external-v1-016",
        ],
        "control_fixture_ids": [
            "structured-corpus-external-v1-002",
            "structured-corpus-external-v1-012",
            "structured-corpus-external-v1-019",
        ],
        "primary_outcomes": [
            "per-fixture total structural difference count",
            "wrapper F1",
            "coordination-member F1",
            "surface projection F1",
        ],
        "acceptance": (
            "At least 3/5 targets reduce structural differences, no target gains a "
            "structure-validation error, and all three controls remain unchanged."
        ),
        "falsification": (
            "If fewer than 3 targets improve, dispatch is exposure evidence but not "
            "a sufficient v5 mechanism; do not make the builders unconditional."
        ),
    },
    {
        "order": 2,
        "id": "E2-wrapper-boundary-oracle",
        "hypothesis": (
            "Incorrect wrapper boundaries contaminate member spans and account for "
            "a material share of surface projection errors."
        ),
        "intervention": (
            "Inject gold wrapper boundaries only, then rerun unchanged connector, "
            "scope, attachment, and projection stages. This is an attribution "
            "oracle, not a proposed production implementation."
        ),
        "target_fixture_ids": [
            "structured-corpus-external-v1-001",
            "structured-corpus-external-v1-003",
            "structured-corpus-external-v1-004",
            "structured-corpus-external-v1-007",
            "structured-corpus-external-v1-008",
            "structured-corpus-external-v1-011",
            "structured-corpus-external-v1-016",
            "structured-corpus-external-v1-020",
        ],
        "control_fixture_ids": [
            "structured-corpus-external-v1-006",
            "structured-corpus-external-v1-017",
        ],
        "primary_outcomes": [
            "coordination-member F1",
            "shared-scope-edge F1",
            "surface projection exact count",
        ],
        "acceptance": (
            "At least 4/8 targets improve surface or member exactness and neither "
            "already wrapper-exact control regresses."
        ),
        "falsification": (
            "If downstream metrics do not improve, wrapper errors are correlated "
            "with, but are not causing, the member/projection failures."
        ),
    },
    {
        "order": 3,
        "id": "E3-region-first-connector-role-oracle",
        "hypothesis": (
            "Connector roles are wrong because splitting happens without protected "
            "wrapper, predicate, example, and quantifier regions."
        ),
        "intervention": (
            "Inject only the gold role for the nine misclassified connector tokens "
            "before member construction; retain predicted wrapper and scope spans."
        ),
        "target_fixture_ids": [
            "structured-corpus-external-v1-001",
            "structured-corpus-external-v1-003",
            "structured-corpus-external-v1-007",
            "structured-corpus-external-v1-010",
            "structured-corpus-external-v1-018",
            "structured-corpus-external-v1-019",
        ],
        "control_fixture_ids": [
            "structured-corpus-external-v1-008",
            "structured-corpus-external-v1-011",
        ],
        "primary_outcomes": [
            "coordination-member exact count",
            "example-attachment edge F1",
            "surface projection F1",
        ],
        "acceptance": (
            "At least 4/6 targets improve a downstream primary outcome and neither "
            "connector-correct control regresses."
        ),
        "falsification": (
            "If token roles become correct but members do not improve, member "
            "boundary construction is an independent failure mechanism."
        ),
    },
    {
        "order": 4,
        "id": "E4-scope-candidate-versus-application",
        "hypothesis": (
            "v4 conflates finding a possible trailing head with proving that the "
            "head distributes over multiple members."
        ),
        "intervention": (
            "With wrapper and member boundaries held to gold as nuisance controls, "
            "compare topology-only scope application against a member-head "
            "compatibility decision."
        ),
        "target_fixture_ids": [
            "structured-corpus-external-v1-011",
            "structured-corpus-external-v1-012",
            "structured-corpus-external-v1-016",
            "structured-corpus-external-v1-017",
            "structured-corpus-external-v1-018",
            "structured-corpus-external-v1-020",
        ],
        "control_fixture_ids": [
            "structured-corpus-external-v1-006",
            "structured-corpus-external-v1-013",
        ],
        "primary_outcomes": [
            "shared-scope edge exact count",
            "false shared-scope edge count",
            "surface projection exact count",
        ],
        "acceptance": (
            "The compatibility condition must distinguish the 017/020 minimal pair, "
            "avoid a scope on singleton 016, and improve at least 4/6 targets with "
            "no control regression."
        ),
        "falsification": (
            "Failure on the 017/020 pair means topology-only deterministic scope "
            "rules are underidentified; do not add another terminal-token rule."
        ),
    },
    {
        "order": 5,
        "id": "E5-example-attachment-three-toggle",
        "hypothesis": (
            "The three attachment failures come from separable cue-boundary, "
            "category-gating, and parent-ranking mechanisms."
        ),
        "intervention": (
            "Apply three toggles in sequence: strip the introductory list cue, "
            "enable category-neutral topology detection, then rank right-local and "
            "previous-segment parent candidates."
        ),
        "target_fixture_ids": [
            "structured-corpus-external-v1-002",
            "structured-corpus-external-v1-005",
            "structured-corpus-external-v1-019",
        ],
        "control_fixture_ids": [
            "structured-corpus-external-v1-006",
            "structured-corpus-external-v1-018",
        ],
        "primary_outcomes": [
            "example member exact count",
            "attachment parent exact count",
            "attachment edge F1",
            "example projection F1",
        ],
        "acceptance": (
            "Toggle 1 fixes example spans in 002/005, toggle 2 discovers 019 "
            "without changing controls, and toggle 3 makes all three parents and "
            "edges exact."
        ),
        "falsification": (
            "A toggle that changes unrelated layers or fails its designated case is "
            "not isolated and must not be merged into v5."
        ),
    },
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _routing(record: dict[str, Any]) -> str:
    rules = record["v4_prediction"]["rule_ids"]
    if any(rule.startswith("fallback.") for rule in rules):
        return "fallback_translation"
    return "v4_native"


def _failed_layers(record: dict[str, Any]) -> list[str]:
    return [
        layer
        for layer in DIFFERENCE_LAYERS
        if not record["evaluation_differences"][layer]["exact"]
    ]


def _layer_summary(fixtures: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for layer in DIFFERENCE_LAYERS:
        differences = [item["evaluation_differences"][layer] for item in fixtures]
        exact_count = sum(item["exact"] for item in differences)
        result[layer] = {
            "fixture_count": len(differences),
            "exact_fixture_count": exact_count,
            "failed_fixture_count": len(differences) - exact_count,
            "missing_count": sum(len(item["missing"]) for item in differences),
            "unexpected_count": sum(
                len(item["unexpected"]) for item in differences
            ),
        }
    return result


def _connector_summary(fixtures: list[dict[str, Any]]) -> dict[str, Any]:
    confusion: Counter[str] = Counter()
    failed_fixture_ids: list[str] = []
    correct = 0
    count = 0
    for fixture in fixtures:
        result = fixture["connector_classification"]
        correct += result["correct"]
        count += result["count"]
        confusion.update(result["confusion"])
        if result["accuracy"] < 1.0:
            failed_fixture_ids.append(fixture["id"])
    return {
        "correct": correct,
        "count": count,
        "accuracy": correct / count,
        "error_count": count - correct,
        "failed_fixture_count": len(failed_fixture_ids),
        "failed_fixture_ids": failed_fixture_ids,
        "confusion": dict(sorted(confusion.items())),
    }


def _cluster(
    *,
    cluster_id: str,
    title: str,
    fixture_ids: list[str],
    fixtures_by_id: dict[str, dict[str, Any]],
    observation: str,
    causal_interpretation: str,
    competing_explanation: str,
) -> dict[str, Any]:
    return {
        "id": cluster_id,
        "title": title,
        "fixture_count": len(fixture_ids),
        "fixture_ids": fixture_ids,
        "category_counts": dict(
            sorted(Counter(fixtures_by_id[x]["category"] for x in fixture_ids).items())
        ),
        "observation": observation,
        "causal_interpretation": causal_interpretation,
        "competing_explanation": competing_explanation,
    }


def _case_summary(fixture: dict[str, Any]) -> dict[str, Any]:
    surface = fixture["evaluation_differences"]["surface_projection"]
    examples = fixture["evaluation_differences"]["example_projection"]
    return {
        "id": fixture["id"],
        "job_id": fixture["job_id"],
        "category": fixture["category"],
        "source_text": fixture["gold"]["source_text"],
        "routing": _routing(fixture),
        "rule_ids": fixture["v4_prediction"]["rule_ids"],
        "failed_layers": _failed_layers(fixture),
        "connector_confusion": fixture["connector_classification"]["confusion"],
        "gold_surface_items": fixture["gold"]["projection"]["surface_items"],
        "predicted_surface_items": fixture["v4_prediction"]["items"],
        "surface_missing": surface["missing"],
        "surface_unexpected": surface["unexpected"],
        "gold_examples": fixture["gold"]["projection"]["examples"],
        "predicted_examples": fixture["v4_prediction"]["examples"],
        "example_missing": examples["missing"],
        "example_unexpected": examples["unexpected"],
    }


def build_analysis(dataset: dict[str, Any]) -> dict[str, Any]:
    fixtures = dataset["fixtures"]
    fixtures_by_id = {item["id"]: item for item in fixtures}
    if len(fixtures_by_id) != 20:
        raise ValueError("expected 20 unique revealed fixtures")

    layer_summary = _layer_summary(fixtures)
    connector_summary = _connector_summary(fixtures)
    fallback_ids = [
        item["id"] for item in fixtures if _routing(item) == "fallback_translation"
    ]
    native_ids = [item["id"] for item in fixtures if _routing(item) == "v4_native"]
    wrapper_failure_ids = [
        item["id"]
        for item in fixtures
        if not item["evaluation_differences"]["wrappers"]["exact"]
    ]
    scope_failure_ids = [
        item["id"]
        for item in fixtures
        if not item["evaluation_differences"]["shared_scope_edges"]["exact"]
    ]
    attachment_failure_ids = [
        item["id"]
        for item in fixtures
        if not (
            item["evaluation_differences"]["example_attachment_parents"]["exact"]
            and item["evaluation_differences"]["example_attachment_edges"]["exact"]
        )
    ]
    surface_failure_ids = [
        item["id"]
        for item in fixtures
        if not item["evaluation_differences"]["surface_projection"]["exact"]
    ]
    projection_only_ids = [
        item["id"]
        for item in fixtures
        if item["id"] in surface_failure_ids
        and item["connector_classification"]["accuracy"] == 1.0
        and all(
            item["evaluation_differences"][layer]["exact"]
            for layer in DIFFERENCE_LAYERS
            if layer not in {"surface_projection", "example_projection"}
        )
    ]

    expected_counts = {
        "fallback": 16,
        "native": 4,
        "wrapper_failures": 18,
        "scope_failures": 15,
        "attachment_failures": 3,
        "surface_failures": 19,
        "projection_only_failures": 0,
        "connector_error_fixtures": 6,
        "connector_errors": 9,
    }
    actual_counts = {
        "fallback": len(fallback_ids),
        "native": len(native_ids),
        "wrapper_failures": len(wrapper_failure_ids),
        "scope_failures": len(scope_failure_ids),
        "attachment_failures": len(attachment_failure_ids),
        "surface_failures": len(surface_failure_ids),
        "projection_only_failures": len(projection_only_ids),
        "connector_error_fixtures": connector_summary["failed_fixture_count"],
        "connector_errors": connector_summary["error_count"],
    }
    if actual_counts != expected_counts:
        raise ValueError(f"revealed evidence drifted: {actual_counts}")

    scope_missing_only = []
    scope_unexpected_only = []
    scope_mixed = []
    for fixture_id in scope_failure_ids:
        result = fixtures_by_id[fixture_id]["evaluation_differences"][
            "shared_scope_edges"
        ]
        if result["missing"] and not result["unexpected"]:
            scope_missing_only.append(fixture_id)
        elif result["unexpected"] and not result["missing"]:
            scope_unexpected_only.append(fixture_id)
        else:
            scope_mixed.append(fixture_id)

    clusters = [
        _cluster(
            cluster_id="C1-conditional-upgrade-bypass",
            title="Most clauses never enter native v4 logic",
            fixture_ids=fallback_ids,
            fixtures_by_id=fixtures_by_id,
            observation=(
                "16/20 predictions expose only fallback.* rule IDs; all 16 have a "
                "surface projection error."
            ),
            causal_interpretation=(
                "v4 is a gated patch layer over v3 rather than one shared structured "
                "pipeline, so unseen clause shapes bypass the intended mechanisms."
            ),
            competing_explanation=(
                "Forcing entry may still fail because the category builders contain "
                "their own boundary assumptions; E1 tests sufficiency."
            ),
        ),
        _cluster(
            cluster_id="C2-wrapper-boundary-undercoverage",
            title="Wrapper boundaries contaminate projected item spans",
            fixture_ids=wrapper_failure_ids,
            fixtures_by_id=fixtures_by_id,
            observation=(
                "Wrapper matching fails on 18/20 fixtures across all four categories; "
                "missed action, qualification, and list-introduction spans remain in "
                "predicted items."
            ),
            causal_interpretation=(
                "Coordination and projection consume spans before predicate/body and "
                "qualification boundaries are consistently resolved."
            ),
            competing_explanation=(
                "Wrapper mismatch may be incidental when downstream member spans are "
                "independently constructed; the wrapper oracle in E2 measures this."
            ),
        ),
        _cluster(
            cluster_id="C3-connector-role-without-regions",
            title="Flat connector scanning confuses four structural roles",
            fixture_ids=connector_summary["failed_fixture_ids"],
            fixtures_by_id=fixtures_by_id,
            observation=(
                "Nine connector tokens are wrong in six fixtures: four surface tokens "
                "are missed, two embedded, two example, and one quantifier token are "
                "classified as surface."
            ),
            causal_interpretation=(
                "Connector role is being decided without stable wrapper, predicate, "
                "example, and quantifier regions."
            ),
            competing_explanation=(
                "Correct roles may not fix contaminated member boundaries; E3 tracks "
                "downstream changes rather than accepting role accuracy by construction."
            ),
        ),
        _cluster(
            cluster_id="C4-scope-candidate-application-conflation",
            title="Scope detection strips heads before proving distribution",
            fixture_ids=scope_failure_ids,
            fixtures_by_id=fixtures_by_id,
            observation=(
                "Shared-scope edges fail on 15/20 fixtures: seven missing-only, four "
                "unexpected-only, and four with both missing and unexpected edges."
            ),
            causal_interpretation=(
                "A terminal head such as ability or experience is treated as shared "
                "scope too early, while legitimate prefix/result/evidence scopes are "
                "often absent."
            ),
            competing_explanation=(
                "The 017/020 pair is underidentified by punctuation alone and may "
                "require member-head compatibility rather than another span heuristic."
            ),
        ),
        _cluster(
            cluster_id="C5-example-attachment-not-clause-graph",
            title="Example attachment is local-tail and category gated",
            fixture_ids=attachment_failure_ids,
            fixtures_by_id=fixtures_by_id,
            observation=(
                "All three attachment-bearing failures are 002, 005, and 019. The "
                "first two retain the list-introduction cue in example 1; 005 selects "
                "a generic right tail instead of the previous segment, and 019 is not "
                "detected in capability."
            ),
            causal_interpretation=(
                "Cue normalization, category-neutral detection, and clause-level "
                "parent selection are three separate mechanisms."
            ),
            competing_explanation=(
                "A single expanded regex could fit these cases but would not identify "
                "which of the three mechanisms transfers."
            ),
        ),
    ]

    counterexamples = []
    for spec in COUNTEREXAMPLE_SPECS:
        counterexamples.append(
            {
                **spec,
                "cases": [
                    {
                        "id": fixture_id,
                        "category": fixtures_by_id[fixture_id]["category"],
                        "source_text": fixtures_by_id[fixture_id]["gold"][
                            "source_text"
                        ],
                    }
                    for fixture_id in spec["fixture_ids"]
                ],
            }
        )

    return {
        "analysis_version": (
            "unified-jd-structured-span-v4-revealed-error-analysis-v1"
        ),
        "created_at": "2026-09-04",
        "scope": {
            "status": "revealed_development_diagnosis_only",
            "fixture_count": len(fixtures),
            "generalization_claim": False,
            "threshold_selection_allowed": False,
            "parser_modified": False,
            "parser_executed": False,
            "model_call_count": 0,
            "network_call_count": 0,
        },
        "inputs": {
            "revealed_development": {
                "path": DATASET_PATH.relative_to(PROJECT_ROOT).as_posix(),
                "sha256": EXPECTED_DATASET_SHA256,
            },
            "reveal_receipt": {
                "path": REVEAL_RECEIPT_PATH.relative_to(PROJECT_ROOT).as_posix(),
                "sha256": EXPECTED_REVEAL_RECEIPT_SHA256,
            },
            "frozen_v4_parser": {
                "path": PARSER_PATH.relative_to(PROJECT_ROOT).as_posix(),
                "sha256": EXPECTED_PARSER_SHA256,
            },
        },
        "baseline_metrics": dataset["v4_baseline"]["metrics"],
        "layer_summary": layer_summary,
        "routing_summary": {
            "fallback_translation_count": len(fallback_ids),
            "fallback_translation_fixture_ids": fallback_ids,
            "native_v4_count": len(native_ids),
            "native_v4_fixture_ids": native_ids,
        },
        "connector_summary": connector_summary,
        "scope_failure_modes": {
            "missing_only": scope_missing_only,
            "unexpected_only": scope_unexpected_only,
            "missing_and_unexpected": scope_mixed,
        },
        "dependency_finding": {
            "surface_failure_count": len(surface_failure_ids),
            "surface_failure_fixture_ids": surface_failure_ids,
            "projection_only_failure_count": len(projection_only_ids),
            "projection_only_fixture_ids": projection_only_ids,
            "conclusion": (
                "Every surface projection failure co-occurs with an upstream wrapper, "
                "connector, member, scope, or attachment error. There is no evidence "
                "for starting the canonicalizer before structural repair."
            ),
        },
        "root_cause_clusters": clusters,
        "minimal_counterexample_pairs": counterexamples,
        "causal_experiment_plan": list(EXPERIMENT_SPECS),
        "decision": {
            "next_action": (
                "Run E1 through E5 on this revealed development set, one intervention "
                "at a time, and record rejected as well as accepted hypotheses."
            ),
            "v5_implementation_allowed": False,
            "v5_implementation_condition": (
                "At least one isolated mechanism must satisfy its predeclared "
                "acceptance condition without control regression."
            ),
            "canonicalizer_allowed": False,
            "new_holdout_required_after_v5_freeze": True,
        },
        "case_summaries": [_case_summary(item) for item in fixtures],
    }


def render_findings(analysis: dict[str, Any]) -> str:
    layer_summary = analysis["layer_summary"]
    connector = analysis["connector_summary"]
    lines = [
        "# Structured span v4 revealed-error diagnosis",
        "",
        "## Scope",
        "",
        "- These 20 jobs are revealed development data, not a holdout.",
        "- Frozen v4 was neither modified nor executed for this analysis.",
        "- No model or network calls were made.",
        "- This report supports diagnosis and experiment design only, not a generalization claim.",
        "",
        "## Main finding",
        "",
        (
            "The primary failure is architectural coverage, not a missing isolated "
            "constraint. **16/20 clauses expose only `fallback.*` rules**, so most "
            "external shapes never enter native v4 logic. Wrapper boundaries then "
            "fail on 18/20 clauses, and scope edges fail on 15/20."
        ),
        "",
        (
            "There are **zero projection-only failures**: every one of the 19 surface "
            "projection failures co-occurs with an upstream structural error. Starting "
            "the canonicalizer now would hide parser defects rather than isolate a new "
            "problem."
        ),
        "",
        "## Evidence summary",
        "",
        "| Layer | Exact fixtures | Failed fixtures | Missing | Unexpected |",
        "|---|---:|---:|---:|---:|",
    ]
    for layer in DIFFERENCE_LAYERS:
        item = layer_summary[layer]
        lines.append(
            f"| `{layer}` | {item['exact_fixture_count']} | "
            f"{item['failed_fixture_count']} | {item['missing_count']} | "
            f"{item['unexpected_count']} |"
        )
    errors = {
        key: value
        for key, value in connector["confusion"].items()
        if key.split("->")[0] != key.split("->")[1]
    }
    lines.extend(
        [
            "",
            (
                f"Connector classification has {connector['error_count']} token errors "
                f"in {connector['failed_fixture_count']} fixtures: "
                + ", ".join(f"`{key}`={value}" for key, value in errors.items())
                + "."
            ),
            "",
            "## Root-cause clusters",
            "",
        ]
    )
    for cluster in analysis["root_cause_clusters"]:
        lines.extend(
            [
                f"### {cluster['id']}: {cluster['title']}",
                "",
                f"Affected: {cluster['fixture_count']}/20 fixtures.",
                "",
                f"Observation: {cluster['observation']}",
                "",
                f"Interpretation: {cluster['causal_interpretation']}",
                "",
                f"Competing explanation: {cluster['competing_explanation']}",
                "",
            ]
        )
    lines.extend(["## Minimal counterexample pairs", ""])
    for pair in analysis["minimal_counterexample_pairs"]:
        ids = " vs ".join(f"`{x}`" for x in pair["fixture_ids"])
        lines.extend(
            [
                (
                    f"- **{pair['id']}** ({ids}): "
                    f"{pair['controlled_contrast']} {pair['inference']}"
                ),
                "",
            ]
        )
    lines.extend(
        [
            "## Causal experiment order",
            "",
            "| Order | Experiment | Targets | Controls | Acceptance |",
            "|---:|---|---:|---:|---|",
        ]
    )
    for experiment in analysis["causal_experiment_plan"]:
        lines.append(
            f"| {experiment['order']} | `{experiment['id']}` | "
            f"{len(experiment['target_fixture_ids'])} | "
            f"{len(experiment['control_fixture_ids'])} | "
            f"{experiment['acceptance']} |"
        )
    lines.extend(
        [
            "",
            (
                "Each intervention must be run and recorded separately. Oracle "
                "experiments attribute error; their use of gold boundaries is not a "
                "production design."
            ),
            "",
            "## Decision",
            "",
            (
                "Do not implement v5 yet. First run E1-E5 and retain only mechanisms "
                "that meet their predeclared acceptance condition without control "
                "regression. After v5 is implemented and frozen, evaluate it once on "
                "a newly collected external holdout that excludes these 20 jobs. The "
                "canonicalizer remains blocked until that gate passes."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    expected_hashes = {
        DATASET_PATH: EXPECTED_DATASET_SHA256,
        REVEAL_RECEIPT_PATH: EXPECTED_REVEAL_RECEIPT_SHA256,
        PARSER_PATH: EXPECTED_PARSER_SHA256,
    }
    for path, expected in expected_hashes.items():
        actual = _sha256(path)
        if actual != expected:
            raise ValueError(f"frozen input changed: {path}: {actual} != {expected}")

    dataset = _load(DATASET_PATH)
    if dataset["status"] != "revealed_corpus_external_development_only":
        raise ValueError("dataset is not eligible for revealed-development analysis")
    analysis = build_analysis(dataset)
    _write_json(OUTPUT_PATH, analysis)
    FINDINGS_PATH.write_text(render_findings(analysis), encoding="utf-8")
    print(f"wrote {OUTPUT_PATH.relative_to(PROJECT_ROOT)}")
    print(f"wrote {FINDINGS_PATH.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
