"""Resolve an ATS tenant using links fetched from a registered employer site."""

import asyncio
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from src.services.browser_job_reader import BrowserReadError
from src.services.recruitment_trust import hiring_scope, within_scope
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


class OfficialHiringResolver:
    """Per-run cache and bounded reads; names only select a site to inspect."""

    def __init__(self, *, sources, reader, browser, max_companies=4):
        self.sources = sources
        self.reader = reader
        self.browser = browser
        self.max_companies = max_companies
        self.cache = {}
        self.locks = {}

    async def resolve(self, candidate, *, record_snapshot):
        if not hiring_scope(candidate.source_url):
            return None
        for records in self.cache.values():
            for record in records:
                if within_scope(candidate.source_url, hiring_scope(record.scope_url)):
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
            if not mentions(source, primary + " " + (candidate.search_snippet or "")):
                continue
            lock = self.locks.setdefault(source.id, asyncio.Lock())
            async with lock:
                if source.id not in self.cache:
                    if len(self.cache) >= self.max_companies:
                        return None
                    self.cache[source.id] = []
                    try:
                        self.cache[source.id] = await asyncio.wait_for(
                            self._read_source(source, record_snapshot),
                            timeout=25,
                        )
                    except (TimeoutError, URLReaderError, BrowserReadError):
                        pass
                for record in self.cache[source.id]:
                    if within_scope(
                        candidate.source_url, hiring_scope(record.scope_url)
                    ):
                        return record
        return None

    async def _read_source(self, source, record_snapshot):
        queue, visited, records = [source.career_url], set(), []
        while queue and len(visited) < 3:
            url = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)
            pages = []
            try:
                response = await self.reader.fetch(url)
                pages.append(
                    (
                        response.final_url,
                        response.body.decode("utf-8", errors="replace"),
                    )
                )
            except URLReaderError:
                pass
            if not pages or not any(
                hiring_scope(link.url)
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
