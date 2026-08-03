from __future__ import annotations

import re
import unicodedata
from datetime import date

from src.domain.eligibility import (
    EligibilityCheck,
    EligibilityInput,
    EligibilityResult,
)
from src.domain.job import FieldEvidence, StructuredJobDescription

_DEGREE_TERMS: tuple[tuple[str, int], ...] = (
    ("博士", 5),
    ("phd", 5),
    ("doctor", 5),
    ("硕士", 4),
    ("研究生", 4),
    ("master", 4),
    ("本科", 3),
    ("学士", 3),
    ("bachelor", 3),
    ("大专", 2),
    ("专科", 2),
    ("college", 2),
    ("中专", 1),
    ("高中", 1),
)

_MAJOR_FAMILIES: dict[str, tuple[str, ...]] = {
    "computer": (
        "计算机",
        "软件工程",
        "网络工程",
        "信息安全",
        "人工智能",
        "数据科学",
        "数据分析",
        "电子信息",
        "通信工程",
        "computerscience",
        "softwareengineering",
        "artificialintelligence",
    ),
    "mathematics": ("数学", "统计", "mathematics", "statistics"),
    "electrical": ("电气", "自动化", "electrical", "automation"),
    "mechanical": ("机械", "车辆工程", "mechanical"),
    "finance": ("金融", "财务", "会计", "经济", "finance", "accounting"),
}

_LOCATION_ALIASES: dict[str, str] = {
    "北京": "北京",
    "北京市": "北京",
    "上海": "上海",
    "上海市": "上海",
    "广州": "广州",
    "广州市": "广州",
    "深圳": "深圳",
    "深圳市": "深圳",
    "杭州": "杭州",
    "杭州市": "杭州",
    "南京": "南京",
    "南京市": "南京",
    "成都": "成都",
    "成都市": "成都",
    "武汉": "武汉",
    "武汉市": "武汉",
    "西安": "西安",
    "西安市": "西安",
    "全国": "全国",
    "全国各地": "全国",
    "不限": "全国",
    "不限地点": "全国",
    "remote": "远程",
    "远程": "远程",
}


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[\s\-_、,，/|()（）]+", "", normalized)


def normalize_location(value: str) -> str:
    normalized = normalize_text(value)
    if normalized in _LOCATION_ALIASES:
        return _LOCATION_ALIASES[normalized]
    for alias, canonical in _LOCATION_ALIASES.items():
        if normalized.startswith(alias) and len(normalized) > len(alias):
            return canonical
    return normalized.removesuffix("省").removesuffix("市")


def _evidence_for(
    job: StructuredJobDescription,
    *field_names: str,
) -> list[FieldEvidence]:
    evidence = job.field_evidence or []
    result: list[FieldEvidence] = []
    for item in evidence:
        if any(
            item.field_path == field_name
            or item.field_path.startswith(f"{field_name}[")
            for field_name in field_names
        ):
            result.append(item)
    return result


def _check(
    *,
    rule_name: str,
    field: str,
    result: str,
    reason: str,
    jd_evidence: list[FieldEvidence] | None = None,
    missing_information: list[str] | None = None,
) -> EligibilityCheck:
    return EligibilityCheck(
        rule_name=rule_name,
        field=field,
        result=result,
        reason=reason,
        jd_evidence=jd_evidence or [],
        missing_information=missing_information or [],
    )


def _graduation_years(job: StructuredJobDescription) -> tuple[list[int] | None, str]:
    if job.graduation_years is not None:
        return job.graduation_years, "graduation_years"
    if job.recruitment_batch:
        years = [int(item) for item in re.findall(r"20\d{2}", job.recruitment_batch)]
        if years:
            return years, "recruitment_batch"
    return None, "graduation_years"


def _check_graduation(
    profile_year: int | None,
    job: StructuredJobDescription,
) -> EligibilityCheck:
    years, evidence_field = _graduation_years(job)
    evidence = _evidence_for(job, evidence_field)
    if years is None:
        return _check(
            rule_name="graduation_year",
            field="graduation_year",
            result="unknown",
            reason="岗位没有明确面向的毕业年份",
            jd_evidence=evidence,
            missing_information=["确认岗位面向的毕业年份"],
        )
    if not years:
        return _check(
            rule_name="graduation_year",
            field="graduation_year",
            result="pass",
            reason="岗位未设置届别限制",
            jd_evidence=evidence,
        )
    if profile_year is None:
        return _check(
            rule_name="graduation_year",
            field="graduation_year",
            result="unknown",
            reason="岗位要求明确，但用户未填写毕业年份",
            jd_evidence=evidence,
            missing_information=["补充毕业年份"],
        )
    if profile_year in years:
        return _check(
            rule_name="graduation_year",
            field="graduation_year",
            result="pass",
            reason=f"岗位接受 {', '.join(map(str, sorted(years)))} 届，用户为 {profile_year} 届",
            jd_evidence=evidence,
        )
    return _check(
        rule_name="graduation_year",
        field="graduation_year",
        result="fail",
        reason=f"岗位接受 {', '.join(map(str, sorted(years)))} 届，用户为 {profile_year} 届",
        jd_evidence=evidence,
    )


def _degree_rank(value: str) -> int | None:
    normalized = normalize_text(value)
    for term, rank in _DEGREE_TERMS:
        if term in normalized:
            return rank
    return None


def _degree_requirement(value: str) -> tuple[str, int | set[int] | None]:
    normalized = normalize_text(value)
    if any(marker in normalized for marker in ("不限", "无要求", "不限制")):
        return "unrestricted", None
    ranks = {
        rank for term, rank in _DEGREE_TERMS if term in normalized
    }
    if not ranks:
        return "unknown", None
    if "以上" in normalized:
        return "minimum", min(ranks)
    return "allowed", ranks


def _check_education(
    profile_degree: str | None,
    job: StructuredJobDescription,
) -> EligibilityCheck:
    requirements = job.education_requirements
    evidence = _evidence_for(job, "education_requirements")
    if requirements is None:
        return _check(
            rule_name="education",
            field="education",
            result="unknown",
            reason="岗位没有明确学历要求",
            jd_evidence=evidence,
            missing_information=["确认岗位学历要求"],
        )
    if not requirements:
        return _check(
            rule_name="education",
            field="education",
            result="pass",
            reason="岗位未设置学历限制",
            jd_evidence=evidence,
        )
    if profile_degree is None:
        return _check(
            rule_name="education",
            field="education",
            result="unknown",
            reason="岗位有学历要求，但用户未填写学历",
            jd_evidence=evidence,
            missing_information=["补充最高学历"],
        )
    profile_rank = _degree_rank(profile_degree)
    if profile_rank is None:
        return _check(
            rule_name="education",
            field="education",
            result="unknown",
            reason="用户学历无法按当前规则规范化",
            jd_evidence=evidence,
            missing_information=["确认学历层级"],
        )

    recognized = False
    has_unknown_requirement = False
    for requirement in requirements:
        kind, value = _degree_requirement(requirement)
        if kind == "unrestricted":
            return _check(
                rule_name="education",
                field="education",
                result="pass",
                reason="岗位明确不限制学历",
                jd_evidence=evidence,
            )
        if kind == "unknown":
            has_unknown_requirement = True
            continue
        recognized = True
        if kind == "minimum" and profile_rank >= value:
            return _check(
                rule_name="education",
                field="education",
                result="pass",
                reason=f"用户学历满足岗位要求：{requirement}",
                jd_evidence=evidence,
            )
        if kind == "allowed" and profile_rank in value:
            return _check(
                rule_name="education",
                field="education",
                result="pass",
                reason=f"用户学历满足岗位要求：{requirement}",
                jd_evidence=evidence,
            )

    if has_unknown_requirement and not recognized:
        return _check(
            rule_name="education",
            field="education",
            result="unknown",
            reason="岗位学历要求包含当前规则无法规范化的表达",
            jd_evidence=evidence,
            missing_information=["确认岗位学历要求"],
        )
    if has_unknown_requirement:
        return _check(
            rule_name="education",
            field="education",
            result="unknown",
            reason="部分岗位学历要求无法规范化，暂不能确定是否符合",
            jd_evidence=evidence,
            missing_information=["确认岗位学历要求"],
        )
    return _check(
        rule_name="education",
        field="education",
        result="fail",
        reason=f"用户学历不满足岗位要求：{'；'.join(requirements)}",
        jd_evidence=evidence,
    )


def _major_key(value: str) -> str:
    return normalize_text(value).replace("专业", "").replace("方向", "")


def _major_families(value: str) -> set[str]:
    normalized = _major_key(value)
    return {
        family
        for family, terms in _MAJOR_FAMILIES.items()
        if any(term in normalized for term in terms)
    }


def _major_relation(user_major: str, requirement: str) -> bool | None:
    user_key = _major_key(user_major)
    requirement_key = _major_key(requirement)
    if any(marker in requirement_key for marker in ("不限", "无要求", "不限制")):
        return True
    if user_key in requirement_key or requirement_key in user_key:
        return True
    user_families = _major_families(user_major)
    requirement_families = _major_families(requirement)
    if user_families and requirement_families:
        return bool(user_families & requirement_families)
    if requirement_families:
        return False
    return None


def _check_major(
    profile_major: str | None,
    job: StructuredJobDescription,
) -> EligibilityCheck:
    requirements = job.major_requirements
    evidence = _evidence_for(job, "major_requirements")
    if requirements is None:
        return _check(
            rule_name="major",
            field="major",
            result="unknown",
            reason="岗位没有明确专业要求",
            jd_evidence=evidence,
            missing_information=["确认岗位专业要求"],
        )
    if not requirements:
        return _check(
            rule_name="major",
            field="major",
            result="pass",
            reason="岗位未设置专业限制",
            jd_evidence=evidence,
        )
    if profile_major is None:
        return _check(
            rule_name="major",
            field="major",
            result="unknown",
            reason="岗位有专业要求，但用户未填写专业",
            jd_evidence=evidence,
            missing_information=["补充所学专业"],
        )

    has_unknown_requirement = False
    for requirement in requirements:
        relation = _major_relation(profile_major, requirement)
        if relation is True:
            return _check(
                rule_name="major",
                field="major",
                result="pass",
                reason=f"用户专业满足岗位要求：{requirement}",
                jd_evidence=evidence,
            )
        if relation is None:
            has_unknown_requirement = True
    if has_unknown_requirement:
        return _check(
            rule_name="major",
            field="major",
            result="unknown",
            reason="岗位专业要求包含当前规则无法规范化的表达",
            jd_evidence=evidence,
            missing_information=["确认专业是否属于岗位要求范围"],
        )
    return _check(
        rule_name="major",
        field="major",
        result="fail",
        reason=f"用户专业不满足岗位要求：{'；'.join(requirements)}",
        jd_evidence=evidence,
    )


def _check_location(
    preferred_locations: list[str] | None,
    job: StructuredJobDescription,
) -> EligibilityCheck:
    job_locations = job.locations
    evidence = _evidence_for(job, "locations")
    if preferred_locations is None:
        return _check(
            rule_name="location",
            field="locations",
            result="unknown",
            reason="用户未填写意向工作地点",
            jd_evidence=evidence,
            missing_information=["补充意向工作地点"],
        )
    if not preferred_locations or job_locations == []:
        return _check(
            rule_name="location",
            field="locations",
            result="pass",
            reason="用户或岗位未设置地点限制",
            jd_evidence=evidence,
        )
    if job_locations is None:
        return _check(
            rule_name="location",
            field="locations",
            result="unknown",
            reason="岗位没有明确工作地点",
            jd_evidence=evidence,
            missing_information=["确认岗位工作地点"],
        )
    preferred = {normalize_location(item) for item in preferred_locations}
    locations = {normalize_location(item) for item in job_locations}
    if "全国" in preferred or "全国" in locations or preferred & locations:
        return _check(
            rule_name="location",
            field="locations",
            result="pass",
            reason="用户意向地点与岗位地点匹配",
            jd_evidence=evidence,
        )
    return _check(
        rule_name="location",
        field="locations",
        result="fail",
        reason=(
            f"用户意向地点为 {'、'.join(preferred_locations)}，"
            f"岗位地点为 {'、'.join(job_locations)}"
        ),
        jd_evidence=evidence,
    )


def _check_job_type(
    preferred_types: list[str] | None,
    job: StructuredJobDescription,
) -> EligibilityCheck:
    if preferred_types is None:
        return _check(
            rule_name="job_type",
            field="job_type",
            result="unknown",
            reason="用户未填写意向岗位类型",
            missing_information=["补充意向岗位类型"],
        )
    if not preferred_types:
        return _check(
            rule_name="job_type",
            field="job_type",
            result="pass",
            reason="用户未设置岗位类型限制",
        )
    if job.job_type is None or job.job_type == "unknown":
        return _check(
            rule_name="job_type",
            field="job_type",
            result="unknown",
            reason="岗位类型无法从 JD 确认",
            missing_information=["确认岗位类型"],
        )
    if job.job_type in preferred_types:
        return _check(
            rule_name="job_type",
            field="job_type",
            result="pass",
            reason=f"岗位类型 {job.job_type} 符合用户意向",
        )
    return _check(
        rule_name="job_type",
        field="job_type",
        result="fail",
        reason=f"岗位类型 {job.job_type} 不在用户意向范围内",
    )


def _check_duration(
    available_months: int | None,
    job: StructuredJobDescription,
) -> EligibilityCheck | None:
    if job.job_type != "internship" and job.internship_duration_months is None:
        return None
    evidence = _evidence_for(job, "internship_duration_months")
    required_months = job.internship_duration_months
    if required_months is None:
        return _check(
            rule_name="internship_duration",
            field="internship_duration_months",
            result="unknown",
            reason="实习岗位没有明确实习时长要求",
            jd_evidence=evidence,
            missing_information=["确认岗位实习时长要求"],
        )
    if required_months == 0:
        return _check(
            rule_name="internship_duration",
            field="internship_duration_months",
            result="pass",
            reason="岗位未设置最低实习时长",
            jd_evidence=evidence,
        )
    if available_months is None:
        return _check(
            rule_name="internship_duration",
            field="internship_duration_months",
            result="unknown",
            reason=f"岗位要求至少实习 {required_months} 个月，但用户未确认可实习时长",
            jd_evidence=evidence,
            missing_information=["补充可实习时长"],
        )
    if available_months >= required_months:
        return _check(
            rule_name="internship_duration",
            field="internship_duration_months",
            result="pass",
            reason=f"用户可实习 {available_months} 个月，满足岗位要求的 {required_months} 个月",
            jd_evidence=evidence,
        )
    return _check(
        rule_name="internship_duration",
        field="internship_duration_months",
        result="fail",
        reason=f"用户可实习 {available_months} 个月，少于岗位要求的 {required_months} 个月",
        jd_evidence=evidence,
    )


def _check_weekly_days(
    available_days: int | None,
    job: StructuredJobDescription,
) -> EligibilityCheck | None:
    if job.weekly_days is None and job.job_type != "internship":
        return None
    evidence = _evidence_for(job, "weekly_days")
    if job.weekly_days is None:
        return _check(
            rule_name="weekly_days",
            field="weekly_days",
            result="unknown",
            reason="实习岗位没有明确每周到岗天数",
            jd_evidence=evidence,
            missing_information=["确认岗位每周到岗天数"],
        )
    if available_days is None:
        return _check(
            rule_name="weekly_days",
            field="weekly_days",
            result="unknown",
            reason=f"岗位要求每周到岗 {job.weekly_days} 天，但用户未确认可到岗天数",
            jd_evidence=evidence,
            missing_information=["补充每周可到岗天数"],
        )
    if available_days >= job.weekly_days:
        return _check(
            rule_name="weekly_days",
            field="weekly_days",
            result="pass",
            reason=f"用户每周可到岗 {available_days} 天，满足岗位要求的 {job.weekly_days} 天",
            jd_evidence=evidence,
        )
    return _check(
        rule_name="weekly_days",
        field="weekly_days",
        result="fail",
        reason=f"用户每周可到岗 {available_days} 天，少于岗位要求的 {job.weekly_days} 天",
        jd_evidence=evidence,
    )


def _check_start_date(
    earliest_start_date: date | None,
    job: StructuredJobDescription,
) -> EligibilityCheck:
    evidence = _evidence_for(job, "earliest_start_date")
    if job.earliest_start_date is None:
        return _check(
            rule_name="earliest_start_date",
            field="earliest_start_date",
            result="unknown",
            reason="岗位没有明确最早到岗时间",
            jd_evidence=evidence,
            missing_information=["确认岗位最早到岗时间"],
        )
    if earliest_start_date is None:
        return _check(
            rule_name="earliest_start_date",
            field="earliest_start_date",
            result="unknown",
            reason="岗位有到岗时间要求，但用户未填写最早可到岗时间",
            jd_evidence=evidence,
            missing_information=["补充最早可到岗时间"],
        )
    if earliest_start_date <= job.earliest_start_date:
        return _check(
            rule_name="earliest_start_date",
            field="earliest_start_date",
            result="pass",
            reason=(
                f"用户最早可在 {earliest_start_date.isoformat()} 到岗，"
                f"满足岗位要求的 {job.earliest_start_date.isoformat()}"
            ),
            jd_evidence=evidence,
        )
    return _check(
        rule_name="earliest_start_date",
        field="earliest_start_date",
        result="fail",
        reason=(
            f"用户最早可在 {earliest_start_date.isoformat()} 到岗，"
            f"晚于岗位要求的 {job.earliest_start_date.isoformat()}"
        ),
        jd_evidence=evidence,
    )


def check_eligibility(input_data: EligibilityInput) -> EligibilityResult:
    """Return a deterministic qualification result for one user and one JD."""

    profile = input_data.profile
    preferences = input_data.preferences
    job = input_data.job
    checks: list[EligibilityCheck] = [
        _check_graduation(profile.graduation_year, job),
        _check_education(profile.degree, job),
        _check_major(profile.major, job),
        _check_location(preferences.preferred_locations, job),
        _check_job_type(preferences.job_types, job),
    ]
    for optional_check in (
        _check_duration(preferences.internship_duration_months, job),
        _check_weekly_days(preferences.weekly_days, job),
    ):
        if optional_check is not None:
            checks.append(optional_check)
    checks.append(_check_start_date(preferences.earliest_start_date, job))

    if any(check.result == "fail" for check in checks):
        eligible = "fail"
    elif any(check.result == "unknown" for check in checks):
        eligible = "unknown"
    else:
        eligible = "pass"
    return EligibilityResult(eligible=eligible, checks=checks)
