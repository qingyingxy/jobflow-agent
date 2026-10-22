"""Source-backed education records and bounded, executable JD predicates."""

from __future__ import annotations

import re
import unicodedata
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.domain.education_dates import (
    supported_graduation_year,
    validate_education_year,
)
from src.domain.fact_provenance import FactProvenance
from src.domain.graduation import quoted_cohort_years

DegreeLevel = Literal[
    "secondary", "associate", "bachelor", "master", "doctor", "unknown"
]
EducationStatus = Literal["enrolled", "graduated", "unknown"]
DEGREE_RANK = {"secondary": 1, "associate": 2, "bachelor": 3, "master": 4, "doctor": 5}
DEGREE_LABELS = {
    "secondary": "高中/中专",
    "associate": "专科",
    "bachelor": "本科",
    "master": "硕士",
    "doctor": "博士",
    "unknown": "未知",
}
DEGREE_ALIASES = {
    "secondary": ("高中", "中专"),
    "associate": ("专科", "大专", "associate"),
    "bachelor": ("本科", "学士", "bachelor"),
    "master": ("硕士", "master"),
    "doctor": ("博士", "phd", "ph.d", "doctor"),
}


def comparable(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value).casefold())


def _english_status_evidence(source: str, status: str) -> bool:
    """Accept explicit current study/completion, with a nearby degree object."""
    text = unicodedata.normalize("NFKC", source).casefold()
    if _english_status_denied(text, status):
        return False
    degree = r"\b(?:degree|bachelor|master|ph\.?d|doctorate)\b"
    object_ahead = rf"(?=[^.;!?\n]{{0,100}}{degree})"
    predicate = (
        r"\b(?:currently\s+pursuing|(?:are|is|am)\s+(?:currently\s+)?(?:pursuing|completing))\b"
        if status == "enrolled"
        else r"\b(?:(?:have|has)\s+(?:already\s+|recently\s+)?completed|(?:already|recently)\s+completed)\b"
    )
    return bool(re.search(predicate + object_ahead, text))


def _english_status_denied(source: str, status: str) -> bool:
    text = unicodedata.normalize("NFKC", source).casefold()
    predicate = (
        r"(?:enrolled|pursu(?:e|ing)|completing)"
        if status == "enrolled"
        else r"(?:graduated|complet(?:e|ed)|degree\s+awarded)"
    )
    return bool(
        re.search(
            rf"\b(?:not|never|no\s+longer|will|would|shall|plan\s+to|intend\s+to|expected\s+to)\b[^.;!?\n]{{0,50}}\b{predicate}\b",
            text,
        )
    )


def degree_levels(text: str) -> set[str]:
    # Keep word boundaries for English aliases: RoboMaster is a competition,
    # not a master's degree. Whitespace removal would also merge English words.
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return {
        level
        for level, terms in DEGREE_ALIASES.items()
        if any(
            re.search(rf"(?<![a-z0-9_]){re.escape(term)}(?![a-z0-9_])", normalized)
            if term.isascii()
            else term in normalized
            for term in terms
        )
    }


class EducationFacts(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    level: DegreeLevel = "unknown"
    major_raw: str | None = Field(default=None, min_length=1, max_length=100)
    school: str | None = Field(default=None, min_length=1, max_length=160)
    enrollment_year: int | None = Field(default=None, ge=1900, le=2200)
    enrollment_source_text: str | None = Field(
        default=None, min_length=1, max_length=500
    )
    graduation_year: int | None = Field(default=None, ge=1900, le=2200)
    graduation_source_text: str | None = Field(
        default=None, min_length=1, max_length=500
    )
    status: EducationStatus = "unknown"
    graduation_year_kind: Literal["actual", "expected", "unknown"] = "unknown"

    @model_validator(mode="after")
    def ordered_years(self):
        if (
            self.enrollment_year is not None
            and self.graduation_year is not None
            and self.enrollment_year > self.graduation_year
        ):
            raise ValueError("毕业年份不能早于入学年份")
        if self.graduation_year is None and self.graduation_year_kind != "unknown":
            raise ValueError("缺少毕业年份时不能声明实际或预计毕业年份")
        return self


class EducationRecord(EducationFacts):
    provenance: FactProvenance = Field(default_factory=FactProvenance)
    reviewed: bool = False
    graduation_year_confirmed: bool = False
    id: str = Field(
        default_factory=lambda: f"edu_{uuid4().hex[:20]}", min_length=1, max_length=40
    )
    source_text: str = Field(min_length=1, max_length=2000)
    source: str = Field(default="manual", min_length=1, max_length=160)


def education_summary(
    records: list[EducationRecord],
) -> tuple[str | None, str | None, int | None]:
    """Compatibility display fields, not selection of the application degree."""
    highest = max((DEGREE_RANK.get(item.level, 0) for item in records), default=0)
    top = [item for item in records if DEGREE_RANK.get(item.level, 0) == highest]
    if not highest or len(top) != 1:
        return None, None, None
    record = top[0]
    return (
        DEGREE_LABELS[record.level],
        record.major_raw,
        supported_graduation_year(record),
    )


def validate_education_grounding(education: EducationFacts, source: str) -> None:
    """Check values against this record, never against another education span."""
    normalized = comparable(source)
    if education.level != "unknown" and degree_levels(source) != {education.level}:
        raise ValueError("每段教育经历只能包含一个明确学历，且必须与原文一致")
    for value in (
        education.major_raw,
        education.school,
        education.enrollment_source_text,
        education.graduation_source_text,
    ):
        if value and comparable(value) not in normalized:
            raise ValueError("教育字段必须来自同一段教育原文")
    validate_education_year(
        year=education.enrollment_year,
        quote=education.enrollment_source_text,
        source=source,
        role="enrollment",
    )
    validate_education_year(
        year=education.graduation_year,
        quote=education.graduation_source_text,
        source=source,
        role="graduation",
    )
    date_quote = comparable(education.graduation_source_text or "")
    expected = any(term in date_quote for term in ("预计", "预期", "拟", "expected"))
    if education.graduation_year_kind == "expected" and not expected:
        raise ValueError("预计毕业年份需要明确的预计毕业依据")
    if education.graduation_year_kind == "actual" and (
        expected
        or not any(term in date_quote for term in ("已毕业", "毕业于", "graduated"))
    ):
        raise ValueError("实际毕业年份需要明确已毕业依据，不能根据日期已过去推断")
    if education.status == "graduated" and (
        (
            not any(
                term in normalized
                for term in ("已毕业", "已获", "取得学位", "graduated", "degreeawarded")
            )
            and not _english_status_evidence(source, "graduated")
        )
        or any(term in normalized for term in ("在读", "预计", "expected"))
        or _english_status_denied(source, "graduated")
    ):
        raise ValueError("不能从学历名称或年份推断已毕业")
    if education.status == "enrolled" and (
        (
            not any(
                term in normalized
                for term in (
                    "在读",
                    "在校",
                    "就读",
                    "至今",
                    "预计",
                    "expected",
                    "present",
                    "enrolled",
                )
            )
            and not _english_status_evidence(source, "enrolled")
        )
        or _english_status_denied(source, "enrolled")
    ):
        raise ValueError("在读状态必须有明确原文依据")


class DegreePredicate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operator: Literal["eq", "gte", "any", "not_specified", "unknown"]
    level: DegreeLevel = "unknown"
    source_text: str | None = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def consistent(self):
        if self.operator != "not_specified" and not self.source_text:
            raise ValueError("学历条件必须绑定原文")
        if (self.operator in {"eq", "gte"}) != (self.level != "unknown"):
            raise ValueError("学历比较必须给出明确层级；any/unknown 不得给出层级")
        return self


class MajorPredicate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["any", "exact", "related", "not_specified", "unknown"]
    values: list[str] = Field(default_factory=list, max_length=20)
    source_text: str | None = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def consistent(self):
        if (self.mode in {"exact", "related"}) != bool(self.values):
            raise ValueError("exact/related 必须给出专业名称，其他模式不得提供名称")
        if self.mode != "not_specified" and not self.source_text:
            raise ValueError("专业条件必须绑定原文")
        if any(not value.strip() for value in self.values):
            raise ValueError("专业名称不能为空")
        return self


class EducationBranch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_text: str = Field(min_length=1, max_length=500)
    degree: DegreePredicate
    major: MajorPredicate
    scope: Literal["application", "historical", "unknown"] = "unknown"
    scope_source_text: str | None = Field(default=None, min_length=1, max_length=2000)
    graduation_years: list[int] | None = Field(
        default=None, min_length=1, max_length=20
    )
    graduation_source_text: str | None = Field(
        default=None, min_length=1, max_length=500
    )
    status: Literal["any", "enrolled", "graduated", "unknown"] = "any"
    # Explicitly retain unsupported qualifications (school tier, equivalence, etc.).
    unresolved: bool = False

    @model_validator(mode="after")
    def scope_has_evidence(self):
        if self.scope != "unknown" and not self.scope_source_text:
            raise ValueError("申请学历或历史背景的适用范围必须有 JD 上下文依据")
        return self


class EducationCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    relation: Literal["all_of", "any_of", "uncertain"]
    branches: list[EducationBranch] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def validate_branches(self):
        if self.relation == "any_of" and len(self.branches) < 2:
            raise ValueError("any_of 至少需要两个学历资格分支")
        if self.relation == "any_of":
            # Different predicates may cite the same sentence; repeated
            # predicates are not distinct alternatives, however.
            identities = [
                (
                    b.degree.operator,
                    b.degree.level,
                    b.major.mode,
                    tuple(sorted(comparable(v) for v in b.major.values)),
                    b.scope,
                    tuple(sorted(b.graduation_years or [])),
                    b.status,
                    b.unresolved,
                )
                for b in self.branches
            ]
            if len(set(identities)) != len(identities):
                raise ValueError(
                    "any_of 的教育分支必须有不同的资格谓词，不能重复同一条件"
                )
        return self


def validate_condition_grounding(
    condition: EducationCondition, source: str, *, document_content: str | None = None
) -> None:
    for branch in condition.branches:
        if (
            document_content is not None
            and branch.scope_source_text
            and branch.scope_source_text not in document_content
        ):
            raise ValueError("教育条件适用范围的上下文不在 JD 原文中")
        if branch.source_text not in source:
            raise ValueError("学历资格分支缺少逐字原文")
        for quote in (
            branch.degree.source_text,
            branch.major.source_text,
            branch.graduation_source_text,
        ):
            if quote and quote not in branch.source_text:
                raise ValueError("资格字段的原文必须属于同一分支")
        degree = branch.degree
        if degree.operator == "not_specified" and degree_levels(branch.source_text):
            raise ValueError("分支有明确学历，不得标为未指定")
        if degree.operator in {"eq", "gte"} and degree.level not in degree_levels(
            degree.source_text
        ):
            raise ValueError("学历层级没有原文依据")
        if degree.operator == "gte" and not any(
            t in comparable(degree.source_text)
            for t in ("以上", "至少", "atleast", "orhigher", "orabove")
        ):
            raise ValueError("学历最低层级需要明确的以上/至少依据")
        if degree.operator == "any" and not any(
            t in comparable(degree.source_text)
            for t in ("学历不限", "不限学历", "无学历要求")
        ):
            raise ValueError("专业不限不等于学历不限")
        major = branch.major
        if major.mode == "any" and not any(
            t in comparable(major.source_text or "")
            for t in ("专业不限", "不限专业", "不限制专业", "anymajor")
        ):
            raise ValueError("不限专业必须由原文明示")
        if any(
            comparable(v) not in comparable(major.source_text or "")
            for v in major.values
        ):
            raise ValueError("专业名称必须有同分支原文支持")
        major_quote = comparable(major.source_text or "")
        listed_open_majors = len(major.values) >= 2 and "等专业" in major_quote
        if major.mode == "related" and not (
            listed_open_majors or any(t in major_quote for t in ("相关", "related"))
        ):
            raise ValueError(
                "相关专业需要原文依据；等理工科等无法表达的开放范围请用 unknown/unresolved"
            )
        if major.mode == "exact" and any(
            t in comparable(major.source_text or "") for t in ("等", "相关", "related")
        ):
            raise ValueError(
                "开放专业范围不能收窄为 exact；请用 related 或 unknown/unresolved"
            )
        if major.mode == "not_specified" and any(
            t in branch.source_text for t in ("专业", "学科")
        ):
            raise ValueError("分支提到专业但没有解释其约束，请解析或标为 unknown")
        if branch.graduation_years and (
            not branch.graduation_source_text
            or any(
                year < 1900
                or year > 2200
                or year not in quoted_cohort_years(branch.graduation_source_text)
                for year in branch.graduation_years
            )
        ):
            raise ValueError("分支毕业年份需要同分支原文依据；复杂区间请标 unresolved")
        if branch.graduation_years and re.search(
            r"以后|之后|之前|以前|及以后|及之后|至|到|[-~～]|[月日]",
            branch.graduation_source_text or "",
        ):
            raise ValueError(
                "毕业年份区间不能变成单年列表；请保留原文并使用 null + unresolved"
            )
        if branch.status != "any" and branch.status != "unknown":
            text = comparable(branch.source_text)
            if branch.status == "graduated":
                supported = bool(
                    re.search(
                        r"已(?:经)?(?:毕业|获|取得)|毕业于|graduated|degreeawarded",
                        text,
                    )
                )
                supported = supported and not any(
                    t in text
                    for t in (
                        "未毕业",
                        "尚未",
                        "预计",
                        "预期",
                        "expected",
                        "notgraduated",
                    )
                )
            else:
                supported = any(t in text for t in ("在读", "在校", "就读", "enrolled"))
                supported = supported and not any(
                    t in text for t in ("非在读", "不在读", "非在校", "notenrolled")
                )
            supported = (
                supported or _english_status_evidence(branch.source_text, branch.status)
            ) and not _english_status_denied(branch.source_text, branch.status)
            if not supported:
                raise ValueError(
                    "当前毕业或在读状态需要明确原文；2027届获得学历不是当前已毕业，未明确时 status=any"
                )
