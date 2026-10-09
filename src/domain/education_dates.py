"""Bounded positive evidence for education date roles, never bare year presence."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from src.domain.education import EducationRecord

YEAR = r"(?:19\d{2}|20\d{2}|21\d{2}|2200)"
MONTH = r"(?:0?[1-9]|1[0-2])(?!\d)"
DAY = r"(?:0?[1-9]|[12]\d|3[01])(?!\d)"
DATE_TAIL = (
    rf"(?:\s*[年./-]\s*{MONTH}"
    rf"(?:\s*月(?:\s*{DAY}\s*日)?|\s*[./-]\s*{DAY}\s*日?)?)?\s*年?"
)
RANGE = re.compile(
    rf"(?<!\d)(?P<start>{YEAR}){DATE_TAIL}\s*(?:[-—–~～至到]|to)\s*"
    rf"(?:(?P<end>{YEAR}){DATE_TAIL}|(?P<open>今|至今|现在|present|current))(?!\d)",
    re.IGNORECASE,
)
ROLE = {
    "enrollment": r"(?:入学|入校|录取|enroll(?:ed|ment)?|admitted|admission)",
    "graduation": r"(?:(?:预计|预期|拟|已|expected)\s*)?(?:毕业|graduation|graduated)",
}


@dataclass
class EducationDateSupport:
    enrollment: set[int] = field(default_factory=set)
    graduation: set[int] = field(default_factory=set)


def education_date_support(text: str) -> EducationDateSupport:
    text = unicodedata.normalize("NFKC", text).casefold()
    support = EducationDateSupport()
    masked = list(text)
    for match in RANGE.finditer(text):
        start = int(match["start"])
        end = int(match["end"]) if match["end"] else None
        if end is not None and end < start:
            raise ValueError("教育时间区间终点早于入学时间")
        support.enrollment.add(start)
        # An open interval has no graduation endpoint. Leaving/visiting a school
        # is not graduation either, even if a study interval has a numeric end.
        if end is not None and not any(
            term in text
            for term in (
                "肄业",
                "退学",
                "休学",
                "交换",
                "访学",
                "未毕业",
                "withdraw",
                "exchange",
                "not graduated",
            )
        ):
            support.graduation.add(end)
        masked[match.start() : match.end()] = " " * (match.end() - match.start())
    remainder = "".join(masked)
    for role, label in ROLE.items():
        prefix = re.compile(
            rf"{label}\s*(?:(?:时间|年份|日期|date|year|in|于)\s*)?[:：]?\s*(?P<year>{YEAR}){DATE_TAIL}(?!\d)"
        )
        suffix = re.compile(
            rf"(?<!\d)(?P<year>{YEAR}){DATE_TAIL}\s*{label}(?!\s*(?:(?:时间|年份|日期|date|year|in|于)\s*)?[:：]?\s*{YEAR})"
        )
        years = getattr(support, role)
        years.update(
            int(match["year"])
            for pattern in (prefix, suffix)
            for match in pattern.finditer(remainder)
            if not re.search(
                r"(?:未|未能|没有|not|never)\s*$", remainder[: match.start()]
            )
        )
    return support


def validate_education_year(
    *,
    year: int | None,
    quote: str | None,
    source: str,
    role: Literal["enrollment", "graduation"],
) -> None:
    if year is None:
        return
    label = "入学" if role == "enrollment" else "毕业"
    if not quote or re.sub(r"\s+", "", quote) not in re.sub(r"\s+", "", source):
        raise ValueError(f"{label}年份缺少同段原文引用")
    # A quote must retain the role or the full interval. A clipped '2020' cannot
    # certify whether that year is enrollment, graduation, or something else.
    quoted = getattr(education_date_support(quote), role)
    contextual = getattr(education_date_support(source), role)
    if quoted != {year} or contextual != {year}:
        raise ValueError(
            f"{label}年份与原文中的时间角色不一致或无法确定；请保留完整日期依据或留空"
        )


def supported_graduation_year(record: EducationRecord) -> int | None:
    """Recheck old automatic records too; old snapshots may contain a start year."""
    if (
        not record.source.startswith("resume_asset:")
        or record.graduation_year_confirmed
    ):
        return record.graduation_year
    try:
        validate_education_year(
            year=record.graduation_year,
            quote=record.graduation_source_text,
            source=record.source_text,
            role="graduation",
        )
    except ValueError:
        return None
    return record.graduation_year
