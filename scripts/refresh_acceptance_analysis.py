"""Recompute local decisions from cached live parses; forbid new model calls."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path


async def refresh(directory: Path):
    directory = directory.resolve()
    path = directory / "report.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    snapshot = directory / "report-before-local-rule-refresh.json"
    if snapshot.exists():
        snapshot = (
            directory
            / f"report-before-local-rule-refresh-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%f')}.json"
        )
    os.environ["DATABASE_URL"] = f"sqlite:///{(directory / 'acceptance.db').as_posix()}"
    os.environ["LOG_LEVEL"] = "WARNING"
    import httpx

    from src.api import jobs
    from src.main import app

    class CachedOnlyClient:
        model_name = report["model"]

        async def generate(self, *args, **kwargs):
            raise RuntimeError("This replay forbids model calls; cached parse required")

    jobs.create_structured_model_client = lambda settings: CachedOnlyClient()
    responses = []
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://acceptance",
        headers={"X-User-ID": "local-user"},
    ) as client:
        for source in report["sources"]:
            for job in source["jobs"]:
                response = await client.post(f"/api/jobs/{job['job_id']}/analyze")
                response.raise_for_status()
                responses.append((job, response.json()))
        candidates_response = await client.get("/api/candidates")
        candidates_response.raise_for_status()
        candidates = {
            item["job_posting_id"]: item for item in candidates_response.json()
        }
    # Retain the original report as an audit snapshot before replacing decisions.
    snapshot.write_bytes(path.read_bytes())
    for job, response in responses:
        job["analysis"] = response
        job["saved_candidate"] = candidates[job["job_id"]]
    report["local_rule_refresh"] = {
        "at": datetime.now(UTC).isoformat(),
        "new_model_calls": 0,
        "reason": "English degree qualifiers and conjunctive skill evidence",
        "previous_report": snapshot.name,
    }
    report["frontend_verification"] = "pending_after_rule_refresh"
    report["local_rule_sha256"] = {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (
            Path("src/services/eligibility_checker.py"),
            Path("src/services/local_evidence_matcher.py"),
        )
    }
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Refreshed {len(responses)} cached analyses without model access")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    asyncio.run(refresh(parser.parse_args().directory))
