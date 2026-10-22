"""Replay frozen public job text against explicit, reviewable field labels."""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from time import monotonic

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import get_settings
from src.services.discovery_matching import classify_discovery_job
from src.services.discovery_sources import JobStub
from src.services.source_understanding import SourceUnderstanding


async def evaluate(args):
    data = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
    events = []
    runtime = SourceUnderstanding(get_settings(), on_event=lambda kind, event: events.append(event))
    results = []
    started = monotonic()
    for sample in data["samples"]:
        job = JobStub(**{k: sample[k] for k in (
            "source_id", "source_job_id", "title", "company", "locations", "job_type", "raw_content",
        )}, detail_url=sample["source_url"], published_at=None,
            recruitment_context=sample.get("recruitment_context", {}))
        before = classify_discovery_job(job, query=data["query"])
        updated = await runtime.review(job, query=data["query"]) if args.live else job
        after = classify_discovery_job(updated, query=data["query"])
        results.append({"id": sample["id"], "title": job.title, "expected": sample["expected"],
            "before": {c["field"]: c["status"] for c in before.checks},
            "after": {c["field"]: c["status"] for c in after.checks},
            "checks": list(after.checks), "understanding": updated.recruitment_context.get("source_understanding")})
        print(json.dumps({"title": job.title, "before": results[-1]["before"], "after": results[-1]["after"]}, ensure_ascii=False), flush=True)
    totals = {}
    for phase in ("before", "after"):
        comparisons = [(r[phase].get(f), expected) for r in results for f, expected in r["expected"].items()]
        known_positive = [(actual, expected) for actual, expected in comparisons if expected == "matched"]
        totals[phase] = {"correct_fields": sum(a == b for a, b in comparisons),
            "field_count": len(comparisons), "positive_fields_recovered": sum(a == "matched" for a, _ in known_positive),
            "positive_field_count": len(known_positive),
            "false_confirmations": sum(a == "matched" and b != "matched" for a, b in comparisons)}
    report = {"dataset": args.dataset, "review_status": data["review_status"], "split": data["split"],
        "mode": "real_model_frozen_text" if args.live else "local_rules_only", "summary": totals,
        "model_calls": runtime.calls, "elapsed_seconds": round(monotonic() - started, 2),
        "limitations": ["开发样本回放，不是未见样本准确率", "字段找回不等于全网岗位召回率", "不改变开放状态门槛"],
        "results": results, "events": events}
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(path), "summary": totals, "calls": runtime.calls}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="datasets/real_pending_jobs_20261018.json")
    parser.add_argument("--output", default="artifacts/source-understanding-replay-20261018.json")
    parser.add_argument("--live", action="store_true", help="Call the configured model with frozen public source text")
    asyncio.run(evaluate(parser.parse_args()))
