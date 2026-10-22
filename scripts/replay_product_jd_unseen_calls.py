"""Replay repeated JD calls without network; preserve failures and all labels."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path

from scripts.replay_product_jd_recorded_calls import RecordedClient
from scripts.run_product_jd_paired_acceptance import decision_metrics
from scripts.run_product_jd_unseen_acceptance import candidate_checks, write
from src.config import Settings
from src.domain.job import RawJobDocument
from src.services.analysis_runtime import create_product_parser
from src.services.jd_parser import JDParserError


async def replay(rows, cases, manifest):
    by_id = {c["id"]: c for c in cases}
    results = []
    for row in rows:
        client = RecordedClient(row["calls"], manifest["model"])
        settings = Settings(
            **manifest["recovery_policy"], product_parse_mode=row["mode"]
        )
        parser = create_product_parser(client, settings)
        case = by_id[row["case_id"]]
        job, failure = None, None
        try:
            parsed = await parser.parse(
                RawJobDocument(
                    raw_content=case["raw_content"], source_url=case["source_url"]
                )
            )
            job = parsed.structured_jd
        except JDParserError as error:
            failure = error.code
        actual = candidate_checks(job, case["qualification_labels"])
        results.append(
            {
                "case_id": row["case_id"],
                "mode": row["mode"],
                "repeat": row["repeat"],
                "failure_code": failure,
                "same_failure": failure == row["failure_code"],
                "same_call_path": client.consumed == len(row["calls"]),
                "same_structured_jd": (job.model_dump(mode="json") if job else None)
                == row["structured_jd"],
                "candidate_checks": actual,
                "changed_candidates": [
                    {
                        "id": old["id"],
                        "expected": old["expected"],
                        "before": old["actual"],
                        "after": new["actual"],
                    }
                    for old, new in zip(row["candidate_checks"], actual, strict=True)
                    if old["actual"] != new["actual"]
                ],
            }
        )
    return results


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("directory", type=Path)
    cli.add_argument("--labels", required=True, type=Path)
    cli.add_argument("--output", required=True, type=Path)
    args = cli.parse_args()
    if args.output.exists():
        cli.error("Preserve previous replay")
    manifest_path = args.directory / "manifest.json"
    predictions_path = args.directory / "predictions.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = json.loads(predictions_path.read_text(encoding="utf-8"))["results"]
    cases = json.loads(args.labels.read_text(encoding="utf-8"))["cases"]
    expected = {
        (c["id"], m, r)
        for c in cases
        for m in ("single_call", "two_stage")
        for r in range(1, manifest["repeats"] + 1)
    }
    keys = [(r["case_id"], r["mode"], r["repeat"]) for r in rows]
    if set(keys) != expected or len(keys) != len(expected):
        cli.error("Complete unique recorded pairs required")
    if (
        manifest["source_hashes"].get(args.labels.as_posix())
        != hashlib.sha256(args.labels.read_bytes()).hexdigest()
    ):
        cli.error("Reference labels must match the recorded manifest")
    results = asyncio.run(replay(rows, cases, manifest))
    report = {
        "live_model_calls": 0,
        "purpose": "Local behavior on fixed recorded responses; no fresh inference or latency measurement.",
        "runs": len(results),
        "same_failures_and_call_paths": all(
            r["same_failure"] and r["same_call_path"] for r in results
        ),
        "same_compiled_jobs": all(r["same_structured_jd"] for r in results),
        "modes": {
            mode: {
                field: decision_metrics(
                    [
                        c
                        for r in results
                        if r["mode"] == mode
                        for c in r["candidate_checks"]
                        if field in c["expected"]
                    ],
                    field,
                )
                for field in ("education", "eligibility")
            }
            for mode in ("single_call", "two_stage")
        },
        "results": results,
        "source_hashes": {
            p.as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(
                set(Path("src").rglob("*.py"))
                | {manifest_path, predictions_path, args.labels, Path(__file__)}
            )
        },
    }
    write(args.output, report)
    print(
        json.dumps(
            {
                "runs": len(results),
                "same_failures_and_call_paths": report["same_failures_and_call_paths"],
                "changes": [
                    {
                        k: r[k]
                        for k in ("case_id", "mode", "repeat", "changed_candidates")
                    }
                    for r in results
                    if r["changed_candidates"]
                ],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
