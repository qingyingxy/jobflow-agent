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


def degree_levels(text: str) -> set[str]:
    text = comparable(text)
    return {
        level
        for level, terms in DEGREE_ALIASES.items()
        if any(term in text for term in terms)
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
        not any(
            term in normalized
            for term in ("已毕业", "已获", "取得学位", "graduated", "degreeawarded")
        )
        or any(term in normalized for term in ("在读", "预计", "expected"))
    ):
        raise ValueError("不能从学历名称或年份推断已毕业")
    if education.status == "enrolled" and not any(
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
        if major.mode == "related" and not any(
            t in comparable(major.source_text or "") for t in ("相关", "related")
        ):
            raise ValueError("相关专业需要原文依据")
        if major.mode == "not_specified" and any(
            t in branch.source_text for t in ("专业", "学科")
        ):
            raise ValueError("分支提到专业但没有解释其约束，请解析或标为 unknown")
        if branch.graduation_years and (
            not branch.graduation_source_text
            or any(
                year < 1900
                or year > 2200
                or str(year) not in branch.graduation_source_text
                for year in branch.graduation_years
            )
        ):
            raise ValueError("分支毕业年份需要同分支原文依据；复杂区间请标 unresolved")
        if branch.status != "any" and branch.status != "unknown":
            markers = (
                ("毕业", "学位", "graduated")
                if branch.status == "graduated"
                else ("在读", "在校", "enrolled")
            )
            if not any(t in comparable(branch.source_text) for t in markers):
                raise ValueError("毕业或在读限制需要原文依据")
