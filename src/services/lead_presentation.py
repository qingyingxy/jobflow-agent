from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

from src.services.company_registry import enabled_company_source_hosts


def discovery_kind(url: str, title: str | None = None) -> str:
    parsed = urlsplit(url)
    route = urlsplit(parsed.fragment.lstrip("!")) if parsed.fragment.startswith(("/", "!/")) else parsed
    path = route.path.lower().rstrip("/")
    params = {k.lower() for k in parse_qs(route.query)}
    if params & {"positionid", "jobid", "job_id", "position_id", "requisitionid"}:
        return "job"
    if not path or path.endswith(("/careers", "/jobs", "/joinus", "/about", "/campus", "/social", "/search", "/list", "-list", "/hot-jobs", "/positions")):
        return "entry"
    if re.search(r"/(?:jobs?|positions?|vacanc(?:y|ies)|post|p|intern|detail|view)/(?:detail/)?[^/]+", path) and not path.endswith("/detail"):
        return "job"
    if title and re.search(r"工程师|开发实习生|产品经理|engineer|developer|analyst", title, re.IGNORECASE):
        return "job"
    return "entry"


def source_label(url: str) -> str:
    return "官网域名" if urlsplit(url).hostname in enabled_company_source_hosts() else "来源待核实"
