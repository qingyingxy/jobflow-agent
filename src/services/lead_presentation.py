from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

from src.services.company_registry import enabled_company_source_hosts


def reference_link_reason(url: str) -> str | None:
    """These URLs are source material, not concrete HTML job pages."""
    path = urlsplit(url).path.lower()
    if re.search(r"\.(?:pdf|docx?|xlsx?|pptx?|zip|png|jpe?g|gif|mp4)$", path):
        return "attachment_or_document"
    if re.search(r"/(?:teachin|career-fair|job-fair|career-event)(?:/|$)", path):
        return "recruitment_event"
    if re.search(
        r"/(?:feed|discuss|discussion|forum|forums|article|articles|news|blog|blogs|wiki|comments)(?:/|$)",
        path,
    ):
        return "article_or_discussion"
    return None


def discovery_kind(url: str, title: str | None = None) -> str:
    if reference_link_reason(url):
        return "entry"
    parsed = urlsplit(url)
    route = (
        urlsplit(parsed.fragment.lstrip("!"))
        if parsed.fragment.startswith(("/", "!/"))
        else parsed
    )
    path = route.path.lower().rstrip("/")
    params = {k.lower() for k in parse_qs(route.query)}
    # A listing path remains a listing even when search/card URLs carry an ID.
    if re.search(r"(?:^|/)(?:[\w-]*[_-])?(?:list|search)(?:[_-][\w-]*)?(?:/|$)", path):
        return "entry"
    if params & {
        "positionid",
        "jobid",
        "job_id",
        "position_id",
        "requisitionid",
        "requirementid",
        "requementid",
    }:
        return "job"
    if not path or path.endswith(
        (
            "/careers",
            "/jobs",
            "/joinus",
            "/about",
            "/campus",
            "/social",
            "/search",
            "/list",
            "-list",
            "/hot-jobs",
            "/positions",
        )
    ):
        return "entry"
    if re.search(
        r"/(?:job[-_]?detail|position[-_]?detail|job[-_]info[-_]detail)/[^/]+", path
    ):
        return "job"
    # ByteDance and similar sites put the concrete ID before a trailing /detail.
    # Bare /jobs/detail and listing names still need an actual detail identifier.
    detail = re.search(r"/(?:jobs?|positions?)/([^/]+)/detail(?:\.html?)?$", path)
    if detail:
        return (
            "entry"
            if detail.group(1) in {"search", "list", "detail", "campus", "social"}
            else "job"
        )
    if re.search(
        r"/(?:jobs?|positions?|vacanc(?:y|ies)|post|p|intern|detail|view)/(?:detail/)?[^/]+",
        path,
    ) and not path.endswith("/detail"):
        return "job"
    if title and re.search(
        r"工程师|开发实习生|产品经理|engineer|developer|analyst", title, re.IGNORECASE
    ):
        return "job"
    return "entry"


def source_label(url: str) -> str:
    return (
        "官网域名"
        if urlsplit(url).hostname in enabled_company_source_hosts()
        else "来源待核实"
    )
