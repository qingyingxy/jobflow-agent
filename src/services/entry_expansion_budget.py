"""Bound entry exploration separately from job verification; retain resumable pages."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from time import monotonic
from urllib.parse import urlsplit

from src.services.job_url import canonical_job_url
from src.services.lead_presentation import discovery_kind
from src.services.recruitment_trust import hiring_scope
from src.services.url_reader import extract_html_links, parse_html_document


class EntryPageCache:
    """Run-local deduplication of observed pages, never guessed query semantics."""

    def __init__(self):
        self.urls = set()
        self.contents = set()

    def contains(self, url):
        return canonical_job_url(url) in self.urls

    def duplicate_content(self, url, html, *, rendered=False):
        # Identical JS shells can produce different filtered results. Only a
        # rendered page or script-free page containing actual jobs is comparable.
        if not rendered and "<script" in html.casefold():
            return False
        links = extract_html_links(html, base_url=url)
        if not any(discovery_kind(link.url, link.text, observed_title=True) == "job" for link in links):
            return False
        parsed = urlsplit(url)
        scope = hiring_scope(url) or (parsed.hostname,)
        value = (scope, parse_html_document(html).text,
                 sorted((canonical_job_url(link.url), link.text) for link in links))
        key = sha256(repr(value).encode()).hexdigest()
        duplicate = key in self.contents
        self.contents.add(key)
        return duplicate

    def complete(self, *urls):
        self.urls.update(canonical_job_url(url) for url in urls)


class EntryExpansionBudget:
    def __init__(self, *, seconds=45, item_seconds=15, limit=8, empty_limit=2,
                 states=None, checkpoint=None, clock=monotonic):
        self.seconds, self.item_seconds = seconds, item_seconds
        self.limit, self.empty_limit = limit, empty_limit
        self.states = deepcopy(states or {})
        self.checkpoint = checkpoint or (lambda *_: None)
        self.clock = clock
        self.spent = 0.0
        self.started = {}
        self.empty_counts = {}
        self.pages = EntryPageCache()

    def reason(self, url, source):
        key = canonical_job_url(url)
        if key in self.started:
            return "entry_duplicate"
        try:
            due = datetime.fromisoformat(self.states.get(key, {}).get("next_retry_at", ""))
            if due.replace(tzinfo=due.tzinfo or UTC) > datetime.now(UTC):
                return "entry_cooldown"
        except (TypeError, ValueError):
            pass
        if self.spent >= self.seconds or len(self.started) >= self.limit:
            return "entry_budget"
        if self.empty_counts.get(source, 0) >= self.empty_limit:
            return "entry_no_progress"
        return None

    def begin(self, url):
        key = canonical_job_url(url)
        self.started[key] = self.clock()
        return min(self.item_seconds, max(0, self.seconds - self.spent))

    def cursor(self, url):
        state = self.states.get(canonical_job_url(url), {})
        return {} if state.get("complete") else deepcopy(state.get("cursor", {}))

    def save_cursor(self, url, source, cursor):
        key = canonical_job_url(url)
        state = {**self.states.get(key, {}), "source": source,
                 "cursor": deepcopy(cursor), "updated_at": datetime.now(UTC).isoformat()}
        self.states[key] = state
        self.checkpoint(key, state)

    def finish(self, url, source, cursor, count, *, interrupted=False):
        key = canonical_job_url(url)
        self.spent += max(0, self.clock() - self.started[key])
        self.empty_counts[source] = 0 if count else self.empty_counts.get(source, 0) + 1
        complete = not cursor.get("queue") and not cursor.get("pending_details")
        # Empty completed pages get a cooldown; interrupted work keeps its queue.
        delay = 60 if interrupted and not count else 900 if not count else 3600 if complete else 0
        self.states[key] = {**self.states.get(key, {}), "output_count": count,
                            "complete": complete and not interrupted,
                            "next_retry_at": (datetime.now(UTC) + timedelta(seconds=delay)).isoformat() if delay else None}
        self.save_cursor(url, source, cursor)
