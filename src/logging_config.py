from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime

_REDACTION_PATTERNS = (
    (
        re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"),
        "Bearer [REDACTED]",
    ),
    (
        re.compile(
            r"(?i)\b(api[_-]?key|authorization|password|secret|token)"
            r"\s*[:=]\s*([^\s,;]+)"
        ),
        r"\1=[REDACTED]",
    ),
    (
        re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"),
        "[REDACTED_EMAIL]",
    ),
    (
        re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)"),
        "[REDACTED_PHONE]",
    ),
)


def redact_log_text(value: str) -> str:
    redacted = value
    for pattern, replacement in _REDACTION_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


class JsonFormatter(logging.Formatter):
    """Render application logs as one JSON object per line."""

    _extra_fields = ("request_id", "method", "path", "status_code", "duration_ms")

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_log_text(record.getMessage()),
        }
        for field in self._extra_fields:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = redact_log_text(
                self.formatException(record.exc_info)
            )
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str) -> None:
    """Configure predictable JSON logs for local runs and deployed services."""

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(
        level=level.upper(),
        handlers=[handler],
        force=True,
    )
