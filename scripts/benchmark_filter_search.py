"""Record one real search through the HTTP API; relevance is reviewed separately.

The runner does not tune search budgets or send a resume. Use a dedicated backend
database for a cold run. Snapshots preserve when results first became available.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

import httpx


async def run(args):
    directory = Path(args.output)
    directory.mkdir(parents=True, exist_ok=True)
    if (directory / "timing.json").exists():
        raise ValueError("This directory already contains a measurement")

    def save(name, value):
        (directory / name).write_text(
            json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    protocol = {
        "query": args.query,
        "started_at": datetime.now(UTC).isoformat(),
        "sample_count": 1,
        "poll_interval_seconds": 1.5,
        "first_usable_definition": "First observed API availability of a verified concrete job subsequently confirmed relevant by independent source review; unverified links and unresolved hard conditions are not usable.",
        "total_time_definition": "POST /discovery/search dispatch to the first observation of a terminal run state; polling delay is included. Also retain server start/finish timestamps.",
        "top10_definition": "First ten concrete job rows in the default UI order, expanding company groups only; explicit exclusions stay hidden. A missing or unverified fact is unknown, not a positive label.",
        "exclusion_error_definition": "Actually relevant jobs among all system-excluded jobs with a determinate independent review. Report unresolved exclusions separately; no excluded sample means N/A, not 0%.",
        "no_mocks": True,
        "manual_review_required": True,
        "search_settings_modified": False,
    }
    save("protocol.json", protocol)
    async with httpx.AsyncClient(
        base_url=args.api_url, headers={"X-User-ID": "local-user"}, timeout=30
    ) as client:
        response = await client.get("/health")
        response.raise_for_status()
        started = monotonic()
        response = await client.post(
            "/api/discovery/search",
            json={"query": args.query, "source_mode": "web", "company_ids": None},
        )
        response.raise_for_status()
        item = response.json()
        run_id = item["id"]
        save("created-run.json", item)
        first_seen, first_verified, first_system_matched = {}, None, None
        first_lead = None
        previous = None
        with (directory / "timeline.jsonl").open("w", encoding="utf-8") as timeline:
            while True:
                responses = await asyncio.gather(
                    client.get(f"/api/discovery/runs/{run_id}"),
                    client.get("/api/discovery/leads"),
                )
                for response in responses:
                    response.raise_for_status()
                item = responses[0].json()
                leads = [
                    lead
                    for lead in responses[1].json()
                    if lead["discovery_run_id"] == run_id
                ]
                elapsed = round(monotonic() - started, 3)
                if leads and first_lead is None:
                    first_lead = elapsed
                matches = item["result_matches"]
                for match in matches:
                    first_seen.setdefault(match["job_posting_id"], elapsed)
                if matches and first_verified is None:
                    first_verified = elapsed
                if (
                    any(match.get("filter_status") == "matched" for match in matches)
                    and first_system_matched is None
                ):
                    first_system_matched = elapsed
                snapshot = {
                    "elapsed_seconds": elapsed,
                    "status": item["status"],
                    "lead_count": len(leads),
                    "lead_statuses": dict(Counter(lead["status"] for lead in leads)),
                    "matches": [
                        {k: m.get(k) for k in ("job_posting_id", "filter_status")}
                        for m in matches
                    ],
                }
                timeline.write(json.dumps(snapshot, ensure_ascii=False) + "\n")
                timeline.flush()
                signature = json.dumps(
                    {k: v for k, v in snapshot.items() if k != "elapsed_seconds"},
                    sort_keys=True,
                )
                if signature != previous:
                    print(json.dumps(snapshot, ensure_ascii=False), flush=True)
                    previous = signature
                save("latest-run.json", item)
                if item["status"] != "RUNNING":
                    break
                if elapsed > 1000:
                    raise TimeoutError(
                        "Benchmark observation exceeded 1000 seconds; run is preserved"
                    )
                await asyncio.sleep(1.5)
        timing = {
            "run_id": run_id,
            "first_lead_seconds": first_lead,
            "first_verified_seconds": first_verified,
            "first_system_matched_seconds": first_system_matched,
            "first_seen_job_seconds": first_seen,
            "total_observed_seconds": elapsed,
            "server_started_at": item["started_at"],
            "server_finished_at": item["finished_at"],
            "analysis_target_count": item["analysis_target_count"],
            "analysis_completed_count": item["analysis_completed_count"],
        }
        save("timing.json", timing)
        save("final-run.json", item)
        save("leads.json", leads)
        for name, endpoint in (
            ("candidates.json", "/api/candidates"),
            ("search-evidence.json", f"/api/discovery/runs/{run_id}/search-evidence"),
        ):
            response = await client.get(endpoint)
            response.raise_for_status()
            save(name, response.json())
        jobs = []
        for match in matches:
            response = await client.get(f"/api/jobs/{match['job_posting_id']}")
            response.raise_for_status()
            jobs.append(response.json())
        save("jobs.json", jobs)
        print(
            json.dumps(
                {
                    "timing": timing,
                    "lead_count": len(leads),
                    "statuses": dict(Counter(m.get("filter_status") for m in matches)),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://127.0.0.1:18031")
    parser.add_argument("--query", required=True)
    parser.add_argument("--output", required=True)
    asyncio.run(run(parser.parse_args()))
