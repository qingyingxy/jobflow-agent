"""Concrete, bounded queries; search preferences never become eligibility gates."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import urlsplit

from src.services.discovery_matching import _LOCATION_GROUPS, _ROLE_GROUPS, _contains
from src.services.search_constraints import has_exclusions, select_term_groups


@dataclass(frozen=True)
class SearchTask:
    query: str
    strategy: str


def query_identity(query: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", query).casefold().split())


def build_agent_search_tasks(query, sources=()):
    """Keep the entire request, adding only code-owned keywords/company scopes.

    Free-text constraints cannot be reliably reconstructed by keyword rules.
    Conservatively preserve them verbatim, even when a role word also appears
    inside an unknown company name. Models can select IDs, never rewrite scope.
    """
    tasks = [SearchTask(query, "原始条件"), SearchTask(f"{query} 官方招聘 具体职位", "条件补搜")]
    tasks.extend(
        SearchTask(
            f"{query} {source.company} site:{urlsplit(source.career_url).hostname}",
            "公司官网",
        )
        for source in sources
    )
    positive_roles, _ = select_term_groups(query, [g[0] for g in _ROLE_GROUPS])
    for aliases, terms in _ROLE_GROUPS:
        if aliases not in positive_roles:
            continue
        for term in terms:
            if not _contains(query.casefold(), term):
                tasks.append(SearchTask(f"{query} {term}", "同义岗位"))
    seen = set()
    return [
        task
        for task in tasks
        if not (
            query_identity(task.query) in seen or seen.add(query_identity(task.query))
        )
    ]


def build_search_tasks(query, sources=()):
    if has_exclusions(query):
        # Splitting a negated query into keywords would erase its meaning.
        return build_agent_search_tasks(query, sources)
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


def next_search_task(tasks, completed, duplicate_streak=0, *, poor_results=False, last_strategy=None):
    completed_keys = {query_identity(query) for query in completed}
    available = [
        task for task in tasks if query_identity(task.query) not in completed_keys
    ]
    if poor_results:
        # Alternate broad recovery and a concrete employer scope; repeatedly
        # appending synonyms to the same broad query can fail in the same way.
        if last_strategy in {"条件补搜", "同义岗位", "方向与城市"}:
            company = next((t for t in available if t.strategy == "公司官网"), None)
            if company:
                return company
        alternative = next(
            (t for t in available if t.strategy in {"条件补搜", "同义岗位", "方向与城市"}), None
        )
        if alternative:
            return alternative
    if duplicate_streak:
        # A repeated result set changes the actual query, not just the prompt.
        alternative = next(
            (t for t in available if t.strategy in {"公司官网", "同义岗位"}), None
        )
        if alternative:
            return alternative
    return available[0] if available else None
