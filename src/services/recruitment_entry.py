from __future__ import annotations

import re
from urllib.parse import urlsplit

from src.services.browser_job_reader import BrowserReadError
from src.services.job_url import canonical_job_url
from src.services.lead_presentation import discovery_kind
from src.services.recruitment_trust import hiring_scope, within_scope
from src.services.retrieval_quality import search_link_rejection
from src.services.url_reader import URLReaderError, extract_html_links


async def expand_entry(
    url,
    *,
    reader,
    browser,
    allowed_hosts,
    record_snapshot,
    max_pages=6,
    max_details=20,
    initial_scope=None,
    query="",
    official_hosts=None,
    on_detail=None,
    on_event=None,
):
    """Follow a bounded number of public list pages, returning observed detail links."""
    queue = [url]
    visited = set()
    details = {}
    scopes = [initial_scope] if initial_scope else []
    observed_details = set()
    deferred_details = set()
    max_details = max(1, min(100, max_details))
    pages_read = 0
    listing_snapshots = 0
    official_hosts = official_hosts or set()

    from src.services.discovery_matching import classify_discovery_job
    from src.services.discovery_sources import JobStub

    def relevance(link):
        stub = JobStub(
            source_id="entry", source_job_id=link.url, company=None,
            title=link.text, locations=[], job_type=None, published_at=None,
            detail_url=link.url, raw_content=link.text,
        )
        # Routing priority only: a missing keyword is not proof of mismatch.
        return "role" in classify_discovery_job(stub, query=query).mismatch_reasons

    def permitted(target):
        return urlsplit(target).hostname in allowed_hosts or any(
            within_scope(target, scope) for scope in scopes
        )

    def collect(links, page_url):
        # Rank the entire observed page before admitting any job to the queue.
        for link in sorted(links, key=relevance):
            if search_link_rejection(link.url, link.text, query=query):
                continue
            parsed = urlsplit(link.url)
            if not permitted(link.url):
                scope = hiring_scope(link.url)
                if urlsplit(page_url).hostname not in official_hosts or not scope:
                    continue
                scopes.append(scope)
                # Routing permission is distinct from official-source trust:
                # allow the observed public ATS host through the existing proxy,
                # while `permitted` still enforces the tenant's URL prefix.
                for transport in (reader, browser):
                    checker = getattr(transport, "safety_checker", None)
                    if checker is not None and hasattr(checker, "proxy_allowed_hosts"):
                        checker.proxy_allowed_hosts = checker.proxy_allowed_hosts | {
                            scope[0]
                        }
                if on_event:
                    on_event(
                        "official_link",
                        {"from_url": page_url, "url": link.url, "scope": list(scope)},
                    )
            if discovery_kind(link.url, link.text) == "job":
                key = canonical_job_url(link.url)
                observed_details.add(key)
                if key not in details:
                    if len(details) >= max_details:
                        deferred_details.add(key)
                        continue
                    details[key] = link
                    if on_detail:
                        on_detail(link, page_url)
            elif (
                any(
                    term in (parsed.path + " " + link.text).lower()
                    for term in (
                        "job",
                        "career",
                        "position",
                        "campus",
                        "opportunit",
                        "join",
                        "下一页",
                        "next",
                        "招聘",
                        "职位",
                    )
                )
                and link.url not in visited
                and link.url not in queue
                and len(queue) < max_pages
            ):
                queue.append(link.url)

    def capture_listing(page_url, html):
        nonlocal pages_read, listing_snapshots
        if listing_snapshots:
            pages_read += 1
        listing_snapshots += 1
        record_snapshot(page_url, html)
        if permitted(page_url):
            collect(extract_html_links(html, base_url=page_url), page_url)

    while queue and pages_read < max_pages and len(details) < max_details:
        current = queue.pop(0)
        if current in visited or not permitted(current):
            continue
        visited.add(current)
        pages_read += 1
        listing_snapshots = 0
        links = []
        html = ""
        try:
            response = await reader.fetch(current)
            html = response.body.decode("utf-8", errors="replace")
            record_snapshot(response.final_url, html)
            if permitted(response.final_url):
                links = extract_html_links(html, base_url=response.final_url)
                collect(links, response.final_url)
        except URLReaderError as error:
            if on_event:
                on_event("entry_read", {"url": current, "error_code": error.code})
        if len(details) < max_details and (not any(
            discovery_kind(link.url, link.text) == "job" for link in links
        ) or re.search(
            r"<(?:button|[^>]+role=[\"']button)[^>]*>[^<]*(?:下一页|加载更多|更多职位|next|load more)",
            html,
            re.IGNORECASE,
        )):
            try:
                if hasattr(browser, "read_listing"):
                    snapshot = await browser.read_listing(
                        current,
                        max_pages=min(3, max_pages - pages_read + 1),
                        record_snapshot=capture_listing,
                    )
                else:
                    snapshot = await browser.read(current)
                record_snapshot(snapshot.final_url, snapshot.raw_html)
                for page_url, html in [
                    (snapshot.final_url, snapshot.raw_html),
                    *getattr(snapshot, "additional_pages", ()),
                ]:
                    if permitted(page_url):
                        collect(extract_html_links(html, base_url=page_url), page_url)
            except BrowserReadError as error:
                if on_event:
                    on_event("entry_read", {"url": current, "error_code": error.code})
        if on_event:
            on_event(
                "entry_page",
                {
                    "url": current,
                    "detail_count": len(details),
                    "visited_pages": pages_read,
                    "observed_details": len(observed_details),
                    "deferred_by_limit": len(deferred_details),
                    "max_details": max_details,
                },
            )
    return sorted(details.values(), key=relevance)
