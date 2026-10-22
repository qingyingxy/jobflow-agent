"""No-network replay of recorded calls through the current runtime and compiler."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path

from scripts.run_product_jd_paired_acceptance import (
    decision_metrics,
    pair_integrity,
    qualifications,
    write_json,
)
from src.domain.job import RawJobDocument
from src.infrastructure.llm_client import (
    ModelClientError,
    ModelResponseError,
    ModelTimeoutError,
    ModelUnavailableError,
    StructuredModelResponse,
)
from src.services.jd_parser import JDParserError
from src.services.product_jd_execution import ProductJDExecutionParser


class RecordedClient:
    provider = "recorded_no_network"

    def __init__(self, calls, model):
        self.calls, self.model_name, self.consumed = calls, model, 0

    async def generate(self, request):
        if self.consumed == len(self.calls):
            raise AssertionError("Current runtime requested an unrecorded call")
        call = self.calls[self.consumed]
        self.consumed += 1
        if request.schema_name != call["schema_name"]:
            raise AssertionError("Current runtime changed the recorded call path")
        if call["status"] != "returned":
            error_type = {
                "model_timeout": ModelTimeoutError,
                "model_unavailable": ModelUnavailableError,
                "model_response_invalid": ModelResponseError,
            }.get(call["error_code"], ModelClientError)
            error = error_type(
                "Replay of recorded model failure", call.get("error_details", {})
            )
            error.code = call["error_code"]
            raise error
        return StructuredModelResponse(
            output=call["output"],
            model=call["model"],
            provider=self.provider,
            usage=call.get("usage"),
            response_id=call.get("response_id"),
            finish_reason=call.get("finish_reason"),
        )


async def replay(rows, cases, model):
    by_id = {c["id"]: c for c in cases}
    results = []
    for row in rows:
        client = RecordedClient(row["calls"], model)
        parser = ProductJDExecutionParser(client, mode=row["mode"])
        case = by_id[row["case_id"]]
        doc = RawJobDocument(
            raw_content=case["raw_content"],
            source_url=case.get("source", {}).get("source_url"),
            source_type="paired_acceptance",
        )
        job, failure = None, None
        try:
            parsed = await parser.parse(doc)
            job = parsed.structured_jd
        except JDParserError as error:
            failure = error.code
        actual = qualifications(job, case.get("qualification_labels", []))
        results.append(
            {
                "case_id": row["case_id"],
                "case_kind": row["case_kind"],
                "mode": row["mode"],
                "failure_code": failure,
                "same_failure_code": failure == row["failure_code"],
                "same_call_path": client.consumed == len(row["calls"]),
                "same_structured_jd": job.model_dump(mode="json")
                == row["structured_jd"]
                if job
                else row["structured_jd"] is None,
                "structured_jd": job.model_dump(mode="json") if job else None,
                "qualifications": actual,
            }
        )
    return results


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("directory", type=Path)
    cli.add_argument("--output", required=True, type=Path)
    args = cli.parse_args()
    if args.output.exists():
        cli.error("Use a fresh output path")
    paths = [
        args.directory / name
        for name in ("predictions.json", "cases.json", "manifest.json")
    ]
    rows = json.loads(paths[0].read_text(encoding="utf-8"))["results"]
    cases = json.loads(paths[1].read_text(encoding="utf-8"))["cases"]
    manifest = json.loads(paths[2].read_text(encoding="utf-8"))
    if not pair_integrity(rows, cases)["complete"]:
        cli.error("Recorded pairs must be complete and unique")
    results = asyncio.run(replay(rows, cases, manifest["model"]))
    report = {
        "live_model_calls": 0,
        "purpose": "Current runtime on fixed recorded responses; not fresh model inference or latency.",
        "source_hashes": {
            p.as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(
                set(Path("src").rglob("*.py")) | set(paths) | {Path(__file__)}
            )
        },
        "runs": len(results),
        "same_failures_and_call_paths": all(
            r["same_failure_code"] and r["same_call_path"] for r in results
        ),
        "changed_jds": [
            {"case_id": r["case_id"], "mode": r["mode"]}
            for r in results
            if not r["same_structured_jd"]
        ],
        "modes": {},
        "results": results,
    }
    for mode in ("single_call", "two_stage"):
        report["modes"][mode] = {}
        for kind in ("real_regression", "synthetic_development"):
            decisions = [
                q
                for r in results
                if r["mode"] == mode and r["case_kind"] == kind
                for q in r["qualifications"]
            ]
            report["modes"][mode][kind] = {
                f: decision_metrics(decisions, f) for f in ("education", "eligibility")
            }
    write_json(args.output, report)
    print(
        json.dumps(
            {k: v for k, v in report.items() if k not in ("results", "source_hashes")},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
