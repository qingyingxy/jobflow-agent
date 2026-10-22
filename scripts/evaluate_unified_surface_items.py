from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.domain.unified_jd_surface_items import (
    SURFACE_ITEM_EXTRACTOR_VERSION,
    SurfaceCategory,
    extract_surface_items,
)

DEFAULT_FIXTURE = Path("datasets/unified_jd_canonical_items_contract_v1.json")
DEFAULT_OUTPUT = Path(
    "artifacts/evaluation/unified-jd-surface-items-prototype-v1-2026-09-04.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _metric(records: list[tuple[list[str], list[str]]]) -> dict[str, Any]:
    true_positive = 0
    false_positive = 0
    false_negative = 0
    exact = 0
    for expected_values, predicted_values in records:
        expected = Counter(expected_values)
        predicted = Counter(predicted_values)
        true_positive += sum((expected & predicted).values())
        false_positive += sum((predicted - expected).values())
        false_negative += sum((expected - predicted).values())
        exact += expected == predicted

    precision = (
        true_positive / (true_positive + false_positive)
        if true_positive + false_positive
        else 1.0
    )
    recall = (
        true_positive / (true_positive + false_negative)
        if true_positive + false_negative
        else 1.0
    )
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "tp": true_positive,
        "fp": false_positive,
        "fn": false_negative,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "comparison_count": len(records),
        "exact_set_count": exact,
        "exact_set_rate": exact / len(records) if records else None,
    }


def _counter_difference(left: list[str], right: list[str]) -> list[str]:
    return sorted((Counter(left) - Counter(right)).elements())


def build_report(
    fixture: dict[str, Any],
    fixture_path: Path,
    *,
    extractor: Callable[[str, SurfaceCategory], Any] = extract_surface_items,
    extractor_version: str = SURFACE_ITEM_EXTRACTOR_VERSION,
) -> dict[str, Any]:
    surface_pairs: list[tuple[list[str], list[str]]] = []
    example_pairs: list[tuple[list[str], list[str]]] = []
    surface_by_category: dict[str, list[tuple[list[str], list[str]]]] = defaultdict(
        list
    )
    examples_by_category: dict[str, list[tuple[list[str], list[str]]]] = defaultdict(
        list
    )
    rule_counts: Counter[str] = Counter()
    records: list[dict[str, Any]] = []

    for item in fixture["fixtures"]:
        category: SurfaceCategory = item["category"]
        extraction = extractor(item["source_text"], category)
        expected_items = item["surface_items"]
        predicted_items = list(extraction.items)
        expected_examples = item["examples"] or []
        predicted_examples = list(extraction.examples)
        surface_pair = (expected_items, predicted_items)
        example_pair = (expected_examples, predicted_examples)
        surface_pairs.append(surface_pair)
        example_pairs.append(example_pair)
        surface_by_category[category].append(surface_pair)
        examples_by_category[category].append(example_pair)
        rule_counts.update(extraction.rule_ids)
        records.append(
            {
                "id": item["id"],
                "case_id": item["case_id"],
                "clause_index": item["clause_index"],
                "category": category,
                "source_text": item["source_text"],
                "expected_surface_items": expected_items,
                "predicted_surface_items": predicted_items,
                "surface_exact": Counter(expected_items) == Counter(predicted_items),
                "missing_surface_items": _counter_difference(
                    expected_items, predicted_items
                ),
                "unexpected_surface_items": _counter_difference(
                    predicted_items, expected_items
                ),
                "expected_examples": expected_examples,
                "predicted_examples": predicted_examples,
                "examples_exact": Counter(expected_examples)
                == Counter(predicted_examples),
                "missing_examples": _counter_difference(
                    expected_examples, predicted_examples
                ),
                "unexpected_examples": _counter_difference(
                    predicted_examples, expected_examples
                ),
                "rule_ids": list(extraction.rule_ids),
            }
        )

    return {
        "report_version": "unified-jd-surface-items-prototype-evaluation-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "extractor_version": extractor_version,
        "contract_version": fixture["contract_version"],
        "model_call_count": 0,
        "evaluation_scope": {
            "type": "development_contract_fit",
            "generalization_claim": False,
            "production_wiring": False,
            "note": (
                "The prototype was developed against these fixtures; use a separately "
                "reviewed holdout before production integration."
            ),
        },
        "fixture": {
            "path": fixture_path.as_posix(),
            "sha256": _sha256(fixture_path),
            "count": len(fixture["fixtures"]),
        },
        "surface_items": {
            "overall": _metric(surface_pairs),
            "by_category": {
                category: _metric(pairs)
                for category, pairs in sorted(surface_by_category.items())
            },
        },
        "examples": {
            "overall": _metric(example_pairs),
            "by_category": {
                category: _metric(pairs)
                for category, pairs in sorted(examples_by_category.items())
            },
        },
        "rule_counts": dict(sorted(rule_counts.items())),
        "failure_counts": {
            "surface_item_failures": sum(
                not record["surface_exact"] for record in records
            ),
            "example_failures": sum(not record["examples_exact"] for record in records),
        },
        "records": records,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate the offline Unified JD surface-item prototype"
    )
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    arguments = _parse_args()
    fixture = json.loads(arguments.fixture.read_text(encoding="utf-8"))
    report = build_report(fixture, arguments.fixture)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    surface = report["surface_items"]["overall"]
    examples = report["examples"]["overall"]
    print(
        "offline surface-item evaluation complete "
        f"surface_exact={surface['exact_set_count']}/{surface['comparison_count']} "
        f"examples_exact={examples['exact_set_count']}/{examples['comparison_count']} "
        f"output={arguments.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
