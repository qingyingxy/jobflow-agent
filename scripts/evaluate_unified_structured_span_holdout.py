from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.domain.unified_jd_structured_spans import (
    STRUCTURED_SPAN_PARSER_VERSION,
    SurfaceCategory,
    extract_surface_items,
)

DEFAULT_FREEZE = Path(
    "datasets/"
    "unified_jd_structured_span_external_holdout_label_freeze_v1_2026-09-04.json"
)
DEFAULT_RAW_OUTPUT = Path(
    "artifacts/evaluation/"
    "unified-jd-structured-span-external-holdout-raw-v1-2026-09-04.json"
)
DEFAULT_REPORT = Path(
    "artifacts/evaluation/"
    "unified-jd-structured-span-external-holdout-report-v1-2026-09-04.json"
)
DEFAULT_FINDINGS = Path(
    "artifacts/evaluation/"
    "unified-jd-structured-span-external-holdout-findings-v1-2026-09-04.md"
)
REPORT_VERSION = "unified-jd-structured-span-external-holdout-report-v1"
RAW_VERSION = "unified-jd-structured-span-external-holdout-raw-v1"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _assert_hash(path: Path, expected: str) -> None:
    actual = _sha256(path)
    if actual != expected:
        raise ValueError(f"frozen hash mismatch for {path}: {actual} != {expected}")


def _write_immutable(path: Path, payload: dict[str, Any] | str) -> None:
    content = (
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        if isinstance(payload, dict)
        else payload
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_text(encoding="utf-8") != content:
            raise FileExistsError(f"refusing to overwrite frozen output: {path}")
        return
    path.write_text(content, encoding="utf-8")


def _load_frozen_inputs(
    freeze_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    label_freeze = _load_json(freeze_path)
    selection_path = Path(label_freeze["selection"]["path"])
    labels_path = Path(label_freeze["labels"]["path"])
    parser_path = Path(label_freeze["parser"]["path"])
    rules_freeze_path = Path(label_freeze["parser"]["freeze_receipt"])

    _assert_hash(selection_path, label_freeze["selection"]["sha256"])
    _assert_hash(labels_path, label_freeze["labels"]["sha256"])
    _assert_hash(parser_path, label_freeze["parser"]["sha256"])

    selection = _load_json(selection_path)
    labels = _load_json(labels_path)
    rules_freeze = _load_json(rules_freeze_path)
    if rules_freeze["parser"]["sha256"] != label_freeze["parser"]["sha256"]:
        raise ValueError("parser hashes disagree across freeze receipts")
    if labels["selection"]["sha256"] != label_freeze["selection"]["sha256"]:
        raise ValueError("selection hashes disagree across label files")
    return label_freeze, selection, labels, rules_freeze


def _validate_selection_and_labels(
    selection: dict[str, Any],
    labels: dict[str, Any],
) -> None:
    selected = {fixture["id"]: fixture for fixture in selection["fixtures"]}
    labeled = labels["fixtures"]
    if set(selected) != {fixture["id"] for fixture in labeled}:
        raise ValueError("selection and label fixture ids differ")
    if len({fixture["case_id"] for fixture in labeled}) != len(labeled):
        raise ValueError("external holdout must use one fixture per job")
    categories = Counter(fixture["category"] for fixture in labeled)
    if categories != Counter(
        {"responsibility": 5, "skill": 5, "experience": 5, "capability": 5}
    ):
        raise ValueError(f"external holdout is not category-balanced: {categories}")

    for fixture in labeled:
        selected_fixture = selected[fixture["id"]]
        compared_fields = ("case_id", "category", "source_text")
        if any(fixture[field] != selected_fixture[field] for field in compared_fields):
            raise ValueError(f"selection changed during labeling: {fixture['id']}")
        expected_values = [
            *fixture["surface_items"],
            *(fixture["examples"] or []),
        ]
        if any(value not in fixture["source_text"] for value in expected_values):
            raise ValueError(f"unanchored label in fixture {fixture['id']}")


def run_frozen_predictions(
    freeze_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    label_freeze, selection, labels, rules_freeze = _load_frozen_inputs(freeze_path)
    _validate_selection_and_labels(selection, labels)

    records: list[dict[str, Any]] = []
    for fixture in labels["fixtures"]:
        category: SurfaceCategory = fixture["category"]
        try:
            extraction = extract_surface_items(fixture["source_text"], category)
        except Exception as error:  # noqa: BLE001 - failures belong in the report
            records.append(
                {
                    "id": fixture["id"],
                    "case_id": fixture["case_id"],
                    "category": category,
                    "source_text": fixture["source_text"],
                    "error_type": type(error).__name__,
                    "error": str(error),
                    "items": [],
                    "examples": [],
                    "rule_ids": [],
                    "parsed_clause": None,
                }
            )
            continue
        records.append(
            {
                "id": fixture["id"],
                "case_id": fixture["case_id"],
                "category": category,
                "source_text": fixture["source_text"],
                "error_type": None,
                "error": None,
                "items": list(extraction.items),
                "examples": list(extraction.examples),
                "rule_ids": list(extraction.rule_ids),
                "parsed_clause": asdict(extraction.parsed_clause),
            }
        )

    raw = {
        "raw_version": RAW_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "parser_version": STRUCTURED_SPAN_PARSER_VERSION,
        "parser_sha256": label_freeze["parser"]["sha256"],
        "label_freeze_path": freeze_path.as_posix(),
        "label_freeze_sha256": _sha256(freeze_path),
        "model_call_count": 0,
        "records": records,
    }
    return raw, labels, rules_freeze


def _metric(pairs: list[tuple[list[str], list[str]]]) -> dict[str, Any]:
    true_positive = 0
    false_positive = 0
    false_negative = 0
    exact = 0
    for expected_values, predicted_values in pairs:
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
        "comparison_count": len(pairs),
        "exact_set_count": exact,
        "exact_set_rate": exact / len(pairs) if pairs else None,
    }


def _difference(left: list[str], right: list[str]) -> list[str]:
    return sorted((Counter(left) - Counter(right)).elements())


def build_report(
    raw: dict[str, Any],
    labels: dict[str, Any],
    rules_freeze: dict[str, Any],
    *,
    raw_path: Path,
) -> dict[str, Any]:
    predictions = {record["id"]: record for record in raw["records"]}
    surface_pairs: list[tuple[list[str], list[str]]] = []
    example_pairs: list[tuple[list[str], list[str]]] = []
    surface_by_category: dict[str, list[tuple[list[str], list[str]]]] = defaultdict(
        list
    )
    examples_by_category: dict[str, list[tuple[list[str], list[str]]]] = defaultdict(
        list
    )
    records: list[dict[str, Any]] = []
    unanchored_outputs: list[dict[str, str]] = []
    structure_errors = 0

    for fixture in labels["fixtures"]:
        prediction = predictions[fixture["id"]]
        expected_items = fixture["surface_items"]
        predicted_items = prediction["items"]
        expected_examples = fixture["examples"] or []
        predicted_examples = prediction["examples"]
        surface_pair = (expected_items, predicted_items)
        example_pair = (expected_examples, predicted_examples)
        surface_pairs.append(surface_pair)
        example_pairs.append(example_pair)
        surface_by_category[fixture["category"]].append(surface_pair)
        examples_by_category[fixture["category"]].append(example_pair)
        structure_errors += prediction["error"] is not None
        for output_type, values in (
            ("item", predicted_items),
            ("example", predicted_examples),
        ):
            unanchored_outputs.extend(
                {
                    "id": fixture["id"],
                    "output_type": output_type,
                    "value": value,
                }
                for value in values
                if value not in fixture["source_text"]
            )
        records.append(
            {
                "id": fixture["id"],
                "case_id": fixture["case_id"],
                "category": fixture["category"],
                "source_text": fixture["source_text"],
                "expected_surface_items": expected_items,
                "predicted_surface_items": predicted_items,
                "surface_exact": Counter(expected_items) == Counter(predicted_items),
                "missing_surface_items": _difference(expected_items, predicted_items),
                "unexpected_surface_items": _difference(
                    predicted_items, expected_items
                ),
                "expected_examples": expected_examples,
                "predicted_examples": predicted_examples,
                "examples_exact": Counter(expected_examples)
                == Counter(predicted_examples),
                "missing_examples": _difference(expected_examples, predicted_examples),
                "unexpected_examples": _difference(
                    predicted_examples, expected_examples
                ),
                "structure_error": prediction["error"],
                "rule_ids": prediction["rule_ids"],
            }
        )

    surface = _metric(surface_pairs)
    examples = _metric(example_pairs)
    gates = rules_freeze["external_holdout_protocol"]["gates"]
    checks = {
        "surface_items_f1": {
            "actual": surface["f1"],
            "operator": ">=",
            "threshold": gates["surface_items_f1_min"],
            "passed": surface["f1"] >= gates["surface_items_f1_min"],
        },
        "surface_exact_set_rate": {
            "actual": surface["exact_set_rate"],
            "operator": ">=",
            "threshold": gates["surface_exact_set_rate_min"],
            "passed": surface["exact_set_rate"] >= gates["surface_exact_set_rate_min"],
        },
        "examples_f1": {
            "actual": examples["f1"],
            "operator": ">=",
            "threshold": gates["examples_f1_min"],
            "passed": examples["f1"] >= gates["examples_f1_min"],
        },
        "unanchored_output_count": {
            "actual": len(unanchored_outputs),
            "operator": "<=",
            "threshold": gates["unanchored_output_count_max"],
            "passed": len(unanchored_outputs) <= gates["unanchored_output_count_max"],
        },
        "structure_validation_error_count": {
            "actual": structure_errors,
            "operator": "<=",
            "threshold": gates["structure_validation_error_count_max"],
            "passed": structure_errors <= gates["structure_validation_error_count_max"],
        },
    }
    gate_passed = all(check["passed"] for check in checks.values())
    return {
        "report_version": REPORT_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "parser_version": raw["parser_version"],
        "parser_sha256": raw["parser_sha256"],
        "model_call_count": 0,
        "evaluation_scope": {
            "type": "frozen_external_to_dev50_same_corpus_holdout",
            "source_partition": "sealed_blind",
            "fixture_count": len(labels["fixtures"]),
            "unique_case_count": len(
                {fixture["case_id"] for fixture in labels["fixtures"]}
            ),
            "cross_source_generalization_claim": False,
            "production_wiring": False,
        },
        "raw_predictions": {
            "path": raw_path.as_posix(),
            "sha256": _sha256(raw_path),
            "record_count": len(raw["records"]),
        },
        "surface_items": {
            "overall": surface,
            "by_category": {
                category: _metric(pairs)
                for category, pairs in sorted(surface_by_category.items())
            },
        },
        "examples": {
            "overall": examples,
            "by_category": {
                category: _metric(pairs)
                for category, pairs in sorted(examples_by_category.items())
            },
        },
        "unanchored_outputs": {
            "count": len(unanchored_outputs),
            "records": unanchored_outputs,
        },
        "structure_validation_errors": structure_errors,
        "gate": {"passed": gate_passed, "checks": checks},
        "canonicalizer_decision": {
            "allowed": gate_passed,
            "reason": (
                "All frozen v3 surface gates passed."
                if gate_passed
                else "At least one frozen v3 surface gate failed; canonicalization "
                "would confound boundary and naming errors."
            ),
        },
        "records": records,
    }


def render_findings(report: dict[str, Any]) -> str:
    surface = report["surface_items"]["overall"]
    examples = report["examples"]["overall"]
    lines = [
        "# Unified JD structured span external holdout v1",
        "",
        "## Scope",
        "",
        "- Frozen v3 parser evaluated once on 20 sealed-blind fixtures.",
        "- The fixtures are external to dev-50 but come from the same source corpus.",
        "- No model API calls were made and production wiring remains disabled.",
        "",
        "## Gate",
        "",
        "| Metric | Actual | Threshold | Passed |",
        "|---|---:|---:|:---:|",
    ]
    for name, check in report["gate"]["checks"].items():
        actual = check["actual"]
        actual_text = f"{actual:.4f}" if isinstance(actual, float) else str(actual)
        threshold = check["threshold"]
        threshold_text = (
            f"{threshold:.4f}" if isinstance(threshold, float) else str(threshold)
        )
        lines.append(
            f"| `{name}` | {actual_text} | {check['operator']} {threshold_text} | "
            f"{'yes' if check['passed'] else 'no'} |"
        )
    lines.extend(
        [
            "",
            "## Aggregate",
            "",
            (
                f"- Surface items: precision {surface['precision']:.4f}, recall "
                f"{surface['recall']:.4f}, F1 {surface['f1']:.4f}, exact "
                f"{surface['exact_set_count']}/{surface['comparison_count']}."
            ),
            (
                f"- Examples: precision {examples['precision']:.4f}, recall "
                f"{examples['recall']:.4f}, F1 {examples['f1']:.4f}, exact "
                f"{examples['exact_set_count']}/{examples['comparison_count']}."
            ),
            f"- Unanchored outputs: {report['unanchored_outputs']['count']}.",
            f"- Structural validation errors: {report['structure_validation_errors']}.",
            "",
            "## Decision",
            "",
            (
                "The external surface gate passed. Canonicalizer implementation is "
                "allowed, but requires its own frozen contract and evaluation."
                if report["gate"]["passed"]
                else "The external surface gate failed. Keep v3 frozen and do not "
                "implement or connect the canonicalizer."
            ),
            "",
            "## Failed Fixtures",
            "",
        ]
    )
    failed = [
        record
        for record in report["records"]
        if not record["surface_exact"] or not record["examples_exact"]
    ]
    if not failed:
        lines.append("None.")
    else:
        for record in failed:
            lines.append(
                f"- `{record['id']}` ({record['category']}): missing surface "
                f"{record['missing_surface_items']}; unexpected surface "
                f"{record['unexpected_surface_items']}; missing examples "
                f"{record['missing_examples']}; unexpected examples "
                f"{record['unexpected_examples']}."
            )
    return "\n".join(lines) + "\n"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the frozen v3 structured-span external holdout once"
    )
    parser.add_argument("--freeze", type=Path, default=DEFAULT_FREEZE)
    parser.add_argument("--raw-output", type=Path, default=DEFAULT_RAW_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--findings", type=Path, default=DEFAULT_FINDINGS)
    return parser.parse_args()


def main() -> int:
    arguments = _parse_args()
    raw, labels, rules_freeze = run_frozen_predictions(arguments.freeze)
    _write_immutable(arguments.raw_output, raw)
    report = build_report(
        raw,
        labels,
        rules_freeze,
        raw_path=arguments.raw_output,
    )
    _write_immutable(arguments.report, report)
    _write_immutable(arguments.findings, render_findings(report))
    surface = report["surface_items"]["overall"]
    print(
        "frozen v3 external holdout complete "
        f"surface_f1={surface['f1']:.4f} "
        f"surface_exact={surface['exact_set_count']}/"
        f"{surface['comparison_count']} "
        f"gate_passed={report['gate']['passed']} "
        f"canonicalizer_allowed={report['canonicalizer_decision']['allowed']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
