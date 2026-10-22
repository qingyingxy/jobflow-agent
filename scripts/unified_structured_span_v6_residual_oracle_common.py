from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATE = "2026-09-05"
PREREGISTRATION_PATH = (
    ROOT
    / f"datasets/unified_jd_structured_span_v6_residual_oracles_preregistration_v1_{DATE}.json"
)
PREREGISTRATION_FREEZE_PATH = (
    ROOT
    / f"datasets/unified_jd_structured_span_v6_residual_oracles_preregistration_freeze_v1_{DATE}.json"
)
SOURCE_FREEZE_PATH = (
    ROOT
    / f"datasets/unified_jd_structured_span_v6_residual_oracles_source_freeze_v1_{DATE}.json"
)
V6_RAW_PATH = (
    ROOT
    / f"artifacts/evaluation/unified-jd-structured-span-v6-regression-raw-v1-{DATE}.json"
)
V6_REPORT_PATH = (
    ROOT
    / f"artifacts/evaluation/unified-jd-structured-span-v6-development-regression-report-v1-{DATE}.json"
)
V5_RAW_PATH = (
    ROOT
    / f"artifacts/evaluation/unified-jd-structured-span-v5-regression-raw-v1-{DATE}.json"
)
CLASSIFICATION_PATH = (
    ROOT
    / f"artifacts/evaluation/unified-jd-structured-span-v5-frozen-regression-classification-v1-{DATE}.json"
)
V4_RAW_PATH = (
    ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-development-v4-raw-v1-2026-09-04.json"
)
V6_SOURCE_FREEZE_PATH = (
    ROOT / f"datasets/unified_jd_structured_span_v6_source_freeze_v1_{DATE}.json"
)

EXPECTED_HASHES = {
    PREREGISTRATION_PATH: (
        "1c5ebe4ff6b12824a2e2ae1dc71e2618509755875c80a95b0cabda41e91a5a23"
    ),
    PREREGISTRATION_FREEZE_PATH: (
        "796115abee17f95907d2cde09fbc209c437fda3d1758bdccbb758901cd464c4c"
    ),
    V6_RAW_PATH: "65bade675974b9aba1c1089ba77c7d4e3144a6275d2e288bb80fcf4fd86f830b",
    V6_REPORT_PATH: (
        "65a23a95a5fd812fbffbef9e8285cf70f29fa87b0fdf3ade42dec07dfeaefb5d"
    ),
    V5_RAW_PATH: "d386a0e0e2e3834abf9c033a54702b7b4a12d81eee3f181605725b8e64819285",
    CLASSIFICATION_PATH: (
        "e42741673adeca13bdcbadd5464297ba17bc136b1052d7be01c23ed9117f47fa"
    ),
    V4_RAW_PATH: "8513bc0e1db960f1e0928d7d8707e4f3f0a314a9a921ad7a1b24875e341ad9d7",
    V6_SOURCE_FREEZE_PATH: (
        "3e6a380b4ec91abc48fcd3f813bc4d83b8044b31990074b90f758e32639654e3"
    ),
}

ATTACHMENT_FAMILIES = (
    "example_attachment_parents",
    "example_attachment_edges",
    "example_projection",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_sha256(value: Any) -> str:
    serialized = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def write_new_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as output:
        output.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def write_new_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as output:
        output.write(value)


def validate_hashes() -> None:
    for path, expected in EXPECTED_HASHES.items():
        actual = sha256(path)
        if actual != expected:
            raise ValueError(f"frozen input hash mismatch for {relative(path)}")


def validate_source_freeze() -> dict[str, Any]:
    freeze = load(SOURCE_FREEZE_PATH)
    if freeze["status"] != "v6_residual_oracle_runners_frozen_before_execution":
        raise ValueError("residual oracle source freeze status is invalid")
    for reference in freeze["artifacts"].values():
        path = ROOT / reference["path"]
        if sha256(path) != reference["sha256"]:
            raise ValueError(f"frozen runner hash mismatch for {reference['path']}")
    return freeze


def load_frozen_inputs() -> dict[str, dict[str, Any]]:
    validate_hashes()
    preregistration = load(PREREGISTRATION_PATH)
    if preregistration["status"] != "frozen_before_oracle_implementation_and_execution":
        raise ValueError("residual oracle preregistration status is invalid")
    if preregistration["population"]["v6_unresolved_target_count"] != 9:
        raise ValueError("target count changed")
    if preregistration["population"]["v6_resolved_control_count"] != 22:
        raise ValueError("control count changed")
    return {
        "preregistration": preregistration,
        "v6_raw": load(V6_RAW_PATH),
        "v6_report": load(V6_REPORT_PATH),
        "v5_raw": load(V5_RAW_PATH),
        "classification": load(CLASSIFICATION_PATH),
        "v4_raw": load(V4_RAW_PATH),
    }


def _span_key(span: dict[str, Any]) -> tuple[int, int, str]:
    return span["start"], span["end"], span["text"]


def _multiset(values: list[str]) -> list[list[Any]]:
    return [
        [value, count]
        for value, count in sorted(Counter(values).items(), key=lambda item: item[0])
    ]


def _member_id_to_span(parsed: dict[str, Any]) -> dict[str, tuple[int, int, str]]:
    result = {
        member["id"]: _span_key(member["span"]) for member in parsed["item_candidates"]
    }
    for group in parsed["coordinations"]:
        result.update(
            {member["id"]: _span_key(member["span"]) for member in group["members"]}
        )
    return result


def full_snapshot(record: dict[str, Any]) -> dict[str, Any]:
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


def projection_snapshot(record: dict[str, Any], *, expected: bool) -> dict[str, Any]:
    items_key = "expected_items" if expected else "actual_items"
    examples_key = "expected_examples" if expected else "actual_examples"
    return {
        "surface_projection": _multiset(record[items_key]),
        "example_projection": _multiset(record[examples_key]),
    }


def _records_by_id(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {record["id"]: record for record in records}


def baseline_record(
    inputs: dict[str, dict[str, Any]], cohort: str, fixture_id: str
) -> dict[str, Any]:
    raw = inputs["v6_raw"]
    if cohort == "legacy-20":
        return _records_by_id(raw["legacy_development"]["records"])[fixture_id]
    if cohort == "projection-60":
        return _records_by_id(raw["projection_60"]["records"])[fixture_id]
    if cohort == "revealed-external-20":
        return _records_by_id(raw["revealed_external"]["records"])[fixture_id]
    raise ValueError(f"unsupported cohort: {cohort}")


def target_snapshots(
    inputs: dict[str, dict[str, Any]], cohort: str, fixture_id: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    baseline = baseline_record(inputs, cohort, fixture_id)
    if cohort == "projection-60":
        return (
            projection_snapshot(baseline, expected=False),
            projection_snapshot(baseline, expected=True),
        )
    if cohort == "legacy-20":
        reference = _records_by_id(inputs["v4_raw"]["records"])[fixture_id]
        return full_snapshot(baseline), full_snapshot(reference)
    raise ValueError(f"target cohort has no frozen reference: {cohort}")


def resolution_map(report: dict[str, Any]) -> dict[str, bool]:
    result: dict[str, bool] = {}
    cohorts = report["gates"]["G8-classified-regression-resolution"]["cohorts"]
    for cohort in cohorts.values():
        for fixture_id, resolved in cohort["cases"].items():
            if fixture_id in result and result[fixture_id] != resolved:
                raise ValueError(f"ambiguous resolution status for {fixture_id}")
            result[fixture_id] = resolved
    return result


def validate_population(inputs: dict[str, dict[str, Any]]) -> None:
    preregistration = inputs["preregistration"]
    resolved = resolution_map(inputs["v6_report"])
    targets = preregistration["population"]["target_observations"]
    controls = preregistration["population"]["control_observations"]
    if any(resolved[item["id"]] for item in targets):
        raise ValueError("a preregistered target is no longer unresolved")
    if any(not resolved[item["id"]] for item in controls):
        raise ValueError("a preregistered control is no longer resolved")
    if len({item["id"] for item in (*targets, *controls)}) != 31:
        raise ValueError("target and control observations are not a 31-case partition")


def control_anchors(inputs: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "cohort": item["cohort"],
            "id": item["id"],
            "baseline_payload_sha256": json_sha256(
                baseline_record(inputs, item["cohort"], item["id"])
            ),
            "baseline_resolved": True,
        }
        for item in inputs["preregistration"]["population"]["control_observations"]
    ]


def mismatched_families(actual: dict[str, Any], reference: dict[str, Any]) -> list[str]:
    if set(actual) != set(reference):
        raise ValueError("actual and reference expose different observable families")
    return sorted(key for key in actual if actual[key] != reference[key])


def snapshot_exact(actual: dict[str, Any], reference: dict[str, Any]) -> bool:
    return actual == reference
