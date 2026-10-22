from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class CompanySource:
    id: str
    company: str
    priority: str
    career_url: str
    entry_type: str
    enabled: bool = True
    resource_hosts: tuple[str, ...] = ()
    official_homepage_url: str | None = None
    hiring_evidence_url: str | None = None
    verification_method: str = "automatic"


REGISTRY_PATH = Path(__file__).resolve().parents[1] / "data" / "company_sources.json"


def load_company_sources() -> list[CompanySource]:
    payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise TypeError("公司来源注册表必须是数组")

    sources: list[CompanySource] = []
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    for item in payload:
        if not isinstance(item, dict):
            raise TypeError("公司来源注册表包含无效记录")
        source = CompanySource(
            id=str(item["id"]).strip(),
            company=str(item["company"]).strip(),
            priority=str(item.get("priority", "C")).strip().upper(),
            career_url=str(item["career_url"]).strip(),
            entry_type=str(item.get("entry_type", "official_career_page")).strip(),
            enabled=bool(item.get("enabled", True)),
            resource_hosts=tuple(item.get("resource_hosts", [])),
        )
        if not source.id or not source.company or not source.career_url:
            raise ValueError("公司来源注册表记录缺少必填字段")
        if source.id in seen_ids:
            raise ValueError(f"公司来源 ID 重复：{source.id}")
        if source.career_url in seen_urls:
            raise ValueError(f"公司招聘入口重复：{source.career_url}")
        if source.priority not in {"A", "B", "C"}:
            raise ValueError(f"公司来源优先级无效：{source.priority}")
        seen_ids.add(source.id)
        seen_urls.add(source.career_url)
        sources.append(source)
    return sources


def enabled_company_sources(
    company_ids: Sequence[str] | None = None,
    *, session=None, user_id: str | None = None,
) -> list[CompanySource]:
    priority_order = {"A": 0, "B": 1, "C": 2}
    sources = sorted(
        (source for source in load_company_sources() if source.enabled),
        key=lambda source: (priority_order[source.priority], source.company),
    )
    if session is not None and user_id is not None:
        from sqlalchemy import select

        from src.domain.company_source import (
            ACCEPTED_COMPANY_STATUSES,
            DiscoveredCompany,
        )

        rows = session.scalars(select(DiscoveredCompany).where(
            DiscoveredCompany.user_id == user_id, DiscoveredCompany.status.in_(ACCEPTED_COMPANY_STATUSES),
        ).order_by(DiscoveredCompany.created_at, DiscoveredCompany.id))
        sources.extend(CompanySource(
            id=row.id, company=row.company, priority="C", career_url=row.career_url,
            entry_type="discovered_official", official_homepage_url=row.homepage_url,
            hiring_evidence_url=(row.evidence.get("manual_confirmation", {}).get("homepage_url")
                if row.status == "manually_confirmed" else row.evidence.get("hiring_link", {}).get("url")),
            verification_method="manual" if row.status == "manually_confirmed" else "automatic",
        ) for row in rows)
    if company_ids is None:
        return sources

    sources_by_id = {source.id: source for source in sources}
    unknown_ids = [source_id for source_id in company_ids if source_id not in sources_by_id]
    if unknown_ids:
        raise ValueError(f"未知公司来源：{', '.join(unknown_ids)}")
    return [sources_by_id[source_id] for source_id in company_ids]


def company_source_hosts(sources: Sequence[CompanySource]) -> set[str]:
    hosts: set[str] = set()
    for source in sources:
        from src.services.recruitment_trust import ATS_DOMAINS

        for url in (source.career_url, source.official_homepage_url):
            host = urlsplit(url).hostname if url else None
            if host and not any(host == root or host.endswith("." + root) for root in ATS_DOMAINS):
                hosts.add(host.rstrip(".").lower())
    return hosts


def enabled_company_source_hosts(*, session=None, user_id=None) -> set[str]:
    """Return official source hosts that may use the configured local proxy."""

    return company_source_hosts(enabled_company_sources(session=session, user_id=user_id))


def provider_source_options(company_ids, sources):
    """Supply private source names only when an ID requires that registry."""
    if company_ids and any(source.id in company_ids and getattr(source, "official_homepage_url", None) for source in sources):
        return {"sources": sources}
    return {}


def within_company_source(url, source):
    """An acquired source grants one employer host or one ATS tenant."""
    from src.services.recruitment_trust import hiring_scope, within_scope

    scope = hiring_scope(source.career_url)
    return within_scope(url, scope) if scope else urlsplit(url).hostname == urlsplit(source.career_url).hostname
