"""Compare discovery interpretation variants on identical, saved public JDs.

The local run baseline is read-only. Live mode calls the configured model with
public job text only, alternates variant order, and never starts app services.
"""

import argparse
import asyncio
import json
import sqlite3
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from time import monotonic


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def baseline(database, count):
    from src.services.search_run_metrics import SearchRunMetrics

    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute("SELECT id,started_at,finished_at,usage_metrics,agent_trace "
                                  "FROM discovery_runs WHERE finished_at IS NOT NULL "
                                  "ORDER BY started_at DESC LIMIT ?", (count,)).fetchall()
    result = []
    for row in rows:
        metrics = SearchRunMetrics(datetime.fromisoformat(row["started_at"]), {})
        for event in json.loads(row["agent_trace"] or "[]"):
            metrics.observe(event.get("tool"), event.get("details") or {})
        result.append({"id": row["id"], "started_at": row["started_at"],
                       "total_seconds": (datetime.fromisoformat(row["finished_at"]) -
                                         datetime.fromisoformat(row["started_at"])).total_seconds(),
                       "metrics": json.loads(row["usage_metrics"] or "{}"),
                       "performance": metrics.snapshot()["performance"]})
    return result


async def compare(args):
    from src.config import get_settings
    from src.services.discovery_sources import JobStub
    from src.services.source_understanding import SourceUnderstanding, checked_decisions

    settings = get_settings()
    if settings.structured_model_provider == "fake":
        raise ValueError("Live comparison requires a configured real model")
    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    variants = [("full", True, settings.llm_reasoning_effort),
                ("search", False, settings.llm_reasoning_effort)]
    if args.compare_low:
        variants.append(("search-low", False, "low"))
    report = {"started_at": datetime.now(UTC).isoformat(), "query": dataset["query"],
              "model": settings.llm_model, "timeout_seconds": settings.web_search_semantic_timeout_seconds,
              "protocol": "Identical public bodies, no fetch or cached interpretation; alternate order. "
                          "Expected labels come from the existing dataset; inspect mismatches before drawing quality conclusions.",
              "rows": []}
    for index, row in enumerate(dataset["samples"][:args.samples]):
        original = JobStub(**{key: row[key] for key in (
            "source_id", "source_job_id", "company", "title", "locations", "job_type", "raw_content")},
            detail_url=row["source_url"], published_at=None)
        ordered = variants[index % len(variants):] + variants[:index % len(variants)]
        for name, qualifications, effort in ordered:
            events = []
            runtime = SourceUnderstanding(settings.model_copy(update={"llm_reasoning_effort": effort}),
                query=dataset["query"], include_qualifications=qualifications,
                on_event=lambda k, d, events=events: events.append((k, d)))
            started = monotonic()
            result = await runtime.review(original, query=dataset["query"])
            checks = checked_decisions(result, runtime.conditions, primary=True)
            predicted = {field: check["status"] for field, check in checks.items()}
            calls = [d for k, d in events if k == "source_understanding" and "duration_ms" in d]
            outcome = {"sample": index, "title": row["title"], "variant": name,
                       "seconds": round(monotonic() - started, 3), "calls": calls,
                       "predicted": predicted, "expected": row["expected"],
                       "correct_fields": sum(predicted.get(k) == v for k, v in row["expected"].items()),
                       "total_fields": len(row["expected"])}
            report["rows"].append(outcome)
            save(args.output / "model-comparison.json", report)
            print(json.dumps({k: outcome[k] for k in ("sample", "variant", "seconds", "correct_fields", "total_fields")}), flush=True)
    report["summary"] = {}
    for name, _, _ in variants:
        rows = [r for r in report["rows"] if r["variant"] == name]
        outcomes = Counter(c.get("error_code") or "success" for r in rows for c in r["calls"])
        report["summary"][name] = {"samples": len(rows), "median_seconds": median(r["seconds"] for r in rows),
            "model_outcomes": dict(outcomes), "correct_fields": sum(r["correct_fields"] for r in rows),
            "total_fields": sum(r["total_fields"] for r in rows)}
    save(args.output / "model-comparison.json", report)
    print(json.dumps(report["summary"]), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--database", type=Path, default=Path("data/jobflow.db"))
    parser.add_argument("--dataset", type=Path, default=Path("datasets/real_pending_jobs_20261018.json"))
    parser.add_argument("--samples", type=int, default=7)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--compare-low", action="store_true")
    args = parser.parse_args()
    save(args.output / "recent-run-baseline.json", baseline(args.database, 5))
    if args.live:
        asyncio.run(compare(args))
