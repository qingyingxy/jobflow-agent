from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Hashable, Iterable
from dataclasses import dataclass
from datetime import date
from typing import Any

from pydantic import ValidationError

from src.domain.unified_jd import (
    UNIFIED_JD_GRANULARITY_VERSION,
    FactFieldName,
    UnifiedJDClause,
    UnifiedJDModelOutput,
    validate_unified_fact_clause_granularity,
)
from src.evaluation.unified_models import (
    UnifiedEvaluationManifest,
    UnifiedPredictionRecord,
)

FACT_FIELDS: tuple[FactFieldName, ...] = (
    "job_type",
    "locations",
    "graduation_years",
    "education_requirements",
    "major_requirements",
    "internship_duration_months",
    "weekly_days",
    "earliest_start_date",
    "deadline",
)

UnifiedEvaluationReport = dict[str, Any]
UNIFIED_EVALUATOR_VERSION = "unified-jd-evaluator-v2"


@dataclass(frozen=True)
class _ParsedPrediction:
    output: UnifiedJDModelOutput
    all_evidence_located: bool


@dataclass(frozen=True)
class _EvidenceSpan:
    index: int
    key: str
    source_text: str
    start: int | None
    end: int | None

    @property
    def located(self) -> bool:
        return self.start is not None and self.end is not None


def evaluate_unified_manifest(
    manifest: UnifiedEvaluationManifest,
    predictions: list[UnifiedPredictionRecord],
) -> UnifiedEvaluationReport:
    """Evaluate raw Unified outputs without invoking a model or legacy parser."""

    pending_ids = [
        case.id
        for case in manifest.cases
        if case.annotation_status in {"pending", "draft"} or case.expected is None
    ]
    if pending_ids:
        raise ValueError(
            "评测前必须完成人工复核 expected；pending/draft case: "
            + ", ".join(pending_ids)
        )

    cases_by_id = {case.id: case for case in manifest.cases}
    predictions_by_id = {prediction.case_id: prediction for prediction in predictions}
    missing_ids = sorted(set(cases_by_id) - set(predictions_by_id))
    extra_ids = sorted(set(predictions_by_id) - set(cases_by_id))

    schema_valid_count = 0
    parse_success_count = 0
    schema_errors: dict[str, list[dict[str, Any]]] = {}
    evidence_error_paths: dict[str, list[str]] = {}
    granularity_errors: dict[str, str] = {}
    schema_valid_outputs: dict[str, UnifiedJDModelOutput] = {}
    parsed_successfully: dict[str, UnifiedJDModelOutput] = {}
    unsupported_critical_facts: list[dict[str, Any]] = []
    evidence_conclusion_count = 0
    localized_conclusion_count = 0
    evidence_citation_count = 0
    localized_citation_count = 0

    for case_id, case in cases_by_id.items():
        prediction = predictions_by_id.get(case_id)
        if prediction is None or prediction.output is None:
            continue
        try:
            output = UnifiedJDModelOutput.model_validate(prediction.output)
        except ValidationError as error:
            schema_errors[case_id] = [
                {
                    "location": list(item["loc"]),
                    "message": item["msg"],
                    "type": item["type"],
                }
                for item in error.errors()
            ]
            continue

        schema_valid_count += 1
        schema_valid_outputs[case_id] = output
        granularity_valid = True
        if manifest.annotation_guide_version == UNIFIED_JD_GRANULARITY_VERSION:
            try:
                validate_unified_fact_clause_granularity(output)
            except ValueError as error:
                granularity_valid = False
                granularity_errors[case_id] = str(error)
        evidence = _evidence_summary(output, case.raw_content)
        evidence_conclusion_count += evidence["conclusion_count"]
        localized_conclusion_count += evidence["localized_conclusion_count"]
        evidence_citation_count += evidence["citation_count"]
        localized_citation_count += evidence["localized_citation_count"]
        if evidence["invalid_paths"]:
            evidence_error_paths[case_id] = evidence["invalid_paths"]
        for field_name in FACT_FIELDS:
            predicted_values = _fact_value_set(output, field_name)
            if not predicted_values:
                continue
            expected_values = _fact_value_set(case.expected, field_name)
            unexpected_values = sorted(predicted_values - expected_values)
            reasons: list[str] = []
            if field_name in evidence["unsupported_fact_fields"]:
                reasons.append("missing_locatable_evidence")
            if unexpected_values:
                reasons.append("value_not_in_human_label")
            if reasons:
                unsupported_critical_facts.append(
                    {
                        "case_id": case_id,
                        "field": field_name,
                        "reasons": reasons,
                        "unexpected_values": unexpected_values,
                    }
                )

        parsed = _ParsedPrediction(
            output=output,
            all_evidence_located=not evidence["invalid_paths"],
        )
        if (
            prediction.failure_code is None
            and parsed.all_evidence_located
            and granularity_valid
        ):
            parse_success_count += 1
            parsed_successfully[case_id] = parsed.output

    facts = _facts_metrics(cases_by_id, parsed_successfully)
    clauses = _clause_metrics(cases_by_id, parsed_successfully)
    required_confusions = _required_preferred_confusions(
        cases_by_id,
        parsed_successfully,
    )
    independent_facts = _facts_metrics(cases_by_id, schema_valid_outputs)
    evidence_spans = _evidence_span_metrics(cases_by_id, schema_valid_outputs)
    clause_dimensions = _clause_dimension_metrics(
        cases_by_id,
        schema_valid_outputs,
    )
    case_count = len(cases_by_id)
    evidence_localization_rate = _ratio_or_perfect(
        localized_conclusion_count,
        evidence_conclusion_count,
    )
    metrics = {
        "schema_valid_rate": schema_valid_count / case_count,
        "parse_success_rate": parse_success_count / case_count,
        "parse_success_count": parse_success_count,
        "facts_macro_f1": facts["macro_f1"],
        "clause_type_relation_f1": clauses["all"]["f1"],
        "required_clause_recall": clauses["required"]["recall"],
        "required_preferred_confusion_count": required_confusions["total"],
        "unsupported_critical_fact_count": len(unsupported_critical_facts),
        "evidence_localization_rate": evidence_localization_rate,
        "facts_value_macro_f1": independent_facts["macro_f1"],
        "evidence_span_character_f1": evidence_spans["all"]["character_coverage"]["f1"],
        "clause_category_f1": clause_dimensions["category"]["overall"]["f1"],
        "clause_level_f1": clause_dimensions["level"]["overall"]["f1"],
        "clause_relation_f1": clause_dimensions["relation"]["overall"]["f1"],
        "canonical_items_f1": clause_dimensions["canonical_items"]["overall"]["f1"],
    }
    gate = _gate_result(metrics, manifest)
    scoped_predictions = [
        prediction for prediction in predictions if prediction.case_id in cases_by_id
    ]
    failure_codes = Counter(
        prediction.failure_code
        for prediction in scoped_predictions
        if prediction.failure_code is not None
    )

    return {
        "evaluation_version": UNIFIED_EVALUATOR_VERSION,
        "manifest_version": manifest.manifest_version,
        "dataset_version": manifest.dataset_version,
        "schema_version": manifest.schema_version,
        "split": manifest.split,
        "label_status": manifest.label_status,
        "case_count": case_count,
        "prediction_count": len(predictions),
        "missing_prediction_count": len(missing_ids),
        "missing_case_ids": missing_ids,
        "extra_prediction_case_ids": extra_ids,
        "prediction_failure_count": sum(failure_codes.values()),
        "failure_codes": dict(sorted(failure_codes.items())),
        "schema_valid_count": schema_valid_count,
        "schema_valid_rate": metrics["schema_valid_rate"],
        "parse_success_count": parse_success_count,
        "parse_success_rate": metrics["parse_success_rate"],
        "facts": facts,
        "clauses": clauses,
        "dimensions": {
            "facts": independent_facts,
            "evidence_spans": evidence_spans,
            **clause_dimensions,
        },
        "required_preferred_confusions": required_confusions,
        "unsupported_critical_facts": {
            "count": len(unsupported_critical_facts),
            "items": unsupported_critical_facts,
        },
        "evidence": {
            "conclusion_count": evidence_conclusion_count,
            "localized_conclusion_count": localized_conclusion_count,
            "localization_rate": evidence_localization_rate,
            "citation_count": evidence_citation_count,
            "localized_citation_count": localized_citation_count,
            "citation_localization_rate": _ratio_or_perfect(
                localized_citation_count,
                evidence_citation_count,
            ),
        },
        "schema_errors": schema_errors,
        "evidence_error_paths": evidence_error_paths,
        "granularity_errors": granularity_errors,
        "metrics": metrics,
        "gate": gate,
    }


def _evidence_summary(
    output: UnifiedJDModelOutput,
    source_content: str,
) -> dict[str, Any]:
    invalid_paths: list[str] = []
    citation_count = 0
    localized_citation_count = 0
    valid_fact_evidence: set[str] = set()

    for index, evidence in enumerate(output.facts.evidence):
        citation_count += 1
        if evidence.source_text in source_content:
            localized_citation_count += 1
            valid_fact_evidence.add(evidence.field)
        else:
            invalid_paths.append(f"facts.evidence[{index}].source_text")

    populated_fact_fields = [
        field_name
        for field_name in FACT_FIELDS
        if getattr(output.facts, field_name) is not None
    ]
    unsupported_fact_fields = [
        field_name
        for field_name in populated_fact_fields
        if field_name not in valid_fact_evidence
    ]
    conclusion_count = len(populated_fact_fields) + len(output.clauses)
    localized_conclusion_count = len(populated_fact_fields) - len(
        unsupported_fact_fields
    )

    for index, clause in enumerate(output.clauses):
        citation_count += 1
        if clause.source_text in source_content:
            localized_citation_count += 1
            localized_conclusion_count += 1
        else:
            invalid_paths.append(f"clauses[{index}].source_text")

    return {
        "invalid_paths": invalid_paths,
        "unsupported_fact_fields": unsupported_fact_fields,
        "conclusion_count": conclusion_count,
        "localized_conclusion_count": localized_conclusion_count,
        "citation_count": citation_count,
        "localized_citation_count": localized_citation_count,
    }


def _evidence_span_metrics(
    cases_by_id: dict[str, Any],
    predictions_by_id: dict[str, UnifiedJDModelOutput],
) -> dict[str, Any]:
    fact_accumulator = _empty_span_accumulator()
    clause_accumulator = _empty_span_accumulator()
    for case_id, case in cases_by_id.items():
        expected = case.expected
        predicted = predictions_by_id.get(case_id)
        _accumulate_span_metrics(
            fact_accumulator,
            _fact_evidence_spans(expected, case.raw_content),
            _fact_evidence_spans(predicted, case.raw_content),
        )
        _accumulate_span_metrics(
            clause_accumulator,
            _clause_evidence_spans(expected, case.raw_content),
            _clause_evidence_spans(predicted, case.raw_content),
        )

    all_accumulator = _empty_span_accumulator()
    for accumulator in (fact_accumulator, clause_accumulator):
        for key, value in accumulator.items():
            all_accumulator[key] += value
    return {
        "matching": (
            "Exact source offsets are compared first; overlap uses deterministic "
            "one-to-one matching with positive character intersection. Fact evidence "
            "is matched only within the same fact field."
        ),
        "fact_evidence": _render_span_accumulator(fact_accumulator),
        "clause_evidence": _render_span_accumulator(clause_accumulator),
        "all": _render_span_accumulator(all_accumulator),
    }


def _empty_span_accumulator() -> dict[str, float]:
    return {
        "expected_count": 0,
        "predicted_count": 0,
        "localized_expected_count": 0,
        "localized_predicted_count": 0,
        "exact_tp": 0,
        "overlap_tp": 0,
        "overlap_iou_sum": 0.0,
        "character_tp": 0,
        "character_fp": 0,
        "character_fn": 0,
    }


def _fact_evidence_spans(
    output: UnifiedJDModelOutput | None,
    source_content: str,
) -> list[_EvidenceSpan]:
    if output is None:
        return []
    return [
        _source_span(
            index=index,
            key=evidence.field,
            source_text=evidence.source_text,
            source_content=source_content,
        )
        for index, evidence in enumerate(output.facts.evidence)
    ]


def _clause_evidence_spans(
    output: UnifiedJDModelOutput | None,
    source_content: str,
) -> list[_EvidenceSpan]:
    if output is None:
        return []
    return [
        _source_span(
            index=index,
            key="clause",
            source_text=clause.source_text,
            source_content=source_content,
        )
        for index, clause in enumerate(output.clauses)
    ]


def _source_span(
    *,
    index: int,
    key: str,
    source_text: str,
    source_content: str,
) -> _EvidenceSpan:
    start = source_content.find(source_text)
    return _EvidenceSpan(
        index=index,
        key=key,
        source_text=source_text,
        start=start if start >= 0 else None,
        end=start + len(source_text) if start >= 0 else None,
    )


def _accumulate_span_metrics(
    accumulator: dict[str, float],
    expected: list[_EvidenceSpan],
    predicted: list[_EvidenceSpan],
) -> None:
    accumulator["expected_count"] += len(expected)
    accumulator["predicted_count"] += len(predicted)
    accumulator["localized_expected_count"] += sum(item.located for item in expected)
    accumulator["localized_predicted_count"] += sum(item.located for item in predicted)
    expected_exact = Counter(
        (item.key, item.start, item.end) for item in expected if item.located
    )
    predicted_exact = Counter(
        (item.key, item.start, item.end) for item in predicted if item.located
    )
    accumulator["exact_tp"] += sum((expected_exact & predicted_exact).values())

    matches = _match_evidence_spans(expected, predicted)
    accumulator["overlap_tp"] += len(matches)
    accumulator["overlap_iou_sum"] += sum(match[2] for match in matches)
    character_tp, character_fp, character_fn = _character_coverage_counts(
        expected,
        predicted,
    )
    accumulator["character_tp"] += character_tp
    accumulator["character_fp"] += character_fp
    accumulator["character_fn"] += character_fn


def _match_evidence_spans(
    expected: list[_EvidenceSpan],
    predicted: list[_EvidenceSpan],
) -> list[tuple[_EvidenceSpan, _EvidenceSpan, float]]:
    candidates: list[tuple[int, float, int, int, int]] = []
    for expected_position, expected_span in enumerate(expected):
        for predicted_position, predicted_span in enumerate(predicted):
            overlap = _span_overlap(expected_span, predicted_span)
            if overlap <= 0:
                continue
            assert expected_span.start is not None
            assert expected_span.end is not None
            assert predicted_span.start is not None
            assert predicted_span.end is not None
            union = max(expected_span.end, predicted_span.end) - min(
                expected_span.start,
                predicted_span.start,
            )
            iou = overlap / union
            exact = int(
                expected_span.start == predicted_span.start
                and expected_span.end == predicted_span.end
            )
            candidates.append(
                (exact, iou, overlap, expected_position, predicted_position)
            )

    matches: list[tuple[_EvidenceSpan, _EvidenceSpan, float]] = []
    matched_expected: set[int] = set()
    matched_predicted: set[int] = set()
    for _, iou, _, expected_position, predicted_position in sorted(
        candidates,
        key=lambda item: (-item[0], -item[1], -item[2], item[3], item[4]),
    ):
        if (
            expected_position in matched_expected
            or predicted_position in matched_predicted
        ):
            continue
        matched_expected.add(expected_position)
        matched_predicted.add(predicted_position)
        matches.append(
            (
                expected[expected_position],
                predicted[predicted_position],
                iou,
            )
        )
    return matches


def _span_overlap(expected: _EvidenceSpan, predicted: _EvidenceSpan) -> int:
    if expected.key != predicted.key or not expected.located or not predicted.located:
        return 0
    assert expected.start is not None
    assert expected.end is not None
    assert predicted.start is not None
    assert predicted.end is not None
    return max(
        0,
        min(expected.end, predicted.end) - max(expected.start, predicted.start),
    )


def _character_coverage_counts(
    expected: list[_EvidenceSpan],
    predicted: list[_EvidenceSpan],
) -> tuple[int, int, int]:
    keys = {item.key for item in [*expected, *predicted]}
    expected_total = sum(
        _intervals_length(_merged_intervals(expected, key))
        + sum(
            len(item.source_text)
            for item in expected
            if item.key == key and not item.located
        )
        for key in keys
    )
    predicted_total = sum(
        _intervals_length(_merged_intervals(predicted, key))
        + sum(
            len(item.source_text)
            for item in predicted
            if item.key == key and not item.located
        )
        for key in keys
    )
    intersection = sum(
        _interval_intersection_length(
            _merged_intervals(expected, key),
            _merged_intervals(predicted, key),
        )
        for key in keys
    )
    return intersection, predicted_total - intersection, expected_total - intersection


def _merged_intervals(
    spans: list[_EvidenceSpan],
    key: str,
) -> list[tuple[int, int]]:
    intervals = sorted(
        (item.start, item.end)
        for item in spans
        if item.key == key and item.start is not None and item.end is not None
    )
    merged: list[tuple[int, int]] = []
    for start, end in intervals:
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
            continue
        merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return merged


def _interval_intersection_length(
    expected: list[tuple[int, int]],
    predicted: list[tuple[int, int]],
) -> int:
    expected_position = 0
    predicted_position = 0
    intersection = 0
    while expected_position < len(expected) and predicted_position < len(predicted):
        expected_start, expected_end = expected[expected_position]
        predicted_start, predicted_end = predicted[predicted_position]
        intersection += max(
            0,
            min(expected_end, predicted_end) - max(expected_start, predicted_start),
        )
        if expected_end <= predicted_end:
            expected_position += 1
        else:
            predicted_position += 1
    return intersection


def _intervals_length(intervals: list[tuple[int, int]]) -> int:
    return sum(end - start for start, end in intervals)


def _render_span_accumulator(accumulator: dict[str, float]) -> dict[str, Any]:
    expected_count = int(accumulator["expected_count"])
    predicted_count = int(accumulator["predicted_count"])
    exact_tp = int(accumulator["exact_tp"])
    overlap_tp = int(accumulator["overlap_tp"])
    exact = _precision_recall_f1(
        exact_tp,
        predicted_count - exact_tp,
        expected_count - exact_tp,
    )
    overlap = _precision_recall_f1(
        overlap_tp,
        predicted_count - overlap_tp,
        expected_count - overlap_tp,
    )
    overlap["mean_iou"] = (
        accumulator["overlap_iou_sum"] / overlap_tp if overlap_tp else None
    )
    character_coverage = _precision_recall_f1(
        int(accumulator["character_tp"]),
        int(accumulator["character_fp"]),
        int(accumulator["character_fn"]),
    )
    return {
        "expected_count": expected_count,
        "predicted_count": predicted_count,
        "localized_expected_count": int(accumulator["localized_expected_count"]),
        "localized_predicted_count": int(accumulator["localized_predicted_count"]),
        "exact": exact,
        "overlap": overlap,
        "character_coverage": character_coverage,
    }


def _clause_dimension_metrics(
    cases_by_id: dict[str, Any],
    predictions_by_id: dict[str, UnifiedJDModelOutput],
) -> dict[str, Any]:
    attributes = ("category", "level", "relation")
    attribute_pairs: dict[str, list[tuple[Counter[Hashable], Counter[Hashable]]]] = {
        attribute: [] for attribute in attributes
    }
    expected_counts = {attribute: Counter() for attribute in attributes}
    predicted_counts = {attribute: Counter() for attribute in attributes}
    aligned = {
        attribute: {
            "pair_count": 0,
            "correct_count": 0,
            "confusions": Counter(),
        }
        for attribute in attributes
    }
    canonical_item_pairs: list[tuple[Counter[Hashable], Counter[Hashable]]] = []
    canonical_items_by_category: dict[
        str, list[tuple[Counter[Hashable], Counter[Hashable]]]
    ] = {}
    aligned_item_pairs: list[tuple[Counter[Hashable], Counter[Hashable]]] = []
    aligned_item_pairs_by_category: dict[
        str, list[tuple[Counter[Hashable], Counter[Hashable]]]
    ] = {}

    for case_id, case in cases_by_id.items():
        expected_clauses = case.expected.clauses
        predicted_output = predictions_by_id.get(case_id)
        predicted_clauses = predicted_output.clauses if predicted_output else []
        for attribute in attributes:
            expected = Counter(
                getattr(clause, attribute) for clause in expected_clauses
            )
            predicted = Counter(
                getattr(clause, attribute) for clause in predicted_clauses
            )
            attribute_pairs[attribute].append((expected, predicted))
            expected_counts[attribute].update(expected)
            predicted_counts[attribute].update(predicted)

        canonical_item_pairs.append(
            (
                _canonical_item_counter(expected_clauses),
                _canonical_item_counter(predicted_clauses),
            )
        )
        categories = {
            clause.category for clause in [*expected_clauses, *predicted_clauses]
        }
        for category in categories:
            canonical_items_by_category.setdefault(category, []).append(
                (
                    _canonical_item_counter(
                        clause
                        for clause in expected_clauses
                        if clause.category == category
                    ),
                    _canonical_item_counter(
                        clause
                        for clause in predicted_clauses
                        if clause.category == category
                    ),
                )
            )

        matches = _match_evidence_spans(
            _clause_evidence_spans(case.expected, case.raw_content),
            _clause_evidence_spans(predicted_output, case.raw_content),
        )
        for expected_span, predicted_span, _ in matches:
            expected_clause = expected_clauses[expected_span.index]
            predicted_clause = predicted_clauses[predicted_span.index]
            for attribute in attributes:
                expected_value = getattr(expected_clause, attribute)
                predicted_value = getattr(predicted_clause, attribute)
                aligned[attribute]["pair_count"] += 1
                if expected_value == predicted_value:
                    aligned[attribute]["correct_count"] += 1
                else:
                    aligned[attribute]["confusions"][
                        (
                            expected_value,
                            predicted_value,
                        )
                    ] += 1
            if expected_clause.category == predicted_clause.category:
                item_pair = (
                    _canonical_item_counter([expected_clause]),
                    _canonical_item_counter([predicted_clause]),
                )
                aligned_item_pairs.append(item_pair)
                aligned_item_pairs_by_category.setdefault(
                    expected_clause.category,
                    [],
                ).append(item_pair)

    result: dict[str, Any] = {}
    for attribute in attributes:
        overall = _counter_metric_with_exact(attribute_pairs[attribute])
        result[attribute] = {
            "overall": overall,
            "expected_counts": dict(sorted(expected_counts[attribute].items())),
            "predicted_counts": dict(sorted(predicted_counts[attribute].items())),
            "span_aligned": _render_aligned_attribute(aligned[attribute]),
        }
    result["canonical_items"] = {
        "normalization": "NFKC, trim, casefold, and collapse whitespace",
        "semantic_alias_expansion": False,
        "overall": _counter_metric_with_exact(canonical_item_pairs),
        "by_category": {
            category: _counter_metric_with_exact(pairs)
            for category, pairs in sorted(canonical_items_by_category.items())
        },
        "span_aligned_same_category": {
            **_counter_metric_with_exact(aligned_item_pairs),
            "by_category": {
                category: _counter_metric_with_exact(pairs)
                for category, pairs in sorted(aligned_item_pairs_by_category.items())
            },
        },
    }
    return result


def _canonical_item_counter(
    clauses: Iterable[UnifiedJDClause],
) -> Counter[Hashable]:
    return Counter(_canonical_text(item) for clause in clauses for item in clause.items)


def _counter_metric_with_exact(
    pairs: Iterable[tuple[Counter[Hashable], Counter[Hashable]]],
) -> dict[str, Any]:
    pair_list = list(pairs)
    result = _counter_metric(pair_list)
    result["comparison_count"] = len(pair_list)
    result["exact_match_accuracy"] = (
        sum(expected == predicted for expected, predicted in pair_list) / len(pair_list)
        if pair_list
        else None
    )
    return result


def _render_aligned_attribute(accumulator: dict[str, Any]) -> dict[str, Any]:
    pair_count = accumulator["pair_count"]
    correct_count = accumulator["correct_count"]
    return {
        "pair_count": pair_count,
        "correct_count": correct_count,
        "accuracy": correct_count / pair_count if pair_count else None,
        "confusions": [
            {
                "expected": expected,
                "predicted": predicted,
                "count": count,
            }
            for (expected, predicted), count in sorted(
                accumulator["confusions"].items()
            )
        ],
    }


def _facts_metrics(
    cases_by_id: dict[str, Any],
    predictions_by_id: dict[str, UnifiedJDModelOutput],
) -> dict[str, Any]:
    field_metrics: dict[str, Any] = {}
    for field_name in FACT_FIELDS:
        pairs = []
        for case_id, case in cases_by_id.items():
            expected = _fact_value_set(case.expected, field_name)
            predicted = _fact_value_set(predictions_by_id.get(case_id), field_name)
            pairs.append((expected, predicted))
        field_metrics[field_name] = _set_metric(pairs)
    return {
        "field_count": len(FACT_FIELDS),
        "fields": field_metrics,
        "macro_f1": sum(item["f1"] for item in field_metrics.values())
        / len(FACT_FIELDS),
    }


def _fact_value_set(
    output: UnifiedJDModelOutput | None,
    field_name: str,
) -> set[str]:
    if output is None:
        return set()
    value = getattr(output.facts, field_name)
    values = value if isinstance(value, list) else [value]
    return {
        _canonical_fact(value_item, field_name)
        for value_item in values
        if value_item is not None
    }


def _canonical_fact(value: Any, field_name: str) -> str:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        normalized = _canonical_text(value)
        if field_name == "locations" and normalized.endswith("市"):
            return normalized[:-1]
        return normalized
    return str(value)


def _clause_metrics(
    cases_by_id: dict[str, Any],
    predictions_by_id: dict[str, UnifiedJDModelOutput],
) -> dict[str, Any]:
    all_pairs: list[tuple[Counter[Hashable], Counter[Hashable]]] = []
    required_pairs: list[tuple[Counter[Hashable], Counter[Hashable]]] = []
    exact_case_count = 0
    for case_id, case in cases_by_id.items():
        expected_clauses = case.expected.clauses
        predicted_output = predictions_by_id.get(case_id)
        predicted_clauses = predicted_output.clauses if predicted_output else []
        expected_all = Counter(_clause_signature(item) for item in expected_clauses)
        predicted_all = Counter(_clause_signature(item) for item in predicted_clauses)
        expected_required = Counter(
            _clause_signature(item)
            for item in expected_clauses
            if item.level == "required"
        )
        predicted_required = Counter(
            _clause_signature(item)
            for item in predicted_clauses
            if item.level == "required"
        )
        all_pairs.append((expected_all, predicted_all))
        required_pairs.append((expected_required, predicted_required))
        exact_case_count += expected_all == predicted_all

    all_metric = _counter_metric(all_pairs)
    all_metric["exact_match_accuracy"] = exact_case_count / len(cases_by_id)
    return {
        "signature_fields": [
            "category",
            "fact_field",
            "level",
            "relation",
            "items",
            "examples",
            "allow_other",
            "qualifier",
        ],
        "all": all_metric,
        "required": _counter_metric(required_pairs),
    }


def _clause_signature(clause: UnifiedJDClause) -> tuple[Hashable, ...]:
    return (*_clause_body_signature(clause), clause.level)


def _clause_body_signature(clause: UnifiedJDClause) -> tuple[Hashable, ...]:
    qualifier = None
    if clause.qualifier is not None:
        qualifier = (
            clause.qualifier.experience_type,
            clause.qualifier.minimum_months,
            _optional_text(clause.qualifier.domain),
        )
    return (
        clause.category,
        clause.fact_field,
        clause.relation,
        tuple(sorted({_canonical_text(item) for item in clause.items})),
        tuple(sorted({_canonical_text(item) for item in clause.examples or []})),
        clause.allow_other,
        qualifier,
    )


def _required_preferred_confusions(
    cases_by_id: dict[str, Any],
    predictions_by_id: dict[str, UnifiedJDModelOutput],
) -> dict[str, Any]:
    required_as_preferred = 0
    preferred_as_required = 0
    by_case: list[dict[str, Any]] = []
    for case_id, case in cases_by_id.items():
        expected = case.expected.clauses
        predicted_output = predictions_by_id.get(case_id)
        predicted = predicted_output.clauses if predicted_output else []
        expected_required = Counter(
            _clause_body_signature(item)
            for item in expected
            if item.level == "required"
        )
        expected_preferred = Counter(
            _clause_body_signature(item)
            for item in expected
            if item.level == "preferred"
        )
        predicted_required = Counter(
            _clause_body_signature(item)
            for item in predicted
            if item.level == "required"
        )
        predicted_preferred = Counter(
            _clause_body_signature(item)
            for item in predicted
            if item.level == "preferred"
        )
        case_required_as_preferred = sum(
            (expected_required & predicted_preferred).values()
        )
        case_preferred_as_required = sum(
            (expected_preferred & predicted_required).values()
        )
        required_as_preferred += case_required_as_preferred
        preferred_as_required += case_preferred_as_required
        if case_required_as_preferred or case_preferred_as_required:
            by_case.append(
                {
                    "case_id": case_id,
                    "required_as_preferred": case_required_as_preferred,
                    "preferred_as_required": case_preferred_as_required,
                }
            )
    return {
        "total": required_as_preferred + preferred_as_required,
        "required_as_preferred": required_as_preferred,
        "preferred_as_required": preferred_as_required,
        "by_case": by_case,
    }


def _set_metric(
    pairs: Iterable[tuple[set[Hashable], set[Hashable]]],
) -> dict[str, Any]:
    pair_list = list(pairs)
    tp = sum(len(expected & predicted) for expected, predicted in pair_list)
    fp = sum(len(predicted - expected) for expected, predicted in pair_list)
    fn = sum(len(expected - predicted) for expected, predicted in pair_list)
    result = _precision_recall_f1(tp, fp, fn)
    result.update(
        {
            "case_count": len(pair_list),
            "exact_match_accuracy": sum(
                expected == predicted for expected, predicted in pair_list
            )
            / len(pair_list),
        }
    )
    return result


def _counter_metric(
    pairs: Iterable[tuple[Counter[Hashable], Counter[Hashable]]],
) -> dict[str, Any]:
    tp = 0
    fp = 0
    fn = 0
    for expected, predicted in pairs:
        tp += sum((expected & predicted).values())
        fp += sum((predicted - expected).values())
        fn += sum((expected - predicted).values())
    return _precision_recall_f1(tp, fp, fn)


def _precision_recall_f1(tp: int, fp: int, fn: int) -> dict[str, Any]:
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
    }


def _gate_result(
    metrics: dict[str, Any],
    manifest: UnifiedEvaluationManifest,
) -> dict[str, Any]:
    thresholds = manifest.thresholds.model_dump(exclude_none=True)
    conditions: dict[str, Any] = {}
    failure_reasons: list[str] = []
    for threshold_name, threshold in thresholds.items():
        if threshold_name.endswith("_min"):
            metric_name = threshold_name.removesuffix("_min")
            comparator = ">="
            passed = metrics[metric_name] >= threshold
        else:
            metric_name = threshold_name.removesuffix("_max")
            comparator = "<="
            passed = metrics[metric_name] <= threshold
        condition = {
            "metric": metric_name,
            "actual": metrics[metric_name],
            "comparator": comparator,
            "threshold": threshold,
            "passed": passed,
        }
        conditions[threshold_name] = condition
        if not passed:
            failure_reasons.append(
                f"{metric_name}={metrics[metric_name]} 未满足 {comparator} {threshold}"
            )
    return {
        "passed": bool(conditions)
        and all(condition["passed"] for condition in conditions.values()),
        "conditions": conditions,
        "failure_reasons": failure_reasons,
    }


def _canonical_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    return re.sub(r"\s+", " ", normalized)


def _optional_text(value: str | None) -> str | None:
    return _canonical_text(value) if value is not None else None


def _ratio_or_perfect(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 1.0
