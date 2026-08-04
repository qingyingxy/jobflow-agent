from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.domain.runs import AgentRun


def summarize_agent_runs(
    session: Session,
    *,
    user_id: str | None = None,
    run_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Summarize persisted AgentRun rows without exposing their payloads."""

    statement = select(AgentRun).order_by(AgentRun.started_at, AgentRun.id)
    if user_id is not None:
        statement = statement.where(AgentRun.user_id == user_id)
    if run_ids is not None:
        if not run_ids:
            return _empty_summary()
        statement = statement.where(AgentRun.id.in_(run_ids))

    runs = list(session.scalars(statement).all())
    durations = [run.duration_ms for run in runs if run.duration_ms is not None]
    failure_codes = Counter(
        code
        for run in runs
        for code in [_failure_code(run)]
        if code is not None
    )
    return {
        "count": len(runs),
        "succeeded_count": sum(run.status == "succeeded" for run in runs),
        "failed_count": sum(run.status == "failed" for run in runs),
        "validation_passed_count": sum(
            run.validation_status == "passed" for run in runs
        ),
        "validation_failed_count": sum(
            run.validation_status == "failed" for run in runs
        ),
        "run_types": _counts(run.run_type for run in runs),
        "models": sorted({run.model for run in runs}),
        "prompt_versions": sorted({run.prompt_version for run in runs}),
        "failure_codes": dict(sorted(failure_codes.items())),
        "duration_ms": {
            "count": len(durations),
            "average": _average(durations),
            "minimum": min(durations) if durations else None,
            "maximum": max(durations) if durations else None,
        },
    }


def _empty_summary() -> dict[str, Any]:
    return {
        "count": 0,
        "succeeded_count": 0,
        "failed_count": 0,
        "validation_passed_count": 0,
        "validation_failed_count": 0,
        "run_types": {},
        "models": [],
        "prompt_versions": [],
        "failure_codes": {},
        "duration_ms": {
            "count": 0,
            "average": None,
            "minimum": None,
            "maximum": None,
        },
    }


def _failure_code(run: AgentRun) -> str | None:
    if isinstance(run.validation_result, dict):
        code = run.validation_result.get("code")
        if isinstance(code, str) and code:
            return code
    return None


def _counts(values: Any) -> dict[str, int]:
    return dict(sorted(Counter(values).items()))


def _average(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None
