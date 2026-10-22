from __future__ import annotations

import re
from functools import lru_cache
from urllib.parse import parse_qs, urlsplit

from src.services import company_registry
from src.services.company_registry import enabled_company_source_hosts


def reference_link_reason(url: str) -> str | None:
    """These URLs are source material, not concrete HTML job pages."""
    parsed = urlsplit(url)
    route = urlsplit(parsed.fragment.lstrip("!")) if parsed.fragment.startswith(("/", "!/")) else parsed
    path = route.path.lower()
    # Referral tracking on a real detail URL is fine; invitation/application
    # endpoints themselves do not describe a job, even on an official host.
    if re.search(r"/(?:invite|invitation|referral|login|signin|sign-in|signup|register|apply|application)(?:/|\.html?$|$)", path):
        return "recruitment_action_page"
    # Official domains also expose legal navigation in search results. Those
    # pages are not recruiting entries, even when their footer links to jobs.
    if re.fullmatch(
        r"/(?:[a-z]{2}(?:-[a-z]{2})?/)?(?:legal/)?"
        r"(?:privacy|privacy[-_]policy|terms|terms[-_]of[-_]use|cookies?)"
        r"(?:\.html?)?/?",
        path,
    ):
        return "legal_or_privacy_page"
    if re.search(r"\.(?:pdf|docx?|xlsx?|pptx?|zip|png|jpe?g|gif|mp4)$", path):
        return "attachment_or_document"
    if re.search(r"/(?:teachin|career-fair|job-fair|career-event)(?:/|$)", path):
        return "recruitment_event"
    if re.search(
        r"/(?:feed|(?:recruit|career|company)feed|discuss|discussion|forum|forums|articles?|article[-_]?detail|news|blog|blogs|wiki|comments)(?:/|$)",
        path,
    ):
        return "article_or_discussion"
    if re.search(r"/(?:community|communities)/(?:detail|topics?|posts?|threads?)(?:/|$)|/(?:ugc[_-]article)(?:/|$)", path):
        return "article_or_discussion"
    if re.search(r"/(?:help|support)/(?:topics?|faq|guides?)(?:/|$)", path):
        return "help_or_support_page"
    return None


def explicit_listing_url(url: str) -> bool:
    parsed = urlsplit(url)
    route = urlsplit(parsed.fragment.lstrip("!")) if parsed.fragment.startswith(("/", "!/")) else parsed
    return bool(re.search(r"(?:^|/)(?:[\w-]*[_-])?(?:list|search)(?:[_-][\w-]*)?(?:/|$)", route.path.lower()))


def discovery_kind(url: str, title: str | None = None, *, observed_title=False) -> str:
    """Route candidates; generated search titles alone cannot establish a detail URL."""
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
    if explicit_listing_url(url):
        return "entry"
    if params & {
        "positionid",
        "jobid",
        "postid",
        "job_id",
        "position_id",
        "requisitionid",
        "requirementid",
        "requementid",
        "jobadid",
        "jobunionid",
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
        r"/(?:jobs?|positions?|careers?|vacanc(?:y|ies)|post|p|intern|detail|view)/(?:detail/)?[^/]+",
        path,
    ) and not path.endswith("/detail"):
        return "job"
    if title and re.search(r"(?:项目|招聘|校招|宣讲)(?:介绍|入口|专题|官网|项目)?页|职位列表|岗位列表|招聘公告|招聘简章|career portal|talent program", title, re.IGNORECASE):
        return "entry"
    # A title read from an official card is useful for irregular detail routes.
    # Search-provider prose is only a hint and may name a job on a campaign page.
    if observed_title and title and re.search(
        r"工程师|研究员|开发实习生|产品经理|分析师|设计师|engineer|developer|analyst|scientist|researcher|designer", title, re.IGNORECASE
    ):
        return "job"
    return "entry"


@lru_cache(maxsize=1)
def _label_hosts(registry_path, modified_ns, size):
    # Display metadata only. Trust checks still use their original registry
    # and tenant evidence. Rebuild when the registry file changes.
    return frozenset(enabled_company_source_hosts())


def source_label(url: str) -> str:
    path = company_registry.REGISTRY_PATH
    stat = path.stat()
    return (
        "官网域名"
        if urlsplit(url).hostname in _label_hosts(str(path), stat.st_mtime_ns, stat.st_size)
        else "来源待核实"
    )


def lead_discovery_kind(lead) -> str:
    """Retain observed card provenance across persistence; it grants no trust."""
    fields = getattr(lead, "extracted_fields", None) or {}
    observed = getattr(lead, "observed_title", False) or fields.get("page_type_basis") == "observed_listing"
    observed = observed or fields.get("basis") == "page_snapshot"
    return "job" if getattr(lead, "job_posting_id", None) else discovery_kind(
        lead.source_url, fields.get("title") or lead.title_hint, observed_title=observed,
    )
