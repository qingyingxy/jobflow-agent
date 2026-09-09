from __future__ import annotations

import unicodedata
from typing import Any

from pydantic import ValidationError

from src.domain.product_jd import ProductJDModelOutput, validate_product_jd_output

PRODUCT_EVALUATOR_VERSION = "product-jd-evaluator-v3"
FACT_FIELDS = (
    "job_type",
    "locations",
    "graduation_years",
    "education_requirements",
    "major_requirements",
    "deadline",
)


def _normalize(value: Any) -> str:
    return unicodedata.normalize("NFKC", str(value)).casefold().strip()


def _count_metrics(
    expected_count: int,
    predicted_count: int,
    true_positives: int,
) -> dict[str, Any]:
    false_positives = predicted_count - true_positives
    false_negatives = expected_count - true_positives
    precision = (
        true_positives / predicted_count
        if predicted_count
        else (1.0 if not expected_count else 0.0)
    )
    recall = true_positives / expected_count if expected_count else None
    f1 = (
        None
        if recall is None
        else (
            2 * precision * recall / (precision + recall)
            if precision + recall
            else 0.0
        )
    )
    return {
        "expected_count": expected_count,
        "predicted_count": predicted_count,
        "tp": true_positives,
        "fp": false_positives,
        "fn": false_negatives,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def _set_metrics(expected: set[Any], predicted: set[Any]) -> dict[str, Any]:
    return _count_metrics(len(expected), len(predicted), len(expected & predicted))


def _macro_f1(metrics: Any) -> float | None:
    values = [item["f1"] for item in metrics if item["f1"] is not None]
    return sum(values) / len(values) if values else None


def _fact_values(output: ProductJDModelOutput, field: str) -> list[str]:
    fact = getattr(output.facts, field)
    if fact is None:
        return []
    value = getattr(fact, "values", None)
    if value is None:
        value = [fact.value]
    normalized = [_normalize(item) for item in value]
    if field == "locations":
        return [item.removesuffix("市") for item in normalized]
    return normalized


def _fact_signatures(
    outputs: dict[str, ProductJDModelOutput],
    field: str,
) -> set[tuple[str, str]]:
    return {
        (case_id, value)
        for case_id, output in outputs.items()
        for value in _fact_values(output, field)
    }


def _fact_presence_signatures(
    outputs: dict[str, ProductJDModelOutput],
    field: str,
) -> set[str]:
    return {
        case_id
        for case_id, output in outputs.items()
        if getattr(output.facts, field) is not None
    }


def _fact_source_character_signatures(
    cases_by_id: dict[str, dict[str, Any]],
    outputs: dict[str, ProductJDModelOutput],
    field: str,
) -> set[tuple[str, int]]:
    characters: set[tuple[str, int]] = set()
    for case_id, output in outputs.items():
        fact = getattr(output.facts, field)
        if fact is None:
            continue
        raw_content = cases_by_id[case_id]["raw_content"]
        start = raw_content.find(fact.source_text)
        if start < 0:
            continue
        characters.update(
            (case_id, index)
            for index in range(start, start + len(fact.source_text))
            if not raw_content[index].isspace()
        )
    return characters


def _requirement_signatures(
    outputs: dict[str, ProductJDModelOutput],
    dimension: str,
) -> set[tuple[Any, ...]]:
    signatures: set[tuple[Any, ...]] = set()
    for case_id, output in outputs.items():
        for item in output.requirements:
            source = _normalize(item.source_text)
            if dimension == "any_of_items" and item.relation != "any_of":
                continue
            if dimension == "source":
                signature = (case_id, source)
            elif dimension == "level":
                signature = (case_id, source, item.level)
            elif dimension == "relation":
                signature = (case_id, source, item.relation)
            elif dimension == "any_of_items":
                signature = (
                    case_id,
                    source,
                    tuple(sorted(_normalize(value) for value in item.items)),
                )
            else:
                signature = (
                    case_id,
                    source,
                    item.level,
                    item.relation,
                    tuple(sorted(_normalize(value) for value in item.items)),
                )
            signatures.add(signature)
    return signatures


def _any_of_item_signatures(
    outputs: dict[str, ProductJDModelOutput],
) -> set[tuple[str, str]]:
    return {
        (case_id, _normalize(value))
        for case_id, output in outputs.items()
        for requirement in output.requirements
        if requirement.relation == "any_of"
        for value in requirement.items
    }


def _any_of_aligned_group_metrics(
    expected: dict[str, ProductJDModelOutput],
    predicted: dict[str, ProductJDModelOutput],
) -> dict[str, Any]:
    expected_count = sum(
        requirement.relation == "any_of"
        for output in expected.values()
        for requirement in output.requirements
    )
    predicted_count = sum(
        requirement.relation == "any_of"
        for output in predicted.values()
        for requirement in output.requirements
    )
    matched_count = 0
    for case_id, expected_output in expected.items():
        predicted_output = predicted.get(case_id)
        if predicted_output is None:
            continue
        expected_groups = [
            item for item in expected_output.requirements if item.relation == "any_of"
        ]
        predicted_groups = [
            item for item in predicted_output.requirements if item.relation == "any_of"
        ]
        candidates: list[tuple[int, int, int, int]] = []
        for expected_index, expected_group in enumerate(expected_groups):
            expected_source = _normalize(expected_group.source_text)
            expected_items = {_normalize(item) for item in expected_group.items}
            for predicted_index, predicted_group in enumerate(predicted_groups):
                predicted_source = _normalize(predicted_group.source_text)
                predicted_items = {_normalize(item) for item in predicted_group.items}
                if expected_items != predicted_items:
                    continue
                if (
                    expected_source not in predicted_source
                    and predicted_source not in expected_source
                ):
                    continue
                candidates.append(
                    (
                        int(expected_source == predicted_source),
                        -abs(len(expected_source) - len(predicted_source)),
                        expected_index,
                        predicted_index,
                    )
                )
        matched_expected: set[int] = set()
        matched_predicted: set[int] = set()
        for _, _, expected_index, predicted_index in sorted(
            candidates,
            reverse=True,
        ):
            if (
                expected_index in matched_expected
                or predicted_index in matched_predicted
            ):
                continue
            matched_expected.add(expected_index)
            matched_predicted.add(predicted_index)
            matched_count += 1
    return _count_metrics(expected_count, predicted_count, matched_count)


def _any_of_aligned_relation_metrics(
    expected: dict[str, ProductJDModelOutput],
    predicted: dict[str, ProductJDModelOutput],
) -> dict[str, Any]:
    """Score any_of detection after aligning only source boundaries.

    This intentionally ignores item segmentation so relation judgment and item
    granularity remain separately observable.
    """
    expected_count = sum(
        requirement.relation == "any_of"
        for output in expected.values()
        for requirement in output.requirements
    )
    predicted_count = sum(
        requirement.relation == "any_of"
        for output in predicted.values()
        for requirement in output.requirements
    )
    matched_count = 0
    for case_id, expected_output in expected.items():
        predicted_output = predicted.get(case_id)
        if predicted_output is None:
            continue
        expected_sources = [
            _normalize(item.source_text)
            for item in expected_output.requirements
            if item.relation == "any_of"
        ]
        predicted_sources = [
            _normalize(item.source_text)
            for item in predicted_output.requirements
            if item.relation == "any_of"
        ]
        candidates: list[tuple[int, int, int, int]] = []
        for expected_index, expected_source in enumerate(expected_sources):
            for predicted_index, predicted_source in enumerate(predicted_sources):
                if (
                    expected_source not in predicted_source
                    and predicted_source not in expected_source
                ):
                    continue
                candidates.append(
                    (
                        int(expected_source == predicted_source),
                        -abs(len(expected_source) - len(predicted_source)),
                        expected_index,
                        predicted_index,
                    )
                )
        matched_expected: set[int] = set()
        matched_predicted: set[int] = set()
        for _, _, expected_index, predicted_index in sorted(
            candidates,
            reverse=True,
        ):
            if (
                expected_index in matched_expected
                or predicted_index in matched_predicted
            ):
                continue
            matched_expected.add(expected_index)
            matched_predicted.add(predicted_index)
            matched_count += 1
    return _count_metrics(expected_count, predicted_count, matched_count)


def _responsibility_signatures(
    outputs: dict[str, ProductJDModelOutput],
) -> set[tuple[str, str]]:
    return {
        (case_id, _normalize(item))
        for case_id, output in outputs.items()
        for item in output.responsibilities
    }


def _character_signatures(
    cases_by_id: dict[str, dict[str, Any]],
    outputs: dict[str, ProductJDModelOutput],
    *,
    kind: str,
    level: str | None = None,
    relation: str | None = None,
) -> set[tuple[str, int]]:
    characters: set[tuple[str, int]] = set()
    for case_id, output in outputs.items():
        raw_content = cases_by_id[case_id]["raw_content"]
        if kind == "responsibility":
            source_texts = output.responsibilities
        else:
            source_texts = [
                item.source_text
                for item in output.requirements
                if level is None or item.level == level
                if relation is None or item.relation == relation
            ]
        for source_text in source_texts:
            start = raw_content.find(source_text)
            if start < 0:
                continue
            characters.update(
                (case_id, index)
                for index in range(start, start + len(source_text))
                if not raw_content[index].isspace()
            )
    return characters


def _level_confusions(
    expected: dict[str, ProductJDModelOutput],
    predicted: dict[str, ProductJDModelOutput],
) -> dict[str, Any]:
    items: list[dict[str, str]] = []
    for case_id, expected_output in expected.items():
        predicted_output = predicted.get(case_id)
        if predicted_output is None:
            continue
        expected_by_source = {
            _normalize(item.source_text): item.level
            for item in expected_output.requirements
        }
        predicted_by_source = {
            _normalize(item.source_text): item.level
            for item in predicted_output.requirements
        }
        for source in sorted(expected_by_source.keys() & predicted_by_source.keys()):
            expected_level = expected_by_source[source]
            predicted_level = predicted_by_source[source]
            if expected_level != predicted_level:
                items.append(
                    {
                        "case_id": case_id,
                        "source_text": source,
                        "expected": expected_level,
                        "predicted": predicted_level,
                    }
                )
    return {"count": len(items), "items": items}


def evaluate_product_dataset(
    dataset: dict[str, Any],
    prediction_file: dict[str, Any],
) -> dict[str, Any]:
    cases = dataset["cases"]
    cases_by_id = {case["id"]: case for case in cases}
    expected: dict[str, ProductJDModelOutput] = {}
    for case in cases:
        if case.get("expected") is None:
            raise ValueError(f"Product evaluation label missing: {case['id']}")
        output = ProductJDModelOutput.model_validate(case["expected"])
        validate_product_jd_output(output, case["raw_content"])
        expected[case["id"]] = output

    predictions_by_id = {
        item["case_id"]: item for item in prediction_file.get("predictions", [])
    }
    predicted: dict[str, ProductJDModelOutput] = {}
    schema_errors: dict[str, Any] = {}
    evidence_errors: dict[str, str] = {}
    schema_valid_count = 0
    evidence_valid_count = 0
    parse_success_count = 0

    for case in cases:
        prediction = predictions_by_id.get(case["id"])
        if prediction is None or prediction.get("output") is None:
            continue
        try:
            output = ProductJDModelOutput.model_validate(prediction["output"])
        except ValidationError as error:
            schema_errors[case["id"]] = [
                {
                    "location": list(item["loc"]),
                    "message": item["msg"],
                    "type": item["type"],
                }
                for item in error.errors()
            ]
            continue
        schema_valid_count += 1
        predicted[case["id"]] = output
        try:
            validate_product_jd_output(output, case["raw_content"])
        except ValueError as error:
            evidence_errors[case["id"]] = str(error)
            continue
        evidence_valid_count += 1
        if prediction.get("failure_code") is None:
            parse_success_count += 1

    case_ids = set(expected)
    prediction_ids = set(predictions_by_id)
    attempted_ids = case_ids & prediction_ids
    expected_scoped = {
        case_id: output for case_id, output in expected.items() if case_id in attempted_ids
    }
    predicted_scoped = {
        case_id: output for case_id, output in predicted.items() if case_id in attempted_ids
    }
    fact_metrics: dict[str, dict[str, Any]] = {}
    for field in FACT_FIELDS:
        value_exact = _set_metrics(
            _fact_signatures(expected_scoped, field),
            _fact_signatures(predicted_scoped, field),
        )
        fact_metrics[field] = {
            **value_exact,
            "value_exact": value_exact,
            "presence": _set_metrics(
                _fact_presence_signatures(expected_scoped, field),
                _fact_presence_signatures(predicted_scoped, field),
            ),
            "source_character_coverage": _set_metrics(
                _fact_source_character_signatures(
                    cases_by_id,
                    expected_scoped,
                    field,
                ),
                _fact_source_character_signatures(
                    cases_by_id,
                    predicted_scoped,
                    field,
                ),
            ),
        }
    supported_fact_f1 = [
        metrics["f1"]
        for metrics in fact_metrics.values()
        if metrics["f1"] is not None
    ]
    requirement_metrics = {
        dimension: _set_metrics(
            _requirement_signatures(expected_scoped, dimension),
            _requirement_signatures(predicted_scoped, dimension),
        )
        for dimension in ("source", "level", "relation", "any_of_items", "exact")
    }
    requirement_metrics["any_of"] = {
        "exact_groups": requirement_metrics["any_of_items"],
        "aligned_relation_groups": _any_of_aligned_relation_metrics(
            expected_scoped,
            predicted_scoped,
        ),
        "aligned_exact_item_groups": _any_of_aligned_group_metrics(
            expected_scoped,
            predicted_scoped,
        ),
        "item_coverage": _set_metrics(
            _any_of_item_signatures(expected_scoped),
            _any_of_item_signatures(predicted_scoped),
        ),
        "source_character_coverage": _set_metrics(
            _character_signatures(
                cases_by_id,
                expected_scoped,
                kind="requirement",
                relation="any_of",
            ),
            _character_signatures(
                cases_by_id,
                predicted_scoped,
                kind="requirement",
                relation="any_of",
            ),
        ),
    }
    requirement_metrics["character_coverage"] = {
        label: _set_metrics(
            _character_signatures(
                cases_by_id,
                expected_scoped,
                kind="requirement",
                level=level,
            ),
            _character_signatures(
                cases_by_id,
                predicted_scoped,
                kind="requirement",
                level=level,
            ),
        )
        for label, level in (
            ("all", None),
            ("required", "required"),
            ("preferred", "preferred"),
        )
    }
    responsibility_metrics = _set_metrics(
        _responsibility_signatures(expected_scoped),
        _responsibility_signatures(predicted_scoped),
    )
    responsibility_metrics["character_coverage"] = _set_metrics(
        _character_signatures(
            cases_by_id,
            expected_scoped,
            kind="responsibility",
        ),
        _character_signatures(
            cases_by_id,
            predicted_scoped,
            kind="responsibility",
        ),
    )
    case_count = len(cases)
    attempted_case_count = len(attempted_ids)
    facts_value_macro_f1 = _macro_f1(
        metrics["value_exact"] for metrics in fact_metrics.values()
    )
    facts_presence_macro_f1 = _macro_f1(
        metrics["presence"] for metrics in fact_metrics.values()
    )
    facts_source_character_macro_f1 = _macro_f1(
        metrics["source_character_coverage"] for metrics in fact_metrics.values()
    )
    primary_metrics = {
        "parse_success_rate": parse_success_count / case_count,
        "schema_valid_rate": schema_valid_count / case_count,
        "evidence_valid_rate": evidence_valid_count / case_count,
        "facts_value_macro_f1": facts_value_macro_f1,
        "hard_major_presence_f1": fact_metrics["major_requirements"]["presence"][
            "f1"
        ],
        "requirement_source_character_f1": requirement_metrics[
            "character_coverage"
        ]["all"]["f1"],
        "any_of_aligned_exact_group_f1": requirement_metrics["any_of"][
            "aligned_exact_item_groups"
        ]["f1"],
        "any_of_aligned_relation_group_f1": requirement_metrics["any_of"][
            "aligned_relation_groups"
        ]["f1"],
        "responsibility_source_character_f1": responsibility_metrics[
            "character_coverage"
        ]["f1"],
    }

    return {
        "evaluation_version": PRODUCT_EVALUATOR_VERSION,
        "dataset_version": dataset["dataset_version"],
        "schema_version": dataset["schema_version"],
        "split": dataset["split"],
        "case_count": case_count,
        "prediction_count": len(predictions_by_id),
        "attempted_case_count": attempted_case_count,
        "missing_case_ids": sorted(case_ids - prediction_ids),
        "extra_prediction_case_ids": sorted(prediction_ids - case_ids),
        "schema_valid_count": schema_valid_count,
        "schema_valid_rate": schema_valid_count / case_count,
        "attempted_schema_valid_rate": (
            schema_valid_count / attempted_case_count if attempted_case_count else None
        ),
        "evidence_valid_count": evidence_valid_count,
        "evidence_valid_rate": evidence_valid_count / case_count,
        "attempted_evidence_valid_rate": (
            evidence_valid_count / attempted_case_count if attempted_case_count else None
        ),
        "parse_success_count": parse_success_count,
        "parse_success_rate": parse_success_count / case_count,
        "attempted_parse_success_rate": (
            parse_success_count / attempted_case_count if attempted_case_count else None
        ),
        "primary_metrics": primary_metrics,
        "facts": {
            "fields": fact_metrics,
            "supported_field_count": len(supported_fact_f1),
            "unsupported_fields": [
                field
                for field, metrics in fact_metrics.items()
                if metrics["f1"] is None
            ],
            "value_macro_f1": facts_value_macro_f1,
            "macro_f1": facts_value_macro_f1,
            "presence_macro_f1": facts_presence_macro_f1,
            "source_character_macro_f1": facts_source_character_macro_f1,
        },
        "requirements": requirement_metrics,
        "responsibilities": responsibility_metrics,
        "required_preferred_confusions": _level_confusions(
            expected_scoped,
            predicted_scoped,
        ),
        "schema_errors": schema_errors,
        "evidence_errors": evidence_errors,
    }
