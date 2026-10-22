"""Summarize actual visit snapshots without replacing any model decisions."""
import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def read(path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def summarize(folder):
    from src.services.job_url import canonical_job_url

    visits = sorted(p for p in folder.glob("visit-*") if p.is_dir())
    baseline = read(visits[0] / "before.json")
    final = read(folder / "latest.json")
    matches = {m["job_posting_id"]: m for m in final["library"]["result_matches"]}
    old_matches = {m["job_posting_id"]: m for m in baseline["library"]["result_matches"]}
    key = lambda job: canonical_job_url(job["source_url"]) if job["source_url"] else job["id"]
    old_ids = {key(j) for j in baseline["jobs"]}
    jobs, duplicates, seen = [], [], set()
    for job in final["jobs"]:
        match = matches.get(job["id"])
        if not match:
            continue
        identity = key(job)
        if identity in seen:
            duplicates.append(job["id"])
        seen.add(identity)
        jobs.append({"id": job["id"], "title": job["title"], "company": job["company"],
            "source_url": job["source_url"], "new": identity not in old_ids,
            "status_before": old_matches.get(job["id"], {}).get("review_status"),
            "review_status": match["review_status"], "filter_status": match["filter_status"],
            "checks": match["checks"], "personal_requirements": match.get("personal_requirements", [])})
    rounds, sessions, restarts = [], [], []
    previous = None
    for path in visits:
        before, idle, after = (read(path / name) for name in ("before.json", "idle-start.json", "after.json"))
        if not before:
            continue
        results = [read(p) for p in sorted(path.glob("round-*.json"))]
        rounds += results
        ended = read(path / "complete.json", {})
        sessions.append({"visit": path.name, "seconds": ended.get("elapsed_seconds"),
            "rounds": len(results), "before_queue": before["library"]["review_queue"],
            "after_queue": after["library"]["review_queue"] if after else None,
            "background_only_completed": after["library"]["review_queue"]["completed"] - idle["library"]["review_queue"]["completed"] if after and idle else None,
            "errors": ended.get("worker_errors", [])})
        if previous:
            restarts.append({"all_jobs_retained": {j["id"] for j in previous["jobs"]} <= {j["id"] for j in before["jobs"]},
                "saved_retained": {c["id"] for c in previous["candidates"] if c["status"] == "SAVED"} <= {c["id"] for c in before["candidates"] if c["status"] == "SAVED"},
                "company_progress_retained": previous["company_search_state"] == before["company_search_state"]})
        previous = after
    metrics, errors = Counter(), Counter()
    for run in rounds:
        for k in ("source_read_attempts", "source_read_successes", "read_attempts", "read_successes", "cache_hits",
                  "retry_attempts", "retry_recovered", "source_retry_attempts", "source_retry_recovered"):
            metrics[k] += (run["metrics"] or {}).get(k, 0)
        for event in run["trace"]:
            code = event.get("error_code") or (event.get("details") or {}).get("error_code")
            if code:
                errors[f'{event["tool"]}:{code}'] += 1
    ui = [read(p) for p in folder.glob("ui-*.json") if p.is_file()]
    latency = [r["milliseconds"] for check in ui for r in check.get("requests", []) if r["path"].endswith("/library")]
    summary = {"goal": final["goal"], "before_counts": baseline["library"]["counts"],
        "after_counts": final["library"]["counts"], "queue_before": baseline["library"]["review_queue"],
        "queue_after": final["library"]["review_queue"], "new_counts": dict(Counter(j["review_status"] for j in jobs if j["new"])),
        "new_unique_jobs": sum(j["new"] for j in jobs),
        "existing_promoted": sum(not j["new"] and j["review_status"] == "recommended" and j["status_before"] != "recommended" for j in jobs),
        "metrics": dict(metrics), "errors": dict(errors), "sessions": sessions, "restarts": restarts,
        "rounds": [{"id": r["run_id"], "status": r["status"], "seconds": r["elapsed_seconds"],
                    "company": r["continue_company"], "metrics": r["metrics"]} for r in rounds],
        "ui_count": len(ui), "library_latency_ms": {"median": statistics.median(latency) if latency else None,
            "max": max(latency) if latency else None}, "duplicate_urls": duplicates, "jobs": jobs}
    (folder / "daily-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("new_unique_jobs", "new_counts", "existing_promoted", "after_counts", "queue_after", "metrics", "restarts")}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    summarize(parser.parse_args().folder.resolve())
