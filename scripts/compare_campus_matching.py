"""Freeze and run a paired local-vs-model campus matching development pilot."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from time import perf_counter

from src.config import Settings
from src.domain.job import JobRequirement
from src.domain.matching import EvidenceRecord
from src.infrastructure.llm_client import create_structured_model_client
from src.services.batch_evidence_matcher import (
    PROMPT_VERSION,
    BatchEvidenceMatcher,
    BatchMatchExecution,
    BatchModelOutput,
    _unknown,
)
from src.services.local_evidence_matcher import match_requirements_locally

DEFAULT_SPEC = Path("datasets/campus_matching_pilot_v1.json")
IMPLEMENTATIONS = [
    "scripts/compare_campus_matching.py",
    "src/services/batch_evidence_matcher.py",
    "src/services/local_evidence_matcher.py",
    "src/services/ordinary_requirement_evaluator.py",
    "src/domain/skill_normalizer.py",
    "src/domain/job.py",
    "src/domain/matching.py",
    "src/domain/education.py",
    "src/domain/eligibility.py",
    "src/services/education_evaluator.py",
    "src/infrastructure/llm_client.py",
]


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def select_cases(spec, source):
    ordered = sorted(
        source["cases"],
        key=lambda r: hashlib.sha256(
            f"{spec['selection']['seed']}:{r['id']}".encode()
        ).hexdigest(),
    )
    selected, companies = [], set()
    for row in ordered:
        if row["source"]["company"] in companies or not row["expected"]["requirements"]:
            continue
        companies.add(row["source"]["company"])
        selected.append(row)
        if len(selected) == spec["selection"]["jobs"]:
            break
    if {row["id"] for row in selected} != set(spec["references"]):
        raise ValueError("Frozen references do not match deterministic selection")
    cases = []
    for row in selected:
        if row["split"] != "development":
            raise ValueError("Only opened development samples are permitted")
        annotation = spec["references"][row["id"]]
        requirements = row["expected"]["requirements"]
        if set(annotation["labels"]) | set(annotation["exclude"]) != {
            str(i) for i in range(len(requirements))
        }:
            raise ValueError(
                "Every requirement must have a predeclared reference or exclusion"
            )
        prepared = []
        for i, item in enumerate(requirements):
            if str(i) in annotation["exclude"]:
                continue
            if " ".join(item["source_text"].split()) not in " ".join(
                row["raw_content"].split()
            ):
                raise ValueError(
                    f"Requirement is not grounded in archived JD: {row['id']}:{i}"
                )
            requirement = JobRequirement(
                category="required_skill"
                if item["level"] == "required"
                else "preferred_skill",
                mandatory=item["level"] == "required",
                name=item["source_text"][:120],
                description=item["source_text"],
                relation=item["relation"],
                items=item["items"],
            )
            prepared.append(
                {
                    "original_index": i,
                    "requirement": requirement.model_dump(mode="json"),
                    "reference": annotation["labels"][str(i)],
                }
            )
        cases.append(
            {
                "id": row["id"],
                "source": row["source"],
                "source_content_sha256": row["source_content_sha256"],
                "requirements": prepared,
                "excluded": annotation["exclude"],
            }
        )
    return cases


def freeze(spec_path, settings, timeout):
    spec = read_json(spec_path)
    candidate = read_json(spec["candidate_file"])
    evidence = [EvidenceRecord.model_validate(e) for e in candidate["evidence"]]
    if any(e.user_id != candidate["user_id"] for e in evidence):
        raise ValueError("Candidate contains unowned evidence")
    cases = select_cases(spec, read_json(spec["source_dataset"]))
    return {
        "version": "campus-matching-comparison-v1",
        "created_at": datetime.now(UTC).isoformat(),
        "spec": spec,
        "spec_sha256": sha(spec_path),
        "candidate": candidate,
        "candidate_sha256": sha(spec["candidate_file"]),
        "source_dataset_sha256": sha(spec["source_dataset"]),
        "cases": cases,
        "implementation_hashes": {p: sha(p) for p in IMPLEMENTATIONS},
        "configuration": {
            "model": settings.llm_model,
            "provider": settings.structured_model_provider,
            "model_route_sha256": hashlib.sha256(
                (settings.llm_base_url or "default").encode()
            ).hexdigest(),
            "reasoning_effort": settings.llm_reasoning_effort,
            "response_format": settings.llm_response_format,
            "thinking_mode": settings.llm_thinking_mode,
            "prompt_version": PROMPT_VERSION,
            "temperature": 0,
            "request_timeout_seconds": timeout,
            "max_output_tokens_per_call": 7000,
            "max_calls": len(cases),
            "http_retries": 0,
            "validation_retries": 0,
            "cache": "disabled",
            "replicates_per_job": 1,
        },
        "limitations": [
            "Historical development JDs and one synthetic candidate, not a representative random sample of applicants.",
            "Agent-authored provisional references were fixed before inference; no independent human adjudication.",
            "Fixed parsed input isolates matching; parsing quality and end-to-end qualification accuracy are not measured.",
            "One run per job does not measure model stability or production latency distribution.",
            "Raw citation validity is provenance only, not proof of semantic support or explanation faithfulness.",
            "Uncertainty counts are not measured user interruptions or a demonstrated reduction in user effort.",
        ],
    }


def persist(path, report):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def classify_rows(case, matches):
    return [
        {
            "original_index": item["original_index"],
            "reference": item["reference"],
            "match": match.model_dump(mode="json"),
            "within_reference": match.support_level in item["reference"]["allowed"],
        }
        for item, match in zip(case["requirements"], matches, strict=True)
    ]


def citation_stats(raw, evidence, expected_count):
    if raw is None:
        return {
            "raw_citations": 0,
            "valid_raw_citations": 0,
            "raw_schema_valid": False,
            "raw_coverage_valid": False,
        }
    try:
        output = BatchModelOutput.model_validate(raw)
    except ValueError:
        return {
            "raw_citations": 0,
            "valid_raw_citations": 0,
            "raw_schema_valid": False,
            "raw_coverage_valid": False,
        }
    claims = {e.id: " ".join(e.claim.split()) for e in evidence}
    citations = [c for j in output.judgments for c in j.citations]
    return {
        "raw_citations": len(citations),
        "valid_raw_citations": sum(
            c.evidence_id in claims
            and " ".join(c.quote.split()) in claims[c.evidence_id]
            for c in citations
        ),
        "raw_schema_valid": True,
        "raw_coverage_valid": sorted(j.requirement_index for j in output.judgments)
        == list(range(expected_count)),
    }


def summarize(results):
    summary = {}
    for mode in ("local", "model"):
        jobs = [r for r in results if r["mode"] == mode]
        if not jobs:
            continue
        rows = [row for job in jobs for row in job["rows"]]
        strict = [r for r in rows if len(r["reference"]["allowed"]) == 1]
        positive = [r for r in strict if r["reference"]["allowed"] == ["supported"]]
        negative = [r for r in strict if r["reference"]["allowed"] != ["supported"]]
        predicted_full = [
            r for r in strict if r["match"]["support_level"] == "supported"
        ]
        tp = sum(r["match"]["support_level"] == "supported" for r in positive)
        false_full = sum(r["match"]["support_level"] == "supported" for r in negative)
        times = sorted(r["duration_ms"] for r in jobs)
        counts = Counter(r["match"]["support_level"] for r in rows)
        summary[mode] = {
            "jobs": len(jobs),
            "requirements": len(rows),
            "strict_reference_count": len(strict),
            "ambiguous_reference_count": len(rows) - len(strict),
            "strict_agreement_count": sum(r["within_reference"] for r in strict),
            "strict_agreement_rate": sum(r["within_reference"] for r in strict)
            / len(strict)
            if strict
            else None,
            "strict_supported_reference_count": len(positive),
            "recovered_supported": tp,
            "missed_supported": len(positive) - tp,
            "false_full_support": false_full,
            "strict_non_supported_reference_count": len(negative),
            "strict_support_precision": tp / len(predicted_full)
            if predicted_full
            else None,
            "strict_support_recall": tp / len(positive) if positive else None,
            "within_ambiguous_reference_count": sum(
                r["within_reference"]
                for r in rows
                if len(r["reference"]["allowed"]) > 1
            ),
            "outcome_counts": dict(counts),
            "model_calls": sum(r["call_count"] for r in jobs),
            "failed_jobs": sum(bool(r.get("error_code")) for r in jobs),
            "validation_failed_requirements": sum(
                r["match"]["validation_status"] == "failed" for r in rows
            ),
            "median_job_ms": median(times),
            "p95_job_ms": times[math.ceil(0.95 * len(times)) - 1],
            "total_job_ms": round(sum(times), 2),
            "input_tokens": sum(
                (r.get("usage") or {}).get(
                    "prompt_tokens", (r.get("usage") or {}).get("input_tokens", 0)
                )
                for r in jobs
            ),
            "output_tokens": sum(
                (r.get("usage") or {}).get(
                    "completion_tokens", (r.get("usage") or {}).get("output_tokens", 0)
                )
                for r in jobs
            ),
            "usage_available_calls": sum(
                r.get("usage") is not None for r in jobs if r["call_count"]
            ),
            "cost_currency": None,
            "cost_amount": None,
        }
        if mode == "model":
            total = sum(r["citations"]["raw_citations"] for r in jobs)
            valid = sum(r["citations"]["valid_raw_citations"] for r in jobs)
            summary[mode].update(
                raw_citations=total,
                valid_raw_citations=valid,
                raw_citation_validity=valid / total if total else None,
                raw_valid_jobs=sum(
                    r["citations"]["raw_schema_valid"]
                    and r["citations"]["raw_coverage_valid"]
                    for r in jobs
                ),
            )
    if "model" in summary and "local" in summary:
        model, local = summary["model"], summary["local"]
        summary["pilot_gates"] = {
            "zero_false_full_support": model["false_full_support"] == 0,
            "at_least_five_additional_supported": model["recovered_supported"]
            - local["recovered_supported"]
            >= 5,
            "valid_citations_and_coverage": model["raw_citation_validity"] == 1
            and model["raw_valid_jobs"] == model["jobs"]
            and model["validation_failed_requirements"] == 0,
            "p95_within_60_seconds": model["p95_job_ms"] <= 60000,
        }
    return summary


async def run(report, settings, output, total_timeout):
    evidence = [
        EvidenceRecord.model_validate(e) for e in report["candidate"]["evidence"]
    ]
    user = report["candidate"]["user_id"]
    results = []
    deadline = perf_counter() + total_timeout
    for number, case in enumerate(report["cases"]):
        requirements = [
            JobRequirement.model_validate(i["requirement"])
            for i in case["requirements"]
        ]
        # Alternate order; neither strategy consumes the other's output.
        for mode in ("local", "model") if number % 2 == 0 else ("model", "local"):
            if mode == "local":
                started = perf_counter()
                matches = match_requirements_locally(
                    user_id=user, requirements=requirements, evidence=evidence
                )
                row = {
                    "duration_ms": round((perf_counter() - started) * 1000, 2),
                    "call_count": 0,
                }
            else:
                remaining = deadline - perf_counter()
                if remaining <= 0:
                    execution = BatchMatchExecution(
                        matches=[
                            _unknown(r, "total_budget_exhausted") for r in requirements
                        ],
                        error_code="total_budget_exhausted",
                    )
                else:
                    started = perf_counter()
                    try:
                        async with asyncio.timeout(
                            min(remaining, settings.llm_timeout_seconds + 5)
                        ):
                            execution = await BatchEvidenceMatcher(
                                create_structured_model_client(settings)
                            ).match(
                                user_id=user,
                                requirements=requirements,
                                evidence=evidence,
                            )
                    except TimeoutError:
                        execution = BatchMatchExecution(
                            matches=[_unknown(r, "run_timeout") for r in requirements],
                            call_count=1,
                            error_code="run_timeout",
                            duration_ms=round((perf_counter() - started) * 1000, 2),
                        )
                matches = execution.matches
                row = {
                    "call_count": execution.call_count,
                    "duration_ms": execution.duration_ms,
                    "usage": execution.usage,
                    "model": execution.model,
                    "raw_output": execution.raw_output,
                    "error_code": execution.error_code,
                    "validation_issues": execution.validation_issues,
                    "response_metadata": execution.response_metadata,
                    "citations": citation_stats(
                        execution.raw_output, evidence, len(requirements)
                    ),
                }
            results.append(
                {
                    "case_id": case["id"],
                    "mode": mode,
                    **row,
                    "rows": classify_rows(case, matches),
                }
            )
            report["results"] = results
            report["summary"] = summarize(results)
            persist(output, report)
            print(
                json.dumps(
                    {
                        "case": case["id"],
                        "mode": mode,
                        "duration_ms": row["duration_ms"],
                        "error": row.get("error_code"),
                    }
                ),
                flush=True,
            )
    report["completed_at"] = datetime.now(UTC).isoformat()
    report["completed"] = True
    persist(output, report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    parser.add_argument(
        "--manifest",
        type=Path,
        help="Frozen dry-run report required for live execution",
    )
    parser.add_argument("--request-timeout", type=float, default=60)
    parser.add_argument("--total-timeout", type=float, default=600)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Choose a new report path; previous reports are immutable")
    if args.request_timeout <= 0 or args.total_timeout <= 0:
        parser.error("Timeouts must be positive")
    settings = Settings(llm_timeout_seconds=args.request_timeout, llm_max_retries=0)
    report = freeze(args.spec, settings, args.request_timeout)
    report.update(results=[], summary={}, completed=False, live=args.live)
    if args.live:
        if settings.structured_model_provider == "fake" or not args.manifest:
            parser.error(
                "Live execution requires a real configured model and frozen manifest"
            )
        previous = read_json(args.manifest)
        for key in (
            "spec_sha256",
            "candidate_sha256",
            "source_dataset_sha256",
            "configuration",
            "implementation_hashes",
            "cases",
        ):
            if previous[key] != report[key]:
                parser.error(
                    f"Freeze changed: {key}; review and freeze before live calls"
                )
        report["manifest_path"] = str(args.manifest)
        report["manifest_sha256"] = sha(args.manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    persist(args.output, report)
    if args.live:
        asyncio.run(run(report, settings, args.output, args.total_timeout))
        print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    else:
        print(
            json.dumps(
                {
                    "jobs": len(report["cases"]),
                    "requirements": sum(
                        len(c["requirements"]) for c in report["cases"]
                    ),
                    "manifest": str(args.output),
                }
            )
        )


if __name__ == "__main__":
    main()
