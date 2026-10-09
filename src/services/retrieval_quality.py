"""Admit plausible recruitment links, retaining rejected URLs in search evidence.

This is routing of unverified sources, not an eligibility decision. Never infer
job facts from a search title or silently turn missing metadata into rejection.
"""

import re
from urllib.parse import urlsplit

from src.services.company_registry import enabled_company_source_hosts
from src.services.lead_presentation import discovery_kind, reference_link_reason
from src.services.recruitment_trust import hiring_scope


def search_link_rejection(url: str, title: str | None, *, query: str) -> str | None:
    reason = reference_link_reason(url)
    if reason:
        return reason
    # A dated recruitment announcement for another cohort is a reference. Dates
    # in paths, publication timestamps, and incomplete titles are not enough.
    wanted = set(re.findall(r"(20\d{2})\s*届", query))
    advertised = set(re.findall(r"(20\d{2})\s*届", title or ""))
    if (
        wanted
        and advertised
        and wanted.isdisjoint(advertised)
        and re.search(r"招聘|校招|毕业生", title or "")
    ):
        return "other_cohort_announcement"
    if discovery_kind(url, title) == "job":
        return None
    parsed = urlsplit(url)
    hosts = enabled_company_source_hosts()
    if parsed.hostname in hosts or hiring_scope(url):
        return None
    if re.search(
        r"(?:^|[./_-])(?:careers?|jobs?|recruitment|campus|positions?)(?:[./_-]|$)",
        parsed.hostname + parsed.path,
        re.IGNORECASE,
    ):
        return None
    if re.search(r"招聘|校招|校园|应届|职位|加入我们", title or ""):
        return None
    return "background_search_source"
