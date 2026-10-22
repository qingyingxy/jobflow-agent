from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from src.evaluation.unified_models import UnifiedEvaluationManifest

DEFAULT_DRAFT = Path(
    "artifacts/evaluation/unified-jd-dev50-draft-v1-2026-09-03.json"
)
DEFAULT_DECISIONS = Path(
    "datasets/unified_jd_dev50_human_review_round1_decisions_v1_2026_09_03.json"
)
DEFAULT_OUTPUT = Path(
    "artifacts/evaluation/"
    "unified-jd-dev50-review-candidate-v1-2026-09-04.json"
)

ROUND1_REVIEW_NOTE = (
    "第一轮语义决策已应用；当前仍为 draft review candidate，"
    "尚未完成第二轮完整人工复核。"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"JSON root must be an object: {path}")
    return payload


def _matching_clause_indexes(
    case: dict[str, Any],
    match: dict[str, Any],
) -> list[int]:
    clauses = case["expected"]["clauses"]
    return [
        index
        for index, clause in enumerate(clauses)
        if all(clause.get(key) == value for key, value in match.items())
    ]


def _single_clause_index(
    case: dict[str, Any],
    match: dict[str, Any],
    *,
    operation: str,
) -> int:
    indexes = _matching_clause_indexes(case, match)
    if len(indexes) != 1:
        raise ValueError(
            f"{case['id']} {operation} expected one clause match, "
            f"found {len(indexes)} for {match}"
        )
    return indexes[0]


def _apply_update_clause(
    case: dict[str, Any],
    change: dict[str, Any],
) -> None:
    match = change.get("match")
    updates = change.get("changes")
    if not isinstance(match, dict) or not isinstance(updates, dict):
        raise TypeError(f"{case['id']} update_clause requires match and changes")
    index = _single_clause_index(case, match, operation="update_clause")
    case["expected"]["clauses"][index].update(copy.deepcopy(updates))


def _apply_add_clause(case: dict[str, Any], change: dict[str, Any]) -> None:
    clause = change.get("value", change.get("clause"))
    if not isinstance(clause, dict):
        raise TypeError(f"{case['id']} add_clause requires value or clause")
    case["expected"]["clauses"].append(copy.deepcopy(clause))


def _apply_remove_clause(case: dict[str, Any], change: dict[str, Any]) -> None:
    match = change.get("match")
    if not isinstance(match, dict):
        raise TypeError(f"{case['id']} remove_clause requires match")
    index = _single_clause_index(case, match, operation="remove_clause")
    del case["expected"]["clauses"][index]


def _apply_replace_clauses(case: dict[str, Any], change: dict[str, Any]) -> None:
    source_texts = change.get("match_source_texts")
    replacement = change.get("value")
    if not isinstance(source_texts, list) or not source_texts:
        raise ValueError(f"{case['id']} replace_clauses needs source texts")
    if isinstance(replacement, dict):
        replacements = [replacement]
    elif isinstance(replacement, list) and replacement and all(
        isinstance(item, dict) for item in replacement
    ):
        replacements = replacement
    else:
        raise TypeError(
            f"{case['id']} replace_clauses requires one or more values"
        )

    indexes = [
        _single_clause_index(
            case,
            {"source_text": source_text},
            operation="replace_clauses",
        )
        for source_text in source_texts
    ]
    if len(indexes) != len(set(indexes)):
        raise ValueError(f"{case['id']} replace_clauses matched duplicate clauses")

    clauses = case["expected"]["clauses"]
    insertion_index = min(indexes)
    for index in sorted(indexes, reverse=True):
        del clauses[index]
    clauses[insertion_index:insertion_index] = copy.deepcopy(replacements)


def _apply_remove_fact_value_and_evidence(
    case: dict[str, Any],
    change: dict[str, Any],
) -> None:
    field = change.get("field")
    value = change.get("value")
    source_text = change.get("source_text")
    facts = case["expected"]["facts"]
    values = facts.get(field)
    if not isinstance(field, str) or not isinstance(values, list):
        raise TypeError(f"{case['id']} cannot remove fact value from {field}")
    if values.count(value) != 1:
        raise ValueError(
            f"{case['id']} expected one {field} value {value!r}, "
            f"found {values.count(value)}"
        )
    remaining_values = [item for item in values if item != value]
    facts[field] = remaining_values or None

    evidence = facts["evidence"]
    matching_evidence = [
        index
        for index, item in enumerate(evidence)
        if item.get("field") == field and item.get("source_text") == source_text
    ]
    if len(matching_evidence) != 1:
        raise ValueError(
            f"{case['id']} expected one fact evidence match, "
            f"found {len(matching_evidence)}"
        )
    del evidence[matching_evidence[0]]


def _apply_update_fact_evidence(
    case: dict[str, Any],
    change: dict[str, Any],
) -> None:
    field = change.get("field")
    source_text = change.get("source_text")
    replacement_source_text = change.get("replacement_source_text")
    if not all(
        isinstance(value, str)
        for value in (field, source_text, replacement_source_text)
    ):
        raise TypeError(
            f"{case['id']} update_fact_evidence requires string fields"
        )

    matches = [
        item
        for item in case["expected"]["facts"]["evidence"]
        if item.get("field") == field and item.get("source_text") == source_text
    ]
    if len(matches) != 1:
        raise ValueError(
            f"{case['id']} expected one fact evidence match, "
            f"found {len(matches)}"
        )
    matches[0]["source_text"] = replacement_source_text


def _apply_change(case: dict[str, Any], change: dict[str, Any]) -> None:
    handlers = {
        "update_clause": _apply_update_clause,
        "add_clause": _apply_add_clause,
        "remove_clause": _apply_remove_clause,
        "replace_clauses": _apply_replace_clauses,
        "remove_fact_value_and_evidence": _apply_remove_fact_value_and_evidence,
        "update_fact_evidence": _apply_update_fact_evidence,
    }
    operation = change.get("operation")
    handler = handlers.get(operation)
    if handler is None:
        raise ValueError(f"{case['id']} unsupported operation: {operation}")
    handler(case, change)


def build_review_candidate(
    *,
    draft_path: Path,
    decisions_path: Path,
) -> UnifiedEvaluationManifest:
    actual_draft_hash = _sha256(draft_path)
    draft = _load_json_object(draft_path)
    review = _load_json_object(decisions_path)

    expected_hash = review.get("source_draft_sha256")
    if actual_draft_hash != expected_hash:
        raise ValueError(
            "round-1 decisions are bound to a different source draft: "
            f"expected {expected_hash}, got {actual_draft_hash}"
        )
    if review.get("status") != "round1_complete":
        raise ValueError("round-1 decision file must have status=round1_complete")

    cases = draft.get("cases")
    decisions = review.get("decisions")
    if not isinstance(cases, list) or not isinstance(decisions, dict):
        raise TypeError("draft cases and review decisions must be present")
    case_ids = [case["id"] for case in cases]
    if len(case_ids) != 50 or len(case_ids) != len(set(case_ids)):
        raise ValueError("Unified dev-50 draft must contain 50 unique cases")
    if set(case_ids) != set(decisions):
        missing = sorted(set(case_ids) - set(decisions))
        extra = sorted(set(decisions) - set(case_ids))
        raise ValueError(f"decision coverage mismatch: missing={missing}, extra={extra}")

    candidate = copy.deepcopy(draft)
    candidate["manifest_version"] = "unified-jd-dev50-review-candidate-v1"
    candidate["dataset_version"] = (
        "unified-jd-dev50-review-candidate-v1-2026-09-04"
    )
    candidate["purpose"] = (
        "Unified dev-50 第一轮语义决策已应用的 review candidate；"
        "仍为 draft，只用于第二轮完整人工复核，评测运行器必须拒绝计算成绩。"
    )
    candidate["label_status"] = "draft"

    candidate_cases = {case["id"]: case for case in candidate["cases"]}
    for case_id in case_ids:
        decision = decisions[case_id]
        if decision.get("status") != "confirmed":
            raise ValueError(f"{case_id} decision is not confirmed")
        decision_kind = decision.get("decision")
        if decision_kind not in {"keep", "modify"}:
            raise ValueError(f"{case_id} has invalid decision: {decision_kind}")
        changes = decision.get("planned_changes", [])
        if decision_kind == "modify" and not changes:
            raise ValueError(f"{case_id} modify decision has no planned changes")
        if decision_kind == "keep" and changes:
            raise ValueError(f"{case_id} keep decision unexpectedly has changes")

        case = candidate_cases[case_id]
        for change in changes:
            if not isinstance(change, dict):
                raise TypeError(f"{case_id} planned change must be an object")
            _apply_change(case, change)
        case["annotation_status"] = "draft"
        case.setdefault("review_notes", []).append(
            f"{ROUND1_REVIEW_NOTE} 决策：{decision_kind}。"
        )

    return UnifiedEvaluationManifest.model_validate(candidate)


def write_review_candidate(
    *,
    draft_path: Path,
    decisions_path: Path,
    output_path: Path,
) -> UnifiedEvaluationManifest:
    manifest = build_review_candidate(
        draft_path=draft_path,
        decisions_path=decisions_path,
    )
    rendered = manifest.model_dump_json(indent=2) + "\n"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and output_path.read_text(encoding="utf-8") != rendered:
        raise FileExistsError(f"refusing to overwrite changed file: {output_path}")
    output_path.write_text(rendered, encoding="utf-8")
    return manifest


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply confirmed round-1 decisions to the Unified dev-50 draft"
    )
    parser.add_argument("--draft", type=Path, default=DEFAULT_DRAFT)
    parser.add_argument("--decisions", type=Path, default=DEFAULT_DECISIONS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    arguments = _parse_args()
    manifest = write_review_candidate(
        draft_path=arguments.draft,
        decisions_path=arguments.decisions,
        output_path=arguments.output,
    )
    print(
        "unified dev-50 review candidate validated "
        f"cases={len(manifest.cases)} "
        f"status={manifest.label_status} "
        f"sha256={_sha256(arguments.output)} "
        f"output={arguments.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
