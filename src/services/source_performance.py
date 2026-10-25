"""Recent source utility changes scheduling, never eligibility or trust."""

from datetime import UTC, datetime


def source_score(state, *, now=None):
    now = now or datetime.now(UTC)
    samples = state.get("performance", [])
    weighted, weights = 0.0, 0.0
    for sample in samples:
        try:
            at = datetime.fromisoformat(sample["at"])
            age = max(0, (now - at.replace(tzinfo=at.tzinfo or UTC)).total_seconds())
        except (ValueError, KeyError, TypeError):
            continue
        # Old observations lose influence, allowing recovered sources to return.
        weight = 0.5 ** (age / 86400)
        if age > 7 * 86400:
            continue
        seconds = max(1, sample.get("duration_ms", 0) / 1000)
        quality = (1 if sample.get("success") else -1) + min(3, sample.get("details", 0))
        weighted += weight * quality / max(5, seconds)
        weights += weight
    if not weights:
        return 0.0
    checked = len(state.get("checked_urls", []))
    relevance = len(state.get("matched_urls", [])) / max(1, checked)
    return weighted / weights * (1 + relevance)


def select_sources(sources, states, batch_size, fair_key):
    fair = sorted(sources, key=fair_key)
    # At least one third of each batch follows oldest/unseen-first rotation.
    explore = max(1, (batch_size + 2) // 3)
    scored = sorted(sources, key=lambda s: (-source_score(states.get(s.id, {})), fair_key(s)))
    selected = [s for s in scored if source_score(states.get(s.id, {})) > 0][:max(0, batch_size - explore)]
    selected += [s for s in fair if s not in selected][:batch_size - len(selected)]
    return selected


def observation(kind, details):
    if kind == "direct_search":
        if not details.get("source_read_attempted"):
            return None
        return {"kind": kind, "at": datetime.now(UTC).isoformat(),
                "success": bool(details.get("source_read_success")),
                "details": details.get("output_count", 0),
                "duration_ms": details.get("read_duration_ms", details.get("duration_ms", 0))}
    if kind == "search_query":
        # Repeated but concrete details are still a healthy retrieval route.
        if "detail_count" not in details and not details.get("new_details") and details.get("duplicate_count"):
            return None  # Older traces cannot distinguish repeated jobs from entries.
        count = details.get("detail_count", details.get("new_details", 0))
        return {"kind": kind, "at": datetime.now(UTC).isoformat(),
                "success": not details.get("error_code") and count > 0,
                "details": count, "duration_ms": details.get("duration_ms", 0)}
    return None
