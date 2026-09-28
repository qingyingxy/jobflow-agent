from __future__ import annotations

import re
from urllib.parse import urlsplit

from src.services.browser_job_reader import BrowserReadError
from src.services.lead_presentation import discovery_kind
from src.services.recruitment_trust import hiring_scope, within_scope
from src.services.url_reader import URLReaderError, extract_html_links


async def expand_entry(
    url,
    *,
    reader,
    browser,
    allowed_hosts,
    record_snapshot,
    max_pages=6,
    query="",
    official_hosts=None,
    on_detail=None,
    on_event=None,
):
    """Follow a bounded number of public list pages, returning observed detail links."""
    queue = [url]
    visited = set()
    details = {}
    scopes = []
    pages_read = 0
    listing_snapshots = 0
    official_hosts = official_hosts or set()

    def permitted(target):
        return urlsplit(target).hostname in allowed_hosts or any(
            within_scope(target, scope) for scope in scopes
        )

    def collect(links, page_url):
        for link in links:
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
                if link.url not in details:
                    details[link.url] = link
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

    while queue and pages_read < max_pages:
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
        if not any(
            discovery_kind(link.url, link.text) == "job" for link in links
        ) or re.search(
            r"<(?:button|[^>]+role=[\"']button)[^>]*>[^<]*(?:下一页|加载更多|更多职位|next|load more)",
            html,
            re.IGNORECASE,
        ):
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
                },
            )
        if len(details) >= 100:
            break
    from src.services.discovery_matching import classify_discovery_job
    from src.services.discovery_sources import JobStub

    def relevance(link):
        stub = JobStub(
            source_id="entry",
            source_job_id=link.url,
            company=None,
            title=link.text,
            locations=[],
            job_type=None,
            published_at=None,
            detail_url=link.url,
            raw_content=link.text,
        )
        return "role" in classify_discovery_job(stub, query=query).mismatch_reasons

    return sorted(details.values(), key=relevance)
