"""Paired, uncached execution-mode smoke comparison; labels are never sent to models."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from src.config import Settings
from src.domain.eligibility import (
    CandidateProfileInput,
    EligibilityInput,
    SearchPreferences,
)
from src.domain.graduation import classify_graduation_condition
from src.domain.job import RawJobDocument, StructuredJobDescription
from src.infrastructure.llm_client import create_structured_model_client
from src.services.eligibility_checker import check_eligibility
from src.services.jd_parser import JDParserError
from src.services.product_jd_execution import ProductJDExecutionParser


def assess(job, expected):
    """Evaluate labelled behaviors, independently of whether JSON validation passed."""
    requirements = job.requirements or []
    checks = {"requirement_count": len(requirements) == expected["requirement_count"]}
    if "graduation_years" in expected:
        checks["graduation_years"] = (
            job.graduation_years == expected["graduation_years"]
        )
    for index, target in enumerate(expected["relations"]):
        matches = [r for r in requirements if target["contains"] in r.description]
        checks[f"relation_{index}"] = len(matches) == 1 and (
            matches[0].relation == target["relation"]
            and matches[0].mandatory == target["mandatory"]
            and (
                "items" not in target
                or set(matches[0].items or []) == set(target["items"])
            )
        )
    branches = [b for r in requirements if r.education for b in r.education.branches]
    checks["education_count"] = len(branches) == len(expected["education"])
    for index, target in enumerate(expected["education"]):
        checks[f"education_{index}"] = any(
            branch.degree.level == target["level"]
            and branch.degree.operator == target["operator"]
            and branch.major.mode == target["major_mode"]
            and ("scope" not in target or branch.scope == target["scope"])
            and ("status" not in target or branch.status == target["status"])
            and (
                "unresolved" not in target or branch.unresolved == target["unresolved"]
            )
            and (
                "graduation_years" not in target
                or branch.graduation_years == target["graduation_years"]
            )
            for branch in branches
        )
    for index, target in enumerate(expected["qualifications"]):
        result = check_eligibility(
            EligibilityInput(
                job=job,
                profile=CandidateProfileInput.model_validate(target["profile"]),
                preferences=SearchPreferences(),
            ),
            include_search_preferences=False,
        )
        checks[f"qualification_{index}"] = (
            result.eligible == target["eligible"]
            and [c.result for c in result.checks if c.field == "educations"]
            == target["education_results"]
        )
    return checks


class RecordingClient:
    """Keep attempted calls even when an overall time budget cancels a request."""

    def __init__(self, client):
        self.client = client
        self.calls = []

    def __getattr__(self, name):
        return getattr(self.client, name)

    async def generate(self, request):
        record = {"schema_name": request.schema_name, "status": "started"}
        self.calls.append(record)
        try:
            response = await self.client.generate(request)
        except BaseException as error:
            record.update(
                status="failed_or_cancelled",
                error_code=getattr(error, "code", type(error).__name__),
            )
            details = getattr(error, "details", {})
            record["error_details"] = {
                k: details[k]
                for k in ("status_code", "usage", "finish_reason")
                if k in details
            }
            raise
        record.update(
            status="returned",
            usage=response.usage,
            model=response.model,
            output=response.output,
        )
        return response


async def compare(cases, settings, *, run_timeout, persist, concurrency=1):
    results = []
    semaphore = asyncio.Semaphore(concurrency)

    async def run_case(index, case):
        # Alternate order to reduce a systematic warm-up/order advantage.
        modes = (
            ("two_stage", "single_call")
            if index % 2 == 0
            else ("single_call", "two_stage")
        )
        for mode in modes:
            client = RecordingClient(create_structured_model_client(settings))
            parser = ProductJDExecutionParser(
                client, mode=mode, validation_retries=settings.parser_validation_retries
            )
            started = perf_counter()
            result = {
                "case_id": case["id"],
                "mode": mode,
                "parser_version": parser.parser_version,
                "prompt_version": parser.prompt_version,
            }
            try:
                async with asyncio.timeout(run_timeout):
                    parsed = await parser.parse(
                        RawJobDocument(raw_content=case["raw_content"])
                    )
                checks = assess(parsed.structured_jd, case["expected"])
                result.update(
                    status="parsed",
                    checks=checks,
                    correct=all(checks.values()),
                    structured_jd=parsed.structured_jd.model_dump(mode="json"),
                    diagnostics=parsed.diagnostics,
                )
            except JDParserError as error:
                result.update(
                    status="failed",
                    correct=False,
                    error_code=error.code,
                    diagnostics=error.details,
                )
            except TimeoutError:
                result.update(status="failed", correct=False, error_code="run_timeout")
            result.update(
                duration_ms=round((perf_counter() - started) * 1000, 2),
                calls=client.calls,
            )
            results.append(result)
            persist(results)
            print(
                json.dumps(
                    {
                        k: result[k]
                        for k in ("case_id", "mode", "status", "correct", "duration_ms")
                    }
                ),
                flush=True,
            )

    async def bounded_case(index, case):
        async with semaphore:
            await run_case(index, case)

    await asyncio.gather(*(bounded_case(i, case) for i, case in enumerate(cases)))
    return results


def summary(results):
    output = {}
    for mode in ("two_stage", "single_call"):
        selected = [r for r in results if r["mode"] == mode]
        usages = [c.get("usage") for r in selected for c in r["calls"]]
        known = [u for u in usages if isinstance(u, dict)]
        output[mode] = {
            "runs": len(selected),
            "parsed": sum(r["status"] == "parsed" for r in selected),
            "correct_cases": sum(r["correct"] for r in selected),
            "model_call_count": sum(len(r["calls"]) for r in selected),
            "duration_ms": sum(r["duration_ms"] for r in selected),
            "known_input_tokens": sum(
                u.get("prompt_tokens", u.get("input_tokens", 0)) for u in known
            ),
            "known_output_tokens": sum(
                u.get("completion_tokens", u.get("output_tokens", 0)) for u in known
            ),
            "usage_complete": len(known) == len(usages),
        }
    return output


def replay_cohort_classification(source_report):
    """Re-evaluate only local cohort classification; preserve original model outcomes."""
    cases = {case["id"]: case for case in source_report["corpus"]["cases"]}
    rows = []
    for previous in source_report["results"]:
        row = {
            "case_id": previous["case_id"],
            "mode": previous["mode"],
            "correct": False,
        }
        if previous["status"] == "parsed":
            job = StructuredJobDescription.model_validate(previous["structured_jd"])
            if job.graduation_source_text:
                job.graduation_condition_kind = classify_graduation_condition(
                    job.graduation_source_text
                )
            checks = assess(job, cases[previous["case_id"]]["expected"])
            row.update(
                checks=checks,
                correct=all(checks.values()),
                graduation_condition_kind=job.graduation_condition_kind,
            )
        rows.append(row)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cases",
        type=Path,
        default=Path("datasets/product_jd_execution_smoke_v1.json"),
    )
    parser.add_argument("--output", type=Path, required=True)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument(
        "--live",
        action="store_true",
        help="Use the configured model; without this flag only freeze the experiment manifest.",
    )
    actions.add_argument(
        "--replay",
        type=Path,
        help="Re-evaluate a saved report with the current local cohort classifier; no model calls.",
    )
    parser.add_argument("--request-timeout", type=float)
    parser.add_argument("--run-timeout", type=float)
    parser.add_argument("--concurrency", type=int, choices=range(1, 5), default=1)
    args = parser.parse_args()
    settings = Settings(llm_max_retries=0)
    args.request_timeout = args.request_timeout or settings.llm_timeout_seconds
    args.run_timeout = args.run_timeout or 4 * args.request_timeout + 40
    settings = settings.model_copy(update={"llm_timeout_seconds": args.request_timeout})
    corpus = json.loads(args.cases.read_text(encoding="utf-8"))
    if args.output.exists():
        parser.error(
            "Output already exists; choose a new path to preserve previous results."
        )
    if min(args.request_timeout, args.run_timeout) <= 0:
        parser.error("Timeouts must be positive")
    if args.live and settings.structured_model_provider == "fake":
        parser.error("Live comparison requires a configured real model")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.replay:
        original = json.loads(args.replay.read_text(encoding="utf-8"))
        rows = replay_cohort_classification(original)
        report = {
            "version": "product-jd-cohort-local-replay-v1",
            "source_report": str(args.replay),
            "source_report_sha256": hashlib.sha256(
                args.replay.read_bytes()
            ).hexdigest(),
            "cases_sha256": original["cases_sha256"],
            "cohort_classifier_sha256": hashlib.sha256(
                Path("src/domain/graduation.py").read_bytes()
            ).hexdigest(),
            "model_call_count": 0,
            "results": rows,
            "limitations": "Local replay of already observed development outputs; not a new model evaluation or holdout.",
        }
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "model_call_count": 0,
                    "correct": sum(r["correct"] for r in rows),
                    "runs": len(rows),
                }
            )
        )
        return
    report = {
        "version": "product-jd-execution-comparison-v1",
        "created_at": datetime.now(UTC).isoformat(),
        "cases_sha256": hashlib.sha256(args.cases.read_bytes()).hexdigest(),
        "corpus": corpus,
        "live": args.live,
        "model": settings.llm_model,
        "provider": settings.structured_model_provider,
        "reasoning_effort": settings.llm_reasoning_effort,
        "response_format": settings.llm_response_format,
        "request_timeout": args.request_timeout,
        "run_timeout": args.run_timeout,
        "concurrency": args.concurrency,
        "validation_retries": settings.parser_validation_retries,
        "http_retries": 0,
        "results": [],
        "limitations": "Synthetic smoke cases, one run per mode; no statistical accuracy or cost claim. No parsing cache. Usage may be incomplete on failed calls.",
    }
    report["implementation_hashes"] = {
        str(path): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in [
            Path(__file__),
            Path("src/services/product_jd_execution.py"),
            Path("src/services/product_jd_education_parser.py"),
            Path("src/services/product_jd_parser.py"),
            Path("src/domain/product_jd.py"),
            Path("src/domain/education.py"),
            Path("src/domain/product_jd_single_call.py"),
            Path("src/services/product_jd_single_call_prompt.py"),
            Path("src/domain/graduation.py"),
            Path("src/services/eligibility_checker.py"),
            Path("src/services/education_evaluator.py"),
        ]
    }

    def persist(results):
        report["results"] = results
        report["summary"] = summary(results)
        temporary = args.output.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        temporary.replace(args.output)

    # Freeze labels/configuration before the first external request.
    persist([])
    if args.live:
        asyncio.run(
            compare(
                corpus["cases"],
                settings,
                run_timeout=args.run_timeout,
                persist=persist,
                concurrency=args.concurrency,
            )
        )
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
