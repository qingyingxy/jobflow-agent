from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from src.config import get_settings
from src.domain.application import Application
from src.domain.application_attempt import (
    ApplicationAttempt,
    ApplicationBlocker,
    SubmissionReceipt,
)
from src.domain.ats_assistance import AtsAssistanceSession


def summarize_application_operations(
    session: Session,
    *,
    user_id: str,
) -> dict[str, Any]:
    rows = session.execute(
        select(
            ApplicationAttempt.id,
            Application.created_at,
            ApplicationAttempt.ready_at,
        )
        .join(Application, Application.id == ApplicationAttempt.application_id)
        .where(ApplicationAttempt.user_id == user_id)
        .order_by(ApplicationAttempt.created_at, ApplicationAttempt.id)
    ).all()
    ready_durations = sorted(
        _duration_seconds(application_created_at, ready_at)
        for _, application_created_at, ready_at in rows
        if ready_at is not None
    )
    blocker_count = int(
        session.scalar(
            select(func.count(ApplicationBlocker.id)).where(
                ApplicationBlocker.user_id == user_id
            )
        )
        or 0
    )
    sessions = list(
        session.scalars(
            select(AtsAssistanceSession).where(
                AtsAssistanceSession.user_id == user_id
            )
        ).all()
    )
    field_confirmation_count = sum(
        len(item.field_confirmations or []) for item in sessions
    )
    receipt_count = int(
        session.scalar(
            select(func.count(SubmissionReceipt.id)).where(
                SubmissionReceipt.user_id == user_id,
                SubmissionReceipt.is_valid.is_(True),
            )
        )
        or 0
    )
    submitted_count = int(
        session.scalar(
            select(func.count(ApplicationAttempt.id)).where(
                ApplicationAttempt.user_id == user_id,
                ApplicationAttempt.status == "SUBMITTED",
            )
        )
        or 0
    )
    return {
        "scope": {
            "user_id": user_id,
            "duration_start": "application_created_at",
            "duration_end": "attempt_ready_at",
            "includes_fixture_data": False,
        },
        "attempt_count": len(rows),
        "ready_attempt_count": len(ready_durations),
        "ready_to_submit_seconds": {
            "values": ready_durations,
            "median": median(ready_durations) if ready_durations else None,
            "p95": _percentile(ready_durations, 0.95),
        },
        "manual_interventions": {
            "blocker_count": blocker_count,
            "sensitive_field_confirmation_count": field_confirmation_count,
            "total": blocker_count + field_confirmation_count,
        },
        "submitted_attempt_count": submitted_count,
        "valid_receipt_count": receipt_count,
        "submitted_receipt_coverage": (
            receipt_count / submitted_count if submitted_count else None
        ),
    }


def _duration_seconds(started_at: datetime, finished_at: datetime) -> float:
    if started_at.tzinfo is None and finished_at.tzinfo is not None:
        finished_at = finished_at.replace(tzinfo=None)
    elif started_at.tzinfo is not None and finished_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=None)
    return max(0.0, (finished_at - started_at).total_seconds())


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    position = (len(values) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    fraction = position - lower
    return values[lower] + (values[upper] - values[lower]) * fraction


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Summarize real application readiness and intervention metrics"
    )
    parser.add_argument("--database-url", default=get_settings().database_url)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--output")
    return parser.parse_args()


def main() -> None:
    arguments = _parse_args()
    engine = create_engine(arguments.database_url, pool_pre_ping=True)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    try:
        with factory() as session:
            report = summarize_application_operations(
                session,
                user_id=arguments.user_id,
            )
    finally:
        engine.dispose()
    serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if arguments.output:
        output_path = Path(arguments.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)


if __name__ == "__main__":
    main()
