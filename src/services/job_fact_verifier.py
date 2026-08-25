from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from src.services.url_reader import ParsedHTMLDocument

_JOB_TYPE_PATTERNS: dict[str, tuple[str, ...]] = {
    "campus": ("校园招聘", "校招", "应届生招聘", "应届招聘", "应届生"),
    "internship": ("实习生", "实习", "internship", "intern"),
    "full_time": ("全职", "正式员工", "full-time", "full time"),
    "part_time": ("兼职", "part-time", "part time"),
}
_REQUIREMENT_MARKERS = (
    "任职要求",
    "岗位要求",
    "职位要求",
    "资格要求",
    "基本要求",
    "优先条件",
    "requirements",
    "qualifications",
    "what you bring",
)


@dataclass(frozen=True)
class VerifiedPageFacts:
    company: str | None
    title: str | None
    locations: list[str]
    job_type: str | None
    graduation_years: list[int]
    requirements: list[str]
    evidence: dict[str, Any]


def verify_page_facts(document: ParsedHTMLDocument) -> VerifiedPageFacts:
    """Extract facts only from fetched page content and structured page metadata."""

    text = document.text
    company = document.company or _labeled_value(
        text,
        ("招聘公司", "公司名称", "company"),
    )
    title = document.title
    locations = _unique([*document.locations, *_body_locations(text)])
    job_type = _canonical_job_type(document.job_type) or _body_job_type(text)
    graduation_years = _graduation_years(text)
    requirements = _requirement_fragments(text)

    evidence: dict[str, Any] = {
        "company": _scalar_evidence(
            company,
            text,
            fallback_kind="json_ld" if document.company else "body",
        ),
        "title": _scalar_evidence(title, text, fallback_kind="heading"),
        "locations": [
            _scalar_evidence(location, text, fallback_kind="json_ld")
            for location in locations
        ],
        "job_type": _job_type_evidence(job_type, text, document.job_type),
        "graduation_years": [
            _scalar_evidence(str(year), text, fallback_kind="body")
            for year in graduation_years
        ],
        "requirements": [
            _scalar_evidence(item, text, fallback_kind="body")
            for item in requirements
        ],
    }
    return VerifiedPageFacts(
        company=company,
        title=title,
        locations=locations,
        job_type=job_type,
        graduation_years=graduation_years,
        requirements=requirements,
        evidence=evidence,
    )


def verified_stub_evidence(
    *,
    raw_content: str,
    company: str | None,
    title: str | None,
    locations: list[str],
    job_type: str | None,
    metadata_kind: str,
) -> dict[str, Any]:
    """Build evidence for official-adapter or user-provided snapshots."""

    canonical_type = _canonical_job_type(job_type) or _body_job_type(raw_content)
    return {
        "company": _scalar_evidence(company, raw_content, fallback_kind=metadata_kind),
        "title": _scalar_evidence(title, raw_content, fallback_kind=metadata_kind),
        "locations": [
            _scalar_evidence(location, raw_content, fallback_kind=metadata_kind)
            for location in locations
        ],
        "job_type": _job_type_evidence(
            canonical_type,
            raw_content,
            job_type,
            fallback_kind=metadata_kind,
        ),
        "graduation_years": [
            _scalar_evidence(str(year), raw_content, fallback_kind="body")
            for year in _graduation_years(raw_content)
        ],
        "requirements": [
            _scalar_evidence(item, raw_content, fallback_kind="body")
            for item in _requirement_fragments(raw_content)
        ],
    }


def _scalar_evidence(
    value: str | None,
    text: str,
    *,
    fallback_kind: str,
) -> dict[str, Any] | None:
    if not value:
        return None
    start = text.casefold().find(value.casefold())
    return {
        "value": value,
        "source_kind": "body" if start >= 0 else fallback_kind,
        "source_text": value,
        "start_char": start if start >= 0 else None,
        "end_char": start + len(value) if start >= 0 else None,
    }


def _job_type_evidence(
    job_type: str | None,
    text: str,
    declared: str | None,
    *,
    fallback_kind: str = "json_ld",
) -> dict[str, Any] | None:
    if not job_type:
        return None
    for marker in _JOB_TYPE_PATTERNS[job_type]:
        start = text.casefold().find(marker.casefold())
        if start >= 0:
            return {
                "value": job_type,
                "source_kind": "body",
                "source_text": text[start : start + len(marker)],
                "start_char": start,
                "end_char": start + len(marker),
            }
    return {
        "value": job_type,
        "source_kind": fallback_kind,
        "source_text": declared or job_type,
        "start_char": None,
        "end_char": None,
    }


def _canonical_job_type(value: str | None) -> str | None:
    if not value:
        return None
    normalized = re.sub(r"[\s_-]+", "", value).casefold()
    aliases = {
        "campus": "campus",
        "校园招聘": "campus",
        "校招": "campus",
        "intern": "internship",
        "internship": "internship",
        "实习": "internship",
        "实习生": "internship",
        "fulltime": "full_time",
        "全职": "full_time",
        "正式员工": "full_time",
        "parttime": "part_time",
        "兼职": "part_time",
    }
    return aliases.get(normalized)


def _body_job_type(text: str) -> str | None:
    folded = text.casefold()
    for job_type, markers in _JOB_TYPE_PATTERNS.items():
        if any(marker.casefold() in folded for marker in markers):
            return job_type
    return None


def _labeled_value(text: str, labels: tuple[str, ...]) -> str | None:
    for label in labels:
        match = re.search(
            rf"{re.escape(label)}\s*[:：]\s*([^\n。；;]{{2,80}})",
            text,
            flags=re.IGNORECASE,
        )
        if match:
            return match.group(1).strip()
    return None


def _body_locations(text: str) -> list[str]:
    matches = re.finditer(
        r"(?:工作地点|办公地点|地点|location)\s*[:：]\s*([^\n。；;]{1,120})",
        text,
        flags=re.IGNORECASE,
    )
    values: list[str] = []
    for match in matches:
        values.extend(
            item.strip()
            for item in re.split(r"[,，、/|]", match.group(1))
            if item.strip()
        )
    return values[:20]


def _graduation_years(text: str) -> list[int]:
    years: list[int] = []
    patterns = (
        r"(?<!\d)(20\d{2})\s*届",
        r"(?<!\d)(20\d{2})\s*年(?:应届|毕业)",
        r"(?:毕业时间|毕业年份)[^\d]{0,8}(20\d{2})",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            year = int(match.group(1))
            if 2000 <= year <= 2200 and year not in years:
                years.append(year)
    return sorted(years)


def _requirement_fragments(text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return []
    fragments = re.split(r"(?<=[。；;!?！？])\s*|\s*[•·]\s*", normalized)
    result: list[str] = []
    in_requirement_section = False
    for fragment in fragments:
        cleaned = fragment.strip()
        if not cleaned:
            continue
        folded = cleaned.casefold()
        has_marker = any(marker in folded for marker in _REQUIREMENT_MARKERS)
        if has_marker:
            in_requirement_section = True
        if has_marker or (
            in_requirement_section
            and any(
                marker in folded
                for marker in ("熟悉", "具备", "要求", "经验", "学历", "专业", "ability", "experience")
            )
        ):
            result.append(cleaned[:500])
        if len(result) >= 8:
            break
    return _unique(result)


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = re.sub(r"\s+", " ", value).strip()
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result
