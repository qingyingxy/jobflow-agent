from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from src.services.discovery_sources import JobStub

MatchTier = Literal["strict", "expanded"]


@dataclass(frozen=True)
class DiscoveryJobMatch:
    match_tier: MatchTier
    mismatch_reasons: tuple[str, ...]
    mismatch_labels: tuple[str, ...]

    def as_dict(self, *, job_posting_id: str) -> dict[str, object]:
        return {
            "job_posting_id": job_posting_id,
            "match_tier": self.match_tier,
            "mismatch_reasons": list(self.mismatch_reasons),
            "mismatch_labels": list(self.mismatch_labels),
        }


_LOCATION_GROUPS: tuple[tuple[str, ...], ...] = (
    ("北京", "beijing"),
    ("上海", "shanghai"),
    ("深圳", "shenzhen"),
    ("广州", "guangzhou"),
    ("杭州", "hangzhou"),
    ("成都", "chengdu"),
    ("南京", "nanjing"),
    ("武汉", "wuhan"),
    ("苏州", "suzhou"),
    ("西安", "xi'an", "xian"),
    ("天津", "tianjin"),
    ("重庆", "chongqing"),
    ("厦门", "xiamen"),
    ("新加坡", "singapore"),
    ("香港", "hong kong"),
    ("圣何塞", "san jose"),
    ("西雅图", "seattle"),
)

_ROLE_GROUPS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("agent", "智能体"), ("agent", "智能体")),
    (
        ("llm", "大模型", "大语言模型", "large language model"),
        (
            "llm",
            "大模型",
            "大语言模型",
            "large language model",
            "foundation model",
            "generative ai",
        ),
    ),
    (
        ("算法", "algorithm"),
        (
            "算法",
            "algorithm",
            "machine learning",
            "机器学习",
            "deep learning",
            "深度学习",
            "推荐",
            "搜索",
            "计算机视觉",
        ),
    ),
    (("rag", "检索增强"), ("rag", "检索增强")),
    (("nlp", "自然语言处理"), ("nlp", "自然语言处理")),
    (("计算机视觉", "computer vision", "cv"), ("计算机视觉", "computer vision", "cv")),
    (("数据", "data"), ("数据", "data")),
    (("后端", "backend", "back-end"), ("后端", "backend", "back-end")),
    (("前端", "frontend", "front-end"), ("前端", "frontend", "front-end")),
    (("测试", "qa"), ("测试", "quality assurance", "qa")),
    (("产品", "product"), ("产品", "product")),
)


def classify_discovery_job(job: JobStub, *, query: str | None) -> DiscoveryJobMatch:
    """Apply deterministic query gates before any model-based job analysis."""

    normalized_query = (query or "").casefold()
    mismatch_reasons: list[str] = []
    mismatch_labels: list[str] = []

    requested_locations = [
        aliases
        for aliases in _LOCATION_GROUPS
        if any(_contains(normalized_query, alias) for alias in aliases)
    ]
    if requested_locations:
        location_text = " ".join(job.locations).casefold()
        if not location_text:
            mismatch_reasons.append("location")
            mismatch_labels.append("地点待确认")
        elif not any(
            _contains(location_text, alias)
            for aliases in requested_locations
            for alias in aliases
        ):
            mismatch_reasons.append("location")
            mismatch_labels.append("地点不匹配")

    expected_types, mismatch_type_label = _expected_job_types(normalized_query)
    if expected_types and job.job_type not in expected_types:
        mismatch_reasons.append("job_type")
        mismatch_labels.append(
            "招聘类型待确认" if job.job_type in {None, "unknown"} else mismatch_type_label
        )

    requested_roles = [
        job_terms
        for query_terms, job_terms in _ROLE_GROUPS
        if any(_contains(normalized_query, term) for term in query_terms)
    ]
    if not requested_roles and _contains_any(
        normalized_query,
        ("ai", "人工智能", "artificial intelligence"),
    ):
        requested_roles = [("ai", "人工智能", "artificial intelligence")]
    role_text = " ".join(part for part in (job.title, job.raw_content) if part).casefold()
    if requested_roles and not any(
        _contains(role_text, term)
        for role_terms in requested_roles
        for term in role_terms
    ):
        mismatch_reasons.append("role")
        mismatch_labels.append("方向不匹配")

    return DiscoveryJobMatch(
        match_tier="expanded" if mismatch_reasons else "strict",
        mismatch_reasons=tuple(mismatch_reasons),
        mismatch_labels=tuple(mismatch_labels),
    )


def _expected_job_types(query: str) -> tuple[set[str], str]:
    campus = _contains_any(query, ("校招", "校园招聘", "应届", "应届生"))
    internship = _contains_any(query, ("实习", "internship", "intern"))
    if campus and internship:
        return {"campus", "internship"}, "非校招或实习"
    if campus:
        return {"campus"}, "非校招"
    if internship:
        return {"internship"}, "非实习"
    if _contains_any(query, ("社招", "社会招聘", "正式岗", "全职", "full-time")):
        return {"full_time"}, "非正式岗"
    return set(), "招聘类型不匹配"


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(_contains(text, term) for term in terms)


def _contains(text: str, term: str) -> bool:
    normalized_term = term.casefold()
    if re.fullmatch(r"[a-z0-9][a-z0-9 .+'-]*", normalized_term):
        return bool(
            re.search(
                rf"(?<![a-z0-9]){re.escape(normalized_term)}(?![a-z0-9])",
                text,
            )
        )
    return normalized_term in text
