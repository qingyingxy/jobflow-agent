"""Private cursors and public coverage summaries for a saved goal version."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from src.domain.search_goal import SearchGoal
from src.services.verified_recruitment_entry import current_progress


def supports_direct_listing(source):
    """Admit official sources for capability detection, not guaranteed readability."""
    from urllib.parse import urlsplit

    from src.services.recruitment_trust import ATS_DOMAINS, hiring_scope

    parsed = urlsplit(source.career_url)
    host = parsed.hostname or ""
    if not source.enabled or parsed.scheme not in {"http", "https"} or not host or parsed.username:
        return False
    if any(host == root or host.endswith("." + root) for root in ATS_DOMAINS):
        return bool(hiring_scope(source.career_url)
                    and getattr(source, "official_homepage_url", None)
                    and getattr(source, "hiring_evidence_url", None))
    return True


def source_states(goal):
    state = goal.company_search_state or {}
    return state.get("sources", {}) if state.get("version") == goal.version else {}


def fresh_cursor(state):
    try:
        checked = datetime.fromisoformat(state["started_at"])
        return timedelta(0) <= datetime.now(UTC) - checked < timedelta(days=7)
    except (KeyError, TypeError, ValueError):
        return False


def fresh_search_profiles(state):
    """Keep observed search methods independently of a completed page cursor."""
    profiles = {}
    for url, profile in state.get("search_profiles", {}).items():
        try:
            age = datetime.now(UTC) - datetime.fromisoformat(profile["checked_at"])
            if timedelta(0) <= age < timedelta(days=30) and isinstance(profile.get("recipe"), dict):
                profiles[url] = deepcopy(profile)
        except (KeyError, TypeError, ValueError):
            continue
    return profiles


def progress_summaries(goal, session=None, *, current_matches=None):
    from src.services.company_registry import enabled_company_sources

    result = []
    for source in enabled_company_sources(goal.company_ids or None, session=session, user_id=goal.user_id):
        state = source_states(goal).get(source.id, {})
        status = state.get("status", "not_checked")
        stale = bool(state.get("started_at")) and not fresh_cursor(state)
        checked = set(state.get("checked_urls", []))
        pending = set(state.get("pending_candidates", {})) - checked
        remaining = {str(item.get("id")) for item in state.get("buffer", [])
                     if str(item.get("id")) not in set(state.get("seen_ids", [])) | checked}
        matched_count = len(state.get("matched_urls", []))
        if current_matches is not None:
            from src.services.job_url import canonical_job_url

            matched_count = sum(current_matches.get(canonical_job_url(url)) == "matched"
                                for url in set(state.get("checked_urls", [])))
        result.append({
            "source_id": source.id, "company": source.company,
            "official_url": source.career_url,
            "status": "stale" if stale else status,
            "matched_count": matched_count,
            "checked_count": len(state.get("checked_urls", [])),
            "pending_count": len(pending), "remaining_count": len(remaining),
            "pages_checked": state.get("pages_checked", 0),
            "strategy": state.get("strategy"),
            "search_attempts": state.get("search_attempts", 0),
            "last_attempt_at": state.get("last_attempt_at"),
            "reason": state.get("reason"), "updated_at": state.get("updated_at"),
            "can_continue": bool(state) and (
                state.get("strategy") == "web_search"
                or (supports_direct_listing(source) and state.get("strategy") == "official_listing"))
                and not stale and status in {"paused", "failed", "running"},
        })
    return result


class CompanyProgressStore:
    def __init__(self, session, *, user_id, goal_id, version):
        self.session, self.user_id, self.goal_id, self.version = session, user_id, goal_id, version

    def load(self):
        goal = self.session.get(SearchGoal, self.goal_id) if self.goal_id else None
        if not goal or goal.user_id != self.user_id or goal.version != self.version:
            return {}
        states = deepcopy(current_progress(goal.company_search_state or {}, self.version).get("sources", {}))
        missing = {key for key, value in states.items() if "performance" not in value}
        if missing:
            # Existing installations can immediately use recent observations;
            # goal/user/version isolation also applies to scheduling evidence.
            from src.domain.discovery import DiscoveryRun
            from src.services.source_performance import observation

            traces = list(self.session.scalars(select(DiscoveryRun.agent_trace).where(
                DiscoveryRun.user_id == self.user_id,
                DiscoveryRun.search_goal_id == self.goal_id,
                DiscoveryRun.search_goal_version == self.version,
                DiscoveryRun.finished_at.is_not(None),
                DiscoveryRun.started_at >= datetime.now(UTC) - timedelta(days=7),
            ).order_by(DiscoveryRun.started_at.desc()).limit(8)))
            for trace in reversed(traces):
                for event in trace or []:
                    details = event.get("details") or {}
                    key = details.get("source_id")
                    if key in missing and (sample := observation(event.get("tool"), details)):
                        sample["at"] = event.get("occurred_at") or sample["at"]
                        states[key]["performance"] = [*states[key].get("performance", []), sample][-12:]
        return states

    def load_verification(self):
        goal = self.session.get(SearchGoal, self.goal_id) if self.goal_id else None
        if not goal or goal.user_id != self.user_id or goal.version != self.version:
            return {}
        state = goal.company_search_state or {}
        return deepcopy(state.get("verification_sources", {})) if state.get("version") == self.version else {}

    def load_entries(self):
        goal = self.session.get(SearchGoal, self.goal_id) if self.goal_id else None
        if not goal or goal.user_id != self.user_id or goal.version != self.version:
            return {}
        state = goal.company_search_state or {}
        entries = state.get("entry_expansions", {}) if state.get("version") == self.version else {}
        cutoff = datetime.now(UTC) - timedelta(days=1)
        result = {}
        for url, entry in entries.items():
            try:
                checked = datetime.fromisoformat(entry["updated_at"])
                if checked.replace(tzinfo=checked.tzinfo or UTC) >= cutoff:
                    result[url] = deepcopy(entry)
            except (KeyError, TypeError, ValueError):
                continue
        return result

    def save_entry(self, url, state):
        if not self.goal_id:
            return
        current = self.session.scalar(select(SearchGoal.company_search_state).where(
            SearchGoal.id == self.goal_id, SearchGoal.user_id == self.user_id,
            SearchGoal.version == self.version,
        ))
        if current is None:
            return
        current = current_progress(current, self.version)
        entries = current.setdefault("entry_expansions", {})
        entries[url] = deepcopy(state)
        # Keep recent continuations bounded independently of company cursors.
        current["entry_expansions"] = dict(sorted(entries.items(),
            key=lambda item: item[1].get("updated_at", ""), reverse=True)[:100])
        self.session.execute(update(SearchGoal).where(
            SearchGoal.id == self.goal_id, SearchGoal.user_id == self.user_id,
            SearchGoal.version == self.version,
        ).values(company_search_state=current, updated_at=SearchGoal.updated_at))
        self.session.commit()

    def save_verification(self, source_id, state):
        if not self.goal_id:
            return
        current = self.session.scalar(select(SearchGoal.company_search_state).where(
            SearchGoal.id == self.goal_id, SearchGoal.user_id == self.user_id,
            SearchGoal.version == self.version,
        ))
        if current is None:
            return
        current = current_progress(current, self.version)
        sources = current.setdefault("verification_sources", {})
        if state:
            sources[source_id] = deepcopy(state)
        else:
            sources.pop(source_id, None)
        self.session.execute(update(SearchGoal).where(
            SearchGoal.id == self.goal_id, SearchGoal.user_id == self.user_id,
            SearchGoal.version == self.version,
        ).values(company_search_state=current, updated_at=SearchGoal.updated_at))
        self.session.commit()

    def save(self, source_id, state):
        if not self.goal_id:
            return
        # Read the current JSON so concurrent company workers preserve each other.
        current = self.session.scalar(select(SearchGoal.company_search_state).where(
            SearchGoal.id == self.goal_id, SearchGoal.user_id == self.user_id,
            SearchGoal.version == self.version,
        ))
        if current is None:
            return
        current = current_progress(current, self.version)
        sources = dict(current.get("sources", {}))
        sources[source_id] = deepcopy(state)
        self.session.execute(update(SearchGoal).where(
            SearchGoal.id == self.goal_id, SearchGoal.user_id == self.user_id,
            SearchGoal.version == self.version,
        ).values(company_search_state={**current, "sources": sources},
                 updated_at=SearchGoal.updated_at))
        self.session.commit()
