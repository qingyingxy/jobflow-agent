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
) -> list[CompanySource]:
    priority_order = {"A": 0, "B": 1, "C": 2}
    sources = sorted(
        (source for source in load_company_sources() if source.enabled),
        key=lambda source: (priority_order[source.priority], source.company),
    )
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
        host = urlsplit(source.career_url).hostname
        if host:
            hosts.add(host.rstrip(".").lower())
    return hosts


def enabled_company_source_hosts() -> set[str]:
    """Return official source hosts that may use the configured local proxy."""

    return company_source_hosts(enabled_company_sources())
