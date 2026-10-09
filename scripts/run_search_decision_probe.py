"""Live bounded search probe, using a fresh database and shared query candidates.

Run each mode in a separate process/directory. No network or model mocks are used.
This measures search and source verification, without downstream JD analysis.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from urllib.parse import urlsplit


def token_summary(usages):
    """Missing provider usage stays unknown; it must not appear as zero cost."""
    available = [item for item in usages if isinstance(item, dict) and item]
    return {
        "calls": len(usages),
        "calls_with_usage": len(available),
        "input_tokens": sum(
            u.get("input_tokens", u.get("prompt_tokens", 0)) or 0 for u in available
        )
        if available
        else None,
        "output_tokens": sum(
            u.get("output_tokens", u.get("completion_tokens", 0)) or 0
            for u in available
        )
        if available
        else None,
        "monetary_cost": None,
    }


async def run(args, directory):
    # Configure before importing application models or the database engine.
    overrides = {
        "DATABASE_URL": f"sqlite:///{(directory / 'probe.db').as_posix()}",
        "LOG_LEVEL": "WARNING",
        "WEB_SEARCH_DECISION_MODE": args.mode,
        "WEB_SEARCH_MAX_ROUNDS": args.rounds,
        "WEB_SEARCH_BUDGET_SECONDS": args.search_seconds,
        "WEB_SEARCH_TARGET_JOBS": 3,
        "WEB_SEARCH_VERIFICATION_BUDGET_SECONDS": 45,
        "WEB_SEARCH_VERIFICATION_ITEM_SECONDS": 15,
        "WEB_SEARCH_ENTRY_LIMIT": 2,
        "WEB_SEARCH_ENTRY_MAX_PAGES": 2,
        "WEB_SEARCH_DECISION_MAX_CALLS": 3,
        "WEB_SEARCH_DECISION_TIMEOUT_SECONDS": 12,
        "LLM_TIMEOUT_SECONDS": 60,
        "LLM_MAX_RETRIES": 0,
    }
    os.environ.update({key: str(value) for key, value in overrides.items()})
    from sqlalchemy import select

    from src.config import get_settings
    from src.domain.discovery import DiscoveryRun, JobLead, SearchEvidence
    from src.domain.job import JobPosting
    from src.infrastructure.database import Base, SessionLocal, engine
    from src.main import app  # noqa: F401 - register all ORM tables
    from src.services.company_registry import enabled_company_sources
    from src.services.multiround_search import execute_multiround_search
    from src.services.search_planner import build_agent_search_tasks

    settings = get_settings()
    if settings.structured_model_provider == "fake":
        raise RuntimeError("A live probe requires a configured real model")
    tasks = build_agent_search_tasks(
        args.query, enabled_company_sources(args.company_ids or None)
    )
    Base.metadata.create_all(engine)
    started = monotonic()
    with SessionLocal() as session:
        discovery = DiscoveryRun(
            id="search-decision-probe",
            user_id="probe-user",
            source="live-search-probe",
            source_url="probe://bounded-search",
            search_query=args.query,
            started_at=datetime.now(UTC),
        )
        session.add(discovery)
        session.commit()

    metadata = {
        "started_at": datetime.now(UTC).isoformat(),
        "mode": args.mode,
        "query": args.query,
        "company_ids": args.company_ids,
        "model": settings.llm_model,
        "model_host": urlsplit(settings.llm_base_url or "").hostname,
        "search_provider": settings.web_search_provider,
        "query_candidates": [{"query": t.query, "strategy": t.strategy} for t in tasks],
        "budgets": {
            k: v for k, v in overrides.items() if k not in {"DATABASE_URL", "LOG_LEVEL"}
        },
        "feedback_wait_seconds": 1,
        "analysis_limit": 0,
        "network_and_model_mocks": False,
        "limitations": [
            "Single live sample, sequential modes; web results can change between runs.",
            "Both modes share agent-safe query candidates and verification feedback wait.",
            "Useful/strict counts are workflow heuristics, not a verified 2027 cohort match.",
            "Provider-reported tokens only; monetary and hosted web-search charges unknown.",
        ],
    }
    (directory / "config.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    task = asyncio.create_task(
        execute_multiround_search(
            run_id="search-decision-probe",
            user_id="probe-user",
            query=args.query,
            company_ids=args.company_ids,
            query_tasks=tasks,
            analysis_limit=0,
            feedback_wait_seconds=1,
        )
    )
    shown = 0
    while not task.done():
        await asyncio.wait({task}, timeout=2)
        with SessionLocal() as session:
            discovery = session.get(DiscoveryRun, "search-decision-probe")
            trace = discovery.agent_trace or []
            for step in trace[shown:]:
                if step.get("tool") in {
                    "search_query",
                    "search_decision",
                    "search_decision_fallback",
                    "search_pause",
                    "search_resume",
                }:
                    print(
                        json.dumps(
                            {
                                "elapsed_seconds": round(monotonic() - started, 1),
                                "tool": step["tool"],
                                "error": step.get("error_code"),
                                "observation": step.get("observation"),
                                "decision": step.get("decision"),
                            },
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )
            shown = len(trace)
    execution_error = None
    try:
        await task
    except Exception as error:  # noqa: BLE001 - export partial evidence on failure
        execution_error = type(error).__name__

    with SessionLocal() as session:
        discovery = session.get(DiscoveryRun, "search-decision-probe")
        evidence = list(session.scalars(select(SearchEvidence)))
        leads = list(session.scalars(select(JobLead)))
        jobs = list(session.scalars(select(JobPosting)))
        trace = discovery.agent_trace or []
        decisions = [s for s in trace if s.get("tool") == "search_decision"]
        stop = next((s for s in reversed(trace) if s.get("phase") == "stop"), {})
        outputs = sum(e.details.get("output_count", 0) for e in evidence)
        duplicates = sum(e.details.get("duplicate_count", 0) for e in evidence)
        searches = []
        search_usage = []
        for e in evidence:
            try:
                raw = json.loads(e.raw_response or "{}")
            except ValueError:
                raw = {}
            usage = raw.get("usage") if isinstance(raw, dict) else None
            search_usage.append(usage)
            searches.append(
                {
                    "query": e.query,
                    "status": e.status,
                    "details": e.details,
                    "usage": usage,
                }
            )
        metrics = {
            "elapsed_seconds": round(monotonic() - started, 2),
            "execution_error": execution_error,
            "search_calls": len(evidence),
            "successful_search_calls": sum(e.status == "COMPLETED" for e in evidence),
            "unique_leads": len(leads),
            "unique_search_links": sum(e.details.get("new_links", 0) for e in evidence),
            "returned_links": outputs,
            "duplicate_ratio": round(duplicates / outputs, 4) if outputs else None,
            "verified_jobs": len(jobs),
            "workflow_useful_jobs": stop.get("details", {}).get("useful_jobs"),
            "decision_calls": len(decisions),
            "accepted_decisions": sum(not d.get("error_code") for d in decisions),
            "fallbacks": sum(
                s.get("tool") == "search_decision_fallback" for s in trace
            ),
            "verification_checkpoints": sum(
                s.get("tool") == "search_pause" for s in trace
            ),
            "search_resumes": sum(s.get("tool") == "search_resume" for s in trace),
            "lead_failure_codes": dict(
                Counter(l.failure_code for l in leads if l.failure_code)
            ),
            "stop_reason": stop.get("decision"),
            "decision_tokens": token_summary(
                [d["details"].get("usage") for d in decisions]
            ),
            "search_tokens": token_summary(search_usage),
        }
        report = {
            **metadata,
            "metrics": metrics,
            "searches": searches,
            "trace": trace,
            "jobs": [
                {
                    "id": j.id,
                    "company": j.company,
                    "title": j.title,
                    "url": j.source_url,
                    "locations": j.locations,
                    "job_type": j.job_type,
                    "verification_status": j.verification_status,
                    "availability_status": j.availability_status,
                    "raw_content": j.raw_content,
                }
                for j in jobs
            ],
            "matches": discovery.result_matches,
            "leads": [
                {
                    "url": l.source_url,
                    "title": l.title_hint,
                    "status": l.status,
                    "failure_code": l.failure_code,
                    "failure_reason": l.failure_reason,
                }
                for l in leads
            ],
        }
        (directory / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(metrics, ensure_ascii=False, indent=2), flush=True)
    engine.dispose()


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["agent", "rule"], required=True)
    parser.add_argument("--query", default="上海 2027 校招 AI应用开发")
    parser.add_argument("--company-ids", nargs="*", default=[])
    parser.add_argument("--rounds", type=int, choices=range(1, 4), default=3)
    parser.add_argument(
        "--search-seconds", type=int, choices=range(30, 181), default=120
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    directory = args.output_dir.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    asyncio.run(run(args, directory))


if __name__ == "__main__":
    main()
