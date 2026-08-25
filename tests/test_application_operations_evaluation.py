from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from src.domain.application import Application
from src.domain.application_attempt import ApplicationAttempt, ApplicationBlocker
from src.domain.ats_assistance import AtsAssistanceSession
from src.evaluation.application_operations import summarize_application_operations


def test_application_operation_metrics_use_real_timestamps_and_interventions(
    db_session: Session,
) -> None:
    started = datetime(2026, 8, 25, 8, 0, tzinfo=UTC)
    db_session.add_all(
        [
            Application(
                id="application_metrics",
                candidate_job_id="candidate_metrics",
                status="PREPARING",
                created_at=started,
                updated_at=started,
            ),
            ApplicationAttempt(
                id="attempt_metrics_ready",
                user_id="metrics-owner",
                application_id="application_metrics",
                job_posting_id="job_metrics",
                packet_revision_id="revision_metrics",
                application_url="https://boards.greenhouse.io/example/jobs/1",
                status="READY_TO_SUBMIT",
                idempotency_key="metrics-ready",
                created_at=started + timedelta(seconds=60),
                updated_at=started + timedelta(seconds=300),
                ready_at=started + timedelta(seconds=300),
            ),
            ApplicationBlocker(
                id="blocker_metrics",
                user_id="metrics-owner",
                attempt_id="attempt_metrics_ready",
                application_id="application_metrics",
                category="ats_assistance",
                observation="Fixture handoff",
                stop_reason="User confirmation required",
                retryable=True,
                status="RESOLVED",
                idempotency_key="metrics-blocker",
                created_at=started + timedelta(seconds=100),
                updated_at=started + timedelta(seconds=200),
                resolved_at=started + timedelta(seconds=200),
            ),
            AtsAssistanceSession(
                id="ats_session_metrics",
                user_id="metrics-owner",
                attempt_id="attempt_metrics_ready",
                application_id="application_metrics",
                job_posting_id="job_metrics",
                packet_revision_id="revision_metrics",
                application_url="https://boards.greenhouse.io/example/jobs/1",
                provider="GREENHOUSE",
                status="READY_FOR_APPROVAL",
                page_fingerprint="a" * 64,
                plan_hash="b" * 64,
                field_plan=[],
                field_confirmations=[
                    {"field_key": "work_auth", "value_hash": "c" * 64},
                    {"field_key": "privacy", "value_hash": "d" * 64},
                ],
                handoff_reasons=[],
                final_summary={},
                inspected_at=started + timedelta(seconds=100),
                prepared_at=started + timedelta(seconds=300),
                created_at=started + timedelta(seconds=100),
                updated_at=started + timedelta(seconds=300),
            ),
        ]
    )
    db_session.commit()

    report = summarize_application_operations(db_session, user_id="metrics-owner")

    assert report["attempt_count"] == 1
    assert report["ready_attempt_count"] == 1
    assert report["ready_to_submit_seconds"]["values"] == [300.0]
    assert report["ready_to_submit_seconds"]["median"] == 300.0
    assert report["manual_interventions"] == {
        "blocker_count": 1,
        "sensitive_field_confirmation_count": 2,
        "total": 3,
    }
    assert report["submitted_receipt_coverage"] is None
