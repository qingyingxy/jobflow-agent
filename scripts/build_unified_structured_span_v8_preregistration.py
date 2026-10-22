from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATE = "2026-09-05"

V7_DEVELOPMENT_RAW_PATH = (
    ROOT
    / f"artifacts/evaluation/unified-jd-structured-span-v7-mechanism-development-raw-v1-{DATE}.json"
)
V7_REGRESSION_RAW_PATH = (
    ROOT
    / f"artifacts/evaluation/unified-jd-structured-span-v7-regression-raw-v1-{DATE}.json"
)
V5_DEVELOPMENT_RAW_PATH = (
    ROOT
    / f"artifacts/evaluation/unified-jd-structured-span-v5-mechanism-development-v5-raw-v1-{DATE}.json"
)
V6_REGRESSION_RAW_PATH = (
    ROOT
    / f"artifacts/evaluation/unified-jd-structured-span-v6-regression-raw-v1-{DATE}.json"
)
E9_RAW_PATH = (
    ROOT
    / f"artifacts/evaluation/unified-jd-structured-span-v6-e9-region-versus-node-family-merge-oracle-raw-v1-{DATE}.json"
)
V7_PREREGISTRATION_PATH = (
    ROOT / f"datasets/unified_jd_structured_span_v7_preregistration_v1_{DATE}.json"
)
V7_SOURCE_FREEZE_PATH = (
    ROOT / f"datasets/unified_jd_structured_span_v7_source_freeze_v1_{DATE}.json"
)
V4_PATH = ROOT / "src/domain/unified_jd_structured_spans_v4.py"
V5_PATH = ROOT / "src/domain/unified_jd_structured_spans_v5.py"
V6_PATH = ROOT / "src/domain/unified_jd_structured_spans_v6.py"
V7_PATH = ROOT / "src/domain/unified_jd_structured_spans_v7.py"
V8_PATH = ROOT / "src/domain/unified_jd_structured_spans_v8.py"

CLASSIFICATION_PATH = (
    ROOT
    / f"artifacts/evaluation/unified-jd-structured-span-v7-frozen-raw-failure-classification-v1-{DATE}.json"
)
CLASSIFICATION_FINDINGS_PATH = (
    ROOT
    / f"artifacts/evaluation/unified-jd-structured-span-v7-frozen-raw-failure-classification-findings-v1-{DATE}.md"
)
PREREGISTRATION_PATH = (
    ROOT / f"datasets/unified_jd_structured_span_v8_preregistration_v1_{DATE}.json"
)
PREREGISTRATION_FINDINGS_PATH = (
    ROOT
    / f"artifacts/evaluation/unified-jd-structured-span-v8-preregistration-findings-v1-{DATE}.md"
)
FREEZE_PATH = (
    ROOT / f"datasets/unified_jd_structured_span_v8_preregistration_freeze_v1_{DATE}.json"
)

RAW_INPUT_HASHES = {
    V7_DEVELOPMENT_RAW_PATH: (
        "c0be0b0af7a85a0b91b0161a2da37283adbf27cad1c36abecab3902d7a9c9145"
    ),
    V7_REGRESSION_RAW_PATH: (
        "f324985a9bdc3430181fae5a0e90ba4283f0b1c7d655910bcee48879d56c7377"
    ),
    V5_DEVELOPMENT_RAW_PATH: (
        "56f51ec6a54c0135478d22f9823373c67255e59fc5d90976fe9bed74bf9ec7ae"
    ),
    V6_REGRESSION_RAW_PATH: (
        "65bade675974b9aba1c1089ba77c7d4e3144a6275d2e288bb80fcf4fd86f830b"
    ),
    E9_RAW_PATH: (
        "496310332f5abbb4cf8a242be7d07c59262e144632fdc261734897d3bcdaf781"
    ),
}
CONTRACT_INPUT_HASHES = {
    V7_PREREGISTRATION_PATH: (
        "8e6fd8abfc67814de11bc6c7d1d4369b942b36c705283a4fcd6c0fc80c5c7afe"
    ),
    V7_SOURCE_FREEZE_PATH: (
        "656cbb81c03c83fc42632d88da08ca3f72c04651a27edf93a330dd8dc6d7d639"
    ),
    V4_PATH: "e09e056cab75e651937391ce5410e6df7c94477c85565abb1425bbe85cfcb094",
    V5_PATH: "8abdb1df73af8731caf565d0f0c74ad824302bf99cdae2b1c6a4e2e13ad541da",
    V6_PATH: "960d0d49f1c0b6b9fece8645ca5edc0a5874cf9ffb250e2f6c780cfcde11ccfd",
    V7_PATH: "4fa68d538c7494df3247d439bb499b4da314b1e83335e12f26c18e5357eb696a",
}

EXACT_FAMILIES = (
    "wrappers",
    "connector_labels",
    "coordination_members",
    "shared_scope_edges",
    "example_attachment_parents",
    "example_attachment_edges",
    "item_candidate_spans",
    "surface_projection",
    "example_projection",
)
OUTPUT_TO_GRAPH_FAMILY = {
    "wrappers": "wrappers",
    "connector_labels": "connector_labels",
    "coordination_members": "coordinations",
    "shared_scope_edges": "shared_scopes",
    "example_attachment_parents": "example_attachments",
    "example_attachment_edges": "example_attachments",
    "item_candidate_spans": "item_candidates",
    "surface_projection": "item_candidates",
    "example_projection": "example_attachments",
}
TRACE_PATTERN = re.compile(
    r"^v7\.selector:signal=(?P<signal>[^:]+):family=(?P<family>[^:]+):"
    r"envelope=(?P<envelope>[^:]+):origin=(?P<origin>[^:]+):"
    r"outcome=(?P<outcome>.+)$"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(value: Any) -> str:
    serialized = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _serialized(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def _write_new(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as output:
        output.write(value)


def _references(values: dict[Path, str]) -> dict[str, dict[str, str]]:
    return {
        path.stem: {"path": _relative(path), "sha256": expected}
        for path, expected in values.items()
    }


def _validate_inputs() -> dict[str, dict[str, Any]]:
    for path, expected in {**RAW_INPUT_HASHES, **CONTRACT_INPUT_HASHES}.items():
        actual = _sha256(path)
        if actual != expected:
            raise ValueError(
                f"frozen input hash mismatch for {_relative(path)}: "
                f"expected {expected}, got {actual}"
            )
    outputs = (
        CLASSIFICATION_PATH,
        CLASSIFICATION_FINDINGS_PATH,
        PREREGISTRATION_PATH,
        PREREGISTRATION_FINDINGS_PATH,
        FREEZE_PATH,
    )
    existing = [_relative(path) for path in outputs if path.exists()]
    if existing:
        raise FileExistsError(f"v8 preregistration output already exists: {existing}")
    if V8_PATH.exists():
        raise FileExistsError("v8 implementation exists before preregistration freeze")

    raw = {
        "v7_development": _load(V7_DEVELOPMENT_RAW_PATH),
        "v7_regression": _load(V7_REGRESSION_RAW_PATH),
        "v5_development": _load(V5_DEVELOPMENT_RAW_PATH),
        "v6_regression": _load(V6_REGRESSION_RAW_PATH),
        "e9": _load(E9_RAW_PATH),
    }
    for name in ("v7_development", "v7_regression", "v5_development", "v6_regression"):
        payload = raw[name]
        if payload["model_call_count"] != 0 or payload["network_call_count"] != 0:
            raise ValueError(f"{name} is not zero-model, zero-network frozen raw")
    e9 = raw["e9"]
    if e9["parser_executed"] or e9["v6_imported"]:
        raise ValueError("E9 raw is not an offline oracle artifact")
    if e9["model_call_count"] != 0 or e9["network_call_count"] != 0:
        raise ValueError("E9 raw is not zero-model, zero-network")
    if len(e9["records"]) != 9 or len(e9["controls"]) != 22:
        raise ValueError("E9 target/control population changed")
    return raw


def _span_key(span: dict[str, Any]) -> tuple[int, int, str]:
    return span["start"], span["end"], span["text"]


def _multiset(values: list[str]) -> list[list[Any]]:
    return [
        [value, count]
        for value, count in sorted(Counter(values).items(), key=lambda item: item[0])
    ]


def _member_id_to_span(parsed: dict[str, Any]) -> dict[str, tuple[int, int, str]]:
    result = {
        member["id"]: _span_key(member["span"])
        for member in parsed["item_candidates"]
    }
    for group in parsed["coordinations"]:
        result.update(
            {
                member["id"]: _span_key(member["span"])
                for member in group["members"]
            }
        )
    return result


def _full_snapshot(record: dict[str, Any]) -> dict[str, Any]:
    parsed = record["parsed_clause"]
    if parsed is None:
        raise ValueError(f"full graph missing for {record['id']}")
    member_spans = _member_id_to_span(parsed)
    return {
        "wrappers": sorted(
            [
                [
                    wrapper["kind"],
                    list(_span_key(wrapper["marker_span"])),
                    list(_span_key(wrapper["content_span"])),
                ]
                for wrapper in parsed["wrappers"]
            ]
        ),
        "connector_labels": sorted(
            [
                [list(_span_key(label["span"])), label["role"]]
                for label in parsed["connector_labels"]
            ]
        ),
        "coordination_members": sorted(
            [
                [group["role"], list(_span_key(member["span"]))]
                for group in parsed["coordinations"]
                for member in group["members"]
            ]
        ),
        "shared_scope_edges": sorted(
            [
                [
                    scope["kind"],
                    list(_span_key(scope["span"])),
                    list(member_spans[member_id]),
                ]
                for scope in parsed["shared_scopes"]
                for member_id in scope["applies_to_member_ids"]
                if member_id in member_spans
            ]
        ),
        "example_attachment_parents": sorted(
            [
                [
                    list(_span_key(attachment["cue_span"])),
                    list(_span_key(attachment["parent_span"])),
                ]
                for attachment in parsed["example_attachments"]
            ]
        ),
        "example_attachment_edges": sorted(
            [
                [
                    list(_span_key(attachment["cue_span"])),
                    list(_span_key(attachment["parent_span"])),
                    list(_span_key(example)),
                ]
                for attachment in parsed["example_attachments"]
                for example in attachment["example_spans"]
            ]
        ),
        "item_candidate_spans": sorted(
            [
                list(_span_key(candidate["span"]))
                for candidate in parsed["item_candidates"]
            ]
        ),
        "surface_projection": _multiset(record["items"]),
        "example_projection": _multiset(record["examples"]),
    }


def _projection_snapshot(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "surface_projection": _multiset(record["actual_items"]),
        "example_projection": _multiset(record["actual_examples"]),
    }


def _record_snapshot(record: dict[str, Any], cohort: str) -> dict[str, Any]:
    if cohort == "projection-60":
        return _projection_snapshot(record)
    return _full_snapshot(record)


def _records_by_id(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {record["id"]: record for record in records}


def _regression_index(payload: dict[str, Any]) -> dict[str, tuple[str, dict[str, Any]]]:
    result: dict[str, tuple[str, dict[str, Any]]] = {}
    for cohort, key in (
        ("legacy-20", "legacy_development"),
        ("revealed-external-20", "revealed_external"),
        ("projection-60", "projection_60"),
    ):
        for record in payload[key]["records"]:
            if record["id"] in result:
                raise ValueError(f"duplicate regression record id: {record['id']}")
            result[record["id"]] = (cohort, record)
    return result


def _trace_entries(record: dict[str, Any]) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for value in record.get("selector_trace", []):
        match = TRACE_PATTERN.fullmatch(value)
        if match is None:
            raise ValueError(f"invalid selector trace for {record['id']}: {value}")
        entries.append({"raw": value, **match.groupdict()})
    return entries


def _restoration_entry(
    entries: list[dict[str, str]], family: str
) -> dict[str, str] | None:
    values = [
        entry
        for entry in entries
        if entry["signal"] == "supported-v5"
        and entry["family"] == family
        and entry["outcome"] != "selected"
    ]
    if len(values) > 1:
        raise ValueError(f"multiple restoration traces for family {family}")
    return values[0] if values else None


def _selection_entry(
    entries: list[dict[str, str]], family: str
) -> dict[str, str] | None:
    values = [
        entry
        for entry in entries
        if entry["family"] == family and entry["outcome"] == "selected"
    ]
    if len(values) > 1:
        raise ValueError(f"multiple selection traces for family {family}")
    return values[0] if values else None


def _fired_signals(entries: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        entry
        for entry in entries
        if entry["family"] == "predicate" and entry["outcome"] == "fired"
    ]


def _classify_e6_exception(
    development: dict[str, Any], v5_reference: dict[str, Any]
) -> dict[str, Any]:
    errors = [record for record in development["records"] if record["error"]]
    if len(errors) != 1:
        raise ValueError(f"expected one v7 development exception, got {len(errors)}")
    record = errors[0]
    reference = _records_by_id(v5_reference["records"])[record["id"]]
    source = record["source_text"]
    e6_signature = (
        "\u4ee5\u4e0b" in source
        and "\u4f18\u5148" in source
        and (":" in source or "\uff1a" in source)
    )
    error_signature = "WrapperSpan" in record["error"] and "start" in record["error"]
    if not e6_signature or not error_signature:
        raise ValueError("the lone exception does not have the frozen E6/type signature")
    if record["selector_trace"] or reference["error"] is not None:
        raise ValueError("E6 exception did not occur before selector output")
    return {
        "classification": "E6-implementation-exception",
        "record_id": record["id"],
        "error": record["error"],
        "raw_observations": {
            "e6_source_signature_present": e6_signature,
            "wrapper_to_span_type_error_signature_present": error_signature,
            "selector_trace_count": len(record["selector_trace"]),
            "frozen_v5_reference_parse_succeeded": reference["error"] is None,
        },
        "interpretation": (
            "The E6 code path failed before routing produced a graph. This is a "
            "mechanical wrapper-versus-source-span implementation exception; the raw "
            "does not evaluate or falsify E6 semantics."
        ),
    }


def _classify_under_recall(
    development: dict[str, Any], v5_reference: dict[str, Any]
) -> dict[str, Any]:
    expected = _records_by_id(v5_reference["records"])
    records: list[dict[str, Any]] = []
    exact_non_error = 0
    family_causes: Counter[str] = Counter()
    family_failures: Counter[str] = Counter()
    primary_causes: Counter[str] = Counter()

    for actual_record in development["records"]:
        if actual_record["error"] is not None:
            continue
        actual = _full_snapshot(actual_record)
        reference = _full_snapshot(expected[actual_record["id"]])
        mismatched = [
            family for family in EXACT_FAMILIES if actual[family] != reference[family]
        ]
        if not mismatched:
            exact_non_error += 1
            continue

        entries = _trace_entries(actual_record)
        fired = _fired_signals(entries)
        family_rows: list[dict[str, Any]] = []
        for output_family in mismatched:
            graph_family = OUTPUT_TO_GRAPH_FAMILY[output_family]
            restoration = _restoration_entry(entries, graph_family)
            selected = _selection_entry(entries, graph_family)
            if restoration is None or selected is None:
                raise ValueError(
                    f"missing selector evidence for {actual_record['id']} {graph_family}"
                )
            if restoration["outcome"] == "unlicensed-delta":
                cause = "license-envelope-undercoverage"
            elif restoration["outcome"] == "veto:runtime-conflict":
                cause = "clause-global-runtime-conflict-veto"
            elif selected["origin"] == "v4":
                cause = "S2-v4-override-without-v5-delta"
            else:
                cause = "unclassified-restoration-under-recall"
            family_causes[cause] += 1
            family_failures[output_family] += 1
            family_rows.append(
                {
                    "output_family": output_family,
                    "graph_family": graph_family,
                    "cause": cause,
                    "restoration_outcome": restoration["outcome"],
                    "restoration_envelope": restoration["envelope"],
                    "selected_signal": selected["signal"],
                    "selected_origin": selected["origin"],
                }
            )

        if fired and any(
            row["cause"] == "clause-global-runtime-conflict-veto"
            for row in family_rows
        ):
            primary = "S2-global-veto-suppressed-supported-restoration"
        elif fired:
            primary = "S2-overrode-v5-v6-agreement"
        else:
            primary = "licensed-envelope-failed-to-cover-supported-v5-closure"
        primary_causes[primary] += 1
        records.append(
            {
                "record_id": actual_record["id"],
                "classification": "supported-v5-restoration-under-recall",
                "primary_cause": primary,
                "fired_conflict_signals": [entry["signal"] for entry in fired],
                "mismatched_families": mismatched,
                "family_evidence": family_rows,
            }
        )

    if len(development["records"]) != 20 or exact_non_error != 7 or len(records) != 12:
        raise ValueError(
            "unexpected development partition: "
            f"exact={exact_non_error}, under_recall={len(records)}"
        )
    expected_primary = {
        "licensed-envelope-failed-to-cover-supported-v5-closure": 4,
        "S2-global-veto-suppressed-supported-restoration": 7,
        "S2-overrode-v5-v6-agreement": 1,
    }
    if dict(primary_causes) != expected_primary:
        raise ValueError(f"unexpected under-recall causes: {dict(primary_causes)}")
    if family_causes["unclassified-restoration-under-recall"]:
        raise ValueError("an under-recall family lacks a frozen-raw explanation")
    return {
        "classification": "supported-v5-restoration-under-recall",
        "record_count": len(records),
        "exact_non_error_record_count": exact_non_error,
        "primary_cause_counts": dict(sorted(primary_causes.items())),
        "failed_family_counts": dict(sorted(family_failures.items())),
        "family_cause_counts": dict(sorted(family_causes.items())),
        "records": records,
        "interpretation": (
            "Restoration under-recall has two independent routing causes. Envelope "
            "licensing rejects supported transitive closure, while S2 either blocks "
            "all licensed families at clause scope or replaces a v5/v6-equal family."
        ),
    }


def _activation_class(mechanisms: set[str]) -> str:
    if mechanisms == {"E2-wrapper-boundary"}:
        return "E2-only-false-activation"
    if mechanisms == {"E3-region-first-connector-role"}:
        return "E3-only-false-activation"
    if mechanisms == {
        "E2-wrapper-boundary",
        "E3-region-first-connector-role",
    }:
        return "E2-plus-E3-false-activation"
    return "other-supported-v5-false-activation"


def _classify_control_activation(
    v7_regression: dict[str, Any],
    v6_regression: dict[str, Any],
    e9_raw: dict[str, Any],
) -> dict[str, Any]:
    actual_index = _regression_index(v7_regression)
    baseline_index = _regression_index(v6_regression)
    failed: list[dict[str, Any]] = []
    preserved: list[str] = []
    activation_counts: Counter[str] = Counter()
    family_failures: Counter[str] = Counter()

    for specification in e9_raw["controls"]:
        fixture_id = specification["id"]
        cohort = specification["cohort"]
        actual_cohort, actual_record = actual_index[fixture_id]
        baseline_cohort, baseline_record = baseline_index[fixture_id]
        if actual_cohort != cohort or baseline_cohort != cohort:
            raise ValueError(f"control cohort mismatch for {fixture_id}")
        actual = _record_snapshot(actual_record, cohort)
        baseline = _record_snapshot(baseline_record, cohort)
        if (
            _canonical_sha256(baseline_record)
            != specification["baseline_payload_sha256"]
        ):
            raise ValueError(f"control baseline hash mismatch for {fixture_id}")
        mismatched = [family for family in baseline if actual[family] != baseline[family]]
        if not mismatched:
            preserved.append(fixture_id)
            continue

        entries = _trace_entries(actual_record)
        fired = _fired_signals(entries)
        non_v6 = [
            entry
            for entry in entries
            if entry["outcome"] == "selected" and entry["origin"] != "v6"
        ]
        if fired:
            raise ValueError(
                f"control {fixture_id} changed with S1-S3 firing; expected restoration only"
            )
        if not non_v6 or any(entry["signal"] != "supported-v5" for entry in non_v6):
            raise ValueError(f"control {fixture_id} did not change via supported-v5")

        mechanisms: set[str] = set()
        restoration_evidence: list[dict[str, str]] = []
        for selected in non_v6:
            restoration = _restoration_entry(entries, selected["family"])
            if restoration is None or restoration["origin"] != "v5":
                raise ValueError(f"missing v5 activation trace for {fixture_id}")
            for mechanism in (
                "E2-wrapper-boundary",
                "E3-region-first-connector-role",
            ):
                if mechanism in restoration["outcome"]:
                    mechanisms.add(mechanism)
            restoration_evidence.append(
                {
                    "graph_family": selected["family"],
                    "activation_outcome": restoration["outcome"],
                    "activation_envelope": restoration["envelope"],
                }
            )
        activation_class = _activation_class(mechanisms)
        if activation_class == "other-supported-v5-false-activation":
            raise ValueError(f"unexpected control activation mechanisms: {mechanisms}")
        activation_counts[activation_class] += 1
        family_failures.update(mismatched)
        failed.append(
            {
                "record_id": fixture_id,
                "cohort": cohort,
                "classification": "control-supported-v5-false-activation",
                "activation_class": activation_class,
                "fired_conflict_signals": [],
                "mismatched_observable_families": mismatched,
                "non_v6_selected_graph_families": [
                    entry["family"] for entry in non_v6
                ],
                "restoration_evidence": restoration_evidence,
            }
        )

    if len(failed) != 15 or len(preserved) != 7:
        raise ValueError(
            f"unexpected control partition: failed={len(failed)}, preserved={len(preserved)}"
        )
    expected_classes = {
        "E2-only-false-activation": 2,
        "E2-plus-E3-false-activation": 4,
        "E3-only-false-activation": 9,
    }
    if dict(activation_counts) != expected_classes:
        raise ValueError(f"unexpected activation classes: {dict(activation_counts)}")
    return {
        "classification": "control-supported-v5-false-activation",
        "control_count": len(e9_raw["controls"]),
        "overactivated_control_count": len(failed),
        "preserved_control_count": len(preserved),
        "activation_class_counts": dict(sorted(activation_counts.items())),
        "failed_family_counts": dict(sorted(family_failures.items())),
        "records": failed,
        "preserved_control_ids": sorted(preserved),
        "interpretation": (
            "All control changes came from broad supported-v5 E2/E3 licensing. None "
            "came from S1-S3. Envelope containment therefore proves locality but not "
            "that a v5 delta is beneficial; a separate compatibility veto is required."
        ),
    }


def _build_classification(raw: dict[str, dict[str, Any]]) -> dict[str, Any]:
    e6 = _classify_e6_exception(raw["v7_development"], raw["v5_development"])
    under_recall = _classify_under_recall(
        raw["v7_development"], raw["v5_development"]
    )
    control_activation = _classify_control_activation(
        raw["v7_regression"], raw["v6_regression"], raw["e9"]
    )
    return {
        "analysis_version": (
            "unified-jd-structured-span-v7-frozen-raw-failure-classification-v1"
        ),
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "offline_frozen_raw_only_no_v7_rerun",
        "scope": {
            "input_kind": "frozen_raw_only",
            "parser_imported": False,
            "parser_executed": False,
            "development_rerun_count": 0,
            "regression_rerun_count": 0,
            "v7_source_modified": False,
            "threshold_or_gate_modified": False,
            "model_call_count": 0,
            "network_call_count": 0,
            "canonicalizer_work": False,
            "generalization_claim": False,
        },
        "inputs": _references(RAW_INPUT_HASHES),
        "summary": {
            "development_record_count": 20,
            "v5_exact_non_error_record_count": 7,
            "e6_implementation_exception_count": 1,
            "supported_v5_restoration_under_recall_count": 12,
            "e9_control_count": 22,
            "control_supported_v5_false_activation_count": 15,
            "preserved_control_count": 7,
            "classes_requested_are_separately_accounted": True,
        },
        "classes": {
            "E6-implementation-exception": e6,
            "supported-v5-restoration-under-recall": under_recall,
            "control-supported-v5-false-activation": control_activation,
        },
        "causal_interference_matrix": {
            "E6-wrapper-to-span-type-path": {
                "development_exception_records": 1,
                "development_under_recall_records": 0,
                "control_overactivation_records": 0,
            },
            "licensed-envelope-undercoverage": {
                "development_exception_records": 0,
                "development_under_recall_records": 4,
                "control_overactivation_records": 0,
            },
            "S2-clause-global-conflict-or-override": {
                "development_exception_records": 0,
                "development_under_recall_records": 8,
                "control_overactivation_records": 0,
            },
            "broad-E2-E3-restoration-activation": {
                "development_exception_records": 0,
                "development_under_recall_records": 0,
                "control_overactivation_records": 15,
            },
        },
        "decision": {
            "E6": "Treat as a typed-envelope implementation defect, not semantic failure.",
            "restoration": (
                "Replace clause-global family licensing with supported-witness closure "
                "over connected delta components."
            ),
            "controls": (
                "Add a compatibility veto independent of E2/E3 activation; source-span "
                "containment alone is insufficient."
            ),
            "conflicts": (
                "Apply S1-S3 only to their implicated component and family bundle; do "
                "not veto all supported restoration in the clause."
            ),
        },
    }


def _v8_mechanism() -> dict[str, Any]:
    return {
        "name": "component-scoped-restoration-with-independent-compatibility",
        "implementation_target": "src/domain/unified_jd_structured_spans_v8.py",
        "candidate_parsers": [
            "src/domain/unified_jd_structured_spans_v4.py",
            "src/domain/unified_jd_structured_spans_v5.py",
            "src/domain/unified_jd_structured_spans_v6.py",
        ],
        "v7_reuse_policy": (
            "Do not execute or import v7 as a candidate parser. Re-express only the "
            "frozen supported mechanisms and conflict predicates specified here, so "
            "the frozen E6 exception cannot be inherited."
        ),
        "selection_unit": (
            "One connected structural delta component and its minimal referential "
            "closure, never a whole clause and never an expected-output-selected node."
        ),
        "ordered_stages": [
            {
                "order": 1,
                "name": "load_frozen_candidate_graphs",
                "rule": (
                    "Obtain frozen v4, v5, and v6 graphs for identical parser inputs. "
                    "The selector receives only source characters, spans, graph roles, "
                    "references, and frozen parser provenance."
                ),
            },
            {
                "order": 2,
                "name": "normalize_typed_envelope_inputs",
                "rule": (
                    "Every envelope constructor accepts SourceSpan values only. Convert "
                    "a wrapper explicitly to its marker and content spans before E6 "
                    "envelope construction; reject any structural object passed as a span."
                ),
                "frozen_E6_signature": (
                    "Keep the prior deictic-header, separator, direct open-list, and "
                    "priority-tail requirements unchanged."
                ),
            },
            {
                "order": 3,
                "name": "build_delta_component_graph",
                "rule": (
                    "Represent every v5-v6 and v4-v6 node delta explicitly. Connect "
                    "nodes only by exact shared boundary, wrapper ownership, coordination "
                    "membership, scope target, attachment edge, or exact producer span. "
                    "Plain region co-membership and broad envelope containment do not "
                    "create an edge."
                ),
            },
            {
                "order": 4,
                "name": "certify_supported_v5_activation",
                "rule": (
                    "A v5 component is activation-eligible only when it contains a "
                    "frozen E2, E3, E6, or E7 witness and the changed nodes are in the "
                    "witness's structural dependency closure. E2 requires a changed "
                    "wrapper boundary used by a changed member, scope, attachment, or "
                    "producer. E3 requires a changed connector role corroborated by the "
                    "same changed coordination or attachment topology. E6 and E7 keep "
                    "their previously frozen exact structural signatures."
                ),
                "forbidden_shortcut": (
                    "A node is not licensed merely because its span lies inside a "
                    "witness envelope."
                ),
            },
            {
                "order": 5,
                "name": "apply_independent_v6_compatibility_veto",
                "rule": (
                    "Even an activation-eligible component stays v6 if v5 deletes a "
                    "complete v6 surface partition, performs an unsupported surface-to-"
                    "example role transfer, loses or reparents a protected attachment, "
                    "contaminates an atomic producer with a wrapper or operator, changes "
                    "a scope-bearing atom outside dependency closure, or fails to repair "
                    "the local structural inconsistency named by its witness."
                ),
                "independence": (
                    "Activation asks whether a supported mechanism is present; "
                    "compatibility separately asks whether applying it conserves every "
                    "unimplicated v6 producer and reference. Both must pass."
                ),
            },
            {
                "order": 6,
                "name": "restore_supported_component_closure",
                "rule": (
                    "Use v5 only for a certified, compatible component and its minimal "
                    "reference closure. Partial family deltas outside that component stay "
                    "v6; a separate certified component is not rejected because another "
                    "component in the same family is unlicensed."
                ),
            },
            {
                "order": 7,
                "name": "route_conflicts_component_locally",
                "rule": (
                    "Evaluate the frozen S3, S1, and S2 predicates independently per "
                    "connected component. A conflict may route only its registered family "
                    "bundle and may not veto disjoint supported restoration. Within the "
                    "same component, a certified compatible supported restoration defeats "
                    "S2; otherwise the frozen S3, S1, S2 order is retained."
                ),
                "S2_specificity_guard": (
                    "S2 may replace a producer only when the v4 counterpart is a complete "
                    "source-covering counterpart for the minimal changed component and "
                    "the replacement preserves all exact v6 families outside it."
                ),
            },
            {
                "order": 8,
                "name": "merge_validate_and_project_once",
                "rule": (
                    "Rebase ids by exact source span, reject dangling or multiply-owned "
                    "references, validate anchoring and unique ids, then derive both "
                    "projections exactly once from the merged graph."
                ),
            },
        ],
        "precedence": [
            "source anchoring, typed spans, graph validity, and reference closure",
            "independent v6 compatibility veto",
            "certified compatible supported-v5 component",
            "S3 conflict bundle outside certified supported components",
            "S1 conflict bundle outside certified supported components",
            "S2 producer replacement outside certified supported components",
            "frozen v6 default",
        ],
        "runtime_prohibitions": [
            "record identifiers, file paths, expected outputs, or evaluation metadata",
            "job metadata or source-origin dispatch",
            "memorized long source substrings or named-entity exceptions",
            "surface or example string canonicalization",
            "model or network calls",
            "whole-clause veto or whole-family replacement caused only by containment",
        ],
    }


def _build_preregistration(
    classification: dict[str, Any], v7_preregistration: dict[str, Any]
) -> dict[str, Any]:
    mechanism = _v8_mechanism()
    runtime_text = json.dumps(mechanism, ensure_ascii=False).casefold()
    forbidden_runtime_text = (
        "structured-v5-mechanism-dev",
        "structured-external",
        "surface-holdout",
        "canonical-v1",
        "job_title",
        "http://",
        "https://",
    )
    hits = [value for value in forbidden_runtime_text if value in runtime_text]
    if hits:
        raise ValueError(f"forbidden runtime specialization in v8 mechanism: {hits}")

    under_recall_ids = [
        record["record_id"]
        for record in classification["classes"][
            "supported-v5-restoration-under-recall"
        ]["records"]
    ]
    false_activation_ids = [
        record["record_id"]
        for record in classification["classes"][
            "control-supported-v5-false-activation"
        ]["records"]
    ]
    e6_id = classification["classes"]["E6-implementation-exception"]["record_id"]
    prior_gates = v7_preregistration["acceptance_gates"]
    prior_behavior_gates = {
        name: gate for name, gate in prior_gates.items() if not name.startswith("G8-")
    }
    return {
        "preregistration_version": "unified-jd-structured-span-v8-preregistration-v1",
        "created_at": DATE,
        "status": "frozen_before_v8_implementation",
        "scope": {
            "task": (
                "typed_E6_repair_component_scoped_supported_restoration_and_control_compatibility"
            ),
            "classification_basis": "frozen_raw_only",
            "development_data_status": "all_inputs_revealed_not_holdout",
            "generalization_claim": False,
            "v4_v5_v6_v7_modification_allowed": False,
            "v7_rerun_allowed": False,
            "gate_or_threshold_relaxation_allowed": False,
            "runtime_record_or_metadata_dispatch_allowed": False,
            "runtime_category_employer_title_url_dispatch_allowed": False,
            "canonicalizer_work_allowed": False,
            "model_calls_allowed": False,
            "network_calls_allowed": False,
        },
        "inputs": {
            "frozen_raw": _references(RAW_INPUT_HASHES),
            "frozen_contract_and_sources": _references(CONTRACT_INPUT_HASHES),
            "offline_classification": {
                "path": _relative(CLASSIFICATION_PATH),
                "sha256": _sha256(CLASSIFICATION_PATH),
            },
        },
        "offline_diagnostic_basis": {
            "E6_implementation_exception_count": 1,
            "supported_v5_restoration_under_recall_count": 12,
            "control_supported_v5_false_activation_count": 15,
            "preserved_control_count": 7,
            "causal_read": (
                "The exception, restoration under-recall, and control false activation "
                "are separate mechanisms and must not share a single threshold or veto."
            ),
        },
        "v8_mechanism": mechanism,
        "acceptance_gates": {
            "G0-frozen-input-validity-and-zero-calls": {
                "requirements": [
                    "All frozen input hashes and frozen v4-v7 source hashes match.",
                    "Every v8 output parses, validates, is source-anchored, and has closed references.",
                    "Model and network call counts are zero.",
                ]
            },
            "G1-v7-behavioral-gates-not-weakened": {
                "source": {
                    "path": _relative(V7_PREREGISTRATION_PATH),
                    "sha256": CONTRACT_INPUT_HASHES[V7_PREREGISTRATION_PATH],
                    "included_gate_keys": list(prior_behavior_gates),
                    "canonical_sha256": _canonical_sha256(prior_behavior_gates),
                },
                "requirement": (
                    "Run every v7 G0-G7 behavioral criterion with identical operators "
                    "and numeric thresholds; all must pass. The implementation-specific "
                    "v7 G8 fixed trace shape is superseded, not weakened, by the v8 G9 "
                    "component-trace, static-audit, and test requirements."
                ),
            },
            "G2-three-class-resolution": {
                "all_criteria_conjunctive": True,
                "E6_implementation_exception": {
                    "record_ids": [e6_id],
                    "required_parse_error_count": 0,
                    "required_exact_to_frozen_v5_count": 1,
                },
                "supported_v5_restoration_under_recall": {
                    "record_ids": under_recall_ids,
                    "required_exact_to_frozen_v5_count": 12,
                },
                "control_supported_v5_false_activation": {
                    "record_ids": false_activation_ids,
                    "required_exact_to_frozen_v6_count": 15,
                    "required_non_v6_selection_count": 0,
                },
            },
            "G3-v5-mechanism-preservation": {
                "fixture_count": 20,
                "required_exact_fixture_count": 20,
                "reference": {
                    "path": _relative(V5_DEVELOPMENT_RAW_PATH),
                    "sha256": RAW_INPUT_HASHES[V5_DEVELOPMENT_RAW_PATH],
                },
                "requirement": (
                    "20/20 exact on wrappers, connector roles, coordination members, "
                    "scope edges, attachment parents and edges, item candidates, and "
                    "both projections."
                ),
            },
            "G4-E9-residual-preservation": {
                "target_record_count": 9,
                "required_exact_record_count": 9,
                "required_corrected_family_count": 16,
                "required_retained_exact_v6_family_count": 9,
            },
            "G5-control-preservation": {
                "control_count": 22,
                "required_exact_and_byte_identical_to_v6_count": 22,
            },
            "G6-legacy-effective-exact": {
                "fixture_count": 20,
                "required_exact_fixture_count": 20,
            },
            "G7-projection-regression-exact": {
                "fixture_count": 60,
                "required_exact_fixture_count": 60,
            },
            "G8-revealed-external-non-regression": {
                "fixture_count": 20,
                "requirements": [
                    "Every aggregate primary metric is no worse than frozen v4 and frozen v6.",
                    "Every per-record primary-layer difference is no greater than frozen v4 and frozen v6.",
                    "The previously registered open-list wrapper regression remains zero.",
                ],
            },
            "G9-selector-and-test-audit": {
                "requirements": [
                    "All existing structured-span tests pass unchanged.",
                    "Synthetic tests cover the typed E6 path, each activation witness, each compatibility veto, component separation, overlap precedence, and reference closure.",
                    "Every trace records component envelope, witness, compatibility result, family origin, and final selection.",
                    "A static audit rejects runtime record identifiers, evaluation metadata, job metadata dispatch, long source literals, canonicalization, and network or model imports.",
                ]
            },
        },
        "evaluation_protocol": {
            "all_criteria_conjunctive": True,
            "threshold_or_operator_change_after_freeze_allowed": False,
            "source_freeze_before_any_v8_record_execution": True,
            "preflight_must_not_import_or_execute_v8": True,
            "raw_written_before_report": True,
            "write_new_outputs_only": True,
            "v8_development_run_count": 1,
            "v8_regression_run_count": 1,
            "rerun_after_failure_allowed": False,
            "failure_policy": (
                "Freeze failed v8 raw and report. Do not modify or rerun v8, add an "
                "exception, or relax a gate; diagnose offline and preregister a new version."
            ),
        },
        "post_gate_protocol": {
            "on_pass": (
                "Freeze v8 and collect a separately preregistered fresh external blind "
                "holdout before any canonicalizer work."
            ),
            "on_fail": (
                "Keep the current production reference and use only frozen raw for the "
                "next diagnosis."
            ),
            "canonicalizer_allowed_after_development_pass": False,
            "canonicalizer_unlock_condition": (
                "Only a separately frozen fresh external blind-holdout pass."
            ),
        },
    }


def _classification_findings(value: dict[str, Any]) -> str:
    under = value["classes"]["supported-v5-restoration-under-recall"]
    controls = value["classes"]["control-supported-v5-false-activation"]
    lines = [
        "# Frozen v7 raw-only failure classification",
        "",
        "## Result",
        "",
        "The three requested failure classes are distinct in the frozen raw:",
        "",
        "- `E6-implementation-exception`: 1 record. It fails before any selector trace and does not test E6 semantics.",
        f"- `supported-v5-restoration-under-recall`: {under['record_count']} records beyond the exception.",
        f"- `control-supported-v5-false-activation`: {controls['overactivated_control_count']} of 22 controls; 7 remain v6-identical.",
        "",
        "## Under-recall causes",
        "",
    ]
    for cause, count in under["primary_cause_counts"].items():
        lines.append(f"- `{cause}`: {count} records.")
    lines.extend(["", "## False-activation causes", ""])
    for cause, count in controls["activation_class_counts"].items():
        lines.append(f"- `{cause}`: {count} controls.")
    lines.extend(
        [
            "",
            "No failed control fired S1, S2, or S3. Every control regression came from supported-v5 E2/E3 licensing, so conflict-signal tuning cannot fix that class.",
            "",
            "## Consequence for v8",
            "",
            "V8 must fix the typed E6 envelope path, replace containment-only restoration with structural dependency closure, add a compatibility veto independent of activation, and scope S1-S3 to the implicated component instead of the whole clause.",
            "",
            "This is an offline revealed-data diagnosis, not a generalization result. V7 was not imported, changed, or rerun; model and network calls are zero.",
            "",
        ]
    )
    return "\n".join(lines)


def _preregistration_findings() -> str:
    return """# V8 structured-span preregistration

## Frozen mechanism

V8 is limited to a typed, component-scoped router over the frozen v4-v6 candidate graphs. It does not execute v7, change frozen parsers, add parsing semantics, canonicalize output, or inspect record/job metadata.

Activation and compatibility are separate decisions. An E2/E3/E6/E7 witness licenses only its structural dependency closure, and v5 is still vetoed when that component destroys an unimplicated v6 producer, attachment, scope, or reference. S1-S3 operate only outside certified compatible restoration components.

## Frozen gates

- The v7 G0-G7 behavioral gate contract is inherited without changing an operator or numeric threshold. The implementation-specific v7 G8 trace shape is replaced by stricter v8 component-trace, static-audit, and test requirements.
- The E6 exception must parse and equal frozen v5; all 12 other under-recall records must equal frozen v5.
- All 15 false-activated controls must return to frozen v6, and all 22 controls must be byte-identical to v6.
- Mechanism development remains 20/20, E9 remains 9/9 with 16/16 corrected and 9/9 retained families, legacy remains 20/20, and projection remains 60/60.
- Revealed external data may regress against neither frozen v4 nor frozen v6, per record and in aggregate.

## Boundary

This step only freezes the v8 preregistration. Implementation, source freeze, and one-time gates are separate; canonicalizer work remains locked even after a development pass until a fresh external blind holdout passes.
"""


def main() -> int:
    raw = _validate_inputs()
    classification = _build_classification(raw)
    _write_new(CLASSIFICATION_PATH, _serialized(classification))
    _write_new(CLASSIFICATION_FINDINGS_PATH, _classification_findings(classification))

    v7_preregistration = _load(V7_PREREGISTRATION_PATH)
    preregistration = _build_preregistration(classification, v7_preregistration)
    _write_new(PREREGISTRATION_PATH, _serialized(preregistration))
    _write_new(PREREGISTRATION_FINDINGS_PATH, _preregistration_findings())

    freeze = {
        "freeze_version": "unified-jd-structured-span-v8-preregistration-freeze-v1",
        "frozen_at": datetime.now(UTC).isoformat(),
        "status": "frozen_before_v8_implementation",
        "artifacts": {
            "classification": {
                "path": _relative(CLASSIFICATION_PATH),
                "sha256": _sha256(CLASSIFICATION_PATH),
            },
            "classification_findings": {
                "path": _relative(CLASSIFICATION_FINDINGS_PATH),
                "sha256": _sha256(CLASSIFICATION_FINDINGS_PATH),
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
        },
        "frozen_inputs": {
            "raw": _references(RAW_INPUT_HASHES),
            "contracts_and_sources": _references(CONTRACT_INPUT_HASHES),
        },
        "checks": {
            "v8_existed_at_freeze": False,
            "classification_used_frozen_raw_only": True,
            "v7_imported_or_executed": False,
            "v7_modified_or_rerun": False,
            "E6_implementation_exception_count": 1,
            "supported_v5_restoration_under_recall_count": 12,
            "control_supported_v5_false_activation_count": 15,
            "all_22_controls_required_v6_identical": True,
            "old_gate_or_threshold_weakened": False,
            "model_call_count": 0,
            "network_call_count": 0,
            "canonicalizer_allowed": False,
        },
        "immutability": (
            "Any change to a typed-span rule, component edge, activation witness, "
            "compatibility veto, conflict precedence, gate, threshold, or frozen input "
            "requires a new preregistration before implementation or execution."
        ),
        "next_allowed_action": (
            "Implement only the frozen v8 mechanism and synthetic tests, freeze source "
            "and evaluator, then execute development and regression gates exactly once."
        ),
    }
    _write_new(FREEZE_PATH, _serialized(freeze))
    print(
        json.dumps(
            {
                "classification": {
                    "path": _relative(CLASSIFICATION_PATH),
                    "sha256": _sha256(CLASSIFICATION_PATH),
                    "summary": classification["summary"],
                },
                "preregistration": {
                    "path": _relative(PREREGISTRATION_PATH),
                    "sha256": _sha256(PREREGISTRATION_PATH),
                },
                "freeze": {
                    "path": _relative(FREEZE_PATH),
                    "sha256": _sha256(FREEZE_PATH),
                },
                "v8_existed_at_freeze": False,
                "v7_rerun_count": 0,
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
