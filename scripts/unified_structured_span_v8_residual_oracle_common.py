from __future__ import annotations

import ast
import hashlib
import json
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATE = "2026-09-05"
PREREGISTRATION_PATH = (
    ROOT
    / f"datasets/unified_jd_structured_span_v8_residual_oracles_preregistration_v1_{DATE}.json"
)
PREREGISTRATION_FREEZE_PATH = (
    ROOT
    / f"datasets/unified_jd_structured_span_v8_residual_oracles_preregistration_freeze_v1_{DATE}.json"
)
V8_DEVELOPMENT_RAW_PATH = (
    ROOT
    / f"artifacts/evaluation/unified-jd-structured-span-v8-mechanism-development-raw-v1-{DATE}.json"
)
V8_REGRESSION_RAW_PATH = (
    ROOT
    / f"artifacts/evaluation/unified-jd-structured-span-v8-regression-raw-v1-{DATE}.json"
)
V8_OFFLINE_REPORT_PATH = (
    ROOT
    / f"artifacts/evaluation/unified-jd-structured-span-v8-frozen-raw-offline-gates-v1-{DATE}.json"
)
V8_POSTMORTEM_PATH = (
    ROOT
    / f"artifacts/evaluation/unified-jd-structured-span-v8-one-time-execution-postmortem-v1-{DATE}.json"
)
V8_SOURCE_FREEZE_PATH = (
    ROOT / f"datasets/unified_jd_structured_span_v8_source_freeze_v1_{DATE}.json"
)
V8_PREREGISTRATION_PATH = (
    ROOT / f"datasets/unified_jd_structured_span_v8_preregistration_v1_{DATE}.json"
)
V8_PREREGISTRATION_FREEZE_PATH = (
    ROOT
    / f"datasets/unified_jd_structured_span_v8_preregistration_freeze_v1_{DATE}.json"
)
V5_MECHANISM_RAW_PATH = (
    ROOT
    / f"artifacts/evaluation/unified-jd-structured-span-v5-mechanism-development-v5-raw-v1-{DATE}.json"
)
V6_REGRESSION_RAW_PATH = (
    ROOT
    / f"artifacts/evaluation/unified-jd-structured-span-v6-regression-raw-v1-{DATE}.json"
)
V7_REGRESSION_RAW_PATH = (
    ROOT
    / f"artifacts/evaluation/unified-jd-structured-span-v7-regression-raw-v1-{DATE}.json"
)
E9_SIGNAL_PATH = (
    ROOT
    / f"artifacts/evaluation/unified-jd-structured-span-v6-e9-runtime-signal-analysis-v1-{DATE}.json"
)

EXPECTED_PREREGISTRATION_HASH = (
    "36314c3079aefe8c244bd99820ed6f68aa6579551770a0f491a41ee960c38f7b"
)
EXPECTED_PREREGISTRATION_FREEZE_HASH = (
    "99e8a37e8d81961f6ababab3e040b275cd77d550b738ce3b70b671ea1d079779"
)

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
GRAPH_FAMILIES = (
    "wrappers",
    "connector_labels",
    "coordinations",
    "shared_scopes",
    "example_attachments",
    "item_candidates",
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


def experiment_plan(
    preregistration: dict[str, Any], experiment_id: str
) -> dict[str, Any]:
    return next(
        experiment
        for experiment in preregistration["experiments"]
        if experiment["id"] == experiment_id
    )


def validate_frozen_inputs() -> dict[str, dict[str, Any]]:
    if sha256(PREREGISTRATION_PATH) != EXPECTED_PREREGISTRATION_HASH:
        raise ValueError("residual-oracle preregistration hash changed")
    if sha256(PREREGISTRATION_FREEZE_PATH) != EXPECTED_PREREGISTRATION_FREEZE_HASH:
        raise ValueError("residual-oracle preregistration freeze hash changed")
    preregistration = load(PREREGISTRATION_PATH)
    freeze = load(PREREGISTRATION_FREEZE_PATH)
    if preregistration["status"] != "frozen_before_oracle_implementation_and_execution":
        raise ValueError("residual-oracle preregistration status is invalid")
    if freeze["status"] != "frozen_before_oracle_implementation_and_execution":
        raise ValueError("residual-oracle preregistration freeze status is invalid")
    for name, reference in preregistration["inputs"].items():
        path = ROOT / reference["path"]
        if sha256(path) != reference["sha256"]:
            raise ValueError(f"frozen input hash mismatch: {name}")
    return {
        "preregistration": preregistration,
        "v8_development": load(V8_DEVELOPMENT_RAW_PATH),
        "v8_regression": load(V8_REGRESSION_RAW_PATH),
        "v8_offline_report": load(V8_OFFLINE_REPORT_PATH),
        "v8_postmortem": load(V8_POSTMORTEM_PATH),
        "v5_mechanism": load(V5_MECHANISM_RAW_PATH),
        "v6_regression": load(V6_REGRESSION_RAW_PATH),
        "v7_regression": load(V7_REGRESSION_RAW_PATH),
        "e9_signal": load(E9_SIGNAL_PATH),
    }


def validate_source_freeze(path: Path, experiment_id: str) -> dict[str, Any]:
    freeze = load(path)
    if freeze["status"] != "offline_oracle_runner_frozen_before_execution":
        raise ValueError("oracle runner source freeze status is invalid")
    if freeze["experiment_id"] != experiment_id:
        raise ValueError("oracle source freeze belongs to another experiment")
    for reference in freeze["artifacts"].values():
        artifact = ROOT / reference["path"]
        if sha256(artifact) != reference["sha256"]:
            raise ValueError(f"frozen runner artifact changed: {reference['path']}")
    return freeze


def static_import_audit(paths: tuple[Path, ...]) -> dict[str, Any]:
    imported: set[str] = set()
    dynamic_import_lines: list[int] = []
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in {"__import__", "eval", "exec"}
            ):
                dynamic_import_lines.append(node.lineno)
    forbidden = sorted(
        module
        for module in imported
        if module == "src"
        or module.startswith("src.")
        or "unified_jd_structured_spans" in module
    )
    return {
        "passed": not forbidden and not dynamic_import_lines,
        "forbidden_imports": forbidden,
        "dynamic_import_lines": dynamic_import_lines,
    }


def records_by_id(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {record["id"]: record for record in raw["records"]}


def regression_record(
    regression: dict[str, Any], cohort: str, record_id: str
) -> dict[str, Any]:
    keys = {
        "legacy-20": "legacy_development",
        "revealed-external-20": "revealed_external",
        "projection-60": "projection_60",
    }
    try:
        return records_by_id(regression[keys[cohort]])[record_id]
    except KeyError as error:
        raise ValueError(f"unknown regression record: {cohort}/{record_id}") from error


def _span_key(span: dict[str, Any]) -> tuple[int, int, str]:
    return span["start"], span["end"], span["text"]


def _span_bounds(span: dict[str, Any]) -> tuple[int, int]:
    return span["start"], span["end"]


def _multiset(values: list[str]) -> list[list[Any]]:
    return [
        [value, count]
        for value, count in sorted(Counter(values).items(), key=lambda item: item[0])
    ]


def _member_id_to_span(parsed: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result = {
        member["id"]: deepcopy(member["span"]) for member in parsed["item_candidates"]
    }
    for group in parsed["coordinations"]:
        result.update(
            {member["id"]: deepcopy(member["span"]) for member in group["members"]}
        )
    return result


def normalize_graph(parsed: dict[str, Any]) -> dict[str, Any]:
    member_spans = _member_id_to_span(parsed)
    return {
        "source_text": parsed["source_text"],
        "category": parsed["category"],
        "protected_spans": deepcopy(parsed["protected_spans"]),
        "segments": deepcopy(parsed["segments"]),
        "wrappers": deepcopy(parsed["wrappers"]),
        "connector_labels": deepcopy(parsed["connector_labels"]),
        "coordinations": [
            {
                "role": group["role"],
                "kind": group["kind"],
                "connector_spans": deepcopy(group["connector_spans"]),
                "members": [
                    {
                        "span": deepcopy(member["span"]),
                        "segment_index": member["segment_index"],
                    }
                    for member in group["members"]
                ],
            }
            for group in parsed["coordinations"]
        ],
        "shared_scopes": [
            {
                "kind": scope["kind"],
                "span": deepcopy(scope["span"]),
                "applies_to_spans": [
                    deepcopy(member_spans[member_id])
                    for member_id in scope["applies_to_member_ids"]
                ],
            }
            for scope in parsed["shared_scopes"]
        ],
        "example_attachments": [
            {
                "id": attachment["id"],
                "cue_span": deepcopy(attachment["cue_span"]),
                "parent_span": deepcopy(attachment["parent_span"]),
                "example_spans": deepcopy(attachment["example_spans"]),
                "segment_index": attachment["segment_index"],
            }
            for attachment in parsed["example_attachments"]
        ],
        "item_candidates": [
            {
                "span": deepcopy(candidate["span"]),
                "segment_index": candidate["segment_index"],
            }
            for candidate in parsed["item_candidates"]
        ],
    }


def _node_spans(family: str, node: dict[str, Any]) -> list[dict[str, Any]]:
    if family == "wrappers":
        return [node["marker_span"], node["content_span"]]
    if family == "connector_labels":
        return [node["span"]]
    if family == "coordinations":
        return [
            *node["connector_spans"],
            *(member["span"] for member in node["members"]),
        ]
    if family == "shared_scopes":
        return [node["span"], *node["applies_to_spans"]]
    if family == "example_attachments":
        return [node["cue_span"], node["parent_span"], *node["example_spans"]]
    if family == "item_candidates":
        return [node["span"]]
    raise ValueError(f"unknown graph family: {family}")


def _node_bounds(family: str, node: dict[str, Any]) -> tuple[int, int]:
    spans = _node_spans(family, node)
    return min(span["start"] for span in spans), max(span["end"] for span in spans)


def _overlaps(left: tuple[int, int], right: tuple[int, int]) -> bool:
    return left[0] < right[1] and right[0] < left[1]


def _node_signature(family: str, node: dict[str, Any]) -> str:
    value = deepcopy(node)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sorted_unique_nodes(
    family: str, nodes: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    by_signature = {_node_signature(family, node): deepcopy(node) for node in nodes}
    return [
        by_signature[signature]
        for signature in sorted(
            by_signature,
            key=lambda value: (
                _node_bounds(family, by_signature[value]),
                value,
            ),
        )
    ]


def replace_nodes_in_envelopes(
    baseline: dict[str, Any],
    reference: dict[str, Any],
    *,
    families: tuple[str, ...],
    envelopes: tuple[tuple[int, int], ...],
) -> dict[str, Any]:
    if baseline["source_text"] != reference["source_text"]:
        raise ValueError("cannot merge graphs from different source text")
    result = deepcopy(baseline)
    for family in families:
        if family not in GRAPH_FAMILIES:
            raise ValueError(f"unknown treatment family: {family}")
        kept = [
            node
            for node in baseline[family]
            if not any(
                _overlaps(_node_bounds(family, node), value) for value in envelopes
            )
        ]
        inserted = [
            node
            for node in reference[family]
            if any(_overlaps(_node_bounds(family, node), value) for value in envelopes)
        ]
        result[family] = _sorted_unique_nodes(family, [*kept, *inserted])
    validate_graph(result)
    return result


def replace_family(
    baseline: dict[str, Any], reference: dict[str, Any], family: str
) -> dict[str, Any]:
    if baseline["source_text"] != reference["source_text"]:
        raise ValueError("cannot merge graphs from different source text")
    if family not in GRAPH_FAMILIES:
        raise ValueError(f"unknown treatment family: {family}")
    result = deepcopy(baseline)
    result[family] = deepcopy(reference[family])
    validate_graph(result)
    return result


def _all_spans(graph: dict[str, Any]) -> list[dict[str, Any]]:
    result = [*graph["protected_spans"], *graph["segments"]]
    for family in GRAPH_FAMILIES:
        for node in graph[family]:
            result.extend(_node_spans(family, node))
    return result


def validate_graph(graph: dict[str, Any]) -> None:
    source = graph["source_text"]
    if not source.strip():
        raise ValueError("graph source text is empty")
    for span in _all_spans(graph):
        start, end = _span_bounds(span)
        if not 0 <= start < end <= len(source):
            raise ValueError(f"invalid source span: {start}-{end}")
        if source[start:end] != span["text"]:
            raise ValueError(f"unanchored source span: {start}-{end}")
    segment_count = len(graph["segments"])
    for candidate in graph["item_candidates"]:
        if not 0 <= candidate["segment_index"] < segment_count:
            raise ValueError("item candidate references an unknown segment")
    known_spans = {
        _span_key(candidate["span"]) for candidate in graph["item_candidates"]
    }
    for coordination in graph["coordinations"]:
        if len(coordination["members"]) < 2:
            raise ValueError("coordination has fewer than two members")
        if len(coordination["connector_spans"]) != len(coordination["members"]) - 1:
            raise ValueError("coordination connector/member arity mismatch")
        for member in coordination["members"]:
            if not 0 <= member["segment_index"] < segment_count:
                raise ValueError("coordination member references an unknown segment")
            known_spans.add(_span_key(member["span"]))
    for scope in graph["shared_scopes"]:
        if not scope["applies_to_spans"]:
            raise ValueError("shared scope has no targets")
        if any(
            _span_key(span) not in known_spans for span in scope["applies_to_spans"]
        ):
            raise ValueError("shared scope references an unknown member span")
    for attachment in graph["example_attachments"]:
        if not attachment["example_spans"]:
            raise ValueError("example attachment has no examples")
        segment_index = attachment["segment_index"]
        if not 0 <= segment_index < segment_count:
            raise ValueError("example attachment references an unknown segment")
        segment = graph["segments"][segment_index]
        local = [attachment["cue_span"], *attachment["example_spans"]]
        if any(
            span["start"] < segment["start"] or span["end"] > segment["end"]
            for span in local
        ):
            raise ValueError("example attachment crosses its local segment")
    for family in GRAPH_FAMILIES:
        signatures = [_node_signature(family, node) for node in graph[family]]
        if len(signatures) != len(set(signatures)):
            raise ValueError(f"duplicate node signature in family: {family}")


def _unique_text(spans: list[dict[str, Any]]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for span in spans:
        key = span["text"].casefold()
        if key not in seen:
            result.append(span["text"])
            seen.add(key)
    return result


def project_graph(graph: dict[str, Any]) -> tuple[list[str], list[str]]:
    candidates = [candidate["span"] for candidate in graph["item_candidates"]]
    examples = [
        example
        for attachment in graph["example_attachments"]
        if any(
            candidate["start"] < attachment["parent_span"]["end"]
            and attachment["parent_span"]["start"] < candidate["end"]
            for candidate in candidates
        )
        for example in attachment["example_spans"]
    ]
    return _unique_text(candidates), _unique_text(examples)


def rebuild_graph(graph: dict[str, Any], rule_ids: list[str]) -> dict[str, Any]:
    validate_graph(graph)
    rebuilt: dict[str, Any] = {
        "source_text": graph["source_text"],
        "category": graph["category"],
        "protected_spans": deepcopy(graph["protected_spans"]),
        "segments": deepcopy(graph["segments"]),
        "wrappers": deepcopy(graph["wrappers"]),
        "connector_labels": deepcopy(graph["connector_labels"]),
    }
    span_to_ids: dict[tuple[int, int, str], list[str]] = {}
    coordinations: list[dict[str, Any]] = []
    next_member = 1
    for group_index, group in enumerate(graph["coordinations"], start=1):
        members: list[dict[str, Any]] = []
        for member in group["members"]:
            member_id = f"member-{next_member}"
            next_member += 1
            members.append(
                {
                    "id": member_id,
                    "span": deepcopy(member["span"]),
                    "segment_index": member["segment_index"],
                }
            )
            span_to_ids.setdefault(_span_key(member["span"]), []).append(member_id)
        coordinations.append(
            {
                "id": f"coord-{group_index}",
                "role": group["role"],
                "kind": group["kind"],
                "connector_spans": deepcopy(group["connector_spans"]),
                "members": members,
            }
        )
    candidates: list[dict[str, Any]] = []
    for candidate_index, candidate in enumerate(graph["item_candidates"], start=1):
        candidate_id = f"candidate-{candidate_index}"
        candidates.append(
            {
                "id": candidate_id,
                "span": deepcopy(candidate["span"]),
                "segment_index": candidate["segment_index"],
            }
        )
        span_to_ids.setdefault(_span_key(candidate["span"]), []).append(candidate_id)
    scopes: list[dict[str, Any]] = []
    for scope_index, scope in enumerate(graph["shared_scopes"], start=1):
        target_ids = [
            span_to_ids[_span_key(span)][0] for span in scope["applies_to_spans"]
        ]
        scopes.append(
            {
                "id": f"scope-{scope_index}",
                "kind": scope["kind"],
                "span": deepcopy(scope["span"]),
                "applies_to_member_ids": target_ids,
            }
        )
    attachments = [
        {
            "id": attachment.get("id", f"example-{index}"),
            "cue_span": deepcopy(attachment["cue_span"]),
            "parent_span": deepcopy(attachment["parent_span"]),
            "example_spans": deepcopy(attachment["example_spans"]),
            "segment_index": attachment["segment_index"],
        }
        for index, attachment in enumerate(graph["example_attachments"], start=1)
    ]
    rebuilt.update(
        {
            "coordinations": coordinations,
            "shared_scopes": scopes,
            "example_attachments": attachments,
            "item_candidates": candidates,
            "rule_ids": list(rule_ids),
        }
    )
    return rebuilt


def record_from_graph(
    baseline_record: dict[str, Any], graph: dict[str, Any], rule_id: str
) -> dict[str, Any]:
    items, examples = project_graph(graph)
    rule_ids = [rule_id, "offline.reference-closure", "offline.graph-projection-once"]
    result = deepcopy(baseline_record)
    result["error"] = None
    result["items"] = items
    result["examples"] = examples
    result["rule_ids"] = rule_ids
    result["selector_trace"] = [rule_id]
    result["parsed_clause"] = rebuild_graph(graph, rule_ids)
    return result


def full_snapshot(record: dict[str, Any]) -> dict[str, Any]:
    parsed = record["parsed_clause"]
    if parsed is None:
        raise ValueError(f"full graph missing for {record['id']}")
    member_spans = {
        member["id"]: _span_key(member["span"]) for member in parsed["item_candidates"]
    }
    for group in parsed["coordinations"]:
        member_spans.update(
            {member["id"]: _span_key(member["span"]) for member in group["members"]}
        )
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


def projection_snapshot(
    record: dict[str, Any], *, expected: bool = False
) -> dict[str, Any]:
    if "actual_items" in record:
        items_key = "expected_items" if expected else "actual_items"
        examples_key = "expected_examples" if expected else "actual_examples"
    else:
        items_key = "expected_items" if expected else "items"
        examples_key = "expected_examples" if expected else "examples"
    return {
        "surface_projection": _multiset(record[items_key]),
        "example_projection": _multiset(record[examples_key]),
    }


def snapshot_exact(actual: dict[str, Any], reference: dict[str, Any]) -> bool:
    return actual == reference


def mismatched_families(actual: dict[str, Any], reference: dict[str, Any]) -> list[str]:
    if set(actual) != set(reference):
        raise ValueError("snapshots expose different observable families")
    return sorted(family for family in actual if actual[family] != reference[family])


def family_status(actual: dict[str, Any], reference: dict[str, Any]) -> dict[str, bool]:
    if set(actual) != set(reference):
        raise ValueError("snapshots expose different observable families")
    return {family: actual[family] == reference[family] for family in sorted(actual)}


def unchanged_anchors(records: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {"id": record["id"], "payload_sha256": json_sha256(record)}
        for record in records
    ]
