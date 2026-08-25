from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.domain.application import DomainEvent
from src.domain.discovery import DiscoveryRun

_SENSITIVE_KEY_MARKERS = (
    "answer",
    "application_number",
    "authorization_token",
    "confirmation_text",
    "contact_email",
    "contact_phone",
    "password",
    "resume_body",
    "salary_strategy",
    "screenshot_metadata",
    "storage_key",
    "token_hash",
)
_SENSITIVE_VALUE_PATTERNS = (
    ("email", re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")),
    ("phone", re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)")),
    ("bearer_token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}")),
)


@dataclass(frozen=True)
class AuditMetadataFinding:
    source_type: str
    source_id: str
    path: str
    reason: str


def audit_sensitive_metadata(
    session: Session,
    *,
    user_id: str | None = None,
) -> list[AuditMetadataFinding]:
    findings: list[AuditMetadataFinding] = []
    event_query = select(DomainEvent)
    discovery_query = select(DiscoveryRun)
    if user_id is not None:
        event_query = event_query.where(DomainEvent.user_id == user_id)
        discovery_query = discovery_query.where(DiscoveryRun.user_id == user_id)
    for event in session.scalars(event_query).all():
        findings.extend(
            _scan_value(
                event.payload,
                source_type="domain_event",
                source_id=event.id,
                path="payload",
            )
        )
    for run in session.scalars(discovery_query).all():
        findings.extend(
            _scan_value(
                run.agent_trace,
                source_type="discovery_trace",
                source_id=run.id,
                path="agent_trace",
            )
        )
    return findings


def _scan_value(
    value: Any,
    *,
    source_type: str,
    source_id: str,
    path: str,
) -> list[AuditMetadataFinding]:
    findings: list[AuditMetadataFinding] = []
    if isinstance(value, dict):
        for key, item in value.items():
            item_path = f"{path}.{key}"
            normalized_key = str(key).strip().casefold()
            if any(marker in normalized_key for marker in _SENSITIVE_KEY_MARKERS):
                findings.append(
                    AuditMetadataFinding(
                        source_type=source_type,
                        source_id=source_id,
                        path=item_path,
                        reason="sensitive_key",
                    )
                )
                continue
            findings.extend(
                _scan_value(
                    item,
                    source_type=source_type,
                    source_id=source_id,
                    path=item_path,
                )
            )
    elif isinstance(value, list):
        for index, item in enumerate(value):
            findings.extend(
                _scan_value(
                    item,
                    source_type=source_type,
                    source_id=source_id,
                    path=f"{path}[{index}]",
                )
            )
    elif isinstance(value, str):
        for reason, pattern in _SENSITIVE_VALUE_PATTERNS:
            if reason == "phone" and _is_identifier_path(path):
                continue
            if pattern.search(value):
                findings.append(
                    AuditMetadataFinding(
                        source_type=source_type,
                        source_id=source_id,
                        path=path,
                        reason=reason,
                    )
                )
    return findings


def _is_identifier_path(path: str) -> bool:
    leaf = path.rsplit(".", 1)[-1].split("[", 1)[0].casefold()
    return leaf == "id" or leaf.endswith(("_id", "_ids"))
