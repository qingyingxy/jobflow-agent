"""Persist fair company rotation independently of a single search run's budget."""

from copy import deepcopy
from datetime import UTC, datetime
from urllib.parse import urlsplit

from src.services.company_search_progress import fresh_cursor, supports_direct_listing
from src.services.search_planner import SearchTask


class CompanyCoverage:
    def __init__(self, *, sources, store, query, batch_size, continued_company=None):
        self.store, self.query = store, query
        self.states = store.load()
        self.web_attempted = set()
        self.result_updates = {}

        def order(source):
            state = self.states.get(source.id, {})
            last = state.get("last_attempt_at") or state.get("updated_at") or ""
            return (bool(last), last, not supports_direct_listing(source), not getattr(source, "official_homepage_url", None))

        from src.services.source_performance import select_sources

        self.sources = (
            [s for s in sources if s.id == continued_company]
            if continued_company else select_sources(sources, self.states, batch_size, order)
        )

    def observe(self, source_id, kind, details):
        from src.services.source_performance import observation

        if source_id not in {s.id for s in self.sources}:
            return
        sample = observation(kind, details)
        if sample is None:
            return
        state = self.states.setdefault(source_id, {})
        state["performance"] = [*state.get("performance", []), sample][-12:]
        self.store.save(source_id, state)

    def direct_states(self):
        # A completed listing is refreshed on its next turn. A partial listing
        # resumes until its cursor expires or the goal version changes.
        result = {}
        for source in self.sources:
            from src.services.verified_recruitment_entry import fresh_entry

            state = self.states.get(source.id, {})
            if not supports_direct_listing(source):
                continue
            if (state.get("strategy") == "official_listing" and fresh_cursor(state)
                    and (not state.get("verified_entry") or fresh_entry(state, source))
                    and state.get("status") != "completed"):
                result[source.id] = deepcopy(state)
            else:
                from src.services.verified_recruitment_entry import (
                    reusable_source_state,
                )

                if reusable := reusable_source_state(state, source):
                    result[source.id] = reusable
        return result

    def save_direct(self, source_id, state):
        # The web fallback may complete while this company is still reading.
        # Its query cursor belongs to the web producer, not the listing copy.
        current = self.states.get(source_id, {})
        state.update({k: current[k] for k in ("search_cursor", "search_status", "search_attempts", "performance") if k in current})
        updates = self.result_updates.get(source_id, {})
        if updates:
            state["checked_urls"] = list(dict.fromkeys([*state.get("checked_urls", []), *updates]))
            matched = set(state.get("matched_urls", []))
            for url, useful in updates.items():
                if useful:
                    matched.add(url)
                else:
                    matched.discard(url)
            state["matched_urls"] = sorted(matched)
        self.states[source_id] = deepcopy(state)
        self.store.save(source_id, state)

    def next_task(self, direct):
        for source in self.sources:
            if source.id in self.web_attempted:
                continue
            if getattr(direct, "running", False) and not direct.fallback_ready(source.id):
                continue
            listing = direct.states.get(source.id, {})
            if listing.get("status") in {"paused", "completed"} and listing.get("reason") not in {
                "listing_boundary", "pagination_unresolved", "pagination_loop",
                "dynamic_navigation_unresolved", "listing_changed", "pagination_changed",
                "pagination_replay_limit", "listing_scope_changed",
                "time_budget", "page_budget", "verification_budget", "verification_pending", "search_unconfirmed",
                "listing_not_ready", "listing_entry_only", "listing_empty",
                "entry_retry_pending",
            }:
                continue
            state = self.states.get(source.id, {})
            from src.services.direct_recruitment_search import search_keywords
            from src.services.search_intent import parse_conditions

            intent = parse_conditions(self.query)
            roles = search_keywords(self.query) or ["招聘"]
            cursor = state.get("search_cursor", 0)
            role = roles[cursor % len(roles)]
            # Retrieval is intentionally broader than eligibility. Requiring
            # every alternative role/year in an indexed snippet loses jobs.
            # The verifier still receives the unchanged full goal conditions.
            narrow_retry = state.get("search_status") in {"failed", "partial"}
            context = " ".join([*intent.locations[:2], *intent.job_types]) if not narrow_retry else ""
            from src.services.recruitment_trust import hiring_scope

            # A landing-page hostname may differ from the actual hiring site.
            # Prefer a listing already observed by the direct reader. When it
            # has found none, search this employer's official jobs without an
            # obsolete host restriction; downstream ownership checks still apply.
            entry = listing.get("base") or listing.get("listing_url")
            tenant = hiring_scope(source.career_url)
            if tenant:
                entry = source.career_url  # Never broaden a registered ATS tenant.
            scope = ""
            if entry:
                try:
                    tenant = hiring_scope(entry)
                    parsed = urlsplit(entry)
                    host = parsed.hostname if parsed.scheme in {"http", "https"} else None
                except ValueError:
                    host = None
                if host:
                    scope = " site:" + host + (tenant[1] if tenant else "")
            return SearchTask(
                f"{source.company} {role} {context} 官方招聘 岗位职责{scope}".strip(),
                "公司覆盖补搜", company_id=source.id,
            )
        return None

    def start_search(self, source_id, *, keep_listing=False):
        now = datetime.now(UTC).isoformat()
        state = self.states.setdefault(source_id, {})
        if not keep_listing or state.get("strategy") != "official_listing":
            if not fresh_cursor(state):
                state.update(started_at=now, checked_urls=[], matched_urls=[])
            state.update(strategy="web_search", status="running", reason=None)
        state.update(last_attempt_at=now, updated_at=now,
                     search_attempts=state.get("search_attempts", 0) + 1,
                     search_status="running")
        self.web_attempted.add(source_id)
        self.store.save(source_id, state)

    def finish_search(self, source_id, *, failed, partial=False):
        state = self.states[source_id]
        state["search_status"] = "failed" if failed else "partial" if partial else "succeeded"
        if not failed and not partial:
            state["search_cursor"] = state.get("search_cursor", 0) + 1
        if state.get("strategy") == "web_search":
            state.update(status="failed" if failed else "paused",
                         reason="search_failed" if failed else "search_partial" if partial else "search_probe")
        state["updated_at"] = datetime.now(UTC).isoformat()
        self.store.save(source_id, state)

    def record_match(self, source_id, url, useful):
        if source_id not in {s.id for s in self.sources} or not url:
            return
        state = self.states.get(source_id)
        if not state or state.get("strategy") not in {"web_search", "official_listing"}:
            return
        self.result_updates.setdefault(source_id, {})[url] = useful
        state["checked_urls"] = list(dict.fromkeys([*state.get("checked_urls", []), url]))
        matched = set(state.get("matched_urls", []))
        if useful:
            matched.add(url)
        else:
            matched.discard(url)
        state["matched_urls"] = sorted(matched)
        self.store.save(source_id, state)
