"""Persist recruitment batches, compare facts, and queue source checks."""
import hashlib
import re
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert

from src.domain.campaign import CampaignEvent, CampaignWatch, RecruitmentCampaign
from src.domain.search_goal import SearchGoal
from src.services.campaign_job_presence import job_observation
from src.services.campaign_parser import BATCH_LABELS, current_open_evidence
from src.services.company_registry import enabled_company_sources
from src.services.job_url import canonical_job_url


def utc(value):
    return value.replace(tzinfo=UTC) if value and value.tzinfo is None else value


def iso(value):
    return utc(value).isoformat() if value else None


def recently_checked(checked_at, now):
    try:
        checked = datetime.fromisoformat(checked_at) if isinstance(checked_at, str) else checked_at
        return bool(checked and timedelta(0) <= utc(now) - utc(checked) <= timedelta(hours=24))
    except (TypeError, ValueError):
        return False


def availability_check_time(facts, checked_at=None):
    """Use the age of the evidence supporting availability, not the latest page read."""
    checked = facts.get("availability_checked_at", checked_at)
    if facts.get("status") in {"closed", "upcoming"}:
        return checked
    if facts.get("status") in {"open", "announced"} and current_open_evidence(facts.get("status_quote", "")):
        return checked
    dates = [key for key in ("starts", "deadline") if facts.get(key)]
    if dates and "date_checked_at" in facts:
        times = [facts["date_checked_at"].get(key) for key in dates]
        return min(times) if all(times) else None
    return checked


def effective_status(facts, now, checked_at=None):
    today = now.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()
    if facts.get("status") == "closed":
        return "closed"
    if facts.get("deadline") and facts["deadline"]["value"] < today:
        return "closed"
    if facts.get("starts") and facts["starts"]["value"] > today:
        return "upcoming"
    if re.search(r"不再|暂停|暂不|尚未|暂未|未开放", facts.get("status_quote", "")):
        return "unknown"
    entry = facts.get("entry") or {}
    if entry.get("status") == "open" and recently_checked(entry.get("checked_at"), now):
        return "open"
    fresh = recently_checked(availability_check_time(facts, checked_at), now)
    if facts.get("status") in {"open", "announced"} and current_open_evidence(facts.get("status_quote", "")):
        return "open" if fresh else "unknown"
    # A complete official window is stronger than a model's missing state label.
    if facts.get("starts") and facts.get("deadline"):
        return "open" if fresh else "unknown"
    if facts.get("status") in {"open", "announced"}:
        # An explicit current state can confirm availability without published dates,
        # but expires after a day without a successful reread of the same source.
        # Launch announcement plus a still-valid deadline also confirms a window.
        if facts.get("deadline"):
            return "open" if fresh else "unknown"
        return "announced" if facts.get("status_quote") else "unknown"
    return facts.get("status", "unknown")


def campaign_sort_key(campaign):
    """Availability first; observation/update time never masquerades as opening time."""
    status, facts = campaign["status"], campaign["facts"]
    starts = facts.get("starts", None)
    published = facts.get("published", None)
    group = (0 if starts else 1) if status == "open" else {"upcoming": 2, "closed": 4}.get(status, 3)
    official_date = starts["value"] if starts else published["value"] if published else None
    # Upcoming applications open soonest first; all other official dates newest first.
    dated = datetime.fromisoformat(official_date).toordinal() if official_date else 0
    recency = dated if status == "upcoming" and starts else -dated
    first_seen = datetime.fromisoformat(campaign["first_seen_at"]).timestamp()
    return group, 0 if official_date else 1, recency, -first_seen, campaign["id"]


def default_year(session, user_id):
    goals = session.scalars(select(SearchGoal).where(SearchGoal.user_id == user_id)
                            .order_by(SearchGoal.updated_at.desc()))
    for goal in goals:
        years = goal.conditions.get("graduation_years", [])
        if len(years) == 1:
            return years[0]
    from src.domain.models import UserProfile
    profile = session.get(UserProfile, user_id)
    if profile and profile.graduation_year:
        return profile.graduation_year
    now = datetime.now(UTC).astimezone(ZoneInfo("Asia/Shanghai"))
    return now.year + (1 if now.month >= 6 else 0)


def watch_rows(session, user_id, year=None):
    statement = select(CampaignWatch).where(CampaignWatch.user_id == user_id)
    if year is not None:
        statement = statement.where(CampaignWatch.year == year)
    return list(session.scalars(statement))


def watch_payload(watch, source):
    return {"company_id": source.id, "company": source.company, "career_url": source.career_url,
            "followed": bool(watch and watch.followed), "status": watch.status if watch else "idle",
            "checked_at": iso(watch.checked_at) if watch else None,
            "succeeded_at": iso(watch.succeeded_at) if watch else None,
            "next_check_at": iso(watch.next_check_at) if watch else None,
            "error": watch.error if watch else None}


def campaign_payload(row, now):
    entry = row.facts.get("entry") or {}
    status = effective_status(row.facts, now, row.last_seen_at)
    entry_current = recently_checked(entry.get("checked_at"), now)
    checked_at = entry.get("checked_at") if entry.get("status") == "open" and entry_current else availability_check_time(row.facts, iso(row.last_seen_at))
    return {"id": row.id, "company_id": row.company_id, "company": row.company, "year": row.year,
            "title": row.title, "batch": row.batch, "batch_label": BATCH_LABELS[row.batch],
            "source_url": row.source_url, "facts": row.facts, "status": status,
            "cohort_status": row.facts.get("cohort_status", "confirmed" if row.facts.get("year_quote") else "unspecified"),
            "application_url": entry.get("url") if status == "open" and entry.get("status") == "open" and entry_current else None,
            "entry_url": entry.get("url"), "availability_checked_at": checked_at,
            "availability_stale": not recently_checked(checked_at, now),
            "availability_scope": entry.get("kind") if status == "open" and entry.get("status") == "open" and entry_current else "campaign",
            "first_seen_at": iso(row.first_seen_at), "last_seen_at": iso(row.last_seen_at),
            "changed_at": iso(row.changed_at)}


def company_card(source, watch, campaigns, year):
    """Visible campus jobs answer the company question; announcements are supplementary."""
    now = datetime.now(UTC)
    observations = [value for c in campaigns if (value := job_observation(c["facts"]))
                    and value["status"] == "found"]
    cached = (getattr(watch, "cache", None) or {}).get("job_check")
    if cached:
        observations.append(cached)
    check = max(observations, key=lambda value: value.get("checked_at") or "", default={})
    checked = check.get("checked_at")
    fresh = recently_checked(checked, now)
    failed = bool(watch and watch.status == "failed" and (iso(watch.checked_at) or "") >= (checked or ""))
    presence = check.get("status", "unknown") if fresh and not failed else "unknown"
    status = "open" if presence == "found" else "empty" if presence == "empty" else "unknown"
    evidence = [c for c in campaigns if (c["facts"].get("entry") or {}).get("job_presence") == "found"] or campaigns
    # Prefer an observed public campus portal, never promote a job URL to the company's main entrance.
    portals = [c["entry_url"] for c in evidence if c.get("entry_url")
               and (c["facts"].get("entry") or {}).get("kind") in {"project", "listing"}]
    confirmed = check.get("cohort_status") == "confirmed"
    dates = sorted(c["facts"]["starts"]["value"] for c in evidence if c["facts"].get("starts"))
    note = ("官网已发现校招岗位" if confirmed else "官网已发现校招岗位，届别未注明") if status == "open" else (
        "本次读取的校招列表暂无岗位" if status == "empty" else
        "岗位信息待重新检查" if checked and not fresh else
        "校招岗位待确认" if campaigns or watch else "尚未检查校招岗位")
    portal = check.get("recruitment_url") or (check.get("url") if check.get("kind") in {"listing", "project"} else None)
    return {**watch_payload(watch, source), "year": year, "recruitment_status": status,
            "status_note": note, "recruitment_url": portal or (portals[0] if portals else source.career_url),
            "cohort_status": "confirmed" if confirmed else "unspecified",
            "availability_checked_at": checked,
            "availability_stale": bool(checked and not fresh),
            "job_titles": check.get("job_titles", []) if status == "open" else [],
            "judgment_reason": check.get("reasoning", ""), "citations": check.get("citations", []),
            "first_seen_at": min((c["first_seen_at"] for c in campaigns), default=None),
            "opening_date": dates[0] if dates else None,
            "directions": list(dict.fromkeys(d for c in evidence for d in c["facts"]["directions"])),
            "evidence_ids": [c["id"] for c in campaigns], "evidence_count": len(campaigns)}


def campaign_snapshot(session, user_id, year=None):
    from src.services.campaign_discovery import discovery_summary
    now = datetime.now(UTC)
    year = year or default_year(session, user_id)
    sources = enabled_company_sources(session=session, user_id=user_id)
    watches = {w.company_id: w for w in watch_rows(session, user_id, year)} if year else {}
    rows = list(session.scalars(select(RecruitmentCampaign).where(
        RecruitmentCampaign.user_id == user_id, RecruitmentCampaign.year == year,
    ).order_by(RecruitmentCampaign.changed_at.desc(), RecruitmentCampaign.id))) if year else []
    ids = [row.id for row in rows]
    events = list(session.scalars(select(CampaignEvent).where(
        CampaignEvent.user_id == user_id, CampaignEvent.campaign_id.in_(ids),
    ).order_by(CampaignEvent.observed_at.desc(), CampaignEvent.id.desc()).limit(100))) if ids else []
    latest = {}
    for event in events:
        latest.setdefault(event.campaign_id, {"kind": event.kind, "at": iso(event.observed_at)})
    allowed = {s.id for s in sources}
    campaigns = [{**campaign_payload(r, now), "latest_event": latest.get(r.id)} for r in rows if r.company_id in allowed]
    campaigns.sort(key=campaign_sort_key)
    grouped = {}
    for campaign in campaigns:
        grouped.setdefault(campaign["company_id"], []).append(campaign)
    cards = [company_card(s, watches.get(s.id), grouped.get(s.id, []), year) for s in sources]
    cards.sort(key=lambda c: ({"open": 0, "upcoming": 1}.get(c["recruitment_status"], 2),
                              not bool(c["evidence_count"]), c["company"]))
    return {"year": year, "companies": [watch_payload(watches.get(s.id), s) for s in sources],
            "campaigns": campaigns, "company_cards": cards,
            "discovery": discovery_summary(session, user_id, year),
            "checked_at": iso(now)}


def ensure_watch(session, user_id, source_id, year):
    from src.domain.campaign import identifier
    session.execute(insert(CampaignWatch).values(id=identifier(), user_id=user_id, company_id=source_id,
        year=year, followed=False, status="idle", cache={}).on_conflict_do_nothing(
            index_elements=["user_id", "company_id", "year"]))
    return session.scalar(select(CampaignWatch).where(CampaignWatch.user_id == user_id,
        CampaignWatch.company_id == source_id, CampaignWatch.year == year))


def queue_checks(session, user_id, year, company_ids=None):
    sources = enabled_company_sources(company_ids, session=session, user_id=user_id)
    watches = {w.company_id: w for w in watch_rows(session, user_id, year)}
    if not company_ids:
        # Oldest/unseen sources first, so repeated updates do not check only big employers.
        sources.sort(key=lambda s: (utc(watches[s.id].checked_at) if s.id in watches and watches[s.id].checked_at
                                    else datetime.min.replace(tzinfo=UTC)))
        sources = [s for s in sources if s.id not in watches or watches[s.id].status not in {"queued", "running"}]
    for source in sources:
        watch = ensure_watch(session, user_id, source.id, year)
        if watch.status not in {"queued", "running"}:
            watch.status, watch.error = "queued", None
            watch.next_check_at = datetime.now(UTC)
    session.commit()


def set_followed(session, user_id, year, company_id, followed):
    enabled_company_sources([company_id], session=session, user_id=user_id)
    watch = ensure_watch(session, user_id, company_id, year)
    watch.followed = followed
    if followed:
        watch.next_check_at = datetime.now(UTC) if not watch.checked_at else datetime.now(UTC) + timedelta(hours=1)
    else:
        watch.next_check_at = None
    session.commit()


def save_campaign(session, user_id, source, facts, url, now):
    facts = {**facts}
    identity = hashlib.sha256(f"{facts['year']}|{facts['batch']}|{facts['title']}|{canonical_job_url(url)}".encode()).hexdigest()
    row = session.scalar(select(RecruitmentCampaign).where(RecruitmentCampaign.user_id == user_id,
        RecruitmentCampaign.company_id == source.id, RecruitmentCampaign.identity == identity))
    # Repeated announcements reached through another official URL share the same title.
    if row is None:
        row = session.scalar(select(RecruitmentCampaign).where(RecruitmentCampaign.user_id == user_id,
            RecruitmentCampaign.company_id == source.id, RecruitmentCampaign.year == facts["year"],
            RecruitmentCampaign.batch == facts["batch"], RecruitmentCampaign.title == facts["title"]))
    if row is None:
        same_page = list(session.scalars(select(RecruitmentCampaign).where(
            RecruitmentCampaign.user_id == user_id, RecruitmentCampaign.company_id == source.id,
            RecruitmentCampaign.year == facts["year"], RecruitmentCampaign.batch == facts["batch"],
            RecruitmentCampaign.source_url == url)))
        compatible = [r for r in same_page if (facts.get("partial") or r.facts.get("partial"))
                      and (r.title.startswith(facts["title"]) or facts["title"].startswith(r.title))]
        if len(compatible) == 1:
            row = compatible[0]
    previous = row.facts if row else None
    previous_status = (previous.get("observed_status") or effective_status(previous, utc(row.last_seen_at), row.last_seen_at)) if row else None
    if row and facts.get("partial") and not previous.get("partial"):
        # A provider outage is not evidence of a changed recruitment status.
        return row
    # Missing values may be retained for display, but must not renew old availability evidence.
    old_checked = (previous or {}).get("availability_checked_at", iso(row.last_seen_at) if row else None)
    observes_status = (facts.get("status") in {"closed", "upcoming"}
                       or bool(facts.get("starts") and facts.get("deadline"))
                       or facts.get("status") in {"open", "announced"} and (
                           current_open_evidence(facts.get("status_quote", "")) or bool(facts.get("deadline"))))
    facts["availability_checked_at"] = iso(now) if observes_status else old_checked
    facts["date_checked_at"] = {key: iso(now) if facts.get(key) else
        (previous or {}).get("date_checked_at", {}).get(key, old_checked)
        for key in ("starts", "deadline")}
    if row is None:
        facts["observed_status"] = effective_status(facts, now, now)
        row = RecruitmentCampaign(user_id=user_id, company_id=source.id, company=source.company,
            identity=identity, year=facts["year"], title=facts["title"], batch=facts["batch"], source_url=url,
            facts=facts, first_seen_at=now, last_seen_at=now, changed_at=now)
        session.add(row)
        session.flush()
    else:
        row.last_seen_at = now
        # Missing fields in a newer parse are not evidence that a deadline was removed.
        facts = {**facts, **{key: row.facts[key] for key in ("published", "starts", "deadline")
                            if not facts.get(key) and row.facts.get(key)}}
        if not facts.get("entry") and row.facts.get("entry"):
            facts["entry"] = row.facts["entry"]
        status = effective_status(facts, now, now)
        facts["observed_status"] = status
        lifecycle_changed = (status == "closed" and previous_status != "closed"
                             or status == "open" and previous_status in {"upcoming", "closed"})
        if fact_values(facts) == fact_values(row.facts) and not lifecycle_changed:
            row.facts = facts
            return row
        row.facts, row.title, row.changed_at = facts, facts["title"], now
        row.source_url = url
    kind = "first_seen"
    if previous is not None:
        kind = "updated"
        if (facts.get("deadline") or {}).get("value") != (previous.get("deadline") or {}).get("value"):
            kind = "deadline_changed"
        if facts["observed_status"] == "closed" and previous_status != "closed":
            kind = "closed"
        elif facts["observed_status"] == "open" and previous_status in {"upcoming", "closed"}:
            kind = "opened"
    session.add(CampaignEvent(user_id=user_id, campaign_id=row.id, kind=kind, observed_at=now,
        evidence={"url": url, "before": previous, "after": facts}))
    return row


def fact_values(facts):
    return {"title": facts["title"], "year": facts["year"], "batch": facts["batch"], "status": facts["status"],
            "directions": sorted(facts["directions"]), "cohort_status": facts.get("cohort_status"),
            "entry": {key: (facts.get("entry") or {}).get(key) for key in ("url", "status", "kind", "title", "job_presence", "job_titles")},
            **{key: facts[key]["value"] if facts.get(key) else None for key in ("published", "starts", "deadline")}}


def campaign_tracking(session, user_id):
    sources = {s.id: s for s in enabled_company_sources(session=session, user_id=user_id)}
    recent = {}
    for event, row in session.execute(select(CampaignEvent, RecruitmentCampaign).join(
        RecruitmentCampaign, RecruitmentCampaign.id == CampaignEvent.campaign_id).where(
            CampaignEvent.user_id == user_id, RecruitmentCampaign.user_id == user_id,
        ).order_by(CampaignEvent.observed_at.desc())):
        recent.setdefault((row.company_id, row.year), {"title": row.title, "kind": event.kind, "at": iso(event.observed_at)})
    return [{**watch_payload(w, sources[w.company_id]), "year": w.year,
             "latest_change": recent.get((w.company_id, w.year))}
            for w in watch_rows(session, user_id) if w.followed and w.company_id in sources]
