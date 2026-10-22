"""Evaluate the runtime JD parser against existing frozen labels, without rewriting them."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from time import perf_counter

from src.config import Settings
from src.domain.job import RawJobDocument
from src.evaluation.product_metrics import evaluate_product_dataset
from src.infrastructure.llm_client import create_structured_model_client
from src.services.jd_parser import JDParserError
from src.services.product_jd_execution import ProductJDExecutionParser

DATASET = Path(
    "artifacts/evaluation/product-jd-test100-human-reviewed-v1-2026-09-09.json"
)
SHARED_FACT_FIELDS = ("job_type", "locations")
LEGACY_GLOBAL_FACT_FIELDS = (*SHARED_FACT_FIELDS, "graduation_years")
FROZEN_FILES = (
    DATASET,
    Path("src/services/product_jd_parser.py"),
    Path("src/services/product_jd_runtime_parser.py"),
    Path("src/domain/product_jd.py"),
    Path("src/evaluation/product_metrics.py"),
)


def write_json(path, payload):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RecordingClient:
    def __init__(self, client):
        self.client = client
        self.calls = []

    def __getattr__(self, name):
        return getattr(self.client, name)

    async def generate(self, request):
        record = {"schema_name": request.schema_name, "status": "started"}
        self.calls.append(record)
        started = perf_counter()
        try:
            response = await self.client.generate(request)
        except BaseException as error:
            record.update(
                status="failed_or_cancelled",
                error_code=getattr(error, "code", type(error).__name__),
                duration_ms=round((perf_counter() - started) * 1000, 2),
            )
            raise
        record.update(
            status="returned",
            duration_ms=round((perf_counter() - started) * 1000, 2),
            output=response.output,
            model=response.model,
            usage=response.usage,
            response_id=response.response_id,
            finish_reason=response.finish_reason,
        )
        return response


async def predict(dataset, settings, args, persist):
    semaphore = asyncio.Semaphore(args.concurrency)

    async def run_case(case):
        async with semaphore:
            client = RecordingClient(create_structured_model_client(settings))
            parser = ProductJDExecutionParser(
                client,
                mode=args.mode,
                validation_retries=args.validation_retries,
            )
            started = perf_counter()
            document = RawJobDocument(
                raw_content=case["raw_content"],
                source_url=case["source"]["source_url"],
                source_type="product_evaluation",
                source_metadata={
                    "company": case["source"]["company"],
                    "title": case["source"]["title"],
                },
            )
            row = {"case_id": case["id"], "output": None, "failure_code": None}
            try:
                async with asyncio.timeout(args.run_timeout):
                    result = await parser.parse_model_output(document)
                row.update(
                    output=result.output.model_dump(mode="json"),
                    raw_extraction=result.raw_extraction,
                    raw_relation_judgment=result.raw_relation_judgment,
                    diagnostics={"stages": list(result.stage_diagnostics)},
                )
            except JDParserError as error:
                row.update(failure_code=error.code, diagnostics=error.details)
            except TimeoutError:
                row.update(failure_code="run_timeout", diagnostics={})
            row.update(
                duration_ms=round((perf_counter() - started) * 1000, 2),
                model_call_count=len(client.calls),
                calls=client.calls,
            )
            return row

    rows = []
    tasks = [asyncio.create_task(run_case(case)) for case in dataset["cases"]]
    for task in asyncio.as_completed(tasks):
        row = await task
        rows.append(row)
        persist(rows)
        print(
            json.dumps(
                {
                    "completed": len(rows),
                    "total": len(tasks),
                    "case_id": row["case_id"],
                    "parsed": row["output"] is not None,
                    "failure_code": row["failure_code"],
                    "model_call_count": row["model_call_count"],
                    "duration_ms": row["duration_ms"],
                }
            ),
            flush=True,
        )
    return rows


def summarize(rows, wall_seconds):
    calls = [call for row in rows for call in row["calls"]]
    usages = [call.get("usage") for call in calls]
    known = [usage for usage in usages if isinstance(usage, dict)]
    durations = sorted(row["duration_ms"] / 1000 for row in rows)
    return {
        "attempted": len(rows),
        "parsed": sum(row["output"] is not None for row in rows),
        "failures": dict(Counter(r["failure_code"] for r in rows if r["failure_code"])),
        "model_call_count": len(calls),
        "calls_per_case": dict(Counter(str(r["model_call_count"]) for r in rows)),
        "wall_seconds": round(wall_seconds, 3),
        "case_duration_sum_seconds": round(sum(durations), 3),
        "case_duration_median_seconds": median(durations),
        "case_duration_p95_seconds": durations[
            max(0, (95 * len(durations) + 99) // 100 - 1)
        ],
        "known_input_tokens": sum(
            u.get("prompt_tokens", u.get("input_tokens", 0)) for u in known
        ),
        "known_output_tokens": sum(
            u.get("completion_tokens", u.get("output_tokens", 0)) for u in known
        ),
        "usage_complete": len(known) == len(usages),
    }


def main():
    argument_parser = argparse.ArgumentParser(description=__doc__)
    argument_parser.add_argument("--dataset", type=Path, default=DATASET)
    argument_parser.add_argument("--output-dir", type=Path, required=True)
    argument_parser.add_argument(
        "--mode", choices=("single_call", "two_stage"), default="single_call"
    )
    argument_parser.add_argument("--live", action="store_true")
    argument_parser.add_argument(
        "--concurrency", type=int, choices=range(1, 5), default=2
    )
    argument_parser.add_argument(
        "--validation-retries", type=int, choices=(0, 1), default=1
    )
    argument_parser.add_argument("--request-timeout", type=float)
    argument_parser.add_argument("--run-timeout", type=float)
    args = argument_parser.parse_args()
    if args.output_dir.exists():
        argument_parser.error(
            "Choose a new output directory; existing results are never overwritten."
        )
    settings = Settings(llm_max_retries=0)
    if args.request_timeout is None:
        args.request_timeout = settings.llm_timeout_seconds
    if args.run_timeout is None:
        requests = (1 if args.mode == "single_call" else 2) * (
            args.validation_retries + 1
        )
        args.run_timeout = requests * args.request_timeout + 40
    if min(args.request_timeout, args.run_timeout) <= 0:
        argument_parser.error("Timeouts must be positive")
    settings = settings.model_copy(update={"llm_timeout_seconds": args.request_timeout})
    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    if not dataset["cases"] or len({c["id"] for c in dataset["cases"]}) != len(
        dataset["cases"]
    ):
        argument_parser.error("Cases must be nonempty and have unique identifiers")
    # Validate all existing labels before spending any model calls.
    evaluate_product_dataset(dataset, {"predictions": []})
    if args.live and settings.structured_model_provider == "fake":
        argument_parser.error("Live evaluation requires a configured real model")
    parser = ProductJDExecutionParser(
        create_structured_model_client(settings),
        mode=args.mode,
        validation_retries=args.validation_retries,
    )
    hashes = {str(p): file_hash(p) for p in (*FROZEN_FILES, args.dataset)}
    implementation_hashes = {
        str(p): file_hash(p)
        for p in (
            Path(__file__),
            Path("src/services/product_jd_execution.py"),
            Path("src/services/product_jd_education_parser.py"),
            Path("src/domain/education.py"),
            Path("src/domain/graduation.py"),
            Path("src/infrastructure/llm_client.py"),
        )
    }
    manifest = {
        "version": "product-runtime-jd-evaluation-v1",
        "evaluation_kind": "regression_on_existing_annotations",
        "created_at": datetime.now(UTC).isoformat(),
        "live": args.live,
        "mode": args.mode,
        "case_count": len(dataset["cases"]),
        "dataset_version": dataset["dataset_version"],
        "parser_version": parser.parser_version,
        "schema_version": parser.schema_version,
        "prompt_version": parser.prompt_version,
        "model": settings.llm_model,
        "provider": settings.structured_model_provider,
        "reasoning_effort": settings.llm_reasoning_effort,
        "response_format": settings.llm_response_format,
        "concurrency": args.concurrency,
        "request_timeout": args.request_timeout,
        "run_timeout": args.run_timeout,
        "validation_retries": args.validation_retries,
        "http_retries": 0,
        "frozen_file_hashes": hashes,
        "implementation_hashes": implementation_hashes,
        "limitations": [
            "Existing test-100 is a regression set for this new mode, not a new independent holdout.",
            "Runtime education and major constraints live in requirement branches; old labels store global facts.",
            "Graduation years may also move into education branches; do not flatten them for higher scores.",
            "Legacy five-field and requirement scores are retained unchanged; contract differences affect them.",
            "Comparable non-education fact score covers job type and location only, including failed cases.",
            "No gold candidate profiles or education predicate labels: qualification accuracy is not scored.",
            "One run per case; validation repair is allowed, but failed cases are not rerun or removed.",
            "Parallel wall time cannot be compared to historical runs with different concurrency/configuration.",
        ],
    }
    args.output_dir.mkdir(parents=True)
    write_json(args.output_dir / "manifest.json", manifest)
    if not args.live:
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return
    order = {case["id"]: index for index, case in enumerate(dataset["cases"])}

    def prediction_payload(rows):
        return {
            "prediction_version": args.output_dir.name,
            "dataset_version": dataset["dataset_version"],
            "model": settings.llm_model,
            "mode": args.mode,
            "parser_version": parser.parser_version,
            "schema_version": parser.schema_version,
            "prompt_version": parser.prompt_version,
            "predictions": sorted(rows, key=lambda row: order[row["case_id"]]),
        }

    def persist(rows):
        write_json(args.output_dir / "predictions.json", prediction_payload(rows))

    persist([])
    started = perf_counter()
    rows = asyncio.run(predict(dataset, settings, args, persist))
    wall_seconds = perf_counter() - started
    report = evaluate_product_dataset(dataset, prediction_payload(rows))
    values = {
        field: report["facts"]["fields"][field]["value_exact"]["f1"]
        for field in SHARED_FACT_FIELDS
    }
    supported = [value for value in values.values() if value is not None]
    legacy_values = {
        field: report["facts"]["fields"][field]["value_exact"]["f1"]
        for field in LEGACY_GLOBAL_FACT_FIELDS
    }
    legacy_supported = [value for value in legacy_values.values() if value is not None]
    report.update(
        context=manifest,
        execution=summarize(rows, wall_seconds),
        comparable_facts={
            "fields": values,
            "field_count": len(supported),
            "value_macro_f1": sum(supported) / len(supported) if supported else None,
        },
        legacy_three_global_facts={
            "fields": legacy_values,
            "field_count": len(legacy_supported),
            "value_macro_f1": (
                sum(legacy_supported) / len(legacy_supported)
                if legacy_supported
                else None
            ),
            "directly_comparable": False,
        },
        frozen_files_unchanged=all(
            file_hash(Path(path)) == digest for path, digest in hashes.items()
        ),
    )
    write_json(args.output_dir / "report.json", report)
    print(
        json.dumps(
            {
                "metrics": report["primary_metrics"],
                "comparable_facts": report["comparable_facts"],
                "legacy_three_global_facts": report["legacy_three_global_facts"],
                "execution": report["execution"],
                "frozen_files_unchanged": report["frozen_files_unchanged"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
