"""Repeat a frozen unseen-JD comparison using the production recovery policy."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import itertools
import json
import math
import shutil
import statistics
import unicodedata
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from urllib.parse import urlsplit

from scripts.run_product_jd_paired_acceptance import RecordingClient, decision_metrics
from src.config import Settings
from src.domain.eligibility import (
    CandidateProfileInput,
    EligibilityInput,
    SearchPreferences,
)
from src.domain.job import RawJobDocument
from src.infrastructure.llm_client import create_structured_model_client
from src.services.analysis_runtime import create_product_parser
from src.services.eligibility_checker import check_eligibility
from src.services.jd_parser import JDParserError

MODES = ("single_call", "two_stage")


def write(path, value):
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize(text):
    return "".join(unicodedata.normalize("NFKC", text).casefold().split())


def overlap(source, quote):
    # Quotes remain literal source substrings; allow an extraction to split a span.
    source, quote = normalize(source), normalize(quote)
    if quote in source:
        return 1.0
    if source in quote:
        return len(source) / len(quote)
    return 0.0


def relation_checks(output, probes):
    requirements = output.get("requirements", []) if output else []
    checks = []
    for probe in probes:
        matching = [
            r
            for r in requirements
            if overlap(r["source_text"], probe["source_text"]) >= 0.5
        ]
        passed = False
        for requirement in matching:
            if (requirement["relation"], requirement["level"]) != (
                probe["relation"],
                probe["level"],
            ):
                continue
            if probe["relation"] == "any_of":
                choices = [
                    [
                        i
                        for i, item in enumerate(requirement["items"])
                        if normalize(option) in normalize(item)
                    ]
                    for option in probe["options"]
                ]
                passed = any(
                    len(set(indices)) == len(indices)
                    for indices in itertools.product(*choices)
                )
            else:
                # A shared mandatory term must not be swallowed by an alternative.
                passed = overlap(
                    requirement["source_text"], probe["source_text"]
                ) >= 0.8 and not any(
                    r["relation"] == "any_of"
                    and overlap(r["source_text"], probe["source_text"]) >= 0.8
                    for r in matching
                )
            if passed:
                break
        checks.append({"expected": probe, "passed": passed})
    return checks


def candidate_checks(job, labels):
    rows = []
    for label in labels:
        actual = None
        if job is not None:
            result = check_eligibility(
                EligibilityInput(
                    job=job,
                    profile=CandidateProfileInput.model_validate(label["profile"]),
                    preferences=SearchPreferences(),
                ),
                include_search_preferences=False,
            )
            checks = [c for c in result.checks if c.field == "educations"]
            education = (
                "fail"
                if any(c.result == "fail" for c in checks)
                else "unknown"
                if not checks or any(c.result == "unknown" for c in checks)
                else "pass"
            )
            actual = {"education": education, "eligibility": result.eligible}
        rows.append(
            {
                "id": label["id"],
                "expected": {
                    k: label[k] for k in ("education", "eligibility") if k in label
                },
                "actual": actual,
            }
        )
    return rows


def summarize(rows):
    report = {}
    for mode in MODES:
        selected = [r for r in rows if r["mode"] == mode]
        durations = sorted(r["duration_ms"] / 1000 for r in selected)
        probes = [p for r in selected for p in r["relation_checks"]]
        candidates = [q for r in selected for q in r["candidate_checks"]]
        report[mode] = {
            "runs": len(selected),
            "parsed": sum(r["output"] is not None for r in selected),
            "calls": sum(len(r["calls"]) for r in selected),
            "duration_median_seconds": statistics.median(durations),
            "duration_p95_seconds": durations[math.ceil(0.95 * len(durations)) - 1],
            "failures": dict(
                Counter(r["failure_code"] for r in selected if r["failure_code"])
            ),
            "relation_probes": {
                "total": len(probes),
                "correct": sum(p["passed"] for p in probes),
            },
            "candidate_decisions": {
                field: decision_metrics(
                    [q for q in candidates if field in q["expected"]], field
                )
                for field in ("education", "eligibility")
            },
            "recovered_transport_attempts": sum(
                a.get("retry_scheduled", False)
                for r in selected
                for a in r["diagnostics"].get("attempts", [])
            ),
        }
    return report


async def run(cases, settings, *, repeats, concurrency, root):
    rows, semaphore = [], asyncio.Semaphore(concurrency)

    async def run_pair(index, case, repeat):
        async with semaphore:
            modes = MODES if (index + repeat) % 2 else tuple(reversed(MODES))
            for mode in modes:
                configured = settings.model_copy(update={"product_parse_mode": mode})
                client = RecordingClient(create_structured_model_client(configured))
                parser = create_product_parser(client, configured)
                started = perf_counter()
                output = job = None
                diagnostics, failure = {}, None
                try:
                    result = await parser.parse_model_output(
                        RawJobDocument(
                            raw_content=case["raw_content"],
                            source_url=case["source_url"],
                        )
                    )
                    output = result.output.model_dump(mode="json")
                    job = parser.compile_result(
                        RawJobDocument(
                            raw_content=case["raw_content"],
                            source_url=case["source_url"],
                        ),
                        result,
                    ).structured_jd
                    diagnostics = {"attempts": list(result.stage_diagnostics)}
                except JDParserError as error:
                    failure, diagnostics = error.code, error.details
                    output = job = None
                except Exception as error:  # noqa: BLE001 - Keep every failed run in the paired denominator.
                    failure = "unexpected_" + type(error).__name__
                    output = job = None
                row = {
                    "case_id": case["id"],
                    "mode": mode,
                    "repeat": repeat,
                    "output": output,
                    "structured_jd": job.model_dump(mode="json") if job else None,
                    "failure_code": failure,
                    "diagnostics": diagnostics,
                    "calls": client.calls,
                    "duration_ms": round((perf_counter() - started) * 1000, 2),
                    "relation_checks": relation_checks(output, case["relation_probes"]),
                    "candidate_checks": candidate_checks(
                        job, case["qualification_labels"]
                    ),
                }
                rows.append(row)
                write(root / "predictions.json", {"results": rows})
                print(
                    json.dumps(
                        {
                            "completed": len(rows),
                            "total": len(cases) * 2 * repeats,
                            "case_id": case["id"],
                            "mode": mode,
                            "repeat": repeat,
                            "parsed": output is not None,
                            "failure_code": failure,
                            "seconds": round(row["duration_ms"] / 1000, 2),
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )

    for repeat in range(1, repeats + 1):
        await asyncio.gather(*(run_pair(i, c, repeat) for i, c in enumerate(cases)))
    return rows


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--labels", required=True, type=Path)
    cli.add_argument("--output-dir", required=True, type=Path)
    cli.add_argument("--repeats", type=int, choices=(1, 2, 3), default=2)
    cli.add_argument("--concurrency", type=int, choices=(1, 2, 3, 4), default=4)
    cli.add_argument("--live", action="store_true")
    args = cli.parse_args()
    if args.output_dir.exists():
        cli.error("Use a new output directory")
    labels = json.loads(args.labels.read_text(encoding="utf-8"))
    cases = labels["cases"]
    if not cases or len({c["id"] for c in cases}) != len(cases):
        cli.error("Unique nonempty cases required")
    for case in cases:
        for probe in case["relation_probes"]:
            if probe["source_text"] not in case["raw_content"]:
                cli.error("Reference quote missing from JD")
            if probe["relation"] not in {"all_of", "any_of"} or probe["level"] not in {
                "required",
                "preferred",
            }:
                cli.error("Invalid reference relation or strength")
            if probe["relation"] == "any_of" and len(probe["options"]) < 2:
                cli.error("Alternative probes need at least two distinct options")
        for label in case["qualification_labels"]:
            CandidateProfileInput.model_validate(label["profile"])
    settings = Settings(llm_max_retries=0, llm_timeout_seconds=120)
    if args.live and settings.structured_model_provider == "fake":
        cli.error("Live run needs the configured real model")
    files = sorted(
        set(Path("src").rglob("*.py"))
        | {
            Path(__file__).resolve().relative_to(Path.cwd()),
            args.labels,
            args.labels.parent / "sources.json",
            Path("scripts/run_product_jd_paired_acceptance.py"),
            Path("scripts/compare_product_jd_execution.py"),
            Path("scripts/run_product_jd_execution_evaluation.py"),
        }
    )
    hashes = {p.as_posix(): file_hash(p) for p in files}
    args.output_dir.mkdir(parents=True)
    for path in files:
        target = args.output_dir / "sources" / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    manifest = {
        "created_at": datetime.now(UTC).isoformat(),
        "source_hashes": hashes,
        "model": settings.llm_model,
        "provider": settings.structured_model_provider,
        "endpoint_host": urlsplit(settings.llm_base_url or "").hostname,
        "reasoning_effort": settings.llm_reasoning_effort,
        "response_format": settings.llm_response_format,
        "repeats": args.repeats,
        "concurrency": args.concurrency,
        "request_timeout": 120,
        "recovery_policy": {
            k: getattr(settings, k)
            for k in (
                "product_parse_transport_retries",
                "product_parse_retry_backoff_seconds",
                "product_parse_run_timeout_seconds",
                "product_parse_max_model_calls",
                "parser_validation_retries",
            )
        },
        "limitations": labels["limitations"],
        "versions": {
            mode: {
                "parser": parser.parser_version,
                "prompt": parser.prompt_version,
                "schema": parser.schema_version,
            }
            for mode in MODES
            for parser in [
                create_product_parser(
                    create_structured_model_client(settings),
                    settings.model_copy(update={"product_parse_mode": mode}),
                )
            ]
        },
    }
    write(args.output_dir / "manifest.json", manifest)
    if not args.live:
        return
    started = perf_counter()
    rows = asyncio.run(
        run(
            cases,
            settings,
            repeats=args.repeats,
            concurrency=args.concurrency,
            root=args.output_dir,
        )
    )
    expected = {
        (c["id"], m, r)
        for c in cases
        for m in MODES
        for r in range(1, args.repeats + 1)
    }
    actual = {(r["case_id"], r["mode"], r["repeat"]) for r in rows}
    write(
        args.output_dir / "report.json",
        {
            "complete": actual == expected and len(rows) == len(expected),
            "frozen_files_unchanged": all(
                file_hash(Path(p)) == h for p, h in hashes.items()
            ),
            "wall_seconds": round(perf_counter() - started, 3),
            "aggregate": summarize(rows),
            "rounds": {
                str(i): summarize([r for r in rows if r["repeat"] == i])
                for i in range(1, args.repeats + 1)
            },
            "limitations": labels["limitations"],
        },
    )


if __name__ == "__main__":
    main()
