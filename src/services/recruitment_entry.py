from __future__ import annotations

import re
from urllib.parse import urlsplit

from src.services.browser_job_reader import BrowserReadError
from src.services.job_url import canonical_job_url
from src.services.lead_presentation import discovery_kind
from src.services.recruitment_trust import hiring_scope, within_scope
from src.services.retrieval_quality import search_link_rejection
from src.services.url_reader import HTMLLink, URLReaderError, extract_html_links


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
    state=None,
    page_cache=None,
    on_checkpoint=None,
):
    """Follow a bounded number of public list pages, returning observed detail links."""
    state = state if state is not None else {}
    queue = list(state.get("queue", [url]))
    visited = set(state.get("visited", []))
    details = {}
    scopes = [tuple(scope) for scope in state.get("scopes", [])]
    if initial_scope and initial_scope not in scopes:
        scopes.append(initial_scope)
    delivered = set(state.get("delivered", []))
    pending_details = dict(state.get("pending_details", {}))
    observed_details = set()
    deferred_details = set()
    max_details = max(1, min(100, max_details))
    pages_read = 0
    attempted = set()
    listing_snapshots = 0
    official_hosts = official_hosts or set()

    from src.services.discovery_matching import _contains, requested_role_terms

    def allow_transport(scope):
        for transport in (reader, browser):
            checker = getattr(transport, "safety_checker", None)
            if checker is not None and hasattr(checker, "proxy_allowed_hosts"):
                checker.proxy_allowed_hosts = checker.proxy_allowed_hosts | {scope[0]}

    # Resumed pages retain the scopes observed from this goal's official entry.
    # Transport permission is host-level; permitted() still checks the tenant.
    for scope in scopes:
        allow_transport(scope)

    def relevance(link):
        # A title is a scheduling hint, never a verified filtering verdict.
        return not any(_contains(link.text.casefold(), term)
                       for group in requested_role_terms(query) for term in group)

    def permitted(target):
        return urlsplit(target).hostname in allowed_hosts or any(
            within_scope(target, scope) for scope in scopes
        )

    def checkpoint():
        state.update(queue=list(queue), visited=sorted(visited), delivered=sorted(delivered),
                     pending_details=dict(pending_details), scopes=[list(scope) for scope in scopes])
        if on_checkpoint:
            on_checkpoint(state)

    def duplicate(page_url, html, *, rendered=False):
        repeated = page_cache and page_cache.duplicate_content(page_url, html, rendered=rendered)
        if repeated and on_event:
            on_event("entry_duplicate", {"url": page_url, "reason": "same_observed_content"})
        return repeated

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
                allow_transport(scope)
                if on_event:
                    on_event(
                        "official_link",
                        {"from_url": page_url, "url": link.url, "scope": list(scope)},
                    )
            if discovery_kind(link.url, link.text, observed_title=True) == "job":
                key = canonical_job_url(link.url)
                observed_details.add(key)
                if key not in delivered:
                    if len(details) >= max_details:
                        deferred_details.add(key)
                        pending_details[key] = {"text": link.text, "from_url": page_url}
                        continue
                    details[key] = link
                    delivered.add(key)
                    pending_details.pop(key, None)
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
                and canonical_job_url(link.url) not in visited
                and canonical_job_url(link.url) not in {canonical_job_url(item) for item in queue}
                and len(queue) < 200
            ):
                queue.append(link.url)

    def capture_listing(page_url, html):
        nonlocal pages_read, listing_snapshots
        if listing_snapshots:
            pages_read += 1
        listing_snapshots += 1
        record_snapshot(page_url, html)
        if permitted(page_url) and not duplicate(page_url, html, rendered=True):
            collect(extract_html_links(html, base_url=page_url), page_url)
        checkpoint()

    # Links already observed beyond a previous cap are consumed before a new read.
    for key, saved in list(pending_details.items()):
        if len(details) >= max_details:
            break
        collect([HTMLLink(key, saved["text"])], saved["from_url"])
    checkpoint()

    while queue and pages_read < max_pages and len(details) < max_details:
        current = next((item for item in queue if canonical_job_url(item) not in attempted), None)
        if current is None:
            break
        queue.remove(current)
        queue.insert(0, current)
        if canonical_job_url(current) in visited or not permitted(current) or (page_cache and page_cache.contains(current)):
            queue.pop(0)
            checkpoint()
            continue
        pages_read += 1
        attempted.add(canonical_job_url(current))
        listing_snapshots = 0
        links = []
        html = ""
        final_url = current
        complete = False
        repeated = False
        try:
            response = await reader.fetch(current)
            html = response.body.decode("utf-8", errors="replace")
            record_snapshot(response.final_url, html)
            if permitted(response.final_url):
                final_url = response.final_url
                repeated = bool(page_cache and page_cache.contains(final_url)) or duplicate(final_url, html)
                links = extract_html_links(html, base_url=response.final_url)
                if not repeated:
                    collect(links, response.final_url)
                complete = True
                checkpoint()
        except URLReaderError as error:
            if on_event:
                on_event("entry_read", {"url": current, "error_code": error.code})
        if not repeated and len(details) < max_details and (not any(
            discovery_kind(link.url, link.text, observed_title=True) == "job" for link in links
        ) or re.search(
            r"<(?:button|[^>]+role=[\"']button)[^>]*>[^<]*(?:下一页|加载更多|更多职位|next|load more)",
            html,
            re.IGNORECASE,
        )):
            complete = False
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
                    if permitted(page_url) and not duplicate(page_url, html, rendered=True):
                        collect(extract_html_links(html, base_url=page_url), page_url)
                if permitted(snapshot.final_url):
                    final_url = snapshot.final_url
                    complete = True
            except BrowserReadError as error:
                if on_event:
                    on_event("entry_read", {"url": current, "error_code": error.code})
        if complete:
            visited.update([canonical_job_url(current), canonical_job_url(final_url)])
            queue.pop(0)
            if page_cache and not pending_details:
                page_cache.complete(current, final_url)
        else:
            queue.append(queue.pop(0))
        checkpoint()
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
