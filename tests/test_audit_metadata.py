from datetime import UTC, datetime

from sqlalchemy.orm import Session

from src.domain.application import DomainEvent
from src.services.audit_metadata import audit_sensitive_metadata


def test_audit_metadata_reports_paths_without_repeating_private_values(
    db_session: Session,
) -> None:
    db_session.add_all(
        [
            DomainEvent(
                id="event_audit_safe",
                user_id="audit-owner",
                entity_type="Application",
                entity_id="application_audit",
                event_type="SafeEvent",
                payload={"attempt_id": "attempt_audit", "status": "READY"},
                created_at=datetime.now(UTC),
            ),
            DomainEvent(
                id="event_audit_unsafe",
                user_id="audit-owner",
                entity_type="Application",
                entity_id="application_audit",
                event_type="UnsafeFixtureEvent",
                payload={
                    "confirmation_text": "submitted",
                    "nested": {"value": "private-person@example.com"},
                },
                created_at=datetime.now(UTC),
            ),
        ]
    )
    db_session.commit()

    findings = audit_sensitive_metadata(db_session, user_id="audit-owner")
    serialized = " ".join(
        f"{item.source_id} {item.path} {item.reason}" for item in findings
    )

    assert len(findings) == 2
    assert "payload.confirmation_text" in serialized
    assert "payload.nested.value" in serialized
    assert "private-person@example.com" not in serialized
    assert all(item.source_id == "event_audit_unsafe" for item in findings)


def test_audit_metadata_does_not_treat_numeric_ids_as_phone_numbers(
    db_session: Session,
) -> None:
    db_session.add(
        DomainEvent(
            id="event_audit_identifier",
            user_id="audit-owner",
            entity_type="JobPosting",
            entity_id="13800138000",
            event_type="JobSelected",
            payload={
                "job_posting_id": "13800138000",
                "related_ids": ["13900139000"],
                "note": "Call 13700137000 before the interview",
            },
            created_at=datetime.now(UTC),
        )
    )
    db_session.commit()

    findings = audit_sensitive_metadata(db_session, user_id="audit-owner")

    assert [(item.path, item.reason) for item in findings] == [
        ("payload.note", "phone")
    ]
