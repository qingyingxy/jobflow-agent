"""Reusable observed hiring entries, independent of query and page cursors."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta


def remember_entry(source, pending):
    # Called only after the reader validates the official navigation and, for
    # custom external domains, the destination's employer identity.
    entry = {key: deepcopy(pending[key]) for key in (
        "url", "scope_url", "proof_url", "official_html", "official_redirects",
        "official_navigation", "require_brand", "brand_evidence",
    ) if key in pending}
    entry["url"] = pending.get("entry_url", pending["url"])
    return {**entry, "registered_url": source.career_url,
            # Reading a destination again does not refresh the original
            # outbound-link proof indefinitely.
            "checked_at": pending.get("checked_at") or datetime.now(UTC).isoformat()}


def fresh_entry(state, source=None):
    entry = state.get("verified_entry", {})
    try:
        age = datetime.now(UTC) - datetime.fromisoformat(entry["checked_at"])
        if not timedelta(0) <= age < timedelta(days=30):
            return None
        if source and entry["registered_url"] != source.career_url:
            return None
        from src.services.recruitment_listing import allowed_listing_url

        if not allowed_listing_url(entry["url"], entry["scope_url"]):
            return None
        return deepcopy(entry)
    except (KeyError, TypeError, ValueError):
        return None


def reusable_source_state(state, source=None):
    from src.services.company_search_progress import fresh_search_profiles

    result = {}
    if entry := fresh_entry(state, source):
        result["verified_entry"] = entry
    if profiles := fresh_search_profiles(state):
        result["search_profiles"] = profiles
    return result


def current_progress(state, version):
    """Changed goals retain methods and proof, never prior filters or results."""
    if state.get("version") == version:
        return deepcopy(state)
    return {"version": version, "sources": {
        key: reusable_source_state(value) for key, value in state.get("sources", {}).items()
        if reusable_source_state(value)
    }}
