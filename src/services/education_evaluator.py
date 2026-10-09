"""Local three-valued evaluation; a branch must use one education record."""

from __future__ import annotations

from dataclasses import dataclass

from src.domain.education import (
    DEGREE_LABELS,
    DEGREE_RANK,
    EducationBranch,
    EducationCondition,
    EducationRecord,
    MajorPredicate,
    comparable,
    degree_levels,
)
from src.domain.education_dates import supported_graduation_year
from src.domain.eligibility import CandidateProfileInput

# Deliberately bounded vocabulary, independent of model guesses. Unlisted or
# interdisciplinary names remain unknown. Changes to this policy need tests.
MAJOR_POLICY_VERSION = "education-major-v2-positive-only"
MAJOR_FAMILIES = {
    "computer": (
        "计算机",
        "计算机科学",
        "计算机科学与技术",
        "计算机技术",
        "软件工程",
        "网络工程",
        "信息安全",
        "人工智能",
        "数据科学与大数据技术",
        "computer science",
        "software engineering",
    ),
    "mechanical": (
        "机械",
        "机械工程",
        "机械设计制造及其自动化",
        "车辆工程",
        "mechanical engineering",
    ),
    "finance": ("金融", "金融学", "金融工程", "finance"),
    "math": ("数学", "数学与应用数学", "统计学", "mathematics", "statistics"),
}


def major_key(value: str) -> str:
    return comparable(value).removesuffix("相关专业").removesuffix("专业")


def major_family(value: str) -> str | None:
    key = major_key(value)
    return next(
        (
            family
            for family, names in MAJOR_FAMILIES.items()
            if key in {major_key(name) for name in names}
        ),
        None,
    )


def match_major(value: str | None, predicate: MajorPredicate) -> str:
    if predicate.mode in {"any", "not_specified"}:
        return "pass"
    if predicate.mode == "unknown" or value is None:
        return "unknown"
    if major_key(value) in {major_key(v) for v in predicate.values}:
        return "pass"
    if predicate.mode == "exact":
        return "fail"
    candidate_family = major_family(value)
    target_families = {major_family(v) for v in predicate.values}
    if candidate_family and candidate_family in target_families:
        return "pass"
    # Different families do not prove that an employer excludes a related major.
    return "unknown"


def candidate_educations(profile: CandidateProfileInput) -> list[EducationRecord]:
    if profile.educations or profile.education_history_complete:
        return profile.educations
    # A legacy scalar tuple represents at most one record, never a complete history.
    if not any((profile.degree, profile.major, profile.graduation_year)):
        return []
    levels = degree_levels(profile.degree or "")
    return [
        EducationRecord(
            id="edu_legacy",
            level=next(iter(levels)) if len(levels) == 1 else "unknown",
            major_raw=profile.major,
            graduation_year=profile.graduation_year,
            source="legacy_profile",
            source_text="；".join(
                str(v)
                for v in (profile.degree, profile.major, profile.graduation_year)
                if v
            ),
        )
    ]


def _and(results: list[str]) -> str:
    return (
        "fail" if "fail" in results else "unknown" if "unknown" in results else "pass"
    )


def binds_application_cohort(condition: EducationCondition) -> bool:
    """Every accepting path must require a record for the application degree."""
    scopes = [branch.scope == "application" for branch in condition.branches]
    if condition.relation == "all_of":
        return any(scopes)
    if condition.relation == "any_of":
        return all(scopes)
    return False


def _record_result(
    record: EducationRecord,
    branch: EducationBranch,
    graduation_years: list[int] | None = None,
) -> str:
    degree = branch.degree
    if degree.operator in {"any", "not_specified"}:
        degree_result = "pass"
    elif degree.operator == "unknown" or record.level == "unknown":
        degree_result = "unknown"
    else:
        matches = (
            record.level == degree.level
            if degree.operator == "eq"
            else DEGREE_RANK[record.level] >= DEGREE_RANK[degree.level]
        )
        degree_result = "pass" if matches else "fail"
    results = [degree_result, match_major(record.major_raw, branch.major)]
    graduation_year = supported_graduation_year(record)
    if branch.graduation_years is not None:
        results.append(
            "unknown"
            if graduation_year is None
            else "pass"
            if graduation_year in branch.graduation_years
            else "fail"
        )
    if graduation_years and branch.scope == "application":
        results.append(
            "unknown"
            if graduation_year is None
            else "pass"
            if graduation_year in graduation_years
            else "fail"
        )
    elif graduation_years and branch.scope == "unknown":
        results.append("unknown")
    if branch.status != "any":
        results.append(
            "unknown"
            if "unknown" in {branch.status, record.status}
            else "pass"
            if record.status == branch.status
            else "fail"
        )
    if branch.unresolved:
        results.append("unknown")
    return _and(results)


@dataclass(frozen=True)
class EducationEvaluation:
    result: str
    reason: str
    evidence: list[EducationRecord]


def evaluate_education(
    condition: EducationCondition,
    profile: CandidateProfileInput,
    *,
    graduation_years: list[int] | None = None,
) -> EducationEvaluation:
    records = candidate_educations(profile)
    branch_results: list[str] = []
    evidence: dict[str, EducationRecord] = {}
    details: list[str] = []
    for branch in condition.branches:
        outcomes = [
            (record, _record_result(record, branch, graduation_years))
            for record in records
        ]
        supported = [record for record, status in outcomes if status == "pass"]
        if supported:
            result = "pass"
            for record in supported:
                evidence[record.id] = record
            names = "、".join(
                f"{DEGREE_LABELS[r.level]}／{r.major_raw or '专业未填'}"
                for r in supported
            )
            details.append(f"“{branch.source_text}”由 {names} 满足")
        else:
            result = (
                "unknown"
                if any(status == "unknown" for _, status in outcomes)
                or not profile.education_history_complete
                else "fail"
            )
            details.append(
                f"“{branch.source_text}”：{'信息不足（字段、专业归类或教育经历完整性待确认）' if result == 'unknown' else '已确认的完整教育经历均不满足'}"
            )
        branch_results.append(result)
    if condition.relation == "uncertain":
        result = "unknown"
    elif condition.relation == "any_of":
        result = (
            "pass"
            if "pass" in branch_results
            else "unknown"
            if "unknown" in branch_results
            else "fail"
        )
    else:
        result = _and(branch_results)
    cited = list(evidence.values()) if result == "pass" else records
    reason = "；".join(details)
    if graduation_years:
        reason += f"；届别 {graduation_years} 仅作用于本次申请学历，历史教育背景独立检查；适用范围不明时待确认"
    return EducationEvaluation(result=result, reason=reason, evidence=cited)
