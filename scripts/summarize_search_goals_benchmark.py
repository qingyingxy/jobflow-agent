"""Summarize live saved-goal measurements using separately supplied source labels.

This reads reviewer decisions; it does not generate labels from system matches.
Unknown source labels stay visible in denominators and are never counted correct.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def summarize(directory):
    jobs = {j["id"]: j for j in read(directory / "jobs.json")}
    by_url = {j["source_url"]: j for j in jobs.values()}
    matches = {m["job_posting_id"]: m for m in read(directory / "library.json")["result_matches"]}
    review = read(directory / "source-review.json")
    labels = {r["job_posting_id"]: r for r in review["labels"]}
    if len(labels) != len(review["labels"]):
        raise ValueError(f"Duplicate reviewed job in {directory}")
    for identifier, label in labels.items():
        job = jobs[identifier]
        if label["label"] not in {"relevant", "irrelevant", "unresolved"}:
            raise ValueError(f"Invalid label: {identifier}")
        if label["source_url"] != job["source_url"] or label["content_hash"] != job["content_hash"]:
            raise ValueError(f"Reviewed source identity changed: {identifier}")
        digest = hashlib.sha256(job["raw_content"].encode("utf-8")).hexdigest()
        if label["raw_content_sha256"] != digest:
            raise ValueError(f"Reviewed raw content changed: {identifier}")
        if not label["quotes"] or any(q not in job["raw_content"] for q in label["quotes"]):
            raise ValueError(f"Missing or unsupported source quote: {identifier}")

    top = read(directory / "top10.json")
    top_labels = []
    for row in top:
        job = by_url.get(row["url"])
        if job is None:
            # Unverified links remain in the display denominator.
            top_labels.append("unresolved")
        elif job["id"] not in labels:
            raise ValueError(f"Top result has no review: {job['id']}")
        else:
            top_labels.append(labels[job["id"]]["label"])
    excluded = [identifier for identifier, m in matches.items() if m["filter_status"] == "excluded"]
    if any(identifier not in labels for identifier in excluded):
        raise ValueError(f"Some exclusions are not reviewed: {directory}")
    exclusion_labels = [labels[i]["label"] for i in excluded]
    decided_exclusions = sum(label != "unresolved" for label in exclusion_labels)
    mistaken_exclusions = exclusion_labels.count("relevant")

    timing = read(directory / "timing.json")
    before = read(directory / "library-before.json")["result_matches"]
    before_ids = {m["job_posting_id"] for m in before}
    valid_cached = [m["job_posting_id"] for m in before
                    if m["filter_status"] == "matched"
                    and labels.get(m["job_posting_id"], {}).get("label") == "relevant"]
    first_times = timing["first_library_matched_job_seconds"]
    confirmed = {identifier: seconds for identifier, seconds in first_times.items()
                 if labels.get(identifier, {}).get("label") == "relevant"}
    first_seconds = min(confirmed.values(), default=None)
    if valid_cached:
        first_seconds = timing["cached_usable_seconds"]
        first_ids = valid_cached
    else:
        first_ids = [i for i, t in confirmed.items() if t == first_seconds]
        if first_seconds is not None and any(i not in labels for i, t in first_times.items() if t < first_seconds):
            raise ValueError(f"Earlier system matches remain unaudited: {directory}")
    new_confirmed = {i: t for i, t in confirmed.items() if i not in before_ids}
    earlier_unknown = [i for i, t in first_times.items()
                       if first_seconds is not None and t < first_seconds
                       and labels.get(i, {}).get("label") == "unresolved"]
    run = read(directory / "final-run.json")
    trace = run["agent_trace"]
    review_requests = [e for e in trace if e["tool"] == "role_review_request"]
    searches = [e for e in trace if e["tool"] == "search_query"]
    stages = [e for e in trace if e["tool"] == "verification_stage"]
    verifications = [e for e in trace if e["tool"] == "verification"]
    source_counts = Counter(j["company"] for j in jobs.values())
    return {
        "case": directory.parent.name, "mode": timing["cache"],
        "query": read(directory / "goal.json")["input_text"],
        "run_id": run["id"], "run_status": run["status"], "failure_summary": run["failure_summary"],
        "first_confirmed_usable_seconds": first_seconds,
        "first_confirmed_job_ids": first_ids,
        "earlier_unresolved_job_ids": earlier_unknown,
        "first_system_matched_seconds": timing["first_library_system_usable_seconds"],
        "first_new_confirmed_seconds": min(new_confirmed.values(), default=None),
        "total_seconds": timing["total_observed_seconds"],
        "top10": {"displayed": len(top), "confirmed_relevant": top_labels.count("relevant"),
                  "irrelevant": top_labels.count("irrelevant"), "unresolved": top_labels.count("unresolved"),
                  "confirmed_effective_ratio": top_labels.count("relevant") / len(top) if top else None,
                  "shortfall_to_ten": max(0, 10 - len(top)),
                  "companies": dict(Counter(by_url[r["url"]]["company"] if r["url"] in by_url else "未核验"
                                            for r in top))},
        "exclusions": {"total": len(excluded), "determinate": decided_exclusions,
                       "mistaken": mistaken_exclusions, "unresolved": exclusion_labels.count("unresolved"),
                       "mistaken_ratio": mistaken_exclusions / decided_exclusions if decided_exclusions else None},
        "library_counts": read(directory / "library.json")["counts"],
        "companies": dict(source_counts),
        "trace_metrics": {
            "search_queries": len(searches),
            "role_review_requests": len(review_requests),
            "role_review_request_failures": dict(Counter(e["error_code"] for e in review_requests
                                                         if e.get("error_code"))),
            "http_stage_failures": dict(Counter(e["error_code"] for e in stages
                                                if e["details"].get("stage") == "http_verification"
                                                and e.get("error_code"))),
            "browser_stage_failures": dict(Counter(e["error_code"] for e in stages
                                                   if e["details"].get("stage") == "browser_verification"
                                                   and e.get("error_code"))),
            "maximum_verification_queue_wait_seconds": max((e["details"].get("queue_wait_ms", 0) / 1000
                                                           for e in verifications), default=0),
        },
    }


def main(root):
    if read(root / "application-code-changed.json"):
        raise ValueError("Application code changed during measurement")
    summaries = read(root / "summary-pending-review.json")
    rows = [summarize(root / Path(s["directory"]).parent.name / s["timing"]["cache"]) for s in summaries]
    report = {"protocol": read(root / "protocol.json"), "application_code_changed": False, "runs": rows}
    save(root / "report.json", report)
    for row in rows:
        top, excluded = row["top10"], row["exclusions"]
        print(json.dumps({"case": row["case"], "mode": row["mode"],
                          "first": row["first_confirmed_usable_seconds"], "total": row["total_seconds"],
                          "top10": f"{top['confirmed_relevant']}/{top['displayed']}",
                          "top10_unresolved": top["unresolved"],
                          "excluded": f"{excluded['mistaken']}/{excluded['determinate']}",
                          "excluded_unresolved": excluded["unresolved"]}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    main(parser.parse_args().input.resolve())
