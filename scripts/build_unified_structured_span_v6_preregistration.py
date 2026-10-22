from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATE = "2026-09-05"
V5_PREREGISTRATION_PATH = (
    ROOT / "datasets/unified_jd_structured_span_v5_preregistration_v1_2026-09-04.json"
)
V5_SOURCE_FREEZE_PATH = (
    ROOT / "datasets/unified_jd_structured_span_v5_source_freeze_v1_2026-09-05.json"
)
V5_DEVELOPMENT_RAW_PATH = (
    ROOT / "artifacts/evaluation/"
    "unified-jd-structured-span-v5-mechanism-development-v5-raw-v1-2026-09-05.json"
)
V5_REGRESSION_RAW_PATH = (
    ROOT / "artifacts/evaluation/"
    "unified-jd-structured-span-v5-regression-raw-v1-2026-09-05.json"
)
V5_REPORT_PATH = (
    ROOT / "artifacts/evaluation/"
    "unified-jd-structured-span-v5-development-regression-report-v1-2026-09-05.json"
)
V5_RECEIPT_PATH = (
    ROOT / "artifacts/evaluation/"
    "unified-jd-structured-span-v5-development-regression-receipt-v1-2026-09-05.json"
)
CLASSIFICATION_PATH = (
    ROOT / "artifacts/evaluation/"
    "unified-jd-structured-span-v5-frozen-regression-classification-v1-2026-09-05.json"
)
CLASSIFICATION_FINDINGS_PATH = (
    ROOT / "artifacts/evaluation/"
    "unified-jd-structured-span-v5-frozen-regression-classification-findings-v1-2026-09-05.md"
)
ANALYZER_PATH = (
    ROOT / "scripts/analyze_unified_structured_span_v5_frozen_regressions.py"
)
V4_PATH = ROOT / "src/domain/unified_jd_structured_spans_v4.py"
V5_PATH = ROOT / "src/domain/unified_jd_structured_spans_v5.py"
V6_PATH = ROOT / "src/domain/unified_jd_structured_spans_v6.py"
PREREGISTRATION_PATH = (
    ROOT / "datasets/unified_jd_structured_span_v6_preregistration_v1_2026-09-05.json"
)
FINDINGS_PATH = (
    ROOT / "artifacts/evaluation/"
    "unified-jd-structured-span-v6-preregistration-findings-v1-2026-09-05.md"
)
FREEZE_PATH = (
    ROOT
    / "datasets/unified_jd_structured_span_v6_preregistration_freeze_v1_2026-09-05.json"
)

FROZEN_INPUT_HASHES = {
    V5_PREREGISTRATION_PATH: "55a5cf715888a810de0a3ebff5ae3dfa6d194a422dc6ea02070791021bdf76c8",
    V5_SOURCE_FREEZE_PATH: "ac91d62eda040c00f1977aca818bb17fd279241a7afbc23339b9e5f68d9276c9",
    V5_DEVELOPMENT_RAW_PATH: "56f51ec6a54c0135478d22f9823373c67255e59fc5d90976fe9bed74bf9ec7ae",
    V5_REGRESSION_RAW_PATH: "d386a0e0e2e3834abf9c033a54702b7b4a12d81eee3f181605725b8e64819285",
    V5_REPORT_PATH: "a1a82413a355de58c7e765ec3fd7799cd479657377d04854be401f9bac531d01",
    V5_RECEIPT_PATH: "60bd1207184f79939699b2b07ffe8184ea2fa893d18f74f17fe34968d325a130",
    CLASSIFICATION_PATH: "e42741673adeca13bdcbadd5464297ba17bc136b1052d7be01c23ed9117f47fa",
    CLASSIFICATION_FINDINGS_PATH: "fc3fcee3962eada89c19ec14c8467c95b616e404aa3dce69fc36a5aef9c50ec2",
    ANALYZER_PATH: "2e676f63954b1defc7cc4c0cd9effb711a90f35ae97fa93a1fe9fb1aee04628e",
    V4_PATH: "e09e056cab75e651937391ce5410e6df7c94477c85565abb1425bbe85cfcb094",
    V5_PATH: "8abdb1df73af8731caf565d0f0c74ad824302bf99cdae2b1c6a4e2e13ad541da",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _serialized(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _canonical_sha256(payload: Any) -> str:
    value = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _write_new(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as output:
        output.write(content)


def _validate_inputs() -> tuple[dict[str, Any], dict[str, Any]]:
    for path, expected_hash in FROZEN_INPUT_HASHES.items():
        actual_hash = _sha256(path)
        if actual_hash != expected_hash:
            raise ValueError(
                f"frozen input hash mismatch for {_relative(path)}: "
                f"expected {expected_hash}, got {actual_hash}"
            )
    if V6_PATH.exists():
        raise FileExistsError("v6 implementation already exists before preregistration")
    for path in (PREREGISTRATION_PATH, FINDINGS_PATH, FREEZE_PATH):
        if path.exists():
            raise FileExistsError(
                f"preregistration output already exists: {_relative(path)}"
            )

    v5_preregistration = _load(V5_PREREGISTRATION_PATH)
    classification = _load(CLASSIFICATION_PATH)
    if classification["scope"]["v5_parser_executed"] is not False:
        raise ValueError("classification was not offline-only")
    if classification["inventory"]["classified_observation_count"] != 31:
        raise ValueError("classification inventory is incomplete")
    return v5_preregistration, classification


def _input_references() -> dict[str, dict[str, str]]:
    return {
        path.stem: {"path": _relative(path), "sha256": expected_hash}
        for path, expected_hash in FROZEN_INPUT_HASHES.items()
    }


def _resolution_cohorts(classification: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for class_id, count in classification["classification_counts"].items():
        cases = [
            {
                "cohort": case["cohort"],
                "id": case["id"],
                **(
                    {"fixture_path": case["fixture_path"]}
                    if "fixture_path" in case
                    else {}
                ),
            }
            for case in classification["cases"]
            if case["classification"] == class_id
        ]
        result[class_id] = {
            "observation_count": count,
            "required_resolved_count": count,
            "required_resolution_rate": 1.0,
            "cases": cases,
        }
    return result


def _build_preregistration(
    v5_preregistration: dict[str, Any], classification: dict[str, Any]
) -> dict[str, Any]:
    preserved_gates = v5_preregistration["development_acceptance_gates"]
    return {
        "preregistration_version": "unified-jd-structured-span-v6-preregistration-v1",
        "created_at": DATE,
        "status": "frozen_before_v6_implementation",
        "scope": {
            "task": "activation_and_compatibility_only",
            "development_data_status": "all_inputs_revealed_not_holdout",
            "generalization_claim": False,
            "v4_modification_allowed": False,
            "v5_modification_allowed": False,
            "v5_gate_or_threshold_modification_allowed": False,
            "new_structure_semantics_allowed": False,
            "fixture_specific_runtime_rules_allowed": False,
            "employer_title_or_category_dispatch_allowed": False,
            "canonicalizer_work_allowed": False,
            "model_calls_allowed": False,
            "network_calls_allowed": False,
        },
        "inputs": _input_references(),
        "offline_diagnostic_basis": {
            "classified_observation_count": classification["inventory"][
                "classified_observation_count"
            ],
            "classification_counts": classification["classification_counts"],
            "interpretation": (
                "The evidence supports an activation/compatibility layer around the "
                "frozen parsers. It does not support expanding v5 parsing semantics."
            ),
        },
        "v6_mechanism": {
            "name": "region-local-supported-delta-compatibility-router",
            "implementation_target": "src/domain/unified_jd_structured_spans_v6.py",
            "composition": (
                "Run the byte-frozen v4 and v5 parsers, align their nodes to exact "
                "top-level source regions, and merge only licensed v5 region subgraphs. "
                "Frozen v4 is the default for every unlicensed or conflicted region."
            ),
            "ordered_stages": [
                {
                    "order": 1,
                    "name": "dual_frozen_parse",
                    "rule": (
                        "Execute the frozen v4 and v5 parsers once each for the same "
                        "source_text and category. Neither parser source may be changed."
                    ),
                },
                {
                    "order": 2,
                    "name": "exact_region_alignment",
                    "rule": (
                        "Assign wrappers, connectors, members, scopes, attachments, and "
                        "candidates to half-open top-level source regions by span "
                        "containment. Cross-region attachments retain their cue region "
                        "and source-anchored parent span."
                    ),
                },
                {
                    "order": 3,
                    "name": "license_supported_activation",
                    "rule": (
                        "A region may use a v5 delta only for: an explicit 如 cue "
                        "including 如 followed by a colon; a protected parenthetical "
                        "attachment; an E7 leading-对 attachment ending in 等领域 or "
                        "等方面; an E6 direct open list governed by an immediately "
                        "preceding deictic 以下… header and colon; or a structural "
                        "wrapper decomposition where v5 creates at least one explicit "
                        "coordination, scope, or attachment inside that same wrapper "
                        "content."
                    ),
                },
                {
                    "order": 4,
                    "name": "apply_role_conflict_guard",
                    "rule": (
                        "For a no-explicit-cue 等 enumeration, if v4 projects the same "
                        "source spans as surface items while v5 only reclassifies them "
                        "as examples, keep the v4 region unless the independently "
                        "licensed E6 or E7 signature is present."
                    ),
                },
                {
                    "order": 5,
                    "name": "preserve_protected_compatibility",
                    "rule": (
                        "Reject a v5 region delta that deletes a v4 protected "
                        "parenthetical attachment without a source-covering replacement, "
                        "or changes a v4 atomic/slash/scope-bearing projection outside "
                        "the licensed delta span."
                    ),
                },
                {
                    "order": 6,
                    "name": "bound_open_list_activation",
                    "rule": (
                        "An open_list_suffix wrapper from terminal 等优先 is retained "
                        "only for the deictic-header-plus-colon E6 form. A plain list "
                        "ending 等优先 retains the frozen v4 wrapper graph."
                    ),
                },
                {
                    "order": 7,
                    "name": "region_local_merge",
                    "rule": (
                        "Start from the v4 graph, replace only licensed and unconflicted "
                        "region nodes with their v5 counterparts, then deterministically "
                        "rebase ids and scope member references. No whole-clause fresh "
                        "dispatch is permitted."
                    ),
                },
                {
                    "order": 8,
                    "name": "validate_and_project",
                    "rule": (
                        "Validate all spans, ids, scope edges, and attachment edges, then "
                        "project from the merged graph without string rewriting or "
                        "canonicalization."
                    ),
                },
            ],
            "precedence": [
                "source anchoring and graph validity",
                "compatibility veto",
                "licensed v5 region delta",
                "frozen v4 default",
            ],
            "runtime_prohibitions": [
                "fixture id, file path, company, title, category, or gold lookup",
                "expected or actual projection string equality lookup",
                "classification-case id lookup",
                "new lexical canonicalization",
                "model or network calls",
            ],
        },
        "evaluation_adjudication": {
            "purpose": (
                "Correct one source-inconsistent same-character offset while retaining "
                "the effective 20/20 legacy exact threshold."
            ),
            "source_gold_immutable": True,
            "fixture_id": "structured-external-v1-016",
            "field": "wrappers[1].marker_span",
            "frozen_value": {"text": "能", "start": 2, "end": 3},
            "source_corrected_value": {"text": "能", "start": 6, "end": 7},
            "evidence": (
                "The associated content_span starts at 7 and the grammatical prefix "
                "immediately precedes it at [6,7); [2,3) is the homograph inside 工程能力."
            ),
            "runtime_exception_allowed": False,
        },
        "acceptance_gates": {
            "G0-G6-preserved-without-weakening": {
                "source": {
                    "path": _relative(V5_PREREGISTRATION_PATH),
                    "sha256": FROZEN_INPUT_HASHES[V5_PREREGISTRATION_PATH],
                    "json_pointer": "/development_acceptance_gates",
                    "canonical_sha256": _canonical_sha256(preserved_gates),
                },
                "requirement": (
                    "Evaluate every original G0-G6 criterion with unchanged operators "
                    "and numeric thresholds. For the single invalid legacy marker "
                    "offset, use the preregistered source-corrected adjudication above "
                    "and continue to require effective 20/20 exactness."
                ),
            },
            "G7-v5-mechanism-preservation": {
                "fixture_count": 20,
                "reference": {
                    "path": _relative(V5_DEVELOPMENT_RAW_PATH),
                    "sha256": FROZEN_INPUT_HASHES[V5_DEVELOPMENT_RAW_PATH],
                },
                "requirement": (
                    "V6 must match frozen v5 exactly fixture-by-fixture on wrappers, "
                    "connector roles, coordination members, scope edges, attachment "
                    "parents and edges, surface projection, and example projection."
                ),
                "required_exact_fixture_count": 20,
            },
            "G8-classified-regression-resolution": {
                "all_criteria_conjunctive": True,
                "cohorts": _resolution_cohorts(classification),
                "resolution_definition": (
                    "A case is resolved only when all frozen expected structural layers "
                    "available for that cohort and both projections are exact. The R7 "
                    "case uses only the source-corrected adjudicated marker offset."
                ),
            },
            "G9-no-new-regression": {
                "legacy_effective_exact_fixture_count": 20,
                "projection_exact_fixture_count": 60,
                "projection_fixture_count": 60,
                "revealed_external": (
                    "Every aggregate metric and every per-fixture primary-layer "
                    "difference count must be no worse than frozen v4; the known "
                    "structured-corpus-external-v1-006 wrapper regression must be zero."
                ),
                "structured_span_tests": "all pass",
            },
        },
        "evaluation_protocol": {
            "all_criteria_conjunctive": True,
            "threshold_or_operator_change_after_freeze_allowed": False,
            "source_freeze_before_any_v6_fixture_execution": True,
            "raw_before_decision": True,
            "write_new_outputs_only": True,
            "v6_development_run_count": 1,
            "v6_regression_run_count": 1,
            "failure_policy": (
                "Freeze the failed raw and keep v4 as production reference. Any source, "
                "trigger, conflict guard, adjudication, or threshold change requires a "
                "new preregistration version before another v6 attempt."
            ),
        },
        "post_gate_protocol": {
            "on_pass": (
                "Freeze v6 and collect a fresh corpus-external blind holdout with no "
                "source, job, URL, or employer-selection overlap with revealed data."
            ),
            "on_fail": (
                "Do not modify frozen v6 in place. Diagnose only from its frozen raw and "
                "create a new preregistration before another implementation."
            ),
            "canonicalizer_allowed_after_development_pass": False,
            "canonicalizer_unlock_condition": (
                "Only a later fresh blind-holdout pass under separately frozen gates."
            ),
        },
    }


def _render_findings(preregistration: dict[str, Any]) -> str:
    counts = preregistration["offline_diagnostic_basis"]["classification_counts"]
    lines = [
        "# V6 activation and compatibility preregistration",
        "",
        "## Frozen decision",
        "",
        "V6 is limited to a region-local compatibility router around the byte-frozen v4 and v5 parsers. It may not add parser semantics, modify v5, weaken a v5 gate, dispatch on fixture metadata, or canonicalize output.",
        "",
        "## Evidence",
        "",
    ]
    for class_id, count in counts.items():
        lines.append(f"- `{class_id}`: {count} frozen observations.")
    lines.extend(
        [
            "",
            "## Gates",
            "",
            "- Original v5 G0-G6 operators and numeric thresholds remain unchanged.",
            "- All 20 mechanism-development fixtures must remain exactly equal to frozen v5 on every layer.",
            "- Every one of the 31 classified regression observations must be resolved.",
            "- Legacy remains effectively 20/20 exact, projection remains 60/60 exact, and revealed external data has no aggregate or per-fixture regression.",
            "- The old same-character marker offset is source-corrected at evaluation time; this is a frozen data adjudication, not a runtime exception or threshold reduction.",
            "",
            "## Next boundary",
            "",
            "Implementation is allowed only after this preregistration and its builder are frozen. A development pass still does not unlock canonicalizer work.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    v5_preregistration, classification = _validate_inputs()
    preregistration = _build_preregistration(v5_preregistration, classification)
    _write_new(PREREGISTRATION_PATH, _serialized(preregistration))
    _write_new(FINDINGS_PATH, _render_findings(preregistration))
    freeze = {
        "freeze_version": "unified-jd-structured-span-v6-preregistration-freeze-v1",
        "frozen_at": datetime.now(UTC).isoformat(),
        "status": "frozen_before_v6_implementation",
        "artifacts": {
            "preregistration": {
                "path": _relative(PREREGISTRATION_PATH),
                "sha256": _sha256(PREREGISTRATION_PATH),
            },
            "findings": {
                "path": _relative(FINDINGS_PATH),
                "sha256": _sha256(FINDINGS_PATH),
            },
            "builder": {
                "path": _relative(Path(__file__).resolve()),
                "sha256": _sha256(Path(__file__).resolve()),
            },
            "classification": {
                "path": _relative(CLASSIFICATION_PATH),
                "sha256": _sha256(CLASSIFICATION_PATH),
            },
            "frozen_v4_parser": {
                "path": _relative(V4_PATH),
                "sha256": _sha256(V4_PATH),
            },
            "frozen_v5_parser": {
                "path": _relative(V5_PATH),
                "sha256": _sha256(V5_PATH),
            },
        },
        "checks": {
            "v6_existed_at_freeze": False,
            "v4_modified": False,
            "v5_modified": False,
            "original_g0_g6_preserved": True,
            "threshold_or_operator_weakened": False,
            "effective_legacy_exact_threshold": "20/20",
            "projection_exact_threshold": "60/60",
            "classified_observations_required_resolved": "31/31",
            "model_call_count": 0,
            "network_call_count": 0,
            "canonicalizer_allowed": False,
        },
        "immutability": (
            "Any mechanism, trigger, veto, adjudication, gate, or threshold change "
            "requires a new preregistration and freeze version before implementation."
        ),
        "next_allowed_action": (
            "Implement only the frozen region-local activation/compatibility router in "
            "src/domain/unified_jd_structured_spans_v6.py, freeze its source, then run "
            "the development and regression gates once."
        ),
    }
    _write_new(FREEZE_PATH, _serialized(freeze))
    print(
        json.dumps(
            {
                "preregistration": {
                    "path": _relative(PREREGISTRATION_PATH),
                    "sha256": _sha256(PREREGISTRATION_PATH),
                },
                "freeze": {
                    "path": _relative(FREEZE_PATH),
                    "sha256": _sha256(FREEZE_PATH),
                },
                "v6_existed_at_freeze": False,
                "original_g0_g6_preserved": True,
                "classified_observations_required_resolved": "31/31",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
