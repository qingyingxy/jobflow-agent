from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Sequence

from src.domain.job import JobRequirement
from src.domain.matching import (
    EvidenceMatchModelOutput,
    EvidenceRecord,
    RequirementMatch,
)
from src.domain.suggestion import ResumeSuggestionModelOutput
from src.services.eligibility_checker import normalize_text

_NUMBER_PATTERN = re.compile(r"\d+(?:\.\d+)?")
_LATIN_TERM_PATTERN = re.compile(r"\b[A-Za-z][A-Za-z0-9+#.-]{1,}\b")
_PROJECT_PHRASE_PATTERN = re.compile(
    r"(?:在|通过|基于)([^，。；,;]{1,30})(?:项目|系统|平台)"
)
_UNSUPPORTED_CLAIM_MARKERS = (
    "已掌握",
    "掌握",
    "具备",
    "熟悉",
    "实现了",
    "完成了",
)
_COMMON_LATIN_WORDS = {
    "a",
    "an",
    "and",
    "experience",
    "has",
    "in",
    "the",
    "to",
    "user",
    "with",
}


def _deduplicate(values: Sequence[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result


def _selected_text(evidence: Sequence[EvidenceRecord]) -> str:
    return " ".join(
        [
            item.title
            for item in evidence
        ]
        + [item.claim for item in evidence]
        + [skill for item in evidence for skill in item.skills]
    )


def _fact_issues(
    explanation: str,
    claims: Sequence[str],
    evidence: Sequence[EvidenceRecord],
) -> list[str]:
    allowed = normalize_text(_selected_text(evidence))
    issues: list[str] = []
    for claim in claims:
        if normalize_text(claim) not in allowed:
            issues.append("模型声明了当前证据中不存在的事实")
            break

    for number in _NUMBER_PATTERN.findall(explanation):
        if number not in allowed:
            issues.append("模型解释包含当前证据中不存在的数字")
            break

    for term in _LATIN_TERM_PATTERN.findall(explanation):
        if term.casefold() in _COMMON_LATIN_WORDS:
            continue
        if normalize_text(term) not in allowed:
            issues.append("模型解释包含当前证据中不存在的技能或项目名")
            break

    for phrase in _PROJECT_PHRASE_PATTERN.findall(explanation):
        normalized_phrase = normalize_text(phrase).removeprefix("用户的")
        if normalized_phrase and normalized_phrase not in allowed:
            issues.append("模型解释包含当前证据中不存在的项目或系统")
            break
    return issues


def validate_requirement_match(
    *,
    user_id: str,
    requirement: JobRequirement,
    output: EvidenceMatchModelOutput,
    evidence: Sequence[EvidenceRecord],
) -> RequirementMatch:
    """Validate and, when necessary, safely downgrade one model match."""

    records_by_id: dict[str, list[EvidenceRecord]] = defaultdict(list)
    for item in evidence:
        records_by_id[item.id].append(item)

    requested_ids = _deduplicate(output.evidence_ids)
    selected: list[EvidenceRecord] = []
    issues: list[str] = []
    for evidence_id in requested_ids:
        records = records_by_id.get(evidence_id, [])
        owned = [item for item in records if item.user_id == user_id]
        if not owned:
            issues.append(f"evidence_id 无效或不属于当前用户: {evidence_id}")
            continue
        if any(item.user_id != user_id for item in records):
            issues.append(f"evidence_id 存在跨用户引用: {evidence_id}")
        selected.append(owned[0])

    if output.support_level == "unsupported":
        if requested_ids:
            issues.append("unsupported 结果不能引用 evidence_id")
        if output.claims:
            issues.append("unsupported 结果不能包含证据事实声明")
        if any(marker in output.explanation for marker in _UNSUPPORTED_CLAIM_MARKERS):
            issues.append("unsupported 结果不能把要求描述为用户已经掌握")
    elif not selected:
        issues.append("supported 或 partial 结果至少需要一个有效 evidence_id")
    else:
        issues.extend(_fact_issues(output.explanation, output.claims, selected))

    if issues:
        return RequirementMatch(
            requirement=requirement,
            support_level="unsupported",
            evidence_ids=[],
            explanation=f"没有找到可以验证“{requirement.name}”的当前用户经历证据。",
            validation_status="failed",
            validation_issues=_deduplicate(issues),
        )

    return RequirementMatch(
        requirement=requirement,
        support_level=output.support_level,
        evidence_ids=requested_ids,
        explanation=output.explanation.strip(),
        validation_status="passed",
    )


def validate_suggestion_output(
    *,
    user_id: str,
    original_text: str,
    output: ResumeSuggestionModelOutput,
    evidence: Sequence[EvidenceRecord],
) -> list[str]:
    """Return evidence-grounding issues without turning model text into final text."""

    records_by_id: dict[str, list[EvidenceRecord]] = defaultdict(list)
    for item in evidence:
        records_by_id[item.id].append(item)

    issues: list[str] = []
    selected: list[EvidenceRecord] = []
    for evidence_id in _deduplicate(output.evidence_ids):
        records = records_by_id.get(evidence_id, [])
        owned = [item for item in records if item.user_id == user_id]
        if not owned:
            issues.append(f"evidence_id 无效或不属于当前用户: {evidence_id}")
            continue
        if any(item.user_id != user_id for item in records):
            issues.append(f"evidence_id 存在跨用户引用: {evidence_id}")
        selected.append(owned[0])

    if not selected:
        issues.append("建议至少需要一个当前用户的有效 evidence_id")
        return _deduplicate(issues)

    evidence_text = _selected_text(selected)
    allowed = normalize_text(f"{original_text} {evidence_text}")
    evidence_only = normalize_text(evidence_text)
    for claim in output.claims:
        if normalize_text(claim) not in evidence_only:
            issues.append("建议声明了当前证据中不存在的事实")
            break

    for number in _NUMBER_PATTERN.findall(output.suggestion_text):
        if number not in allowed:
            issues.append("建议文本包含原文和当前证据中不存在的数字")
            break

    for term in _LATIN_TERM_PATTERN.findall(output.suggestion_text):
        if term.casefold() in _COMMON_LATIN_WORDS:
            continue
        if normalize_text(term) not in allowed:
            issues.append("建议文本包含原文和当前证据中不存在的技能或项目名")
            break

    for phrase in _PROJECT_PHRASE_PATTERN.findall(output.suggestion_text):
        normalized_phrase = normalize_text(phrase).removeprefix("用户的")
        if normalized_phrase and normalized_phrase not in allowed:
            issues.append("建议文本包含当前证据中不存在的项目或系统")
            break

    return _deduplicate(issues)


class EvidenceValidator:
    @staticmethod
    def validate(
        *,
        user_id: str,
        requirement: JobRequirement,
        output: EvidenceMatchModelOutput,
        evidence: Sequence[EvidenceRecord],
    ) -> RequirementMatch:
        return validate_requirement_match(
            user_id=user_id,
            requirement=requirement,
            output=output,
            evidence=evidence,
        )
