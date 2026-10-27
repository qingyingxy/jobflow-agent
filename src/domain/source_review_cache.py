"""Source judgments are scoped by evidence, conditions and interpreter version."""

from datetime import UTC, datetime

REVIEW_MAPS = {
    "source_understanding": "source_understandings",
    "source_review_attempt": "source_review_attempts",
}
REVIEW_KEYS = (*REVIEW_MAPS, *REVIEW_MAPS.values(), "understanding_policy",
               "qualification_understanding", "qualification_review_attempt", "work_location_understanding")


def records(context, kind):
    context = context or {}
    saved = context.get(REVIEW_MAPS[kind])
    values = {key: value for key, value in saved.items()
              if isinstance(value, dict) and value.get("fingerprint") == key} if isinstance(saved, dict) else {}
    # Read old databases without an eager migration or another model call.
    legacy = context.get(kind)
    legacy = legacy if isinstance(legacy, dict) else {}
    key = legacy.get("fingerprint")
    if key and legacy.get("saved_at", "") >= values.get(key, {}).get("saved_at", ""):
        values[key] = legacy
    return values


def put_record(context, kind, record):
    values = records(context, kind)
    record = {**record, "saved_at": datetime.now(UTC).isoformat()}
    values[record["fingerprint"]] = record
    # The single record remains a compatibility view, never the only cache.
    return {**(context or {}), REVIEW_MAPS[kind]: values, kind: record}


def merge_context(stored, incoming, original=None):
    """Merge delayed checkpoints without losing another target's newer work."""
    stored, incoming = stored or {}, incoming or {}
    result = dict(incoming)
    if original is not None:
        for key in REVIEW_KEYS:
            if incoming.get(key) == (original or {}).get(key) and key in stored:
                result[key] = stored[key]
    for kind, map_key in REVIEW_MAPS.items():
        merged = records(stored, kind)
        for key, record in records(result, kind).items():
            if key not in merged or record.get("saved_at", "") >= merged[key].get("saved_at", ""):
                merged[key] = record
        if merged:
            result[map_key] = merged
    return result
