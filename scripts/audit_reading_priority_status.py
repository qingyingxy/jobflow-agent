"""Replay saved real jobs in an isolated SQLite copy; no network/model calls."""

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path
from time import perf_counter

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from src.domain.application import CandidateJob
from src.domain.job import JobPosting
from src.domain.search_goal import SearchGoal
from src.services.body_quality import assess_body
from src.services.job_identity import candidate_groups, unique_candidates
from src.services.search_goal_service import SearchGoalService


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reuse-copy", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    trial = args.output / "trial.db"
    if trial.exists() and not args.reuse_copy:
        raise SystemExit("Output database already exists; choose a new output directory")
    if not trial.exists():
        with sqlite3.connect(args.source.resolve().as_uri() + "?mode=ro", uri=True) as original, sqlite3.connect(trial) as copy:
            original.backup(copy)
    engine = create_engine("sqlite:///" + trial.as_posix())
    summary = {"method": "saved_real_body_replay", "network_calls": 0, "source_database_changed": False, "goals": []}
    with Session(engine) as session:
        jobs = list(session.scalars(select(JobPosting).join(CandidateJob, CandidateJob.job_posting_id == JobPosting.id)
                                   .where(CandidateJob.user_id == "local-user")))
        summary["raw_job_rows"] = len(jobs)
        groups = candidate_groups(session, "local-user")
        summary["unique_jobs"] = len(groups)
        summary["duplicates"] = [{"url": url, "rows": len(rows), "title": rows[0][1].title,
                                   "states": [candidate.status for candidate, _ in rows]}
                                  for url, rows in groups.items() if len(rows) > 1]
        summary["unreadable"] = [{"id": job.id, "title": job.title, "url": job.source_url,
                                  "quality": assess_body(job.raw_content, title=job.title)} for job in jobs
                                 if assess_body(job.raw_content, title=job.title)["status"] != "readable"]
        service = SearchGoalService(session)
        visible_ids = {job.id for candidate, job in unique_candidates(session, "local-user")
                       if candidate.status not in {"IGNORED", "CONVERTED"}}
        for goal in session.scalars(select(SearchGoal).where(SearchGoal.user_id == "local-user")):
            started = perf_counter()
            library = service.library("local-user", goal.id, include_progress=False)
            elapsed = perf_counter() - started
            matches = library["result_matches"]
            by_id = {job.id: job for job in service.postings("local-user")}
            stages = {stage: dict(Counter(m["result_status"][stage]["state"] for m in matches))
                      for stage in ("analysis", "search", "personal")}
            samples = []
            for stage, value in (("analysis", "reading_required"), ("analysis", "waiting"),
                                 ("search", "source_missing"), ("search", "matched"), ("personal", "conflict")):
                match = next((m for m in matches if m["result_status"][stage]["state"] == value
                              and m["job_posting_id"] in visible_ids), None)
                if match:
                    job = by_id[match["job_posting_id"]]
                    samples.append({"stage": stage, "value": value, "title": job.title, "company": job.company,
                                    "id": job.id, "review_status": match["review_status"], "result_status": match["result_status"]})
            summary["goals"].append({"id": goal.id, "query": goal.query, "counts": library["counts"],
                                      "elapsed_seconds": round(elapsed, 3), "stages": stages, "samples": samples})
    engine.dispose()
    (args.output / "replay.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
