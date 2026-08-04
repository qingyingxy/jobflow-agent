from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

from src.evaluation.models import (
    EvaluationCase,
    EvaluationManifest,
    PredictionMatch,
    PredictionRecord,
)

EvaluationReport = dict[str, Any]


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
        failure_code=prediction.failure_code,
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
    report: EvaluationReport = {
        "manifest_version": manifest.manifest_version,
        "dataset_version": manifest.dataset_version,
        "split": manifest.split,
        "case_count": len(cases_by_id),
        "prediction_count": len(predictions),
        "prediction_failure_count": sum(
            prediction.failure_code is not None for prediction in predictions
        ),
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
    return {
        "fields": field_metrics,
        "macro_f1": _safe_average(macro_values),
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
    for case_id, case in cases_by_id.items():
        if field_name not in case.expected.fields:
            continue
        labeled_cases += 1
        expected = _value_set(case.expected.fields[field_name])
        predicted = _value_set(predictions_by_id[case_id].fields.get(field_name))
        true_positive += len(expected & predicted)
        false_positive += len(predicted - expected)
        false_negative += len(expected - predicted)

    precision = _ratio(true_positive, true_positive + false_positive)
    recall = _ratio(true_positive, true_positive + false_negative)
    f1 = _f1(precision, recall)
    return {
        "labeled_case_count": labeled_cases,
        "tp": true_positive,
        "fp": false_positive,
        "fn": false_negative,
        "precision": precision,
        "recall": recall,
        "f1": f1,
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
    return unsupported_claims / claims if claims else 0.0


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


def _value_set(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, list):
        return {_canonical(item) for item in value}
    return {_canonical(value)}


def _canonical(value: Any) -> str:
    if isinstance(value, str):
        normalized = unicodedata.normalize("NFKC", value).strip().casefold()
        return re.sub(r"\s+", " ", normalized)
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
