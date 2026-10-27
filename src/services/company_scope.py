"""Apply an explicitly selected employer scope to retrieval and presentation."""
from urllib.parse import urlsplit

from src.services.company_registry import enabled_company_sources, within_company_source
from src.services.recruitment_trust import hiring_scope


def in_company_scope(item, sources):
    if sources is None:
        return True
    url = getattr(item, "source_url", None) or getattr(item, "detail_url", "") or ""
    company = getattr(item, "company", None) or getattr(item, "company_hint", None)
    source_id = getattr(item, "source_id", None)
    for source in sources:
        if within_company_source(url, source):
            return True
        # Two employers on the same ATS host remain different tenants, even
        # when a search snippet supplies the wrong company name.
        tenant = hiring_scope(source.career_url)
        if tenant and urlsplit(url).hostname == tenant[0]:
            continue
        if source_id in {source.id, f"official:{source.id}"} or (
            company and company.strip().casefold() == source.company.strip().casefold()
        ):
            return True
    return False


def goal_company_sources(session, goal):
    if not goal.company_ids:
        return None
    return [s for s in enabled_company_sources(session=session, user_id=goal.user_id)
            if s.id in goal.company_ids]


def run_company_sources(session, run):
    # Preserve the scope at search time, including after the goal is edited.
    trace = next((s for s in run.agent_trace or [] if s.get("tool") == "query_plan"), None)
    ids = (trace.get("details") or {}).get("company_ids") if trace else None
    if trace is None and run.search_goal_id:
        from src.domain.search_goal import SearchGoal

        goal = session.get(SearchGoal, run.search_goal_id)
        if goal and goal.user_id == run.user_id and goal.version == run.search_goal_version:
            ids = goal.company_ids
    if not ids:
        return None
    return [s for s in enabled_company_sources(session=session, user_id=run.user_id) if s.id in ids]
