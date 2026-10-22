"""Durable, bounded interpretation attempts for bodies not yet parsed as jobs."""

import hashlib
import json
from datetime import UTC, datetime

from src.services.semantic_retry import failed_attempt, retry_at
from src.services.source_understanding import VERSION


def page_fingerprint(snapshot, conditions):
    from src.domain.search_goal import SearchGoalConditions
    conditions = SearchGoalConditions.model_validate(conditions).model_dump()
    return hashlib.sha256(json.dumps([VERSION, snapshot.source_url,
        snapshot.field_evidence.get("raw_html", ""), conditions],
        ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def page_attempt(snapshot, conditions):
    previous = snapshot.field_evidence.get("page_review_attempt", {})
    key = page_fingerprint(snapshot, conditions)
    return previous if previous.get("fingerprint") == key else {"fingerprint": key, "failures": 0}


def save_page_attempt(snapshot, conditions, *, error=None, started=False):
    previous = page_attempt(snapshot, conditions)
    now = datetime.now(UTC)
    failure = failed_attempt(error)
    failures = previous.get("failures", 0) + int(failure)
    if not started and error is None:
        failures = 0
    attempt = {**previous, "version": VERSION, "attempted_at": now.isoformat(),
        "queued_at": previous.get("queued_at") or now.isoformat(),
        "error_code": "semantic_pending" if started else error,
        "failures": failures, "next_retry_at":
        retry_at(error, failures, now)}
    snapshot.field_evidence = {**snapshot.field_evidence, "ai_reading_pending": bool(started or error),
        "page_review_attempt": attempt}
    return attempt
