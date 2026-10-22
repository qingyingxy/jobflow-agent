from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATE = "2026-09-05"
REGRESSION_RAW_PATH = (
    ROOT / "artifacts/evaluation/"
    "unified-jd-structured-span-v5-regression-raw-v1-2026-09-05.json"
)
DEVELOPMENT_RAW_PATH = (
    ROOT / "artifacts/evaluation/"
    "unified-jd-structured-span-v5-mechanism-development-v5-raw-v1-2026-09-05.json"
)
V5_REPORT_PATH = (
    ROOT / "artifacts/evaluation/"
    "unified-jd-structured-span-v5-development-regression-report-v1-2026-09-05.json"
)
V5_RECEIPT_PATH = (
    ROOT / "artifacts/evaluation/"
    "unified-jd-structured-span-v5-development-regression-receipt-v1-2026-09-05.json"
)
LEGACY_GOLD_PATH = (
    ROOT / "datasets/unified_jd_structured_span_v4_development_gold_v1_2026-09-04.json"
)
EXTERNAL_DEVELOPMENT_PATH = (
    ROOT / "datasets/"
    "unified_jd_structured_span_v4_corpus_external_revealed_development_v1_2026-09-04.json"
)
OUTPUT_JSON_PATH = (
    ROOT / "artifacts/evaluation/"
    "unified-jd-structured-span-v5-frozen-regression-classification-v1-2026-09-05.json"
)
OUTPUT_FINDINGS_PATH = (
    ROOT / "artifacts/evaluation/"
    "unified-jd-structured-span-v5-frozen-regression-classification-findings-v1-2026-09-05.md"
)

FROZEN_HASHES = {
    REGRESSION_RAW_PATH: "d386a0e0e2e3834abf9c033a54702b7b4a12d81eee3f181605725b8e64819285",
    DEVELOPMENT_RAW_PATH: "56f51ec6a54c0135478d22f9823373c67255e59fc5d90976fe9bed74bf9ec7ae",
    V5_REPORT_PATH: "a1a82413a355de58c7e765ec3fd7799cd479657377d04854be401f9bac531d01",
    V5_RECEIPT_PATH: "60bd1207184f79939699b2b07ffe8184ea2fa893d18f74f17fe34968d325a130",
    LEGACY_GOLD_PATH: "5bb034f2aaa6ad44c2ad0f6c06618291d451a58ec3808e903a27cafe58fe9509",
    EXTERNAL_DEVELOPMENT_PATH: "965263881ff85bca636aa6ab87adaca24d74183fa13400709133323a3a6d5b73",
}

AMBIGUOUS_DENG_ROLE_FLIP = "R1-ambiguous-deng-surface-example-role-flip"
SINGLETON_PARENTHETICAL_LOSS = "R2-singleton-parenthetical-attachment-loss"
WRAPPER_OPERATOR_DRIFT = "R3-wrapper-operator-boundary-drift"
CONNECTOR_SCOPE_DRIFT = "R4-connector-scope-decomposition-drift"
EXPLICIT_CUE_SEGMENTATION = "R5-explicit-cue-colon-segmentation-gap"
OPEN_LIST_OVERACTIVATION = "R6-open-list-wrapper-overactivation"
GOLD_OFFSET_DEFECT = "R7-frozen-gold-same-character-offset-defect"

LEGACY_CLASSES = {
    "structured-external-v1-001": WRAPPER_OPERATOR_DRIFT,
    "structured-external-v1-006": AMBIGUOUS_DENG_ROLE_FLIP,
    "structured-external-v1-007": AMBIGUOUS_DENG_ROLE_FLIP,
    "structured-external-v1-010": AMBIGUOUS_DENG_ROLE_FLIP,
    "structured-external-v1-014": WRAPPER_OPERATOR_DRIFT,
    "structured-external-v1-016": GOLD_OFFSET_DEFECT,
    "structured-external-v1-017": WRAPPER_OPERATOR_DRIFT,
    "structured-external-v1-018": WRAPPER_OPERATOR_DRIFT,
}

PROJECTION_CLASSES = {
    "canonical-v1-responsibility-001": WRAPPER_OPERATOR_DRIFT,
    "canonical-v1-responsibility-005": SINGLETON_PARENTHETICAL_LOSS,
    "canonical-v1-skill-001": AMBIGUOUS_DENG_ROLE_FLIP,
    "canonical-v1-skill-002": AMBIGUOUS_DENG_ROLE_FLIP,
    "canonical-v1-skill-003": AMBIGUOUS_DENG_ROLE_FLIP,
    "canonical-v1-skill-004": EXPLICIT_CUE_SEGMENTATION,
    "canonical-v1-skill-005": SINGLETON_PARENTHETICAL_LOSS,
    "canonical-v1-capability-004": WRAPPER_OPERATOR_DRIFT,
    "canonical-v1-capability-005": WRAPPER_OPERATOR_DRIFT,
    "surface-holdout-v1-001": AMBIGUOUS_DENG_ROLE_FLIP,
    "surface-holdout-v1-003": CONNECTOR_SCOPE_DRIFT,
    "surface-holdout-v1-004": AMBIGUOUS_DENG_ROLE_FLIP,
    "surface-holdout-v1-005": CONNECTOR_SCOPE_DRIFT,
    "surface-holdout-v1-006": AMBIGUOUS_DENG_ROLE_FLIP,
    "surface-holdout-v1-009": SINGLETON_PARENTHETICAL_LOSS,
    "surface-holdout-v1-010": AMBIGUOUS_DENG_ROLE_FLIP,
    "surface-holdout-v1-015": CONNECTOR_SCOPE_DRIFT,
    "surface-holdout-v1-017": CONNECTOR_SCOPE_DRIFT,
    "surface-holdout-v1-019": CONNECTOR_SCOPE_DRIFT,
    "surface-holdout-v2-002": CONNECTOR_SCOPE_DRIFT,
    "surface-holdout-v2-010": AMBIGUOUS_DENG_ROLE_FLIP,
    "surface-holdout-v2-019": AMBIGUOUS_DENG_ROLE_FLIP,
}

EXTERNAL_CLASSES = {
    "structured-corpus-external-v1-006": OPEN_LIST_OVERACTIVATION,
}

CLASS_DEFINITIONS = {
    AMBIGUOUS_DENG_ROLE_FLIP: {
        "definition": (
            "A no-explicit-cue postposed 等 enumeration that the frozen contract "
            "projects as surface members is reclassified by v5 as examples under a "
            "container head."
        ),
        "v6_implication": (
            "Require an output-conflict compatibility guard: when frozen v4 keeps the "
            "same source spans as surface items and v5 only changes them to examples, "
            "prefer v4 unless an independently supported E6/E7 or explicit-cue trigger "
            "licenses the role change."
        ),
    },
    SINGLETON_PARENTHETICAL_LOSS: {
        "definition": (
            "A protected parenthetical with one lexical example is preserved by the "
            "old contract but omitted by the fresh v5 graph, changing both attachment "
            "and parent projection."
        ),
        "v6_implication": (
            "A frozen v4 parenthetical attachment may not be deleted unless v5 emits a "
            "source-anchored replacement attachment covering the same protected span."
        ),
    },
    WRAPPER_OPERATOR_DRIFT: {
        "definition": (
            "Whole-clause fresh activation changes a wrapper, leading operator, or "
            "predicate boundary outside the structural region that justified v5."
        ),
        "v6_implication": (
            "Activate and merge v5 deltas per top-level source region; preserve frozen "
            "v4 boundaries outside the licensed region and reject unlicensed token loss."
        ),
    },
    CONNECTOR_SCOPE_DRIFT: {
        "definition": (
            "A connector is split or retained at a different level, changing an atomic "
            "phrase, shared scope, residual predicate, or slash coordination."
        ),
        "v6_implication": (
            "Treat frozen v4 protected/atomic spans and existing scope-bearing projection "
            "as compatibility constraints outside a licensed E2/E3 delta."
        ),
    },
    EXPLICIT_CUE_SEGMENTATION: {
        "definition": (
            "The top-level colon after an explicit 如 cue separates the cue from its "
            "example body, so v5 loses the registered attachment."
        ),
        "v6_implication": (
            "Normalize the region map for 如 followed only by optional whitespace and a "
            "colon before activation; do not change general colon segmentation."
        ),
    },
    OPEN_LIST_OVERACTIVATION: {
        "definition": (
            "Terminal 等优先 creates an open-list wrapper without the preregistered "
            "deictic 以下…: direct-list context."
        ),
        "v6_implication": (
            "License E6 direct-open-list activation only when a preceding deictic header "
            "and colon govern the enumerated region; otherwise retain the v4 wrapper set."
        ),
    },
    GOLD_OFFSET_DEFECT: {
        "definition": (
            "The old gold anchors prefix 能 to the earlier homograph in 工程能力 at "
            "[2,3), while its content begins after the actual prefix at [6,7)."
        ),
        "v6_implication": (
            "Keep the 20/20 effective threshold, but preregister the source-corrected "
            "[6,7) target. Never add a runtime fixture exception."
        ),
    },
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _write_new(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as output:
        output.write(content)


def _span_key(span: dict[str, Any]) -> tuple[int, int, str]:
    return span["start"], span["end"], span["text"]


def _group_members(value: dict[str, Any], *, gold: bool) -> list[Any]:
    groups = value["coordinations"] if gold else value["parsed_clause"]["coordinations"]
    result: list[Any] = []
    for group in groups:
        role = group["role"] if gold else group.get("role", "surface")
        spans = (
            group["member_spans"]
            if gold
            else [item["span"] for item in group["members"]]
        )
        result.extend((role, _span_key(span)) for span in spans)
    return result


def _member_id_spans(parsed: dict[str, Any]) -> dict[str, tuple[int, int, str]]:
    result = {
        item["id"]: _span_key(item["span"])
        for item in parsed.get("item_candidates", [])
    }
    for group in parsed.get("coordinations", []):
        result.update(
            {item["id"]: _span_key(item["span"]) for item in group["members"]}
        )
    return result


def _layer_values(value: dict[str, Any], *, gold: bool) -> dict[str, list[Any]]:
    if gold:
        wrappers = [
            (item["kind"], _span_key(item["marker_span"])) for item in value["wrappers"]
        ]
        connectors = [
            (_span_key(item["span"]), item["role"])
            for item in value["connector_labels"]
        ]
        scopes = [
            (scope["kind"], _span_key(scope["span"]), _span_key(member))
            for scope in value["shared_scopes"]
            for member in scope["applies_to_member_spans"]
        ]
        attachments = value["example_attachments"]
        surface = value["projection"]["surface_items"]
        examples = value["projection"]["examples"]
    else:
        parsed = value["parsed_clause"]
        wrappers = [
            (item["kind"].split(".")[-1], _span_key(item["marker_span"]))
            for item in parsed["wrappers"]
        ]
        connectors = [
            (_span_key(item["span"]), item["role"])
            for item in parsed["connector_labels"]
        ]
        member_spans = _member_id_spans(parsed)
        scopes = [
            (scope["kind"], _span_key(scope["span"]), member_spans[member_id])
            for scope in parsed["shared_scopes"]
            for member_id in scope["applies_to_member_ids"]
            if member_id in member_spans
        ]
        attachments = parsed["example_attachments"]
        surface = value["items"]
        examples = value["examples"]
    attachment_parents = [
        (_span_key(item["cue_span"]), _span_key(item["parent_span"]))
        for item in attachments
    ]
    attachment_edges = [
        (
            _span_key(item["cue_span"]),
            _span_key(item["parent_span"]),
            _span_key(example),
        )
        for item in attachments
        for example in item["example_spans"]
    ]
    return {
        "wrappers": wrappers,
        "connector_labels": connectors,
        "coordination_members": _group_members(value, gold=gold),
        "shared_scope_edges": scopes,
        "example_attachment_parents": attachment_parents,
        "example_attachment_edges": attachment_edges,
        "surface_projection": list(surface),
        "example_projection": list(examples),
    }


def _difference_counts(
    gold_fixture: dict[str, Any], prediction: dict[str, Any]
) -> dict[str, int]:
    expected = _layer_values(gold_fixture, gold=True)
    actual = _layer_values(prediction, gold=False)
    return {
        layer: sum((Counter(expected[layer]) - Counter(actual[layer])).values())
        + sum((Counter(actual[layer]) - Counter(expected[layer])).values())
        for layer in expected
    }


def _validate_inputs() -> None:
    for path, expected_hash in FROZEN_HASHES.items():
        actual_hash = _sha256(path)
        if actual_hash != expected_hash:
            raise ValueError(
                f"frozen input hash mismatch for {_relative(path)}: "
                f"expected {expected_hash}, got {actual_hash}"
            )
    if OUTPUT_JSON_PATH.exists() or OUTPUT_FINDINGS_PATH.exists():
        raise FileExistsError("offline classification output already exists")
    receipt = _load(V5_RECEIPT_PATH)
    if receipt["v5_development_run_count"] != 1:
        raise ValueError("unexpected v5 development run count")
    if receipt["v5_regression_run_count"] != 1:
        raise ValueError("unexpected v5 regression run count")
    if receipt["gate_passed"] is not False:
        raise ValueError("offline failure analysis requires the frozen failed v5 gate")


def _legacy_cases(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    gold = _load(LEGACY_GOLD_PATH)
    predictions = {item["id"]: item for item in bundle["legacy_development"]["records"]}
    cases: list[dict[str, Any]] = []
    for fixture in gold["fixtures"]:
        prediction = predictions[fixture["id"]]
        differences = _difference_counts(fixture, prediction)
        if not any(differences.values()):
            continue
        cases.append(
            {
                "cohort": "legacy-20",
                "id": fixture["id"],
                "classification": LEGACY_CLASSES[fixture["id"]],
                "source_text": fixture["source_text"],
                "rule_mode": (
                    "v5-fresh"
                    if prediction["rule_ids"]
                    and prediction["rule_ids"][0].startswith("v5.")
                    else "v4-compatible"
                ),
                "difference_counts": {
                    key: value for key, value in differences.items() if value
                },
                "expected_items": fixture["projection"]["surface_items"],
                "actual_items": prediction["items"],
                "expected_examples": fixture["projection"]["examples"],
                "actual_examples": prediction["examples"],
            }
        )
    if {case["id"] for case in cases} != set(LEGACY_CLASSES):
        raise ValueError("legacy regression set changed from the frozen raw diagnosis")
    return cases


def _projection_cases(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    cases = [
        {
            "cohort": "projection-60",
            "fixture_path": item["fixture_path"],
            "id": item["id"],
            "classification": PROJECTION_CLASSES[item["id"]],
            "source_text": item["source_text"],
            "expected_items": item["expected_items"],
            "actual_items": item["actual_items"],
            "expected_examples": item["expected_examples"],
            "actual_examples": item["actual_examples"],
        }
        for item in bundle["projection_60"]["records"]
        if not item["exact"]
    ]
    if {case["id"] for case in cases} != set(PROJECTION_CLASSES):
        raise ValueError(
            "projection regression set changed from the frozen raw diagnosis"
        )
    return cases


def _external_cases(report: dict[str, Any]) -> list[dict[str, Any]]:
    dataset = _load(EXTERNAL_DEVELOPMENT_PATH)
    fixtures = {item["id"]: item for item in dataset["fixtures"]}
    comparison = report["gates"]["G6-regression"]["checks"][
        "revealed_external_per_fixture_non_regression"
    ]["actual"]
    cases: list[dict[str, Any]] = []
    for fixture_id, result in comparison.items():
        if result["passed"]:
            continue
        fixture = fixtures[fixture_id]
        cases.append(
            {
                "cohort": "revealed-external-20",
                "id": fixture_id,
                "classification": EXTERNAL_CLASSES[fixture_id],
                "source_text": fixture["gold"]["source_text"],
                "baseline_difference_counts": result["baseline_difference_counts"],
                "v5_difference_counts": result["v5_difference_counts"],
                "failed_layers": [
                    layer
                    for layer, passed in result["layer_checks"].items()
                    if not passed
                ],
            }
        )
    if {case["id"] for case in cases} != set(EXTERNAL_CLASSES):
        raise ValueError(
            "external regression set changed from the frozen raw diagnosis"
        )
    return cases


def _render_findings(analysis: dict[str, Any]) -> str:
    lines = [
        "# Frozen v5 offline regression classification",
        "",
        "## Boundary",
        "",
        "- Inputs are the frozen v5 raw/report artifacts and their already-frozen gold.",
        "- The v5 parser was neither imported nor executed.",
        "- No source, threshold, model, network, or canonicalizer change was made.",
        "",
        "## Inventory",
        "",
        f"- Legacy regressions: {analysis['inventory']['legacy_regression_count']}/20.",
        f"- Projection regressions: {analysis['inventory']['projection_regression_count']}/60.",
        f"- Revealed external per-fixture regressions: {analysis['inventory']['external_regression_count']}/20.",
        f"- Total classified observations: {analysis['inventory']['classified_observation_count']}.",
        "",
        "## Mutually exclusive classes",
        "",
        "| Class | Count | Runtime implication |",
        "|---|---:|---|",
    ]
    for class_id, count in analysis["classification_counts"].items():
        implication = analysis["class_definitions"][class_id]["v6_implication"]
        lines.append(f"| `{class_id}` | {count} | {implication} |")
    lines.extend(
        [
            "",
            "## Causal boundary",
            "",
            "The frozen evidence supports a region-local activation and compatibility router, not another unrestricted parser expansion. V5's E2/E3/E6/E7 mechanisms remain supported inside licensed regions; the regressions arise when whole-clause activation changes unrelated boundaries or when v4/v5 disagree on an ambiguous role.",
            "",
            "The legacy `structured-external-v1-016` failure is an evaluation-label offset defect: the gold points to the `能` inside `工程能力` at `[2,3)`, while the actual prefix is `[6,7)`. V6 must retain an effective 20/20 threshold using the source-corrected target; no fixture-specific runtime exception is allowed.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    _validate_inputs()
    bundle = _load(REGRESSION_RAW_PATH)
    report = _load(V5_REPORT_PATH)
    cases = [
        *_legacy_cases(bundle),
        *_projection_cases(bundle),
        *_external_cases(report),
    ]
    counts = Counter(case["classification"] for case in cases)
    analysis = {
        "analysis_version": "unified-jd-structured-span-v5-frozen-regression-classification-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "offline_frozen_raw_regression_classification",
        "scope": {
            "v5_parser_imported": False,
            "v5_parser_executed": False,
            "development_or_regression_rerun_count": 0,
            "v5_source_modified": False,
            "v5_threshold_modified": False,
            "model_call_count": 0,
            "network_call_count": 0,
            "canonicalizer_work": False,
        },
        "inputs": {
            _relative(path): {"sha256": expected_hash}
            for path, expected_hash in FROZEN_HASHES.items()
        },
        "inventory": {
            "legacy_regression_count": sum(
                case["cohort"] == "legacy-20" for case in cases
            ),
            "projection_regression_count": sum(
                case["cohort"] == "projection-60" for case in cases
            ),
            "external_regression_count": sum(
                case["cohort"] == "revealed-external-20" for case in cases
            ),
            "classified_observation_count": len(cases),
        },
        "classification_counts": dict(sorted(counts.items())),
        "class_definitions": CLASS_DEFINITIONS,
        "cases": cases,
        "supported_v6_mechanism": {
            "name": "region-local-supported-delta-compatibility-router",
            "components": [
                "source-region-local activation instead of whole-clause fresh dispatch",
                "surface-versus-example conflict guard for ambiguous no-cue 等",
                "frozen v4 protected attachment and atomic/scope compatibility preservation",
                "narrow 如： cue-region normalization",
                "deictic-header requirement for E6 direct-open-list wrapper activation",
            ],
        },
        "unsupported_responses": [
            "modifying frozen v5",
            "weakening any v5 gate after observing this result",
            "fixture, employer, title, category, or projection-string runtime dispatch",
            "canonicalizer work",
        ],
    }
    if analysis["inventory"] != {
        "legacy_regression_count": 8,
        "projection_regression_count": 22,
        "external_regression_count": 1,
        "classified_observation_count": 31,
    }:
        raise ValueError("classified inventory does not match the frozen gate result")
    if counts != {
        AMBIGUOUS_DENG_ROLE_FLIP: 12,
        SINGLETON_PARENTHETICAL_LOSS: 3,
        WRAPPER_OPERATOR_DRIFT: 7,
        CONNECTOR_SCOPE_DRIFT: 6,
        EXPLICIT_CUE_SEGMENTATION: 1,
        OPEN_LIST_OVERACTIVATION: 1,
        GOLD_OFFSET_DEFECT: 1,
    }:
        raise ValueError("classification counts do not match the frozen review")

    _write_new(
        OUTPUT_JSON_PATH, json.dumps(analysis, ensure_ascii=False, indent=2) + "\n"
    )
    _write_new(OUTPUT_FINDINGS_PATH, _render_findings(analysis))
    print(
        json.dumps(
            {
                "output": _relative(OUTPUT_JSON_PATH),
                "findings": _relative(OUTPUT_FINDINGS_PATH),
                "inventory": analysis["inventory"],
                "classification_counts": analysis["classification_counts"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
