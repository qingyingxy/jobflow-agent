"""Durable retry decisions for reads; scheduling never establishes job facts."""

from datetime import UTC, datetime, timedelta

SOURCE_FAILURES = frozenset({
    "url_fetch_failed", "url_fetch_timeout", "source_timeout", "source_server_error",
    "source_rate_limited", "browser_timeout", "browser_read_failed", "verification_timeout",
    "browser_body_incomplete",
})
DEFERRED = frozenset({
    "verification_budget_exhausted", "verification_cancelled", "verification_queue_full",
    "source_circuit_open", "company_target", "company_read_limit", "search_reference_deferred", "semantic_page_pending", "company_paused",
    "entry_budget", "entry_no_progress", "entry_cooldown", "entry_duplicate", "recruitment_entry_page",
})
BROWSER_FALLBACK = frozenset({"lead_requires_browser", "job_detail_unconfirmed", "page_body_incomplete"})
MANUAL = frozenset({
    "browser_login_required", "browser_captcha_required", "browser_2fa_required",
    "browser_security_challenge", "official_source_unconfirmed", "entry_source_unconfirmed",
    "source_forbidden", "unsafe_url",
})
STOPPED = frozenset({"job_closed", "lead_not_job_page", "source_not_found"})
PAGE_FAILURES = frozenset({
    "browser_job_page_unverified", "visual_extraction_unverified", "job_detail_unconfirmed",
    "lead_not_job_page", "job_closed", "source_not_found",
})


def utc_time(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value.replace(tzinfo=UTC) if value and value.tzinfo is None else value


def failed_state(state, code, *, now=None):
    now = utc_time(now) or datetime.now(UTC)
    state = dict(state or {})
    if code in DEFERRED:
        state["last_outcome"] = code
        state.setdefault("mode", "ready")
        return state
    state.update(last_outcome=code, next_retry_at=None)
    if not code:
        # Pausing a queued/interrupted read does not consume a retry.
        state["mode"] = "ready"
    elif code in BROWSER_FALLBACK:
        exhausted = state.get("next_method") == "browser"
        state.update(mode="needs_adapter" if exhausted else "ready",
                     next_method="browser", last_failure_code=code)
    else:
        state.update(last_failure_code=code, last_failure_at=now.isoformat())
        if code in SOURCE_FAILURES:
            count = state.get("transient_failures", 0) + 1
            state.update(transient_failures=count, mode="exhausted" if count >= 3 else "cooldown")
            if count < 3:
                state["next_retry_at"] = (now + timedelta(seconds=60 if count == 1 else 300)).isoformat()
        elif code in MANUAL:
            state["mode"] = "manual"
        elif code in STOPPED:
            state["mode"] = "stopped"
        else:
            state["mode"] = "needs_adapter"
    return state


def lead_state(lead):
    if lead.retry_state:
        state = dict(lead.retry_state)
        if lead.status in {"CLOSED", "REJECTED_NON_JOB"}:
            state["mode"] = "stopped"
        return state
    # Existing rows retain their original evidence; infer a conservative first attempt.
    state = {"queued_at": utc_time(lead.discovered_at).isoformat()}
    if lead.failure_code:
        state = failed_state(state, lead.failure_code, now=lead.updated_at or lead.discovered_at)
        if lead.failure_code.startswith("browser_") or lead.failure_code == "visual_extraction_unverified":
            state.update(methods=["http", "browser"], next_method="browser")
    elif lead.status in {"CLOSED", "REJECTED_NON_JOB"}:
        state["mode"] = "stopped"
    elif lead.status == "NEEDS_USER":
        state["mode"] = "manual"
    elif lead.status == "NEEDS_BROWSER":
        state.update(mode="ready", next_method="browser")
    return state


def can_retry(state, *, now=None):
    if state.get("mode") in {"manual", "stopped", "needs_adapter", "exhausted"}:
        return False
    due = utc_time(state.get("next_retry_at"))
    return not due or due <= (utc_time(now) or datetime.now(UTC))


def retry_message(state):
    return {
        "cooldown": "暂缓自动重试，到期后随下一次搜索继续",
        "exhausted": "已达到自动重试上限，可手动重新核验",
        "manual": "需要确认来源或人工处理后再核验",
        "needs_adapter": "页面读取方式需要适配，已暂停自动重试",
        "stopped": "已停止自动重试",
    }.get(state.get("mode"), "已保留进度，下次搜索继续核验")


def mark_method(lead, method):
    state = lead_state(lead)
    state.update(
        attempts=state.get("attempts", 0) + 1,
        methods=list(dict.fromkeys([*state.get("methods", []), method])),
        next_method=method, last_attempt_at=datetime.now(UTC).isoformat(),
    )
    lead.retry_state = state


def mark_success(lead):
    lead.retry_state = {**lead_state(lead), "mode": "succeeded", "transient_failures": 0,
                        "next_retry_at": None, "last_outcome": "verified"}


def prior_retry_state(session, *, run, normalized_url):
    from sqlalchemy import select

    from src.domain.discovery import DiscoveryRun, JobLead

    if not run.search_goal_id:
        return {}
    previous = session.scalar(select(JobLead).join(DiscoveryRun, DiscoveryRun.id == JobLead.discovery_run_id)
        .where(JobLead.user_id == run.user_id, DiscoveryRun.user_id == run.user_id,
               DiscoveryRun.search_goal_id == run.search_goal_id,
               DiscoveryRun.search_goal_version == run.search_goal_version,
               JobLead.discovery_run_id != run.id, JobLead.normalized_url == normalized_url)
        .order_by(DiscoveryRun.started_at.desc(), JobLead.created_at.desc(), JobLead.id.desc()).limit(1))
    return parser_retry_state(session, previous) if previous else {}


def parser_retry_state(session, lead):
    """A parser upgrade may schedule one fresh read of a previously unreadable DOM."""
    from sqlalchemy import select

    from src.domain.discovery import LeadVerification
    from src.services.discovery_sources import looks_like_job_page
    from src.services.job_detail_scope import EXTRACTOR_VERSION
    from src.services.job_lead_service import _readable_page_document
    from src.services.job_url import canonical_job_url

    state = lead_state(lead)
    if (state.get('mode') != 'needs_adapter'
            or state.get('last_failure_code') not in {'job_detail_unconfirmed', 'browser_job_page_unverified', 'visual_extraction_unverified'}
            or state.get('structure_retry_version') == EXTRACTOR_VERSION
            or lead.selection_status == 'IGNORED'):
        return state
    snapshots = session.scalars(select(LeadVerification).where(
        LeadVerification.user_id == lead.user_id, LeadVerification.lead_id == lead.id,
        LeadVerification.result == 'SNAPSHOT', LeadVerification.source_type.in_(['browser_snapshot', 'http_snapshot']),
    ).order_by(LeadVerification.checked_at.desc(), LeadVerification.id.desc()).limit(8))
    for snapshot in snapshots:
        if canonical_job_url(snapshot.source_url) != lead.normalized_url:
            continue
        evidence = snapshot.field_evidence or {}
        if evidence.get('extractor') == EXTRACTOR_VERSION:
            return state
        html = evidence.get('raw_html')
        if not isinstance(html, str) or not html:
            continue
        document, scoped = _readable_page_document(html, snapshot.source_url)
        if scoped and looks_like_job_page(document, url=snapshot.source_url):
            return {**state, 'mode': 'ready', 'next_method': 'browser', 'next_retry_at': None,
                    'structure_retry_version': EXTRACTOR_VERSION, 'structure_retry_snapshot_id': snapshot.id}
        return state
    return state
