from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from collections.abc import Callable, Hashable, Iterable
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.domain.unified_jd_structured_spans import (
    STRUCTURED_SPAN_PARSER_VERSION as V3_VERSION,
)
from src.domain.unified_jd_structured_spans import extract_surface_items as extract_v3

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GOLD = Path(
    "datasets/unified_jd_structured_span_v4_development_gold_v1_2026-09-04.json"
)
DEFAULT_V3_RAW = Path(
    "artifacts/evaluation/"
    "unified-jd-structured-span-v4-development-v3-raw-v1-2026-09-04.json"
)
DEFAULT_V3_REPORT = Path(
    "artifacts/evaluation/"
    "unified-jd-structured-span-v4-development-v3-report-v1-2026-09-04.json"
)

SpanKey = tuple[int, int, str]
MetricKey = Hashable


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _span_key(span: dict[str, Any]) -> SpanKey:
    return (span["start"], span["end"], span["text"])


def _metric(
    pairs: Iterable[tuple[Iterable[MetricKey], Iterable[MetricKey]]],
) -> dict[str, Any]:
    pair_list = list(pairs)
    tp = fp = fn = exact = 0
    for expected_values, predicted_values in pair_list:
        expected = Counter(expected_values)
        predicted = Counter(predicted_values)
        tp += sum((expected & predicted).values())
        fp += sum((predicted - expected).values())
        fn += sum((expected - predicted).values())
        exact += expected == predicted
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "fixture_count": len(pair_list),
        "exact_fixture_count": exact,
        "exact_fixture_rate": exact / len(pair_list) if pair_list else None,
    }


def _wrapper_keys(fixture: dict[str, Any], *, gold: bool) -> list[MetricKey]:
    wrappers = fixture["wrappers"] if gold else fixture["parsed_clause"]["wrappers"]
    return [
        (
            item["kind"] if gold else item["kind"].split(".")[-1],
            _span_key(item["marker_span"]),
        )
        for item in wrappers
    ]


def _groups(fixture: dict[str, Any], *, gold: bool) -> list[dict[str, Any]]:
    if gold:
        return fixture["coordinations"]
    return fixture["parsed_clause"]["coordinations"]


def _group_role(group: dict[str, Any], *, gold: bool) -> str:
    return group["role"] if gold else group.get("role", "surface")


def _group_member_spans(group: dict[str, Any], *, gold: bool) -> list[dict[str, Any]]:
    if gold:
        return group["member_spans"]
    return [item["span"] for item in group["members"]]


def _coordination_member_keys(
    fixture: dict[str, Any], *, gold: bool
) -> list[MetricKey]:
    return [
        (_group_role(group, gold=gold), _span_key(span))
        for group in _groups(fixture, gold=gold)
        for span in _group_member_spans(group, gold=gold)
    ]


def _connector_role_map(fixture: dict[str, Any], *, gold: bool) -> dict[SpanKey, str]:
    if gold:
        return {
            _span_key(item["span"]): item["role"]
            for item in fixture["connector_labels"]
        }
    parsed = fixture["parsed_clause"]
    if "connector_labels" in parsed:
        return {
            _span_key(item["span"]): item["role"] for item in parsed["connector_labels"]
        }
    roles: dict[SpanKey, str] = {}
    for group in _groups(fixture, gold=False):
        role = _group_role(group, gold=False)
        for span in group["connector_spans"]:
            roles[_span_key(span)] = role
    return roles


def _member_id_to_span(parsed: dict[str, Any]) -> dict[str, SpanKey]:
    result = {
        member["id"]: _span_key(member["span"])
        for member in parsed.get("item_candidates", [])
    }
    for group in parsed.get("coordinations", []):
        result.update(
            {member["id"]: _span_key(member["span"]) for member in group["members"]}
        )
    return result


def _scope_edge_keys(fixture: dict[str, Any], *, gold: bool) -> list[MetricKey]:
    if gold:
        return [
            (scope["kind"], _span_key(scope["span"]), _span_key(member))
            for scope in fixture["shared_scopes"]
            for member in scope["applies_to_member_spans"]
        ]
    parsed = fixture["parsed_clause"]
    member_spans = _member_id_to_span(parsed)
    return [
        (scope["kind"], _span_key(scope["span"]), member_spans[member_id])
        for scope in parsed["shared_scopes"]
        for member_id in scope["applies_to_member_ids"]
        if member_id in member_spans
    ]


def _attachment_parent_keys(fixture: dict[str, Any], *, gold: bool) -> list[MetricKey]:
    values = (
        fixture["example_attachments"]
        if gold
        else fixture["parsed_clause"]["example_attachments"]
    )
    return [
        (_span_key(item["cue_span"]), _span_key(item["parent_span"])) for item in values
    ]


def _attachment_example_edge_keys(
    fixture: dict[str, Any], *, gold: bool
) -> list[MetricKey]:
    values = (
        fixture["example_attachments"]
        if gold
        else fixture["parsed_clause"]["example_attachments"]
    )
    return [
        (
            _span_key(item["cue_span"]),
            _span_key(item["parent_span"]),
            _span_key(example),
        )
        for item in values
        for example in item["example_spans"]
    ]


def _connector_classification(
    gold_fixture: dict[str, Any], prediction: dict[str, Any]
) -> dict[str, Any]:
    expected = _connector_role_map(gold_fixture, gold=True)
    predicted = _connector_role_map(prediction, gold=False)
    locations = sorted(set(expected) | set(predicted))
    confusion: Counter[tuple[str, str]] = Counter()
    for location in locations:
        confusion[
            (expected.get(location, "none"), predicted.get(location, "none"))
        ] += 1
    correct = sum(
        count
        for (expected_role, predicted_role), count in confusion.items()
        if expected_role == predicted_role
    )
    per_role = {
        role: _metric(
            [
                (
                    [location for location, value in expected.items() if value == role],
                    [
                        location
                        for location, value in predicted.items()
                        if value == role
                    ],
                )
            ]
        )
        for role in sorted(set(expected.values()) | set(predicted.values()))
    }
    return {
        "correct": correct,
        "count": len(locations),
        "accuracy": correct / len(locations) if locations else 1.0,
        "confusion": {
            f"{expected_role}->{predicted_role}": count
            for (expected_role, predicted_role), count in sorted(confusion.items())
        },
        "per_role": per_role,
    }


def _aggregate_connector_classification(
    records: list[tuple[dict[str, Any], dict[str, Any]]],
) -> dict[str, Any]:
    results = [
        _connector_classification(gold, prediction) for gold, prediction in records
    ]
    confusion: Counter[str] = Counter()
    for result in results:
        confusion.update(result["confusion"])
    count = sum(result["count"] for result in results)
    correct = sum(result["correct"] for result in results)
    roles = sorted(
        {
            role
            for gold, prediction in records
            for role in (
                set(_connector_role_map(gold, gold=True).values())
                | set(_connector_role_map(prediction, gold=False).values())
            )
        }
    )
    return {
        "correct": correct,
        "count": count,
        "accuracy": correct / count if count else 1.0,
        "confusion": dict(sorted(confusion.items())),
        "per_role": {
            role: _metric(
                (
                    (
                        [
                            location
                            for location, value in _connector_role_map(
                                gold, gold=True
                            ).items()
                            if value == role
                        ],
                        [
                            location
                            for location, value in _connector_role_map(
                                prediction, gold=False
                            ).items()
                            if value == role
                        ],
                    )
                    for gold, prediction in records
                )
            )
            for role in roles
        },
    }


def _evaluate_pairs(
    records: list[tuple[dict[str, Any], dict[str, Any]]],
    gold_values: Callable[[dict[str, Any]], Iterable[MetricKey]],
    predicted_values: Callable[[dict[str, Any]], Iterable[MetricKey]],
) -> dict[str, Any]:
    return _metric(
        (gold_values(gold), predicted_values(prediction))
        for gold, prediction in records
    )


def evaluate_predictions(gold: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    predictions = {item["id"]: item for item in raw["records"]}
    records = [(item, predictions[item["id"]]) for item in gold["fixtures"]]
    valid_records = [pair for pair in records if pair[1]["parsed_clause"] is not None]
    structural_errors = len(records) - len(valid_records)
    wrappers = _evaluate_pairs(
        valid_records,
        lambda item: _wrapper_keys(item, gold=True),
        lambda item: _wrapper_keys(item, gold=False),
    )
    members = _evaluate_pairs(
        valid_records,
        lambda item: _coordination_member_keys(item, gold=True),
        lambda item: _coordination_member_keys(item, gold=False),
    )
    scopes = _evaluate_pairs(
        valid_records,
        lambda item: _scope_edge_keys(item, gold=True),
        lambda item: _scope_edge_keys(item, gold=False),
    )
    attachment_parents = _evaluate_pairs(
        valid_records,
        lambda item: _attachment_parent_keys(item, gold=True),
        lambda item: _attachment_parent_keys(item, gold=False),
    )
    attachment_examples = _evaluate_pairs(
        valid_records,
        lambda item: _attachment_example_edge_keys(item, gold=True),
        lambda item: _attachment_example_edge_keys(item, gold=False),
    )
    surface = _metric(
        (
            (gold_item["projection"]["surface_items"], prediction["items"])
            for gold_item, prediction in records
        )
    )
    examples = _metric(
        (
            (gold_item["projection"]["examples"], prediction["examples"])
            for gold_item, prediction in records
        )
    )
    per_fixture: list[dict[str, Any]] = []
    for gold_item, prediction in records:
        if prediction["parsed_clause"] is None:
            per_fixture.append(
                {
                    "id": gold_item["id"],
                    "diagnostic_status": gold_item["diagnostic_status"],
                    "error": prediction["error"],
                }
            )
            continue
        pair = [(gold_item, prediction)]
        per_fixture.append(
            {
                "id": gold_item["id"],
                "diagnostic_status": gold_item["diagnostic_status"],
                "wrapper_exact": _evaluate_pairs(
                    pair,
                    lambda item: _wrapper_keys(item, gold=True),
                    lambda item: _wrapper_keys(item, gold=False),
                )["exact_fixture_count"]
                == 1,
                "connector_classification": _connector_classification(
                    gold_item, prediction
                ),
                "coordination_members_exact": _evaluate_pairs(
                    pair,
                    lambda item: _coordination_member_keys(item, gold=True),
                    lambda item: _coordination_member_keys(item, gold=False),
                )["exact_fixture_count"]
                == 1,
                "shared_scope_exact": _evaluate_pairs(
                    pair,
                    lambda item: _scope_edge_keys(item, gold=True),
                    lambda item: _scope_edge_keys(item, gold=False),
                )["exact_fixture_count"]
                == 1,
                "example_attachment_exact": _evaluate_pairs(
                    pair,
                    lambda item: _attachment_example_edge_keys(item, gold=True),
                    lambda item: _attachment_example_edge_keys(item, gold=False),
                )["exact_fixture_count"]
                == 1,
                "projection_exact": Counter(gold_item["projection"]["surface_items"])
                == Counter(prediction["items"]),
            }
        )
    return {
        "report_version": "unified-jd-structured-span-v4-development-report-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "parser_version": raw["parser_version"],
        "gold_version": gold["gold_version"],
        "evaluation_scope": {
            "status": gold["status"],
            "fixture_count": len(records),
            "revealed_v3_failures": sum(
                item["diagnostic_status"] == "revealed_v3_failure"
                for item, _ in records
            ),
            "passing_controls": sum(
                item["diagnostic_status"] == "passing_control" for item, _ in records
            ),
            "generalization_claim": False,
        },
        "structure_validation_errors": structural_errors,
        "wrappers": wrappers,
        "connector_classification": _aggregate_connector_classification(valid_records),
        "coordination_members": members,
        "shared_scope_edges": scopes,
        "example_attachment_parents": attachment_parents,
        "example_attachment_edges": attachment_examples,
        "projection": {"surface_items": surface, "examples": examples},
        "records": per_fixture,
    }


def run_predictions(gold: dict[str, Any], parser_name: str) -> dict[str, Any]:
    if parser_name == "v3":
        version = V3_VERSION
        extractor = extract_v3
    elif parser_name == "v4":
        from src.domain.unified_jd_structured_spans_v4 import (
            STRUCTURED_SPAN_PARSER_VERSION as V4_VERSION,
        )
        from src.domain.unified_jd_structured_spans_v4 import (
            extract_surface_items as extract_v4,
        )

        version = V4_VERSION
        extractor = extract_v4
    else:
        raise ValueError(f"unsupported parser: {parser_name}")

    records: list[dict[str, Any]] = []
    for fixture in gold["fixtures"]:
        try:
            extraction = extractor(fixture["source_text"], fixture["category"])
            records.append(
                {
                    "id": fixture["id"],
                    "category": fixture["category"],
                    "source_text": fixture["source_text"],
                    "error": None,
                    "items": list(extraction.items),
                    "examples": list(extraction.examples),
                    "rule_ids": list(extraction.rule_ids),
                    "parsed_clause": asdict(extraction.parsed_clause),
                }
            )
        except Exception as error:  # noqa: BLE001 - errors are evaluation results
            records.append(
                {
                    "id": fixture["id"],
                    "category": fixture["category"],
                    "source_text": fixture["source_text"],
                    "error": f"{type(error).__name__}: {error}",
                    "items": [],
                    "examples": [],
                    "rule_ids": [],
                    "parsed_clause": None,
                }
            )
    return {
        "raw_version": "unified-jd-structured-span-v4-development-raw-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "parser_version": version,
        "gold_path": DEFAULT_GOLD.as_posix(),
        "gold_sha256": _sha256(PROJECT_ROOT / DEFAULT_GOLD),
        "model_call_count": 0,
        "records": records,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate structure and projection independently on revealed data"
    )
    parser.add_argument("--parser", choices=("v3", "v4"), default="v3")
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--raw-output", type=Path, default=DEFAULT_V3_RAW)
    parser.add_argument("--report", type=Path, default=DEFAULT_V3_REPORT)
    return parser.parse_args()


def main() -> int:
    arguments = _parse_args()
    gold_path = (
        arguments.gold
        if arguments.gold.is_absolute()
        else PROJECT_ROOT / arguments.gold
    )
    raw_path = (
        arguments.raw_output
        if arguments.raw_output.is_absolute()
        else PROJECT_ROOT / arguments.raw_output
    )
    report_path = (
        arguments.report
        if arguments.report.is_absolute()
        else PROJECT_ROOT / arguments.report
    )
    gold = _load(gold_path)
    raw = run_predictions(gold, arguments.parser)
    report = evaluate_predictions(gold, raw)
    _write(raw_path, raw)
    _write(report_path, report)
    surface = report["projection"]["surface_items"]
    print(
        f"parser={arguments.parser} structure_errors={report['structure_validation_errors']} "
        f"connector_accuracy={report['connector_classification']['accuracy']:.4f} "
        f"member_f1={report['coordination_members']['f1']:.4f} "
        f"scope_f1={report['shared_scope_edges']['f1']:.4f} "
        f"attachment_f1={report['example_attachment_edges']['f1']:.4f} "
        f"surface_f1={surface['f1']:.4f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
