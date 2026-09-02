from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import Any

from src.domain.skill_normalizer import (
    SKILL_ONTOLOGY_VERSION,
    normalize_atomic_skill_values,
    normalize_skill_concepts,
    normalize_skill_group,
)
from src.evaluation.models import (
    EvaluationCase,
    EvaluationManifest,
    PredictionMatch,
    PredictionRecord,
)

EvaluationReport = dict[str, Any]


@dataclass(frozen=True)
class _MetricConcept:
    skill_id: str
    strength: str
    qualifier: str | None = None
    relation: str = "all_of"
    group_name: str | None = None
    allow_other: bool = False
    source_text: str | None = None


def validate_prediction(
    prediction: PredictionRecord,
    case: EvaluationCase,
) -> PredictionRecord:
    """Apply the same evidence boundary used by the product to eval output."""

    allowed_ids = set(case.candidate_evidence_ids)
    validated_matches: list[PredictionMatch] = []
    for match in prediction.matches:
        issues = list(match.validation_issues)
        valid_ids: list[str] = []
        for evidence_id in _deduplicate(match.evidence_ids):
            if evidence_id not in allowed_ids:
                issues.append(f"evidence_id 不在当前案例候选证据中: {evidence_id}")
                continue
            valid_ids.append(evidence_id)

        support_level = match.support_level
        if support_level == "unsupported":
            if valid_ids:
                issues.append("unsupported 结果不能引用 evidence_id")
            valid_ids = []
        elif not valid_ids:
            issues.append("supported 或 partial 结果至少需要一个有效 evidence_id")
            support_level = "unsupported"

        validated_matches.append(
            PredictionMatch(
                requirement_key=match.requirement_key,
                support_level=support_level,
                evidence_ids=valid_ids,
                validation_issues=_deduplicate(issues),
            )
        )

    return PredictionRecord(
        case_id=prediction.case_id,
        fields=prediction.fields,
        eligibility=prediction.eligibility,
        matches=validated_matches,
        warnings=prediction.warnings,
        failure_code=prediction.failure_code,
        failure_details=prediction.failure_details,
    )


def evaluate_manifest(
    manifest: EvaluationManifest,
    predictions: list[PredictionRecord],
    *,
    model: str | None = None,
    prompt_version: str | None = None,
    validator_version: str = "evidence-boundary-v1",
) -> EvaluationReport:
    cases_by_id = {case.id: case for case in manifest.cases if case.split == manifest.split}
    predictions_by_id = {prediction.case_id: prediction for prediction in predictions}
    missing_ids = sorted(set(cases_by_id) - set(predictions_by_id))
    extra_ids = sorted(set(predictions_by_id) - set(cases_by_id))

    raw_predictions = [
        predictions_by_id.get(case_id, PredictionRecord(case_id=case_id))
        for case_id in cases_by_id
    ]
    validated_predictions = [
        validate_prediction(prediction, cases_by_id[prediction.case_id])
        for prediction in raw_predictions
    ]

    raw_metrics = _metric_bundle(cases_by_id, raw_predictions, manifest.fields)
    validated_metrics = _metric_bundle(
        cases_by_id,
        validated_predictions,
        manifest.fields,
    )
    scoped_predictions = [
        prediction
        for prediction in predictions
        if prediction.case_id in cases_by_id
    ]
    failure_codes = Counter(
        prediction.failure_code
        for prediction in scoped_predictions
        if prediction.failure_code is not None
    )
    successful_prediction_count = sum(
        prediction.failure_code is None for prediction in scoped_predictions
    )
    timeout_count = failure_codes.get("model_timeout", 0)
    warning_codes = Counter(
        warning.code
        for prediction in scoped_predictions
        for warning in prediction.warnings
    )
    report: EvaluationReport = {
        "manifest_version": manifest.manifest_version,
        "dataset_version": manifest.dataset_version,
        "skill_ontology_version": SKILL_ONTOLOGY_VERSION,
        "split": manifest.split,
        "case_count": len(cases_by_id),
        "prediction_count": len(predictions),
        "prediction_failure_count": sum(
            prediction.failure_code is not None for prediction in predictions
        ),
        "successful_prediction_count": successful_prediction_count,
        "success_rate": _ratio(successful_prediction_count, len(cases_by_id)),
        "failure_codes": dict(sorted(failure_codes.items())),
        "prediction_warning_count": sum(warning_codes.values()),
        "warning_codes": dict(sorted(warning_codes.items())),
        "timeout_count": timeout_count,
        "timeout_rate": _ratio(timeout_count, len(cases_by_id)),
        "missing_prediction_count": len(missing_ids),
        "missing_case_ids": missing_ids,
        "extra_prediction_case_ids": extra_ids,
        "model": model,
        "prompt_version": prompt_version,
        "validator_version": validator_version,
        "raw": raw_metrics,
        "validated": validated_metrics,
        "validator": _validator_summary(raw_predictions, validated_predictions),
        "thresholds": _threshold_results(
            validated_metrics,
            manifest.thresholds.model_dump(exclude_none=True),
        ),
    }
    return report


def _metric_bundle(
    cases_by_id: dict[str, EvaluationCase],
    predictions: list[PredictionRecord],
    fields: list[str],
) -> dict[str, Any]:
    predictions_by_id = {prediction.case_id: prediction for prediction in predictions}
    field_metrics = {
        field_name: _field_metric(cases_by_id, predictions_by_id, field_name)
        for field_name in fields
    }
    macro_values = [
        result["f1"]
        for result in field_metrics.values()
        if result["f1"] is not None
    ]
    supported_claim_count, unsupported_claim_count = _unsupported_claim_counts(
        cases_by_id,
        predictions_by_id,
    )
    return {
        "fields": field_metrics,
        "macro_f1": _safe_average(macro_values),
        "skill_detection": _skill_detection_metric(
            cases_by_id,
            predictions_by_id,
        ),
        "skill_strength": _skill_strength_metric(
            cases_by_id,
            predictions_by_id,
        ),
        "any_of_relations": _any_of_relation_metric(
            cases_by_id,
            predictions_by_id,
        ),
        "skill_concepts": _skill_concept_metric(
            cases_by_id,
            predictions_by_id,
        ),
        "skill_concept_strength": _skill_concept_strength_metric(
            cases_by_id,
            predictions_by_id,
        ),
        "skill_qualifiers": _skill_qualifier_metric(
            cases_by_id,
            predictions_by_id,
        ),
        "concept_any_of_relations": _concept_any_of_relation_metric(
            cases_by_id,
            predictions_by_id,
        ),
        "eligibility_accuracy": _eligibility_accuracy(
            cases_by_id,
            predictions_by_id,
        ),
        "false_accept_rate": _false_accept_rate(cases_by_id, predictions_by_id),
        "evidence_precision": _evidence_precision(cases_by_id, predictions_by_id),
        "evidence_coverage": _evidence_coverage(cases_by_id, predictions_by_id),
        "unsupported_claim_rate": _unsupported_claim_rate(
            cases_by_id,
            predictions_by_id,
        ),
        "supported_claim_count": supported_claim_count,
        "unsupported_claim_count": unsupported_claim_count,
        "failure_accuracy": _failure_accuracy(cases_by_id, predictions_by_id),
    }


def _field_metric(
    cases_by_id: dict[str, EvaluationCase],
    predictions_by_id: dict[str, PredictionRecord],
    field_name: str,
) -> dict[str, Any]:
    true_positive = 0
    false_positive = 0
    false_negative = 0
    labeled_cases = 0
    exact_match_cases = 0
    for case_id, case in cases_by_id.items():
        if field_name not in case.expected.fields:
            continue
        labeled_cases += 1
        expected = _value_set(case.expected.fields[field_name], field_name=field_name)
        predicted = _value_set(
            predictions_by_id[case_id].fields.get(field_name),
            field_name=field_name,
        )
        exact_match_cases += expected == predicted
        true_positive += len(expected & predicted)
        false_positive += len(predicted - expected)
        false_negative += len(expected - predicted)

    precision = _ratio(true_positive, true_positive + false_positive)
    recall = _ratio(true_positive, true_positive + false_negative)
    f1 = _f1(precision, recall)
    return {
        "labeled_case_count": labeled_cases,
        "exact_match_accuracy": _ratio(exact_match_cases, labeled_cases),
        "tp": true_positive,
        "fp": false_positive,
        "fn": false_negative,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def _skill_detection_metric(
    cases_by_id: dict[str, EvaluationCase],
    predictions_by_id: dict[str, PredictionRecord],
) -> dict[str, Any]:
    pairs = [
        (
            _expected_detected_skills(case),
            _predicted_detected_skills(predictions_by_id[case_id]),
        )
        for case_id, case in cases_by_id.items()
    ]
    return _set_metric(pairs)


def _skill_strength_metric(
    cases_by_id: dict[str, EvaluationCase],
    predictions_by_id: dict[str, PredictionRecord],
) -> dict[str, Any]:
    pairs_by_strength: dict[str, list[tuple[set[str], set[str]]]] = {
        "required": [],
        "preferred": [],
        "mention": [],
    }
    for case_id, case in cases_by_id.items():
        expected = _skill_strength_sets(
            case.expected.fields,
            mentions=case.expected.skill_mentions,
        )
        predicted = _skill_strength_sets(predictions_by_id[case_id].fields)
        for strength, pairs in pairs_by_strength.items():
            pairs.append(
                (expected[strength], predicted[strength])
            )

    class_metrics = {
        strength: _set_metric(pairs)
        for strength, pairs in pairs_by_strength.items()
    }
    return {
        "classes": class_metrics,
        "macro_f1": _safe_average(
            [
                metric["f1"]
                for metric in class_metrics.values()
                if metric["f1"] is not None
            ]
        ),
    }


def _any_of_relation_metric(
    cases_by_id: dict[str, EvaluationCase],
    predictions_by_id: dict[str, PredictionRecord],
) -> dict[str, Any]:
    expected_positive_cases = 0
    exact_match_cases = 0
    expected_negative_cases = 0
    false_positive_cases = 0

    for case_id, case in cases_by_id.items():
        expected = _value_set(
            case.expected.fields.get("required_skill_groups"),
            field_name="required_skill_groups",
        )
        predicted = _value_set(
            predictions_by_id[case_id].fields.get("required_skill_groups"),
            field_name="required_skill_groups",
        )
        if expected:
            expected_positive_cases += 1
            exact_match_cases += expected == predicted
        else:
            expected_negative_cases += 1
            false_positive_cases += bool(predicted)

    return {
        "expected_positive_case_count": expected_positive_cases,
        "exact_match_case_count": exact_match_cases,
        "conditional_exact_match_accuracy": _ratio(
            exact_match_cases,
            expected_positive_cases,
        ),
        "expected_negative_case_count": expected_negative_cases,
        "false_positive_case_count": false_positive_cases,
        "false_positive_case_rate": _ratio(
            false_positive_cases,
            expected_negative_cases,
        ),
    }


def _skill_concept_metric(
    cases_by_id: dict[str, EvaluationCase],
    predictions_by_id: dict[str, PredictionRecord],
) -> dict[str, Any]:
    pairs: list[tuple[set[str], set[str]]] = []
    for case_id, case in cases_by_id.items():
        if case.expected.fields.get("skill_concepts"):
            expected = _concept_ids(_concept_records(case.expected.fields))
        elif case.expected.skill_mentions:
            expected = _concept_ids_for_labels(case.expected.skill_mentions)
        else:
            expected = _concept_ids(_concept_records(case.expected.fields))
        predicted = _concept_ids(
            _concept_records(predictions_by_id[case_id].fields)
        )
        pairs.append((expected, predicted))
    return _set_metric(pairs)


def _skill_concept_strength_metric(
    cases_by_id: dict[str, EvaluationCase],
    predictions_by_id: dict[str, PredictionRecord],
) -> dict[str, Any]:
    pairs_by_strength: dict[str, list[tuple[set[str], set[str]]]] = {
        "required": [],
        "preferred": [],
        "mention": [],
    }
    for case_id, case in cases_by_id.items():
        expected = _concept_records(
            case.expected.fields,
            mentions=case.expected.skill_mentions,
        )
        predicted = _concept_records(predictions_by_id[case_id].fields)
        for strength, pairs in pairs_by_strength.items():
            pairs.append(
                (
                    {
                        item.skill_id
                        for item in expected
                        if item.strength == strength
                    },
                    {
                        item.skill_id
                        for item in predicted
                        if item.strength == strength
                    },
                )
            )
    class_metrics = {
        strength: _set_metric(pairs)
        for strength, pairs in pairs_by_strength.items()
    }
    return {
        "classes": class_metrics,
        "macro_f1": _safe_average(
            [
                metric["f1"]
                for metric in class_metrics.values()
                if metric["f1"] is not None
            ]
        ),
    }


def _skill_qualifier_metric(
    cases_by_id: dict[str, EvaluationCase],
    predictions_by_id: dict[str, PredictionRecord],
) -> dict[str, Any]:
    pairs: list[tuple[set[tuple[str, str]], set[tuple[str, str]]]] = []
    for case_id, case in cases_by_id.items():
        expected = {
            (item.skill_id, item.qualifier)
            for item in _concept_records(
                case.expected.fields,
                mentions=case.expected.skill_mentions,
            )
            if item.qualifier is not None
        }
        predicted = {
            (item.skill_id, item.qualifier)
            for item in _concept_records(predictions_by_id[case_id].fields)
            if item.qualifier is not None
        }
        pairs.append((expected, predicted))
    return _set_metric(pairs)


def _concept_any_of_relation_metric(
    cases_by_id: dict[str, EvaluationCase],
    predictions_by_id: dict[str, PredictionRecord],
) -> dict[str, Any]:
    expected_positive_cases = 0
    exact_match_cases = 0
    expected_negative_cases = 0
    false_positive_cases = 0
    for case_id, case in cases_by_id.items():
        expected = _concept_any_of_groups(case.expected.fields)
        predicted = _concept_any_of_groups(predictions_by_id[case_id].fields)
        if expected:
            expected_positive_cases += 1
            exact_match_cases += expected == predicted
        else:
            expected_negative_cases += 1
            false_positive_cases += bool(predicted)
    return {
        "expected_positive_case_count": expected_positive_cases,
        "exact_match_case_count": exact_match_cases,
        "conditional_exact_match_accuracy": _ratio(
            exact_match_cases,
            expected_positive_cases,
        ),
        "expected_negative_case_count": expected_negative_cases,
        "false_positive_case_count": false_positive_cases,
        "false_positive_case_rate": _ratio(
            false_positive_cases,
            expected_negative_cases,
        ),
    }


def _concept_records(
    fields: dict[str, Any],
    *,
    mentions: list[str] | None = None,
) -> list[_MetricConcept]:
    explicit = fields.get("skill_concepts")
    if isinstance(explicit, list) and explicit:
        records = _explicit_concept_records(explicit)
        if records:
            return records
    return _fallback_concept_records(fields, mentions=mentions)


def _explicit_concept_records(values: list[Any]) -> list[_MetricConcept]:
    records: list[_MetricConcept] = []
    for value in values:
        if not isinstance(value, dict):
            continue
        strength = value.get("strength")
        if strength not in {"required", "preferred", "mention"}:
            continue
        canonical_name = value.get("canonical_name")
        identities = normalize_skill_concepts(
            canonical_name,
            qualifier=value.get("qualifier"),
            source_text=value.get("source_text"),
        )
        for identity in identities:
            records.append(
                _MetricConcept(
                    skill_id=identity.skill_id,
                    strength=strength,
                    qualifier=identity.qualifier,
                    relation=(
                        value.get("relation")
                        if value.get("relation") in {"all_of", "any_of"}
                        else "all_of"
                    ),
                    group_name=value.get("group_name"),
                    allow_other=bool(value.get("allow_other", False)),
                    source_text=value.get("source_text"),
                )
            )
    return _unique_metric_concepts(records)


def _fallback_concept_records(
    fields: dict[str, Any],
    *,
    mentions: list[str] | None = None,
) -> list[_MetricConcept]:
    records: list[_MetricConcept] = []
    required_ids: set[str] = set()
    preferred_ids: set[str] = set()
    group_ids: set[str] = set()

    required = _metric_concepts_for_labels(
        fields.get("required_skills"),
        strength="required",
    )
    records.extend(required)
    required_ids.update(item.skill_id for item in required)

    raw_groups = fields.get("required_skill_groups")
    groups = raw_groups if isinstance(raw_groups, list) else [raw_groups]
    for raw_group in groups:
        if not isinstance(raw_group, dict):
            continue
        group = normalize_skill_group(raw_group, options_are_atomic=True)
        if group is None:
            continue
        options = _metric_concepts_for_labels(
            group["any_of"],
            strength="required",
            relation="any_of",
            group_name=group["name"],
            allow_other=group["allow_other"],
        )
        records.extend(options)
        group_ids.update(item.skill_id for item in options)

    preferred = [
        item
        for item in _metric_concepts_for_labels(
            fields.get("preferred_skills"),
            strength="preferred",
        )
        if item.skill_id not in required_ids and item.skill_id not in group_ids
    ]
    records.extend(preferred)
    preferred_ids.update(item.skill_id for item in preferred)

    raw_mentions: Any = mentions if mentions is not None else fields.get("skill_mentions")
    records.extend(
        item
        for item in _metric_concepts_for_labels(raw_mentions, strength="mention")
        if item.skill_id not in required_ids
        and item.skill_id not in group_ids
        and item.skill_id not in preferred_ids
    )
    return _unique_metric_concepts(records)


def _metric_concepts_for_labels(
    value: Any,
    *,
    strength: str,
    relation: str = "all_of",
    group_name: str | None = None,
    allow_other: bool = False,
) -> list[_MetricConcept]:
    values = value if isinstance(value, list) else [value]
    return [
        _MetricConcept(
            skill_id=identity.skill_id,
            strength=strength,
            qualifier=identity.qualifier,
            relation=relation,
            group_name=group_name,
            allow_other=allow_other,
        )
        for label in values
        for identity in normalize_skill_concepts(label)
    ]


def _concept_ids(records: list[_MetricConcept]) -> set[str]:
    return {item.skill_id for item in records}


def _concept_ids_for_labels(labels: list[str]) -> set[str]:
    return {
        identity.skill_id
        for label in labels
        for identity in normalize_skill_concepts(label)
    }


def _concept_any_of_groups(fields: dict[str, Any]) -> set[tuple[Any, ...]]:
    explicit = fields.get("skill_concepts")
    if isinstance(explicit, list) and explicit:
        records = [
            item for item in _explicit_concept_records(explicit)
            if item.relation == "any_of"
        ]
        grouped: dict[tuple[Any, ...], set[str]] = {}
        for item in records:
            grouping_key = (
                item.strength,
                item.group_name,
                item.source_text,
                item.allow_other,
            )
            grouped.setdefault(grouping_key, set()).add(item.skill_id)
        return {
            (strength, tuple(sorted(options)), allow_other)
            for (strength, _name, _source, allow_other), options in grouped.items()
            if len(options) >= 2
        }

    raw_groups = fields.get("required_skill_groups")
    groups = raw_groups if isinstance(raw_groups, list) else [raw_groups]
    signatures: set[tuple[Any, ...]] = set()
    for raw_group in groups:
        if not isinstance(raw_group, dict):
            continue
        group = normalize_skill_group(raw_group, options_are_atomic=True)
        if group is None:
            continue
        option_ids = _concept_ids_for_labels(group["any_of"])
        if len(option_ids) >= 2:
            signatures.add(
                ("required", tuple(sorted(option_ids)), group["allow_other"])
            )
    return signatures


def _unique_metric_concepts(
    records: list[_MetricConcept],
) -> list[_MetricConcept]:
    unique: list[_MetricConcept] = []
    seen: set[tuple[Any, ...]] = set()
    for item in records:
        key = (
            item.skill_id,
            item.strength,
            item.qualifier,
            item.relation,
            item.group_name,
            item.allow_other,
        )
        if key not in seen:
            unique.append(item)
            seen.add(key)
    return unique


def _expected_detected_skills(case: EvaluationCase) -> set[str]:
    explicit_mentions = _value_set(
        case.expected.skill_mentions,
        field_name="skill_mentions",
    )
    if explicit_mentions:
        return explicit_mentions
    return _detected_skill_union(case.expected.fields)


def _predicted_detected_skills(prediction: PredictionRecord) -> set[str]:
    return _detected_skill_union(prediction.fields)


def _detected_skill_union(fields: dict[str, Any]) -> set[str]:
    return set().union(
        _skill_field_set(fields, "required_skills"),
        _required_group_options(fields),
        _skill_field_set(fields, "preferred_skills"),
        _skill_field_set(fields, "skill_mentions"),
    )


def _skill_strength_sets(
    fields: dict[str, Any],
    *,
    mentions: list[str] | None = None,
) -> dict[str, set[str]]:
    group_options = _required_group_options(fields)
    required = _skill_field_set(fields, "required_skills") - group_options
    preferred = _skill_field_set(fields, "preferred_skills") - group_options
    raw_mentions = _value_set(
        mentions if mentions is not None else fields.get("skill_mentions"),
        field_name="skill_mentions",
    )
    mention_only = raw_mentions - required - preferred - group_options
    return {
        "required": required,
        "preferred": preferred,
        "mention": mention_only,
    }


def _skill_field_set(fields: dict[str, Any], field_name: str) -> set[str]:
    return _value_set(fields.get(field_name), field_name=field_name)


def _required_group_options(fields: dict[str, Any]) -> set[str]:
    raw_groups = fields.get("required_skill_groups")
    groups = raw_groups if isinstance(raw_groups, list) else [raw_groups]
    options: set[str] = set()
    for raw_group in groups:
        if not isinstance(raw_group, dict):
            continue
        normalized_group = normalize_skill_group(
            raw_group,
            options_are_atomic=True,
        )
        if normalized_group is None:
            continue
        options.update(
            _value_set(
                normalized_group.get("any_of"),
                field_name="skill_mentions",
            )
        )
    return options


def _set_metric(
    pairs: list[tuple[set[Any], set[Any]]],
) -> dict[str, Any]:
    true_positive = sum(len(expected & predicted) for expected, predicted in pairs)
    false_positive = sum(len(predicted - expected) for expected, predicted in pairs)
    false_negative = sum(len(expected - predicted) for expected, predicted in pairs)
    exact_match_cases = sum(expected == predicted for expected, predicted in pairs)
    precision = _ratio(true_positive, true_positive + false_positive)
    recall = _ratio(true_positive, true_positive + false_negative)
    return {
        "labeled_case_count": len(pairs),
        "exact_match_accuracy": _ratio(exact_match_cases, len(pairs)),
        "tp": true_positive,
        "fp": false_positive,
        "fn": false_negative,
        "precision": precision,
        "recall": recall,
        "f1": _f1(precision, recall),
    }


def _eligibility_accuracy(
    cases_by_id: dict[str, EvaluationCase],
    predictions_by_id: dict[str, PredictionRecord],
) -> float | None:
    labeled = [
        case
        for case in cases_by_id.values()
        if case.expected.eligibility is not None
    ]
    if not labeled:
        return None
    correct = sum(
        predictions_by_id[case.id].eligibility == case.expected.eligibility
        for case in labeled
    )
    return correct / len(labeled)


def _false_accept_rate(
    cases_by_id: dict[str, EvaluationCase],
    predictions_by_id: dict[str, PredictionRecord],
) -> float | None:
    failed_cases = [
        case
        for case in cases_by_id.values()
        if case.expected.eligibility == "fail"
    ]
    if not failed_cases:
        return None
    false_accepts = sum(
        predictions_by_id[case.id].eligibility == "pass" for case in failed_cases
    )
    return false_accepts / len(failed_cases)


def _failure_accuracy(
    cases_by_id: dict[str, EvaluationCase],
    predictions_by_id: dict[str, PredictionRecord],
) -> float | None:
    labeled = [
        case
        for case in cases_by_id.values()
        if case.expected.failure_code is not None
    ]
    if not labeled:
        return None
    correct = sum(
        predictions_by_id[case.id].failure_code == case.expected.failure_code
        for case in labeled
    )
    return correct / len(labeled)


def _evidence_precision(
    cases_by_id: dict[str, EvaluationCase],
    predictions_by_id: dict[str, PredictionRecord],
) -> float | None:
    predicted_count = 0
    correct_count = 0
    for case_id, case in cases_by_id.items():
        expected_by_requirement = case.expected.evidence
        for match in predictions_by_id[case_id].matches:
            expected_ids = set(expected_by_requirement.get(match.requirement_key, []))
            for evidence_id in match.evidence_ids:
                predicted_count += 1
                correct_count += evidence_id in expected_ids
    return _ratio(correct_count, predicted_count)


def _evidence_coverage(
    cases_by_id: dict[str, EvaluationCase],
    predictions_by_id: dict[str, PredictionRecord],
) -> float | None:
    expected_count = 0
    covered_count = 0
    for case_id, case in cases_by_id.items():
        for requirement_key, expected_ids in case.expected.evidence.items():
            expected_set = set(expected_ids)
            expected_count += len(expected_set)
            predicted_set = {
                evidence_id
                for match in predictions_by_id[case_id].matches
                if match.requirement_key == requirement_key
                for evidence_id in match.evidence_ids
            }
            covered_count += len(expected_set & predicted_set)
    return _ratio(covered_count, expected_count)


def _unsupported_claim_rate(
    cases_by_id: dict[str, EvaluationCase],
    predictions_by_id: dict[str, PredictionRecord],
) -> float:
    claims, unsupported_claims = _unsupported_claim_counts(
        cases_by_id,
        predictions_by_id,
    )
    return unsupported_claims / claims if claims else 0.0


def _unsupported_claim_counts(
    cases_by_id: dict[str, EvaluationCase],
    predictions_by_id: dict[str, PredictionRecord],
) -> tuple[int, int]:
    claims = 0
    unsupported_claims = 0
    for case_id, case in cases_by_id.items():
        for match in predictions_by_id[case_id].matches:
            if match.support_level == "unsupported":
                continue
            claims += 1
            expected_ids = set(case.expected.evidence.get(match.requirement_key, []))
            if not expected_ids or not expected_ids.intersection(match.evidence_ids):
                unsupported_claims += 1
    return claims, unsupported_claims


def _validator_summary(
    raw_predictions: list[PredictionRecord],
    validated_predictions: list[PredictionRecord],
) -> dict[str, int]:
    downgraded_matches = 0
    removed_evidence_ids = 0
    issues = 0
    for raw, validated in zip(raw_predictions, validated_predictions, strict=True):
        for raw_match, validated_match in zip(
            raw.matches,
            validated.matches,
            strict=True,
        ):
            if raw_match.support_level != validated_match.support_level:
                downgraded_matches += 1
            removed_evidence_ids += len(raw_match.evidence_ids) - len(
                validated_match.evidence_ids
            )
            issues += len(validated_match.validation_issues)
    return {
        "downgraded_matches": downgraded_matches,
        "removed_evidence_ids": removed_evidence_ids,
        "validation_issue_count": issues,
    }


def _threshold_results(
    metrics: dict[str, Any],
    thresholds: dict[str, float],
) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for metric_name, threshold in thresholds.items():
        actual = metrics.get(metric_name)
        if actual is None:
            results[metric_name] = {
                "threshold": threshold,
                "actual": None,
                "passed": False,
            }
            continue
        lower_is_better = {
            "false_accept_rate",
            "unsupported_claim_rate",
        }
        passed = (
            actual <= threshold
            if metric_name in lower_is_better
            else actual >= threshold
        )
        results[metric_name] = {
            "threshold": threshold,
            "actual": actual,
            "passed": passed,
        }
    return results


def _value_set(value: Any, *, field_name: str | None = None) -> set[str]:
    if value is None:
        return set()
    if field_name in {"required_skills", "preferred_skills", "skill_mentions"}:
        values = value if isinstance(value, list) else [value]
        return {
            _canonical(item)
            for item in normalize_atomic_skill_values(values)
        }
    if isinstance(value, list):
        return {_canonical(item, field_name=field_name) for item in value}
    return {_canonical(value, field_name=field_name)}


def _canonical(value: Any, *, field_name: str | None = None) -> str:
    if field_name == "required_skill_groups" and isinstance(value, dict):
        normalized_group = normalize_skill_group(
            value,
            options_are_atomic=True,
        ) or value
        raw_options = normalized_group.get("any_of")
        options = raw_options if isinstance(raw_options, list) else []
        canonical_group = {
            "any_of": sorted({_canonical(option) for option in options}),
            "allow_other": bool(normalized_group.get("allow_other", False)),
        }
        return json.dumps(
            canonical_group,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    if isinstance(value, str):
        normalized = unicodedata.normalize("NFKC", value).strip().casefold()
        normalized = re.sub(r"\s+", " ", normalized)
        if field_name == "locations" and normalized.endswith("市"):
            normalized = normalized[:-1]
        return normalized
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _deduplicate(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _f1(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None or precision + recall == 0:
        return 0.0 if precision == 0 or recall == 0 else None
    return 2 * precision * recall / (precision + recall)


def _safe_average(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None
