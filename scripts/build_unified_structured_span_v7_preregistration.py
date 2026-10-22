from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATE = "2026-09-05"

E9_RAW_PATH = (
    ROOT / "artifacts/evaluation/"
    "unified-jd-structured-span-v6-e9-region-versus-node-family-merge-oracle-raw-v1-2026-09-05.json"
)
E9_REPORT_PATH = (
    ROOT / "artifacts/evaluation/"
    "unified-jd-structured-span-v6-e9-region-versus-node-family-merge-oracle-report-v1-2026-09-05.json"
)
E9_PREREGISTRATION_PATH = (
    ROOT / "datasets/"
    "unified_jd_structured_span_v6_residual_oracles_preregistration_v1_2026-09-05.json"
)
E9_RECEIPT_PATH = (
    ROOT / "datasets/"
    "unified_jd_structured_span_v6_residual_oracles_evaluation_receipt_v1_2026-09-05.json"
)
V6_REGRESSION_RAW_PATH = (
    ROOT / "artifacts/evaluation/"
    "unified-jd-structured-span-v6-regression-raw-v1-2026-09-05.json"
)
V6_REPORT_PATH = (
    ROOT / "artifacts/evaluation/"
    "unified-jd-structured-span-v6-development-regression-report-v1-2026-09-05.json"
)
V6_MECHANISM_RAW_PATH = (
    ROOT / "artifacts/evaluation/"
    "unified-jd-structured-span-v6-mechanism-development-raw-v1-2026-09-05.json"
)
V5_PREREGISTRATION_PATH = (
    ROOT / "datasets/unified_jd_structured_span_v5_preregistration_v1_2026-09-04.json"
)
V5_MECHANISM_RAW_PATH = (
    ROOT / "artifacts/evaluation/"
    "unified-jd-structured-span-v5-mechanism-development-v5-raw-v1-2026-09-05.json"
)
V5_REPORT_PATH = (
    ROOT / "artifacts/evaluation/"
    "unified-jd-structured-span-v5-development-regression-report-v1-2026-09-05.json"
)
V6_PREREGISTRATION_PATH = (
    ROOT / "datasets/unified_jd_structured_span_v6_preregistration_v1_2026-09-05.json"
)
V6_SOURCE_FREEZE_PATH = (
    ROOT / "datasets/unified_jd_structured_span_v6_source_freeze_v1_2026-09-05.json"
)
V4_PATH = ROOT / "src/domain/unified_jd_structured_spans_v4.py"
V5_PATH = ROOT / "src/domain/unified_jd_structured_spans_v5.py"
V6_PATH = ROOT / "src/domain/unified_jd_structured_spans_v6.py"
V7_PATH = ROOT / "src/domain/unified_jd_structured_spans_v7.py"

ANALYSIS_PATH = (
    ROOT / "artifacts/evaluation/"
    "unified-jd-structured-span-v6-e9-runtime-signal-analysis-v1-2026-09-05.json"
)
ANALYSIS_FINDINGS_PATH = (
    ROOT / "artifacts/evaluation/"
    "unified-jd-structured-span-v6-e9-runtime-signal-analysis-findings-v1-2026-09-05.md"
)
PREREGISTRATION_PATH = (
    ROOT / "datasets/unified_jd_structured_span_v7_preregistration_v1_2026-09-05.json"
)
PREREGISTRATION_FINDINGS_PATH = (
    ROOT / "artifacts/evaluation/"
    "unified-jd-structured-span-v7-preregistration-findings-v1-2026-09-05.md"
)
FREEZE_PATH = (
    ROOT
    / "datasets/unified_jd_structured_span_v7_preregistration_freeze_v1_2026-09-05.json"
)

FROZEN_INPUT_HASHES = {
    E9_RAW_PATH: "496310332f5abbb4cf8a242be7d07c59262e144632fdc261734897d3bcdaf781",
    E9_REPORT_PATH: "e07b31f2ac2ef91e680ca145fdf29dbfdab144fcd418f5a2faaf04940ee74afa",
    E9_PREREGISTRATION_PATH: "1c5ebe4ff6b12824a2e2ae1dc71e2618509755875c80a95b0cabda41e91a5a23",
    E9_RECEIPT_PATH: "32fddf710894956873a171abbd338ce7c0068ad63367c469e4c6dd1fa9a90cd4",
    V6_REGRESSION_RAW_PATH: "65bade675974b9aba1c1089ba77c7d4e3144a6275d2e288bb80fcf4fd86f830b",
    V6_REPORT_PATH: "65a23a95a5fd812fbffbef9e8285cf70f29fa87b0fdf3ade42dec07dfeaefb5d",
    V6_MECHANISM_RAW_PATH: "335faa4cfee4620f6ce11d81f919cb16677396e331dd489cb14ef19ee0c38a54",
    V5_PREREGISTRATION_PATH: "55a5cf715888a810de0a3ebff5ae3dfa6d194a422dc6ea02070791021bdf76c8",
    V5_MECHANISM_RAW_PATH: "56f51ec6a54c0135478d22f9823373c67255e59fc5d90976fe9bed74bf9ec7ae",
    V5_REPORT_PATH: "a1a82413a355de58c7e765ec3fd7799cd479657377d04854be401f9bac531d01",
    V6_PREREGISTRATION_PATH: "c2298897d55d8859dff97f9f504ae3bf947daade353a7ea69b1c27527cbdbe99",
    V6_SOURCE_FREEZE_PATH: "3e6a380b4ec91abc48fcd3f813bc4d83b8044b31990074b90f758e32639654e3",
    V4_PATH: "e09e056cab75e651937391ce5410e6df7c94477c85565abb1425bbe85cfcb094",
    V5_PATH: "8abdb1df73af8731caf565d0f0c74ad824302bf99cdae2b1c6a4e2e13ad541da",
    V6_PATH: "960d0d49f1c0b6b9fece8645ca5edc0a5874cf9ffb250e2f6c780cfcde11ccfd",
}

# These ids are evidence addresses in the frozen E9 audit only. They are never
# serialized into the v7 runtime mechanism or permitted in implementation.
OFFLINE_SIGNAL_BY_SWITCH = {
    (
        "surface-holdout-v1-004",
        "example_projection",
    ): "S1-implicit-enumeration-partition-conflict",
    (
        "surface-holdout-v1-004",
        "surface_projection",
    ): "S1-implicit-enumeration-partition-conflict",
    (
        "surface-holdout-v1-006",
        "example_projection",
    ): "S1-implicit-enumeration-partition-conflict",
    (
        "surface-holdout-v1-006",
        "surface_projection",
    ): "S1-implicit-enumeration-partition-conflict",
    (
        "surface-holdout-v2-019",
        "example_projection",
    ): "S1-implicit-enumeration-partition-conflict",
    (
        "surface-holdout-v2-019",
        "surface_projection",
    ): "S1-implicit-enumeration-partition-conflict",
    (
        "surface-holdout-v1-001",
        "surface_projection",
    ): "S2-atomic-surface-conservation-conflict",
    (
        "surface-holdout-v1-003",
        "surface_projection",
    ): "S2-atomic-surface-conservation-conflict",
    (
        "surface-holdout-v1-005",
        "surface_projection",
    ): "S2-atomic-surface-conservation-conflict",
    (
        "surface-holdout-v1-017",
        "surface_projection",
    ): "S2-atomic-surface-conservation-conflict",
    (
        "surface-holdout-v2-002",
        "surface_projection",
    ): "S2-atomic-surface-conservation-conflict",
    (
        "structured-external-v1-014",
        "example_attachment_edges",
    ): "S3-cross-coordination-attachment-bundle-conflict",
    (
        "structured-external-v1-014",
        "example_attachment_parents",
    ): "S3-cross-coordination-attachment-bundle-conflict",
    (
        "structured-external-v1-014",
        "item_candidate_spans",
    ): "S3-cross-coordination-attachment-bundle-conflict",
    (
        "structured-external-v1-014",
        "shared_scope_edges",
    ): "S3-cross-coordination-attachment-bundle-conflict",
    (
        "structured-external-v1-014",
        "surface_projection",
    ): "S3-cross-coordination-attachment-bundle-conflict",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _serialized(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _write_new(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as output:
        output.write(content)


def _canonical_sha256(payload: Any) -> str:
    value = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _input_references() -> dict[str, dict[str, str]]:
    return {
        path.stem: {"path": _relative(path), "sha256": expected_hash}
        for path, expected_hash in FROZEN_INPUT_HASHES.items()
    }


def _source_lookup(regression_raw: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for cohort in ("legacy_development", "revealed_external", "projection_60"):
        for record in regression_raw[cohort]["records"]:
            result[record["id"]] = record["source_text"]
    return result


def _projection_texts(payload: dict[str, Any], family: str) -> list[str]:
    if family not in {"surface_projection", "example_projection"}:
        return []
    return [item[0] for item in payload[family]]


def _validate_inputs() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    for path, expected_hash in FROZEN_INPUT_HASHES.items():
        actual_hash = _sha256(path)
        if actual_hash != expected_hash:
            raise ValueError(
                f"frozen input hash mismatch for {_relative(path)}: "
                f"expected {expected_hash}, got {actual_hash}"
            )
    outputs = (
        ANALYSIS_PATH,
        ANALYSIS_FINDINGS_PATH,
        PREREGISTRATION_PATH,
        PREREGISTRATION_FINDINGS_PATH,
        FREEZE_PATH,
    )
    for path in outputs:
        if path.exists():
            raise FileExistsError(f"output already exists: {_relative(path)}")
    if V7_PATH.exists():
        raise FileExistsError("v7 implementation exists before preregistration freeze")

    e9_raw = _load(E9_RAW_PATH)
    e9_report = _load(E9_REPORT_PATH)
    regression_raw = _load(V6_REGRESSION_RAW_PATH)
    actual_switches = {
        (record["id"], family)
        for record in e9_raw["records"]
        for family in record["baseline_mismatched_families"]
    }
    if actual_switches != set(OFFLINE_SIGNAL_BY_SWITCH):
        raise ValueError(
            "offline signal map does not cover the frozen 16 switches exactly"
        )
    if not e9_report["accepted"]:
        raise ValueError("E9 did not pass its preregistered gate")
    if e9_report["changed_family_count"]["node_family_changed"] != 16:
        raise ValueError("E9 changed-family count is not 16")
    if e9_report["changed_family_count"]["node_family_retained_v6"] != 9:
        raise ValueError("E9 retained-family count is not 9")
    return e9_raw, e9_report, regression_raw


def _signal_definitions() -> list[dict[str, Any]]:
    return [
        {
            "id": "S1-implicit-enumeration-partition-conflict",
            "name": "Implicit enumeration partition conflict",
            "switch_count": 6,
            "observable_inputs": [
                "source characters and half-open offsets",
                "frozen v4 surface-producing spans",
                "frozen v6 attachment cue, example, parent, and surface-producing spans",
                "wrapper-marker spans already emitted by either frozen graph",
            ],
            "runtime_predicate": {
                "all_required": [
                    "A frozen-v6 attachment has an unprotected implicit cue whose source text is exactly the terminal enumeration marker deng and has at least two example members.",
                    "The cue envelope has no explicit example introducer such as ru, liru, or a protected parenthetical example cue.",
                    "After subtracting only graph-declared wrapper-marker prefixes, the ordered frozen-v4 surface spans form a non-overlapping partition of the same pre-cue source envelope covered by the frozen-v6 example spans.",
                    "At least one partition span is absent from frozen-v6 surface-producing nodes, so the delta is a role transfer rather than a strictly additive attachment.",
                ],
                "normalization_forbidden": "No item text canonicalization, token synonym table, or expected-output comparison; compare source offsets, coverage, order, and containment only.",
            },
            "causal_interpretation": "V6 has promoted an uncued surface enumeration into an example attachment even though the older surface partition still covers the source envelope.",
            "allowed_route": "Use the frozen-v4 producer bundle for the implicated implicit-enumeration surface/example families; preserve unrelated frozen-v6 families.",
            "vetoes": [
                "Do not activate for an explicit source-anchored example cue.",
                "Do not activate for a protected parenthetical attachment.",
                "Do not activate unless coverage and partition conditions are both satisfied.",
            ],
            "evidence_limit": "The three positive records expose projection layers only, so E9 does not validate their unobserved attachment topology.",
        },
        {
            "id": "S2-atomic-surface-conservation-conflict",
            "name": "Atomic surface conservation conflict",
            "switch_count": 5,
            "observable_inputs": [
                "source characters and connector offsets",
                "frozen v4 and v6 surface-producing spans",
                "frozen v4 and v6 wrapper, connector-role, scope, and attachment spans",
            ],
            "runtime_predicate": {
                "all_required": [
                    "A source-anchored frozen-v4 surface atom has no exact frozen-v6 surface-producing span.",
                    "The mismatch is observable as strict enclosure, connector promotion into two or more v6 surface atoms, wrapper/operator contamination at the candidate boundary, or deletion into a non-surface family.",
                    "No explicit attachment cue or protected example attachment inside the minimal changed envelope accounts for the loss.",
                    "The v6 replacement is not a purely additive node that preserves the complete v4 atom as a surface producer.",
                ],
                "minimal_changed_envelope": "The smallest source interval containing the missing v4 atom and every overlapping v6 surface-producing span; a wrapper may license only its actual marker or structural-delta span, never its entire content span.",
                "normalization_forbidden": "No semantic lexicon, phrase rewrite, category branch, or gold projection comparison; use only span equality, overlap, containment, connector roles, and graph-declared markers.",
            },
            "causal_interpretation": "A region-level structural activation has overwritten a surface atom outside the topology that actually licensed the activation.",
            "allowed_route": "Use the frozen-v4 surface-producer family for the clause when any atom fails the compatibility predicate; keep example, wrapper, scope, and attachment families at their otherwise selected origins.",
            "vetoes": [
                "Do not activate when every v4 atom is exactly preserved by v6.",
                "Do not activate when an explicit source cue creates a source-covering attachment that explains the change.",
                "Do not treat a wrapper content span as blanket permission for changes outside the minimal structural-delta envelope.",
            ],
            "evidence_limit": "All five positive switches are surface projections; upstream graph correctness must be checked by validity and any available full-graph labels.",
        },
        {
            "id": "S3-cross-coordination-attachment-bundle-conflict",
            "name": "Cross-coordination attachment bundle conflict",
            "switch_count": 5,
            "observable_inputs": [
                "frozen v4 and v6 attachment cue, parent, and example spans",
                "frozen v6 surface connector and coordination-member spans",
                "frozen v4 and v6 item-candidate and shared-scope spans",
                "source-anchored wrapper or operator markers",
            ],
            "runtime_predicate": {
                "all_required": [
                    "V4 and v6 agree on an attachment cue and its ordered example spans.",
                    "The v6 attachment parent strictly crosses a connector labeled surface and contains at least two surface coordination members, while the v4 parent ends within one member before that connector.",
                    "A v6 residual item candidate begins at a source token that either frozen graph independently identifies as a wrapper or shared-scope operator boundary.",
                    "The candidate, scope, attachment-parent, and attachment-edge differences share one connected source-span component.",
                ],
                "normalization_forbidden": "No conference-name lexicon, source substring exception, category branch, or fixture lookup.",
            },
            "causal_interpretation": "The attachment parent overreaches a surface coordination boundary and the same boundary error strands an operator inside the residual candidate.",
            "allowed_route": "Atomically use frozen-v4 attachment parents, attachment edges, item candidates, shared scopes, and the derived surface projection for the connected component; keep v6 wrappers, connector labels, coordination members, and example projection.",
            "vetoes": [
                "Do not activate on parent-width difference alone.",
                "Do not activate without the surface-crossing parent and residual-operator conditions together.",
                "Reject the route if id rebasing cannot preserve every referenced member.",
            ],
            "evidence_limit": "This signal has one positive full-graph record; it is a preregistered hypothesis, not generalization evidence.",
        },
    ]


def _build_analysis(
    e9_raw: dict[str, Any],
    e9_report: dict[str, Any],
    regression_raw: dict[str, Any],
) -> dict[str, Any]:
    sources = _source_lookup(regression_raw)
    records: list[dict[str, Any]] = []
    switch_rows: list[dict[str, Any]] = []
    for record in e9_raw["records"]:
        record_switches: list[dict[str, str]] = []
        for family in record["baseline_mismatched_families"]:
            signal_id = OFFLINE_SIGNAL_BY_SWITCH[(record["id"], family)]
            row = {"family": family, "runtime_signal": signal_id}
            record_switches.append(row)
            switch_rows.append({"evidence_record_id": record["id"], **row})
        v6_payload = record["frozen_v6_region_level"]
        v4_payload = record["v4_whole_region_fallback_oracle"]
        records.append(
            {
                "evidence_record_id": record["id"],
                "source_text": sources[record["id"]],
                "prior_error_class": record["classification"],
                "switches": record_switches,
                "observable_contrast": {
                    "v4_only_surface_texts": sorted(
                        set(_projection_texts(v4_payload, "surface_projection"))
                        - set(_projection_texts(v6_payload, "surface_projection"))
                    ),
                    "v6_only_surface_texts": sorted(
                        set(_projection_texts(v6_payload, "surface_projection"))
                        - set(_projection_texts(v4_payload, "surface_projection"))
                    ),
                    "v4_only_example_texts": sorted(
                        set(_projection_texts(v4_payload, "example_projection"))
                        - set(_projection_texts(v6_payload, "example_projection"))
                    ),
                    "v6_only_example_texts": sorted(
                        set(_projection_texts(v6_payload, "example_projection"))
                        - set(_projection_texts(v4_payload, "example_projection"))
                    ),
                },
                "already_exact_v6_families_retained_by_e9": record[
                    "already_exact_v6_families"
                ],
            }
        )

    counts = Counter(row["runtime_signal"] for row in switch_rows)
    expected_counts = {
        signal["id"]: signal["switch_count"] for signal in _signal_definitions()
    }
    if dict(counts) != expected_counts:
        raise ValueError(f"runtime signal counts differ: {dict(counts)}")

    return {
        "analysis_version": "unified-jd-structured-span-v6-e9-runtime-signal-analysis-v1",
        "created_at": DATE,
        "status": "frozen_raw_offline_signal_extraction_for_v7_preregistration",
        "scope": {
            "data_status": "revealed_frozen_development_and_oracle_data",
            "e9_is_gold_directed": True,
            "runtime_selector_validated": False,
            "generalization_claim": False,
            "parser_executed": False,
            "model_call_count": 0,
            "network_call_count": 0,
            "v4_modified": False,
            "v5_modified": False,
            "v6_modified": False,
            "canonicalizer_work_performed": False,
        },
        "inputs": _input_references(),
        "frozen_e9_facts": {
            "target_record_count": len(e9_raw["records"]),
            "node_family_targets_exact": e9_report["resolved_target_count_by_arm"][
                "node_family_selection_oracle"
            ],
            "node_family_changed_count": e9_report["changed_family_count"][
                "node_family_changed"
            ],
            "already_exact_v6_family_count_retained": e9_report["changed_family_count"][
                "node_family_retained_v6"
            ],
            "control_count_byte_identical": e9_report["checks"][
                "controls_byte_identical_22_of_22"
            ]["actual"],
            "supported_claim": "Node-family granularity is sufficient under a gold-directed oracle.",
            "unsupported_claim": "E9 does not establish that any proposed runtime selector is correct.",
        },
        "mechanism_repartition": {
            "reason": "The previous R1/R3/R4 labels describe output symptoms. Runtime routing needs mutually exclusive graph-and-span predicates, so the 16 switches are repartitioned by observable mechanism.",
            "signal_count": 3,
            "switch_count": len(switch_rows),
            "counts_by_signal": dict(counts),
            "all_switches_assigned_exactly_once": len(switch_rows)
            == len({(row["evidence_record_id"], row["family"]) for row in switch_rows}),
        },
        "runtime_signal_candidates": _signal_definitions(),
        "switch_audit": switch_rows,
        "record_evidence": records,
        "cross_gate_constraint": {
            "frozen_v6_mechanism_20_exact_count": 2,
            "unchanged_v5_mechanism_20_required_exact_count": 20,
            "consequence": "A v7 that merely applies the 16 v4-directed switches on top of v6 is structurally incapable of satisfying the unchanged mechanism-preservation gate. V7 must also restore a v5 family only when every v5-v6 delta in that family is covered by the already-supported E2, E3, E6, or E7 runtime mechanism and no S1-S3 veto fires.",
        },
        "conclusion": "Three runtime-observable candidate signals account for all 16 E9 family switches without using gold or fixture metadata, but their selectors remain unvalidated until a separately frozen v7 implementation is run once through all unchanged gates.",
    }


def _build_preregistration(analysis: dict[str, Any]) -> dict[str, Any]:
    v5_preregistration = _load(V5_PREREGISTRATION_PATH)
    runtime_signals = [
        {
            key: value
            for key, value in signal.items()
            if key not in {"switch_count", "evidence_limit"}
        }
        for signal in analysis["runtime_signal_candidates"]
    ]
    plan = {
        "preregistration_version": "unified-jd-structured-span-v7-preregistration-v1",
        "created_at": DATE,
        "status": "frozen_before_v7_implementation",
        "scope": {
            "task": "runtime_observable_node_family_routing_only",
            "development_data_status": "all_selector_inputs_revealed_not_holdout",
            "generalization_claim": False,
            "v4_modification_allowed": False,
            "v5_modification_allowed": False,
            "v6_modification_allowed": False,
            "old_gate_or_threshold_modification_allowed": False,
            "new_parser_semantics_allowed": False,
            "fixture_specific_runtime_rules_allowed": False,
            "category_employer_title_or_source_specific_dispatch_allowed": False,
            "canonicalizer_work_allowed": False,
            "model_calls_allowed": False,
            "network_calls_allowed": False,
        },
        "inputs": {
            **_input_references(),
            "runtime_signal_analysis": {
                "path": _relative(ANALYSIS_PATH),
                "sha256": _sha256(ANALYSIS_PATH),
            },
        },
        "causal_basis": {
            "supported": [
                "E9 establishes that node-family selection is sufficient for 9/9 residual records while changing 16 inexact observable families and retaining 9 exact v6 families.",
                "The 16 switches can be partitioned into three source-and-graph-observable conflict signatures with counts 6, 5, and 5.",
                "The E2, E3, E6, and E7 mechanisms remain the only previously supported v5 activation mechanisms.",
            ],
            "not_supported": [
                "E9 is gold-directed and does not validate a deployable selector.",
                "Projection-only E9 records do not validate hidden wrapper, member, scope, or attachment topology.",
                "No evidence supports fixture, category, company, title, or long-source-substring dispatch.",
                "No evidence supports changing extraction text with a canonicalizer.",
            ],
            "known_gate_debt": {
                "frozen_v6_v5_mechanism_exact": "2/20",
                "unchanged_required_v5_mechanism_exact": "20/20",
                "decision": "The 20/20 gate remains mandatory. The 2/20 v6 result is a baseline measurement, never a new threshold.",
            },
        },
        "v7_mechanism": {
            "name": "runtime-observable-node-family-compatibility-router",
            "implementation_target": "src/domain/unified_jd_structured_spans_v7.py",
            "behavioral_baseline": "Frozen v6 is the default origin for every family. V7 may select frozen v5 only through supported-family restoration and frozen v4 only through S1, S2, or S3.",
            "frozen_components": [
                "src/domain/unified_jd_structured_spans_v4.py",
                "src/domain/unified_jd_structured_spans_v5.py",
                "src/domain/unified_jd_structured_spans_v6.py",
            ],
            "selection_unit": "A complete node family for one clause or the explicitly registered S3 referential-closure bundle; never an individual node chosen by expected correctness.",
            "observable_families": [
                "wrappers",
                "connector_labels",
                "coordination_members",
                "shared_scope_edges",
                "example_attachment_parents",
                "example_attachment_edges",
                "item_candidate_spans",
                "surface_projection",
                "example_projection",
            ],
            "ordered_stages": [
                {
                    "order": 1,
                    "name": "load_frozen_parse_candidates",
                    "rule": "For identical source_text and category inputs, obtain the frozen v4, v5, and v6 graphs without changing any frozen source. Category is passed to the parsers but may not be inspected by the router.",
                },
                {
                    "order": 2,
                    "name": "derive_source_graph_observables",
                    "rule": "Build exact-offset inventories of wrapper markers, connectors and roles, coordination members, scopes, attachment cues/parents/examples, item candidates, envelopes, partitions, and graph references. No gold, fixture metadata, normalized output string, model, or network input is available.",
                },
                {
                    "order": 3,
                    "name": "restore_supported_v5_families",
                    "rule": "For a family where v5 and v6 differ, select v5 only when every differing node is contained by an E2 wrapper-boundary, E3 innermost connector-role, E6 deictic-header priority-tail, or E7 prepositional-before-example envelope already frozen as supported, and no S1-S3 conflict predicate fires for that family. If even one delta is unlicensed, retain v6 for the complete family.",
                    "purpose": "Keep the unchanged v5 mechanism-development requirement at 20/20 rather than accepting frozen v6's failed 2/20 baseline.",
                },
                {
                    "order": 4,
                    "name": "apply_s1_implicit_enumeration_partition_conflict",
                    "rule": runtime_signals[0]["runtime_predicate"],
                    "route": runtime_signals[0]["allowed_route"],
                    "vetoes": runtime_signals[0]["vetoes"],
                },
                {
                    "order": 5,
                    "name": "apply_s2_atomic_surface_conservation_conflict",
                    "rule": runtime_signals[1]["runtime_predicate"],
                    "route": runtime_signals[1]["allowed_route"],
                    "vetoes": runtime_signals[1]["vetoes"],
                },
                {
                    "order": 6,
                    "name": "apply_s3_cross_coordination_attachment_bundle_conflict",
                    "rule": runtime_signals[2]["runtime_predicate"],
                    "route": runtime_signals[2]["allowed_route"],
                    "vetoes": runtime_signals[2]["vetoes"],
                },
                {
                    "order": 7,
                    "name": "apply_precedence_and_referential_closure",
                    "rule": "Resolve origins in the fixed order graph validity, S3 bundle, S1 role bundle, S2 surface family, supported v5 restoration, frozen v6 default. Rebase ids by exact source span and reject a non-closed route; never widen a selected source envelope to make references pass.",
                },
                {
                    "order": 8,
                    "name": "validate_and_project_once",
                    "rule": "Validate source anchoring, unique ids, reference closure, connector ownership, scope targets, and attachment edges, then derive both projections from the merged graph exactly once. Direct projection-list patching and canonicalization are forbidden.",
                },
            ],
            "runtime_signals": runtime_signals,
            "precedence": [
                "source anchoring, graph validity, and reference closure",
                "S3 cross-coordination attachment bundle conflict",
                "S1 implicit enumeration partition conflict",
                "S2 atomic surface conservation conflict",
                "supported E2/E3/E6/E7 v5-family restoration",
                "frozen v6 default",
            ],
            "runtime_prohibitions": [
                "fixture id, corpus id, file path, gold label, expected output, or error-class lookup",
                "category, employer, job title, URL, or company dispatch",
                "memorized long source substring or named-entity exception",
                "surface or example string canonicalization",
                "post-hoc threshold, precedence, signal, or family-bundle changes",
                "model or network calls",
            ],
        },
        "acceptance_gates": {
            "G0-frozen-input-and-validity": {
                "requirements": [
                    "Frozen v4, v5, and v6 source hashes match this preregistration.",
                    "Every v7 output parses, is source-anchored, has unique ids, and has no dangling scope or attachment reference.",
                    "Model and network call counts are zero.",
                ]
            },
            "G1-original-v5-G0-G6-unchanged": {
                "source": {
                    "path": _relative(V5_PREREGISTRATION_PATH),
                    "sha256": FROZEN_INPUT_HASHES[V5_PREREGISTRATION_PATH],
                    "json_pointer": "/development_acceptance_gates",
                    "canonical_sha256": _canonical_sha256(
                        v5_preregistration["development_acceptance_gates"]
                    ),
                },
                "requirement": "Run every original G0-G6 criterion with identical operators and numeric thresholds; all must pass.",
            },
            "G2-v5-mechanism-preservation": {
                "fixture_count": 20,
                "reference": {
                    "path": _relative(V5_MECHANISM_RAW_PATH),
                    "sha256": FROZEN_INPUT_HASHES[V5_MECHANISM_RAW_PATH],
                },
                "frozen_v6_baseline_exact_fixture_count": 2,
                "required_exact_fixture_count": 20,
                "requirement": "V7 must equal frozen v5 fixture-by-fixture on wrappers, connector roles, coordination members, shared scopes, attachment parents and edges, item candidates, and both projections for 20/20 fixtures.",
                "threshold_not_relaxed": True,
            },
            "G3-e9-residual-runtime-selection": {
                "target_record_count": 9,
                "required_exact_record_count": 9,
                "required_v4_directed_observable_family_count": 16,
                "required_retained_exact_v6_family_count": 9,
                "requirements": [
                    "Every target is exact on every frozen layer available for its cohort.",
                    "All 16 E9-inexact observable families equal their frozen v4-compatible references.",
                    "All 9 already-exact v6 observable families remain byte-identical to frozen v6.",
                    "The recorded selector trace uses only S1, S2, S3, supported-v5 restoration, and default-v6 decisions.",
                ],
                "projection_only_limit": "Hidden topology on projection-only records is judged only by G0 validity, not claimed exact without labels.",
            },
            "G4-v6-resolved-control-preservation": {
                "control_count": 22,
                "required_exact_count": 22,
                "required_byte_identical_to_v6_count": 22,
                "requirement": "All 22 controls from the frozen E9 preregistration remain exact and byte-identical to frozen v6 on every observable family.",
            },
            "G5-legacy-effective-exact": {
                "fixture_count": 20,
                "required_exact_fixture_count": 20,
                "requirement": "Effective 20/20 exactness on every structural and projection layer using only the already-frozen same-character offset adjudication; no runtime exception.",
            },
            "G6-projection-regression-exact": {
                "fixture_count": 60,
                "required_exact_fixture_count": 60,
                "requirement": "60/60 exact on surface and example projections under the existing evaluator.",
            },
            "G7-revealed-external-non-regression": {
                "fixture_count": 20,
                "requirements": [
                    "Every aggregate primary-layer metric is no worse than frozen v4 and no worse than frozen v6.",
                    "Every per-fixture primary-layer difference count is no greater than both frozen v4 and frozen v6.",
                    "The known open-list wrapper regression remains zero.",
                ],
            },
            "G8-tests-and-selector-audit": {
                "requirements": [
                    "All existing structured-span tests pass unchanged.",
                    "New synthetic tests exercise every required predicate and every veto for S1-S3 plus supported-v5 restoration.",
                    "A static audit finds no runtime reference to fixture ids, corpus paths, gold, expected outputs, categories, employers, titles, URLs, or long source literals.",
                    "The selector trace is deterministic and records signal, family, source envelope, origin, and veto outcome without recording gold.",
                ]
            },
        },
        "evaluation_protocol": {
            "all_criteria_conjunctive": True,
            "threshold_or_operator_change_after_freeze_allowed": False,
            "source_freeze_before_any_v7_fixture_execution": True,
            "preflight_must_not_import_or_execute_v7": True,
            "raw_written_before_report": True,
            "write_new_outputs_only": True,
            "v7_development_run_count": 1,
            "v7_regression_run_count": 1,
            "rerun_after_failure_allowed": False,
            "failure_policy": "Freeze failed raw and report. Do not modify or rerun v7, change a selector, add an exception, or weaken a gate; diagnose offline and preregister a new version.",
        },
        "post_gate_protocol": {
            "on_pass": "Freeze v7 source and one-time results, then preregister and collect a fresh corpus-external blind holdout with no source, job, URL, employer-selection, or annotation overlap with revealed data.",
            "on_fail": "Keep v4 as the production reference and use only frozen raw for the next causal diagnosis.",
            "canonicalizer_allowed_after_development_pass": False,
            "canonicalizer_unlock_condition": "Only a separately preregistered fresh external blind-holdout pass; neither E9 nor the revealed v7 gates unlock canonicalizer work.",
        },
    }

    serialized_runtime = json.dumps(plan["v7_mechanism"], ensure_ascii=False)
    forbidden_evidence_ids = {record_id for record_id, _ in OFFLINE_SIGNAL_BY_SWITCH}
    leaked = sorted(
        value for value in forbidden_evidence_ids if value in serialized_runtime
    )
    if leaked:
        raise ValueError(f"fixture ids leaked into runtime mechanism: {leaked}")
    return plan


def _render_analysis_findings(analysis: dict[str, Any]) -> str:
    counts = analysis["mechanism_repartition"]["counts_by_signal"]
    return "\n".join(
        [
            "# E9 runtime-signal extraction",
            "",
            "## Result",
            "",
            "All 16 gold-directed E9 switches are assigned exactly once to three runtime-observable candidate signals:",
            "",
            f"- `S1-implicit-enumeration-partition-conflict`: {counts['S1-implicit-enumeration-partition-conflict']} switches.",
            f"- `S2-atomic-surface-conservation-conflict`: {counts['S2-atomic-surface-conservation-conflict']} switches.",
            f"- `S3-cross-coordination-attachment-bundle-conflict`: {counts['S3-cross-coordination-attachment-bundle-conflict']} switches.",
            "",
            "The runtime predicates use only source offsets and frozen graph relations: coverage, partition, overlap, containment, connector role, marker boundaries, attachment topology, and reference closure. Fixture ids appear only in the offline switch audit.",
            "",
            "## Important reclassification",
            "",
            "The one-switch residual previously grouped under R1 is an atomic surface-boundary conflict, not a remaining example-role error. Symptom labels therefore cannot be used as runtime dispatch rules.",
            "",
            "## Gate debt",
            "",
            "Frozen v6 matches frozen v5 on only 2/20 mechanism-development fixtures. The old 20/20 requirement remains unchanged, so applying only the 16 v4-directed switches cannot be a viable v7. V7 also needs family-level restoration for deltas fully licensed by the already-supported E2/E3/E6/E7 mechanisms.",
            "",
            "## Limit",
            "",
            "E9 proves oracle sufficiency, not selector validity. Three S1 records and all five S2 switches are projection-only evidence; their hidden topology is not claimed correct.",
            "",
        ]
    )


def _render_preregistration_findings(plan: dict[str, Any]) -> str:
    gates = plan["acceptance_gates"]
    return "\n".join(
        [
            "# V7 runtime selector preregistration",
            "",
            "## Frozen decision",
            "",
            "V7 is limited to runtime-observable node-family routing over byte-frozen v4, v5, and v6. Frozen v6 remains the default; v5 is available only for fully licensed E2/E3/E6/E7 family restoration, and v4 only for S1-S3 conflicts.",
            "",
            "## Non-negotiable gates",
            "",
            f"- Mechanism development remains {gates['G2-v5-mechanism-preservation']['required_exact_fixture_count']}/20 exact against frozen v5; frozen v6's 2/20 is not accepted as a threshold.",
            f"- E9 residuals must be {gates['G3-e9-residual-runtime-selection']['required_exact_record_count']}/9 with all 16 wrong families corrected and all 9 correct v6 families retained.",
            f"- E9 controls remain {gates['G4-v6-resolved-control-preservation']['required_exact_count']}/22 exact and byte-identical.",
            f"- Legacy remains {gates['G5-legacy-effective-exact']['required_exact_fixture_count']}/20 exact and projection remains {gates['G6-projection-regression-exact']['required_exact_fixture_count']}/60 exact.",
            "- Revealed external data may regress against neither frozen v4 nor frozen v6, per fixture and in aggregate.",
            "- Original v5 G0-G6 operators and numeric thresholds remain unchanged.",
            "",
            "## Boundary",
            "",
            "This preregistration does not implement or execute v7. After implementation, source must be frozen before a single development/regression run. Even a full pass does not unlock canonicalizer work without a separately frozen fresh external blind holdout.",
            "",
        ]
    )


def main() -> int:
    e9_raw, e9_report, regression_raw = _validate_inputs()
    analysis = _build_analysis(e9_raw, e9_report, regression_raw)
    _write_new(ANALYSIS_PATH, _serialized(analysis))
    _write_new(ANALYSIS_FINDINGS_PATH, _render_analysis_findings(analysis))

    preregistration = _build_preregistration(analysis)
    _write_new(PREREGISTRATION_PATH, _serialized(preregistration))
    _write_new(
        PREREGISTRATION_FINDINGS_PATH,
        _render_preregistration_findings(preregistration),
    )

    freeze = {
        "freeze_version": "unified-jd-structured-span-v7-preregistration-freeze-v1",
        "frozen_at": datetime.now(UTC).isoformat(),
        "status": "frozen_before_v7_implementation",
        "artifacts": {
            "runtime_signal_analysis": {
                "path": _relative(ANALYSIS_PATH),
                "sha256": _sha256(ANALYSIS_PATH),
            },
            "runtime_signal_findings": {
                "path": _relative(ANALYSIS_FINDINGS_PATH),
                "sha256": _sha256(ANALYSIS_FINDINGS_PATH),
            },
            "preregistration": {
                "path": _relative(PREREGISTRATION_PATH),
                "sha256": _sha256(PREREGISTRATION_PATH),
            },
            "preregistration_findings": {
                "path": _relative(PREREGISTRATION_FINDINGS_PATH),
                "sha256": _sha256(PREREGISTRATION_FINDINGS_PATH),
            },
            "builder": {
                "path": _relative(Path(__file__).resolve()),
                "sha256": _sha256(Path(__file__).resolve()),
            },
            "frozen_v4_parser": {
                "path": _relative(V4_PATH),
                "sha256": _sha256(V4_PATH),
            },
            "frozen_v5_parser": {
                "path": _relative(V5_PATH),
                "sha256": _sha256(V5_PATH),
            },
            "frozen_v6_parser": {
                "path": _relative(V6_PATH),
                "sha256": _sha256(V6_PATH),
            },
        },
        "checks": {
            "v7_existed_at_freeze": False,
            "e9_target_count": 9,
            "e9_changed_family_count": 16,
            "e9_retained_exact_v6_family_count": 9,
            "e9_control_count": 22,
            "runtime_signal_count": 3,
            "all_16_switches_assigned_once": True,
            "fixture_id_in_runtime_mechanism": False,
            "old_threshold_or_operator_weakened": False,
            "v5_mechanism_required_exact": "20/20",
            "legacy_required_effective_exact": "20/20",
            "projection_required_exact": "60/60",
            "model_call_count": 0,
            "network_call_count": 0,
            "canonicalizer_allowed": False,
        },
        "immutability": "Any signal predicate, family route, veto, precedence rule, gate, threshold, or frozen input change requires a new preregistration and freeze version before implementation.",
        "next_allowed_action": "Implement only the frozen v7 runtime-observable node-family router, add synthetic predicate/veto tests and the one-time evaluator, freeze all source, then execute development and regression gates exactly once.",
    }
    _write_new(FREEZE_PATH, _serialized(freeze))

    print(
        json.dumps(
            {
                "analysis": {
                    "path": _relative(ANALYSIS_PATH),
                    "sha256": _sha256(ANALYSIS_PATH),
                    "switch_count": analysis["mechanism_repartition"]["switch_count"],
                },
                "preregistration": {
                    "path": _relative(PREREGISTRATION_PATH),
                    "sha256": _sha256(PREREGISTRATION_PATH),
                },
                "freeze": {
                    "path": _relative(FREEZE_PATH),
                    "sha256": _sha256(FREEZE_PATH),
                },
                "v7_existed_at_freeze": False,
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
