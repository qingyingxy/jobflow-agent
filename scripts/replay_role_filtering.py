"""Replay saved, source-reviewed jobs without searching or reading a resume.

Historical outcomes are a reference, not a randomized baseline. --live uses the
configured role model, its normal timeout/call budget, and two verification slots.
"""

import argparse
import asyncio
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.config import get_settings
from src.infrastructure.database import Base
from src.main import app  # noqa: F401 - register table models
from src.services.discovery_matching import classify_discovery_job
from src.services.discovery_sources import JobStub
from src.services.job_role_review import VERSION, JobRoleReviewer, duty_text

REPO = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def code_hashes():
    return {str(p.relative_to(REPO)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((REPO / "src").rglob("*.py"))}


def summarize(items, status_key):
    counts = Counter((item["label"], item[status_key]) for item in items)
    relevant = sum(item["label"] == "relevant" for item in items)
    confirmed = counts[("relevant", "matched")]
    return {
        "statuses": dict(Counter(item[status_key] for item in items)),
        "relevant_jobs": relevant,
        "relevant_confirmed": confirmed,
        "relevant_pending": counts[("relevant", "pending")],
        "relevant_excluded": counts[("relevant", "excluded")],
        "irrelevant_matched": counts[("irrelevant", "matched")],
        "unresolved_matched": counts[("unresolved", "matched")],
        "unreviewed_jobs": sum(item["label"] == "unreviewed" for item in items),
        "unreviewed_matched": counts[("unreviewed", "matched")],
        "unreviewed_excluded": counts[("unreviewed", "excluded")],
        "automatic_confirmation_rate": confirmed / relevant if relevant else None,
    }


async def replay(case, output, *, live):
    jobs = sorted(read(case / "jobs.json"), key=lambda j: j["first_seen_at"])
    historical = read(case / "final-run.json")
    source_review = read(case / "source-review.json")
    saved_goal = "labels" in source_review
    if saved_goal:
        labels = {item["job_posting_id"]: item for item in source_review["labels"]}
        for job in jobs:
            label = labels.get(job["id"])
            if label and label["raw_content_sha256"] != hashlib.sha256(job["raw_content"].encode()).hexdigest():
                raise ValueError("Source body changed since review")
        original_rows = read(case / "library.json")["result_matches"]
        query = read(case / "goal.json")["query"]
        case_name = case.parent.name + "-" + case.name
    else:
        labels = {item["job_id"]: item for item in source_review["items"]}
        original_rows = historical["result_matches"]
        query = historical["search_query"]
        case_name = case.name
    original = {item["job_posting_id"]: item for item in original_rows}
    settings = get_settings()
    if live and settings.structured_model_provider == "fake":
        raise ValueError("Live replay requires a configured real model")
    if not live:
        settings = settings.model_copy(update={"web_search_role_review_enabled": False})
    events, results = [], []
    reviewer = JobRoleReviewer(settings, on_event=lambda kind, data: events.append({"kind": kind, **data}))
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    queue = asyncio.Queue()
    for job in jobs:
        queue.put_nowait(job)

    async def worker():
        with Session(engine) as session:
            while not queue.empty():
                raw = queue.get_nowait()
                started = monotonic()
                job = JobStub(**{k: raw.get(k) for k in JobStub.__dataclass_fields__ if k != "detail_url"},
                              detail_url=raw["source_url"])
                review = await reviewer.review(job, query=query, session=session,
                                               user_id="replay", lead_id=raw["id"])
                match = classify_discovery_job(job, query=query, role_review=review)
                label = labels.get(raw["id"], {})
                results.append({
                    "job_id": raw["id"], "title": job.title, "source_url": job.detail_url,
                    "label": label.get("label" if saved_goal else "review_label", "unreviewed"),
                    "historical_status": original[raw["id"]]["filter_status"],
                    "filter_status": match.filter_status, "checks": list(match.checks),
                    "review": review, "duties": duty_text(job),
                    "role_elapsed_seconds": round(monotonic() - started, 3),
                })
                queue.task_done()

    started = monotonic()
    try:
        await asyncio.gather(worker(), worker())
    finally:
        await reviewer.aclose()
        engine.dispose()
    results.sort(key=lambda row: row["job_id"])
    report = {
        "case": case_name, "query": query, "live_model": live,
        "role_version": VERSION, "role_calls": reviewer.calls,
        "local_role_confirmations": sum(any(c.get("method") == "local_duties" for c in row["checks"]) for row in results),
        "local_confirmed_jobs": sum(row["filter_status"] == "matched" and any(c.get("method") == "local_duties" for c in row["checks"]) for row in results),
        "role_events": dict(Counter(event.get("error_code") or event.get("method") or "completed" for event in events)),
        "role_replay_elapsed_seconds": round(monotonic() - started, 3),
        "historical": summarize(results, "historical_status"),
        "replay": summarize(results, "filter_status"),
        "inputs_sha256": {name: hashlib.sha256((case / name).read_bytes()).hexdigest()
                          for name in ("jobs.json", "final-run.json", "source-review.json")},
        "items": results, "events": events,
    }
    save(output / (case_name + ".json"), report)
    print(json.dumps({k: v for k, v in report.items() if k not in {"items", "events", "inputs_sha256"}}, ensure_ascii=False), flush=True)
    return report


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cases", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    start_hashes = code_hashes()
    save(args.output / "code-hashes-start.json", start_hashes)
    reports = [await replay(case, args.output, live=args.live) for case in args.cases]
    end_hashes = code_hashes()
    save(args.output / "code-hashes-end.json", end_hashes)
    changed = [path for path in start_hashes.keys() | end_hashes.keys() if start_hashes.get(path) != end_hashes.get(path)]
    save(args.output / "summary.json", {
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": "Saved source text replay; source labels are assistant judgments, not human gold. No new search or page read. Historical model responses differ; this is not a causal speed or accuracy estimate.",
        "application_code_changed": changed,
        "cases": [{k: v for k, v in report.items() if k not in {"items", "events", "inputs_sha256"}} for report in reports],
    })
    if changed:
        raise RuntimeError("Application changed during replay")


if __name__ == "__main__":
    asyncio.run(main())
