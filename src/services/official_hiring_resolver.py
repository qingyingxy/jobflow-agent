"""Resolve an ATS tenant using links fetched from a registered employer site."""

import asyncio
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from src.services.browser_job_reader import BrowserReadError
from src.services.recruitment_trust import ATS_DOMAINS, hiring_scope, within_scope
from src.services.url_reader import URLReaderError, extract_html_links


@dataclass(frozen=True)
class OfficialHiringEvidence:
    entry_url: str
    from_url: str
    scope_url: str
    snapshot_id: str | None
    company: str


def same_official_site(url, entry_url):
    host = (urlsplit(url).hostname or "").removeprefix("www.")
    expected = (urlsplit(entry_url).hostname or "").removeprefix("www.")
    return bool(host and host == expected)


def observed_scope(url):
    """Only for observed, employer-verified entries; never a name-based guess."""
    scope = hiring_scope(url)
    if scope:
        return scope
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    from src.services.company_entry_resolution import permitted_entry

    if (parsed.scheme not in {"http", "https"} or parsed.username or not host
            or not permitted_entry(url)
            or any(host == root or host.endswith("." + root) for root in ATS_DOMAINS)):
        return None
    return host, parsed.path.rstrip("/") + "/"


def covers(url, entry):
    scope = observed_scope(entry)
    parsed = urlsplit(url)
    return bool(parsed.scheme in {"http", "https"} and not parsed.username
                and scope and within_scope(url, scope))


class OfficialHiringResolver:
    """Per-run cache and bounded reads; names only select a site to inspect."""

    def __init__(self, *, sources, reader, browser, max_companies=4):
        self.sources = sources
        self.reader = reader
        self.browser = browser
        self.max_companies = max_companies
        self.cache = {}
        self.locks = {}
        self.entry_states = dict
        self.on_entry = lambda source, entry: None

    async def resolve(self, candidate, *, record_snapshot):
        from src.services.verified_recruitment_entry import fresh_entry

        for source in self.sources:
            entry = fresh_entry(self.entry_states().get(source.id, {}), source)
            if entry and covers(candidate.source_url, entry["scope_url"]):
                snapshot_id = record_snapshot(entry["proof_url"], entry.get("official_html", ""))
                return OfficialHiringEvidence(source.career_url, entry["proof_url"],
                    entry["scope_url"], snapshot_id, source.company)
        for source in self.sources:
            scope = hiring_scope(source.career_url)
            if (getattr(source, "official_homepage_url", None) and source.hiring_evidence_url and scope
                    and within_scope(candidate.source_url, scope)):
                return OfficialHiringEvidence(source.official_homepage_url,
                    source.hiring_evidence_url, source.career_url, None, source.company)
        for records in self.cache.values():
            for record in records:
                if covers(candidate.source_url, record.scope_url):
                    return record
        primary = " ".join(
            filter(
                None,
                [
                    candidate.company_hint,
                    candidate.title_hint,
                    urlsplit(candidate.source_url).hostname,
                ],
            )
        )

        def mentions(source, text):
            aliases = [
                source.company,
                source.id,
                *re.split(r"\s*/\s*|\s+", source.company),
            ]
            return any(
                re.search(
                    r"(?<![a-zA-Z0-9])" + re.escape(alias) + r"(?![a-zA-Z0-9])",
                    text,
                    re.IGNORECASE,
                )
                for alias in aliases
                if len(alias) >= (3 if alias.isascii() else 2)
            )

        # Direct title/tenant hints outrank incidental companies in search prose.
        for source in sorted(
            self.sources, key=lambda source: not mentions(source, primary)
        ):
            if getattr(source, "official_homepage_url", None):
                # Discovered sources carry a persisted, narrow tenant proof.
                # Do not broaden it by following links from a shared ATS page.
                continue
            if not mentions(source, primary + " " + (candidate.search_snippet or "")):
                continue
            cache_key = (source.id, urlsplit(candidate.source_url).hostname)
            lock = self.locks.setdefault(source.id, asyncio.Lock())
            async with lock:
                if cache_key not in self.cache:
                    companies_read = {key[0] for key in self.cache}
                    if source.id not in companies_read and len(companies_read) >= self.max_companies:
                        return None
                    self.cache[cache_key] = []
                    try:
                        self.cache[cache_key] = await asyncio.wait_for(
                            self._read_source(source, record_snapshot, candidate.source_url),
                            timeout=25,
                        )
                    except (TimeoutError, URLReaderError, BrowserReadError):
                        pass
                for record in self.cache[cache_key]:
                    if covers(candidate.source_url, record.scope_url):
                        return record
        return None

    async def _read_source(self, source, record_snapshot, target_url=None):
        queue, visited, records = [source.career_url], set(), []
        while queue and len(visited) < 3:
            url = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)
            pages = []
            try:
                async with asyncio.timeout(6):
                    response = await self.reader.fetch(url)
                pages.append(
                    (
                        response.final_url,
                        response.body.decode("utf-8", errors="replace"),
                    )
                )
            except (URLReaderError, TimeoutError):
                pass
            if not pages or not any(
                hiring_scope(link.url) or (target_url and covers(target_url, link.url))
                for _, html in pages
                for link in extract_html_links(html, base_url=url)
            ):
                try:
                    snapshot = await self.browser.read(url)
                    pages.append((snapshot.final_url, snapshot.raw_html))
                except BrowserReadError:
                    pass
            for final_url, html in pages:
                snapshot_id = record_snapshot(final_url, html)
                if not same_official_site(final_url, source.career_url):
                    continue
                for link in extract_html_links(html, base_url=final_url):
                    if hiring_scope(link.url):
                        records.append(
                            OfficialHiringEvidence(
                                source.career_url,
                                final_url,
                                link.url,
                                snapshot_id,
                                source.company,
                            )
                        )
                    elif (target_url and covers(target_url, link.url)
                          and not same_official_site(link.url, source.career_url)
                          and re.search(r"招聘|校招|应届|职位|岗位|投递|careers?|jobs?|recruit", link.text, re.IGNORECASE)):
                        # Custom hiring hosts need both an actual official link
                        # and the destination's employer identity. A mention in
                        # a search snippet cannot establish ownership.
                        from src.services.company_discovery import mentions
                        from src.services.url_reader import parse_html_document
                        from src.services.verified_recruitment_entry import (
                            remember_entry,
                        )

                        try:
                            async with asyncio.timeout(6):
                                destination = await self.reader.fetch(link.url)
                            from src.services.recruitment_listing import (
                                allowed_listing_url,
                            )

                            document = parse_html_document(destination.body.decode("utf-8", errors="replace"))
                            if (not 200 <= destination.status_code < 300
                                    or not allowed_listing_url(destination.final_url, link.url)
                                    or not mentions(source.company, document.title or "")):
                                continue
                        except (URLReaderError, TimeoutError):
                            continue
                        entry = remember_entry(source, {"url": link.url, "scope_url": link.url,
                            "proof_url": final_url, "official_html": html, "require_brand": True})
                        self.on_entry(source, entry)
                        records.append(OfficialHiringEvidence(source.career_url, final_url,
                            link.url, snapshot_id, source.company))
                    elif (
                        same_official_site(link.url, source.career_url)
                        and link.url not in visited
                        and link.url not in queue
                        and re.search(
                            r"招聘|加入|careers?|join|recruit",
                            link.text + " " + urlsplit(link.url).path,
                            re.IGNORECASE,
                        )
                    ):
                        queue.append(link.url)
            if records:
                break
        return records
