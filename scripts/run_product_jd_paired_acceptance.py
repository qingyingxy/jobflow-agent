"""Frozen paired test100 regression plus preregistered education acceptance."""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from scripts.compare_product_jd_execution import assess
from scripts.run_product_jd_execution_evaluation import (
    DATASET,
    SHARED_FACT_FIELDS,
    file_hash,
    summarize,
    write_json,
)
from src.config import Settings
from src.domain.eligibility import (
    CandidateProfileInput,
    EligibilityInput,
    SearchPreferences,
)
from src.domain.job import RawJobDocument
from src.evaluation.product_metrics import evaluate_product_dataset
from src.infrastructure.llm_client import create_structured_model_client
from src.services.eligibility_checker import check_eligibility
from src.services.jd_parser import JDParserError
from src.services.product_jd_execution import ProductJDExecutionParser

MODES = ("single_call", "two_stage")
EDUCATION_LABELS = Path("datasets/product_jd_education_acceptance_v1_20261009.json")


class RecordingClient:
    def __init__(self, client):
        self.client = client
        self.calls = []

    def __getattr__(self, name):
        return getattr(self.client, name)

    async def generate(self, request):
        started = perf_counter()
        record = {"schema_name": request.schema_name, "status": "started"}
        self.calls.append(record)
        try:
            response = await self.client.generate(request)
        except BaseException as error:
            details = getattr(error, "details", {}) or {}
            record.update(
                status="failed_or_cancelled",
                error_code=getattr(error, "code", type(error).__name__),
                error_details={
                    k: details[k]
                    for k in ("status_code", "usage", "finish_reason")
                    if k in details
                },
            )
            raise
        else:
            record.update(
                status="returned",
                output=response.output,
                model=response.model,
                usage=response.usage,
                response_id=response.response_id,
                finish_reason=response.finish_reason,
            )
            return response
        finally:
            record["duration_ms"] = round((perf_counter() - started) * 1000, 2)


def qualifications(job, labels):
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
            # An absent executable predicate cannot count as a confirmed pass.
            education = (
                "fail"
                if any(c.result == "fail" for c in checks)
                else "unknown"
                if not checks or any(c.result == "unknown" for c in checks)
                else "pass"
            )
            actual = {
                "education": education,
                "eligibility": result.eligible,
                "checks": [c.model_dump(mode="json") for c in result.checks],
            }
        rows.append(
            {
                "id": label["id"],
                "expected": {k: label[k] for k in ("education", "eligibility")},
                "actual": actual,
            }
        )
    return rows


def decision_metrics(decisions, field):
    """Unavailable predictions remain in the accuracy and class denominators."""
    confusion = Counter()
    for row in decisions:
        expected = row["expected"][field]
        actual = row["actual"][field] if row["actual"] else "unavailable"
        confusion[(expected, actual)] += 1
    support = {
        label: sum(v for (e, _), v in confusion.items() if e == label)
        for label in ("pass", "fail", "unknown")
    }
    count = len(decisions)
    correct = sum(v for (e, a), v in confusion.items() if e == a)
    wrong_pass = sum(
        v for (e, a), v in confusion.items() if a == "pass" and e != "pass"
    )
    wrong_fail = sum(
        v for (e, a), v in confusion.items() if a == "fail" and e != "fail"
    )
    missed = sum(
        v for (e, a), v in confusion.items() if e in {"pass", "fail"} and a == "unknown"
    )
    return {
        "total": count,
        "correct": correct,
        "accuracy": correct / count if count else None,
        "support": support,
        "confusion": {
            e: {a: confusion[e, a] for a in ("pass", "fail", "unknown", "unavailable")}
            for e in ("pass", "fail", "unknown")
        },
        "wrong_pass": wrong_pass,
        "wrong_fail": wrong_fail,
        "false_exclusion_of_expected_pass": confusion["pass", "fail"],
        "false_exclusion_rate": confusion["pass", "fail"] / support["pass"]
        if support["pass"]
        else None,
        "missed_determinate_as_unknown": missed,
        "expected_unknown_correct": confusion["unknown", "unknown"],
        "unavailable": sum(v for (_, a), v in confusion.items() if a == "unavailable"),
    }


def validate_inputs(dataset, labels):
    ids = [c["id"] for c in dataset["cases"]]
    if not ids or len(ids) != len(set(ids)):
        raise ValueError("Real JD identifiers must be unique and nonempty")
    evaluate_product_dataset(dataset, {"predictions": []})
    annotated = [c["case_id"] for c in labels["real_annotations"]]
    if len(set(annotated)) != len(annotated) or not set(annotated) <= set(ids):
        raise ValueError("Real education annotations must refer to unique existing JDs")
    synthetic_ids = [c["id"] for c in labels["synthetic_cases"]]
    if len(set(synthetic_ids)) != len(synthetic_ids) or set(ids) & set(synthetic_ids):
        raise ValueError(
            "Synthetic identifiers must be unique and distinct from real JDs"
        )
    for case in labels["real_annotations"] + labels["synthetic_cases"]:
        decisions = case.get("qualification_labels", case.get("qualifications", []))
        if len({q["id"] for q in decisions}) != len(decisions):
            raise ValueError("Candidate identifiers must be unique within a JD")
        for label in decisions:
            CandidateProfileInput.model_validate(label["profile"])
            if any(
                label[k] not in {"pass", "fail", "unknown"}
                for k in ("education", "eligibility")
            ):
                raise ValueError("Candidate labels must use three-valued decisions")


def pair_integrity(rows, cases):
    counts = Counter((r["case_id"], r["mode"]) for r in rows)
    expected = {(c["id"], mode) for c in cases for mode in MODES}
    return {
        "expected_runs": len(expected),
        "completed_runs": len(rows),
        "complete": set(counts) == expected and all(v == 1 for v in counts.values()),
        "missing": [list(key) for key in sorted(expected - set(counts))],
        "duplicates": [list(key) for key, v in counts.items() if v > 1],
    }


def build_report(dataset, cases, rows, manifest, wall_seconds):
    integrity = pair_integrity(rows, cases)
    report = {
        "manifest": manifest,
        "pairs": integrity,
        "wall_seconds": round(wall_seconds, 3),
        "modes": {},
    }
    for mode in MODES:
        selected = [r for r in rows if r["mode"] == mode]
        real = [r for r in selected if r["case_kind"] == "real_regression"]
        legacy = evaluate_product_dataset(dataset, {"predictions": real})
        fields = {
            f: legacy["facts"]["fields"][f]["value_exact"]["f1"]
            for f in SHARED_FACT_FIELDS
        }
        supported = [v for v in fields.values() if v is not None]
        education = {}
        for kind in ("real_regression", "synthetic_development"):
            candidates = [
                q
                for r in selected
                if r["case_kind"] == kind
                for q in r["qualifications"]
            ]
            education[kind] = {
                f: decision_metrics(candidates, f) for f in ("education", "eligibility")
            }
        semantics = [r for r in selected if r["case_kind"] == "synthetic_development"]
        report["modes"][mode] = {
            "real_execution": summarize(real, wall_seconds) if real else None,
            "all_execution": summarize(selected, wall_seconds) if selected else None,
            "comparable_facts": {
                "fields": fields,
                "value_macro_f1": sum(supported) / len(supported)
                if supported
                else None,
            },
            "legacy_regression": legacy,
            "education_acceptance": education,
            "synthetic_semantics": {
                "total": len(semantics),
                "all_checks_correct": sum(
                    r.get("semantic_correct", False) for r in semantics
                ),
            },
        }
    report["frozen_files_unchanged"] = all(
        file_hash(Path(p)) == digest for p, digest in manifest["source_hashes"].items()
    )
    return report


async def run_paired(cases, settings, args, persist):
    rows = []
    semaphore = asyncio.Semaphore(args.concurrency)

    async def run_case(index, case):
        async with semaphore:
            modes = MODES if index % 2 else tuple(reversed(MODES))
            for mode in modes:
                client = RecordingClient(create_structured_model_client(settings))
                parser = ProductJDExecutionParser(
                    client, mode=mode, validation_retries=args.validation_retries
                )
                document = RawJobDocument(
                    raw_content=case["raw_content"],
                    source_url=case.get("source", {}).get("source_url"),
                    source_type="paired_acceptance",
                )
                started = perf_counter()
                row = {
                    "case_id": case["id"],
                    "case_kind": case["case_kind"],
                    "mode": mode,
                    "output": None,
                    "structured_jd": None,
                    "failure_code": None,
                }
                job = None
                try:
                    async with asyncio.timeout(args.run_timeout):
                        result = await parser.parse_model_output(document)
                        compiled = parser.compile_result(document, result)
                    job = compiled.structured_jd
                    row.update(
                        output=result.output.model_dump(mode="json"),
                        structured_jd=job.model_dump(mode="json"),
                        raw_extraction=result.raw_extraction,
                        raw_relation_judgment=result.raw_relation_judgment,
                        diagnostics={"stages": list(result.stage_diagnostics)},
                    )
                except JDParserError as error:
                    row.update(failure_code=error.code, diagnostics=error.details)
                except TimeoutError:
                    row.update(failure_code="run_timeout")
                except Exception as error:  # noqa: BLE001 - Preserve failed runs in the paired denominator.
                    row.update(failure_code="unexpected_" + type(error).__name__)
                row["qualifications"] = qualifications(
                    job, case.get("qualification_labels", [])
                )
                if case["case_kind"] == "synthetic_development":
                    row["semantic_checks"] = (
                        assess(job, case["expected"]) if job else {}
                    )
                    row["semantic_correct"] = job is not None and all(
                        row["semantic_checks"].values()
                    )
                row.update(
                    duration_ms=round((perf_counter() - started) * 1000, 2),
                    calls=client.calls,
                    model_call_count=len(client.calls),
                )
                rows.append(row)
                persist(rows)
                print(
                    json.dumps(
                        {
                            "completed": len(rows),
                            "total": 2 * len(cases),
                            "case_id": case["id"],
                            "mode": mode,
                            "parsed": job is not None,
                            "failure_code": row["failure_code"],
                            "calls": len(client.calls),
                            "seconds": round(row["duration_ms"] / 1000, 2),
                        }
                    ),
                    flush=True,
                )

    await asyncio.gather(*(run_case(i, case) for i, case in enumerate(cases)))
    return rows


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--dataset", type=Path, default=DATASET)
    cli.add_argument("--education-labels", type=Path, default=EDUCATION_LABELS)
    cli.add_argument("--output-dir", type=Path, required=True)
    cli.add_argument("--live", action="store_true")
    cli.add_argument("--concurrency", type=int, choices=range(1, 5), default=4)
    cli.add_argument("--validation-retries", type=int, choices=(0, 1), default=1)
    cli.add_argument("--request-timeout", type=float, default=180)
    cli.add_argument("--run-timeout", type=float, default=760)
    args = cli.parse_args()
    if args.output_dir.exists():
        cli.error("Use a new directory to preserve previous results")
    if min(args.request_timeout, args.run_timeout) <= 0:
        cli.error("Timeouts must be positive")
    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    labels = json.loads(args.education_labels.read_text(encoding="utf-8"))
    validate_inputs(dataset, labels)
    settings = Settings(llm_max_retries=0).model_copy(
        update={
            "llm_timeout_seconds": args.request_timeout,
            "parser_validation_retries": args.validation_retries,
        }
    )
    if args.live and settings.structured_model_provider == "fake":
        cli.error("Live evaluation needs the configured real provider")
    by_id = {c["case_id"]: c for c in labels["real_annotations"]}
    cases = [
        {
            **c,
            "case_kind": "real_regression",
            "qualification_labels": by_id.get(c["id"], {}).get("qualifications", []),
        }
        for c in dataset["cases"]
    ]
    cases += [
        {**c, "case_kind": "synthetic_development"} for c in labels["synthetic_cases"]
    ]
    files = sorted(
        set(Path("src").rglob("*.py"))
        | {
            Path(__file__).relative_to(Path.cwd())
            if Path(__file__).is_absolute()
            else Path(__file__),
            Path("scripts/compare_product_jd_execution.py"),
            Path("scripts/run_product_jd_execution_evaluation.py"),
            args.dataset,
            args.education_labels,
            Path("pyproject.toml"),
        }
    )
    hashes = {p.as_posix(): file_hash(p) for p in files}
    versions = {}
    for mode in MODES:
        parser = ProductJDExecutionParser(
            create_structured_model_client(settings),
            mode=mode,
            validation_retries=args.validation_retries,
        )
        versions[mode] = {
            "parser": parser.parser_version,
            "schema": parser.schema_version,
            "prompt": parser.prompt_version,
        }
    manifest = {
        "version": "product-jd-paired-acceptance-v1",
        "created_at": datetime.now(UTC).isoformat(),
        "live": args.live,
        "model": settings.llm_model,
        "provider": settings.structured_model_provider,
        "reasoning_effort": settings.llm_reasoning_effort,
        "response_format": settings.llm_response_format,
        "concurrency": args.concurrency,
        "request_timeout": args.request_timeout,
        "run_timeout": args.run_timeout,
        "validation_retries": args.validation_retries,
        "http_retries": 0,
        "case_count": len(cases),
        "real_case_count": len(dataset["cases"]),
        "versions": versions,
        "source_hashes": hashes,
        "limitations": [
            "Test100 is an existing regression set, not an independent holdout.",
            "Education annotations are assistant-created before calls, not independently human-reviewed.",
            "Synthetic cases are development regressions, reported separately from real JDs.",
            "Legacy scores retain frozen labels; education/major/year contract migration prevents direct comparison with old five-field Macro-F1.",
            "Only job_type and locations are directly comparable legacy fact fields.",
            "Eligibility covers current local education/cohort hard checks, not skill suitability or search preferences.",
            "One run per mode and JD; no application cache; failed calls and repairs remain included.",
            "Per-mode duration sums/medians are not separate wall times; wall time is for the combined concurrent experiment.",
        ],
    }
    args.output_dir.mkdir(parents=True)
    for path in files:
        destination = args.output_dir / "sources" / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
    write_json(args.output_dir / "manifest.json", manifest)
    write_json(
        args.output_dir / "cases.json",
        {"cases": cases, "education_annotations": labels},
    )
    if not args.live:
        print(
            json.dumps(
                {"frozen": True, "case_count": len(cases), "model": settings.llm_model},
                ensure_ascii=False,
            )
        )
        return
    started = perf_counter()

    def persist(rows):
        write_json(args.output_dir / "predictions.json", {"results": rows})
        write_json(
            args.output_dir / "progress.json",
            {
                **pair_integrity(rows, cases),
                "elapsed_seconds": round(perf_counter() - started, 2),
            },
        )

    persist([])
    rows = asyncio.run(run_paired(cases, settings, args, persist))
    report = build_report(dataset, cases, rows, manifest, perf_counter() - started)
    write_json(args.output_dir / "report.json", report)
    print(
        json.dumps(
            {
                "pairs": report["pairs"],
                "wall_seconds": report["wall_seconds"],
                "frozen_files_unchanged": report["frozen_files_unchanged"],
                "modes": {
                    m: {k: v for k, v in r.items() if k != "legacy_regression"}
                    for m, r in report["modes"].items()
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
