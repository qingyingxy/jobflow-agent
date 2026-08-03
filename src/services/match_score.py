from __future__ import annotations

from collections.abc import Sequence

from src.domain.eligibility import EligibilityResult
from src.domain.job import JobRequirement
from src.domain.matching import (
    MatchScore,
    RequirementMatch,
    ScoreGroupResult,
    requirement_key,
)

GROUP_WEIGHTS = {
    "required_skill": 0.60,
    "preferred_skill": 0.20,
    "preferences": 0.20,
}

_SUPPORT_VALUES = {
    "supported": 1.0,
    "partial": 0.5,
    "unsupported": 0.0,
}


def _deduplicate_requirements(
    requirements: Sequence[JobRequirement] | None,
) -> list[JobRequirement] | None:
    if requirements is None:
        return None
    result: list[JobRequirement] = []
    seen: set[str] = set()
    for requirement in requirements:
        key = requirement_key(requirement)
        if key not in seen:
            result.append(requirement)
            seen.add(key)
    return result


def _skill_group(
    *,
    group: str,
    requirements: Sequence[JobRequirement] | None,
    matches: Sequence[RequirementMatch],
) -> ScoreGroupResult:
    original_weight = GROUP_WEIGHTS[group]
    if requirements is None:
        return ScoreGroupResult(
            group=group,
            status="insufficient_data",
            original_weight=original_weight,
            effective_weight=0,
            reason="岗位要求列表缺失，不能判断该技能分组是否适用",
        )

    selected = [item for item in requirements if item.category == group]
    if not selected:
        return ScoreGroupResult(
            group=group,
            status="not_applicable",
            original_weight=original_weight,
            effective_weight=0,
            denominator=0,
            reason="岗位要求已明确列出，但没有该类技能要求",
        )

    match_by_key: dict[str, RequirementMatch] = {}
    for match in matches:
        match_by_key.setdefault(requirement_key(match.requirement), match)
    values = [
        _SUPPORT_VALUES.get(
            match_by_key.get(requirement_key(requirement), None).support_level
            if match_by_key.get(requirement_key(requirement), None) is not None
            else "unsupported",
            0.0,
        )
        for requirement in selected
    ]
    numerator = sum(values)
    denominator = len(values)
    score = numerator / denominator
    return ScoreGroupResult(
        group=group,
        status="applicable",
        original_weight=original_weight,
        effective_weight=0,
        score=score,
        numerator=numerator,
        denominator=denominator,
        reason="按规范化后的岗位要求和匹配结论计算",
    )


def _preference_group(eligibility: EligibilityResult) -> ScoreGroupResult:
    checks = [
        check
        for check in eligibility.checks
        if check.field in {"locations", "job_type"}
    ]
    original_weight = GROUP_WEIGHTS["preferences"]
    values = [
        1.0 if check.result == "pass" else 0.0
        for check in checks
        if check.result in {"pass", "fail"}
    ]
    if not values:
        return ScoreGroupResult(
            group="preferences",
            status="insufficient_data",
            original_weight=original_weight,
            effective_weight=0,
            reason="地点或岗位类型偏好缺少可判断信息",
        )
    numerator = sum(values)
    return ScoreGroupResult(
        group="preferences",
        status="applicable",
        original_weight=original_weight,
        effective_weight=0,
        score=numerator / len(values),
        numerator=numerator,
        denominator=len(values),
        reason="按地点和岗位类型资格检查的可判断结果计算",
    )


def calculate_match_score(
    *,
    requirements: Sequence[JobRequirement] | None,
    matches: Sequence[RequirementMatch],
    eligibility: EligibilityResult,
) -> MatchScore:
    """Calculate a reproducible 60/20/20 score with explicit missing data."""

    canonical_requirements = _deduplicate_requirements(requirements)
    groups = [
        _skill_group(
            group="required_skill",
            requirements=canonical_requirements,
            matches=matches,
        ),
        _skill_group(
            group="preferred_skill",
            requirements=canonical_requirements,
            matches=matches,
        ),
        _preference_group(eligibility),
    ]
    has_insufficient_data = any(
        group.status == "insufficient_data" for group in groups
    )
    applicable_groups = [group for group in groups if group.status == "applicable"]
    weight_total = sum(group.original_weight for group in applicable_groups)
    if has_insufficient_data or not applicable_groups or weight_total <= 0:
        score = None
    else:
        for group in groups:
            if group.status == "applicable":
                group.effective_weight = round(
                    group.original_weight / weight_total,
                    6,
                )
        score = round(
            sum(
                (group.score or 0) * group.effective_weight
                for group in applicable_groups
            )
            * 100,
            2,
        )

    missing_information = [
        item
        for check in eligibility.checks
        for item in check.missing_information
    ]
    if has_insufficient_data:
        missing_information.append("补充缺失的 JD 要求或用户偏好")
    missing_information = list(dict.fromkeys(missing_information))

    if eligibility.eligible == "fail":
        recommendation = "not_recommended"
    elif eligibility.eligible == "unknown":
        recommendation = "needs_confirmation"
    elif score is None:
        recommendation = "insufficient_data"
    else:
        recommendation = "recommended"

    return MatchScore(
        score=score,
        eligibility=eligibility.eligible,
        recommendation=recommendation,
        groups=groups,
        missing_information=missing_information,
    )


class MatchScoreCalculator:
    @staticmethod
    def calculate(
        *,
        requirements: Sequence[JobRequirement] | None,
        matches: Sequence[RequirementMatch],
        eligibility: EligibilityResult,
    ) -> MatchScore:
        return calculate_match_score(
            requirements=requirements,
            matches=matches,
            eligibility=eligibility,
        )
