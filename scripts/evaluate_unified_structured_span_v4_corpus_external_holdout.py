from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Callable, Hashable, Iterable
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FREEZE = Path(
    "datasets/unified_jd_structured_span_v4_corpus_external_label_freeze_v1_2026-09-04.json"
)
DEFAULT_RULES_FREEZE = Path(
    "datasets/unified_jd_structured_span_rules_freeze_v4_2026-09-04.json"
)
DEFAULT_RAW = Path(
    "artifacts/evaluation/unified-jd-structured-span-v4-corpus-external-raw-v1-2026-09-04.json"
)
DEFAULT_REPORT = Path(
    "artifacts/evaluation/unified-jd-structured-span-v4-corpus-external-report-v1-2026-09-04.json"
)
DEFAULT_FINDINGS = Path(
    "artifacts/evaluation/unified-jd-structured-span-v4-corpus-external-findings-v1-2026-09-04.md"
)
DEFAULT_RECEIPT = Path(
    "datasets/unified_jd_structured_span_v4_corpus_external_evaluation_receipt_v1_2026-09-04.json"
)
RAW_VERSION = "unified-jd-structured-span-v4-corpus-external-raw-v1"
REPORT_VERSION = "unified-jd-structured-span-v4-corpus-external-report-v1"
SpanKey = tuple[int, int, str]
MetricKey = Hashable


def _absolute(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def _relative(path: Path) -> str:
    return str(path.resolve().relative_to(PROJECT_ROOT)).replace("\\", "/")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _serialized(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _write_new(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"single-use output already exists: {path}")
    path.write_text(content, encoding="utf-8")


def _assert_hash(path: Path, expected: str) -> None:
    actual = _sha256(path)
    if actual != expected:
        raise ValueError(f"frozen hash mismatch for {path}: {actual} != {expected}")


def _assert_spans_anchored(value: Any, source: str) -> None:
    if isinstance(value, dict):
        if {"text", "start", "end"} <= value.keys() and source[
            value["start"] : value["end"]
        ] != value["text"]:
            raise ValueError(f"unanchored frozen span: {value}")
        for child in value.values():
            _assert_spans_anchored(child, source)
    elif isinstance(value, list):
        for child in value:
            _assert_spans_anchored(child, source)


def _validate_frozen_inputs(
    freeze_path: Path,
    rules_freeze_path: Path,
    output_paths: Iterable[Path],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    freeze = _load(freeze_path)
    if freeze["status"] != "frozen_before_v4_prediction":
        raise ValueError(f"unexpected holdout freeze status: {freeze['status']}")
    if freeze["freeze_checks"]["v4_parser_run_count"] != 0:
        raise ValueError("freeze receipt does not describe an unused holdout")
    for name, artifact in freeze["artifacts"].items():
        artifact_path = _absolute(Path(artifact["path"]))
        _assert_hash(artifact_path, artifact["sha256"])
        if name == "parser" and artifact["sha256"] == "":
            raise ValueError("empty parser hash")

    for output_path in output_paths:
        if output_path.exists():
            raise FileExistsError(f"refusing a repeated holdout run: {output_path}")

    corpus = _load(_absolute(Path(freeze["artifacts"]["corpus"]["path"])))
    selection = _load(_absolute(Path(freeze["artifacts"]["selection"]["path"])))
    labels = _load(_absolute(Path(freeze["artifacts"]["labels"]["path"])))
    rules_freeze = _load(rules_freeze_path)
    if rules_freeze["parser"]["sha256"] != freeze["artifacts"]["parser"]["sha256"]:
        raise ValueError("parser hashes disagree across freeze receipts")
    if labels["selection"]["sha256"] != freeze["artifacts"]["selection"]["sha256"]:
        raise ValueError("selection hashes disagree across frozen artifacts")

    selected = {item["id"]: item for item in selection["fixtures"]}
    jobs = {item["job_id"]: item for item in corpus["jobs"]}
    if len(selected) != 20 or len(labels["fixtures"]) != 20 or len(jobs) != 20:
        raise ValueError("corpus-external holdout must contain 20 unique jobs and fixtures")
    categories = Counter(item["category"] for item in labels["fixtures"])
    if categories != Counter(
        {"responsibility": 5, "skill": 5, "experience": 5, "capability": 5}
    ):
        raise ValueError(f"unbalanced frozen labels: {categories}")

    for fixture in labels["fixtures"]:
        selected_fixture = selected[fixture["id"]]
        for key in ("job_id", "category", "source_section", "source_text"):
            if fixture[key] != selected_fixture[key]:
                raise ValueError(f"selection/label mismatch for {fixture['id']}: {key}")
        job = jobs[fixture["job_id"]]
        if job[fixture["source_section"]].count(fixture["source_text"]) != 1:
            raise ValueError(f"source clause is not uniquely anchored: {fixture['id']}")
        _assert_spans_anchored(fixture, fixture["source_text"])

    return freeze, corpus, labels, rules_freeze


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
    return fixture["coordinations"] if gold else fixture["parsed_clause"]["coordinations"]


def _group_role(group: dict[str, Any], *, gold: bool) -> str:
    return group["role"] if gold else group.get("role", "surface")


def _group_member_spans(group: dict[str, Any], *, gold: bool) -> list[dict[str, Any]]:
    return group["member_spans"] if gold else [item["span"] for item in group["members"]]


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
        return {_span_key(item["span"]): item["role"] for item in fixture["connector_labels"]}
    parsed = fixture["parsed_clause"]
    if "connector_labels" in parsed:
        return {_span_key(item["span"]): item["role"] for item in parsed["connector_labels"]}
    roles: dict[SpanKey, str] = {}
    for group in parsed["coordinations"]:
        for span in group["connector_spans"]:
            roles[_span_key(span)] = group.get("role", "surface")
    return roles


def _member_id_to_span(parsed: dict[str, Any]) -> dict[str, SpanKey]:
    result = {
        item["id"]: _span_key(item["span"])
        for item in parsed.get("item_candidates", [])
    }
    for group in parsed.get("coordinations", []):
        result.update({item["id"]: _span_key(item["span"]) for item in group["members"]})
    return result


def _scope_edge_keys(fixture: dict[str, Any], *, gold: bool) -> list[MetricKey]:
    if gold:
        return [
            (scope["kind"], _span_key(scope["span"]), _span_key(member))
            for scope in fixture["shared_scopes"]
            for member in scope["applies_to_member_spans"]
        ]
    parsed = fixture["parsed_clause"]
    members = _member_id_to_span(parsed)
    return [
        (scope["kind"], _span_key(scope["span"]), members[member_id])
        for scope in parsed["shared_scopes"]
        for member_id in scope["applies_to_member_ids"]
        if member_id in members
    ]


def _attachment_parent_keys(fixture: dict[str, Any], *, gold: bool) -> list[MetricKey]:
    values = fixture["example_attachments"] if gold else fixture["parsed_clause"]["example_attachments"]
    return [(_span_key(item["cue_span"]), _span_key(item["parent_span"])) for item in values]


def _attachment_edge_keys(fixture: dict[str, Any], *, gold: bool) -> list[MetricKey]:
    values = fixture["example_attachments"] if gold else fixture["parsed_clause"]["example_attachments"]
    return [
        (_span_key(item["cue_span"]), _span_key(item["parent_span"]), _span_key(example))
        for item in values
        for example in item["example_spans"]
    ]


def _evaluate_pairs(
    records: list[tuple[dict[str, Any], dict[str, Any]]],
    gold_values: Callable[[dict[str, Any]], Iterable[MetricKey]],
    predicted_values: Callable[[dict[str, Any]], Iterable[MetricKey]],
) -> dict[str, Any]:
    return _metric((gold_values(gold), predicted_values(prediction)) for gold, prediction in records)


def _connector_classification(
    records: list[tuple[dict[str, Any], dict[str, Any]]],
) -> dict[str, Any]:
    confusion: Counter[tuple[str, str]] = Counter()
    for gold, prediction in records:
        expected = _connector_role_map(gold, gold=True)
        predicted = _connector_role_map(prediction, gold=False)
        for location in set(expected) | set(predicted):
            confusion[(expected.get(location, "none"), predicted.get(location, "none"))] += 1
    count = sum(confusion.values())
    correct = sum(value for (expected, predicted), value in confusion.items() if expected == predicted)
    roles = sorted({role for pair in confusion for role in pair if role != "none"})
    return {
        "correct": correct,
        "count": count,
        "accuracy": correct / count if count else 1.0,
        "confusion": {
            f"{expected}->{predicted}": value
            for (expected, predicted), value in sorted(confusion.items())
        },
        "per_role": {
            role: _metric(
                (
                    (
                        [location for location, value in _connector_role_map(gold, gold=True).items() if value == role],
                        [location for location, value in _connector_role_map(prediction, gold=False).items() if value == role],
                    )
                    for gold, prediction in records
                )
            )
            for role in roles
        },
    }


def _by_category(
    records: list[tuple[dict[str, Any], dict[str, Any]]],
    evaluator: Callable[[list[tuple[dict[str, Any], dict[str, Any]]]], dict[str, Any]],
) -> dict[str, Any]:
    grouped: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    for pair in records:
        grouped[pair[0]["category"]].append(pair)
    return {category: evaluator(pairs) for category, pairs in sorted(grouped.items())}


def _collect_unanchored(value: Any, source: str, path: str = "parsed_clause") -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if {"text", "start", "end"} <= value.keys() and source[value["start"] : value["end"]] != value["text"]:
            results.append({"path": path, "span": value})
        for key, child in value.items():
            results.extend(_collect_unanchored(child, source, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            results.extend(_collect_unanchored(child, source, f"{path}[{index}]"))
    return results


def _difference(left: Iterable[MetricKey], right: Iterable[MetricKey]) -> list[MetricKey]:
    return list((Counter(left) - Counter(right)).elements())


def run_predictions_once(
    labels: dict[str, Any], freeze_path: Path, parser_sha256: str
) -> dict[str, Any]:
    from src.domain.unified_jd_structured_spans_v4 import (
        STRUCTURED_SPAN_PARSER_VERSION,
        extract_surface_items,
    )

    records: list[dict[str, Any]] = []
    for fixture in labels["fixtures"]:
        try:
            extraction = extract_surface_items(fixture["source_text"], fixture["category"])
            records.append(
                {
                    "id": fixture["id"],
                    "job_id": fixture["job_id"],
                    "category": fixture["category"],
                    "source_text": fixture["source_text"],
                    "error": None,
                    "items": list(extraction.items),
                    "examples": list(extraction.examples),
                    "rule_ids": list(extraction.rule_ids),
                    "parsed_clause": asdict(extraction.parsed_clause),
                }
            )
        except Exception as error:  # noqa: BLE001 - parser failures are evaluation data
            records.append(
                {
                    "id": fixture["id"],
                    "job_id": fixture["job_id"],
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
        "raw_version": RAW_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "run_policy": "single_use_frozen_corpus_external_holdout",
        "v4_parser_run_count": 1,
        "parser_version": STRUCTURED_SPAN_PARSER_VERSION,
        "parser_sha256": parser_sha256,
        "label_freeze_path": _relative(freeze_path),
        "label_freeze_sha256": _sha256(freeze_path),
        "model_call_count": 0,
        "records": records,
    }


def build_report(
    raw: dict[str, Any],
    labels: dict[str, Any],
    rules_freeze: dict[str, Any],
    raw_path: Path,
) -> dict[str, Any]:
    predictions = {item["id"]: item for item in raw["records"]}
    records = [(item, predictions[item["id"]]) for item in labels["fixtures"]]
    valid = [pair for pair in records if pair[1]["parsed_clause"] is not None]
    structure_errors = len(records) - len(valid)

    pair_evaluators: dict[str, tuple[Callable[[dict[str, Any]], Iterable[MetricKey]], Callable[[dict[str, Any]], Iterable[MetricKey]]]] = {
        "wrappers": (
            lambda item: _wrapper_keys(item, gold=True),
            lambda item: _wrapper_keys(item, gold=False),
        ),
        "coordination_members": (
            lambda item: _coordination_member_keys(item, gold=True),
            lambda item: _coordination_member_keys(item, gold=False),
        ),
        "shared_scope_edges": (
            lambda item: _scope_edge_keys(item, gold=True),
            lambda item: _scope_edge_keys(item, gold=False),
        ),
        "example_attachment_parents": (
            lambda item: _attachment_parent_keys(item, gold=True),
            lambda item: _attachment_parent_keys(item, gold=False),
        ),
        "example_attachment_edges": (
            lambda item: _attachment_edge_keys(item, gold=True),
            lambda item: _attachment_edge_keys(item, gold=False),
        ),
        "surface_projection": (
            lambda item: item["projection"]["surface_items"],
            lambda item: item["items"],
        ),
        "example_projection": (
            lambda item: item["projection"]["examples"],
            lambda item: item["examples"],
        ),
    }
    metrics: dict[str, Any] = {}
    for name, (gold_values, predicted_values) in pair_evaluators.items():
        source_records = records if name.endswith("projection") else valid
        evaluator = lambda pairs, gv=gold_values, pv=predicted_values: _evaluate_pairs(pairs, gv, pv)
        metrics[name] = {
            "overall": evaluator(source_records),
            "by_category": _by_category(source_records, evaluator),
        }
    connector = {
        "overall": _connector_classification(valid),
        "by_category": _by_category(valid, _connector_classification),
    }

    unanchored: list[dict[str, Any]] = []
    per_fixture: list[dict[str, Any]] = []
    for gold, prediction in records:
        if prediction["parsed_clause"] is not None:
            unanchored.extend(
                {"id": gold["id"], **item}
                for item in _collect_unanchored(prediction["parsed_clause"], gold["source_text"])
            )
        for output_type in ("items", "examples"):
            unanchored.extend(
                {"id": gold["id"], "path": output_type, "value": value}
                for value in prediction[output_type]
                if value not in gold["source_text"]
            )
        detail: dict[str, Any] = {
            "id": gold["id"],
            "job_id": gold["job_id"],
            "category": gold["category"],
            "error": prediction["error"],
        }
        if prediction["parsed_clause"] is not None:
            for name, (gold_values, predicted_values) in pair_evaluators.items():
                expected = list(gold_values(gold))
                actual = list(predicted_values(prediction))
                detail[name] = {
                    "exact": Counter(expected) == Counter(actual),
                    "missing": _difference(expected, actual),
                    "unexpected": _difference(actual, expected),
                }
            detail["connector_classification"] = _connector_classification([(gold, prediction)])
        per_fixture.append(detail)

    development_report_path = _absolute(
        Path(rules_freeze["development_evidence"]["v4_treatment_report"]["path"])
    )
    _assert_hash(
        development_report_path,
        rules_freeze["development_evidence"]["v4_treatment_report"]["sha256"],
    )
    _load(development_report_path)
    regression_rate = rules_freeze["development_evidence"][
        "previous_development_regression"
    ]["exact_projection_rate"]
    gates = rules_freeze["corpus_external_holdout_protocol"]["gates"]
    checks = {
        "connector_classification_accuracy": {
            "actual": connector["overall"]["accuracy"],
            "operator": ">=",
            "threshold": gates["connector_classification_accuracy_min"],
        },
        "coordination_member_f1": {
            "actual": metrics["coordination_members"]["overall"]["f1"],
            "operator": ">=",
            "threshold": gates["coordination_member_f1_min"],
        },
        "shared_scope_edge_f1": {
            "actual": metrics["shared_scope_edges"]["overall"]["f1"],
            "operator": ">=",
            "threshold": gates["shared_scope_edge_f1_min"],
        },
        "example_attachment_edge_f1": {
            "actual": metrics["example_attachment_edges"]["overall"]["f1"],
            "operator": ">=",
            "threshold": gates["example_attachment_edge_f1_min"],
        },
        "surface_projection_f1": {
            "actual": metrics["surface_projection"]["overall"]["f1"],
            "operator": ">=",
            "threshold": gates["surface_projection_f1_min"],
        },
        "surface_projection_exact_rate": {
            "actual": metrics["surface_projection"]["overall"]["exact_fixture_rate"],
            "operator": ">=",
            "threshold": gates["surface_projection_exact_rate_min"],
        },
        "unanchored_output_count": {
            "actual": len(unanchored),
            "operator": "<=",
            "threshold": gates["unanchored_output_count_max"],
        },
        "structure_validation_error_count": {
            "actual": structure_errors,
            "operator": "<=",
            "threshold": gates["structure_validation_error_count_max"],
        },
        "previous_development_regression_exact_rate": {
            "actual": regression_rate,
            "operator": ">=",
            "threshold": gates["previous_development_regression_exact_rate_min"],
        },
    }
    for check in checks.values():
        check["passed"] = (
            check["actual"] >= check["threshold"]
            if check["operator"] == ">="
            else check["actual"] <= check["threshold"]
        )
    gate_passed = all(check["passed"] for check in checks.values())

    return {
        "report_version": REPORT_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "parser_version": raw["parser_version"],
        "parser_sha256": raw["parser_sha256"],
        "evaluation_scope": {
            "type": "frozen_corpus_external_single_use_holdout",
            "source": "ByteDance experienced-hire public job pages",
            "fixture_count": len(records),
            "unique_job_count": len({item[0]["job_id"] for item in records}),
            "company_count": 1,
            "cross_ai_campus_corpus": True,
            "cross_employer_generalization_claim": False,
            "v4_parser_run_count": 1,
            "model_call_count": 0,
        },
        "frozen_inputs": {
            "label_freeze_path": raw["label_freeze_path"],
            "label_freeze_sha256": raw["label_freeze_sha256"],
        },
        "raw_predictions": {
            "path": _relative(raw_path),
            "sha256": _sha256(raw_path),
            "record_count": len(raw["records"]),
        },
        "structure_validation_errors": structure_errors,
        "unanchored_outputs": {"count": len(unanchored), "records": unanchored},
        "connector_classification": connector,
        **metrics,
        "gate": {"passed": gate_passed, "checks": checks},
        "canonicalizer_decision": {
            "allowed": gate_passed,
            "reason": (
                "All frozen corpus-external v4 gates passed."
                if gate_passed
                else "At least one frozen corpus-external v4 gate failed; holdout must become revealed development data before any parser revision."
            ),
        },
        "records": per_fixture,
    }


def render_findings(report: dict[str, Any]) -> str:
    lines = [
        "# V4 corpus-external holdout findings",
        "",
        "## Scope",
        "",
        "- One frozen run on 20 real ByteDance experienced-hire jobs outside the AI-campus corpus.",
        "- One clause per job; responsibility, skill, experience, and capability each contain five fixtures.",
        "- This supports a cross-corpus claim only; all jobs come from one employer.",
        "- No model API calls were made.",
        "",
        "## Frozen gate",
        "",
        "| Metric | Actual | Threshold | Passed |",
        "|---|---:|---:|:---:|",
    ]
    for name, check in report["gate"]["checks"].items():
        actual = check["actual"]
        threshold = check["threshold"]
        actual_text = f"{actual:.4f}" if isinstance(actual, float) else str(actual)
        threshold_text = f"{threshold:.4f}" if isinstance(threshold, float) else str(threshold)
        lines.append(
            f"| `{name}` | {actual_text} | {check['operator']} {threshold_text} | "
            f"{'yes' if check['passed'] else 'no'} |"
        )
    lines.extend(["", "## Layer summary", ""])
    for name in (
        "wrappers",
        "coordination_members",
        "shared_scope_edges",
        "example_attachment_edges",
        "surface_projection",
        "example_projection",
    ):
        metric = report[name]["overall"]
        lines.append(
            f"- `{name}`: P={metric['precision']:.4f}, R={metric['recall']:.4f}, "
            f"F1={metric['f1']:.4f}, exact={metric['exact_fixture_count']}/{metric['fixture_count']}."
        )
    lines.extend(["", "## Failed fixtures", ""])
    failed = [
        item
        for item in report["records"]
        if item["error"] is not None
        or not item.get("surface_projection", {}).get("exact", False)
        or not item.get("coordination_members", {}).get("exact", False)
        or not item.get("shared_scope_edges", {}).get("exact", False)
        or not item.get("example_attachment_edges", {}).get("exact", False)
    ]
    if not failed:
        lines.append("None.")
    else:
        for item in failed:
            failures = [
                name
                for name in (
                    "wrappers",
                    "coordination_members",
                    "shared_scope_edges",
                    "example_attachment_edges",
                    "surface_projection",
                    "example_projection",
                )
                if not item.get(name, {}).get("exact", False)
            ]
            lines.append(
                f"- `{item['id']}` / `{item['job_id']}` / `{item['category']}`: "
                f"{item['error'] or ', '.join(failures)}."
            )
    lines.extend(
        [
            "",
            "## Decision",
            "",
            (
                "All frozen gates passed. Canonicalizer work is allowed under a separately frozen contract."
                if report["gate"]["passed"]
                else "The frozen gate failed. Do not tune against this holdout in place and do not start the canonicalizer. Reveal these cases as development data, diagnose the failed layers, then create a new external holdout for any revised parser."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _receipt(
    freeze_path: Path,
    parser_sha256: str,
    raw_path: Path,
    report_path: Path,
    findings_path: Path,
    report: dict[str, Any],
) -> dict[str, Any]:
    return {
        "receipt_version": "unified-jd-structured-span-v4-corpus-external-evaluation-receipt-v1",
        "evaluated_at": datetime.now(UTC).isoformat(),
        "status": "single_use_holdout_evaluated",
        "label_freeze": {"path": _relative(freeze_path), "sha256": _sha256(freeze_path)},
        "parser": {
            "path": "src/domain/unified_jd_structured_spans_v4.py",
            "sha256": parser_sha256,
            "run_count_on_holdout": 1,
        },
        "outputs": {
            "raw": {"path": _relative(raw_path), "sha256": _sha256(raw_path)},
            "report": {"path": _relative(report_path), "sha256": _sha256(report_path)},
            "findings": {"path": _relative(findings_path), "sha256": _sha256(findings_path)},
        },
        "gate_passed": report["gate"]["passed"],
        "failed_gates": [
            name for name, check in report["gate"]["checks"].items() if not check["passed"]
        ],
        "canonicalizer_allowed": report["canonicalizer_decision"]["allowed"],
        "model_call_count": 0,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the frozen v4 corpus-external holdout exactly once")
    parser.add_argument("--freeze", type=Path, default=DEFAULT_FREEZE)
    parser.add_argument("--rules-freeze", type=Path, default=DEFAULT_RULES_FREEZE)
    parser.add_argument("--raw-output", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--findings", type=Path, default=DEFAULT_FINDINGS)
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    parser.add_argument("--preflight", action="store_true")
    return parser.parse_args()


def main() -> int:
    arguments = _parse_args()
    freeze_path = _absolute(arguments.freeze)
    rules_freeze_path = _absolute(arguments.rules_freeze)
    raw_path = _absolute(arguments.raw_output)
    report_path = _absolute(arguments.report)
    findings_path = _absolute(arguments.findings)
    receipt_path = _absolute(arguments.receipt)
    output_paths = (raw_path, report_path, findings_path, receipt_path)
    freeze, _, labels, rules_freeze = _validate_frozen_inputs(
        freeze_path, rules_freeze_path, output_paths
    )
    if arguments.preflight:
        print(
            "preflight passed: frozen hashes, 20 unique fixtures, category balance, "
            "source anchors, and unused output paths verified; v4 was not imported"
        )
        return 0

    parser_sha256 = freeze["artifacts"]["parser"]["sha256"]
    raw = run_predictions_once(labels, freeze_path, parser_sha256)
    _write_new(raw_path, _serialized(raw))
    report = build_report(raw, labels, rules_freeze, raw_path)
    _write_new(report_path, _serialized(report))
    _write_new(findings_path, render_findings(report))
    receipt = _receipt(
        freeze_path, parser_sha256, raw_path, report_path, findings_path, report
    )
    _write_new(receipt_path, _serialized(receipt))
    print(
        "single-use v4 corpus-external holdout complete "
        f"connector_accuracy={report['connector_classification']['overall']['accuracy']:.4f} "
        f"member_f1={report['coordination_members']['overall']['f1']:.4f} "
        f"scope_f1={report['shared_scope_edges']['overall']['f1']:.4f} "
        f"attachment_f1={report['example_attachment_edges']['overall']['f1']:.4f} "
        f"surface_f1={report['surface_projection']['overall']['f1']:.4f} "
        f"surface_exact={report['surface_projection']['overall']['exact_fixture_count']}/20 "
        f"gate_passed={report['gate']['passed']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
