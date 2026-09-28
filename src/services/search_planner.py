"""Concrete, bounded queries; search preferences never become eligibility gates."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from src.services.discovery_matching import _LOCATION_GROUPS, _ROLE_GROUPS, _contains


@dataclass(frozen=True)
class SearchTask:
    query: str
    strategy: str


def build_search_tasks(query, sources=()):
    lowered = query.casefold()
    cities = [
        aliases[0]
        for aliases in _LOCATION_GROUPS
        if any(_contains(lowered, a) for a in aliases)
    ]
    roles = [
        terms[0]
        for aliases, terms in _ROLE_GROUPS
        if any(_contains(lowered, a) for a in aliases)
    ]
    synonyms = [
        terms[min(1, len(terms) - 1)]
        for aliases, terms in _ROLE_GROUPS
        if any(_contains(lowered, a) for a in aliases)
    ]
    # Remove only recognised alternatives. Keep years, recruitment type and all
    # other user constraints, including directions not in the vocabulary.
    remainder = query
    for aliases in _LOCATION_GROUPS:
        for alias in sorted(aliases, key=len, reverse=True):
            if alias.isascii():
                remainder = re.sub(
                    r"(?<!\w)" + re.escape(alias) + r"(?!\w)",
                    " ",
                    remainder,
                    flags=re.IGNORECASE,
                )
            else:
                remainder = remainder.replace(alias, " ")
    for aliases, _ in _ROLE_GROUPS:
        for alias in sorted(aliases, key=len, reverse=True):
            if _contains(lowered, alias):
                remainder = re.sub(
                    re.escape(alias), " ", remainder, flags=re.IGNORECASE
                )
    remainder = re.sub(r"[/、,，|]+", " ", remainder).strip()
    focused = [
        SearchTask(f"{role} {city} {remainder} 招聘 职位", "方向与城市")
        for city in (cities or [""])
        for role in (roles or [""])
    ]
    companies = [
        SearchTask(
            f"{query} {s.company} site:{urlsplit(s.career_url).hostname}", "公司官网"
        )
        for s in sources
    ]
    alternatives = [
        SearchTask(f"{word} {' '.join(cities)} {remainder} 招聘", "同义岗位")
        for word in synonyms
    ]
    tasks = [SearchTask(query, "原始条件")]
    for i in range(max(len(focused), len(companies), len(alternatives), 1)):
        for group in (focused, companies, alternatives):
            if i < len(group):
                tasks.append(group[i])
    seen = set()
    return [task for task in tasks if not (task.query in seen or seen.add(task.query))]


def next_search_task(tasks, completed, duplicate_streak=0):
    available = [task for task in tasks if task.query not in completed]
    if duplicate_streak:
        # A repeated result set changes the actual query, not just the prompt.
        alternative = next(
            (t for t in available if t.strategy in {"公司官网", "同义岗位"}), None
        )
        if alternative:
            return alternative
    return available[0] if available else None
