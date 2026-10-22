"""Replay public JDs and recorded decisions; never load candidate information."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sqlite3
from collections import Counter
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.config import get_settings
from src.domain.job import RawJobDocument
from src.infrastructure.database import Base
from src.infrastructure.llm_client import FakeModelClient
from src.main import app  # noqa: F401 - register database models
from src.services.discovery_matching import classify_discovery_job
from src.services.discovery_sources import JobStub
from src.services.jd_parser import JDParserError
from src.services.job_role_review import (
    JobRoleReviewer,
    duty_passages,
    fingerprint,
    resolve_citations,
)
from src.services.product_jd_execution import ProductJDExecutionParser


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def summary(items, key):
    counts = Counter((item["label"], item[key]) for item in items)
    return {
        "statuses": dict(Counter(item[key] for item in items)),
        "relevant_matched": counts["relevant", "matched"],
        "relevant_pending": counts["relevant", "pending"],
        "relevant_excluded": counts["relevant", "excluded"],
        "irrelevant_matched": counts["irrelevant", "matched"],
        "unresolved_matched": counts["unresolved", "matched"],
    }


async def replay(root, *, live, recorded_roles=None):
    jobs = read(root / "round-1/jobs.json")
    run = read(root / "round-1/final-run.json")
    labels = {
        j["source_job_id"]: j["label"]
        for j in read(root / "source-review.json")["items"]
    }
    historical = {
        j["job_posting_id"]: j["filter_status"] for j in run["result_matches"]
    }
    database = (root / "round-1/acceptance.db").resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(database, uri=True) as connection:
        recorded = {
            url: json.loads(evidence)
            for url, evidence in connection.execute(
                "SELECT source_url, field_evidence FROM lead_verifications "
                "WHERE result='ROLE_REVIEW' ORDER BY checked_at"
            )
        }
    if recorded_roles is not None:
        source = read(recorded_roles)
        for path, digest in source["source_sha256"].items():
            if hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest:
                raise ValueError(
                    "Recorded role decisions are bound to different sources"
                )
        recorded = {
            next(
                j["source_url"]
                for j in jobs
                if j["source_job_id"] == item["source_job_id"]
            ): item["review"]
            for item in source["items"]
            if item["review"]
        }
    events = []
    reviewer = JobRoleReviewer(
        get_settings(),
        on_event=lambda kind, data: events.append({"kind": kind, **data}),
    )
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    items = []
    queue = asyncio.Queue()
    for job in sorted(jobs, key=lambda j: j["first_seen_at"]):
        queue.put_nowait(job)

    async def worker():
        with Session(engine) as session:
            while not queue.empty():
                job = queue.get_nowait()
                stub = JobStub(
                    **{
                        k: job.get(k)
                        for k in JobStub.__dataclass_fields__
                        if k != "detail_url"
                    },
                    detail_url=job["source_url"],
                )
                review = None
                if live:
                    review = await reviewer.review(
                        stub,
                        query=run["search_query"],
                        session=session,
                        user_id="public-replay",
                        lead_id=job["id"],
                    )
                elif record := recorded.get(stub.detail_url):
                    # Explicit replay under the new policy, never reuse the old cache key.
                    review = {
                        "fingerprint": fingerprint(stub, run["search_query"]),
                        "decision": resolve_citations(
                            record["proposed_output"], duty_passages(stub)
                        ),
                    }
                local = classify_discovery_job(stub, query=run["search_query"])
                match = classify_discovery_job(
                    stub, query=run["search_query"], role_review=review
                )
                items.append(
                    {
                        "source_job_id": job["source_job_id"],
                        "title": job["title"],
                        "label": labels[job["source_job_id"]],
                        "historical_status": historical[job["id"]],
                        "local_status": local.filter_status,
                        "filter_status": match.filter_status,
                        "checks": list(match.checks),
                        "review": review,
                    }
                )
                queue.task_done()

    await asyncio.gather(worker(), worker())
    engine.dispose()
    parsers = []
    for path in sorted(root.glob("public-jd-calls-*.json")):
        job = next(j for j in jobs if path.stem.endswith(j["source_job_id"]))
        calls = read(path)
        client = FakeModelClient(
            outputs=[c["response"]["output"] for c in calls if "response" in c]
        )
        parser = ProductJDExecutionParser(
            client, mode="two_stage", validation_retries=1
        )
        row = {"source_job_id": job["source_job_id"], "title": job["title"]}
        try:
            parsed = await parser.parse(
                RawJobDocument(
                    raw_content=job["raw_content"],
                    source_url=job["source_url"],
                    source_metadata={"title": job["title"]},
                )
            )
            row.update(
                status="parsed",
                structured_jd=parsed.structured_jd.model_dump(mode="json"),
            )
        except JDParserError as error:
            row.update(status="failed", error_code=error.code)
        row["recorded_responses_consumed"] = len(client.requests)
        parsers.append(row)
    return {
        "scope": "Public source replay. Assistant reference labels; no new search or candidate matching. Offline results reuse model proposals and are not fresh accuracy or latency measurements.",
        "live_role_model": live,
        "role_calls": reviewer.calls,
        "source_sha256": {
            str(p): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [root / "round-1/jobs.json", root / "source-review.json"]
        },
        "historical": summary(items, "historical_status"),
        "local": summary(items, "local_status"),
        "replay": summary(items, "filter_status"),
        "public_jd_parsing": parsers,
        "items": items,
        "events": events,
    }


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--recorded-role-results", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Do not overwrite previous results")
    if args.live and args.recorded_role_results:
        raise ValueError("Choose fresh calls or recorded decisions")
    report = await replay(
        args.source, live=args.live, recorded_roles=args.recorded_role_results
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                k: v
                for k, v in report.items()
                if k not in {"items", "events", "public_jd_parsing"}
            },
            ensure_ascii=False,
        )
    )
    print(
        json.dumps(
            [
                {k: v for k, v in r.items() if k != "structured_jd"}
                for r in report["public_jd_parsing"]
            ],
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
