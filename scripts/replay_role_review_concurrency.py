"""Replay a fixed public job pool, optionally with bounded fresh role reviews."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sqlite3
from collections import Counter
from pathlib import Path
from time import monotonic

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.config import get_settings
from src.infrastructure.database import Base
from src.main import app  # noqa: F401 - register ORM models in the empty database
from src.services.discovery_matching import classify_discovery_job
from src.services.discovery_sources import JobStub
from src.services.job_role_review import (
    VERSION,
    JobRoleReviewer,
    duty_passages,
    fingerprint,
    resolve_citations,
)


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def counts(rows, key):
    pairs = Counter((row["label"], row[key]) for row in rows)
    return {
        "statuses": dict(Counter(row[key] for row in rows)),
        "false_matched": pairs["irrelevant", "matched"],
        "false_excluded": pairs["relevant", "excluded"],
        "relevant_matched": pairs["relevant", "matched"],
        "relevant_pending": pairs["relevant", "pending"],
        "unresolved_matched": pairs["unresolved", "matched"],
    }


async def replay(source, *, live, concurrency):
    paths = [
        source / name for name in ("jobs.json", "final-run.json", "source-review.json")
    ]
    jobs, run, labels = map(read, paths)
    labels = {row["source_job_id"]: row for row in labels["items"]}
    historical = {
        row["job_posting_id"]: row["filter_status"] for row in run["result_matches"]
    }
    query = run["search_query"]
    settings = get_settings().model_copy(
        update={"web_search_role_review_concurrency": concurrency}
    )
    if live and (
        settings.structured_model_provider == "fake" or not settings.llm_api_key
    ):
        raise ValueError("Fresh reviews require the configured live provider")
    with sqlite3.connect(
        (source / "acceptance.db").resolve().as_uri() + "?mode=ro", uri=True
    ) as database:
        records = {
            url: json.loads(data)
            for url, data in database.execute(
                "SELECT source_url,field_evidence FROM lead_verifications "
                "WHERE result='ROLE_REVIEW' ORDER BY checked_at"
            )
        }
    events = []
    reviewer = JobRoleReviewer(
        settings, on_event=lambda kind, data: events.append({"kind": kind, **data})
    )
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    started = monotonic()
    try:
        with Session(engine) as session:

            async def one(job):
                label = labels[job["source_job_id"]]
                if (
                    hashlib.sha256(job["raw_content"].encode()).hexdigest()
                    != label["raw_content_sha256"]
                ):
                    raise ValueError(
                        "Reference label is bound to different public text"
                    )
                stub = JobStub(
                    **{
                        key: job.get(key) if key != "detail_url" else job["source_url"]
                        for key in JobStub.__dataclass_fields__
                    }
                )
                review = None
                invalid_proposal = False
                if live:
                    review = await reviewer.review(
                        stub,
                        query=query,
                        session=session,
                        user_id="public-fixed-pool",
                        lead_id=job["id"],
                    )
                elif (record := records.get(stub.detail_url)) and record.get(
                    "proposed_output"
                ):
                    try:
                        # Explicit replay under the new policy, not a reuse of an old cache key.
                        review = {
                            "fingerprint": fingerprint(stub, query),
                            "decision": resolve_citations(
                                record["proposed_output"], duty_passages(stub)
                            ),
                        }
                    except ValueError:
                        invalid_proposal = True
                match = classify_discovery_job(stub, query=query, role_review=review)
                return {
                    "source_job_id": job["source_job_id"],
                    "title": job["title"],
                    "label": label["label"],
                    "historical_status": historical[job["id"]],
                    "filter_status": match.filter_status,
                    "checks": list(match.checks),
                    "review": review,
                    "invalid_recorded_proposal": invalid_proposal,
                    "completed_elapsed_seconds": round(monotonic() - started, 3),
                }

            # All public texts are already available. Stable ordering preserves the
            # same input batches across concurrency settings; this is not search latency.
            rows = await asyncio.gather(
                *(
                    one(job)
                    for job in sorted(jobs, key=lambda row: row["first_seen_at"])
                )
            )
            wall_seconds = monotonic() - started
    finally:
        await reviewer.aclose()
        engine.dispose()
    requests = [event for event in events if event["kind"] == "role_review_request"]
    return {
        "scope": "Fixed public text pool; no search, resume, profile or personal eligibility. Assistant reference labels, not independent human gold.",
        "live": live,
        "version": VERSION,
        "concurrency": concurrency,
        "configuration": {
            key: getattr(settings, key)
            for key in (
                "llm_model",
                "web_search_role_review_batch_size",
                "web_search_role_review_max_calls",
                "web_search_role_review_timeout_seconds",
            )
        },
        "source_sha256": {
            str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths
        },
        "historical": counts(rows, "historical_status"),
        "replay": counts(rows, "filter_status"),
        "wall_seconds": round(wall_seconds, 3),
        "actual_role_requests": reviewer.calls,
        "batch_job_counts": [event["job_count"] for event in requests],
        "request_duration_sum_seconds": sum(event["duration_ms"] for event in requests)
        / 1000,
        "events": events,
        "items": rows,
    }


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "source", type=Path, help="A run directory with jobs and source-review JSON"
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--concurrency", type=int, choices=(1, 2, 3), default=2)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Do not overwrite prior measurements")
    result = await replay(args.source, live=args.live, concurrency=args.concurrency)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                key: value
                for key, value in result.items()
                if key not in {"items", "events", "source_sha256"}
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
